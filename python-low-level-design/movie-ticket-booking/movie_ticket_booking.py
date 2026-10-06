"""
Movie Ticket Booking System (BookMyShow) - Low Level Design
-----------------------------------------------------------
Search shows, hold seats for a limited time, pay, confirm, cancel.

Key design decisions
  * A Screen has a seat *layout* (immutable `Seat`s). Each Show has its own
    seat *inventory* (`ShowSeat`s with status). Booking A1 for the 1 pm show
    must not touch A1 for the 4 pm show.
  * Seat state machine: AVAILABLE -> HELD(booking, expires_at) -> BOOKED.
    HELD -> AVAILABLE on cancel or expiry; BOOKED -> AVAILABLE on cancel.
    An expired hold counts as available immediately (lazy expiry); the
    sweeper (`release_expired`) only tidies up.
  * Concurrency: one lock per ShowSeat. A request for several seats takes
    their locks in one global order (sorted seat id), checks all, then
    changes all: all-or-nothing, no deadlock, and requests for disjoint
    seats in the same show run in parallel. Every change to a booking's
    status happens under its seats' locks, so confirm / cancel / expiry of
    one booking are serialised without a separate booking lock.
  * Payment is an external call: it is never made while holding a lock. It
    is idempotent (keyed by booking id). If the hold expired while the user
    was paying, confirmation fails under the locks and the charge is
    refunded, so a seat is never sold twice.
  * Money is Decimal (rupees, 2 dp); prices are snapshotted at hold time.
  * Time is injected (`clock`) so expiry is testable.

Python 3.10+, stdlib only.
"""

from __future__ import annotations

import itertools
import threading
from abc import ABC, abstractmethod
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Callable, Iterator

Clock = Callable[[], datetime]
PAISE = Decimal("0.01")
MAX_SEATS_PER_BOOKING = 10


# --- Errors -----------------------------------------------------------------------

class BookingError(Exception):
    pass


class SeatUnavailable(BookingError):
    def __init__(self, seat_ids: list[str]) -> None:
        super().__init__(f"seats not available: {', '.join(seat_ids)}")
        self.seat_ids = seat_ids


class HoldExpired(BookingError):
    pass


class PaymentFailed(BookingError):
    pass


class InvalidBookingState(BookingError):
    pass


# --- Catalogue: movies, theatres, screens, seats ------------------------------------

class City(Enum):
    MUMBAI = "Mumbai"
    DELHI = "Delhi"
    BANGALORE = "Bangalore"


class Genre(Enum):
    ACTION = "Action"
    COMEDY = "Comedy"
    DRAMA = "Drama"
    SCI_FI = "Sci-Fi"


class SeatCategory(Enum):
    REGULAR = "Regular"
    PREMIUM = "Premium"
    VIP = "VIP"


@dataclass(frozen=True)
class Movie:
    movie_id: str
    title: str
    genre: Genre
    duration_minutes: int
    language: str


@dataclass(frozen=True)
class Seat:
    """A physical seat in a screen's layout. Has no booking state."""
    seat_id: str          # e.g. "A7"
    row: str
    number: int
    category: SeatCategory


@dataclass(frozen=True)
class Screen:
    screen_id: str
    name: str
    seats: tuple[Seat, ...]

    @staticmethod
    def with_rows(screen_id: str, name: str, rows: dict[str, SeatCategory], per_row: int) -> Screen:
        seats = tuple(Seat(f"{r}{n}", r, n, cat) for r, cat in rows.items() for n in range(1, per_row + 1))
        return Screen(screen_id, name, seats)


@dataclass(frozen=True)
class Theatre:
    theatre_id: str
    name: str
    city: City


# --- Show inventory -------------------------------------------------------------------

class SeatStatus(Enum):
    AVAILABLE = "Available"
    HELD = "Held"
    BOOKED = "Booked"


@dataclass(eq=False)
class ShowSeat:
    """One seat for one show. Mutable fields are guarded by `lock`."""
    seat: Seat
    status: SeatStatus = SeatStatus.AVAILABLE
    booking_id: str | None = None
    hold_expires_at: datetime | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def is_free(self, now: datetime) -> bool:
        """Available, or held by a hold that has already expired."""
        if self.status is SeatStatus.AVAILABLE:
            return True
        return self.status is SeatStatus.HELD and self.hold_expires_at is not None \
            and self.hold_expires_at <= now

    def held_by(self, booking_id: str) -> bool:
        return self.status is SeatStatus.HELD and self.booking_id == booking_id

    def hold(self, booking_id: str, expires_at: datetime) -> None:
        self.status, self.booking_id, self.hold_expires_at = SeatStatus.HELD, booking_id, expires_at

    def book(self) -> None:
        self.status, self.hold_expires_at = SeatStatus.BOOKED, None

    def release(self) -> None:
        self.status, self.booking_id, self.hold_expires_at = SeatStatus.AVAILABLE, None, None


class Show:
    def __init__(self, show_id: str, movie: Movie, theatre: Theatre, screen: Screen,
                 start_time: datetime, base_prices: dict[SeatCategory, Decimal]) -> None:
        missing = {s.category for s in screen.seats} - base_prices.keys()
        if missing:
            raise ValueError(f"no base price for {sorted(c.value for c in missing)}")
        self.show_id = show_id
        self.movie = movie
        self.theatre = theatre
        self.screen = screen
        self.start_time = start_time
        self.end_time = start_time + timedelta(minutes=movie.duration_minutes + 15)  # + cleaning
        self.base_prices = dict(base_prices)
        self._seats: dict[str, ShowSeat] = {s.seat_id: ShowSeat(s) for s in screen.seats}

    def seat(self, seat_id: str) -> ShowSeat:
        try:
            return self._seats[seat_id]
        except KeyError:
            raise BookingError(f"no seat {seat_id!r} in {self.screen.name}") from None

    def available_seat_ids(self, now: datetime) -> list[str]:
        # Unlocked read: a snapshot for display. It can be stale by the time the
        # user clicks; the locked check in hold_seats is what counts.
        return [sid for sid, s in self._seats.items() if s.is_free(now)]

    def __str__(self) -> str:
        return f"{self.movie.title} @ {self.theatre.name} {self.start_time:%a %d %b %H:%M}"


@contextmanager
def locked_in_order(seats: list[ShowSeat]) -> Iterator[None]:
    """Acquire seat locks in one global order (seat id). Two requests for
    {A1, A2} and {A2, A1} both lock A1 first, so neither can hold one lock
    while waiting for the other: no deadlock."""
    with ExitStack() as stack:
        for s in sorted(seats, key=lambda s: s.seat.seat_id):
            stack.enter_context(s.lock)
        yield


# --- Pricing (Strategy) ---------------------------------------------------------------

class PricingStrategy(ABC):
    @abstractmethod
    def price(self, base: Decimal, show: Show, seat: Seat) -> Decimal: ...


class StandardPricing(PricingStrategy):
    def price(self, base: Decimal, show: Show, seat: Seat) -> Decimal:
        return base


class PeakHourPricing(PricingStrategy):
    def __init__(self, hours: range = range(18, 22), multiplier: Decimal = Decimal("1.2")) -> None:
        self.hours, self.multiplier = hours, multiplier

    def price(self, base: Decimal, show: Show, seat: Seat) -> Decimal:
        return base * self.multiplier if show.start_time.hour in self.hours else base


class WeekendPricing(PricingStrategy):
    def __init__(self, multiplier: Decimal = Decimal("1.25")) -> None:
        self.multiplier = multiplier

    def price(self, base: Decimal, show: Show, seat: Seat) -> Decimal:
        return base * self.multiplier if show.start_time.weekday() >= 5 else base


class CompositePricing(PricingStrategy):
    """Applies strategies in sequence (each sees the previous one's output)."""

    def __init__(self, *strategies: PricingStrategy) -> None:
        self.strategies = strategies

    def price(self, base: Decimal, show: Show, seat: Seat) -> Decimal:
        for s in self.strategies:
            base = s.price(base, show, seat)
        return base


# --- Payment --------------------------------------------------------------------------

class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, idempotency_key: str, amount: Decimal) -> str:
        """Charge once per key; a retry with the same key returns the same
        payment id without charging again. Raises PaymentFailed if declined."""

    @abstractmethod
    def refund(self, payment_id: str, amount: Decimal) -> None: ...


class FakePaymentGateway(PaymentGateway):
    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}
        self.charges: list[tuple[str, Decimal]] = []
        self.refunds: list[tuple[str, Decimal]] = []
        self.decline_next = False
        self.during_charge: Callable[[], None] | None = None   # test hook: simulate a slow gateway
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def charge(self, idempotency_key: str, amount: Decimal) -> str:
        if self.during_charge:
            self.during_charge()
        with self._lock:
            if idempotency_key in self._by_key:
                return self._by_key[idempotency_key]
            if self.decline_next:
                self.decline_next = False
                raise PaymentFailed("card declined")
            pid = f"PAY-{next(self._ids)}"
            self._by_key[idempotency_key] = pid
            self.charges.append((pid, amount))
            return pid

    def refund(self, payment_id: str, amount: Decimal) -> None:
        with self._lock:
            self.refunds.append((payment_id, amount))


# --- Booking --------------------------------------------------------------------------

class BookingStatus(Enum):
    PENDING = "Pending"       # seats held, awaiting payment
    CONFIRMED = "Confirmed"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"


@dataclass(eq=False)
class Booking:
    """Status changes only under the locks of `seats` (see BookingService)."""
    booking_id: str
    user_id: str
    show: Show
    seats: list[ShowSeat]
    line_prices: dict[str, Decimal]          # seat id -> price, snapshotted at hold time
    expires_at: datetime
    status: BookingStatus = BookingStatus.PENDING
    payment_id: str | None = None

    @property
    def total(self) -> Decimal:
        return sum(self.line_prices.values(), Decimal("0"))

    @property
    def seat_ids(self) -> list[str]:
        return [s.seat.seat_id for s in self.seats]


class BookingService:
    """Facade for the booking flow: hold -> pay_and_confirm -> (cancel)."""

    def __init__(self, gateway: PaymentGateway, pricing: PricingStrategy | None = None,
                 clock: Clock = datetime.now, hold_ttl: timedelta = timedelta(minutes=10)) -> None:
        self._gateway = gateway
        self._pricing = pricing or StandardPricing()
        self._clock = clock
        self._hold_ttl = hold_ttl
        self._shows: dict[str, Show] = {}
        self._bookings: dict[str, Booking] = {}
        self._registry_lock = threading.Lock()     # guards the two dicts only
        self._ids = itertools.count(1)

    # Catalogue ---------------------------------------------------------------

    def add_show(self, show: Show) -> None:
        with self._registry_lock:
            self._shows[show.show_id] = show

    def show(self, show_id: str) -> Show:
        with self._registry_lock:
            try:
                return self._shows[show_id]
            except KeyError:
                raise BookingError(f"unknown show {show_id!r}") from None

    def search(self, city: City | None = None, movie_id: str | None = None,
               on: date | None = None, genre: Genre | None = None) -> list[Show]:
        with self._registry_lock:
            shows = list(self._shows.values())
        return sorted((s for s in shows
                       if (city is None or s.theatre.city is city)
                       and (movie_id is None or s.movie.movie_id == movie_id)
                       and (on is None or s.start_time.date() == on)
                       and (genre is None or s.movie.genre is genre)),
                      key=lambda s: s.start_time)

    def available_seats(self, show_id: str) -> list[str]:
        return self.show(show_id).available_seat_ids(self._clock())

    def booking(self, booking_id: str) -> Booking:
        with self._registry_lock:
            try:
                return self._bookings[booking_id]
            except KeyError:
                raise BookingError(f"unknown booking {booking_id!r}") from None

    # Step 1: hold ------------------------------------------------------------

    def hold_seats(self, show_id: str, user_id: str, seat_ids: list[str]) -> Booking:
        if not seat_ids:
            raise BookingError("select at least one seat")
        if len(set(seat_ids)) != len(seat_ids):
            raise BookingError("duplicate seat in request")
        if len(seat_ids) > MAX_SEATS_PER_BOOKING:
            raise BookingError(f"at most {MAX_SEATS_PER_BOOKING} seats per booking")
        show = self.show(show_id)
        seats = [show.seat(sid) for sid in seat_ids]
        booking_id = f"BK-{next(self._ids):05d}"

        with locked_in_order(seats):
            now = self._clock()
            if now >= show.start_time:
                raise BookingError("show has already started")
            taken = [s.seat.seat_id for s in seats if not s.is_free(now)]
            if taken:
                raise SeatUnavailable(taken)        # nothing changed: all-or-nothing
            expires_at = now + self._hold_ttl
            for s in seats:
                s.hold(booking_id, expires_at)

        prices = {s.seat.seat_id: self._pricing.price(show.base_prices[s.seat.category], show, s.seat)
                  .quantize(PAISE, ROUND_HALF_UP) for s in seats}
        booking = Booking(booking_id, user_id, show, seats, prices, expires_at)
        with self._registry_lock:
            self._bookings[booking_id] = booking
        return booking

    # Step 2: pay and confirm -------------------------------------------------

    def pay_and_confirm(self, booking_id: str) -> Booking:
        """Safe to retry: the charge is idempotent on booking id, and a second
        call on a CONFIRMED booking returns it unchanged."""
        booking = self.booking(booking_id)
        if booking.status is BookingStatus.CONFIRMED:
            return booking
        if booking.status is not BookingStatus.PENDING:
            raise InvalidBookingState(f"{booking_id} is {booking.status.value}")
        if self._clock() >= booking.expires_at:      # cheap early exit; re-checked under locks
            self._expire(booking)
            raise HoldExpired(f"{booking_id}: hold expired before payment; not charged")

        # External call: never while holding seat locks.
        payment_id = self._gateway.charge(booking_id, booking.total)

        with locked_in_order(booking.seats):
            if booking.status is BookingStatus.CONFIRMED:
                return booking                         # a concurrent retry won
            still_ours = (booking.status is BookingStatus.PENDING
                          and self._clock() < booking.expires_at
                          and all(s.held_by(booking_id) for s in booking.seats))
            if still_ours:
                for s in booking.seats:
                    s.book()
                booking.status, booking.payment_id = BookingStatus.CONFIRMED, payment_id
                return booking
            self._expire_locked(booking)

        # Paid, but the hold lapsed (or was cancelled) first: give the money back.
        self._gateway.refund(payment_id, booking.total)
        raise HoldExpired(f"{booking_id}: hold lapsed during payment; refunded")

    # Cancel / expire -----------------------------------------------------------

    def cancel(self, booking_id: str) -> Booking:
        booking = self.booking(booking_id)
        with locked_in_order(booking.seats):
            was = booking.status
            if was not in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
                raise InvalidBookingState(f"{booking_id} is {was.value}")
            for s in booking.seats:
                if s.booking_id == booking_id:       # never release a seat someone else now holds
                    s.release()
            booking.status = BookingStatus.CANCELLED
        if was is BookingStatus.CONFIRMED and booking.payment_id:
            self._gateway.refund(booking.payment_id, booking.total)   # refund policy plugs in here
        return booking

    def release_expired(self) -> int:
        """Sweeper: expire PENDING bookings past their hold. Correctness does not
        depend on it (expired holds are already treated as free); it keeps
        booking statuses and seat maps tidy."""
        now = self._clock()
        with self._registry_lock:
            due = [b for b in self._bookings.values()
                   if b.status is BookingStatus.PENDING and b.expires_at <= now]
        return sum(self._expire(b) for b in due)

    def _expire(self, booking: Booking) -> bool:
        with locked_in_order(booking.seats):
            return self._expire_locked(booking)

    def _expire_locked(self, booking: Booking) -> bool:
        if booking.status is not BookingStatus.PENDING:
            return False
        for s in booking.seats:
            if s.held_by(booking.booking_id):
                s.release()
        booking.status = BookingStatus.EXPIRED
        return True


# --- Demo -----------------------------------------------------------------------------

class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


def build_demo() -> tuple[BookingService, FakeClock, FakePaymentGateway]:
    clock = FakeClock(datetime(2026, 10, 9, 12, 0))           # a Friday
    gateway = FakePaymentGateway()
    service = BookingService(gateway, CompositePricing(PeakHourPricing(), WeekendPricing()), clock)
    screen = Screen.with_rows("S1", "Audi 1", {"A": SeatCategory.VIP, "B": SeatCategory.PREMIUM,
                                               "C": SeatCategory.REGULAR, "D": SeatCategory.REGULAR}, 8)
    pvr = Theatre("T1", "PVR Phoenix", City.MUMBAI)
    inception = Movie("M1", "Inception", Genre.SCI_FI, 148, "English")
    prices = {SeatCategory.REGULAR: Decimal("200"), SeatCategory.PREMIUM: Decimal("320"),
              SeatCategory.VIP: Decimal("450")}
    for show_id, start in (("SH1", datetime(2026, 10, 9, 13, 0)),
                           ("SH2", datetime(2026, 10, 9, 19, 0)),
                           ("SH3", datetime(2026, 10, 10, 19, 0))):
        service.add_show(Show(show_id, inception, pvr, screen, start, prices))
    return service, clock, gateway


def demo() -> None:
    service, clock, gateway = build_demo()

    print("=== Search ===")
    for s in service.search(city=City.MUMBAI, movie_id="M1"):
        print(f"  {s.show_id}: {s}  free={len(service.available_seats(s.show_id))}")

    print("\n=== Hold + pay (Saturday evening: peak x1.2 then weekend x1.25) ===")
    b1 = service.hold_seats("SH3", "asha", ["A1", "A2", "C5"])
    print(f"  {b1.booking_id} held {b1.seat_ids} until {b1.expires_at:%H:%M}: "
          + ", ".join(f"{k}=₹{v}" for k, v in b1.line_prices.items()) + f"  total ₹{b1.total}")
    service.pay_and_confirm(b1.booking_id)
    service.pay_and_confirm(b1.booking_id)   # client retry: no second charge
    print(f"  {b1.booking_id}: {b1.status.value}, charges recorded: {len(gateway.charges)}")

    print("\n=== Same seat, different show is independent ===")
    b2 = service.hold_seats("SH1", "ravi", ["A1"])
    print(f"  SH1 A1 -> {b2.booking_id} {b2.status.value}")

    print("\n=== Double booking is rejected, all-or-nothing ===")
    try:
        service.hold_seats("SH3", "vik", ["C4", "C5"])
    except SeatUnavailable as e:
        print(f"  rejected: {e}; C4 still free: {'C4' in service.available_seats('SH3')}")

    print("\n=== Hold expires while the user is paying ===")
    slow = service.hold_seats("SH2", "meera", ["B3"])
    taken_by: list[Booking] = []

    def gateway_takes_11_minutes() -> None:
        gateway.during_charge = None
        clock.advance(minutes=11)                               # meera's hold lapses...
        taken_by.append(service.hold_seats("SH2", "dev", ["B3"]))  # ...and dev grabs B3

    gateway.during_charge = gateway_takes_11_minutes
    try:
        service.pay_and_confirm(slow.booking_id)
    except HoldExpired as e:
        print(f"  meera: {e}")
    service.pay_and_confirm(taken_by[0].booking_id)
    print(f"  dev: {taken_by[0].status.value}; meera {slow.status.value}; "
          f"charges={len(gateway.charges)} refunds={len(gateway.refunds)}")

    print("\n=== Cancel a confirmed booking ===")
    service.cancel(b1.booking_id)
    print(f"  {b1.booking_id}: {b1.status.value}; A1 free again: {'A1' in service.available_seats('SH3')}")
    print(f"  sweeper expired {service.release_expired()} stale hold(s)")


if __name__ == "__main__":
    demo()
