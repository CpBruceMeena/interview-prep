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
