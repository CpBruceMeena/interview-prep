import threading
import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from parking_lot import (
    Car, DailyFeeCalculator, HourlyFeeCalculator, InvalidTicketError,
    ManualClock, Motorcycle, ParkingFloor, ParkingFullError, ParkingLot,
    ParkingSpot, ParkingTicketStatus, SpotAllocationMapping, SpotType, Truck,
    VehicleAlreadyParkedError, VehicleFactory, VehicleType, setup_parking_lot,
)


def small_lot(clock=None):
    lot = ParkingLot("Test", HourlyFeeCalculator(), clock=clock or ManualClock(datetime(2025, 1, 1)))
    f1 = ParkingFloor(1)
    f1.add_spot(ParkingSpot("M1", 1, SpotType.MOTORCYCLE))
    f1.add_spot(ParkingSpot("C1", 1, SpotType.COMPACT))
    f1.add_spot(ParkingSpot("L1", 1, SpotType.LARGE))
    lot.add_floor(f1)
    f2 = ParkingFloor(2)
    f2.add_spot(ParkingSpot("C2", 2, SpotType.COMPACT))
    lot.add_floor(f2)
    return lot


class AllocationTest(unittest.TestCase):
    def test_allowed_spots_are_best_fit_ordered(self):
        self.assertEqual(SpotAllocationMapping.get_allowed_spots(Motorcycle("m")),
                         (SpotType.MOTORCYCLE, SpotType.COMPACT, SpotType.LARGE))
        self.assertEqual(SpotAllocationMapping.get_allowed_spots(Car("c")),
                         (SpotType.COMPACT, SpotType.LARGE))
        self.assertEqual(SpotAllocationMapping.get_allowed_spots(Truck("t")),
                         (SpotType.LARGE,))

    def test_car_prefers_compact_on_any_floor_over_large(self):
        lot = small_lot()
        self.assertEqual(lot.park_vehicle(Car("A")).spot.spot_id, "C1")
        # next compact is on floor 2; still preferred over the free LARGE on floor 1
        self.assertEqual(lot.park_vehicle(Car("B")).spot.spot_id, "C2")
        self.assertEqual(lot.park_vehicle(Car("C")).spot.spot_id, "L1")
        with self.assertRaises(ParkingFullError):
            lot.park_vehicle(Car("D"))

    def test_motorcycle_falls_back_to_larger_spots(self):
        lot = small_lot()
        spots = [lot.park_vehicle(Motorcycle(f"M{i}")).spot.spot_id for i in range(4)]
        self.assertEqual(spots, ["M1", "C1", "C2", "L1"])

    def test_truck_only_large(self):
        lot = small_lot()
        lot.park_vehicle(Truck("T1"))
        with self.assertRaises(ParkingFullError):
            lot.park_vehicle(Truck("T2"))
        self.assertEqual(lot.available_count(), 3)

    def test_floors_sorted_regardless_of_add_order(self):
        lot = ParkingLot("x", HourlyFeeCalculator())
        f3, f1 = ParkingFloor(3), ParkingFloor(1)
        f3.add_spot(ParkingSpot("X", 3, SpotType.COMPACT))
        f1.add_spot(ParkingSpot("Y", 1, SpotType.COMPACT))
        lot.add_floor(f3)
        lot.add_floor(f1)
        self.assertEqual(lot.park_vehicle(Car("A")).spot.spot_id, "Y")

    def test_floor_rejects_bad_spots(self):
        floor = ParkingFloor(1)
        floor.add_spot(ParkingSpot("A", 1, SpotType.COMPACT))
        with self.assertRaises(ValueError):
            floor.add_spot(ParkingSpot("A", 1, SpotType.COMPACT))
        with self.assertRaises(ValueError):
            floor.add_spot(ParkingSpot("B", 2, SpotType.COMPACT))


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.clock = ManualClock(datetime(2025, 1, 1, 9, 0))
        self.lot = small_lot(self.clock)

    def test_park_and_unpark_frees_spot_and_charges(self):
        t = self.lot.park_vehicle(Car("A"))
        self.clock.advance(minutes=61)
        fee = self.lot.unpark_vehicle(t.ticket_id)
        self.assertEqual(fee, Decimal("40.00"))
        self.assertIsInstance(fee, Decimal)
        self.assertEqual(t.status, ParkingTicketStatus.PAID)
        self.assertEqual(t.exit_time, datetime(2025, 1, 1, 10, 1))
        self.assertTrue(t.spot.is_available)
        # spot is reusable and the plate can park again
        self.assertEqual(self.lot.park_vehicle(Car("A")).spot.spot_id, "C1")

    def test_double_unpark_and_unknown_ticket_rejected(self):
        t = self.lot.park_vehicle(Car("A"))
        self.lot.unpark_vehicle(t.ticket_id)
        with self.assertRaises(InvalidTicketError):
            self.lot.unpark_vehicle(t.ticket_id)
        with self.assertRaises(InvalidTicketError):
            self.lot.unpark_vehicle("nope")
        self.assertEqual(self.lot.available_count(), 4)

    def test_same_plate_cannot_park_twice(self):
        self.lot.park_vehicle(Car("A"))
        with self.assertRaises(VehicleAlreadyParkedError):
            self.lot.park_vehicle(Car("A"))

    def test_lost_ticket(self):
        t = self.lot.park_vehicle(Motorcycle("B"))
        self.clock.advance(minutes=30)
        fee = self.lot.unpark_lost_ticket("B")
        self.assertEqual(fee, Decimal("10.00") + ParkingLot.LOST_TICKET_PENALTY)
        self.assertEqual(t.status, ParkingTicketStatus.LOST)
        with self.assertRaises(InvalidTicketError):
            self.lot.unpark_vehicle(t.ticket_id)
        with self.assertRaises(InvalidTicketError):
            self.lot.unpark_lost_ticket("B")

    def test_strategy_swap_applies_at_close(self):
        t = self.lot.park_vehicle(Car("A"))
        self.clock.advance(hours=25)
        self.lot.set_fee_calculator(DailyFeeCalculator())
        self.assertEqual(self.lot.unpark_vehicle(t.ticket_id), Decimal("200.00"))


class FeeTest(unittest.TestCase):
    def test_hourly_rounding(self):
        calc = HourlyFeeCalculator()
        self.assertEqual(calc.calculate_fee(timedelta(0), SpotType.COMPACT), Decimal("20.00"))
        self.assertEqual(calc.calculate_fee(timedelta(hours=1), SpotType.COMPACT), Decimal("20.00"))
        self.assertEqual(calc.calculate_fee(timedelta(hours=1, seconds=1), SpotType.COMPACT),
                         Decimal("40.00"))
        self.assertEqual(calc.calculate_fee(timedelta(hours=3), SpotType.LARGE), Decimal("90.00"))

    def test_daily_rounding(self):
        calc = DailyFeeCalculator()
        self.assertEqual(calc.calculate_fee(timedelta(hours=24), SpotType.MOTORCYCLE),
                         Decimal("50.00"))
        self.assertEqual(calc.calculate_fee(timedelta(hours=24, minutes=1), SpotType.MOTORCYCLE),
                         Decimal("100.00"))


class FactoryTest(unittest.TestCase):
    def test_create(self):
        v = VehicleFactory.create_vehicle(VehicleType.TRUCK, "T")
        self.assertIsInstance(v, Truck)
        self.assertEqual(v.license_plate, "T")
        with self.assertRaises(ValueError):
            VehicleFactory.create_vehicle(VehicleType.CAR, "")


class ConcurrencyTest(unittest.TestCase):
    def test_no_double_allocation_under_contention(self):
        lot = setup_parking_lot()          # 35 compact + 20 large = 55 car-capable spots
        n_threads = 100
        barrier = threading.Barrier(n_threads)
        tickets, full = [], []
        sink_lock = threading.Lock()

        def worker(i):
            barrier.wait()
            try:
                t = lot.park_vehicle(Car(f"CAR-{i}"))
                with sink_lock:
                    tickets.append(t)
            except ParkingFullError:
                with sink_lock:
                    full.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(tickets), 55)
        self.assertEqual(len(full), 45)
        self.assertEqual(len({t.spot.spot_id for t in tickets}), 55)
        self.assertEqual(len({t.ticket_id for t in tickets}), 55)
        self.assertEqual(lot.available_count(SpotType.COMPACT), 0)
        self.assertEqual(lot.available_count(SpotType.LARGE), 0)

    def test_concurrent_unpark_same_ticket_charges_once(self):
        lot = small_lot()
        t = lot.park_vehicle(Car("A"))
        results, errors = [], []
        barrier = threading.Barrier(20)

        def worker():
            barrier.wait()
            try:
                results.append(lot.unpark_vehicle(t.ticket_id))
            except InvalidTicketError:
                errors.append(1)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 19)
        self.assertEqual(lot.available_count(), 4)


if __name__ == "__main__":
    unittest.main()
