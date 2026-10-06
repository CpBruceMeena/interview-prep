"""
Car Rental Platform - Low Level Design
--------------------------------------
We own the fleet. Customers search by time range, place a short HOLD on a
vehicle while they pay, then confirm. The core problems are:

  * When is a car free?  Each vehicle has a schedule of non-overlapping,
    half-open [start, end) blocks (reservations, holds, maintenance). That
    interval set is the source of truth, exactly like a Postgres
    `EXCLUDE USING gist (vehicle_id WITH =, tstzrange(...) WITH &&)`.
    Hourly / weekly views are projections computed from it.
  * No double booking.  "Check overlap + insert" is one atomic step under
    the vehicle's own lock (try_block). Search results are only a hint.
  * Reservation lifecycle.  PENDING (hold with expiry) -> CONFIRMED ->
    IN_PROGRESS -> COMPLETED, with CANCELLED / EXPIRED exits, enforced by a
    transition table under the reservation's lock.

Lock order: reservation -> vehicle schedule (schedule locks are leaves).
Money is Decimal. Time comes from an injectable clock. Stdlib only, 3.10+.
"""

from __future__ import annotations

import bisect
import itertools
import math
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Callable, Dict, List, Optional, Set

HOUR = timedelta(hours=1)
MONEY = Decimal("0.01")


def to_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def billable_hours(start: datetime, end: datetime) -> int:
    """Every started hour is billed; minimum one hour."""
    return max(1, math.ceil((end - start) / HOUR))


# ============================================================
# Enums and errors
# ============================================================

class VehicleType(Enum):
    HATCHBACK = "Hatchback"
    SEDAN = "Sedan"
    SUV = "SUV"
    LUXURY = "Luxury"
    VAN = "Van"


class FuelType(Enum):
    PETROL = "Petrol"
    DIESEL = "Diesel"
    ELECTRIC = "Electric"
    HYBRID = "Hybrid"


class VehicleStatus(Enum):
    """Physical state right now. Future bookings live in the calendar, not here."""
    AVAILABLE = "Available"   # on the lot
    RENTED = "Rented"         # out with a customer


class ReservationStatus(Enum):
    PENDING = "Pending"            # hold placed, awaiting payment, expires
    CONFIRMED = "Confirmed"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"            # hold timed out before confirmation


class BlockKind(Enum):
    RESERVATION = "Reservation"
    MAINTENANCE = "Maintenance"


class RentalError(Exception):
    pass


class NotFoundError(RentalError):
    pass


class InvalidRequestError(RentalError):
    pass


class InvalidTransitionError(RentalError):
    pass


class HoldExpiredError(RentalError):
    pass


class VehicleUnavailableError(RentalError):
    def __init__(self, message: str, next_free: Optional[datetime] = None):
        super().__init__(message)
        self.next_free = next_free


# ============================================================
# Fleet and customers
# ============================================================

@dataclass(eq=False)
class Vehicle:
    vehicle_id: str
    vehicle_type: VehicleType
    make: str
    model: str
    year: int
    license_plate: str
    fuel_type: FuelType
    hourly_rate: Decimal
    daily_rate: Decimal
    location: str
    seats: int = 5
    status: VehicleStatus = VehicleStatus.AVAILABLE

    def __str__(self) -> str:
        return f"{self.year} {self.make} {self.model} ({self.license_plate})"


@dataclass(eq=False)
class Customer:
    customer_id: str
    name: str
    email: str
    license_number: str
    loyalty_points: int = 0


# ============================================================
# Pricing (Strategy + Decorator)
# ============================================================

class RentalPricing(ABC):
    @abstractmethod
    def calculate_cost(self, vehicle: Vehicle, hours: int) -> Decimal:
        ...


class HourlyRentalPricing(RentalPricing):
    """Hourly, but each 24h block is capped at the daily rate."""

    def calculate_cost(self, vehicle: Vehicle, hours: int) -> Decimal:
        full_days, rest = divmod(hours, 24)
        return to_money(vehicle.daily_rate * full_days
                        + min(vehicle.hourly_rate * rest, vehicle.daily_rate))


class DailyRentalPricing(RentalPricing):
    """Any started day is a full day."""

    def calculate_cost(self, vehicle: Vehicle, hours: int) -> Decimal:
        return to_money(vehicle.daily_rate * math.ceil(hours / 24))


class WeeklyDiscountPricing(RentalPricing):
    """Decorator: 10% off for 7+ days, a further 15% off for 30+ days."""

    def __init__(self, base: RentalPricing):
        self._base = base

    def calculate_cost(self, vehicle: Vehicle, hours: int) -> Decimal:
        cost = self._base.calculate_cost(vehicle, hours)
        if hours >= 7 * 24:
            cost *= Decimal("0.90")
        if hours >= 30 * 24:
            cost *= Decimal("0.85")
        return to_money(cost)


# ============================================================
# Availability: per-vehicle interval schedule (source of truth)
# ============================================================

@dataclass
class Block:
    start: datetime
    end: datetime                       # exclusive
    kind: BlockKind
    ref_id: str
    expires_at: Optional[datetime] = None   # set for unconfirmed holds

    def live(self, now: datetime) -> bool:
        return self.expires_at is None or now < self.expires_at


class VehicleSchedule:
    """
    Non-overlapping blocks sorted by start. Because they never overlap, their
    ends are sorted too, so "does [s, e) overlap anything?" is one bisect:
    find the first block whose end > s; conflict iff that block starts < e.
    Expired holds are dropped lazily before every read or write.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._blocks: List[Block] = []

    # All methods below require self.lock to be held by the caller.
    def purge_expired(self, now: datetime) -> None:
        if any(not b.live(now) for b in self._blocks):
            self._blocks = [b for b in self._blocks if b.live(now)]

    def conflict(self, start: datetime, end: datetime) -> Optional[Block]:
        i = bisect.bisect_right(self._blocks, start, key=lambda b: b.end)
        if i < len(self._blocks) and self._blocks[i].start < end:
            return self._blocks[i]
        return None

    def insert(self, block: Block) -> None:
        bisect.insort(self._blocks, block, key=lambda b: b.start)

    def find(self, ref_id: str) -> Optional[Block]:
        return next((b for b in self._blocks if b.ref_id == ref_id), None)

    def remove(self, ref_id: str) -> None:
        self._blocks = [b for b in self._blocks if b.ref_id != ref_id]

    def blocks(self) -> List[Block]:
        return list(self._blocks)


class AvailabilityCalendar:
    """
    Every reservation also blocks a turnaround buffer after the return time
    (cleaning, inspection), so back-to-back bookings leave room to turn the car.
    """

    def __init__(self, clock: Callable[[], datetime],
                 turnaround: timedelta = timedelta(0), lookahead_days: int = 7):
        self._clock = clock
        self._turnaround = turnaround
        self._lookahead_days = lookahead_days
        self._lock = threading.Lock()
        self._schedules: Dict[str, VehicleSchedule] = {}

    def add_vehicle(self, vehicle_id: str) -> None:
        with self._lock:
            self._schedules.setdefault(vehicle_id, VehicleSchedule())

    def _schedule(self, vehicle_id: str) -> VehicleSchedule:
        with self._lock:
            sched = self._schedules.get(vehicle_id)
        if sched is None:
            raise NotFoundError(f"vehicle {vehicle_id}")
        return sched

    def _span(self, kind: BlockKind, start: datetime, end: datetime) -> tuple[datetime, datetime]:
        return (start, end + self._turnaround) if kind is BlockKind.RESERVATION else (start, end)

    # ---- writes (atomic per vehicle) ----

    def try_block(self, vehicle_id: str, start: datetime, end: datetime, kind: BlockKind,
                  ref_id: str, expires_at: Optional[datetime] = None) -> bool:
        """Check-and-insert as ONE step under the vehicle's lock. False = overlaps something."""
        s, e = self._span(kind, start, end)
        sched = self._schedule(vehicle_id)
        with sched.lock:
            sched.purge_expired(self._clock())
            if sched.conflict(s, e) is not None:
                return False
            sched.insert(Block(s, e, kind, ref_id, expires_at))
            return True

    def confirm_hold(self, vehicle_id: str, ref_id: str) -> bool:
        """Make a hold permanent. False if it already expired (and was possibly re-booked)."""
        sched = self._schedule(vehicle_id)
        with sched.lock:
            sched.purge_expired(self._clock())
            block = sched.find(ref_id)
            if block is None:
                return False
            block.expires_at = None
            return True

    def release(self, vehicle_id: str, ref_id: str) -> None:
        sched = self._schedule(vehicle_id)
        with sched.lock:
            sched.remove(ref_id)

    # ---- reads ----

    def is_available(self, vehicle_id: str, pickup: datetime, dropoff: datetime) -> bool:
        """Could a reservation for [pickup, dropoff) (plus turnaround) be placed right now?"""
        s, e = self._span(BlockKind.RESERVATION, pickup, dropoff)
        return self._is_free(vehicle_id, s, e)

    def _is_free(self, vehicle_id: str, start: datetime, end: datetime) -> bool:
        sched = self._schedule(vehicle_id)
        with sched.lock:
            sched.purge_expired(self._clock())
            return sched.conflict(start, end) is None

    def get_available_vehicles(self, vehicle_ids: List[str], pickup: datetime,
                               dropoff: datetime) -> List[str]:
        return [v for v in vehicle_ids if self.is_available(v, pickup, dropoff)]

    def next_free_window(self, vehicle_id: str, pickup: datetime, dropoff: datetime) -> datetime:
        """Earliest start >= pickup at which a booking of the same length fits. O(n) walk of the gaps."""
        length = dropoff - pickup + self._turnaround
        sched = self._schedule(vehicle_id)
        with sched.lock:
            sched.purge_expired(self._clock())
            candidate = pickup
            for b in sched.blocks():
                if b.end <= candidate:
                    continue
                if b.start >= candidate + length:
                    break
                candidate = b.end
            return candidate

    def free_hours(self, vehicle_id: str, day: date) -> List[int]:
        """Hours h whose whole slot [h:00, h+1:00) is free (bookings may start/end mid-hour)."""
        midnight = datetime.combine(day, time())
        return [h for h in range(24)
                if self._is_free(vehicle_id, midnight + h * HOUR, midnight + (h + 1) * HOUR)]

    def get_availability_summary(self, vehicle_id: str, day: date) -> dict:
        free = self.free_hours(vehicle_id, day)
        return {"date": day.isoformat(), "available": free,
                "booked": [h for h in range(24) if h not in free],
                "total_available_hours": len(free)}

    def get_weekly_availability(self, vehicle_id: str, start_date: date) -> dict:
        days = []
        for offset in range(self._lookahead_days):
            d = start_date + timedelta(days=offset)
            free = self.free_hours(vehicle_id, d)
            days.append({"date": d.isoformat(), "day_name": d.strftime("%a"),
                         "available_hours": free, "total_available": len(free),
                         "is_fully_booked": not free})
        return {"vehicle_id": vehicle_id, "week_start": start_date.isoformat(), "days": days}

    def weekly_bitmap(self, vehicle_id: str, start_date: date) -> int:
        """lookahead x 24-bit mask, bit (day*24 + hour) = 1 if that hour is free. 168 bits = 21 bytes/week."""
        bits = 0
        for offset in range(self._lookahead_days):
            for h in self.free_hours(vehicle_id, start_date + timedelta(days=offset)):
                bits |= 1 << (offset * 24 + h)
        return bits


# ============================================================
# Reservation: the state machine
# ============================================================

_TRANSITIONS: Dict[ReservationStatus, Set[ReservationStatus]] = {
    ReservationStatus.PENDING: {ReservationStatus.CONFIRMED, ReservationStatus.CANCELLED,
                                ReservationStatus.EXPIRED},
    ReservationStatus.CONFIRMED: {ReservationStatus.IN_PROGRESS, ReservationStatus.CANCELLED},
    ReservationStatus.IN_PROGRESS: {ReservationStatus.COMPLETED},
    ReservationStatus.COMPLETED: set(),
    ReservationStatus.CANCELLED: set(),
    ReservationStatus.EXPIRED: set(),
}


@dataclass(eq=False)
class Reservation:
    reservation_id: str
    customer: Customer
    vehicle: Vehicle
    pickup: datetime
    dropoff: datetime
    pickup_location: str
    dropoff_location: str
    pricing: RentalPricing
    quoted_amount: Decimal
    hold_expires_at: datetime
    status: ReservationStatus = ReservationStatus.PENDING
    final_amount: Optional[Decimal] = None
    returned_at: Optional[datetime] = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def move_to(self, target: ReservationStatus) -> None:
        """Caller holds self.lock."""
        if target not in _TRANSITIONS[self.status]:
            raise InvalidTransitionError(f"{self.reservation_id}: {self.status.name} -> {target.name}")
        self.status = target

    @property
    def duration_hours(self) -> int:
        return billable_hours(self.pickup, self.dropoff)

    def __str__(self) -> str:
        return (f"Reservation[{self.reservation_id}] {self.customer.name} - {self.vehicle.make} "
                f"{self.vehicle.model} {self.pickup:%a %d %H:%M} -> {self.dropoff:%a %d %H:%M} "
                f"{self.status.name} {self.quoted_amount}")


# ============================================================
# Search (read side: results are a hint, booking re-checks atomically)
# ============================================================

class SearchService:
    def __init__(self, vehicles: Callable[[], List[Vehicle]], calendar: AvailabilityCalendar):
        self._vehicles = vehicles
        self._calendar = calendar

    def _matching(self, vehicle_type: Optional[VehicleType], location: Optional[str]) -> List[Vehicle]:
        return [v for v in self._vehicles()
                if (vehicle_type is None or v.vehicle_type is vehicle_type)
                and (location is None or v.location == location)]

    def search_available(self, pickup: datetime, dropoff: datetime,
                         vehicle_type: Optional[VehicleType] = None,
                         location: Optional[str] = None) -> List[Vehicle]:
        """Vehicles free for the whole range, cheapest hourly rate first."""
        found = [v for v in self._matching(vehicle_type, location)
                 if self._calendar.is_available(v.vehicle_id, pickup, dropoff)]
        return sorted(found, key=lambda v: (v.hourly_rate, v.vehicle_id))

    def search_by_date(self, day: date, vehicle_type: Optional[VehicleType] = None) -> dict:
        results = [{"vehicle": v, "availability": self._calendar.get_availability_summary(v.vehicle_id, day)}
                   for v in self._matching(vehicle_type, None)]
        results.sort(key=lambda r: -r["availability"]["total_available_hours"])
        return {"date": day.isoformat(), "results": results,
                "total_available": sum(1 for r in results if r["availability"]["total_available_hours"])}

    def browse_weekly(self, start_date: date, vehicle_type: Optional[VehicleType] = None,
                      location: Optional[str] = None) -> dict:
        fleet = []
        for v in self._matching(vehicle_type, location):
            weekly = self._calendar.get_weekly_availability(v.vehicle_id, start_date)
            fleet.append({"vehicle": v, "weekly_availability": weekly,
                          "total_weekly_available_hours": sum(d["total_available"] for d in weekly["days"])})
        fleet.sort(key=lambda r: -r["total_weekly_available_hours"])
        return {"week_start": start_date.isoformat(), "fleet": fleet, "total_vehicles": len(fleet)}


# ============================================================
# Facade
# ============================================================

class CarRentalService:
    HOLD_TTL = timedelta(minutes=10)     # time to pay before the hold lapses
    MIN_RENTAL = HOUR
    RETURN_GRACE = timedelta(minutes=15)
    POINTS_PER_HOUR = 2

    def __init__(self, clock: Callable[[], datetime] = datetime.now,
                 turnaround: timedelta = timedelta(minutes=30), lookahead_days: int = 7):
        self._clock = clock
        self._lock = threading.Lock()
        self._vehicles: Dict[str, Vehicle] = {}
        self._customers: Dict[str, Customer] = {}
        self._reservations: Dict[str, Reservation] = {}
        self._ids = itertools.count(1)
        self.calendar = AvailabilityCalendar(clock, turnaround, lookahead_days)
        self.search = SearchService(lambda: list(self._vehicles.values()), self.calendar)

    # ---- registration ----

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids):04d}"

    def add_vehicle(self, vehicle: Vehicle) -> None:
        with self._lock:
            self._vehicles[vehicle.vehicle_id] = vehicle
        self.calendar.add_vehicle(vehicle.vehicle_id)

    def register_customer(self, name: str, email: str, license_number: str) -> Customer:
        with self._lock:
            customer = Customer(self._next_id("C"), name, email, license_number)
            self._customers[customer.customer_id] = customer
            return customer

    def get_reservation(self, reservation_id: str) -> Reservation:
        res = self._reservations.get(reservation_id)
        if res is None:
            raise NotFoundError(f"reservation {reservation_id}")
        return res

    # ---- booking ----

    def create_reservation(self, customer_id: str, vehicle_id: str, pickup: datetime,
                           dropoff: datetime, pickup_location: str, dropoff_location: str,
                           pricing: Optional[RentalPricing] = None) -> Reservation:
        """Places a PENDING hold. Raises VehicleUnavailableError (with next_free) on overlap."""
        customer = self._customers.get(customer_id)
        vehicle = self._vehicles.get(vehicle_id)
        if customer is None or vehicle is None:
            raise NotFoundError("customer or vehicle not found")
        now = self._clock()
        if pickup < now:
            raise InvalidRequestError("cannot book in the past")
        if dropoff - pickup < self.MIN_RENTAL:
            raise InvalidRequestError(f"minimum rental is {self.MIN_RENTAL}")

        pricing = pricing or HourlyRentalPricing()
        rid = self._next_id("R")
        hold_until = now + self.HOLD_TTL
        if not self.calendar.try_block(vehicle_id, pickup, dropoff, BlockKind.RESERVATION,
                                       rid, expires_at=hold_until):
            raise VehicleUnavailableError(
                f"{vehicle.make} {vehicle.model} is not free {pickup:%a %d %H:%M} - {dropoff:%a %d %H:%M}",
                self.calendar.next_free_window(vehicle_id, pickup, dropoff))
        res = Reservation(rid, customer, vehicle, pickup, dropoff, pickup_location, dropoff_location,
                          pricing, pricing.calculate_cost(vehicle, billable_hours(pickup, dropoff)),
                          hold_until)
        with self._lock:
            self._reservations[rid] = res
        return res

    def confirm_reservation(self, reservation_id: str) -> Reservation:
        """Called after payment authorisation succeeds."""
        res = self.get_reservation(reservation_id)
        with res.lock:
            if res.status is not ReservationStatus.PENDING:
                raise InvalidTransitionError(f"{reservation_id} is {res.status.name}")
            if not self.calendar.confirm_hold(res.vehicle.vehicle_id, reservation_id):
                res.move_to(ReservationStatus.EXPIRED)
                raise HoldExpiredError(f"hold on {reservation_id} expired; search again")
            res.move_to(ReservationStatus.CONFIRMED)
        return res

    def cancel_reservation(self, reservation_id: str) -> Reservation:
        res = self.get_reservation(reservation_id)
        with res.lock:
            res.move_to(ReservationStatus.CANCELLED)
            self.calendar.release(res.vehicle.vehicle_id, reservation_id)
        return res

    def expire_holds(self) -> List[str]:
        """Periodic sweep: mark lapsed PENDING holds EXPIRED (the calendar already ignores them)."""
        now, expired = self._clock(), []
        for res in list(self._reservations.values()):
            with res.lock:
                if res.status is ReservationStatus.PENDING and now >= res.hold_expires_at:
                    res.move_to(ReservationStatus.EXPIRED)
                    self.calendar.release(res.vehicle.vehicle_id, res.reservation_id)
                    expired.append(res.reservation_id)
        return expired

    def schedule_maintenance(self, vehicle_id: str, start: datetime, end: datetime) -> str:
        """Maintenance is just another block; it can't overlap a booking and vice versa."""
        mid = self._next_id("M")
        if not self.calendar.try_block(vehicle_id, start, end, BlockKind.MAINTENANCE, mid):
            raise VehicleUnavailableError(f"maintenance window overlaps a booking on {vehicle_id}")
        return mid

    # ---- pickup / return ----

    def start_rental(self, reservation_id: str) -> Reservation:
        res = self.get_reservation(reservation_id)
        with res.lock:
            res.move_to(ReservationStatus.IN_PROGRESS)
            res.vehicle.status = VehicleStatus.RENTED
        return res

    def complete_rental(self, reservation_id: str, returned_at: Optional[datetime] = None) -> Decimal:
        """
        Charges the quote, or re-prices on the actual duration if returned later
        than the grace period. Early return still pays the booked time.
        """
        res = self.get_reservation(reservation_id)
        with res.lock:
            res.move_to(ReservationStatus.COMPLETED)
            returned_at = returned_at or self._clock()
            res.returned_at = returned_at
            if returned_at > res.dropoff + self.RETURN_GRACE:
                res.final_amount = res.pricing.calculate_cost(
                    res.vehicle, billable_hours(res.pickup, returned_at))
            else:
                res.final_amount = res.quoted_amount
            res.vehicle.status = VehicleStatus.AVAILABLE
            self.calendar.release(res.vehicle.vehicle_id, reservation_id)
            res.customer.loyalty_points += res.duration_hours * self.POINTS_PER_HOUR
            return res.final_amount


# ============================================================
# Demo (deterministic: fixed clock)
# ============================================================

class FixedClock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def demo() -> None:
    clock = FixedClock(datetime(2025, 1, 13, 8, 0))   # Monday 08:00
    svc = CarRentalService(clock=clock, turnaround=timedelta(minutes=30))
    D = Decimal
    for v in [
        Vehicle("V1", VehicleType.SUV, "Toyota", "Fortuner", 2024, "KA-01-AB-1234", FuelType.DIESEL, D("12"), D("80"), "Airport", 7),
        Vehicle("V2", VehicleType.SEDAN, "Honda", "City", 2024, "KA-01-CD-5678", FuelType.PETROL, D("8"), D("50"), "Airport"),
        Vehicle("V3", VehicleType.HATCHBACK, "Maruti", "Swift", 2023, "KA-01-EF-9012", FuelType.PETROL, D("5"), D("35"), "Airport"),
        Vehicle("V4", VehicleType.SUV, "Hyundai", "Creta", 2024, "KA-01-IJ-7890", FuelType.PETROL, D("10"), D("65"), "City"),
    ]:
        svc.add_vehicle(v)
    alice = svc.register_customer("Alice", "alice@example.com", "DL-1")
    bob = svc.register_customer("Bob", "bob@example.com", "DL-2")

    print("=== Car Rental Platform ===")
    pickup = datetime(2025, 1, 14, 10, 0)
    dropoff = datetime(2025, 1, 14, 12, 30)
    hits = svc.search.search_available(pickup, dropoff, VehicleType.SUV)
    print("SUVs free Tue 10:00-12:30:", [str(v) for v in hits])

    res = svc.create_reservation(alice.customer_id, "V1", pickup, dropoff, "Airport", "Airport")
    print(f"Hold placed: {res} (3 started hours x 12)")
    svc.confirm_reservation(res.reservation_id)
    print(f"Confirmed: {res.status.name}")

    try:
        svc.create_reservation(bob.customer_id, "V1", datetime(2025, 1, 14, 12, 45),
                               datetime(2025, 1, 14, 15, 0), "Airport", "Airport")
    except VehicleUnavailableError as e:
        print(f"Bob rejected (inside turnaround): {e}; next free start {e.next_free:%a %H:%M}")

    # Hold that lapses before payment.
    held = svc.create_reservation(bob.customer_id, "V2", pickup, dropoff, "Airport", "Airport")
    clock.advance(timedelta(minutes=11))
    try:
        svc.confirm_reservation(held.reservation_id)
    except HoldExpiredError as e:
        print(f"Bob's hold: {e} -> {held.status.name}")

    # Long rental with discount decorator.
    week = svc.create_reservation(alice.customer_id, "V4", datetime(2025, 1, 15, 9, 0),
                                  datetime(2025, 1, 23, 9, 0), "City", "City",
                                  WeeklyDiscountPricing(DailyRentalPricing()))
    print(f"8-day rental quote: {week.quoted_amount} (8 x 65 less 10%)")

    svc.schedule_maintenance("V3", datetime(2025, 1, 14, 0, 0), datetime(2025, 1, 14, 12, 0))
    print("V3 Tue free hours:", svc.calendar.free_hours("V3", date(2025, 1, 14)))
    print("V1 Tue free hours:", svc.calendar.free_hours("V1", date(2025, 1, 14)))

    clock.now = pickup
    svc.start_rental(res.reservation_id)
    charged = svc.complete_rental(res.reservation_id, returned_at=datetime(2025, 1, 14, 15, 0))
    print(f"Returned 2.5 h late: charged {charged} (re-priced on 5 h x 12)")
    day_hold = svc.create_reservation(bob.customer_id, "V1", datetime(2025, 1, 17, 8, 0),
                                      datetime(2025, 1, 17, 20, 0), "Airport", "Airport")
    print(f"12 h on V1 quoted {day_hold.quoted_amount} (12 x 12 = 144, capped at the 80 daily rate)")

    # Concurrency: 8 customers race for the same car and slot.
    racers = [svc.register_customer(f"Racer-{i}", f"r{i}@example.com", f"DL-R{i}") for i in range(8)]
    barrier, won = threading.Barrier(len(racers)), []

    def race(c: Customer) -> None:
        barrier.wait()
        try:
            won.append(svc.create_reservation(c.customer_id, "V2", datetime(2025, 1, 16, 9, 0),
                                              datetime(2025, 1, 16, 12, 0), "Airport", "Airport"))
        except VehicleUnavailableError:
            pass

    threads = [threading.Thread(target=race, args=(c,)) for c in racers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"8 concurrent holds on one slot -> {len(won)} succeeded")


if __name__ == "__main__":
    demo()
