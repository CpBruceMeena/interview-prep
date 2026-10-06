import threading
import unittest
from decimal import Decimal

from food_delivery import (
    Actor, BatchingStrategy, Cart, Coupon, CouponType, Customer, DeliveryPartner,
    DifferentRestaurantError, DispatchService, FakePaymentGateway,
    IdempotencyConflictError, InvalidCouponError, InvalidTransitionError,
    ItemUnavailableError, Location, MenuItem, NearestAvailableStrategy,
    NotAuthorizedError, NotificationObserver, OrderObserver, OrderService,
    OrderStatus, PaymentFailedError, Restaurant, RestaurantClosedError, build_demo,
    money,
)


def make_restaurant(rid="R1", lat=12.9716):
    r = Restaurant(rid, f"Rest {rid}", Location(lat, 77.5946), packaging_fee="10")
    r.add_item(MenuItem("A", "Dosa", Decimal("100")))
    r.add_item(MenuItem("B", "Coffee", Decimal("30.25")))
    return r


CUSTOMER = Customer("C1", "Asha", Location(12.9716, 77.5946))  # same spot as R1


def make_service(strategy=None, partners=(), fail_customers=()):
    dispatch = DispatchService(strategy or NearestAvailableStrategy(radius_km=10))
    for p in partners:
        dispatch.register(p)
    payments = FakePaymentGateway(fail_customers)
    service = OrderService(dispatch, payments)
    service.add_restaurant(make_restaurant())
    return service, dispatch, payments


def cart_with(service, items=(("A", 1),), customer=CUSTOMER, rid="R1"):
    cart = Cart(customer)
    for item, qty in items:
        cart.add(service._restaurants[rid], item, qty)
    return cart


class CartTests(unittest.TestCase):
    def test_single_restaurant_rule(self):
        r1, r2 = make_restaurant("R1"), make_restaurant("R2")
        cart = Cart(CUSTOMER)
        cart.add(r1, "A")
        with self.assertRaises(DifferentRestaurantError):
            cart.add(r2, "A")
        cart.add(r2, "B", 2, replace_cart=True)
        self.assertIs(cart.restaurant, r2)
        self.assertEqual(cart.quantities, {"B": 2})

    def test_remove_last_item_frees_restaurant(self):
        r1 = make_restaurant()
        cart = Cart(CUSTOMER)
        cart.add(r1, "A", 2)
        cart.remove("A", 5)
        self.assertTrue(cart.is_empty)
        self.assertIsNone(cart.restaurant)

    def test_unknown_item(self):
        with self.assertRaises(ItemUnavailableError):
            Cart(CUSTOMER).add(make_restaurant(), "ZZZ")


class PricingTests(unittest.TestCase):
    def test_money_rejects_float(self):
        with self.assertRaises(TypeError):
            money(0.1)

    def test_breakdown_is_exact(self):
        service, _, _ = make_service()
        bill = service.quote(cart_with(service, [("A", 1), ("B", 3)]))
        # items 100 + 90.75; packaging 10; delivery base 25 (0 km); tax 5% of 190.75 = 9.5375
        self.assertEqual(bill.amount_of("ITEMS"), Decimal("190.75"))
        self.assertEqual(bill.amount_of("DELIVERY"), Decimal("25.00"))
        self.assertEqual(bill.amount_of("TAX"), Decimal("9.54"))
        self.assertEqual(bill.total, Decimal("235.29"))

    def test_delivery_fee_charges_partial_km(self):
        service, _, _ = make_service()
        far = Customer("C2", "B", Location(12.9716 + 0.03, 77.5946))  # ~3.34 km
        bill = service.quote(cart_with(service, customer=far))
        self.assertEqual(bill.amount_of("DELIVERY"), Decimal("41.00"))  # 25 + 2 * 8

    def test_surge_scales_delivery_only(self):
        service, _, _ = make_service()
        service.surge_multiplier = Decimal("1.5")
        bill = service.quote(cart_with(service))
        self.assertEqual(bill.amount_of("SURGE"), Decimal("12.50"))
        self.assertEqual(bill.amount_of("ITEMS"), Decimal("100.00"))

    def test_coupon_cap_min_and_unknown(self):
        service, _, _ = make_service()
        service.add_coupon(Coupon("P50", CouponType.PERCENT, Decimal("50"),
                                  min_subtotal=Decimal("150"), max_discount=Decimal("60")))
        service.add_coupon(Coupon("FLAT500", CouponType.FLAT, Decimal("500")))
        with self.assertRaises(InvalidCouponError):
            service.quote(cart_with(service), "P50")  # subtotal 100 < 150
        with self.assertRaises(InvalidCouponError):
            service.quote(cart_with(service), "NOPE")
        bill = service.quote(cart_with(service, [("A", 2)]), "P50")
        self.assertEqual(bill.amount_of("COUPON"), Decimal("-60.00"))  # 50% of 200 capped
        flat = service.quote(cart_with(service), "FLAT500")
        self.assertEqual(flat.amount_of("COUPON"), Decimal("-100.00"))  # never beyond food
        self.assertEqual(flat.amount_of("TAX"), Decimal("0.00"))


class PlacementTests(unittest.TestCase):
    def test_idempotent_retry_returns_same_order(self):
        service, _, payments = make_service()
        a = service.place_order(cart_with(service), "k1")
        b = service.place_order(cart_with(service), "k1")
        self.assertIs(a, b)
        self.assertEqual(len(payments.charges), 1)

    def test_same_key_different_cart_conflicts(self):
        service, _, _ = make_service()
        service.place_order(cart_with(service), "k1")
        with self.assertRaises(IdempotencyConflictError):
            service.place_order(cart_with(service, [("B", 1)]), "k1")

    def test_failed_payment_is_retryable_and_creates_nothing(self):
        service, _, payments = make_service(fail_customers={"C1"})
        with self.assertRaises(PaymentFailedError):
            service.place_order(cart_with(service), "k1")
        self.assertEqual(service._orders, {})
        payments._fail.clear()
        order = service.place_order(cart_with(service), "k1")
        self.assertEqual(order.status, OrderStatus.PLACED)

    def test_closed_restaurant_and_out_of_stock(self):
        service, _, _ = make_service()
        r = service._restaurants["R1"]
        r.set_availability("A", False)
        with self.assertRaises(ItemUnavailableError):
            service.place_order(cart_with(service), "k1")
        r.set_availability("A", True)
        r.is_open = False
        with self.assertRaises(RestaurantClosedError):
            service.place_order(cart_with(service), "k2")

    def test_concurrent_duplicates_create_one_order(self):
        service, _, payments = make_service()
        results, barrier = [], threading.Barrier(16)

        def tap():
            barrier.wait()
            results.append(service.place_order(cart_with(service), "same-key"))

        threads = [threading.Thread(target=tap) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len({id(o) for o in results}), 1)
        self.assertEqual(len(service._orders), 1)
        self.assertEqual(len(payments.charges), 1)


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.partner = DeliveryPartner("P1", "Ravi", Location(12.9716, 77.5946))
        self.service, self.dispatch, self.payments = make_service(partners=[self.partner])
        self.order = self.service.place_order(cart_with(self.service), "k")

    def test_happy_path(self):
        oid = self.order.order_id
        self.assertIs(self.service.accept(oid), self.partner)
        self.service.start_preparing(oid)
        self.service.mark_ready(oid)
        self.service.pick_up(oid, "P1")
        self.service.deliver(oid, "P1")
        self.assertEqual(self.order.status, OrderStatus.DELIVERED)
        self.assertEqual(self.partner.active_orders, [])
        self.assertEqual([s for s, _ in self.order.history][-1], OrderStatus.DELIVERED)

    def test_illegal_jump(self):
        with self.assertRaises(InvalidTransitionError):
            self.service.mark_ready(self.order.order_id)

    def test_wrong_partner_cannot_pick_up(self):
        oid = self.order.order_id
        self.service.accept(oid)
        self.service.start_preparing(oid)
        self.service.mark_ready(oid)
        self.dispatch.register(DeliveryPartner("P9", "X", Location(0, 0)))
        with self.assertRaises(NotAuthorizedError):
            self.service.pick_up(oid, "P9")

    def test_cancel_rules_by_actor(self):
        oid = self.order.order_id
        with self.assertRaises(NotAuthorizedError):
            self.service.cancel(oid, Actor.PARTNER)
        self.service.accept(oid)
        self.service.start_preparing(oid)
        with self.assertRaises(NotAuthorizedError):
            self.service.cancel(oid, Actor.CUSTOMER)
        self.service.cancel(oid, Actor.RESTAURANT)
        self.assertEqual(self.order.status, OrderStatus.CANCELLED)
        self.assertEqual(self.partner.active_orders, [])  # partner freed
        self.assertIn(self.order.payment_id, self.payments.refunds)
        with self.assertRaises(InvalidTransitionError):
            self.service.cancel(oid, Actor.SYSTEM)  # terminal

    def test_reject_refunds(self):
        self.service.reject(self.order.order_id)
        self.assertEqual(self.order.status, OrderStatus.REJECTED)
        self.assertEqual(self.payments.refunds[self.order.payment_id], self.order.total)

    def test_cancel_vs_start_preparing_exactly_one_wins(self):
        oid = self.order.order_id
        self.service.accept(oid)
        barrier = threading.Barrier(2)
        won = []

        def run(name, fn):
            barrier.wait()
            try:
                fn()
                won.append(name)
            except (InvalidTransitionError, NotAuthorizedError):
                pass

        t1 = threading.Thread(target=run, args=("prep", lambda: self.service.start_preparing(oid)))
        t2 = threading.Thread(target=run, args=("cancel", lambda: self.service.cancel(oid, Actor.CUSTOMER)))
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(len(won), 1)
        expected = OrderStatus.PREPARING if won == ["prep"] else OrderStatus.CANCELLED
        self.assertEqual(self.order.status, expected)

    def test_cancel_between_rank_and_claim_does_not_leak_partner(self):
        """Forces the worst interleaving deterministically: the order is cancelled after
        the strategy ranked a partner but before the dispatcher claims/attaches."""
        partner = DeliveryPartner("PX", "p", Location(12.9716, 77.5946))
        holder = {}

        class CancelMidDispatch(NearestAvailableStrategy):
            def rank(self, order, restaurant, partners):
                ranked = super().rank(order, restaurant, partners)
                holder["service"].cancel(order.order_id, Actor.CUSTOMER)
                return ranked

        service, _, _ = make_service(CancelMidDispatch(radius_km=10), partners=[partner])
        holder["service"] = service
        order = service.place_order(cart_with(service), "k")
        self.assertIsNone(service.accept(order.order_id))
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertIsNone(order.partner_id)
        self.assertEqual(partner.active_orders, [])


class DispatchTests(unittest.TestCase):
    def test_nearest_idle_partner_wins(self):
        near = DeliveryPartner("NEAR", "n", Location(12.9720, 77.5946))
        far = DeliveryPartner("FAR", "f", Location(12.9900, 77.5946))
        service, _, _ = make_service(partners=[far, near])
        order = service.place_order(cart_with(service), "k")
        self.assertIs(service.accept(order.order_id), near)

    def test_offline_and_out_of_radius_skipped(self):
        off = DeliveryPartner("OFF", "o", Location(12.9716, 77.5946))
        off.set_online(False)
        remote = DeliveryPartner("REMOTE", "r", Location(13.5, 77.5946))
        service, _, _ = make_service(partners=[off, remote])
        order = service.place_order(cart_with(service), "k")
        self.assertIsNone(service.accept(order.order_id))
        off.set_online(True)
        self.assertIs(service.dispatch(order.order_id), off)  # retry succeeds

    def test_no_double_assignment_under_concurrency(self):
        partners = [DeliveryPartner(f"P{i}", "p", Location(12.9716 + i * 0.001, 77.5946))
                    for i in range(5)]
        service, _, _ = make_service(partners=partners)
        orders = [service.place_order(cart_with(service), f"k{i}") for i in range(20)]
        barrier = threading.Barrier(len(orders))
        assigned = []
        lock = threading.Lock()

        def accept(oid):
            barrier.wait()
            p = service.accept(oid)
            if p:
                with lock:
                    assigned.append(p.partner_id)

        threads = [threading.Thread(target=accept, args=(o.order_id,)) for o in orders]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(assigned), 5)
        self.assertEqual(len(set(assigned)), 5)
        for p in partners:
            self.assertEqual(len(p.active_orders), 1)
        self.assertEqual(sum(1 for o in orders if o.partner_id), 5)

    def test_cancel_during_dispatch_does_not_leak_partner(self):
        partner = DeliveryPartner("P1", "p", Location(12.9716, 77.5946))
        service, dispatch, _ = make_service(partners=[partner])
        order = service.place_order(cart_with(service), "k")
        service._move(order.order_id, OrderStatus.ACCEPTED, Actor.RESTAURANT)
        service.cancel(order.order_id, Actor.CUSTOMER)
        # A late dispatcher (e.g. a retry worker) must not attach to a cancelled order.
        self.assertIsNone(dispatch.assign(order, service._restaurants["R1"]))
        self.assertEqual(partner.active_orders, [])

    def test_batching_reuses_partner_until_pickup(self):
        partner = DeliveryPartner("P1", "p", Location(12.9716, 77.5946))
        other = DeliveryPartner("P2", "q", Location(12.9800, 77.5946))
        service, _, _ = make_service(BatchingStrategy(max_orders=2, radius_km=10),
                                     partners=[partner, other])
        o1, o2, o3 = (service.place_order(cart_with(service), f"k{i}") for i in range(3))
        self.assertIs(service.accept(o1.order_id), partner)
        self.assertIs(service.accept(o2.order_id), partner)  # batched, same restaurant
        self.assertIs(service.accept(o3.order_id), other)    # P1 at capacity
        self.assertEqual(sorted(partner.active_orders), [o1.order_id, o2.order_id])

    def test_batch_closes_after_pickup(self):
        partner = DeliveryPartner("P1", "p", Location(12.9716, 77.5946))
        service, _, _ = make_service(BatchingStrategy(max_orders=3, radius_km=10),
                                     partners=[partner])
        o1 = service.place_order(cart_with(service), "k1")
        service.accept(o1.order_id)
        service.start_preparing(o1.order_id)
        service.mark_ready(o1.order_id)
        service.pick_up(o1.order_id, "P1")
        o2 = service.place_order(cart_with(service), "k2")
        self.assertIsNone(service.accept(o2.order_id))
        service.deliver(o1.order_id, "P1")
        self.assertIs(service.dispatch(o2.order_id), partner)


class ObserverTests(unittest.TestCase):
    def test_events_in_order_and_broken_observer_isolated(self):
        class Boom(OrderObserver):
            def on_order_event(self, event):
                raise RuntimeError("boom")

        class Recorder(OrderObserver):
            def __init__(self):
                self.events = []

            def on_order_event(self, event):
                self.events.append(event)

        service, _, _ = make_service(partners=[DeliveryPartner("P1", "p", Location(12.9716, 77.5946))])
        rec, notifier = Recorder(), NotificationObserver()
        service.subscribe(Boom())
        service.subscribe(rec)
        service.subscribe(notifier)
        order = service.place_order(cart_with(service), "k")
        service.accept(order.order_id)
        service.cancel(order.order_id, Actor.CUSTOMER)
        self.assertEqual([e.seq for e in rec.events], [0, 1, 2])
        self.assertEqual([e.new_status for e in rec.events],
                         [OrderStatus.PLACED, OrderStatus.ACCEPTED, OrderStatus.CANCELLED])
        self.assertEqual(rec.events[-1].partner_id, "P1")  # who was released
        self.assertTrue(any("cancelled" in text for _, text in notifier.sent))


class DemoTest(unittest.TestCase):
    def test_demo_builds(self):
        service, *_ = build_demo()
        self.assertIsInstance(service, OrderService)


if __name__ == "__main__":
    unittest.main()
