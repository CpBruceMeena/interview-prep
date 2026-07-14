"""
Payment Processing System - Low Level Design
----------------------------------------------
Design Principles: SOLID, Strategy Pattern, Chain of Responsibility, Observer
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Callable
import uuid


class PaymentStatus(Enum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"
    REFUNDED = "Refunded"
    PARTIALLY_REFUNDED = "Partially Refunded"
    DISPUTED = "Disputed"


class PaymentMethod(Enum):
    CREDIT_CARD = "Credit Card"
    DEBIT_CARD = "Debit Card"
    UPI = "UPI"
    NET_BANKING = "Net Banking"
    WALLET = "Wallet"
    CRYPTO = "Cryptocurrency"


class Currency(Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    INR = "INR"
    JPY = "JPY"


# --- Customer / Merchant (SRP) ---

class Customer:
    def __init__(self, customer_id: str, name: str, email: str):
        self._customer_id = customer_id
        self._name = name
        self._email = email
        self._payment_methods: List['PaymentMethodInfo'] = []

    @property
    def customer_id(self) -> str:
        return self._customer_id

    @property
    def name(self) -> str:
        return self._name

    def add_payment_method(self, method: 'PaymentMethodInfo') -> None:
        self._payment_methods.append(method)


class Merchant:
    def __init__(self, merchant_id: str, name: str, account_number: str):
        self._merchant_id = merchant_id
        self._name = name
        self._account_number = account_number
        self._fee_percentage = 2.5  # 2.5% processing fee

    @property
    def merchant_id(self) -> str:
        return self._merchant_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def fee_percentage(self) -> float:
        return self._fee_percentage

    def __str__(self) -> str:
        return self._name


class PaymentMethodInfo:
    """Stores tokenized payment method details"""
    def __init__(self, method_id: str, method_type: PaymentMethod,
                 token: str, last_four: str, is_default: bool = False):
        self._method_id = method_id
        self._method_type = method_type
        self._token = token  # Tokenized version, never store raw details
        self._last_four = last_four
        self._is_default = is_default

    @property
    def method_id(self) -> str:
        return self._method_id

    @property
    def method_type(self) -> PaymentMethod:
        return self._method_type

    def __str__(self) -> str:
        return f"{self._method_type.value} ending in {self._last_four}"


# --- Payment (Aggregate Root) ---

class Payment:
    def __init__(self, payment_id: str, amount: float, currency: Currency,
                 customer: Customer, merchant: Merchant,
                 payment_method: PaymentMethodInfo):
        self._payment_id = payment_id
        self._amount = amount
        self._currency = currency
        self._customer = customer
        self._merchant = merchant
        self._payment_method = payment_method
        self._status = PaymentStatus.PENDING
        self._created_at = datetime.now()
        self._completed_at: Optional[datetime] = None
        self._transaction_fee = 0.0
        self._refunded_amount = 0.0
        self._description: str = ""
        self._metadata: Dict[str, str] = {}

    @property
    def payment_id(self) -> str:
        return self._payment_id

    @property
    def amount(self) -> float:
        return self._amount

    @property
    def currency(self) -> Currency:
        return self._currency

    @property
    def customer(self) -> Customer:
        return self._customer

    @property
    def merchant(self) -> Merchant:
        return self._merchant

    @property
    def status(self) -> PaymentStatus:
        return self._status

    @status.setter
    def status(self, value: PaymentStatus) -> None:
        self._status = value
        if value == PaymentStatus.COMPLETED:
            self._completed_at = datetime.now()
            self._transaction_fee = self._amount * self._merchant.fee_percentage / 100

    def can_refund(self, amount: Optional[float] = None) -> bool:
        if self._status not in (PaymentStatus.COMPLETED, PaymentStatus.PARTIALLY_REFUNDED):
            return False
        remaining = self._amount - self._refunded_amount
        if amount:
            return amount <= remaining
        return remaining > 0

    def process_refund(self, amount: float) -> 'Refund':
        if not self.can_refund(amount):
            raise ValueError(f"Cannot refund {amount} for payment {self._payment_id}")
        refund = Refund.generate(self, amount)
        self._refunded_amount += amount
        if self._refunded_amount >= self._amount:
            self._status = PaymentStatus.REFUNDED
        else:
            self._status = PaymentStatus.PARTIALLY_REFUNDED
        return refund

    def set_description(self, description: str) -> None:
        self._description = description

    def __str__(self) -> str:
        return (f"Payment[{self._payment_id[:8]}]: "
                f"${self._amount:.2f} {self._currency.value} - {self._status.value}")


# --- Refund (SRP) ---

class Refund:
    def __init__(self, refund_id: str, payment: Payment,
                 amount: float, reason: str = ""):
        self._refund_id = refund_id
        self._payment = payment
        self._amount = amount
        self._reason = reason
        self._status = PaymentStatus.PENDING
        self._created_at = datetime.now()

    @classmethod
    def generate(cls, payment: Payment, amount: float,
                  reason: str = "") -> 'Refund':
        refund_id = f"RF-{uuid.uuid4().hex[:8].upper()}"
        return cls(refund_id, payment, amount, reason)

    @property
    def refund_id(self) -> str:
        return self._refund_id

    @property
    def amount(self) -> float:
        return self._amount

    def process(self) -> None:
        self._status = PaymentStatus.COMPLETED

    def __str__(self) -> str:
        return f"Refund[{self._refund_id[:8]}]: ${self._amount:.2f}"


# --- Payment Gateway Strategy (Strategy Pattern) ---

class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, payment: Payment) -> bool:
        """Process payment and return success/failure"""
        pass

    @abstractmethod
    def refund_transaction(self, refund: Refund) -> bool:
        pass

    @property
    @abstractmethod
    def gateway_name(self) -> str:
        pass


class StripeGateway(PaymentGateway):
    @property
    def gateway_name(self) -> str:
        return "Stripe"

    def charge(self, payment: Payment) -> bool:
        print(f"  [Stripe] Charging ${payment.amount:.2f} via {payment._payment_method}")
        # Simulate processing
        return True

    def refund_transaction(self, refund: Refund) -> bool:
        print(f"  [Stripe] Refunding ${refund.amount:.2f}")
        return True


class PayPalGateway(PaymentGateway):
    @property
    def gateway_name(self) -> str:
        return "PayPal"

    def charge(self, payment: Payment) -> bool:
        print(f"  [PayPal] Processing ${payment.amount:.2f}")
        return True

    def refund_transaction(self, refund: Refund) -> bool:
        print(f"  [PayPal] Processing refund ${refund.amount:.2f}")
        return True


class RazorpayGateway(PaymentGateway):
    @property
    def gateway_name(self) -> str:
        return "Razorpay"

    def charge(self, payment: Payment) -> bool:
        print(f"  [Razorpay] Processing INR payment")
        return True

    def refund_transaction(self, refund: Refund) -> bool:
        print(f"  [Razorpay] Processing refund")
        return True


# --- Payment Validator (Chain of Responsibility) ---

class PaymentValidator(ABC):
    def __init__(self):
        self._next: Optional[PaymentValidator] = None

    def set_next(self, validator: 'PaymentValidator') -> 'PaymentValidator':
        self._next = validator
        return validator

    def validate(self, payment: Payment) -> Tuple[bool, str]:
        result, message = self._do_validate(payment)
        if not result:
            return False, message
        if self._next:
            return self._next.validate(payment)
        return True, "Valid"

    @abstractmethod
    def _do_validate(self, payment: Payment) -> Tuple[bool, str]:
        pass


class AmountValidator(PaymentValidator):
    def _do_validate(self, payment: Payment) -> Tuple[bool, str]:
        if payment.amount <= 0:
            return False, "Amount must be positive"
        if payment.amount > 100000:
            return False, "Amount exceeds maximum limit"
        return True, "Amount OK"


class CurrencyValidator(PaymentValidator):
    def _do_validate(self, payment: Payment) -> Tuple[bool, str]:
        supported = {Currency.USD, Currency.EUR, Currency.INR, Currency.GBP}
        if payment.currency not in supported:
            return False, f"Currency {payment.currency.value} not supported"
        return True, "Currency OK"


class PaymentMethodValidator(PaymentValidator):
    def _do_validate(self, payment: Payment) -> Tuple[bool, str]:
        if not payment._payment_method:
            return False, "No payment method provided"
        return True, "Payment method OK"


# --- Fraud Detection (Strategy) ---

class FraudCheck(ABC):
    @abstractmethod
    def check(self, payment: Payment) -> Tuple[bool, str]:
        pass


class AmountFraudCheck(FraudCheck):
    def check(self, payment: Payment) -> Tuple[bool, str]:
        if payment.amount > 10000:
            return False, f"High amount ${payment.amount:.2f} flagged for review"
        return True, "Amount check passed"


class VelocityFraudCheck(FraudCheck):
    def __init__(self, max_per_hour: int = 5):
        self._max = max_per_hour
        self._recent: List[datetime] = []

    def check(self, payment: Payment) -> Tuple[bool, str]:
        now = datetime.now()
        self._recent = [t for t in self._recent if now - t < timedelta(hours=1)]
        if len(self._recent) >= self._max:
            return False, "Too many transactions in last hour"
        self._recent.append(now)
        return True, "Velocity check passed"


# --- Payment Service (Facade) ---

class PaymentService:
    def __init__(self, gateway: PaymentGateway):
        self._gateway = gateway
        self._payments: Dict[str, Payment] = {}
        self._refunds: Dict[str, Refund] = {}
        self._fraud_checks: List[FraudCheck] = []
        self._validators = PaymentMethodValidator()
        self._validators.set_next(AmountValidator()).set_next(CurrencyValidator())

    def add_fraud_check(self, check: FraudCheck) -> None:
        self._fraud_checks.append(check)

    def create_payment(self, customer: Customer, merchant: Merchant,
                       amount: float, currency: Currency = Currency.USD,
                       payment_method: Optional[PaymentMethodInfo] = None,
                       description: str = "") -> Payment:
        if not payment_method and customer._payment_methods:
            payment_method = customer._payment_methods[0]

        pid = f"PY-{uuid.uuid4().hex[:8].upper()}"
        payment = Payment(pid, amount, currency, customer, merchant, payment_method)
        payment.set_description(description)
        self._payments[pid] = payment
        return payment

    def process_payment(self, payment: Payment) -> Tuple[bool, str]:
        # Validate
        valid, msg = self._validators.validate(payment)
        if not valid:
            payment.status = PaymentStatus.FAILED
            return False, msg

        # Fraud check
        for check in self._fraud_checks:
            passed, msg = check.check(payment)
            if not passed:
                payment.status = PaymentStatus.FAILED
                return False, f"Fraud: {msg}"

        # Process
        payment.status = PaymentStatus.PROCESSING
        success = self._gateway.charge(payment)

        if success:
            payment.status = PaymentStatus.COMPLETED
            print(f"  ✅ Payment {payment.payment_id[:8]} completed: "
                  f"${payment.amount:.2f} via {self._gateway.gateway_name}")
            return True, "Success"
        else:
            payment.status = PaymentStatus.FAILED
            return False, "Payment gateway declined"

    def refund_payment(self, payment_id: str, amount: Optional[float] = None,
                       reason: str = "") -> Optional[Refund]:
        payment = self._payments.get(payment_id)
        if not payment:
            print(f"  Payment {payment_id} not found")
            return None

        refund_amount = amount or payment.amount
        if not payment.can_refund(refund_amount):
            print(f"  Cannot refund {refund_amount} for payment {payment_id}")
            return None

        refund = payment.process_refund(refund_amount)
        success = self._gateway.refund_transaction(refund)

        if success:
            refund.process()
            self._refunds[refund.refund_id] = refund
            print(f"  ✅ Refund ${refund_amount:.2f} processed for {payment_id[:8]}")
        else:
            print(f"  ❌ Refund failed for {payment_id[:8]}")

        return refund

    def get_payment(self, payment_id: str) -> Optional[Payment]:
        return self._payments.get(payment_id)

    def get_payments_by_customer(self, customer_id: str) -> List[Payment]:
        return [p for p in self._payments.values()
                if p.customer.customer_id == customer_id]


# --- Demo ---

def demo():
    print("=== Payment Processing System ===")
    print("=" * 50)

    # Setup
    gateway = StripeGateway()
    service = PaymentService(gateway)
    service.add_fraud_check(AmountFraudCheck())
    service.add_fraud_check(VelocityFraudCheck())

    # Create customer and merchant
    customer = Customer("CUST-001", "Alice Johnson", "alice@email.com")
    card = PaymentMethodInfo("PM-001", PaymentMethod.CREDIT_CARD,
                             "tok_visa_4242", "4242", True)
    customer.add_payment_method(card)

    merchant = Merchant("MER-001", "TechStore Inc.", "ACC-12345678")

    # Process payment
    print("\n--- Processing Payment ---")
    payment = service.create_payment(customer, merchant, 1500.00,
                                      Currency.USD, card,
                                      "MacBook Pro 14-inch")
    success, msg = service.process_payment(payment)

    print(f"\n  Result: {success} - {msg}")

    # Check status
    print(f"\n--- Payment Status ---")
    print(f"  {payment}")
    print(f"  Transaction fee: ${payment._transaction_fee:.2f}")

    # Refund
    print("\n--- Partial Refund ---")
    refund = service.refund_payment(payment.payment_id, 500.00, "Damaged item")
    if refund:
        print(f"  {refund}")
        print(f"  Payment status: {payment.status.value}")
        print(f"  Refunded amount: ${payment._refunded_amount:.2f}")

    # Fraud scenario
    print("\n--- Fraud Check Demo ---")
    payment2 = service.create_payment(customer, merchant, 50000.00)
    success, msg = service.process_payment(payment2)
    print(f"  Result: {success} - {msg}")


if __name__ == "__main__":
    demo()
