"""
Payment Processing System - Low Level Design
============================================

What this models (and what interviewers actually probe):

* Money is Decimal, quantized to the currency's minor unit. Never float.
* Every charge and refund carries a client idempotency key. A retry with the
  same key returns the original result; the same key with a different request
  is rejected; a duplicate that arrives while the first is in flight gets 409.
* The idempotency key is forwarded to the gateway, which is what makes retrying
  a *timeout* safe: the gateway dedupes, so a retry can never double-charge.
* Payment state machine with an explicit transition table, including UNKNOWN
  (gateway timed out, outcome not known) which is resolved by reconcile().
* Refund invariant: succeeded + in-flight refunds <= captured amount, enforced
  under the payment's lock *before* calling the gateway.
* Transactional outbox: each state change and its event are written under the
  same lock (one DB transaction in production); a relay publishes them
  at-least-once.

Stdlib only, Python 3.10+.
"""

from __future__ import annotations

import itertools
import random
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Callable, Deque, Dict, List, Optional, Tuple


# ---------------------------------------------------------------- errors

class PaymentError(Exception):
    pass


class ValidationError(PaymentError):
    pass


class IdempotencyConflictError(PaymentError):
    """Same idempotency key reused with a different request (HTTP 422 at Stripe)."""


class RequestInProgressError(PaymentError):
    """A request with this idempotency key is still being processed (HTTP 409)."""


class IllegalTransitionError(PaymentError):
    pass


class RefundError(PaymentError):
    pass


class NotFoundError(PaymentError):
    pass


# Gateway-side failures. The distinction matters: one is safe to retry blindly,
# the other is only safe to retry because the idempotency key travels with it.
class GatewayUnavailableError(Exception):
    """Request definitely not processed (connection refused, 503 before acceptance)."""


class GatewayTimeoutError(Exception):
    """Request may or may not have been processed. Outcome unknown."""


# ---------------------------------------------------------------- money

class Currency(Enum):
    USD = ("USD", 2)
    EUR = ("EUR", 2)
    INR = ("INR", 2)
    JPY = ("JPY", 0)   # no minor unit: 1.5 JPY is not a valid amount

    @property
    def code(self) -> str:
        return self.value[0]

    @property
    def exponent(self) -> int:
        return self.value[1]


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise ValidationError("amount must be a Decimal (construct from a string, never a float)")
        if not self.amount.is_finite():
            raise ValidationError("amount must be finite")
        quantum = Decimal(1).scaleb(-self.currency.exponent)
        if self.amount != self.amount.quantize(quantum):
            raise ValidationError(f"{self.amount} has more precision than {self.currency.code} allows")

    @classmethod
    def of(cls, amount: str, currency: Currency) -> "Money":
        return cls(Decimal(amount), currency)

    @classmethod
    def zero(cls, currency: Currency) -> "Money":
        return cls(Decimal(0).quantize(Decimal(1).scaleb(-currency.exponent)), currency)

    def _same(self, other: "Money") -> None:
        if self.currency is not other.currency:
            raise ValidationError(f"currency mismatch: {self.currency.code} vs {other.currency.code}")

    def __add__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._same(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._same(other)
        return self.amount <= other.amount

    def fee(self, basis_points: int) -> "Money":
        quantum = Decimal(1).scaleb(-self.currency.exponent)
        return Money((self.amount * basis_points / Decimal(10_000)).quantize(quantum, ROUND_HALF_UP),
                     self.currency)

    def __str__(self) -> str:
        return f"{self.amount} {self.currency.code}"


# ---------------------------------------------------------------- domain

class PaymentStatus(Enum):
    PROCESSING = "processing"                  # record created, gateway call in progress
    SUCCEEDED = "succeeded"
    FAILED = "failed"                          # declined, or rejected by risk rules
    UNKNOWN = "unknown"                        # gateway timed out; reconcile() decides
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


ALLOWED_TRANSITIONS: Dict[PaymentStatus, set] = {
    PaymentStatus.PROCESSING: {PaymentStatus.SUCCEEDED, PaymentStatus.FAILED, PaymentStatus.UNKNOWN},
    PaymentStatus.UNKNOWN: {PaymentStatus.SUCCEEDED, PaymentStatus.FAILED},
    PaymentStatus.SUCCEEDED: {PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED},
    PaymentStatus.PARTIALLY_REFUNDED: {PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED},
    PaymentStatus.FAILED: set(),
    PaymentStatus.REFUNDED: set(),
}

REFUNDABLE = {PaymentStatus.SUCCEEDED, PaymentStatus.PARTIALLY_REFUNDED}


class RefundStatus(Enum):
    PENDING = "pending"        # amount is held against the payment; gateway call in flight or unknown
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class Merchant:
    merchant_id: str
    name: str
    fee_bps: int = 250         # 2.50%


@dataclass(frozen=True)
class PaymentRequest:
    """Everything that defines 'the same request' for idempotency purposes."""
    idempotency_key: str
    merchant_id: str
    customer_id: str
    amount: Money
    payment_token: str         # tokenized card/UPI handle; raw PAN never reaches us (PCI scope)


@dataclass
class Refund:
    refund_id: str
    payment_id: str
    idempotency_key: str
    amount: Money
    reason: str
    status: RefundStatus = RefundStatus.PENDING
    gateway_ref: Optional[str] = None


@dataclass
class Payment:
    payment_id: str
    request: PaymentRequest
    status: PaymentStatus = PaymentStatus.PROCESSING
    gateway_ref: Optional[str] = None
    failure_reason: Optional[str] = None
    fee: Optional[Money] = None
    refunds: List[Refund] = field(default_factory=list)
    history: List[PaymentStatus] = field(default_factory=lambda: [PaymentStatus.PROCESSING])
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def amount(self) -> Money:
        return self.request.amount

    def refunded(self) -> Money:
        return _sum(self.amount.currency, (r.amount for r in self.refunds if r.status is RefundStatus.SUCCEEDED))

    def held_for_refunds(self) -> Money:
        return _sum(self.amount.currency, (r.amount for r in self.refunds if r.status is RefundStatus.PENDING))

    def refundable(self) -> Money:
        if self.status not in REFUNDABLE:
            return Money.zero(self.amount.currency)
        return self.amount - self.refunded() - self.held_for_refunds()

    def transition(self, to: PaymentStatus) -> None:
        """Caller holds self.lock."""
        if to not in ALLOWED_TRANSITIONS[self.status]:
            raise IllegalTransitionError(f"{self.payment_id}: {self.status.value} -> {to.value}")
        self.status = to
        self.history.append(to)


def _sum(currency: Currency, amounts) -> Money:
    total = Money.zero(currency)
    for a in amounts:
        total = total + a
    return total


# ---------------------------------------------------------------- gateway

class GatewayDecision(Enum):
    APPROVED = "approved"
    DECLINED = "declined"


@dataclass(frozen=True)
class GatewayResult:
    decision: GatewayDecision
    reference: str
    reason: str = ""


class PaymentGateway(ABC):
    """Adapter over Stripe / Adyen / Razorpay. Implementations MUST forward the idempotency
    key to the provider so that a retried request is deduplicated on their side."""

    @abstractmethod
    def charge(self, idempotency_key: str, amount: Money, payment_token: str) -> GatewayResult: ...

    @abstractmethod
    def refund(self, idempotency_key: str, charge_reference: str, amount: Money) -> GatewayResult: ...


class SimulatedGateway(PaymentGateway):
    """Deterministic in-memory gateway with scriptable faults.

    Faults (consumed one per call): "unavailable" (not processed), "timeout_before"
    (not processed, caller sees a timeout), "timeout_after" (processed, caller still sees
    a timeout: the case that causes double charges without idempotency keys).
    Tokens starting with "tok_decline" are declined.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._results: Dict[str, GatewayResult] = {}
        self._faults: Deque[str] = deque()
        self._refs = itertools.count(1)
        self.money_moved: List[Tuple[str, Money]] = []   # what actually hit the card network

    def inject(self, *faults: str) -> None:
        with self._lock:
            self._faults.extend(faults)

    def charge(self, idempotency_key: str, amount: Money, payment_token: str) -> GatewayResult:
        def decide() -> GatewayResult:
            if payment_token.startswith("tok_decline"):
                return GatewayResult(GatewayDecision.DECLINED, f"ch_{next(self._refs)}", "card_declined")
            self.money_moved.append(("charge", amount))
            return GatewayResult(GatewayDecision.APPROVED, f"ch_{next(self._refs)}")
        return self._call(f"charge:{idempotency_key}", decide)

    def refund(self, idempotency_key: str, charge_reference: str, amount: Money) -> GatewayResult:
        def decide() -> GatewayResult:
            self.money_moved.append(("refund", amount))
            return GatewayResult(GatewayDecision.APPROVED, f"re_{next(self._refs)}")
        return self._call(f"refund:{idempotency_key}", decide)

    def _call(self, key: str, decide: Callable[[], GatewayResult]) -> GatewayResult:
        with self._lock:
            fault = self._faults.popleft() if self._faults else None
            if fault == "unavailable":
                raise GatewayUnavailableError("connection refused")
            if fault == "timeout_before":
                raise GatewayTimeoutError("read timeout")
            if key not in self._results:             # provider-side idempotency
                self._results[key] = decide()
            if fault == "timeout_after":
                raise GatewayTimeoutError("read timeout (charge went through)")
            return self._results[key]


# ---------------------------------------------------------------- retries

class RetryPolicy:
    """Exponential backoff with full jitter. Only for errors the caller says are retryable."""

    def __init__(self, max_attempts: int = 3, base_delay_s: float = 0.2, max_delay_s: float = 5.0,
                 sleep: Callable[[float], None] = time.sleep, rng: Optional[random.Random] = None):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self._base, self._cap = base_delay_s, max_delay_s
        self._sleep = sleep
        self._rng = rng or random.Random()

    def run(self, fn: Callable[[], GatewayResult]) -> GatewayResult:
        for attempt in range(self.max_attempts):
            try:
                return fn()
            except (GatewayUnavailableError, GatewayTimeoutError):
                if attempt == self.max_attempts - 1:
                    raise
                self._sleep(self._rng.uniform(0, min(self._cap, self._base * 2 ** attempt)))
        raise AssertionError("unreachable")


# ---------------------------------------------------------------- risk rules

class RiskRule(ABC):
    """Pre-authorization check. Return a rejection reason, or None to allow."""

    @abstractmethod
    def evaluate(self, request: PaymentRequest) -> Optional[str]: ...


class AmountLimitRule(RiskRule):
    def __init__(self, limit: Money):
        self._limit = limit

    def evaluate(self, request: PaymentRequest) -> Optional[str]:
        if request.amount.currency is self._limit.currency and self._limit < request.amount:
            return f"amount exceeds {self._limit}"
        return None


class VelocityRule(RiskRule):
    """At most `max_attempts` payment attempts per customer per sliding window."""

    def __init__(self, max_attempts: int, window_s: float, clock: Callable[[], float] = time.monotonic):
        self._max, self._window, self._clock = max_attempts, window_s, clock
        self._lock = threading.Lock()
        self._attempts: Dict[str, Deque[float]] = {}

    def evaluate(self, request: PaymentRequest) -> Optional[str]:
        now = self._clock()
        with self._lock:
            q = self._attempts.setdefault(request.customer_id, deque())
            while q and q[0] <= now - self._window:
                q.popleft()
            if len(q) >= self._max:
                return f"more than {self._max} attempts in {self._window:.0f}s"
            q.append(now)   # counts attempts, not successes: card-testing bots mostly fail
            return None


# ---------------------------------------------------------------- outbox

@dataclass(frozen=True)
class OutboxEvent:
    event_id: int
    type: str
    aggregate_id: str
    payload: Dict[str, str]


class Outbox:
    """Stands in for an `outbox` table written in the same transaction as the state change."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: Dict[int, OutboxEvent] = {}
        self._ids = itertools.count(1)

    def append(self, type_: str, aggregate_id: str, **payload: str) -> None:
        with self._lock:
            event = OutboxEvent(next(self._ids), type_, aggregate_id, payload)
            self._pending[event.event_id] = event

    def relay(self, publish: Callable[[OutboxEvent], None]) -> int:
        """Publish pending events in order; stop at the first failure. At-least-once:
        a crash after publish but before removal re-sends, so consumers dedupe on event_id."""
        with self._lock:
            batch = sorted(self._pending.values(), key=lambda e: e.event_id)
        sent = 0
        for event in batch:
            try:
                publish(event)
            except Exception:
                break
            with self._lock:
                self._pending.pop(event.event_id, None)
            sent += 1
        return sent

    def pending(self) -> List[OutboxEvent]:
        with self._lock:
            return sorted(self._pending.values(), key=lambda e: e.event_id)


# ---------------------------------------------------------------- service

class PaymentService:
    def __init__(self, gateway: PaymentGateway, retry: Optional[RetryPolicy] = None,
                 risk_rules: Optional[List[RiskRule]] = None, outbox: Optional[Outbox] = None):
        self._gateway = gateway
        self._retry = retry or RetryPolicy()
        self._rules = list(risk_rules or [])
        self.outbox = outbox or Outbox()
        self._lock = threading.Lock()             # guards the maps below, never held across I/O
        self._merchants: Dict[str, Merchant] = {}
        self._payments: Dict[str, Payment] = {}
        self._by_key: Dict[Tuple[str, str], Payment] = {}       # (merchant_id, key) -> payment
        self._refund_keys: Dict[Tuple[str, str], Refund] = {}   # (payment_id, key) -> refund
        self._ids = itertools.count(1)

    def add_merchant(self, merchant: Merchant) -> None:
        with self._lock:
            self._merchants[merchant.merchant_id] = merchant

    # ---- charge ------------------------------------------------------------

    def pay(self, request: PaymentRequest) -> Payment:
        """Create-and-charge, idempotent on (merchant_id, idempotency_key)."""
        if request.amount.amount <= 0:
            raise ValidationError("amount must be positive")
        if not request.idempotency_key:
            raise ValidationError("idempotency_key is required")

        with self._lock:
            merchant = self._merchants.get(request.merchant_id)
            if merchant is None:
                raise NotFoundError(f"merchant {request.merchant_id}")
            existing = self._by_key.get((request.merchant_id, request.idempotency_key))
            if existing is not None:
                if existing.request != request:
                    raise IdempotencyConflictError(f"key {request.idempotency_key} reused with a different request")
                if existing.status is PaymentStatus.PROCESSING:
                    raise RequestInProgressError(request.idempotency_key)
                return existing
            payment = Payment(f"pay_{next(self._ids)}", request)
            self._payments[payment.payment_id] = payment
            self._by_key[(request.merchant_id, request.idempotency_key)] = payment

        # From here on, a concurrent duplicate sees PROCESSING and gets 409.
        with payment.lock:
            for rule in self._rules:
                reason = rule.evaluate(request)
                if reason:
                    self._finish_charge(payment, PaymentStatus.FAILED, reason=f"risk: {reason}")
                    return payment

        self._attempt_charge(payment, merchant)
        return payment

    def reconcile(self) -> List[Payment]:
        """Resolve UNKNOWN payments and PENDING refunds by re-sending with the *same* key.
        The gateway either returns the original outcome or processes it once now."""
        with self._lock:
            unknown = [p for p in self._payments.values() if p.status is PaymentStatus.UNKNOWN]
            pending = [(p, r) for p in self._payments.values() for r in p.refunds
                       if r.status is RefundStatus.PENDING]
        for p in unknown:
            self._attempt_charge(p, self._merchants[p.request.merchant_id])
        for p, r in pending:
            self._attempt_refund(p, r)
        return unknown

    def _attempt_charge(self, payment: Payment, merchant: Merchant) -> None:
        req = payment.request
        try:
            result = self._retry.run(lambda: self._gateway.charge(req.idempotency_key, req.amount,
                                                                  req.payment_token))
        except (GatewayUnavailableError, GatewayTimeoutError) as e:
            with payment.lock:
                if payment.status is PaymentStatus.PROCESSING:
                    self._finish_charge(payment, PaymentStatus.UNKNOWN, reason=str(e))
            return
        with payment.lock:
            if payment.status not in (PaymentStatus.PROCESSING, PaymentStatus.UNKNOWN):
                return                                     # someone else already resolved it
            payment.gateway_ref = result.reference
            if result.decision is GatewayDecision.APPROVED:
                payment.fee = req.amount.fee(merchant.fee_bps)
                self._finish_charge(payment, PaymentStatus.SUCCEEDED)
            else:
                self._finish_charge(payment, PaymentStatus.FAILED, reason=result.reason)

    def _finish_charge(self, payment: Payment, to: PaymentStatus, reason: Optional[str] = None) -> None:
        """Caller holds payment.lock. State change and outbox event are one atomic step."""
        payment.transition(to)
        payment.failure_reason = reason
        self.outbox.append(f"payment.{to.value}", payment.payment_id,
                           amount=str(payment.amount), reason=reason or "")

    # ---- refund ------------------------------------------------------------

    def refund(self, payment_id: str, amount: Money, idempotency_key: str, reason: str = "") -> Refund:
        """Partial or full refund, idempotent on (payment_id, idempotency_key)."""
        if amount.amount <= 0:
            raise ValidationError("refund amount must be positive")
        payment = self.get(payment_id)

        with payment.lock:
            with self._lock:
                existing = self._refund_keys.get((payment_id, idempotency_key))
            if existing is not None:
                if existing.amount != amount:
                    raise IdempotencyConflictError(f"refund key {idempotency_key} reused with a different amount")
                return existing
            if payment.status not in REFUNDABLE:
                raise RefundError(f"{payment_id} is {payment.status.value}; only settled charges can be refunded")
            if payment.refundable() < amount:
                raise RefundError(f"refund {amount} exceeds refundable {payment.refundable()}")
            # Hold the amount before calling out, so concurrent refunds cannot over-refund.
            refund = Refund(f"re_{next(self._ids)}", payment_id, idempotency_key, amount, reason)
            payment.refunds.append(refund)
            with self._lock:
                self._refund_keys[(payment_id, idempotency_key)] = refund

        self._attempt_refund(payment, refund)
        return refund

    def _attempt_refund(self, payment: Payment, refund: Refund) -> None:
        try:
            result = self._retry.run(lambda: self._gateway.refund(refund.idempotency_key,
                                                                  payment.gateway_ref or "", refund.amount))
        except (GatewayUnavailableError, GatewayTimeoutError):
            return                         # stays PENDING with the amount held; reconcile() retries
        with payment.lock:
            if refund.status is not RefundStatus.PENDING:
                return
            refund.gateway_ref = result.reference
            if result.decision is GatewayDecision.APPROVED:
                refund.status = RefundStatus.SUCCEEDED
                fully = payment.refunded() == payment.amount
                payment.transition(PaymentStatus.REFUNDED if fully else PaymentStatus.PARTIALLY_REFUNDED)
                self.outbox.append("refund.succeeded", refund.refund_id,
                                   payment_id=payment.payment_id, amount=str(refund.amount))
            else:
                refund.status = RefundStatus.FAILED        # releases the hold
                self.outbox.append("refund.failed", refund.refund_id,
                                   payment_id=payment.payment_id, reason=result.reason)

    # ---- queries -----------------------------------------------------------

    def get(self, payment_id: str) -> Payment:
        with self._lock:
            payment = self._payments.get(payment_id)
        if payment is None:
            raise NotFoundError(payment_id)
        return payment


# ---------------------------------------------------------------- demo

def demo() -> None:
    gateway = SimulatedGateway()
    service = PaymentService(
        gateway,
        retry=RetryPolicy(max_attempts=3, sleep=lambda s: None),
        risk_rules=[AmountLimitRule(Money.of("10000.00", Currency.USD))],
    )
    service.add_merchant(Merchant("m_1", "TechStore", fee_bps=290))
    usd = lambda s: Money.of(s, Currency.USD)

    # 1. The dangerous case: the gateway charges the card, then our read times out.
    gateway.inject("timeout_after")
    req = PaymentRequest("order-42", "m_1", "cust_1", usd("1500.00"), "tok_visa")
    p = service.pay(req)
    print(f"1. {p.payment_id}: {p.status.value}, fee {p.fee}, charges at gateway: {len(gateway.money_moved)}")

    # 2. Client retries after its own timeout: same key -> same payment, no new charge.
    assert service.pay(req) is p
    print(f"2. retry returned {p.payment_id}; charges at gateway still {len(gateway.money_moved)}")

    # 3. Gateway stays down past all retries -> UNKNOWN, then reconcile resolves it.
    gateway.inject("timeout_before", "timeout_before", "timeout_before")
    p2 = service.pay(PaymentRequest("order-43", "m_1", "cust_1", usd("20.00"), "tok_visa"))
    print(f"3. {p2.payment_id}: {p2.status.value}", end=" -> ")
    service.reconcile()
    print(p2.status.value)

    # 4. Partial refunds; a retried refund is not applied twice; over-refund is rejected.
    service.refund(p.payment_id, usd("500.00"), "rf-1", "damaged")
    service.refund(p.payment_id, usd("500.00"), "rf-1", "damaged")
    try:
        service.refund(p.payment_id, usd("1000.01"), "rf-2")
    except RefundError as e:
        print("4. rejected:", e)
    print(f"   {p.payment_id}: {p.status.value}, refunded {p.refunded()}, refundable {p.refundable()}")

    # 5. Declines and risk rejections are terminal FAILED states.
    d = service.pay(PaymentRequest("order-44", "m_1", "cust_2", usd("10.00"), "tok_decline_nsf"))
    r = service.pay(PaymentRequest("order-45", "m_1", "cust_2", usd("50000.00"), "tok_visa"))
    print(f"5. {d.status.value} ({d.failure_reason}); {r.status.value} ({r.failure_reason})")

    # 6. Outbox relay: events leave in commit order.
    published: List[str] = []
    service.outbox.relay(lambda e: published.append(f"{e.type}:{e.aggregate_id}"))
    print("6. published:", published)


if __name__ == "__main__":
    demo()
