# Payment Processing System - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Financial transactions, idempotency, fraud detection, PCI compliance, settlement

---

## Question 1: Core Design
**Interviewer:** *"Design a payment processing system — payments, refunds, fraud detection, merchant settlements."*

### 🎯 Expected Answer

**Payment lifecycle:**
```
PENDING → PROCESSING → COMPLETED → (can refund → REFUNDED)
    │           │            │
    └── FAILED  └── FAILED   └── DISPUTED
```

**Idempotency Key — The most critical design decision:**
```python
def process_payment(idempotency_key: str, amount, customer, merchant):
    # Check if already processed
    existing = redis.get(f"idempotency:{idempotency_key}")
    if existing:
        return existing  # Return previous result — never double-charge!
    
    payment = Payment(idempotency_key, amount, customer, merchant)
    result = gateway.charge(payment)
    
    # Store result with TTL (e.g., 24 hours)
    redis.setex(f"idempotency:{idempotency_key}", 86400, result)
    return result
```

**Why idempotency keys?** Network failures cause retries. Without idempotency, a retry after successful charge creates a double charge. The idempotency key ensures the second request returns the same result as the first — payment only processed once.

---

## Question 2: Payment Gateway Integration
**Interviewer:** *"Support multiple payment gateways."*

### 🎯 Answer

**Strategy Pattern + Fallback Chain:**
```python
class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, payment) -> bool: pass
    @abstractmethod
    def refund(self, refund) -> bool: pass

class StripeGateway(PaymentGateway): ...
class PayPalGateway(PaymentGateway): ...
class RazorpayGateway(PaymentGateway): ...

class GatewayRouter:
    def route(self, payment) -> PaymentGateway:
        # Geo-routing: use local gateway for lower fees
        if payment.currency == Currency.INR:
            return RazorpayGateway()
        if payment.amount > 10000:
            return StripeGateway()  # Better fraud protection for high-value
        return PayPalGateway()
```

**Circuit Breaker for gateway failures:**
```python
class CircuitBreaker:
    def __init__(self, threshold=5, timeout=30):
        self._failures = 0
        self._threshold = threshold
        self._state = "CLOSED"  # CLOSED → OPEN → HALF_OPEN → CLOSED
    
    def call(self, gateway, payment):
        if self._state == "OPEN":
            if time.time() - self._last_failure > self._timeout:
                self._state = "HALF_OPEN"
            else:
                raise CircuitOpenError()
        
        try:
            result = gateway.charge(payment)
            self._failures = 0
            self._state = "CLOSED"
            return result
        except Exception:
            self._failures += 1
            if self._failures >= self._threshold:
                self._state = "OPEN"
                self._last_failure = time.time()
            raise
```

---

## Question 3: Refund & Dispute Handling

**Refund flow:**
```python
class Refund:
    def __init__(self, payment, amount, reason):
        if payment.refunded_amount + amount > payment.amount:
            raise ValueError("Refund exceeds payment amount")
        self._status = "PENDING"
    
    def process(self):
        self._payment.status = "PROCESSING"
        success = gateway.refund(self)
        if success:
            self._status = "COMPLETED"
            self._payment.refunded_amount += self._amount
            if self._payment.refunded_amount >= self._payment.amount:
                self._payment.status = "REFUNDED"
            else:
                self._payment.status = "PARTIALLY_REFUNDED"
```

**Dispute lifecycle:**
```
CHARGEBACK → EVIDENCE_PENDING → EVIDENCE_SUBMITTED → RESOLVED
                                      │
                                      └── LOST (funds withdrawn)
                                      └── WON (funds returned)
```

---

## Question 4: Fraud Detection Pipeline

**Chain of Responsibility for fraud checks:**
```python
class FraudCheck(ABC):
    def __init__(self):
        self._next = None
    
    def set_next(self, check):
        self._next = check
        return check
    
    @abstractmethod
    def check(self, payment) -> Tuple[bool, str]: pass

class AmountFraudCheck(FraudCheck):
    def check(self, payment):
        if payment.amount > 10000:
            return False, "High-value transaction flagged"
        return self._next.check(payment) if self._next else (True, "")

class VelocityFraudCheck(FraudCheck):
    def check(self, payment):
        recent = get_recent_transactions(payment.customer_id, minutes=60)
        if len(recent) > 5:
            return False, "Transaction velocity exceeded"
        return self._next.check(payment) if self._next else (True, "")
```

---

## Question 5: Settlement & Reconciliation

```python
class SettlementEngine:
    def daily_settlement(self, date):
        for merchant in self._merchants:
            # Calculate: total_sales - fees - refunds
            gross = sum(tx.amount for tx in transactions(date, merchant))
            fees = sum(tx.fee for tx in transactions(date, merchant))
            refunds = sum(r.amount for r in refunds(date, merchant))
            
            net = gross - fees - refunds
            
            # Generate bank file (NEFT/ACH format)
            bank_file = self._generate_ach_file(merchant, net)
            
            # Upload to bank
            self._bank_connector.upload(bank_file)
            
            # Record settlement
            self._record_settlement(merchant, date, gross, fees, refunds, net)
```

---

## Question 6: PCI Compliance

| Requirement | Implementation |
|-------------|---------------|
| **Never store raw PAN** | Tokenization at point of entry |
| **Encryption at rest** | AES-256 for stored tokens |
| **Encryption in transit** | TLS 1.3 for all API calls |
| **Access control** | Least privilege, audit logs |
| **Key rotation** | Rotate encryption keys every 90 days |
| **SAQ validation** | Annual self-assessment questionnaire |

---

## Question 7: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | PaymentGateway | Interchangeable: Stripe, PayPal, Razorpay |
| **Chain of Responsibility** | Fraud checks | Composable validation pipeline |
| **Observer** | Notifications | Status changes → email, SMS |
| **Facade** | PaymentService | Unified payment API |
| **Factory** | Gateway creation | Config-driven routing |
| **Template Method** | Payment flow | Consistent process, customizable steps |
| **Circuit Breaker** | Gateway calls | Resilience pattern |
