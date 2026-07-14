# 🧠 Payment Processing LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![](payment-processing-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

What payment methods? (Card, UPI, Wallet?) What gateways? (Stripe, PayPal?) What's the validation chain? Fraud detection? Refunds?

## Phase 1: Identify the Nouns

> *"A customer pays a merchant via a payment gateway. The payment is validated, checked for fraud, and processed. Refunds are possible."*

| Noun | Decision | Why |
|------|----------|-----|
| Customer | Regular Class | Has payment methods |
| Merchant | Regular Class | Has fee percentage |
| Payment | Regular Class | Aggregate root — status, amount, refunds |
| PaymentMethodInfo | Regular Class | Tokenized card/wallet details |
| PaymentGateway | ABC | Strategy pattern |
| PaymentValidator | ABC | Chain of Responsibility |
| FraudCheck | ABC | Strategy pattern |
| Refund | Regular Class | Linked to a Payment |
| PaymentService | Facade | Main entry point |

## Phase 2: Enums First

```python
class PaymentStatus(Enum):    PENDING, PROCESSING, COMPLETED, FAILED, REFUNDED, PARTIALLY_REFUNDED, DISPUTED
class PaymentMethod(Enum):    CREDIT_CARD, DEBIT_CARD, UPI, NET_BANKING, WALLET, CRYPTO
class Currency(Enum):         USD, EUR, GBP, INR, JPY
```

7 payment statuses! This is a complex state machine.

## Phase 3: dataclass vs `__init__`

- **`Payment`**: Regular — complex behavior (status transitions, refund processing)
- **`Refund`**: Regular — linked to payment, has its own lifecycle
- **`PaymentMethodInfo`**: Regular — holds tokenized data (never raw card numbers)
- **`Customer`/`Merchant`**: Regular — identity classes

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Validate payment | Chain of Validators | Each validator checks one thing |
| Check fraud | `FraudCheck` implementations | Strategy pattern |
| Charge card | `PaymentGateway.charge()` | Gateway-specific logic |
| Process refund | `Payment.process_refund()` | Payment tracks refunded amount |
| Orchestrate flow | `PaymentService.process_payment()` | Facade |

## Phase 5: Chain of Responsibility for Validation

```python
class PaymentValidator(ABC):
    def set_next(self, validator) -> PaymentValidator  # Chain
    def validate(self, payment) -> Tuple[bool, str]

amount_validator = AmountValidator()
currency_validator = CurrencyValidator()
method_validator = PaymentMethodValidator()

amount_validator.set_next(currency_validator).set_next(method_validator)
# Calls all three in sequence
```

**Why Chain of Responsibility?** Each validation concern is separate (amount, currency, method). They can be added/removed independently.

## Phase 6: Key Payment Flow

```
create_payment() → validate (chain) → fraud check (list) → gateway.charge() → COMPLETED
                                                        → Failed → FAILED
```

At each step, the payment status is updated. This makes debugging easy.

## Phase 7: Refund Tracking

```python
class Payment:
    def process_refund(self, amount):
        if self._refunded_amount + amount > self._amount:
            raise ValueError("Cannot refund more than charged")
        self._refunded_amount += amount
        # Auto-transition status
        if self._refunded_amount >= self._amount:
            self._status = REFUNDED
        else:
            self._status = PARTIALLY_REFUNDED
```

## Phase 8: Quick Checklist

✅ **Chain of Responsibility:** Validation chain is extensible
✅ **Strategy:** Gateways are swappable (Stripe, PayPal, Razorpay)
✅ **SRP:** Each class has one job — validation, fraud, gateway, payment
✅ **Encapsulation:** Payment status transitions are controlled
