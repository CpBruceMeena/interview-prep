import threading
import time
import unittest
from decimal import Decimal

from payment_processing import (
    ALLOWED_TRANSITIONS, AmountLimitRule, Currency, GatewayDecision, GatewayResult,
    IdempotencyConflictError, IllegalTransitionError, Merchant, Money, Payment,
    PaymentRequest, PaymentService, PaymentStatus, RefundError, RefundStatus,
    RequestInProgressError, RetryPolicy, SimulatedGateway, ValidationError, VelocityRule,
)


def usd(s: str) -> Money:
    return Money.of(s, Currency.USD)


def req(key: str, amount: str = "100.00", token: str = "tok_visa", customer: str = "c1") -> PaymentRequest:
    return PaymentRequest(key, "m1", customer, usd(amount), token)


class SlowGateway(SimulatedGateway):
    """Widens race windows so concurrency tests exercise the locking, not luck."""

    def charge(self, *a, **kw):
        time.sleep(0.005)
        return super().charge(*a, **kw)

    def refund(self, *a, **kw):
        time.sleep(0.002)
        return super().refund(*a, **kw)


def make(gateway=None, **kw):
    gateway = gateway or SimulatedGateway()
    sleeps = []
    service = PaymentService(gateway, retry=RetryPolicy(max_attempts=3, sleep=sleeps.append), **kw)
    service.add_merchant(Merchant("m1", "Shop", fee_bps=250))
    return service, gateway, sleeps


class MoneyTest(unittest.TestCase):
    def test_rejects_float_and_excess_precision(self):
        with self.assertRaises(ValidationError):
            Money(10.5, Currency.USD)  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            Money.of("10.001", Currency.USD)
        with self.assertRaises(ValidationError):
            Money.of("1.5", Currency.JPY)
        Money.of("150", Currency.JPY)

    def test_currency_mismatch(self):
        with self.assertRaises(ValidationError):
            usd("1.00") + Money.of("1.00", Currency.EUR)

    def test_fee_rounds_half_up_to_minor_unit(self):
        self.assertEqual(usd("10.10").fee(250).amount, Decimal("0.25"))   # 0.2525 -> 0.25
        self.assertEqual(usd("0.30").fee(250).amount, Decimal("0.01"))    # 0.0075 -> 0.01


class ChargeTest(unittest.TestCase):
    def test_happy_path(self):
        service, gw, _ = make()
        p = service.pay(req("k1", "200.00"))
        self.assertIs(p.status, PaymentStatus.SUCCEEDED)
        self.assertEqual(p.fee, usd("5.00"))
        self.assertEqual(len(gw.money_moved), 1)

    def test_same_key_returns_same_payment_without_new_charge(self):
        service, gw, _ = make()
        p = service.pay(req("k1"))
        self.assertIs(service.pay(req("k1")), p)
        self.assertEqual(len(gw.money_moved), 1)

    def test_same_key_different_request_conflicts(self):
        service, _, _ = make()
        service.pay(req("k1", "100.00"))
        with self.assertRaises(IdempotencyConflictError):
            service.pay(req("k1", "100.01"))

    def test_decline_is_terminal_and_not_retried(self):
        service, gw, sleeps = make()
        p = service.pay(req("k1", token="tok_decline"))
        self.assertIs(p.status, PaymentStatus.FAILED)
        self.assertEqual(p.failure_reason, "card_declined")
        self.assertEqual(sleeps, [])
        self.assertEqual(gw.money_moved, [])

    def test_transient_failures_are_retried_with_backoff(self):
        service, gw, sleeps = make()
        gw.inject("unavailable", "timeout_before")
        p = service.pay(req("k1"))
        self.assertIs(p.status, PaymentStatus.SUCCEEDED)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(len(gw.money_moved), 1)

    def test_timeout_after_charge_does_not_double_charge(self):
        service, gw, _ = make()
        gw.inject("timeout_after", "timeout_after")
        p = service.pay(req("k1"))
        self.assertIs(p.status, PaymentStatus.SUCCEEDED)
        self.assertEqual(len(gw.money_moved), 1)

    def test_exhausted_retries_leave_unknown_then_reconcile(self):
        service, gw, _ = make()
        gw.inject("timeout_after", "timeout_before", "timeout_before")
        p = service.pay(req("k1"))
        self.assertIs(p.status, PaymentStatus.UNKNOWN)
        with self.assertRaises(RefundError):
            service.refund(p.payment_id, usd("1.00"), "r1")
        self.assertEqual(service.reconcile(), [p])
        self.assertIs(p.status, PaymentStatus.SUCCEEDED)
        self.assertEqual(len(gw.money_moved), 1)      # the original charge, found by key

    def test_risk_rules(self):
        clock = [0.0]
        service, gw, _ = make(risk_rules=[AmountLimitRule(usd("500.00")),
                                          VelocityRule(2, 60, clock=lambda: clock[0])])
        self.assertIs(service.pay(req("k1", "500.01")).status, PaymentStatus.FAILED)  # stops before velocity
        self.assertIs(service.pay(req("k2")).status, PaymentStatus.SUCCEEDED)
        self.assertIs(service.pay(req("k2b")).status, PaymentStatus.SUCCEEDED)
        p = service.pay(req("k3"))
        self.assertIs(p.status, PaymentStatus.FAILED)
        self.assertIn("attempts", p.failure_reason)
        self.assertIs(service.pay(req("k4", customer="c2")).status, PaymentStatus.SUCCEEDED)
        clock[0] = 61
        self.assertIs(service.pay(req("k5")).status, PaymentStatus.SUCCEEDED)

    def test_validation(self):
        service, _, _ = make()
        with self.assertRaises(ValidationError):
            service.pay(req("k1", "0.00"))
        with self.assertRaises(ValidationError):
            service.pay(req("", "1.00"))


class StateMachineTest(unittest.TestCase):
    def test_terminal_states_have_no_exits(self):
        self.assertEqual(ALLOWED_TRANSITIONS[PaymentStatus.FAILED], set())
        self.assertEqual(ALLOWED_TRANSITIONS[PaymentStatus.REFUNDED], set())

    def test_illegal_transition_raises(self):
        p = Payment("p", req("k"))
        p.transition(PaymentStatus.FAILED)
        with self.assertRaises(IllegalTransitionError):
            p.transition(PaymentStatus.SUCCEEDED)


class RefundTest(unittest.TestCase):
    def setUp(self):
        self.service, self.gw, _ = make()
        self.p = self.service.pay(req("k1", "100.00"))

    def test_partial_then_full(self):
        self.service.refund(self.p.payment_id, usd("30.00"), "r1")
        self.assertIs(self.p.status, PaymentStatus.PARTIALLY_REFUNDED)
        self.service.refund(self.p.payment_id, usd("70.00"), "r2")
        self.assertIs(self.p.status, PaymentStatus.REFUNDED)
        with self.assertRaises(RefundError):
            self.service.refund(self.p.payment_id, usd("0.01"), "r3")

    def test_refund_retry_is_idempotent(self):
        r1 = self.service.refund(self.p.payment_id, usd("30.00"), "r1")
        self.assertIs(self.service.refund(self.p.payment_id, usd("30.00"), "r1"), r1)
        self.assertEqual(self.p.refunded(), usd("30.00"))
        with self.assertRaises(IdempotencyConflictError):
            self.service.refund(self.p.payment_id, usd("31.00"), "r1")

    def test_cannot_over_refund(self):
        with self.assertRaises(RefundError):
            self.service.refund(self.p.payment_id, usd("100.01"), "r1")

    def test_cannot_refund_failed_payment(self):
        f = self.service.pay(req("k2", token="tok_decline"))
        with self.assertRaises(RefundError):
            self.service.refund(f.payment_id, usd("1.00"), "r1")

    def test_unknown_refund_holds_amount_until_reconciled(self):
        self.gw.inject("timeout_before", "timeout_before", "timeout_before")
        r = self.service.refund(self.p.payment_id, usd("60.00"), "r1")
        self.assertIs(r.status, RefundStatus.PENDING)
        self.assertEqual(self.p.refundable(), usd("40.00"))       # held, not lost
        with self.assertRaises(RefundError):
            self.service.refund(self.p.payment_id, usd("50.00"), "r2")
        self.service.reconcile()
        self.assertIs(r.status, RefundStatus.SUCCEEDED)
        self.assertEqual(self.p.refunded(), usd("60.00"))

    def test_declined_refund_releases_hold(self):
        class DecliningRefunds(SimulatedGateway):
            def refund(self, key, ref, amount):
                return GatewayResult(GatewayDecision.DECLINED, "re_x", "insufficient_balance")
        service, _, _ = make(DecliningRefunds())
        p = service.pay(req("k1"))
        r = service.refund(p.payment_id, usd("40.00"), "r1")
        self.assertIs(r.status, RefundStatus.FAILED)
        self.assertEqual(p.refundable(), usd("100.00"))
        self.assertIs(p.status, PaymentStatus.SUCCEEDED)


class OutboxTest(unittest.TestCase):
    def test_relay_is_ordered_and_retries_after_publish_failure(self):
        service, _, _ = make()
        service.pay(req("k1"))
        service.pay(req("k2", token="tok_decline"))
        sent, fail = [], [True]

        def publish(e):
            if fail[0]:
                fail[0] = False
                raise ConnectionError("broker down")
            sent.append(e.type)

        self.assertEqual(service.outbox.relay(publish), 0)
        self.assertEqual(len(service.outbox.pending()), 2)
        self.assertEqual(service.outbox.relay(publish), 2)
        self.assertEqual(sent, ["payment.succeeded", "payment.failed"])
        self.assertEqual(service.outbox.pending(), [])


class ConcurrencyTest(unittest.TestCase):
    def test_concurrent_duplicate_requests_charge_once(self):
        service, gw, _ = make(SlowGateway())
        barrier, results = threading.Barrier(10), []

        def go():
            barrier.wait()
            try:
                results.append(service.pay(req("same")).payment_id)
            except RequestInProgressError:
                results.append("409")

        ts = [threading.Thread(target=go) for _ in range(10)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(gw.money_moved), 1)
        self.assertEqual(len({r for r in results if r != "409"}), 1)

    def test_concurrent_refunds_never_exceed_captured_amount(self):
        service, gw, _ = make(SlowGateway())
        p = service.pay(req("k1", "100.00"))
        barrier, ok = threading.Barrier(25), []

        def go(i):
            barrier.wait()
            try:
                service.refund(p.payment_id, usd("10.00"), f"r{i}")
                ok.append(i)
            except RefundError:
                pass

        ts = [threading.Thread(target=go, args=(i,)) for i in range(25)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(ok), 10)
        self.assertEqual(p.refunded(), usd("100.00"))
        self.assertIs(p.status, PaymentStatus.REFUNDED)
        self.assertEqual(sum(1 for kind, _ in gw.money_moved if kind == "refund"), 10)


if __name__ == "__main__":
    unittest.main()
