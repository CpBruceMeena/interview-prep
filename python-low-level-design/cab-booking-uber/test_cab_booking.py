import threading
import unittest
from decimal import Decimal

from cab_booking import (
    CabBookingService, CabStatus, CabType, GeoIndex, HighestRatedDriverMatching,
    InvalidTransitionError, KafkaBroker, Location, NoDriverAvailableError,
    RiderBusyError, StandardPricing, SurgePricing, TripStatus, compute_surge,
    geohash_encode, GPS_DLQ, GPS_RAW,
)

CENTER = Location(19.0760, 72.8777)
DROP = Location(19.1000, 72.9000)


def offset(km_north: float = 0.0, km_east: float = 0.0, base: Location = CENTER) -> Location:
    import math
    return Location(base.lat + km_north / 111.32,
                    base.lng + km_east / (111.32 * math.cos(math.radians(base.lat))))


class GeoIndexTest(unittest.TestCase):
    def test_geohash_known_value(self):
        # Reference value for (57.64911, 10.40744) from the original geohash spec.
        self.assertEqual(geohash_encode(57.64911, 10.40744, 11), "u4pruydqqvj")

    def test_search_returns_sorted_and_respects_radius(self):
        g = GeoIndex()
        g.upsert("near", offset(0.5), ts=1)
        g.upsert("mid", offset(1.5), ts=1)
        g.upsert("far", offset(8.0), ts=1)
        hits = g.search(CENTER, 2.0)
        self.assertEqual([h[0] for h in hits], ["near", "mid"])
        self.assertLess(hits[0][1], hits[1][1])

    def test_search_finds_points_across_cell_boundaries(self):
        # A 1 km ring of points in 8 directions: whichever cell CENTER is in,
        # several of these land in neighbouring cells and must still be found.
        g = GeoIndex()
        dirs = [(1, 0), (-1, 0), (0, 1), (0, -1), (0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7)]
        for i, (n, e) in enumerate(dirs):
            g.upsert(f"d{i}", offset(n, e), ts=1)
        self.assertEqual(len(g.search(CENTER, 1.2)), 8)

    def test_search_across_antimeridian(self):
        g = GeoIndex()
        g.upsert("east", Location(0.0, 179.995), ts=1)
        hits = g.search(Location(0.0, -179.995), 2.0)
        self.assertEqual([h[0] for h in hits], ["east"])

    def test_stale_update_is_ignored_and_move_reindexes(self):
        g = GeoIndex()
        g.upsert("d", offset(0.2), ts=10)
        self.assertFalse(g.upsert("d", offset(9.0), ts=5))      # out-of-order
        self.assertEqual(len(g.search(CENTER, 1.0)), 1)
        self.assertTrue(g.upsert("d", offset(9.0), ts=11))      # real move
        self.assertEqual(g.search(CENTER, 1.0), [])
        self.assertEqual(len(g), 1)


class PricingAndSurgeTest(unittest.TestCase):
    def test_standard_fare_is_exact_decimal(self):
        fare = StandardPricing(CabType.MINI).calculate_fare(10, 20)
        self.assertEqual(fare, Decimal("170.00"))  # 50 + 10*10 + 1*20

    def test_surge_decorates_base(self):
        fare = SurgePricing(StandardPricing(CabType.MINI), Decimal("1.5")).calculate_fare(10, 20)
        self.assertEqual(fare, Decimal("255.00"))

    def test_surge_curve(self):
        self.assertEqual(compute_surge(0, 0), Decimal("1.0"))   # no demand, no surge
        self.assertEqual(compute_surge(3, 0), Decimal("2.5"))
        self.assertEqual(compute_surge(7, 2), Decimal("2.0"))
        self.assertEqual(compute_surge(2, 2), Decimal("1.0"))


class TripLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.svc = CabBookingService()
        self.rider = self.svc.register_rider("Alice", "1")
        self.d1 = self.svc.register_driver("Bob", "2", "L1", CabType.MINI)
        self.d2 = self.svc.register_driver("Cara", "3", "L2", CabType.MINI)
        self.svc.update_driver_location(self.d1.driver_id, offset(0.3), ts=1)
        self.svc.update_driver_location(self.d2.driver_id, offset(1.0), ts=1)

    def test_happy_path_and_driver_status(self):
        trip = self.svc.request_ride(self.rider.rider_id, CENTER, DROP)
        self.assertIs(trip.driver, self.d1)                       # nearest
        self.assertEqual(self.d1.status, CabStatus.BOOKED)
        self.svc.accept_trip(trip.trip_id)
        self.svc.driver_arrived(trip.trip_id)
        self.svc.start_trip(trip.trip_id)
        self.assertEqual(self.d1.status, CabStatus.ON_TRIP)
        self.assertEqual(self.svc.complete_trip(trip.trip_id), trip.fare)
        self.assertEqual(trip.status, TripStatus.COMPLETED)
        self.assertEqual(self.d1.status, CabStatus.AVAILABLE)

    def test_illegal_transitions_rejected(self):
        trip = self.svc.request_ride(self.rider.rider_id, CENTER, DROP)
        with self.assertRaises(InvalidTransitionError):
            self.svc.start_trip(trip.trip_id)                     # must accept + arrive first
        for step in (self.svc.accept_trip, self.svc.driver_arrived, self.svc.start_trip):
            step(trip.trip_id)
        with self.assertRaises(InvalidTransitionError):
            self.svc.cancel_trip(trip.trip_id)                    # no cancel once started
        self.svc.complete_trip(trip.trip_id)
        with self.assertRaises(InvalidTransitionError):
            self.svc.cancel_trip(trip.trip_id)
        self.assertEqual(self.d1.status, CabStatus.AVAILABLE)

    def test_cancel_frees_driver_and_rider(self):
        trip = self.svc.request_ride(self.rider.rider_id, CENTER, DROP)
        self.svc.accept_trip(trip.trip_id)
        self.svc.cancel_trip(trip.trip_id)
        self.assertEqual(self.d1.status, CabStatus.AVAILABLE)
        self.svc.request_ride(self.rider.rider_id, CENTER, DROP)  # rider may book again

    def test_rider_cannot_hold_two_active_trips(self):
        self.svc.request_ride(self.rider.rider_id, CENTER, DROP)
        with self.assertRaises(RiderBusyError):
            self.svc.request_ride(self.rider.rider_id, CENTER, DROP)

    def test_decline_rematches_then_cancels_when_exhausted(self):
        trip = self.svc.request_ride(self.rider.rider_id, CENTER, DROP)
        self.svc.decline_trip(trip.trip_id)
        self.assertIs(trip.driver, self.d2)
        self.assertEqual(self.d1.status, CabStatus.AVAILABLE)
        self.svc.decline_trip(trip.trip_id)                       # d1 already declined: not re-offered
        self.assertEqual(trip.status, TripStatus.CANCELLED)
        self.assertEqual(self.d2.status, CabStatus.AVAILABLE)

    def test_filters_cab_type_offline_and_radius(self):
        self.svc.go_offline(self.d1.driver_id)
        trip = self.svc.request_ride(self.rider.rider_id, CENTER, DROP)
        self.assertIs(trip.driver, self.d2)
        r2 = self.svc.register_rider("Bo", "9")
        with self.assertRaises(NoDriverAvailableError):
            self.svc.request_ride(r2.rider_id, CENTER, DROP, CabType.SUV)
        far = self.svc.register_rider("Far", "8")
        self.svc.go_online(self.d1.driver_id)
        with self.assertRaises(NoDriverAvailableError):
            self.svc.request_ride(far.rider_id, offset(50), DROP)
        self.assertFalse(self.svc.go_offline(self.d2.driver_id))  # booked: cannot go offline

    def test_highest_rated_strategy(self):
        self.d2.add_rating(5)
        self.d1.add_rating(1)
        self.svc.set_matching_strategy(HighestRatedDriverMatching())
        trip = self.svc.request_ride(self.rider.rider_id, CENTER, DROP)
        self.assertIs(trip.driver, self.d2)


class PipelineTest(unittest.TestCase):
    def test_gps_through_kafka_and_surge(self):
        broker = KafkaBroker()
        svc = CabBookingService(broker=broker)
        d = svc.register_driver("Bob", "2", "L1", CabType.MINI)
        svc.update_driver_location(d.driver_id, offset(0.1), ts=1)
        self.assertEqual(len(svc.geo_index), 1)
        riders = [svc.register_rider(f"r{i}", str(i)) for i in range(4)]
        trip = svc.request_ride(riders[0].rider_id, CENTER, DROP)
        for r in riders[1:]:
            with self.assertRaises(NoDriverAvailableError):
                svc.request_ride(r.rider_id, CENTER, DROP)
        svc.zone_analytics.aggregate()
        zone = svc.zone_manager.zone_for(CENTER)
        self.assertEqual(zone.ride_request_count, 4)
        svc.cancel_trip(trip.trip_id)
        svc.zone_analytics.aggregate()                            # window closed: demand reset
        self.assertEqual(zone.ride_request_count, 0)
        self.assertEqual(zone.surge_multiplier, Decimal("1.0"))

    def test_malformed_gps_goes_to_dlq(self):
        broker = KafkaBroker()
        svc = CabBookingService(broker=broker)
        broker.produce(GPS_RAW, "x", {"driver_id": "x", "lat": "not-a-number", "lng": 1, "ts": 1})
        svc._gps.poll()
        self.assertEqual(broker.topic_size(GPS_DLQ), 1)


class ConcurrencyTest(unittest.TestCase):
    def test_one_driver_is_never_double_booked(self):
        for _ in range(20):
            svc = CabBookingService()
            d = svc.register_driver("Solo", "1", "L", CabType.MINI)
            svc.update_driver_location(d.driver_id, offset(0.2), ts=1)
            riders = [svc.register_rider(f"r{i}", str(i)) for i in range(16)]
            barrier = threading.Barrier(len(riders))
            trips, misses = [], []

            def go(rider):
                barrier.wait()
                try:
                    trips.append(svc.request_ride(rider.rider_id, CENTER, DROP))
                except NoDriverAvailableError:
                    misses.append(rider)

            threads = [threading.Thread(target=go, args=(r,)) for r in riders]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(trips), 1)
            self.assertEqual(len(misses), 15)

    def test_n_drivers_n_riders_each_driver_used_once(self):
        svc = CabBookingService()
        n = 12
        for i in range(n):
            d = svc.register_driver(f"d{i}", str(i), f"L{i}", CabType.MINI)
            svc.update_driver_location(d.driver_id, offset(0.1 * i), ts=1)
        riders = [svc.register_rider(f"r{i}", str(i)) for i in range(n)]
        barrier = threading.Barrier(n)
        trips = []
        threads = [threading.Thread(target=lambda r=r: (barrier.wait(), trips.append(
            svc.request_ride(r.rider_id, CENTER, DROP)))) for r in riders]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(trips), n)                           # nobody starved: losers moved on
        self.assertEqual(len({t.driver.driver_id for t in trips}), n)

    def test_cancel_vs_start_race_has_one_winner(self):
        for _ in range(50):
            svc = CabBookingService()
            r = svc.register_rider("A", "1")
            d = svc.register_driver("B", "2", "L", CabType.MINI)
            svc.update_driver_location(d.driver_id, offset(0.2), ts=1)
            trip = svc.request_ride(r.rider_id, CENTER, DROP)
            svc.accept_trip(trip.trip_id)
            svc.driver_arrived(trip.trip_id)
            results = []
            barrier = threading.Barrier(2)

            def attempt(fn):
                barrier.wait()
                try:
                    fn(trip.trip_id)
                    results.append(fn.__name__)
                except InvalidTransitionError:
                    pass

            ts = [threading.Thread(target=attempt, args=(f,)) for f in (svc.start_trip, svc.cancel_trip)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(len(results), 1)
            expected = CabStatus.ON_TRIP if results == ["start_trip"] else CabStatus.AVAILABLE
            self.assertEqual(d.status, expected)


if __name__ == "__main__":
    unittest.main()
