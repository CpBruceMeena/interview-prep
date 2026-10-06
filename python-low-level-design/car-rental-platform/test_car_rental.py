import threading
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

from car_rental import (
    CarRentalService, DailyRentalPricing, FixedClock, FuelType, HoldExpiredError,
    HourlyRentalPricing, InvalidRequestError, InvalidTransitionError, ReservationStatus,
    Vehicle, VehicleStatus, VehicleType, VehicleUnavailableError, WeeklyDiscountPricing,
    billable_hours,
)

D = Decimal
NOW = datetime(2025, 1, 13, 8, 0)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2025, 1, day, hour, minute)


def car(vid: str = "V1", vtype: VehicleType = VehicleType.SEDAN, hourly: str = "10",
        daily: str = "60", location: str = "Airport") -> Vehicle:
    return Vehicle(vid, vtype, "Make", "Model", 2024, f"PL-{vid}", FuelType.PETROL,
                   D(hourly), D(daily), location)


class PricingTest(unittest.TestCase):
    def setUp(self):
        self.v = car(hourly="10", daily="60")

    def test_billable_hours_rounds_up_started_hours(self):
        self.assertEqual(billable_hours(at(14, 10), at(14, 10, 1)), 1)
        self.assertEqual(billable_hours(at(14, 10), at(14, 12, 30)), 3)
        self.assertEqual(billable_hours(at(14, 10), at(14, 12)), 2)

    def test_hourly_is_capped_at_daily_rate_per_day(self):
        p = HourlyRentalPricing()
        self.assertEqual(p.calculate_cost(self.v, 3), D("30.00"))
        self.assertEqual(p.calculate_cost(self.v, 10), D("60.00"))       # 100 capped at 60
        self.assertEqual(p.calculate_cost(self.v, 26), D("80.00"))       # 1 day + 2 h

    def test_daily_and_discount(self):
        self.assertEqual(DailyRentalPricing().calculate_cost(self.v, 25), D("120.00"))
        weekly = WeeklyDiscountPricing(DailyRentalPricing())
        self.assertEqual(weekly.calculate_cost(self.v, 7 * 24), D("378.00"))    # 420 * 0.9
        self.assertEqual(weekly.calculate_cost(self.v, 30 * 24), D("1377.00"))  # 1800 * .9 * .85


class CalendarTest(unittest.TestCase):
    def setUp(self):
        self.clock = FixedClock(NOW)
        self.svc = CarRentalService(clock=self.clock, turnaround=timedelta(0))
        self.svc.add_vehicle(car("V1"))
        self.cust = self.svc.register_customer("A", "a@x", "DL")

    def book(self, start, end, vid="V1"):
        return self.svc.create_reservation(self.cust.customer_id, vid, start, end, "Airport", "Airport")

    def test_half_open_intervals_allow_back_to_back(self):
        self.book(at(14, 10), at(14, 12))
        self.book(at(14, 12), at(14, 14))                                  # touches, doesn't overlap
        self.book(at(14, 8), at(14, 10))

    def test_sub_hour_overlaps_are_caught(self):
        # The old hourly-slot version floored both ends, so these slipped through.
        self.book(at(14, 10, 30), at(14, 11, 45))
        for start, end in [(at(14, 11), at(14, 12)), (at(14, 9, 30), at(14, 10, 45)),
                           (at(14, 10, 40), at(14, 11, 50)), (at(14, 9), at(14, 13))]:
            with self.assertRaises(VehicleUnavailableError):
                self.book(start, end)

    def test_free_hours_projection(self):
        self.book(at(14, 10, 30), at(14, 12))
        free = self.svc.calendar.free_hours("V1", date(2025, 1, 14))
        self.assertNotIn(10, free)          # partially booked hour is not free
        self.assertNotIn(11, free)
        self.assertIn(12, free)
        self.assertEqual(len(free), 22)
        bitmap = self.svc.calendar.weekly_bitmap("V1", date(2025, 1, 13))
        self.assertFalse(bitmap >> (24 + 10) & 1)
        self.assertTrue(bitmap >> (24 + 12) & 1)

    def test_turnaround_buffer_and_next_free_suggestion(self):
        svc = CarRentalService(clock=self.clock, turnaround=timedelta(minutes=30))
        svc.add_vehicle(car("V1"))
        c = svc.register_customer("B", "b@x", "DL2")
        svc.create_reservation(c.customer_id, "V1", at(14, 10), at(14, 12), "A", "A")
        with self.assertRaises(VehicleUnavailableError) as ctx:
            svc.create_reservation(c.customer_id, "V1", at(14, 12, 15), at(14, 13, 15), "A", "A")
        self.assertEqual(ctx.exception.next_free, at(14, 12, 30))
        svc.create_reservation(c.customer_id, "V1", at(14, 12, 30), at(14, 13, 30), "A", "A")

    def test_next_free_skips_gaps_that_are_too_small(self):
        self.book(at(14, 10), at(14, 12))
        self.book(at(14, 13), at(14, 15))
        with self.assertRaises(VehicleUnavailableError) as ctx:
            self.book(at(14, 11), at(14, 13))                              # needs 2 h; 12-13 gap too small
        self.assertEqual(ctx.exception.next_free, at(14, 15))

    def test_maintenance_blocks_and_is_blocked(self):
        self.svc.schedule_maintenance("V1", at(14, 0), at(14, 12))
        with self.assertRaises(VehicleUnavailableError):
            self.book(at(14, 11), at(14, 13))
        self.book(at(15, 9), at(15, 11))
        with self.assertRaises(VehicleUnavailableError):
            self.svc.schedule_maintenance("V1", at(15, 10), at(15, 12))

    def test_validation(self):
        with self.assertRaises(InvalidRequestError):
            self.book(at(13, 7), at(13, 9))                                # in the past
        with self.assertRaises(InvalidRequestError):
            self.book(at(14, 10), at(14, 10, 30))                          # under 1 h
        with self.assertRaises(InvalidRequestError):
            self.book(at(14, 12), at(14, 10))

    def test_search_filters_and_sorts_by_price(self):
        self.svc.add_vehicle(car("V2", VehicleType.SUV, hourly="15", daily="90"))
        self.svc.add_vehicle(car("V3", VehicleType.SEDAN, hourly="5", daily="30", location="City"))
        self.book(at(14, 9), at(14, 11))
        ids = [v.vehicle_id for v in self.svc.search.search_available(at(14, 10), at(14, 12))]
        self.assertEqual(ids, ["V3", "V2"])
        ids = [v.vehicle_id for v in self.svc.search.search_available(at(14, 10), at(14, 12), location="Airport")]
        self.assertEqual(ids, ["V2"])


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.clock = FixedClock(NOW)
        self.svc = CarRentalService(clock=self.clock, turnaround=timedelta(0))
        self.v = car("V1", hourly="10", daily="60")
        self.svc.add_vehicle(self.v)
        self.a = self.svc.register_customer("A", "a@x", "DL1")
        self.b = self.svc.register_customer("B", "b@x", "DL2")

    def hold(self, cust, start=at(14, 10), end=at(14, 13)):
        return self.svc.create_reservation(cust.customer_id, "V1", start, end, "Airport", "Airport")

    def test_happy_path(self):
        r = self.hold(self.a)
        self.assertEqual(r.status, ReservationStatus.PENDING)
        self.assertEqual(r.quoted_amount, D("30.00"))
        self.svc.confirm_reservation(r.reservation_id)
        self.svc.start_rental(r.reservation_id)
        self.assertEqual(self.v.status, VehicleStatus.RENTED)
        self.assertEqual(self.svc.complete_rental(r.reservation_id, at(14, 13, 10)), D("30.00"))  # in grace
        self.assertEqual(r.status, ReservationStatus.COMPLETED)
        self.assertEqual(self.v.status, VehicleStatus.AVAILABLE)
        self.assertEqual(self.a.loyalty_points, 6)

    def test_late_return_is_repriced(self):
        r = self.hold(self.a)
        self.svc.confirm_reservation(r.reservation_id)
        self.svc.start_rental(r.reservation_id)
        self.assertEqual(self.svc.complete_rental(r.reservation_id, at(14, 14, 30)), D("50.00"))  # 5 h

    def test_illegal_transitions(self):
        r = self.hold(self.a)
        with self.assertRaises(InvalidTransitionError):
            self.svc.start_rental(r.reservation_id)                        # not confirmed
        self.svc.confirm_reservation(r.reservation_id)
        self.svc.start_rental(r.reservation_id)
        with self.assertRaises(InvalidTransitionError):
            self.svc.cancel_reservation(r.reservation_id)                  # already driving
        self.svc.complete_rental(r.reservation_id)
        with self.assertRaises(InvalidTransitionError):
            self.svc.start_rental(r.reservation_id)

    def test_cancel_frees_the_slot_only_for_that_reservation(self):
        r1 = self.hold(self.a, at(14, 10), at(14, 12))
        self.hold(self.b, at(14, 12), at(14, 14))
        self.svc.cancel_reservation(r1.reservation_id)
        self.assertTrue(self.svc.calendar.is_available("V1", at(14, 10), at(14, 12)))
        self.assertFalse(self.svc.calendar.is_available("V1", at(14, 12), at(14, 13)))

    def test_hold_expiry_frees_slot_and_blocks_late_confirm(self):
        r = self.hold(self.a)
        self.clock.advance(timedelta(minutes=10))                          # TTL reached
        other = self.hold(self.b)                                          # expired hold is ignored
        with self.assertRaises(HoldExpiredError):
            self.svc.confirm_reservation(r.reservation_id)
        self.assertEqual(r.status, ReservationStatus.EXPIRED)
        self.svc.confirm_reservation(other.reservation_id)

    def test_expire_sweep(self):
        r = self.hold(self.a)
        self.clock.advance(timedelta(minutes=5))
        self.assertEqual(self.svc.expire_holds(), [])
        self.clock.advance(timedelta(minutes=6))
        self.assertEqual(self.svc.expire_holds(), [r.reservation_id])
        self.assertTrue(self.svc.calendar.is_available("V1", at(14, 10), at(14, 13)))

    def test_confirmed_booking_never_expires(self):
        r = self.hold(self.a)
        self.svc.confirm_reservation(r.reservation_id)
        self.clock.advance(timedelta(hours=1))
        with self.assertRaises(VehicleUnavailableError):
            self.hold(self.b)


class ConcurrencyTest(unittest.TestCase):
    def test_overlapping_requests_one_winner(self):
        for _ in range(20):
            svc = CarRentalService(clock=FixedClock(NOW), turnaround=timedelta(0))
            svc.add_vehicle(car("V1"))
            custs = [svc.register_customer(f"c{i}", f"{i}@x", f"DL{i}") for i in range(12)]
            barrier, wins, losses = threading.Barrier(len(custs)), [], []

            def go(i, c):
                barrier.wait()
                start = at(14, 10) + timedelta(minutes=10 * i)     # all mutually overlapping
                try:
                    wins.append(svc.create_reservation(c.customer_id, "V1", start,
                                                       start + timedelta(hours=3), "A", "A"))
                except VehicleUnavailableError:
                    losses.append(c)

            ts = [threading.Thread(target=go, args=(i, c)) for i, c in enumerate(custs)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(len(wins), 1)
            self.assertEqual(len(losses), 11)

    def test_disjoint_requests_all_succeed(self):
        svc = CarRentalService(clock=FixedClock(NOW), turnaround=timedelta(0))
        svc.add_vehicle(car("V1"))
        custs = [svc.register_customer(f"c{i}", f"{i}@x", f"DL{i}") for i in range(12)]
        barrier, wins = threading.Barrier(len(custs)), []

        def go(i, c):
            barrier.wait()
            start = at(14, 0) + timedelta(hours=2 * i)
            wins.append(svc.create_reservation(c.customer_id, "V1", start,
                                               start + timedelta(hours=2), "A", "A"))

        ts = [threading.Thread(target=go, args=(i, c)) for i, c in enumerate(custs)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(wins), 12)
        self.assertEqual(svc.calendar.free_hours("V1", date(2025, 1, 14)), [])

    def test_confirm_vs_cancel_race(self):
        for _ in range(50):
            svc = CarRentalService(clock=FixedClock(NOW), turnaround=timedelta(0))
            svc.add_vehicle(car("V1"))
            c = svc.register_customer("c", "c@x", "DL")
            r = svc.create_reservation(c.customer_id, "V1", at(14, 10), at(14, 12), "A", "A")
            barrier, ok = threading.Barrier(2), []

            def attempt(fn):
                barrier.wait()
                try:
                    fn(r.reservation_id)
                    ok.append(fn.__name__)
                except InvalidTransitionError:
                    pass

            ts = [threading.Thread(target=attempt, args=(f,))
                  for f in (svc.confirm_reservation, svc.cancel_reservation)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            # Either order is legal (PENDING->CANCELLED, or CONFIRMED->CANCELLED); what must
            # hold is that the calendar agrees with the final status.
            self.assertIn("cancel_reservation", ok)
            free =svc.calendar.is_available("V1", at(14, 10), at(14, 12))
            self.assertEqual(free, r.status is ReservationStatus.CANCELLED)


if __name__ == "__main__":
    unittest.main()
