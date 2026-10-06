import threading
import unittest

from vending_machine import (
    ChangeUnavailableError, Denomination as D, Dispenser, DispenseFailedError,
    FakeGateway, InvalidStateError, PaymentDeclinedError, PaymentMethod,
    Product, SoldOutError, UnknownSlotError, VendingMachine, make_change,
)


def machine(dispenser=None, gateway=None, float_=None) -> VendingMachine:
    vm = VendingMachine(dispenser, gateway,
                        change_float=float_ if float_ is not None
                        else {D.QUARTER: 4, D.DIME: 5, D.NICKEL: 4})
    vm.add_slot("A1", Product("coke", "Coke", 150), 3)
    vm.add_slot("C1", Product("gum", "Gum", 65), 2)
    return vm


class Jammed(Dispenser):
    def dispense(self, slot_code):
        return False


class MakeChangeTest(unittest.TestCase):
    def test_bounded_supply_beats_greedy(self):
        # Greedy takes the quarter and can't finish; 3 dimes is correct.
        self.assertEqual(make_change(30, {D.QUARTER: 1, D.DIME: 3}), {D.DIME: 3})

    def test_fewest_coins(self):
        self.assertEqual(make_change(60, {D.QUARTER: 5, D.DIME: 5, D.NICKEL: 5}),
                         {D.QUARTER: 2, D.DIME: 1})

    def test_impossible_and_zero(self):
        self.assertIsNone(make_change(5, {D.DIME: 10}))
        self.assertEqual(make_change(0, {}), {})

    def test_notes_never_paid_out(self):
        self.assertIsNone(make_change(100, {D.ONE_NOTE: 3}))
        self.assertEqual(make_change(100, {D.ONE_NOTE: 3, D.DOLLAR_COIN: 1}),
                         {D.DOLLAR_COIN: 1})

    def test_denominations_are_distinct(self):
        self.assertIsNot(D.DOLLAR_COIN, D.ONE_NOTE)
        self.assertEqual(len(list(D)), 6)


class CashFlowTest(unittest.TestCase):
    def test_exact_payment(self):
        vm = machine()
        vm.select("A1")
        self.assertIsNone(vm.insert(D.ONE_NOTE))
        self.assertIsNone(vm.insert(D.QUARTER))
        r = vm.insert(D.QUARTER)
        self.assertEqual((r.paid_cents, r.change_cents, r.method), (150, 0, PaymentMethod.CASH))
        self.assertEqual(vm.stock()["A1"], 2)
        self.assertEqual(vm.state, "IDLE")

    def test_change_and_cash_box_accounting(self):
        vm = machine()
        before = vm.cash_total_cents()
        vm.select("C1")
        r = vm.insert(D.ONE_NOTE)
        self.assertEqual(r.change_cents, 35)
        self.assertEqual(vm.cash_total_cents(), before + 65)

    def test_escrowed_coins_can_be_used_for_change(self):
        vm = machine(float_={})              # empty cash box
        vm.select("A1")                      # $1.50
        for _ in range(3):
            vm.insert(D.QUARTER)
        r = vm.insert(D.ONE_NOTE)            # $1.75 in; 25c back from escrow
        self.assertEqual(r.change, {D.QUARTER: 1})
        self.assertEqual(vm.cash_total_cents(), 150)

    def test_rejects_piece_when_change_impossible(self):
        vm = machine(float_={})
        vm.select("C1")
        vm.insert(D.QUARTER)
        vm.insert(D.QUARTER)
        with self.assertRaises(ChangeUnavailableError):
            vm.insert(D.QUARTER)             # would need 10c change, box is empty
        self.assertEqual(vm.balance_cents, 50)
        self.assertEqual(vm.state, "AWAITING_PAYMENT")
        vm.insert(D.DIME)
        r = vm.insert(D.NICKEL)
        self.assertEqual(r.change_cents, 0)

    def test_cancel_returns_exact_pieces(self):
        vm = machine()
        vm.select("A1")
        vm.insert(D.DIME)
        vm.insert(D.ONE_NOTE)
        vm.insert(D.DIME)
        self.assertEqual(vm.cancel(), {D.DIME: 2, D.ONE_NOTE: 1})
        self.assertEqual(vm.state, "IDLE")
        self.assertEqual(vm.stock()["A1"], 3)

    def test_jam_refunds_cash_and_keeps_stock(self):
        vm = machine(dispenser=Jammed())
        cash = vm.cash_total_cents()
        vm.select("C1")
        with self.assertRaises(DispenseFailedError):
            vm.insert(D.ONE_NOTE)
        self.assertEqual(vm.cash_total_cents(), cash)
        self.assertEqual(vm.stock()["C1"], 2)
        self.assertEqual(vm.state, "IDLE")


class StateTest(unittest.TestCase):
    def test_illegal_actions(self):
        vm = machine()
        with self.assertRaises(InvalidStateError):
            vm.insert(D.DIME)
        with self.assertRaises(InvalidStateError):
            vm.cancel()
        vm.select("A1")
        with self.assertRaises(InvalidStateError):
            vm.select("C1")

    def test_unknown_and_sold_out(self):
        vm = machine()
        with self.assertRaises(UnknownSlotError):
            vm.select("Z9")
        for _ in range(2):
            vm.purchase_with_card("C1", "visa")
        with self.assertRaises(SoldOutError):
            vm.select("C1")
        self.assertEqual(vm.state, "IDLE")

    def test_maintenance_refunds_open_transaction(self):
        vm = machine()
        vm.select("A1")
        vm.insert(D.QUARTER)
        self.assertEqual(vm.enter_maintenance(), {D.QUARTER: 1})
        self.assertEqual(vm.state, "OUT_OF_SERVICE")
        with self.assertRaises(InvalidStateError):
            vm.select("A1")
        vm.exit_maintenance()
        self.assertEqual(vm.select("A1").name, "Coke")

    def test_restock_respects_capacity(self):
        vm = machine()
        self.assertEqual(vm.restock("A1", 7), 10)
        with self.assertRaises(ValueError):
            vm.restock("A1", 1)


class CardFlowTest(unittest.TestCase):
    def test_capture_after_dispense(self):
        gw = FakeGateway()
        vm = machine(gateway=gw)
        r = vm.purchase_with_card("A1", "visa")
        self.assertEqual(r.method, PaymentMethod.CARD)
        self.assertEqual(list(gw.captured.values()), [150])
        self.assertEqual(gw.holds, {})

    def test_decline_leaves_machine_idle(self):
        vm = machine()
        with self.assertRaises(PaymentDeclinedError):
            vm.purchase_with_card("A1", "declined-card")
        self.assertEqual(vm.state, "IDLE")
        self.assertEqual(vm.stock()["A1"], 3)

    def test_jam_voids_hold(self):
        gw = FakeGateway()
        vm = machine(dispenser=Jammed(), gateway=gw)
        with self.assertRaises(DispenseFailedError):
            vm.purchase_with_card("A1", "visa")
        self.assertEqual(gw.captured, {})
        self.assertEqual(list(gw.voided.values()), [150])
        self.assertEqual(vm.stock()["A1"], 3)

    def test_cannot_mix_cash_and_card(self):
        vm = machine()
        vm.select("A1")
        vm.insert(D.QUARTER)
        with self.assertRaises(InvalidStateError):
            vm.pay_by_card("visa")


class ConcurrencyTest(unittest.TestCase):
    def test_no_oversell_under_concurrent_remote_purchases(self):
        gw = FakeGateway()
        vm = machine(gateway=gw)          # A1 has 3 units
        results = {"ok": 0, "sold_out": 0, "busy": 0}
        lock = threading.Lock()
        barrier = threading.Barrier(16)

        def buyer(i):
            barrier.wait()
            try:
                vm.purchase_with_card("A1", f"card-{i}")
                key = "ok"
            except SoldOutError:
                key = "sold_out"
            with lock:
                results[key] += 1

        threads = [threading.Thread(target=buyer, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(results["ok"], 3)
        self.assertEqual(results["sold_out"], 13)
        self.assertEqual(len(gw.captured), 3)
        self.assertEqual(gw.holds, {})        # no dangling authorizations
        self.assertEqual(vm.stock()["A1"], 0)

    def test_restock_races_with_sales(self):
        vm = machine()
        vm.restock("C1", 8)                   # C1: 10 units, capacity 10
        sold = []

        def seller():
            for _ in range(200):
                try:
                    vm.purchase_with_card("C1", "visa")
                    sold.append(1)
                except SoldOutError:
                    pass

        restocked = []

        def restocker():
            for _ in range(200):
                try:
                    vm.restock("C1", 1)
                    restocked.append(1)
                except ValueError:
                    pass

        ts = [threading.Thread(target=seller), threading.Thread(target=restocker)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=5)
        self.assertEqual(vm.stock()["C1"], 10 + len(restocked) - len(sold))
        self.assertTrue(0 <= vm.stock()["C1"] <= 10)


if __name__ == "__main__":
    unittest.main()
