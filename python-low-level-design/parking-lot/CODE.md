# Parking Lot — Implementation

> Python implementation of a multi-floor parking lot: best-fit spot allocation, pluggable pricing, a lost-ticket flow, and real thread-safety for a single process.
> The production schema (PostgreSQL + Redis) is in [**DB_SCHEMA.md**](DB_SCHEMA.md); the service view is in [**HIGH_LEVEL_DESIGN.md**](HIGH_LEVEL_DESIGN.md).

---

## 🧭 Walkthrough

### Class map

| Class | Responsibility | Notes |
|-------|----------------|-------|
| `Vehicle` (ABC) → `Motorcycle`, `Car`, `Truck` | Declares the *smallest* spot it fits via `get_required_spot_type()` | Validates a non-empty plate |
| `SpotType.size` | Ordering MOTORCYCLE < COMPACT < LARGE | Drives best-fit |
| `SpotAllocationMapping.get_allowed_spots(vehicle)` | Compatible spot types, smallest first | Derived from `size`, so a new `Vehicle` subclass needs no table entry |
| `ParkingSpot` | Holds the parked vehicle; `park()` / `vacate()` reject illegal transitions | Not thread-safe alone; the lot serialises access |
| `ParkingFloor` | Owns spots + a per-`SpotType` free index (`dict` used as an ordered set) | `occupy()` / `release()` keep the index and spot state in sync |
| `FeeCalculator` (ABC) → `HourlyFeeCalculator`, `DailyFeeCalculator` | Pricing strategy: `calculate_fee(duration: timedelta, spot_type) -> Decimal` | Rounds up to started units, minimum one |
| `ParkingTicket` | `ACTIVE → PAID` or `ACTIVE → LOST`; `close()` refuses a non-ACTIVE ticket | Entry/exit times come from the lot's clock |
| `TicketManager` | Issues `TICK-000001`-style ids and stores tickets | `itertools.count`, only called under the lot lock |
| `DisplayBoard.render(floors)` | Returns the availability text | Pull-based renderer, not an Observer |
| `ParkingLot` | Facade: `park_vehicle`, `unpark_vehicle`, `unpark_lost_ticket`, `set_fee_calculator`, `available_count`, `show_available_spots` | Owns the one lock and the plate → active-ticket index |
| `ManualClock` | Injectable deterministic clock | Used by the demo and tests instead of `sleep()` |

### Key design decisions

1. **Best fit, not first fit.** `_find_spot_locked` iterates spot types smallest-first, and floors lowest-first inside each type. A car takes a COMPACT spot on floor 2 before a LARGE spot on floor 1, because LARGE spots are the scarce resource (only trucks can use them). If the business prefers "nearest floor first", swap the two loops; that is the one-line change an interviewer often asks for.
2. **Free-spot index per floor.** Allocation is O(floors × spot types), not O(total spots). The `dict`-as-ordered-set gives O(1) add/remove and a stable "first free" pick.
3. **One lock around check-then-act.** `park_vehicle` does duplicate-plate check → find spot → occupy → issue ticket inside a single `threading.Lock`. Without it, two threads can both see the same spot free. Unpark takes the same lock, so two exits racing on one ticket charge exactly once (the second gets `InvalidTicketError`). The critical section is a handful of dict operations, so a coarse lock is cheaper than it looks; finer-grained locks (per floor / per spot type) only pay off at contention levels a single lot never sees.
4. **Exceptions, not `None` + `print`.** `ParkingFullError`, `VehicleAlreadyParkedError`, `InvalidTicketError` (all subclasses of `ParkingError`). Domain code never prints; the demo does.
5. **`Decimal` money, injected clock.** Fees are `Decimal` so `0.1 + 0.2` problems cannot reach a receipt. `clock` defaults to `datetime.now` but tests pass a `ManualClock`, which makes the "2 h 10 m → 3 billable hours" case a fast, exact assertion.
6. **Strategy swap is applied at close time.** `set_fee_calculator` affects every ticket closed afterwards, including ones opened under the old pricing. In production you would instead stamp the rate card id on the ticket at entry (see DB_SCHEMA `rate_card`).

### Where to extend

| Interviewer asks for | Change |
|----------------------|--------|
| EV spots / charging | Add `SpotType.EV`; give `SpotAllocationMapping` a rule (EVs prefer EV spots, non-EVs never use them). This is why the mapping is its own class. |
| Reservations | A `Reservation` holding a spot id + time window; mark the spot unavailable in the floor index while reserved. |
| Grace period, tax, surge | Decorators over `FeeCalculator` (`GracePeriodFee(inner, minutes=15)`). |
| Nearest-to-entrance allocation | Replace `_find_spot_locked` with an `AllocationStrategy` interface; keep the lock in `ParkingLot`. |
| Multiple processes / gates | The in-memory lock no longer helps: move the "claim a spot" step into the DB (`FOR UPDATE SKIP LOCKED` or a conditional `UPDATE`), see HIGH_LEVEL_DESIGN. |

---

## 📦 Source

<!-- source: parking_lot.py -->
```python
"""
Parking Lot System - Low Level Design
-------------------------------------
In-memory, thread-safe parking lot for a single process.

Key decisions:
  - Vehicle hierarchy (ABC): each vehicle declares the *smallest* spot it fits.
  - Best-fit allocation: smallest compatible spot type first, then lowest floor,
    so a car never takes a LARGE spot while COMPACT spots are free.
  - Each floor keeps a free-spot index per SpotType, so allocation is
    O(floors x spot_types) instead of a scan over every spot.
  - One lock in ParkingLot guards the whole "find spot -> occupy -> issue ticket"
    sequence. That removes the check-then-act race; the critical section is a
    few dict operations, so a coarse lock is the right first answer.
  - Money is Decimal, never float. Time comes from an injectable clock so fees
    are testable without sleeping.
  - Pricing is a Strategy (FeeCalculator) that can be swapped at runtime.

Production schema (PostgreSQL + Redis) lives in DB_SCHEMA.md / HIGH_LEVEL_DESIGN.md.
"""

from __future__ import annotations

import itertools
import math
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Type


# --- Enums ---

class VehicleType(Enum):
    MOTORCYCLE = "Motorcycle"
    CAR = "Car"
    TRUCK = "Truck"


class SpotType(Enum):
    MOTORCYCLE = "Motorcycle"
    COMPACT = "Compact"
    LARGE = "Large"

    @property
    def size(self) -> int:
        """Ordering used for best-fit: a vehicle fits any spot of >= size."""
        return _SPOT_SIZE[self]


_SPOT_SIZE = {SpotType.MOTORCYCLE: 1, SpotType.COMPACT: 2, SpotType.LARGE: 3}


class ParkingTicketStatus(Enum):
    ACTIVE = "Active"
    PAID = "Paid"
    LOST = "Lost"   # closed via the lost-ticket flow (penalty charged)


# --- Exceptions ---

class ParkingError(Exception):
    """Base class for domain errors raised by the parking lot."""


class ParkingFullError(ParkingError):
    pass


class VehicleAlreadyParkedError(ParkingError):
    pass


class InvalidTicketError(ParkingError):
    pass


# --- Vehicle Hierarchy (LSP) ---

class Vehicle(ABC):
    """Base vehicle. Subclasses only declare the smallest spot they fit."""

    def __init__(self, license_plate: str, vehicle_type: VehicleType):
        if not license_plate:
            raise ValueError("license_plate is required")
        self._license_plate = license_plate
        self._vehicle_type = vehicle_type

    @property
    def license_plate(self) -> str:
        return self._license_plate

    @property
    def vehicle_type(self) -> VehicleType:
        return self._vehicle_type

    @abstractmethod
    def get_required_spot_type(self) -> SpotType:
        """The smallest spot type this vehicle fits in."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._license_plate!r})"


class Motorcycle(Vehicle):
    def __init__(self, license_plate: str):
        super().__init__(license_plate, VehicleType.MOTORCYCLE)

    def get_required_spot_type(self) -> SpotType:
        return SpotType.MOTORCYCLE


class Car(Vehicle):
    def __init__(self, license_plate: str):
        super().__init__(license_plate, VehicleType.CAR)

    def get_required_spot_type(self) -> SpotType:
        return SpotType.COMPACT


class Truck(Vehicle):
    def __init__(self, license_plate: str):
        super().__init__(license_plate, VehicleType.TRUCK)

    def get_required_spot_type(self) -> SpotType:
        return SpotType.LARGE


# --- Factory Pattern ---

class VehicleFactory:
    """Creates vehicles from a type tag (e.g. what an ANPR camera reports)."""

    _vehicle_map: Dict[VehicleType, Type[Vehicle]] = {
        VehicleType.MOTORCYCLE: Motorcycle,
        VehicleType.CAR: Car,
        VehicleType.TRUCK: Truck,
    }

    @classmethod
    def create_vehicle(cls, vehicle_type: VehicleType, license_plate: str) -> Vehicle:
        vehicle_class = cls._vehicle_map.get(vehicle_type)
        if vehicle_class is None:
            raise ValueError(f"Unsupported vehicle type: {vehicle_type}")
        return vehicle_class(license_plate)

    @classmethod
    def register_vehicle_type(cls, vehicle_type: VehicleType,
                              vehicle_class: Type[Vehicle]) -> None:
        cls._vehicle_map[vehicle_type] = vehicle_class


# --- Spot Mapping (SRP) ---

class SpotAllocationMapping:
    """Which spot types a vehicle may use, in best-fit order (smallest first).

    Derived from Vehicle.get_required_spot_type() + SpotType.size, so a new
    Vehicle subclass needs no entry here. If the business wants a different
    rule (e.g. trucks may never use COMPACT, EVs only on EV spots), this is the
    single place to change.
    """

    @staticmethod
    def get_allowed_spots(vehicle: Vehicle) -> Tuple[SpotType, ...]:
        required = vehicle.get_required_spot_type().size
        return tuple(sorted((t for t in SpotType if t.size >= required),
                            key=lambda t: t.size))


# --- Spot (SRP) ---

class ParkingSpot:
    """One physical spot. Not thread-safe on its own: ParkingLot serialises access."""

    def __init__(self, spot_id: str, floor: int, spot_type: SpotType):
        self._spot_id = spot_id
        self._floor = floor
        self._spot_type = spot_type
        self._parked_vehicle: Optional[Vehicle] = None

    @property
    def spot_id(self) -> str:
        return self._spot_id

    @property
    def floor(self) -> int:
        return self._floor

    @property
    def spot_type(self) -> SpotType:
        return self._spot_type

    @property
    def is_available(self) -> bool:
        return self._parked_vehicle is None

    @property
    def parked_vehicle(self) -> Optional[Vehicle]:
        return self._parked_vehicle

    def park(self, vehicle: Vehicle) -> None:
        if self._parked_vehicle is not None:
            raise ValueError(f"Spot {self._spot_id} is already occupied")
        self._parked_vehicle = vehicle

    def vacate(self) -> Vehicle:
        if self._parked_vehicle is None:
            raise ValueError(f"Spot {self._spot_id} is already vacant")
        vehicle, self._parked_vehicle = self._parked_vehicle, None
        return vehicle


# --- Floor (SRP / Composition) ---

class ParkingFloor:
    """Owns a floor's spots plus a per-type index of free spots.

    The index is a dict used as an insertion-ordered set: O(1) add/remove,
    O(1) "give me any free COMPACT spot".
    """

    def __init__(self, floor_number: int):
        self._floor_number = floor_number
        self._spots: Dict[str, ParkingSpot] = {}
        self._free: Dict[SpotType, Dict[str, ParkingSpot]] = {t: {} for t in SpotType}

    @property
    def floor_number(self) -> int:
        return self._floor_number

    def add_spot(self, spot: ParkingSpot) -> None:
        if spot.spot_id in self._spots:
            raise ValueError(f"Duplicate spot id {spot.spot_id}")
        if spot.floor != self._floor_number:
            raise ValueError(f"Spot {spot.spot_id} belongs to floor {spot.floor}")
        self._spots[spot.spot_id] = spot
        if spot.is_available:
            self._free[spot.spot_type][spot.spot_id] = spot

    def find_spot(self, spot_id: str) -> Optional[ParkingSpot]:
        return self._spots.get(spot_id)

    def get_available_spots(self, spot_type: Optional[SpotType] = None) -> List[ParkingSpot]:
        if spot_type is not None:
            return list(self._free[spot_type].values())
        return [s for t in SpotType for s in self._free[t].values()]

    def available_count(self, spot_type: SpotType) -> int:
        return len(self._free[spot_type])

    def first_free(self, spot_type: SpotType) -> Optional[ParkingSpot]:
        return next(iter(self._free[spot_type].values()), None)

    def occupy(self, spot: ParkingSpot, vehicle: Vehicle) -> None:
        spot.park(vehicle)
        del self._free[spot.spot_type][spot.spot_id]

    def release(self, spot: ParkingSpot) -> Vehicle:
        vehicle = spot.vacate()
        self._free[spot.spot_type][spot.spot_id] = spot
        return vehicle


# --- Fee Calculation (Strategy Pattern - OCP/DIP) ---

class FeeCalculator(ABC):
    """Pricing strategy. Pure function of duration and spot type."""

    @abstractmethod
    def calculate_fee(self, duration: timedelta, spot_type: SpotType) -> Decimal:
        ...


def _ceil_units(duration: timedelta, unit: timedelta) -> int:
    """Whole billing units, rounded up, minimum 1."""
    return max(1, math.ceil(duration / unit))


class HourlyFeeCalculator(FeeCalculator):
    """Per started hour (minimum one hour)."""

    _rates = {
        SpotType.MOTORCYCLE: Decimal("10.00"),
        SpotType.COMPACT: Decimal("20.00"),
        SpotType.LARGE: Decimal("30.00"),
    }

    def calculate_fee(self, duration: timedelta, spot_type: SpotType) -> Decimal:
        return self._rates[spot_type] * _ceil_units(duration, timedelta(hours=1))


class DailyFeeCalculator(FeeCalculator):
    """Per started 24h day (minimum one day)."""

    _daily_rates = {
        SpotType.MOTORCYCLE: Decimal("50.00"),
        SpotType.COMPACT: Decimal("100.00"),
        SpotType.LARGE: Decimal("150.00"),
    }

    def calculate_fee(self, duration: timedelta, spot_type: SpotType) -> Decimal:
        return self._daily_rates[spot_type] * _ceil_units(duration, timedelta(days=1))


# --- Ticket ---

class ParkingTicket:
    """A ticket's lifecycle: ACTIVE -> PAID, or ACTIVE -> LOST. Terminal states are final."""

    def __init__(self, ticket_id: str, spot: ParkingSpot, vehicle: Vehicle,
                 entry_time: datetime):
        self._ticket_id = ticket_id
        self._spot = spot
        self._vehicle = vehicle
        self._entry_time = entry_time
        self._exit_time: Optional[datetime] = None
        self._fee: Optional[Decimal] = None
        self._status = ParkingTicketStatus.ACTIVE

    @property
    def ticket_id(self) -> str:
        return self._ticket_id

    @property
    def spot(self) -> ParkingSpot:
        return self._spot

    @property
    def vehicle(self) -> Vehicle:
        return self._vehicle

    @property
    def entry_time(self) -> datetime:
        return self._entry_time

    @property
    def exit_time(self) -> Optional[datetime]:
        return self._exit_time

    @property
    def fee(self) -> Optional[Decimal]:
        return self._fee

    @property
    def status(self) -> ParkingTicketStatus:
        return self._status

    def close(self, exit_time: datetime, fee_calculator: FeeCalculator,
              penalty: Decimal = Decimal("0"),
              status: ParkingTicketStatus = ParkingTicketStatus.PAID) -> Decimal:
        if self._status is not ParkingTicketStatus.ACTIVE:
            raise InvalidTicketError(f"Ticket {self._ticket_id} is already {self._status.value}")
        if status is ParkingTicketStatus.ACTIVE:
            raise ValueError("close() must move the ticket to a terminal state")
        duration = max(exit_time - self._entry_time, timedelta(0))  # clock skew guard
        self._fee = fee_calculator.calculate_fee(duration, self._spot.spot_type) + penalty
        self._exit_time = exit_time
        self._status = status
        return self._fee


# --- Ticket Manager (SRP) ---

class TicketManager:
    """Issues ticket ids and stores tickets. Called only under ParkingLot's lock."""

    def __init__(self):
        self._tickets: Dict[str, ParkingTicket] = {}
        self._ids = itertools.count(1)

    def create_ticket(self, spot: ParkingSpot, vehicle: Vehicle,
                      entry_time: datetime) -> ParkingTicket:
        ticket_id = f"TICK-{next(self._ids):06d}"
        ticket = ParkingTicket(ticket_id, spot, vehicle, entry_time)
        self._tickets[ticket_id] = ticket
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[ParkingTicket]:
        return self._tickets.get(ticket_id)


# --- Display Board (SRP) ---

class DisplayBoard:
    """Renders availability. Pull-based: it reads counts on demand."""

    @staticmethod
    def render(floors: List[ParkingFloor]) -> str:
        lines = ["=== Available Spots ==="]
        for floor in floors:
            total = sum(floor.available_count(t) for t in SpotType)
            lines.append(f"Floor {floor.floor_number}: {total} spots available")
            for spot_type in SpotType:
                lines.append(f"  {spot_type.value}: {floor.available_count(spot_type)}")
        return "\n".join(lines)


# --- Main Parking Lot (Facade) ---

class ParkingLot:
    """Facade and the single point of synchronisation.

    Invariants (hold whenever the lock is free):
      - a spot is in its floor's free index  <=>  spot.is_available
      - a plate is in _active_by_plate        <=>  it has exactly one ACTIVE ticket
    """

    LOST_TICKET_PENALTY = Decimal("50.00")

    def __init__(self, name: str, fee_calculator: FeeCalculator,
                 clock: Callable[[], datetime] = datetime.now):
        self._name = name
        self._floors: List[ParkingFloor] = []
        self._floor_by_number: Dict[int, ParkingFloor] = {}
        self._ticket_manager = TicketManager()
        self._fee_calculator = fee_calculator
        self._clock = clock
        self._active_by_plate: Dict[str, ParkingTicket] = {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    def add_floor(self, floor: ParkingFloor) -> None:
        with self._lock:
            if floor.floor_number in self._floor_by_number:
                raise ValueError(f"Floor {floor.floor_number} already exists")
            self._floors.append(floor)
            self._floors.sort(key=lambda f: f.floor_number)  # lowest floor fills first
            self._floor_by_number[floor.floor_number] = floor

    def find_available_spot(self, vehicle: Vehicle) -> Optional[ParkingSpot]:
        """Best fit: smallest compatible spot type, then lowest floor.

        Read-only. Callers that intend to park must go through park_vehicle(),
        which repeats the search under the lock.
        """
        with self._lock:
            return self._find_spot_locked(vehicle)

    def _find_spot_locked(self, vehicle: Vehicle) -> Optional[ParkingSpot]:
        for spot_type in SpotAllocationMapping.get_allowed_spots(vehicle):
            for floor in self._floors:
                spot = floor.first_free(spot_type)
                if spot is not None:
                    return spot
        return None

    def park_vehicle(self, vehicle: Vehicle) -> ParkingTicket:
        with self._lock:
            if vehicle.license_plate in self._active_by_plate:
                raise VehicleAlreadyParkedError(f"{vehicle.license_plate} is already parked")
            spot = self._find_spot_locked(vehicle)
            if spot is None:
                raise ParkingFullError(f"No available spot for {vehicle.license_plate}")
            self._floor_by_number[spot.floor].occupy(spot, vehicle)
            ticket = self._ticket_manager.create_ticket(spot, vehicle, self._clock())
            self._active_by_plate[vehicle.license_plate] = ticket
            return ticket

    def unpark_vehicle(self, ticket_id: str) -> Decimal:
        """Close the ticket, free the spot, return the fee. Not idempotent:
        a second call for the same ticket raises InvalidTicketError."""
        with self._lock:
            ticket = self._ticket_manager.get_ticket(ticket_id)
            if ticket is None:
                raise InvalidTicketError(f"Unknown ticket {ticket_id}")
            return self._close_locked(ticket, Decimal("0"), ParkingTicketStatus.PAID)

    def unpark_lost_ticket(self, license_plate: str) -> Decimal:
        """Lost-ticket flow: find the session by plate, charge fee + penalty."""
        with self._lock:
            ticket = self._active_by_plate.get(license_plate)
            if ticket is None:
                raise InvalidTicketError(f"No active ticket for {license_plate}")
            return self._close_locked(ticket, self.LOST_TICKET_PENALTY,
                                      ParkingTicketStatus.LOST)

    def _close_locked(self, ticket: ParkingTicket, penalty: Decimal,
                      status: ParkingTicketStatus) -> Decimal:
        # close() validates state first, so a failed close leaves everything untouched.
        fee = ticket.close(self._clock(), self._fee_calculator, penalty, status)
        self._floor_by_number[ticket.spot.floor].release(ticket.spot)
        del self._active_by_plate[ticket.vehicle.license_plate]
        return fee

    def get_ticket(self, ticket_id: str) -> Optional[ParkingTicket]:
        with self._lock:
            return self._ticket_manager.get_ticket(ticket_id)

    def available_count(self, spot_type: Optional[SpotType] = None) -> int:
        with self._lock:
            types = [spot_type] if spot_type else list(SpotType)
            return sum(f.available_count(t) for f in self._floors for t in types)

    def show_available_spots(self) -> str:
        with self._lock:
            return DisplayBoard.render(self._floors)

    def set_fee_calculator(self, fee_calculator: FeeCalculator) -> None:
        """Swap pricing at runtime. Applies to tickets closed after the swap."""
        with self._lock:
            self._fee_calculator = fee_calculator


# --- Demo ---

def setup_parking_lot(clock: Callable[[], datetime] = datetime.now) -> ParkingLot:
    lot = ParkingLot("Downtown Parking", HourlyFeeCalculator(), clock=clock)

    floor1 = ParkingFloor(1)
    for i in range(10):
        floor1.add_spot(ParkingSpot(f"A{i+1:02d}", 1, SpotType.MOTORCYCLE))
    for i in range(20):
        floor1.add_spot(ParkingSpot(f"B{i+1:02d}", 1, SpotType.COMPACT))
    for i in range(10):
        floor1.add_spot(ParkingSpot(f"C{i+1:02d}", 1, SpotType.LARGE))
    lot.add_floor(floor1)

    floor2 = ParkingFloor(2)
    for i in range(15):
        floor2.add_spot(ParkingSpot(f"D{i+1:02d}", 2, SpotType.COMPACT))
    for i in range(10):
        floor2.add_spot(ParkingSpot(f"E{i+1:02d}", 2, SpotType.LARGE))
    lot.add_floor(floor2)

    return lot


class ManualClock:
    """Deterministic clock for demos and tests."""

    def __init__(self, start: datetime):
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)


def main() -> None:
    clock = ManualClock(datetime(2025, 1, 1, 9, 0))
    lot = setup_parking_lot(clock)
    print(lot.show_available_spots())

    car = VehicleFactory.create_vehicle(VehicleType.CAR, "ABC-1234")
    bike = VehicleFactory.create_vehicle(VehicleType.MOTORCYCLE, "BIKE-001")
    truck = VehicleFactory.create_vehicle(VehicleType.TRUCK, "TRK-9999")

    tickets = {}
    for v in (car, bike, truck):
        t = lot.park_vehicle(v)
        tickets[v.license_plate] = t
        print(f"{v} -> {t.spot.spot_id} (floor {t.spot.floor}), ticket {t.ticket_id}")

    try:
        lot.park_vehicle(Car("ABC-1234"))
    except VehicleAlreadyParkedError as e:
        print(f"Rejected: {e}")

    print(lot.show_available_spots())

    clock.advance(hours=2, minutes=10)       # 2h10m -> 3 started hours
    fee = lot.unpark_vehicle(tickets["ABC-1234"].ticket_id)
    print(f"ABC-1234 paid ${fee}")

    try:
        lot.unpark_vehicle(tickets["ABC-1234"].ticket_id)
    except InvalidTicketError as e:
        print(f"Rejected: {e}")

    clock.advance(minutes=20)
    fee = lot.unpark_lost_ticket("BIKE-001")
    print(f"BIKE-001 lost ticket, paid ${fee}")

    lot.set_fee_calculator(DailyFeeCalculator())
    clock.advance(days=1)
    fee = lot.unpark_vehicle(tickets["TRK-9999"].ticket_id)
    print(f"TRK-9999 paid ${fee} (daily pricing)")

    print(lot.show_available_spots())


if __name__ == "__main__":
    main()
```
<!-- /source -->

---

## ▶️ How to Run

```bash
cd python-low-level-design/parking-lot
python3 parking_lot.py                      # deterministic demo
python3 -m unittest test_parking_lot -v      # tests, including a 100-thread contention test
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | `FeeCalculator` | Interchangeable pricing, swappable at runtime |
| **Factory** | `VehicleFactory` | Build a `Vehicle` from a type tag (e.g. what an ANPR camera reports) |
| **Facade** | `ParkingLot` | One entry point that also owns synchronisation |
| **Template / polymorphism** | `Vehicle.get_required_spot_type()` | No `if vehicle_type == ...` chains |

Not used, despite appearing in many write-ups: **Singleton** (`ParkingLot` is a normal class; a singleton would make tests share state), **Observer** (the display board pulls counts; add listeners only when there are several subscribers), **State pattern** (ticket status is a two-transition enum, a full State class hierarchy would be overkill).
