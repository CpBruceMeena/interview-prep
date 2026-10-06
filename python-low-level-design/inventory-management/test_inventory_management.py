import threading
import unittest
from decimal import Decimal

from inventory_management import (
    DemandBasedReorderPolicy, GreedySplitAllocation, IdempotencyConflictError,
    InsufficientStockError, InvalidStateError, InventoryService, ManualClock,
    MovementType, NotFoundError, POStatus, Product, ReservationExpiredError,
    ReservationStatus, Warehouse,
)


def make_service(**kwargs) -> tuple[InventoryService, ManualClock]:
    clock = ManualClock()
    inv = InventoryService(clock=clock, reservation_ttl_s=600, **kwargs)
    inv.add_product(Product("A", "Widget", Decimal("2.50"), reorder_level=5, reorder_quantity=20))
    inv.add_product(Product("B", "Gadget", Decimal("10.00"), reorder_level=0, reorder_quantity=10))
    inv.add_warehouse(Warehouse("W1", "Near", priority=0))
    inv.add_warehouse(Warehouse("W2", "Far", priority=1))
    return inv, clock


class ReserveCommitReleaseTest(unittest.TestCase):
    def setUp(self):
        self.inv, self.clock = make_service()
        self.inv.receive_stock("A", "W1", 10)
        self.inv.receive_stock("A", "W2", 10)
        self.inv.receive_stock("B", "W1", 5)

    def test_reserve_holds_stock_without_moving_it(self):
        self.inv.reserve("o1", {"A": 4})
        self.assertEqual(self.inv.stock("A", "W1"), (10, 4, 6))

    def test_single_warehouse_preferred_when_one_can_fill(self):
        r = self.inv.reserve("o1", {"A": 10})
        self.assertEqual([(l.warehouse_id, l.quantity) for l in r.lines], [("W1", 10)])

    def test_splits_across_warehouses_when_needed(self):
        r = self.inv.reserve("o1", {"A": 15})
        self.assertEqual([(l.warehouse_id, l.quantity) for l in r.lines], [("W1", 10), ("W2", 5)])

    def test_greedy_split_strategy(self):
        inv, _ = make_service(allocation=GreedySplitAllocation())
        inv.receive_stock("A", "W1", 3)
        inv.receive_stock("A", "W2", 10)
        r = inv.reserve("o1", {"A": 5})
        self.assertEqual([(l.warehouse_id, l.quantity) for l in r.lines], [("W1", 3), ("W2", 2)])

    def test_multi_line_reservation_is_all_or_nothing(self):
        with self.assertRaises(InsufficientStockError):
            self.inv.reserve("o1", {"A": 1, "B": 6})
        self.assertEqual(self.inv.stock("A", "W1"), (10, 0, 10))
        self.assertEqual(self.inv.stock("B", "W1"), (5, 0, 5))

    def test_commit_ships_reserved_units_and_records_ledger(self):
        r = self.inv.reserve("o1", {"A": 12})
        self.inv.commit(r.reservation_id)
        self.assertEqual(self.inv.stock("A", "W1"), (0, 0, 0))
        self.assertEqual(self.inv.stock("A", "W2"), (8, 0, 8))
        ships = [m for m in self.inv.movements("A") if m.type is MovementType.SHIP]
        self.assertEqual(sorted(m.delta for m in ships), [-10, -2])

    def test_commit_is_idempotent(self):
        r = self.inv.reserve("o1", {"A": 2})
        self.inv.commit(r.reservation_id)
        self.inv.commit(r.reservation_id)
        self.assertEqual(self.inv.stock("A", "W1"), (8, 0, 8))

    def test_release_returns_stock_and_is_idempotent(self):
        r = self.inv.reserve("o1", {"A": 2})
        self.inv.release(r.reservation_id)
        self.inv.release(r.reservation_id)
        self.assertEqual(self.inv.stock("A", "W1"), (10, 0, 10))
        self.assertIs(r.status, ReservationStatus.RELEASED)

    def test_cannot_release_committed_or_commit_released(self):
        r1 = self.inv.reserve("o1", {"A": 1})
        self.inv.commit(r1.reservation_id)
        with self.assertRaises(InvalidStateError):
            self.inv.release(r1.reservation_id)
        r2 = self.inv.reserve("o2", {"A": 1})
        self.inv.release(r2.reservation_id)
        with self.assertRaises(InvalidStateError):
            self.inv.commit(r2.reservation_id)

    def test_reserve_is_idempotent_per_order(self):
        r = self.inv.reserve("o1", {"A": 3})
        self.assertIs(self.inv.reserve("o1", {"A": 3}), r)
        self.assertEqual(self.inv.stock("A", "W1"), (10, 3, 7))
        with self.assertRaises(IdempotencyConflictError):
            self.inv.reserve("o1", {"A": 4})

    def test_expiry_sweeper_releases(self):
        r = self.inv.reserve("o1", {"A": 3})
        self.clock.advance(599)
        self.assertEqual(self.inv.expire_reservations(), [])
        self.clock.advance(1)
        self.assertEqual(self.inv.expire_reservations(), [r])
        self.assertEqual(self.inv.stock("A", "W1"), (10, 0, 10))

    def test_commit_after_ttl_fails_even_without_sweeper(self):
        r = self.inv.reserve("o1", {"A": 3})
        self.clock.advance(600)
        with self.assertRaises(ReservationExpiredError):
            self.inv.commit(r.reservation_id)
        self.assertIs(r.status, ReservationStatus.EXPIRED)
        self.assertEqual(self.inv.stock("A", "W1"), (10, 0, 10))

    def test_rejects_bad_input(self):
        for bad in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                self.inv.reserve("x", {"A": bad})
        with self.assertRaises(NotFoundError):
            self.inv.reserve("x", {"NOPE": 1})
        with self.assertRaises(NotFoundError):
            self.inv.receive_stock("A", "NOPE", 1)


class TransferAndAdjustTest(unittest.TestCase):
    def setUp(self):
        self.inv, _ = make_service()
        self.inv.receive_stock("A", "W1", 10)

    def test_transfer_moves_only_available_units(self):
        self.inv.reserve("o1", {"A": 8})
        with self.assertRaises(InsufficientStockError):
            self.inv.transfer_stock("A", "W1", "W2", 3)
        self.inv.transfer_stock("A", "W1", "W2", 2)
        self.assertEqual(self.inv.stock("A", "W1"), (8, 8, 0))
        self.assertEqual(self.inv.stock("A", "W2"), (2, 0, 2))

    def test_transfer_to_unknown_warehouse_loses_nothing(self):
        with self.assertRaises(NotFoundError):
            self.inv.transfer_stock("A", "W1", "NOPE", 3)
        self.assertEqual(self.inv.stock("A", "W1"), (10, 0, 10))

    def test_adjust_cannot_drop_below_reserved(self):
        self.inv.reserve("o1", {"A": 6})
        with self.assertRaises(InsufficientStockError):
            self.inv.adjust_stock("A", "W1", 5, "cycle count")
        self.assertEqual(self.inv.adjust_stock("A", "W1", 7, "cycle count"), -3)
        self.assertEqual(self.inv.stock("A", "W1"), (7, 6, 1))


class ReorderTest(unittest.TestCase):
    def test_fixed_policy_does_not_duplicate_open_pos(self):
        inv, _ = make_service()
        inv.receive_stock("A", "W1", 4)
        pos = inv.check_reorder()
        self.assertEqual([(p.sku, p.warehouse_id, p.quantity) for p in pos], [("A", "W1", 20)])
        self.assertEqual(inv.check_reorder(), [])
        inv.receive_purchase_order(pos[0].po_id)
        self.assertEqual(inv.stock("A", "W1"), (24, 0, 24))
        with self.assertRaises(InvalidStateError):
            inv.receive_purchase_order(pos[0].po_id)

    def test_cancelled_po_no_longer_counts_toward_position(self):
        inv, _ = make_service()
        inv.receive_stock("A", "W1", 4)
        po = inv.check_reorder()[0]
        inv.cancel_purchase_order(po.po_id)
        self.assertIs(po.status, POStatus.CANCELLED)
        self.assertEqual(len(inv.check_reorder()), 1)

    def test_reserved_stock_counts_against_position(self):
        inv, _ = make_service()
        inv.receive_stock("A", "W1", 10)
        self.assertEqual(inv.check_reorder(), [])
        inv.reserve("o1", {"A": 6})                 # available drops to 4 <= 5
        self.assertEqual(len(inv.check_reorder()), 1)

    def test_demand_based_policy_uses_shipped_history(self):
        inv, clock = make_service(reorder_policy=DemandBasedReorderPolicy(7, 3, 14),
                                  demand_lookback_days=10)
        inv.receive_stock("A", "W1", 200)
        for i in range(10):                         # 10 units/day for 10 days
            r = inv.reserve(f"o{i}", {"A": 10})
            inv.commit(r.reservation_id)
        # position 100, reorder point = 10/day * 10 days = 100 -> reorder up to 14 days cover
        po = inv.check_reorder()[0]
        self.assertEqual(po.quantity, 140 - 100)
        # 11 days later the history has aged out of the window: demand 0, position 100 > 5
        inv.cancel_purchase_order(po.po_id)
        clock.advance(11 * 86_400)
        self.assertEqual(inv.check_reorder(), [])

    def test_inventory_value_is_decimal(self):
        inv, _ = make_service()
        inv.receive_stock("A", "W1", 3)
        inv.receive_stock("B", "W2", 1)
        self.assertEqual(inv.inventory_value(), Decimal("17.50"))


class ConcurrencyTest(unittest.TestCase):
    def test_no_overselling_under_contention(self):
        inv, _ = make_service()
        inv.receive_stock("A", "W1", 30)
        inv.receive_stock("A", "W2", 20)
        successes, barrier = [], threading.Barrier(40)

        def buyer(n: int) -> None:
            barrier.wait()
            try:
                inv.reserve(f"o{n}", {"A": 2})
                successes.append(n)
            except InsufficientStockError:
                pass

        threads = [threading.Thread(target=buyer, args=(n,)) for n in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(successes), 25)        # 50 units / 2 each
        self.assertEqual(inv.available("A"), 0)

    def test_opposite_transfers_do_not_deadlock_and_conserve_stock(self):
        inv, _ = make_service()
        inv.receive_stock("A", "W1", 1000)
        inv.receive_stock("A", "W2", 1000)

        def mover(src: str, dst: str) -> None:
            for _ in range(300):
                inv.transfer_stock("A", src, dst, 1)

        threads = [threading.Thread(target=mover, args=p) for p in [("W1", "W2"), ("W2", "W1")] * 2]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive(), "deadlock")
        self.assertEqual(inv.stock("A", "W1")[0] + inv.stock("A", "W2")[0], 2000)

    def test_commit_vs_expiry_race_has_one_winner(self):
        for _ in range(50):
            inv, clock = make_service()
            inv.receive_stock("A", "W1", 5)
            r = inv.reserve("o1", {"A": 5})
            clock.advance(600)
            barrier = threading.Barrier(2)
            outcomes = []

            def commit():
                barrier.wait()
                try:
                    inv.commit(r.reservation_id)
                    outcomes.append("commit")
                except ReservationExpiredError:
                    outcomes.append("expired")

            def sweep():
                barrier.wait()
                inv.expire_reservations()

            ts = [threading.Thread(target=commit), threading.Thread(target=sweep)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(outcomes, ["expired"])
            self.assertEqual(inv.stock("A", "W1"), (5, 0, 5))

    def test_concurrent_duplicate_order_reserves_once(self):
        inv, _ = make_service()
        inv.receive_stock("A", "W1", 100)
        barrier, results = threading.Barrier(10), []

        def go():
            barrier.wait()
            try:
                results.append(inv.reserve("same", {"A": 3}).reservation_id)
            except IdempotencyConflictError:
                results.append("conflict")

        ts = [threading.Thread(target=go) for _ in range(10)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(inv.stock("A", "W1"), (100, 3, 97))
        self.assertEqual(len({r for r in results if r != "conflict"}), 1)


if __name__ == "__main__":
    unittest.main()
