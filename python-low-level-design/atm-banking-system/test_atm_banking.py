import threading
import unittest
from datetime import date
from decimal import Decimal

from atm_banking import (
    ATM, AccountType, Bank, CardBlockedError, CardError, CashDispenser, DispenseError,
    FlakyDispenser, IdempotencyError, InsufficientFundsError, InvalidOperationError,
    InvalidTransitionError, LimitExceededError, TransactionStatus, WrongPinError, to_money,
)

D = Decimal


class Clock:
    def __init__(self, today):
        self.today = today

    def __call__(self):
        return self.today


class MoneyTest(unittest.TestCase):
    def test_floats_rejected(self):
        with self.assertRaises(TypeError):
            to_money(10.0)
        with self.assertRaises(ValueError):
            to_money("1.001")


class AccountRulesTest(unittest.TestCase):
    def setUp(self):
        self.bank = Bank(clock=Clock(date(2025, 1, 1)))

    def test_savings_keeps_minimum_balance(self):
        acct = self.bank.open_account("c", AccountType.SAVINGS, "1000.00")
        self.assertEqual(self.bank.available(acct.account_number), D("500.00"))
        other = self.bank.open_account("c", AccountType.CHECKING)
        with self.assertRaises(InsufficientFundsError):
            self.bank.transfer(acct.account_number, other.account_number, "500.01", "r1")

    def test_checking_overdraft(self):
        acct = self.bank.open_account("c", AccountType.CHECKING, "100.00")
        other = self.bank.open_account("c", AccountType.CHECKING)
        self.bank.transfer(acct.account_number, other.account_number, "1100.00", "r1")
        self.assertEqual(self.bank.balance(acct.account_number), D("-1000.00"))
        with self.assertRaises(InsufficientFundsError):
            self.bank.transfer(acct.account_number, other.account_number, "0.01", "r2")

    def test_credit_limit_enforced(self):
        # The original code withdrew from credit accounts with no limit check at all.
        credit = self.bank.open_account("c", AccountType.CREDIT, credit_limit=D("300.00"))
        card = self.bank.issue_card(credit.account_number, "1111")
        self.bank.authorize_withdrawal(card.card_number, credit.account_number, "300.00", "r1")
        with self.assertRaises(InsufficientFundsError):
            self.bank.authorize_withdrawal(card.card_number, credit.account_number, "1.00", "r2")


class TwoPhaseWithdrawalTest(unittest.TestCase):
    def setUp(self):
        self.bank = Bank(clock=Clock(date(2025, 1, 1)))
        self.acct = self.bank.open_account("c", AccountType.CHECKING, "1000.00",
                                           overdraft_limit=D("0"))
        self.card = self.bank.issue_card(self.acct.account_number, "1234", daily_limit="800.00")
        self.n = self.acct.account_number

    def authorize(self, amount, rid):
        return self.bank.authorize_withdrawal(self.card.card_number, self.n, amount, rid)

    def test_hold_capture(self):
        tx = self.authorize("300.00", "r1")
        self.assertEqual(tx.status, TransactionStatus.PENDING)
        self.assertEqual(self.bank.balance(self.n), D("1000.00"))
        self.assertEqual(self.bank.available(self.n), D("700.00"))
        self.bank.capture(tx.tx_id)
        self.bank.capture(tx.tx_id)                       # idempotent
        self.assertEqual(self.bank.balance(self.n), D("700.00"))
        self.assertEqual(self.bank.available(self.n), D("700.00"))
        with self.assertRaises(InvalidTransitionError):
            self.bank.reverse(tx.tx_id)

    def test_hold_reverse_restores_funds_and_daily_limit(self):
        tx = self.authorize("800.00", "r1")
        with self.assertRaises(LimitExceededError):
            self.authorize("1.00", "r2")
        self.bank.reverse(tx.tx_id)
        self.bank.reverse(tx.tx_id)                       # idempotent
        self.assertEqual(self.bank.available(self.n), D("1000.00"))
        self.authorize("800.00", "r3")                    # limit freed by the reversal
        with self.assertRaises(InvalidTransitionError):
            self.bank.capture(tx.tx_id)

    def test_daily_limit_resets_next_day(self):
        self.authorize("800.00", "r1")
        self.bank._clock.today = date(2025, 1, 2)
        self.authorize("100.00", "r2")

    def test_idempotent_retry(self):
        a = self.authorize("100.00", "same")
        b = self.authorize("100.00", "same")
        self.assertIs(a, b)
        self.assertEqual(self.bank.available(self.n), D("900.00"))
        with self.assertRaises(IdempotencyError):
            self.authorize("200.00", "same")

    def test_declined_request_can_be_retried(self):
        with self.assertRaises(LimitExceededError):
            self.authorize("900.00", "r1")
        self.authorize("100.00", "r1")                    # failures are not cached

    def test_card_cannot_touch_someone_elses_account(self):
        stranger = self.bank.open_account("other", AccountType.SAVINGS, "5000.00")
        with self.assertRaises(CardError):
            self.bank.authorize_withdrawal(self.card.card_number, stranger.account_number,
                                           "10.00", "r1")


class DispenserTest(unittest.TestCase):
    def test_finds_combination_greedy_misses(self):
        d = CashDispenser({500: 1, 200: 3})
        self.assertEqual(d.plan(600), {200: 3})

    def test_min_notes_and_impossible(self):
        d = CashDispenser({2000: 5, 500: 10, 100: 10})
        self.assertEqual(d.plan(2600), {2000: 1, 500: 1, 100: 1})
        with self.assertRaises(DispenseError):
            d.plan(150)
        with self.assertRaises(DispenseError):
            CashDispenser({100: 2}).plan(300)

    def test_dispense_updates_stock(self):
        d = CashDispenser({100: 5})
        d.dispense(d.plan(300))
        self.assertEqual(d.notes(), {100: 2})


class ATMStateMachineTest(unittest.TestCase):
    def setUp(self):
        self.bank = Bank(clock=Clock(date(2025, 1, 1)))
        self.savings = self.bank.open_account("c", AccountType.SAVINGS, "5000.00")
        self.checking = self.bank.open_account("c", AccountType.CHECKING, "100.00")
        self.card = self.bank.issue_card(self.savings.account_number, "1234")
        self.dispenser = FlakyDispenser({500: 10, 100: 10})
        self.atm = ATM("A1", self.bank, self.dispenser)

    def login(self):
        self.atm.insert_card(self.card.card_number)
        self.atm.enter_pin("1234")

    def test_operations_rejected_outside_session(self):
        for op in (lambda: self.atm.enter_pin("1"), lambda: self.atm.withdraw(100),
                   self.atm.balance, self.atm.eject_card):
            with self.assertRaises(InvalidOperationError):
                op()
        self.atm.insert_card(self.card.card_number)
        with self.assertRaises(InvalidOperationError):
            self.atm.withdraw(100)                        # PIN not entered yet
        with self.assertRaises(InvalidOperationError):
            self.atm.insert_card(self.card.card_number)

    def test_unknown_card_stays_idle(self):
        with self.assertRaises(CardError):
            self.atm.insert_card("nope")
        self.assertEqual(self.atm.state, "IDLE")

    def test_withdraw_happy_path(self):
        self.login()
        self.assertEqual(self.atm.withdraw(700), {500: 1, 100: 2})
        self.assertEqual(self.atm.balance(), D("4300.00"))
        self.atm.eject_card()
        self.assertEqual(self.atm.state, "IDLE")

    def test_cannot_dispense_means_no_hold(self):
        self.login()
        with self.assertRaises(DispenseError):
            self.atm.withdraw(150)
        self.assertEqual(self.bank.available(self.savings.account_number), D("4500.00"))

    def test_jam_reverses_hold(self):
        self.login()
        self.dispenser.jam_next = True
        with self.assertRaises(DispenseError):
            self.atm.withdraw(500)
        self.assertEqual(self.bank.balance(self.savings.account_number), D("5000.00"))
        self.assertEqual(self.bank.available(self.savings.account_number), D("4500.00"))
        self.assertEqual(self.bank.statement(self.savings.account_number)[-1].status,
                         TransactionStatus.REVERSED)

    def test_insufficient_funds_leaves_cash_in_machine(self):
        self.login()
        self.atm.select_account(self.checking.account_number)
        before = self.dispenser.notes()
        with self.assertRaises(InsufficientFundsError):
            self.atm.withdraw(1500)                       # 100 + 1000 overdraft < 1500
        self.assertEqual(self.dispenser.notes(), before)

    def test_three_wrong_pins_block_and_retain(self):
        self.atm.insert_card(self.card.card_number)
        with self.assertRaises(WrongPinError):
            self.atm.enter_pin("0000")
        with self.assertRaises(WrongPinError):
            self.atm.enter_pin("0000")
        with self.assertRaises(CardBlockedError):
            self.atm.enter_pin("0000")
        self.assertEqual(self.atm.state, "IDLE")
        self.assertEqual(self.atm.retained_cards, [self.card.card_number])
        with self.assertRaises(CardBlockedError):
            self.atm.insert_card(self.card.card_number)

    def test_correct_pin_resets_attempts(self):
        self.atm.insert_card(self.card.card_number)
        for _ in range(2):
            with self.assertRaises(WrongPinError):
                self.atm.enter_pin("0000")
        self.atm.enter_pin("1234")
        self.atm.eject_card()
        self.atm.insert_card(self.card.card_number)
        with self.assertRaises(WrongPinError):
            self.atm.enter_pin("0000")                   # back to 3 attempts, not blocked

    def test_expired_card_rejected(self):
        self.bank._clock.today = date(2031, 1, 1)
        with self.assertRaises(CardError):
            self.atm.insert_card(self.card.card_number)

    def test_out_of_cash_goes_out_of_service(self):
        atm = ATM("A2", self.bank, CashDispenser({100: 2}))
        atm.insert_card(self.card.card_number)
        atm.enter_pin("1234")
        atm.withdraw(200)
        atm.eject_card()
        self.assertEqual(atm.state, "OUT_OF_SERVICE")
        with self.assertRaises(InvalidOperationError):
            atm.insert_card(self.card.card_number)
        atm.restock({100: 10})
        self.assertEqual(atm.state, "IDLE")


class ConcurrencyTest(unittest.TestCase):
    def test_concurrent_withdrawals_never_overdraw(self):
        bank = Bank(clock=Clock(date(2025, 1, 1)))
        acct = bank.open_account("c", AccountType.SAVINGS, "10500.00")      # 10000 withdrawable
        card = bank.issue_card(acct.account_number, "1", daily_limit="1000000.00")
        ok, barrier = [], threading.Barrier(16)

        def worker(i):
            barrier.wait()
            for j in range(50):
                try:
                    tx = bank.authorize_withdrawal(card.card_number, acct.account_number,
                                                   "100.00", f"w{i}-{j}")
                    bank.capture(tx.tx_id)
                    ok.append(tx)
                except InsufficientFundsError:
                    pass

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(ok), 100)
        self.assertEqual(bank.balance(acct.account_number), D("500.00"))

    def test_opposite_transfers_do_not_deadlock_and_conserve_money(self):
        bank = Bank()
        a = bank.open_account("c", AccountType.CHECKING, "1000.00")
        b = bank.open_account("c", AccountType.CHECKING, "1000.00")

        def mover(src, dst, tag):
            for i in range(300):
                bank.transfer(src, dst, "1.00", f"{tag}-{i}")

        threads = [threading.Thread(target=mover, args=(a.account_number, b.account_number, "ab")),
                   threading.Thread(target=mover, args=(b.account_number, a.account_number, "ba"))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive(), "deadlock")
        self.assertEqual(bank.balance(a.account_number) + bank.balance(b.account_number),
                         D("2000.00"))

    def test_same_request_id_from_two_threads_moves_money_once(self):
        bank = Bank()
        a = bank.open_account("c", AccountType.CHECKING, "1000.00")
        b = bank.open_account("c", AccountType.CHECKING, "0.00")
        barrier, results = threading.Barrier(8), []

        def retry():
            barrier.wait()
            try:
                results.append(bank.transfer(a.account_number, b.account_number, "10.00", "dup"))
            except IdempotencyError:
                pass                                       # in flight elsewhere; client retries later

        threads = [threading.Thread(target=retry) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(bank.balance(b.account_number), D("10.00"))
        self.assertTrue(results)


if __name__ == "__main__":
    unittest.main()
