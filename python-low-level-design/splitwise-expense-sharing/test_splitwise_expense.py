import random
import threading
import unittest
from decimal import Decimal

from splitwise_expense import (
    ExactSplit, EqualSplit, GreedySettlement, InvalidSplitError, NotFoundError,
    OptimalSettlement, PercentageSplit, ShareSplit, SplitType, SplitwiseError,
    SplitwiseService, allocate, to_money,
)

D = Decimal


class MoneyTest(unittest.TestCase):
    def test_rejects_float_and_sub_cent(self):
        with self.assertRaises(TypeError):
            to_money(10.5)
        with self.assertRaises(ValueError):
            to_money("10.005")
        self.assertEqual(to_money("10.5"), D("10.50"))

    def test_allocate_sums_exactly_and_stays_within_a_cent(self):
        rng = random.Random(7)
        for _ in range(500):
            total = rng.randint(0, 100_000)
            weights = [D(rng.randint(0, 50)) for _ in range(rng.randint(1, 9))]
            if sum(weights) == 0:
                continue
            parts = allocate(total, weights)
            self.assertEqual(sum(parts), total)
            for part, w in zip(parts, weights):
                exact = total * w / sum(weights)
                self.assertLess(abs(part - exact), 1)
                self.assertGreaterEqual(part, 0)


class SplitStrategyTest(unittest.TestCase):
    ids = ["a", "b", "c"]

    def test_equal_split_spreads_remainder_one_cent_each(self):
        shares = EqualSplit().calculate_shares(D("100.00"), self.ids, None)
        self.assertEqual(list(shares.values()), [D("33.34"), D("33.33"), D("33.33")])

    def test_equal_split_tiny_amount_never_negative(self):
        # The old float version produced a -0.01 share here.
        ids = [str(i) for i in range(7)]
        shares = EqualSplit().calculate_shares(D("0.05"), ids, None)
        self.assertEqual(sum(shares.values()), D("0.05"))
        self.assertTrue(all(s >= 0 for s in shares.values()))

    def test_percentage_split_sums_to_total(self):
        shares = PercentageSplit().calculate_shares(D("10.00"), self.ids, ["33.33", "33.33", "33.34"])
        self.assertEqual(sum(shares.values()), D("10.00"))

    def test_percentage_must_total_100(self):
        with self.assertRaises(InvalidSplitError):
            PercentageSplit().calculate_shares(D("10.00"), self.ids, ["30", "30", "30"])

    def test_exact_must_match_amount(self):
        with self.assertRaises(InvalidSplitError):
            ExactSplit().calculate_shares(D("10.00"), self.ids, ["3", "3", "3"])

    def test_share_split_ratio(self):
        shares = ShareSplit().calculate_shares(D("100.00"), self.ids, ["2", "1", "0"])
        self.assertEqual(shares, {"a": D("66.67"), "b": D("33.33"), "c": D("0.00")})

    def test_values_reject_floats(self):
        with self.assertRaises(InvalidSplitError):
            ShareSplit().calculate_shares(D("1.00"), self.ids, [1.0, 1.0, 1.0])


class SettlementTest(unittest.TestCase):
    @staticmethod
    def apply(balances, transfers):
        result = dict(balances)
        for t in transfers:
            result[t.debtor] += t.amount
            result[t.creditor] -= t.amount
        return result

    def random_balances(self, rng, n):
        vals = [rng.randint(-50, 50) for _ in range(n - 1)]
        vals.append(-sum(vals))
        return {f"u{i}": D(v) for i, v in enumerate(vals)}

    def test_both_strategies_settle_everything(self):
        rng = random.Random(3)
        for _ in range(200):
            balances = self.random_balances(rng, rng.randint(2, 8))
            nonzero = sum(1 for b in balances.values() if b)
            greedy = GreedySettlement().settle(balances)
            optimal = OptimalSettlement().settle(balances)
            for plan in (greedy, optimal):
                self.assertTrue(all(v == 0 for v in self.apply(balances, plan).values()))
                self.assertTrue(all(t.amount > 0 for t in plan))
            self.assertLessEqual(len(greedy), max(nonzero - 1, 0))
            self.assertLessEqual(len(optimal), len(greedy))

    def test_optimal_beats_greedy_on_known_case(self):
        balances = {"A": D(-8), "B": D(-7), "C": D(-2), "D": D(9), "E": D(8)}
        self.assertEqual(len(GreedySettlement().settle(balances)), 4)
        self.assertEqual(len(OptimalSettlement().settle(balances)), 3)

    def test_one_cent_balance_is_not_dropped(self):
        plan = GreedySettlement().settle({"a": D("-0.01"), "b": D("0.01")})
        self.assertEqual(len(plan), 1)

    def test_unbalanced_input_rejected(self):
        with self.assertRaises(ValueError):
            GreedySettlement().settle({"a": D(-1), "b": D(2)})


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.sw = SplitwiseService()
        self.a, self.b, self.c = (self.sw.add_user(n, n + "@x").user_id for n in "abc")
        self.g = self.sw.create_group("trip", [self.a, self.b, self.c]).group_id

    def test_balances_and_settle_up(self):
        self.sw.add_expense("dinner", "90.00", self.a, [self.a, self.b, self.c], group_id=self.g)
        self.assertEqual(self.sw.get_group_balances(self.g),
                         {self.a: D("60.00"), self.b: D("-30.00"), self.c: D("-30.00")})
        for t in self.sw.get_settlement_plan(self.g):
            self.sw.record_payment(t.debtor, t.creditor, t.amount, self.g)
        self.assertEqual(self.sw.get_group_balances(self.g), {})

    def test_payer_not_participant(self):
        self.sw.add_expense("gift", "20.00", self.a, [self.b, self.c], group_id=self.g)
        self.assertEqual(self.sw.get_balance(self.a), D("20.00"))
        self.assertEqual(self.sw.get_balance(self.b), D("-10.00"))

    def test_delete_expense_reverses_ledger(self):
        e = self.sw.add_expense("x", "10.00", self.a, [self.a, self.b, self.c], group_id=self.g)
        self.sw.delete_expense(e.expense_id)
        self.assertEqual(self.sw.get_group_balances(self.g), {})
        with self.assertRaises(NotFoundError):
            self.sw.delete_expense(e.expense_id)

    def test_validation(self):
        with self.assertRaises(NotFoundError):
            self.sw.add_expense("x", "10.00", self.a, [self.a, "nope"], group_id=self.g)
        with self.assertRaises(InvalidSplitError):
            self.sw.add_expense("x", "10.00", self.a, [self.a, self.a])
        with self.assertRaises(InvalidSplitError):
            self.sw.add_expense("x", "0", self.a, [self.a])
        outsider = self.sw.add_user("d", "d@x").user_id
        with self.assertRaises(SplitwiseError):
            self.sw.add_expense("x", "10.00", self.a, [outsider], group_id=self.g)
        with self.assertRaises(InvalidSplitError):
            self.sw.add_expense("x", "10.00", self.a, [self.a], SplitType.EXACT, ["9.00"])

    def test_cannot_remove_member_with_balance(self):
        self.sw.add_expense("x", "10.00", self.a, [self.a, self.b], group_id=self.g)
        with self.assertRaises(SplitwiseError):
            self.sw.remove_member(self.g, self.b)
        self.sw.remove_member(self.g, self.c)

    def test_personal_and_group_balances_combine(self):
        self.sw.add_expense("x", "10.00", self.a, [self.a, self.b], group_id=self.g)
        self.sw.add_expense("y", "4.00", self.a, [self.b])
        self.assertEqual(self.sw.get_balance(self.b), D("-9.00"))

    def test_concurrent_expenses_keep_ledger_exact(self):
        members = [self.a, self.b, self.c]
        threads_n, per_thread = 8, 200

        def worker(seed):
            rng = random.Random(seed)
            for _ in range(per_thread):
                payer = rng.choice(members)
                self.sw.add_expense("t", D(rng.randint(1, 10_000)) / 100, payer, members,
                                    group_id=self.g)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(threads_n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        balances = self.sw.get_group_balances(self.g)
        self.assertEqual(sum(balances.values()), 0)
        # Ids are unique and every expense was recorded.
        self.assertEqual(len(self.sw._expenses), threads_n * per_thread)
        # Recompute from scratch and compare with the incrementally maintained ledger.
        recomputed = {}
        for e in self.sw._expenses.values():
            recomputed[e.paid_by] = recomputed.get(e.paid_by, 0) + e.amount
            for uid, share in e.shares.items():
                recomputed[uid] = recomputed.get(uid, 0) - share
        self.assertEqual({k: v for k, v in recomputed.items() if v}, balances)


if __name__ == "__main__":
    unittest.main()
