import random
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from movie_ticket_booking import (
    BookingError,
    BookingService,
    BookingStatus,
    City,
    CompositePricing,
    FakeClock,
    FakePaymentGateway,
    Genre,
    HoldExpired,
    InvalidBookingState,
    Movie,
    PaymentFailed,
    PeakHourPricing,
    Screen,
    SeatCategory,
    SeatStatus,
    SeatUnavailable,
    Show,
    StandardPricing,
    Theatre,
    WeekendPricing,
    build_demo,
)

PRICES = {SeatCategory.REGULAR: Decimal("200"), SeatCategory.PREMIUM: Decimal("320"),
          SeatCategory.VIP: Decimal("450")}


def make_service(pricing=None, seats_per_row=10):
    clock = FakeClock(datetime(2026, 10, 7, 10, 0))          # Wednesday
    gateway = FakePaymentGateway()
    service = BookingService(gateway, pricing or StandardPricing(), clock, timedelta(minutes=10))
    screen = Screen.with_rows("S1", "Audi 1", {"A": SeatCategory.VIP, "B": SeatCategory.REGULAR},
                              seats_per_row)
    theatre = Theatre("T1", "PVR", City.MUMBAI)
    movie = Movie("M1", "Inception", Genre.SCI_FI, 148, "English")
    service.add_show(Show("S-1pm", movie, theatre, screen, datetime(2026, 10, 7, 13, 0), PRICES))
    service.add_show(Show("S-7pm", movie, theatre, screen, datetime(2026, 10, 7, 19, 0), PRICES))
    return service, clock, gateway


class HoldTests(unittest.TestCase):
    def test_hold_then_confirm(self):
        service, _, gateway = make_service()
        b = service.hold_seats("S-1pm", "u1", ["A1", "B2"])
        self.assertEqual(b.status, BookingStatus.PENDING)
        self.assertEqual(b.total, Decimal("650.00"))
        service.pay_and_confirm(b.booking_id)
        self.assertEqual(b.status, BookingStatus.CONFIRMED)
        self.assertTrue(all(s.status is SeatStatus.BOOKED for s in b.seats))
        self.assertEqual(gateway.charges, [(b.payment_id, Decimal("650.00"))])

    def test_seat_inventory_is_per_show(self):
        """Regression: seat state used to live on the Screen, so booking A1
        for one show blocked A1 for every show on that screen."""
        service, _, _ = make_service()
        service.hold_seats("S-1pm", "u1", ["A1"])
        b = service.hold_seats("S-7pm", "u2", ["A1"])
        self.assertEqual(b.status, BookingStatus.PENDING)

    def test_conflict_is_all_or_nothing(self):
        service, _, _ = make_service()
        service.hold_seats("S-1pm", "u1", ["A2"])
        with self.assertRaises(SeatUnavailable) as ctx:
            service.hold_seats("S-1pm", "u2", ["A1", "A2", "A3"])
        self.assertEqual(ctx.exception.seat_ids, ["A2"])
        free = service.available_seats("S-1pm")
        self.assertIn("A1", free)
        self.assertIn("A3", free)

    def test_request_validation(self):
        service, clock, _ = make_service()
        for bad in ([], ["A1", "A1"], ["Z9"], [f"B{i}" for i in range(1, 11)] + ["A1"]):
            with self.subTest(bad=bad), self.assertRaises(BookingError):
                service.hold_seats("S-1pm", "u", bad)
        with self.assertRaises(BookingError):
            service.hold_seats("nope", "u", ["A1"])
        clock.now = datetime(2026, 10, 7, 13, 0)
        with self.assertRaises(BookingError):
            service.hold_seats("S-1pm", "u", ["A1"])          # show started

    def test_unknown_category_price_rejected_at_show_creation(self):
        screen = Screen.with_rows("S", "x", {"A": SeatCategory.VIP}, 2)
        with self.assertRaises(ValueError):
            Show("X", Movie("M", "m", Genre.DRAMA, 90, "en"), Theatre("T", "t", City.DELHI),
                 screen, datetime(2026, 1, 1), {SeatCategory.REGULAR: Decimal("1")})


class ExpiryTests(unittest.TestCase):
    def test_expired_hold_is_free_without_the_sweeper(self):
        service, clock, _ = make_service()
        service.hold_seats("S-1pm", "u1", ["A1"])
        clock.advance(minutes=9, seconds=59)
        with self.assertRaises(SeatUnavailable):
            service.hold_seats("S-1pm", "u2", ["A1"])
        clock.advance(seconds=1)
        b2 = service.hold_seats("S-1pm", "u2", ["A1"])
        self.assertEqual(b2.status, BookingStatus.PENDING)

    def test_pay_after_expiry_is_not_charged(self):
        service, clock, gateway = make_service()
        b = service.hold_seats("S-1pm", "u1", ["A1"])
        clock.advance(minutes=10)
        with self.assertRaises(HoldExpired):
            service.pay_and_confirm(b.booking_id)
        self.assertEqual(gateway.charges, [])
        self.assertEqual(b.status, BookingStatus.EXPIRED)
        self.assertIn("A1", service.available_seats("S-1pm"))

    def test_hold_lapses_during_payment_seat_resold_and_charge_refunded(self):
        """The race that sells a seat twice if confirm doesn't re-check
        ownership under the lock."""
        service, clock, gateway = make_service()
        slow = service.hold_seats("S-1pm", "u1", ["A1"])
        stolen = []

        def lapse():
            gateway.during_charge = None
            clock.advance(minutes=11)
            stolen.append(service.hold_seats("S-1pm", "u2", ["A1"]))

        gateway.during_charge = lapse
        with self.assertRaises(HoldExpired):
            service.pay_and_confirm(slow.booking_id)
        self.assertEqual(slow.status, BookingStatus.EXPIRED)
        self.assertEqual(len(gateway.refunds), 1)
        seat = service.show("S-1pm").seat("A1")
        self.assertEqual(seat.booking_id, stolen[0].booking_id)    # u2 still holds it
        service.pay_and_confirm(stolen[0].booking_id)
        self.assertEqual(seat.status, SeatStatus.BOOKED)

    def test_payment_just_before_expiry_confirms(self):
        service, clock, _ = make_service()
        b = service.hold_seats("S-1pm", "u1", ["A1"])
        clock.advance(minutes=9, seconds=59)
        service.pay_and_confirm(b.booking_id)
        self.assertEqual(b.status, BookingStatus.CONFIRMED)

    def test_sweeper_expires_only_lapsed_pending_holds(self):
        service, clock, _ = make_service()
        old = service.hold_seats("S-1pm", "u1", ["A1"])
        paid = service.hold_seats("S-1pm", "u2", ["A2"])
        service.pay_and_confirm(paid.booking_id)
        clock.advance(minutes=5)
        fresh = service.hold_seats("S-1pm", "u3", ["A3"])
        clock.advance(minutes=6)
        self.assertEqual(service.release_expired(), 1)
        self.assertEqual(old.status, BookingStatus.EXPIRED)
        self.assertEqual(paid.status, BookingStatus.CONFIRMED)
        self.assertEqual(fresh.status, BookingStatus.PENDING)

    def test_expiring_an_old_booking_never_releases_a_reheld_seat(self):
        service, clock, _ = make_service()
        old = service.hold_seats("S-1pm", "u1", ["A1"])
        clock.advance(minutes=11)
        new = service.hold_seats("S-1pm", "u2", ["A1"])
        service.release_expired()
        self.assertEqual(old.status, BookingStatus.EXPIRED)
        self.assertTrue(service.show("S-1pm").seat("A1").held_by(new.booking_id))


class PaymentAndCancelTests(unittest.TestCase):
    def test_retry_is_idempotent(self):
        service, _, gateway = make_service()
        b = service.hold_seats("S-1pm", "u1", ["A1"])
        service.pay_and_confirm(b.booking_id)
        service.pay_and_confirm(b.booking_id)
        self.assertEqual(len(gateway.charges), 1)

    def test_declined_payment_keeps_hold_for_retry(self):
        service, _, gateway = make_service()
        b = service.hold_seats("S-1pm", "u1", ["A1"])
        gateway.decline_next = True
        with self.assertRaises(PaymentFailed):
            service.pay_and_confirm(b.booking_id)
        self.assertEqual(b.status, BookingStatus.PENDING)
        service.pay_and_confirm(b.booking_id)
        self.assertEqual(b.status, BookingStatus.CONFIRMED)

    def test_cancel_pending_releases_without_refund(self):
        service, _, gateway = make_service()
        b = service.hold_seats("S-1pm", "u1", ["A1"])
        service.cancel(b.booking_id)
        self.assertEqual(b.status, BookingStatus.CANCELLED)
        self.assertIn("A1", service.available_seats("S-1pm"))
        self.assertEqual(gateway.refunds, [])
        with self.assertRaises(InvalidBookingState):
            service.pay_and_confirm(b.booking_id)

    def test_cancel_confirmed_refunds_and_frees(self):
        service, _, gateway = make_service()
        b = service.hold_seats("S-1pm", "u1", ["A1", "A2"])
        service.pay_and_confirm(b.booking_id)
        service.cancel(b.booking_id)
        self.assertEqual(gateway.refunds, [(b.payment_id, Decimal("900.00"))])
        self.assertIn("A2", service.available_seats("S-1pm"))
        with self.assertRaises(InvalidBookingState):
            service.cancel(b.booking_id)


class PricingTests(unittest.TestCase):
    def test_composite_pricing_and_rounding(self):
        pricing = CompositePricing(PeakHourPricing(multiplier=Decimal("1.15")), WeekendPricing())
        service, clock, _ = make_service(pricing)
        show = service.show("S-7pm")
        # 7 pm on a Wednesday: peak only. 450 * 1.15 = 517.50
        b = service.hold_seats("S-7pm", "u", ["A1"])
        self.assertEqual(b.total, Decimal("517.50"))
        show.start_time = datetime(2026, 10, 10, 19, 0)        # Saturday: 450 * 1.15 * 1.25 = 646.875
        b2 = service.hold_seats("S-7pm", "u", ["A2"])
        self.assertEqual(b2.line_prices["A2"], Decimal("646.88"))

    def test_price_is_snapshotted_at_hold_time(self):
        service, _, gateway = make_service()
        b = service.hold_seats("S-1pm", "u", ["B1"])
        service.show("S-1pm").base_prices[SeatCategory.REGULAR] = Decimal("999")
        service.pay_and_confirm(b.booking_id)
        self.assertEqual(gateway.charges[0][1], Decimal("200.00"))


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self._switch = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)          # force frequent thread switches to expose races

    def tearDown(self):
        sys.setswitchinterval(self._switch)

    def _run(self, n, target):
        barrier = threading.Barrier(n)
        threads = [threading.Thread(target=lambda i=i: (barrier.wait(), target(i)), daemon=True)
                   for i in range(n)]
        for t in threads:
            t.start()
        deadline = time.monotonic() + 10
        for t in threads:
            t.join(timeout=max(0.0, deadline - time.monotonic()))
        self.assertFalse(any(t.is_alive() for t in threads), "deadlock: threads still running")

    def test_many_users_one_seat_exactly_one_wins(self):
        service, _, _ = make_service()
        wins, lock = [], threading.Lock()

        def attempt(i):
            try:
                b = service.hold_seats("S-1pm", f"u{i}", ["A5"])
                with lock:
                    wins.append(b)
            except SeatUnavailable:
                pass

        self._run(32, attempt)
        self.assertEqual(len(wins), 1)

    def test_overlapping_multi_seat_requests_never_double_book(self):
        """Random overlapping seat sets in random order: every seat ends up in
        at most one booking, and failed requests hold nothing."""
        service, _, _ = make_service(seats_per_row=6)
        seats = [f"A{i}" for i in range(1, 7)] + [f"B{i}" for i in range(1, 7)]
        wins, lock = [], threading.Lock()

        def attempt(i):
            rng = random.Random(i)
            for _ in range(30):
                pick = rng.sample(seats, rng.randint(1, 4))
                try:
                    b = service.hold_seats("S-1pm", f"u{i}", pick)
                except SeatUnavailable:
                    continue
                with lock:
                    wins.append(b)
                if rng.random() < 0.5:
                    service.cancel(b.booking_id)

        self._run(16, attempt)
        active = [b for b in wins if b.status is BookingStatus.PENDING]
        held = [sid for b in active for sid in b.seat_ids]
        self.assertEqual(len(held), len(set(held)), "a seat is in two active bookings")
        show = service.show("S-1pm")
        for sid in seats:
            seat = show.seat(sid)
            owners = [b.booking_id for b in active if sid in b.seat_ids]
            if seat.status is SeatStatus.HELD:
                self.assertEqual(owners, [seat.booking_id])
            else:
                self.assertEqual(owners, [])

    def test_opposite_lock_order_requests_do_not_deadlock(self):
        """{A1, A2} vs {A2, A1}, repeatedly. Without a global lock order this
        deadlocks (thread 1 holds A1 waiting for A2, thread 2 the reverse)."""
        service, _, _ = make_service()

        def attempt(i):
            order = ["A1", "A2"] if i % 2 else ["A2", "A1"]
            for _ in range(300):
                try:
                    b = service.hold_seats("S-1pm", f"u{i}", order)
                    service.cancel(b.booking_id)
                except SeatUnavailable:
                    pass

        self._run(8, attempt)

    def test_concurrent_confirm_and_cancel_of_one_booking(self):
        """Confirm and cancel race. Either outcome is fine; the seat state must
        match the booking state and money must balance."""
        for trial in range(50):
            service, _, gateway = make_service()
            b = service.hold_seats("S-1pm", "u", ["A1"])

            def act(i):
                try:
                    if i == 0:
                        service.pay_and_confirm(b.booking_id)
                    else:
                        service.cancel(b.booking_id)
                except (HoldExpired, InvalidBookingState):
                    pass

            self._run(2, act)
            seat = service.show("S-1pm").seat("A1")
            if b.status is BookingStatus.CONFIRMED:
                self.assertIs(seat.status, SeatStatus.BOOKED)
                self.assertEqual((len(gateway.charges), len(gateway.refunds)), (1, 0))
            else:
                self.assertIs(b.status, BookingStatus.CANCELLED)
                self.assertIs(seat.status, SeatStatus.AVAILABLE)
                self.assertEqual(len(gateway.charges), len(gateway.refunds))


class DemoTests(unittest.TestCase):
    def test_demo_world_is_deterministic(self):
        service, _, _ = build_demo()
        self.assertEqual([s.show_id for s in service.search(city=City.MUMBAI)], ["SH1", "SH2", "SH3"])


if __name__ == "__main__":
    unittest.main()
