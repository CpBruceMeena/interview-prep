# 🏗️ Software Design Patterns — Principal Engineer Deep-Dive

> *12 GoF patterns (Factory Method and Abstract Factory share a section) plus a selection framework, each with a pattern card (intent, structure, when not to use it), a runnable implementation and the trade-offs a staff interviewer probes. Code is Python 3.10+ unless marked; examples that call real SDKs (Stripe, boto3, psycopg2) need those packages.*

---

## Table of Contents

1. [Strategy Pattern](#1-strategy-pattern)
2. [Observer Pattern](#2-observer-pattern)
3. [Factory Method & Abstract Factory](#3-factory-method-abstract-factory)
4. [Singleton Pattern — When It's OK and When It's Not](#4-singleton-pattern-when-its-ok-and-when-its-not)
5. [Builder Pattern](#5-builder-pattern)
6. [Adapter Pattern](#6-adapter-pattern)
7. [Decorator Pattern](#7-decorator-pattern)
8. [Facade Pattern](#8-facade-pattern)
9. [Command Pattern](#9-command-pattern)
10. [State Pattern](#10-state-pattern)
11. [Template Method Pattern](#11-template-method-pattern)
12. [Pattern Selection — Production Decision Framework](#12-pattern-selection-production-decision-framework)

---

## 1. Strategy Pattern

**Q:** "Your payment processing system needs to support multiple payment gateways (Stripe, PayPal, Square) with different rate limits, retry logic, and error handling. The system should support adding new gateways without modifying existing code. Design this using the Strategy pattern. What are the alternatives? When would you NOT use Strategy?"

**What They're Really Testing:** Whether you understand Strategy as a way to apply the Open/Closed principle in production, and can identify when simpler approaches (like first-class functions) replace the need for the pattern entirely.

!!! abstract "Pattern card"
    **Intent (GoF):** define a family of algorithms, encapsulate each one, and make them interchangeable, so the algorithm can vary independently of the clients that use it.<br>
    **Structure:** a *Context* holds a reference to a *Strategy* interface; *ConcreteStrategies* implement it; the client (or a config/registry) picks which one the context uses.<br>
    **Use when:** several variants of one behaviour exist and must be chosen at runtime or added without editing the caller.<br>
    **Don't use when:** there are two stable variants (an `if` is clearer), or the variants are plain functions; in Python, Go, Java 8+ and Kotlin a function or lambda *is* a strategy, no class hierarchy needed.

### Answer

**The Problem Strategy Solves:**

```
Without Strategy:
┌──────────────────────────────────────┐
│            PaymentProcessor           │
│                                      │
│  def process_payment(method, amount): │
│    if method == 'stripe':            │
│      # 50 lines of Stripe code      │
│    elif method == 'paypal':           │
│      # 50 lines of PayPal code       │
│    elif method == 'square':          │
│      # 50 lines of Square code       │
│    elif method == 'new_gateway':      │
│      # Need to modify this method!   │
│                                      │
│  → Violates Open/Closed Principle    │
│  → 200+ line monster method          │
│  → Every new gateway = modify class  │
│  → Testing all paths is painful      │
└──────────────────────────────────────┘
```

**Strategy Pattern Implementation:**

```python
# ── STRATEGY INTERFACE ──────────────────────────────────────
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class PaymentResult:
    success: bool
    transaction_id: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[dict] = None
    gateway_used: Optional[str] = None
    retriable: bool = False        # True only if the charge certainly didn't happen

class PaymentGatewayStrategy(ABC):
    """Interface for all payment gateway strategies."""

    # Money is an integer in minor units (cents). int(19.99 * 100) == 1998,
    # so never multiply floats to get cents.
    @abstractmethod
    def charge(self, amount_cents: int, currency: str,
               source: dict) -> PaymentResult:
        """Charge a payment source."""

    @abstractmethod
    def refund(self, transaction_id: str,
               amount_cents: Optional[int] = None) -> PaymentResult:
        """Refund a transaction (full refund if amount is None)."""

    @abstractmethod
    def get_rate_limit(self) -> int:
        """Max requests/second we allow ourselves for this gateway (from config)."""

    @abstractmethod
    def is_available(self) -> bool:
        """Health check for this gateway."""

# ── CONCRETE STRATEGIES ─────────────────────────────────────

class StripeStrategy(PaymentGatewayStrategy):
    def __init__(self, api_key: str, webhook_secret: str, rate_limit: int):
        self.client = stripe.StripeClient(api_key)
        self.webhook_secret = webhook_secret
        self.rate_limit = rate_limit
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            reset_timeout=30,
        )

    def charge(self, amount_cents: int, currency: str,
               source: dict) -> PaymentResult:
        try:
            # Wrap in circuit breaker
            return self._circuit_breaker.call(
                self._do_charge, amount_cents, currency, source
            )
        except CircuitBreakerOpen:
            return PaymentResult(
                success=False,
                error_message="Stripe circuit breaker open",
                retriable=True,      # we never called Stripe: safe to try another gateway
            )

    def _do_charge(self, amount_cents: int, currency: str,
                   source: dict) -> PaymentResult:
        try:
            intent = self.client.v1.payment_intents.create(   # stripe-python >= 12.5
                params={
                    "amount": amount_cents,
                    "currency": currency.lower(),
                    "payment_method": source['payment_method_id'],
                    "confirm": True,
                },
                options={"idempotency_key": source['idempotency_key']},
            )
            return PaymentResult(
                success=True,
                transaction_id=intent.id,
                raw_response=intent.to_dict(),
            )
        except stripe.CardError as e:
            # A decline is a final answer from the bank: do NOT fail over.
            return PaymentResult(
                success=False,
                error_message=f"Card declined: {e.user_message}",
            )
        except stripe.RateLimitError:
            # Backoff and retry handled by caller
            raise

    def refund(self, transaction_id: str,
               amount_cents: Optional[int] = None) -> PaymentResult:
        params = {"payment_intent": transaction_id}
        if amount_cents is not None:
            params["amount"] = amount_cents      # omit for a full refund
        try:
            refund = self.client.v1.refunds.create(params=params)
            return PaymentResult(success=True, transaction_id=refund.id)
        except stripe.StripeError as e:
            return PaymentResult(success=False, error_message=str(e))

    def get_rate_limit(self) -> int:
        # Stripe documents ~100 ops/s global in live mode and lower
        # per-endpoint limits; use YOUR account's limits, from config.
        return self.rate_limit

    def is_available(self) -> bool:
        try:
            self.client.v1.balance.retrieve()
            return True
        except Exception:
            return False


class PayPalStrategy(PaymentGatewayStrategy):
    def __init__(self, client_id: str, client_secret: str, rate_limit: int):
        self.client = PayPalClient(client_id, client_secret)   # illustrative wrapper
        self.rate_limit = rate_limit

    def charge(self, amount_cents: int, currency: str,
               source: dict) -> PaymentResult:
        try:
            order = self.client.order.create({
                'intent': 'CAPTURE',
                'purchase_units': [{
                    'amount': {
                        'currency_code': currency,
                        'value': f"{amount_cents // 100}.{amount_cents % 100:02d}",  # "19.99"
                    }
                }],
            })
            capture = self.client.order.capture(order.id)
            return PaymentResult(
                success=True,
                transaction_id=capture.id,
                raw_response=capture.to_dict(),
            )
        except PayPalError as e:
            return PaymentResult(
                success=False,
                error_message=f"PayPal error: {e.message}",
            )

    def refund(self, transaction_id: str,
               amount_cents: Optional[int] = None) -> PaymentResult:
        try:
            refund = self.client.payment.refund(
                transaction_id,
                amount_cents=amount_cents,
            )
            return PaymentResult(success=True, transaction_id=refund.id)
        except Exception as e:
            return PaymentResult(success=False, error_message=str(e))

    def get_rate_limit(self) -> int:
        return self.rate_limit

    def is_available(self) -> bool:
        try:
            self.client.auth.get_token()
            return True
        except Exception:
            return False


class SquareStrategy(PaymentGatewayStrategy):
    """Same shape as above: charge/refund/get_rate_limit/is_available.
    (Elided; as written with only `pass` it would be abstract and
    raise TypeError on instantiation.)"""

# ── CONTEXT (uses strategies) ───────────────────────────────

class PaymentProcessor:
    """
    Context class that uses payment gateway strategies.
    Selects strategy based on availability, rate limits, and cost.
    """

    def __init__(self):
        # Register all available strategies
        self.gateways: dict[str, PaymentGatewayStrategy] = {
            'stripe': StripeStrategy(
                api_key=os.environ['STRIPE_API_KEY'],
                webhook_secret=os.environ['STRIPE_WEBHOOK_SECRET'],
                rate_limit=int(os.environ.get('STRIPE_RPS', '80')),
            ),
            'paypal': PayPalStrategy(
                client_id=os.environ['PAYPAL_CLIENT_ID'],
                client_secret=os.environ['PAYPAL_CLIENT_SECRET'],
                rate_limit=int(os.environ.get('PAYPAL_RPS', '40')),
            ),
            'square': SquareStrategy(
                access_token=os.environ['SQUARE_ACCESS_TOKEN'],
            ),
        }

    def process_payment(self, amount_cents: int, currency: str,
                        source: dict, preferred: Optional[str] = None) -> PaymentResult:
        """
        Process a payment, automatically selecting the best gateway.

        Selection criteria:
          1. Use preferred gateway if available and healthy
          2. Fall back ONLY if the failure proves no charge happened
          3. Consider rate limits and current load
        """
        if preferred and preferred in self.gateways:
            gateway = self.gateways[preferred]
            if gateway.is_available():
                result = gateway.charge(amount_cents, currency, source)
                if result.success:
                    return self._enrich_result(result, preferred)
                if not result.retriable:
                    return result   # declined, or outcome unknown: don't double-charge

        # Fallback: try other gateways
        for name, gateway in self.gateways.items():
            if name == preferred:
                continue  # Already tried
            if not gateway.is_available():
                continue
            if self._is_rate_limited(gateway):
                continue

            result = gateway.charge(amount_cents, currency, source)
            if result.success:
                return self._enrich_result(result, name)
            if not result.retriable:
                return result

        return PaymentResult(
            success=False,
            error_message="All payment gateways failed",
        )

    def _is_rate_limited(self, gateway: PaymentGatewayStrategy) -> bool:
        """Check if gateway is approaching its rate limit."""
        current_rate = self._get_current_rate(gateway)   # e.g. sliding-window counter
        return current_rate > gateway.get_rate_limit() * 0.8

    def _enrich_result(self, result: PaymentResult,
                       gateway_name: str) -> PaymentResult:
        result.gateway_used = gateway_name
        return result
```

**Alternatives to Strategy Pattern:**

```python
# ── ALTERNATIVE 1: First-class functions (simpler!) ─────────
# In languages with first-class functions, Strategy is just a
# function passed as a parameter:

def process_payment_stripe(amount, currency, source):
    """Stripe-specific implementation."""
    ...

def process_payment_paypal(amount, currency, source):
    """PayPal-specific implementation."""
    ...

# Registration
gateway_registry: dict[str, Callable] = {
    'stripe': process_payment_stripe,
    'paypal': process_payment_paypal,
}

# Usage — just pass the function
def process(amount, currency, source, gateway_fn):
    return gateway_fn(amount, currency, source)

# ── ALTERNATIVE 2: Dictionary dispatch ─────────────────────
# When strategies have no state, a dict of functions is enough:

GATEWAY_HANDLERS = {
    'stripe': {
        'charge': lambda amt, cur, src: stripe_charge(amt, cur, src),
        'refund': lambda tx_id: stripe_refund(tx_id),
    },
    'paypal': {
        'charge': lambda amt, cur, src: paypal_charge(amt, cur, src),
        'refund': lambda tx_id: paypal_refund(tx_id),
    },
}

def charge(gateway, amount, currency, source):
    return GATEWAY_HANDLERS[gateway]['charge'](amount, currency, source)
```

**When NOT to Use Strategy:**

```yaml
Strategy is overkill when:
  1. You have only 2 stable variations (use if/else)
  2. The algorithm never changes at runtime and nobody else adds variants
  3. The algorithm is a simple one-liner
  4. Variants are stateless and your language has first-class functions
     (pass a function; it is still the Strategy pattern, minus the classes)
  5. The strategies share 90%+ code (factor the shared part out, or use
     Template Method for a fixed skeleton)

Use Strategy when:
  1. You need to switch algorithms at runtime
  2. You want to add new algorithms without modifying existing code
  3. The algorithms have complex state/logic that benefit from classes
  4. You need common infrastructure (logging, metrics, circuit breakers)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Open/Closed** | Explains how Strategy enables adding gateways without modifying PaymentProcessor |
| **Fallback logic** | Implements automatic fallback when primary gateway fails |
| **Function alternative** | Knows that first-class functions can replace Strategy in simpler cases |
| **Circuit breaker** | Adds infrastructure concerns (rate limits, health checks) to the pattern |
| **Payment safety** | Fails over only when the first gateway certainly didn't charge; money in integer minor units |

---

## 2. Observer Pattern

**Q:** "Design an event-driven notification system where users can subscribe to different types of events (order updates, price changes, inventory alerts). The system must support both push and pull models, handle subscriber failures gracefully, and scale to 10K events/second. Implement this using the Observer pattern, then critique its limitations."

**What They're Really Testing:** Whether you understand the Observer pattern's strengths (decoupling) and weaknesses (memory leaks, notification storms, subscriber failure propagation) from production experience.

!!! abstract "Pattern card"
    **Intent (GoF):** define a one-to-many dependency so that when one object (the *subject*) changes state, all its dependents (*observers*) are notified automatically.<br>
    **Structure:** *Subject* keeps a list of *Observer*s and offers `attach`/`detach`/`notify`; each *ConcreteObserver* implements `update(event)`. An **event bus** (pub/sub) adds a broker between them, so publishers and subscribers don't reference each other at all.<br>
    **Use when:** several independent reactions follow one change, and the source shouldn't know about them (UI updates, domain events inside a service, cache invalidation).<br>
    **Don't use when:** the order of reactions matters or the caller needs their result (call them explicitly); or the reactions cross process boundaries and must survive crashes. In-process observers lose events on restart, so use a durable broker (Kafka, SQS) with an outbox.

### Answer

**Push vs pull:**

| Model | Subject sends | Pros | Cons |
|-------|---------------|------|------|
| **Push** | The data (`OrderShipped{order_id, tracking_no}`) | One hop; observers don't call back | Payload may be large or irrelevant to some observers; schema becomes a contract |
| **Pull** | Only "X changed" (`PriceChanged{product_id}`) | Small events; observer fetches exactly what it needs, always fresh | N observers × 1 read each: a notification can trigger a thundering herd on the source |

At 10K events/s, push with a *self-contained* event is usually right; pull is useful when the data is large or sensitive and only some observers need it.

**Production-grade in-process Event Bus (runs as-is):**

```python
import asyncio
import logging
import weakref
from collections import defaultdict
from typing import Any, Awaitable, Callable

Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    """In-process pub/sub. Publishers don't know who listens.

    - Handler failures are isolated and logged.
    - Each handler gets a timeout so one slow subscriber can't stall publish().
    - subscribe() returns an unsubscribe function: the caller owns cleanup.
    - subscribe_weak() holds bound methods weakly, so a forgotten subscriber
      can still be garbage-collected.
    """

    def __init__(self, handler_timeout: float = 5.0):
        self._handlers: dict[str, list] = defaultdict(list)  # entries: callable or WeakMethod
        self._timeout = handler_timeout

    def subscribe(self, event_type: str, handler: Handler) -> Callable[[], None]:
        self._handlers[event_type].append(handler)
        return lambda: self._remove(event_type, handler)

    def subscribe_weak(self, event_type: str, bound_method: Handler) -> None:
        # weakref.ref(obj.method) would die immediately: a bound method is a
        # temporary object. WeakMethod tracks the instance instead.
        self._handlers[event_type].append(weakref.WeakMethod(bound_method))

    def _remove(self, event_type: str, entry) -> None:
        try:
            self._handlers[event_type].remove(entry)
        except ValueError:
            pass

    def _live_handlers(self, event_type: str) -> list[Handler]:
        live = []
        for entry in list(self._handlers[event_type]):   # copy: handlers may unsubscribe
            if isinstance(entry, weakref.WeakMethod):
                fn = entry()
                if fn is None:                             # owner was collected
                    self._remove(event_type, entry)
                    continue
                live.append(fn)
            else:
                live.append(entry)
        return live

    async def publish(self, event_type: str, event: Any) -> None:
        handlers = self._live_handlers(event_type)
        results = await asyncio.gather(
            *(asyncio.wait_for(h(event), self._timeout) for h in handlers),
            return_exceptions=True,                        # isolate failures
        )
        for h, r in zip(handlers, results):
            if isinstance(r, BaseException):
                logging.error("handler %s failed: %r", getattr(h, "__qualname__", h), r)
```

```python
# ── USAGE ──────────────────────────────────────────────────
class OrderNotifier:
    def __init__(self, bus: EventBus):
        self._unsubscribe = [
            bus.subscribe("order.created", self.on_created),
            bus.subscribe("order.shipped", self.on_shipped),
        ]

    async def on_created(self, event):
        await email_service.send_confirmation(event["order_id"])

    async def on_shipped(self, event):
        await sms_service.send_tracking(event["user_phone"], event["tracking_number"])

    def close(self):
        """Explicit lifecycle. Don't rely on __del__: the bus holds a strong
        reference to these bound methods, so __del__ would never run."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()


class OrderService:
    def __init__(self, db, bus: EventBus):
        self.db, self.bus = db, bus

    async def create_order(self, order_data):
        order = await self.db.create_order(order_data)
        # Publisher has no idea who listens.
        await self.bus.publish("order.created", {"order_id": order.id, "user_id": order.user_id})
        return order
```

**Observer pitfalls and fixes:**

1. **Lapsed listener (memory leak).** The subject's list holds a strong reference to every bound method, and a bound method holds its object. A component that subscribes and is "thrown away" stays alive and keeps receiving events. Fix: explicit `unsubscribe` tied to the component's lifecycle (the function returned by `subscribe`), or `WeakMethod`. A plain `weakref.ref(obj.method)` is a classic bug: the bound method is a temporary, so the reference is dead immediately.
2. **Failure propagation.** One observer raising must not stop the others or fail the publisher. `gather(..., return_exceptions=True)` isolates it.
3. **Slow observers.** Synchronous notification makes the publisher as slow as the slowest observer. Bound each handler with a timeout, or hand events to a queue and let observers consume at their own pace.
4. **Notification storms.** 1,000 price updates × 1,000 observers = 1,000,000 handler calls. Coalesce bursts:

```python
import asyncio


class PriceChangeBatcher:
    """Coalesces bursts: 1,000 price updates in 100 ms become ONE notification
    with the latest price per product."""

    def __init__(self, bus, window_s: float = 0.1):
        self.bus, self.window_s = bus, window_s
        self._pending: dict[str, int] = {}
        self._flush_task: asyncio.Task | None = None

    def price_changed(self, product_id: str, price_cents: int) -> None:
        self._pending[product_id] = price_cents          # last write wins per product
        if self._flush_task is None:                     # start a window on first change
            self._flush_task = asyncio.get_running_loop().create_task(self._flush_later())

    async def _flush_later(self) -> None:
        await asyncio.sleep(self.window_s)
        batch, self._pending, self._flush_task = self._pending, {}, None
        await self.bus.publish("prices.changed", batch)
```

5. **Fire-and-forget tasks.** `asyncio.create_task(...)` without keeping a reference can be garbage-collected before it finishes, and its exceptions disappear. Keep task references (or use `asyncio.TaskGroup`) and log failures.
6. **Re-entrancy and ordering.** An observer that publishes during `publish()` can cause cascades or infinite loops; observers must not rely on being called in any order.

**Scaling to 10K events/s across services:** in-process observers don't survive restarts or scale out. Publish domain events to Kafka (via a transactional outbox), give each notification channel (email, SMS, push) its own consumer group, partition by `user_id` for per-user ordering, and send failures to a retry topic and then a DLQ. That's still the Observer pattern; the broker is the subject's subscriber list, made durable.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Push vs pull** | Explains both models and when to use each |
| **Memory leaks** | Identifies the lapsed-listener problem; explicit unsubscribe or `WeakMethod` (not `weakref.ref` on a bound method) |
| **Isolation** | Ensures one failing or slow observer doesn't affect others |
| **Event bus** | Mentions decoupled pub-sub, and a durable broker once events cross processes |
| **Thundering herd** | Identifies notification storms and proposes batching/coalescing |

---

## 3. Factory Method & Abstract Factory

**Q:** "Design a document processing system that handles PDF, Word, HTML, and Markdown documents. Documents need different parsers, renderers, and exporters. Walk through both Factory Method and Abstract Factory patterns. When would you choose one over the other? When is a factory just unnecessary complexity?"

**What They're Really Testing:** Whether you understand factories as a way to manage object creation when constructors aren't enough, and can distinguish between genuine creation complexity and over-engineering.

!!! abstract "Pattern card"
    **Factory Method (GoF):** define an interface for creating an object, but let **subclasses** decide which class to instantiate. Structure: a *Creator* with an overridable `create_x()` method, used by the creator's own logic; *ConcreteCreators* override it.<br>
    **Abstract Factory (GoF):** provide an interface for creating **families** of related objects without naming their concrete classes. Structure: an *AbstractFactory* with one `create_*` per product; each *ConcreteFactory* returns a matching set.<br>
    **Simple factory** (not a GoF pattern, but what most people mean by "factory"): one function that maps an input (file extension, config value) to a class.<br>
    **Use when:** callers must not depend on concrete classes, the choice depends on runtime input, or several products must stay consistent with each other.<br>
    **Don't use when:** a constructor call or a dict of classes does the job; a factory with one product and no logic is indirection without benefit.

### Answer

**Factory Method — Single Product Family:**

```python
# ── THE PROBLEM: Direct construction is inflexible ──────────
class Document:
    def __init__(self, path: str):
        self.path = path
        # But how do we parse differently per format?
        # Constructor can't decide the parser!

# ── FACTORY METHOD ──────────────────────────────────────────
from abc import ABC, abstractmethod

class Document(ABC):
    """Product — represents a parsed document."""

    def __init__(self, path: str):
        self.path = path
        # Calling overridable methods from a constructor works in Python, but in
        # Java/C#/C++ it's a known hazard: the subclass's fields aren't set yet.
        self.content = self._parse(path)          # hook for subclasses
        self._renderer = self._create_renderer()  # the Factory Method

    @abstractmethod
    def _parse(self, path: str):
        """Factory Method: subclasses define how to parse."""
        pass

    @abstractmethod
    def _create_renderer(self):
        """Factory Method: subclasses define the renderer."""
        pass

    def render(self) -> str:
        return self._renderer.render(self.content)


class PDFDocument(Document):
    def _parse(self, path: str):
        return pdf_parser.parse(path)

    def _create_renderer(self):
        return PDFRenderer()


class MarkdownDocument(Document):
    def _parse(self, path: str):
        return markdown_parser.parse(path)

    def _create_renderer(self):
        return HTMLRenderer()  # MD renders as HTML


class WordDocument(Document):
    def _parse(self, path: str):
        return word_parser.parse(path)

    def _create_renderer(self):
        return WordRenderer()


# ── SIMPLE (PARAMETERIZED) FACTORY ─────────────────────────
# Not GoF Factory Method: one function decides the class from input.
# This is what "factory" means in most codebases.
from pathlib import Path

class DocumentFactory:
    """Factory method that creates the right document type."""

    @staticmethod
    def create(path: str) -> Document:
        ext = Path(path).suffix.lower()

        factories = {
            '.pdf': PDFDocument,
            '.md': MarkdownDocument,
            '.docx': WordDocument,
            '.html': HTMLDocument,
        }

        doc_class = factories.get(ext)
        if not doc_class:
            raise ValueError(f"Unsupported document type: {ext}")

        return doc_class(path)

# Usage:
# doc = DocumentFactory.create("report.pdf")
# content = doc.render()
```

**Abstract Factory — Multiple Product Families:**

```python
# ── ABSTRACT FACTORY ────────────────────────────────────────
# Use when you need FAMILIES of related products that must
# work together (e.g., UI widgets for different OS themes)

from abc import ABC, abstractmethod

# Product interfaces
class Button(ABC):
    @abstractmethod
    def render(self) -> str:
        pass

    @abstractmethod
    def on_click(self, handler):
        pass

class TextField(ABC):
    @abstractmethod
    def render(self) -> str:
        pass

    @abstractmethod
    def set_text(self, text: str):
        pass

class Checkbox(ABC):
    @abstractmethod
    def render(self) -> str:
        pass

# Abstract Factory
class UIFactory(ABC):
    """
    Abstract Factory: creates families of related UI widgets.
    Each concrete factory creates widgets that are CONSISTENT
    with each other (e.g., all dark-theme widgets match).
    """

    @abstractmethod
    def create_button(self) -> Button:
        pass

    @abstractmethod
    def create_text_field(self) -> TextField:
        pass

    @abstractmethod
    def create_checkbox(self) -> Checkbox:
        pass


# ── CONCRETE FACTORY: Light Theme ───────────────────────────
class LightButton(Button):
    def render(self):
        return "[ Light Button ]"

    def on_click(self, handler):
        handler()

class LightTextField(TextField):
    def render(self):
        return "[ Light Text Field ]"

    def set_text(self, text):
        print(f"Light text field: {text}")

class LightCheckbox(Checkbox):
    def render(self):
        return "[☐ Light Checkbox]"

class LightUIFactory(UIFactory):
    """Concrete factory for light theme."""

    def create_button(self) -> Button:
        return LightButton()

    def create_text_field(self) -> TextField:
        return LightTextField()

    def create_checkbox(self) -> Checkbox:
        return LightCheckbox()


# ── CONCRETE FACTORY: Dark Theme ────────────────────────────
class DarkButton(Button):
    def render(self):
        return "[ Dark Button ]"

    def on_click(self, handler):      # every abstract method must be implemented,
        handler()                     # or instantiation raises TypeError

class DarkTextField(TextField):
    def render(self):
        return "[ Dark Text Field ]"

    def set_text(self, text):
        print(f"Dark text field: {text}")

class DarkCheckbox(Checkbox):
    def render(self):
        return "[☑ Dark Checkbox]"

class DarkUIFactory(UIFactory):
    """Concrete factory for dark theme."""

    def create_button(self) -> Button:
        return DarkButton()

    def create_text_field(self) -> TextField:
        return DarkTextField()

    def create_checkbox(self) -> Checkbox:
        return DarkCheckbox()


# ── CLIENT CODE ─────────────────────────────────────────────
class Application:
    """Client that uses the Abstract Factory."""

    def __init__(self, factory: UIFactory):
        self.factory = factory
        self.button = factory.create_button()
        self.text_field = factory.create_text_field()
        self.checkbox = factory.create_checkbox()

    def render(self):
        return f"{self.button.render()} {self.text_field.render()} {self.checkbox.render()}"

    def on_submit(self):
        self.button.on_click(lambda: print("Submitted"))

# Usage:
# theme = load_user_theme_preference()
# factory = LightUIFactory() if theme == 'light' else DarkUIFactory()
# app = Application(factory)
# print(app.render())
# → "[ Dark Button ] [ Dark Text Field ] [☑ Dark Checkbox]"
```

**Factory Method vs Abstract Factory:**

```yaml
Factory Method:
  - Creates ONE product type
  - Subclass decides which class to instantiate
  - Uses inheritance
  - Example: Document._create_renderer()

Abstract Factory:
  - Creates a FAMILY of related products
  - Concrete factory decides WHICH family
  - Uses composition (client has a factory)
  - Example: UIFactory creates Button + TextField + Checkbox

When one is better:
  Factory Method: Single product with multiple variants
  Abstract Factory: Multiple products that must be consistent together
```

**When Factories Are Unnecessary:**

```python
# ❌ OVER-ENGINEERED: Factory for simple object creation
class UserFactory:
    @staticmethod
    def create(name, email):
        return User(name, email)

# ✅ Simpler: Just use the constructor!
user = User(name, email)

# ❌ OVER-ENGINEERED: Factory when Python can use callables
class ParserFactory:
    def get_parser(self, format):
        if format == 'json':
            return JSONParser()
        elif format == 'yaml':
            return YAMLParser()

# ✅ Simpler: dictionary of callables
PARSERS = {
    'json': JSONParser,
    'yaml': YAMLParser,
    'toml': TOMLParser,
}

parser = PARSERS[format]()  # Create instance directly

# ✅ Even simpler: registrable decorator
PARSER_REGISTRY = {}

def register_parser(format):
    def decorator(cls):
        PARSER_REGISTRY[format] = cls
        return cls
    return decorator

@register_parser('json')
class JSONParser: ...

@register_parser('yaml')
class YAMLParser: ...

# No factory needed! Just registry + constructor call.
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Factory Method** | Creates single product, subclasses decide implementation |
| **Abstract Factory** | Creates product families that must be consistent |
| **When to skip** | Knows when a simple dict of callables replaces a factory |
| **Registrable pattern** | Proposes decorator-based registration as a Pythonic alternative |
| **Naming precision** | Doesn't call every `create()` function "Factory Method"; knows the simple-factory distinction |

---

## 4. Singleton Pattern — When It's OK and When It's Not

**Q:** "Singleton is often called an anti-pattern. Defend it: when is Singleton actually the right choice in production? Then critique it: why is it problematic for testing and dependency management? Show me a thread-safe Singleton implementation and a Dependency Injection alternative."

**What They're Really Testing:** Whether you understand the Singleton debate at a nuanced level — not "Singleton is always bad" or "Singleton is always good" — but when it genuinely helps and when it hurts.

!!! abstract "Pattern card"
    **Intent (GoF):** ensure a class has only one instance and provide a global point of access to it.<br>
    **Structure:** a private/guarded constructor, a static `instance()` accessor, lazy or eager creation (thread-safe if lazy).<br>
    **The two halves are separable:** "exactly one instance" is often legitimate (a connection pool, a metrics registry); "global access" is the part that hurts, because it hides dependencies and couples tests. Keep the first, drop the second: create one instance at startup and **inject** it.<br>
    **Remember the scope:** a singleton is one per *process* (per class loader in Java). With 4 Gunicorn workers × 10 pods you have 40 "singletons", so size the pool for that (40 × 20 connections = 800 DB connections).<br>
    **Don't use when:** you want convenience access to a service, or the object holds mutable state that tests need to reset.

### Answer

**Thread-Safe Singleton in Python:**

```python
# ── APPROACH 1: Module-level singleton (Pythonic) ──────────
# In Python, modules are singletons. Just define at module level.

# config.py
class _AppConfig:
    """Application configuration. Module-level singleton."""

    def __init__(self):
        self.database_url: str = ""
        self.redis_url: str = ""
        self.api_keys: dict = {}
        self._loaded = False

    def load(self, env: str = "development"):
        if self._loaded:
            return  # Already loaded — idempotent
        self.database_url = os.environ.get("DATABASE_URL", "sqlite:///dev.db")
        self.redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        self.api_keys = self._load_api_keys()
        self._loaded = True

    def _load_api_keys(self) -> dict:
        return json.loads(os.environ.get("API_KEYS", "{}"))

# Module-level instance (Python's natural singleton)
config = _AppConfig()

# Usage:
# from config import config
# config.load()
# db_url = config.database_url


# ── APPROACH 2: Thread-safe Singleton class ────────────────
import threading

class ThreadSafeSingleton:
    """
    Thread-safe Singleton with double-checked locking.
    The unlocked first check is a fast path; the second check under the lock
    is what makes it correct. (In Java, DCL is only correct if the field is
    `volatile`; the idiomatic Java answer is an enum or a holder class.)
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:  # Double-checked locking
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._do_init()
            self._initialized = True

    def _do_init(self):
        """One-time initialization."""
        self.connection_pool = self._create_connection_pool()
        self.cache = {}

    def _create_connection_pool(self):
        return {"connections": 10}  # Simulated


# ── APPROACH 3: Metaclass Singleton ─────────────────────────
class SingletonMeta(type):
    """Metaclass for creating singletons."""

    _instances = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    instance = super().__call__(*args, **kwargs)
                    cls._instances[cls] = instance
        return cls._instances[cls]

class DatabasePool(metaclass=SingletonMeta):
    def __init__(self):
        self.pool = self._create_pool()

    def _create_pool(self):
        return psycopg2.pool.ThreadedConnectionPool(1, 20, os.environ["DATABASE_URL"])
```

**When Singleton Is the RIGHT Choice:**

```yaml
Singleton is acceptable when:
  1. Resource pools (database connections, thread pools)
     - You truly want ONE pool shared across the application
     - Multiple pools would exhaust resources (too many connections)
  2. Configuration/registry
     - Application config is read once and shared globally
     - Logging configuration
  3. Hardware interfaces
     - Printer spooler, GPU context, FPGA interface
     - Physical hardware can only be accessed from one instance
  4. Cache that must be shared
     - In-process cache with global visibility
     - Metrics registry

Key criteria: Does the system have a GENUINE need for exactly one instance?
  - Connection pool: YES, one per process; 50 pools in one process would
    exhaust the database's connection limit
  - Logging config / metrics registry: YES, one per process
  - UserService: NO — there's no reason you can't have two UserService instances
```

**When Singleton Is the WRONG Choice:**

```yaml
Singleton is harmful when:
  1. You use it just for "global access" convenience
     → Use dependency injection instead
  2. The singleton holds state that makes testing impossible
     → Can't reset state between tests
     → Tests become order-dependent
  3. The singleton depends on infrastructure (DB, external API)
     → Can't mock/replace in tests
  4. You might need multiple instances in the future
     → Multi-tenant systems, test configurations
```

**Singleton vs Dependency Injection:**

```python
# ── BAD: Singleton makes testing impossible ─────────────────
class UserService:
    """Singleton — hard to test."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Hardcoded dependency — can't replace in tests!
            cls._instance.db = DatabasePool()
            cls._instance.cache = RedisCache()
        return cls._instance

    def get_user(self, user_id):
        return self.db.query("SELECT * FROM users WHERE id = %s", user_id)

# Test:
def test_get_user():
    # PROBLEM: Can't replace db with mock
    # DatabasePool() is hardcoded in __new__
    # Test hits the real database!
    service = UserService()
    user = service.get_user(1)


# ── GOOD: Dependency Injection makes testing easy ──────────
class UserService:
    """DI — easy to test. Not a singleton."""

    def __init__(self, db: DatabasePool, cache: RedisCache):
        # Dependencies are INJECTED, not created
        self.db = db
        self.cache = cache

    def get_user(self, user_id):
        return self.db.query("SELECT * FROM users WHERE id = %s", user_id)

# Test:
def test_get_user():
    mock_db = MagicMock()
    mock_db.query.return_value = {"id": 1, "name": "Test"}

    service = UserService(db=mock_db, cache=MagicMock())
    user = service.get_user(1)

    assert user["name"] == "Test"
    mock_db.query.assert_called_once_with(
        "SELECT * FROM users WHERE id = %s", 1
    )


# ── BEST: Dependency Injection FRAMEWORK ────────────────────
# Use a DI framework for production wiring:

# container.py
from dependency_injector import containers, providers

class AppContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    # DatabasePool here is a plain class taking a url (not the metaclass one above):
    # the CONTAINER enforces "one instance", the class itself stays testable.
    db = providers.Singleton(DatabasePool, url=config.database_url)
    # ^ Singleton scope: one instance per app
    #   But replaceable in tests!

    cache = providers.Singleton(RedisCache, url=config.redis_url)

    user_service = providers.Factory(
        UserService,
        db=db,
        cache=cache,
    )
    # ^ Factory scope: new instance per injection site

# main.py
container = AppContainer()
container.config.database_url.from_env("DATABASE_URL")
container.config.redis_url.from_env("REDIS_URL")

user_service = container.user_service()
# DatabasePool is singleton (one pool), UserService is factory (new each time)

# test.py
def test_get_user():
    container = AppContainer()
    container.db.override(providers.Factory(MagicMock))  # Replace DB with mock
    container.cache.override(providers.Factory(MagicMock))

    user_service = container.user_service()
    user_service.db.query.return_value = {"id": 1}
    assert user_service.get_user(1) == {"id": 1}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Thread safety** | Implements thread-safe singleton with double-checked locking; knows Java needs `volatile` (or an enum/holder) |
| **Scope** | Knows "single" means per process/class loader, and what that means for pools across pods |
| **When singleton works** | Identifies genuine single-instance needs (pools, config) |
| **Testing critique** | Shows how singleton makes testing impossible and DI makes it easy |
| **DI container** | Proposes DI framework with singleton scope for app-wide dependencies |

---

## 5. Builder Pattern

**Q:** "Design a query builder for a database that constructs complex SQL queries programmatically. Walk through the Builder pattern. How does it handle the 'telescoping constructor' problem? When does a builder become over-engineering?"

**What They're Really Testing:** Whether you understand the Builder pattern's primary use case — constructing complex objects with many optional parameters — and can distinguish it from simple named parameters.

!!! abstract "Pattern card"
    **Intent (GoF):** separate the construction of a complex object from its representation, so the same construction process can create different representations. In everyday use (Bloch's *Effective Java* builder) it means building an **immutable** object step by step, with validation in `build()`.<br>
    **Structure:** a *Builder* with fluent setters that return `this`/`self` and a `build()` that validates and returns the *Product*; optionally a *Director* that runs a standard sequence of steps.<br>
    **Use when:** many optional parameters in a language without named arguments (Java, Go uses functional options instead), cross-field validation, immutable results, or incremental/conditional construction (query builders, test-data builders).<br>
    **Don't use when:** the language has keyword arguments and defaults (Python, Kotlin) and there are no cross-field rules; a dataclass or record is enough.

### Answer

**The Telescoping Constructor Problem:**

Telescoping constructors are a Java/C++ problem: `new Query("users", null, null, "name", 10, 20, null, null, null, false)` is unreadable and easy to get wrong, and overloads multiply (`Query(table)`, `Query(table, select)`, …). Python's keyword arguments already solve readability:

```python
query = Query(table="users", select=["id", "name"], order_by="name", limit=10, offset=20)
```

So in Python, a builder earns its keep for other reasons: building **incrementally** (adding filters only when a request parameter is present), **validating** cross-field rules once at the end, and producing an **immutable** result.

**Java — the canonical builder (runs with `java HttpRequestDemo.java`, Java 17+):**

```java
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

public class HttpRequestDemo {
    // Immutable product: final fields, no setters, defensive copy of the map.
    record HttpRequest(String method, String url, Map<String, String> headers,
                       Duration timeout, int maxRetries) {

        static Builder builder(String url) { return new Builder(url); }

        static final class Builder {
            private final String url;                        // required: constructor arg
            private String method = "GET";                   // optional: defaults
            private final Map<String, String> headers = new LinkedHashMap<>();
            private Duration timeout = Duration.ofSeconds(5);
            private int maxRetries = 0;

            private Builder(String url) { this.url = url; }

            Builder method(String m) { this.method = m; return this; }
            Builder header(String k, String v) { headers.put(k, v); return this; }
            Builder timeout(Duration t) { this.timeout = t; return this; }
            Builder maxRetries(int n) { this.maxRetries = n; return this; }

            HttpRequest build() {
                if (maxRetries > 0 && method.equals("POST") && !headers.containsKey("Idempotency-Key")) {
                    throw new IllegalStateException("retried POST needs an Idempotency-Key");
                }
                return new HttpRequest(method, url, Map.copyOf(headers), timeout, maxRetries);
            }
        }
    }

    public static void main(String[] args) {
        HttpRequest req = HttpRequest.builder("https://api.example.com/charges")
                .method("POST")
                .header("Idempotency-Key", "k-123")
                .timeout(Duration.ofSeconds(2))
                .maxRetries(3)
                .build();
        System.out.println(req);
    }
}
```

**Python — a SQL query builder (runs as-is):**

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
_OPS = {"=", "!=", "<", "<=", ">", ">=", "IN"}


def _ident(name: str) -> str:
    """Identifiers can't be bound parameters, so whitelist their shape."""
    if not _IDENT.match(name):
        raise ValueError(f"bad identifier: {name!r}")
    return name


@dataclass(frozen=True)
class Query:
    """The product: immutable once built."""
    sql: str
    params: tuple


@dataclass
class QueryBuilder:
    _table: str | None = None
    _columns: list[str] = field(default_factory=lambda: ["*"])
    _joins: list[str] = field(default_factory=list)
    _where: list[tuple[str, str, object]] = field(default_factory=list)
    _order_by: list[str] = field(default_factory=list)
    _limit: int | None = None
    _offset: int | None = None

    def table(self, name: str) -> QueryBuilder:
        self._table = _ident(name)
        return self

    def select(self, *columns: str) -> QueryBuilder:
        self._columns = [_ident(c) for c in columns] or ["*"]
        return self

    def join(self, table: str, left: str, right: str, kind: str = "INNER") -> QueryBuilder:
        if kind not in {"INNER", "LEFT"}:
            raise ValueError(kind)
        self._joins.append(f"{kind} JOIN {_ident(table)} ON {_ident(left)} = {_ident(right)}")
        return self

    def where(self, column: str, op: str, value: object) -> QueryBuilder:
        if op not in _OPS:
            raise ValueError(f"bad operator: {op}")
        self._where.append((_ident(column), op, value))
        return self

    def order_by(self, column: str, descending: bool = False) -> QueryBuilder:
        self._order_by.append(f"{_ident(column)} {'DESC' if descending else 'ASC'}")
        return self

    def limit(self, n: int) -> QueryBuilder:
        self._limit = int(n)
        return self

    def offset(self, n: int) -> QueryBuilder:
        self._offset = int(n)
        return self

    def build(self) -> Query:
        """Validate cross-field rules, then produce the immutable product.
        Pure: calling build() twice gives the same result."""
        if not self._table:
            raise ValueError("table() is required")
        if self._offset is not None and self._limit is None:
            raise ValueError("offset() requires limit()")

        parts = [f"SELECT {', '.join(self._columns)}", f"FROM {self._table}", *self._joins]
        params: list[object] = []
        if self._where:
            clauses = []
            for column, op, value in self._where:
                if op == "IN":
                    values = list(value)
                    clauses.append(f"{column} IN ({', '.join(['%s'] * len(values))})")
                    params.extend(values)
                else:
                    clauses.append(f"{column} {op} %s")
                    params.append(value)
            parts.append("WHERE " + " AND ".join(clauses))
        if self._order_by:
            parts.append("ORDER BY " + ", ".join(self._order_by))
        if self._limit is not None:
            parts.append(f"LIMIT {self._limit}")
        if self._offset is not None:
            parts.append(f"OFFSET {self._offset}")
        return Query(" ".join(parts), tuple(params))


# ── USAGE ───────────────────────────────────────────────────
filters = {"status": "active", "min_age": 18}       # e.g. from query-string params

builder = QueryBuilder().table("users").select("users.id", "users.name")
if "status" in filters:                              # conditional construction:
    builder.where("users.status", "=", filters["status"])   # the real reason to use a builder
if "min_age" in filters:
    builder.where("users.age", ">", filters["min_age"])
query = builder.order_by("users.name").limit(10).build()

# query.sql    == "SELECT users.id, users.name FROM users WHERE users.status = %s
#                  AND users.age > %s ORDER BY users.name ASC LIMIT 10"
# query.params == ("active", 18)
```

Two bugs to avoid in query builders: string-formatting **values** into SQL (always bind parameters) and accepting **identifiers** (table, column, sort direction) unchecked; identifiers can't be bound, so whitelist them. And keep `build()` free of side effects, so calling it twice doesn't duplicate parameters. In production, use SQLAlchemy Core, jOOQ or squirrel (Go) rather than writing your own.

**When Builder Is Over-Engineering:**

```python
# ❌ OVER-ENGINEERED: Builder for 2-3 parameters
class Address:
    """Simple value object with 3 fields."""

    def __init__(self, street, city, zip_code):
        self.street = street
        self.city = city
        self.zip_code = zip_code

class AddressBuilder:
    """Totally unnecessary builder."""

    def __init__(self):
        self._street = None
        self._city = None
        self._zip_code = None

    def street(self, value):
        self._street = value
        return self
    # ...

    def build(self):
        return Address(self._street, self._city, self._zip_code)

# ✅ Simpler: named parameters with defaults
address = Address(street="123 Main St", city="NYC", zip_code="10001")

# ✅ Even simpler: dataclass with named parameters
from dataclasses import dataclass

@dataclass
class Address:
    street: str
    city: str
    zip_code: str
```

**When Builder IS the Right Choice:**

```yaml
Use Builder when:
  1. Construction has many optional parameters and no named arguments (Java)
  2. Some parameters depend on each other
     (e.g., offset requires limit)
  3. The object is IMMUTABLE after construction
  4. Construction has VALIDATION logic
     (e.g., table name is required, offset requires limit)
  5. The object is assembled incrementally or conditionally
  6. The same construction process creates different
     representations (e.g., SQL string vs Query object)

Go idiom instead of builders: functional options
  NewServer(addr, WithTimeout(5*time.Second), WithTLS(cfg))

Skip Builder when:
  1. Simple case: named parameters or dataclass work
  2. The constructed object is mutable — just set properties
  3. You have only 2-3 parameters
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Telescoping problem** | Explains the pain of constructors with many optional parameters |
| **Method chaining** | Implements fluent interface with `return self` |
| **Validation + immutability** | Cross-field checks in `build()`; product is immutable |
| **Safety** | Values bound as parameters; identifiers whitelisted |
| **Over-engineering** | Identifies when named parameters or dataclass replace builder |

---

## 6. Adapter Pattern

**Q:** "Your team is migrating from an old payment gateway to a new one. The old gateway has interface A, the new one has interface B. You can't modify either interface. Design an Adapter to make the new gateway work with the old code. How does this differ from the Facade pattern?"

**What They're Really Testing:** Whether you understand Adapter as an interface compatibility pattern, and can distinguish it from Facade (simplification) and Proxy (control).

!!! abstract "Pattern card"
    **Intent (GoF):** convert the interface of a class into another interface that clients expect, so classes with incompatible interfaces can work together.<br>
    **Structure:** the *Client* depends on a *Target* interface; the *Adapter* implements Target and holds an *Adaptee*, translating calls, parameters, units, errors and return shapes. Prefer an **object adapter** (composition) over a class adapter (multiple inheritance).<br>
    **Use when:** you integrate a third-party SDK or a legacy component you can't change, or you're swapping providers behind a stable interface. At service scale the same idea is DDD's **anti-corruption layer**.<br>
    **Don't use when:** you own both sides (change one of them), or the interfaces differ so much in *semantics* (sync vs async, different consistency) that a thin translation would hide real behaviour differences.

### Answer

**Adapter (runs as-is):**

```python
from abc import ABC, abstractmethod
from decimal import Decimal


# ── TARGET: the interface existing code depends on (can't change) ──
class PaymentGateway(ABC):
    @abstractmethod
    def process_payment(self, amount: Decimal, currency: str, card_token: str) -> dict: ...

    @abstractmethod
    def refund_payment(self, transaction_id: str) -> dict: ...


# ── ADAPTEE: the new provider's SDK (can't change) ──────────
class NewPaymentGateway:
    def create_payment_intent(self, amount_cents: int, currency: str) -> str:
        return "pi_67890"

    def confirm_payment_intent(self, intent_id: str, payment_method_id: str) -> dict:
        return {"id": intent_id, "status": "succeeded"}

    def create_refund(self, payment_intent_id: str, amount_cents: int | None = None) -> dict:
        return {"id": "re_12345", "status": "succeeded"}


# ── ADAPTER: implements the target, delegates to the adaptee ──
class NewPaymentAdapter(PaymentGateway):
    def __init__(self, gateway: NewPaymentGateway):
        self._gateway = gateway          # object adapter: composition, not inheritance

    def process_payment(self, amount: Decimal, currency: str, card_token: str) -> dict:
        amount_cents = int((amount * 100).to_integral_value())   # Decimal, not float math
        intent_id = self._gateway.create_payment_intent(amount_cents, currency.lower())
        result = self._gateway.confirm_payment_intent(intent_id, card_token)
        return {                                       # translate back to the old shape
            "success": result["status"] == "succeeded",
            "transaction_id": result["id"],            # the intent id IS our transaction id
            "amount": amount,
            "currency": currency,
        }

    def refund_payment(self, transaction_id: str) -> dict:
        result = self._gateway.create_refund(transaction_id)
        return {"success": result["status"] == "succeeded", "transaction_id": result["id"]}


# ── CLIENT: unchanged, depends only on the target interface ──
class CheckoutService:
    def __init__(self, payments: PaymentGateway):
        self.payments = payments

    def checkout(self, cart_total: Decimal, card_token: str) -> dict:
        return self.payments.process_payment(cart_total, "USD", card_token)


checkout = CheckoutService(NewPaymentAdapter(NewPaymentGateway()))
checkout.checkout(Decimal("19.99"), "pm_card_visa")
# {'success': True, 'transaction_id': 'pi_67890', 'amount': Decimal('19.99'), 'currency': 'USD'}
```

What the adapter really translates, and where bugs hide:

- **Units and types:** dollars as `Decimal` ↔ integer cents. `int(19.99 * 100)` is `1998` because of float rounding, which is why money never goes through floats.
- **Identifiers:** return the provider's ID as the transaction ID (or store a mapping table). Rewriting ID prefixes (`TX_` → `pi_`) only works by coincidence.
- **Errors:** map the adaptee's exceptions to the ones the client already handles (declined vs retriable vs unknown outcome). Leaking `NewSdkError` to callers breaks the abstraction.
- **Behavioural gaps:** a one-call API adapted to a two-step flow (create + confirm intent) can fail *between* the steps; the adapter needs idempotency keys and a reconciliation path.
- **Compliance:** if the old interface passes raw card numbers, the adapter has to tokenize them, which puts it (and everything upstream) in PCI DSS scope. Here the legacy interface already takes a token.

**Adapter vs Facade vs Proxy:**

```yaml
Adapter:
  - CONVERTS interface A to interface B
  - Purpose: compatibility between existing code
  - Example: NewPaymentGateway → OldPaymentGateway interface

Facade:
  - SIMPLIFIES a complex subsystem
  - Purpose: reduce complexity for clients
  - Example: OrderFacade(frontend, inventory, payment, shipping)

Proxy:
  - CONTROLS access to an object
  - Purpose: lazy loading, access control, logging
  - Example: CachingProxy(ExpensiveService)

KEY DIFFERENCE:
  Adapter changes the INTERFACE (A → B)
  Facade changes the COMPLEXITY (complex → simple)
  Proxy changes the ACCESS (direct → controlled)

  Adapter: "Make this API look like that API"
  Facade:  "Give me a simple way to use this complex system"
  Proxy:   "I'm standing in front of the real object, with the same interface"
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Interface translation** | Adapter converts old interface calls to new ones without changing client code |
| **Adapter vs Facade** | Clearly distinguishes between interface conversion (Adapter) and simplification (Facade) |
| **Object vs class adapter** | Uses object adapter (composition) over class adapter (inheritance) for flexibility |
| **Idiomatic translation** | Translates units, IDs and errors correctly (cents vs dollars, provider IDs, exception mapping) |

---

## 7. Decorator Pattern

**Q:** "Design a middleware system for an HTTP server where each request passes through multiple processing stages: authentication, rate limiting, logging, caching, and compression. The order and combination of stages varies per route. Use the Decorator pattern. How is this different from the Chain of Responsibility pattern?"

**What They're Really Testing:** Whether you understand Decorator as a way to add responsibilities to objects dynamically, and can distinguish it from Chain of Responsibility (where handlers decide whether to pass the request).

!!! abstract "Pattern card"
    **Intent (GoF):** attach additional responsibilities to an object dynamically; a flexible alternative to subclassing for extending behaviour.<br>
    **Structure:** *Component* interface; *ConcreteComponent* does the real work; *Decorator* implements the same interface, holds a Component, and adds behaviour before and/or after delegating. Decorators nest, so behaviours combine without a subclass per combination (`LoggedCachedAuthedHandler`).<br>
    **Use when:** cross-cutting behaviour (logging, metrics, caching, retries, auth) must be combined per instance or per route.<br>
    **Don't use when:** order-dependence would surprise people and isn't documented, or the "decorator" changes the contract (different return type, swallowed errors); that breaks substitutability. Python's `@decorator` syntax wraps *functions* and is a related but separate language feature.

### Answer

**Decorator pattern for HTTP middleware (runs as-is with PyJWT and a Redis-like client):**

```python
import gzip
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import jwt  # PyJWT


@dataclass
class Request:
    method: str
    path: str
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    client_ip: str = ""
    user: Optional[dict] = None


@dataclass
class Response:
    status_code: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


class HttpHandler(ABC):                       # Component
    @abstractmethod
    async def handle(self, request: Request) -> Response: ...


class AppHandler(HttpHandler):                # ConcreteComponent
    def __init__(self, app):
        self.app = app

    async def handle(self, request: Request) -> Response:
        return await self.app.dispatch(request)


class Middleware(HttpHandler):                # Decorator: same interface, wraps one
    def __init__(self, wrapped: HttpHandler):
        self._wrapped = wrapped


def _json_error(status: int, message: str, **headers) -> Response:
    return Response(status, {"Content-Type": "application/json", **headers},
                    f'{{"error": "{message}"}}'.encode())


class LoggingMiddleware(Middleware):
    def __init__(self, wrapped, logger):
        super().__init__(wrapped)
        self.logger = logger

    async def handle(self, request):
        start = time.perf_counter()
        response = await self._wrapped.handle(request)           # always delegates
        ms = (time.perf_counter() - start) * 1000
        self.logger.info("%s %s -> %s (%.0f ms)", request.method, request.path,
                         response.status_code, ms)
        return response


class RateLimitMiddleware(Middleware):
    """Fixed window per client IP. Runs BEFORE auth so credential-stuffing
    attempts are throttled too."""

    def __init__(self, wrapped, redis, limit: int, window_s: int = 60):
        super().__init__(wrapped)
        self.redis, self.limit, self.window_s = redis, limit, window_s

    async def handle(self, request):
        key = f"ratelimit:{request.client_ip}:{int(time.time()) // self.window_s}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, self.window_s)
        if count > self.limit:
            return _json_error(429, "rate limit exceeded", **{"Retry-After": str(self.window_s)})
        response = await self._wrapped.handle(request)
        response.headers["RateLimit-Remaining"] = str(max(0, self.limit - count))
        return response


class AuthMiddleware(Middleware):
    def __init__(self, wrapped, jwt_secret: str):
        super().__init__(wrapped)
        self.jwt_secret = jwt_secret

    async def handle(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return _json_error(401, "missing token")
        try:
            request.user = jwt.decode(header.removeprefix("Bearer "), self.jwt_secret,
                                      algorithms=["HS256"])  # pin the algorithm
        except jwt.ExpiredSignatureError:
            return _json_error(401, "token expired")
        except jwt.InvalidTokenError:
            return _json_error(401, "invalid token")
        return await self._wrapped.handle(request)


class CacheMiddleware(Middleware):
    def __init__(self, wrapped, cache, ttl_s: int = 300):
        super().__init__(wrapped)
        self.cache, self.ttl_s = cache, ttl_s

    async def handle(self, request):
        if request.method != "GET":
            return await self._wrapped.handle(request)
        # The key MUST include whatever varies the response. Behind auth that
        # includes the user, or user A's data is served to user B.
        user_id = (request.user or {}).get("sub", "anon")
        key = f"http:{user_id}:{request.path}"
        cached = await self.cache.get(key)
        if cached is not None:
            return Response(200, {"Content-Type": "application/json", "X-Cache": "HIT"}, cached)
        response = await self._wrapped.handle(request)
        if response.status_code == 200:
            await self.cache.setex(key, self.ttl_s, response.body)   # uncompressed body
        response.headers["X-Cache"] = "MISS"
        return response


class CompressionMiddleware(Middleware):
    async def handle(self, request):
        response = await self._wrapped.handle(request)
        if "gzip" in request.headers.get("Accept-Encoding", "") and len(response.body) > 1024:
            response.body = gzip.compress(response.body)
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Vary"] = "Accept-Encoding"
            response.headers["Content-Length"] = str(len(response.body))
        return response


def build_stack(app, cfg: dict, *, redis, cache, jwt_secret, logger) -> HttpHandler:
    """Wrap from the inside out. The LAST wrapper applied runs FIRST.
    Resulting request order: logging → compression → rate limit → auth → cache → app."""
    handler: HttpHandler = AppHandler(app)
    if cfg.get("cache"):
        handler = CacheMiddleware(handler, cache)
    if cfg.get("auth"):
        handler = AuthMiddleware(handler, jwt_secret)
    if cfg.get("rate_limit"):
        handler = RateLimitMiddleware(handler, redis, limit=cfg["rate_limit"])
    if cfg.get("compression"):
        handler = CompressionMiddleware(handler)     # outside the cache: cache stores raw bodies
    return LoggingMiddleware(handler, logger)


ROUTES = {
    "public":    {"rate_limit": 20,  "cache": True, "compression": True},
    "protected": {"rate_limit": 100, "auth": True, "cache": True, "compression": True},
    "admin":     {"rate_limit": 500, "auth": True, "compression": True},   # never cached
}
```

**Ordering is the design.** Each choice above has a reason:

| Order decision | Why |
|----------------|-----|
| Logging outermost | Sees every request, including ones rejected by rate limit or auth |
| Rate limit before auth | Throttles brute-force and credential-stuffing attempts before spending CPU on token checks |
| Cache *inside* auth | Only authenticated requests reach the cache, and the key can include the user |
| Compression *outside* cache | The cache stores raw bodies; otherwise a cache hit returns gzip bytes without a `Content-Encoding` header, or serves gzip to clients that didn't ask for it |

The most expensive bug in middleware like this is a cache key of just `method:path` behind auth: `/me` cached for Alice is served to Bob. Cache keys must include everything the response varies on (user, tenant, `Accept-Encoding`, query string), or mark personalised responses `Cache-Control: private` and skip shared caching.

**Decorator vs Chain of Responsibility:**

| | Decorator | Chain of Responsibility |
|---|---|---|
| Intent | *Add* behaviour around a call | *Find* the handler that deals with a request |
| Typical flow | Every layer runs and delegates to the next; can act before and after | Each handler either handles the request (and stops) or passes it on |
| Short-circuiting | Allowed (auth returns 401) but not the point | The point: the first matching handler wins |
| Examples | Logging, metrics, caching, retry wrappers, Java I/O streams | Event bubbling in UIs, approval chains, exception handlers, routing fallbacks |

HTTP middleware stacks (Express, ASP.NET Core, Go `http.Handler` wrappers, Starlette) are a hybrid: structurally decorators (same interface, wrapping), and any layer may short-circuit like a chain. Saying that explicitly is a better answer than forcing a strict distinction.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Before/after** | Adds behavior both before and after calling wrapped handler |
| **Middleware stack** | Builds ordered middleware stacks per route with different configurations |
| **vs Chain of Responsibility** | Distinguishes intent (add behaviour vs find a handler); recognises middleware as a hybrid |
| **Ordering & cache safety** | Justifies the order; cache keys include user and encoding |
| **Production awareness** | Adds concrete middleware: JWT auth, rate limiting, caching, compression |

---

## 8. Facade Pattern

**Q:** "You're onboarding a new team member who needs to place orders in your complex e-commerce system. The order process touches 7 services with 15+ steps. Design a Facade that simplifies this. How do you test a Facade? How is Facade different from just a 'god class'?"

**What They're Really Testing:** Whether you understand Facade as a simplification layer, and can distinguish it from a god class that centralizes too much logic.

!!! abstract "Pattern card"
    **Intent (GoF):** provide a unified, higher-level interface to a set of interfaces in a subsystem, making the subsystem easier to use.<br>
    **Structure:** a *Facade* that knows which subsystem classes to call and in what order; *subsystem classes* do the real work and don't know the facade exists. Clients may still use the subsystem directly when they need to.<br>
    **Use when:** many clients repeat the same multi-step sequence, or you want a stable entry point while the subsystem changes behind it. In layered/DDD code, an *application service* is a facade; at system scale, a BFF or gateway aggregation endpoint is one.<br>
    **Don't use when:** it starts accumulating business rules (that's a god class), or it hides choices that clients legitimately need to make.

### Answer

**Complex Subsystem Without Facade:**

```python
# ── COMPLEX SUBSYSTEM (14 steps to place an order) ─────────
# Without Facade, the client must:

class ClientCode:
    async def place_order_shopping_cart(self, user_id, items, payment_info, shipping_address):
        # Step 1: Validate items
        for item in items:
            if not await inventory_service.is_available(item['id'], item['qty']):
                raise Exception(f"Item {item['id']} not available")

        # Step 2: Calculate pricing
        subtotal = 0
        for item in items:
            price = await pricing_service.get_price(item['id'])
            subtotal += price * item['qty']

        # Step 3: Apply promotions
        promo = await promotion_service.get_applicable_promotions(user_id, items)
        discount = await promotion_service.calculate_discount(promo, subtotal)

        # Step 4: Calculate tax
        tax = await tax_service.calculate_tax(shipping_address, subtotal - discount)

        # Step 5: Calculate shipping
        shipping = await shipping_service.calculate_cost(items, shipping_address)

        total = subtotal - discount + tax + shipping

        # Step 6: Validate payment
        auth_result = await payment_service.authorize(user_id, total, payment_info)

        # Step 7: Reserve inventory
        for item in items:
            await inventory_service.reserve(item['id'], item['qty'])

        # Step 8: Create order
        order = await order_service.create(user_id, items, total, shipping_address)

        # Step 9: Capture payment
        await payment_service.capture(auth_result['id'], total)

        # Step 10: Schedule shipping
        await shipping_service.schedule(order['id'], items, shipping_address)

        # Step 11: Send notification
        await notification_service.send_order_confirmation(user_id, order['id'])

        # Step 12: Update analytics
        await analytics_service.track_order(user_id, order['id'], total)

        # Step 13: Update loyalty points
        await loyalty_service.add_points(user_id, total)

        # Step 14: Invalidate cache
        await cache_service.invalidate(f"user:{user_id}:cart")

        return order

# PROBLEM:
# - Client code knows about 7 different services
# - Client code manages 14-step order flow
# - Any change to the process breaks all clients
# - Hard to test (mock 7 services)
```

**Facade Pattern Solution (runs as-is with stub subsystems):**

```python
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PriceSummary:
    subtotal: int          # cents
    discount: int
    tax: int
    shipping: int

    @property
    def total(self) -> int:
        return self.subtotal - self.discount + self.tax + self.shipping


@dataclass(frozen=True)
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    total: Optional[int] = None
    error: Optional[str] = None


class OutOfStock(Exception): ...


class OrderFacade:
    """One entry point for 'place an order'. It sequences subsystem calls and
    owns the compensation order; the business rules stay in the subsystems."""

    def __init__(self, inventory, pricing, payment, orders, events):
        self.inventory, self.pricing, self.payment = inventory, pricing, payment
        self.orders, self.events = orders, events

    async def place_order(self, user_id: str, items: list[dict],
                          payment_token: str, address: dict) -> OrderResult:
        undo = []                                   # compensations, run in reverse
        try:
            price = await self._price(user_id, items, address)

            reservation = await self.inventory.reserve(items)        # raises OutOfStock
            undo.append(lambda: self.inventory.release(reservation))

            auth = await self.payment.authorize(user_id, price.total, payment_token)
            undo.append(lambda: self.payment.void(auth["id"]))

            order = await self.orders.create(user_id, items, price, address,
                                             reservation, auth["id"])
            undo.append(lambda: self.orders.cancel(order["id"]))

            await self.payment.capture(auth["id"], price.total)      # pivot: no undo after this
            undo.clear()

            # Side effects that may lag (email, loyalty, analytics) go out as an
            # event, ideally via an outbox, not as fire-and-forget tasks that
            # vanish if the process dies.
            await self.events.publish("order.placed", {"order_id": order["id"],
                                                       "user_id": user_id,
                                                       "total": price.total})
            return OrderResult(True, order["id"], price.total)

        except Exception as e:
            for compensate in reversed(undo):
                try:
                    await compensate()
                except Exception:
                    logging.exception("compensation failed; needs reconciliation")
            return OrderResult(False, error=str(e))

    async def _price(self, user_id, items, address) -> PriceSummary:
        prices = await asyncio.gather(*(self.pricing.get_price(i["id"]) for i in items))
        subtotal = sum(p * i["qty"] for p, i in zip(prices, items))
        discount = await self.pricing.discount_for(user_id, items, subtotal)
        tax = await self.pricing.tax_for(address, subtotal - discount)
        shipping = await self.pricing.shipping_for(items, address)
        return PriceSummary(subtotal, discount, tax, shipping)


# ── CLIENT CODE ────────────────────────────────────────────
async def handle_checkout(request, facade: OrderFacade):   # facade built once, injected
    result = await facade.place_order(request.user_id, request.cart_items,
                                      request.payment_token, request.shipping_address)
    return result
```

Notes for the interview:

- The facade owns **sequencing and compensation** (reserve → authorize → create → capture, undone in reverse on failure), which the 14-step client code above got wrong or skipped. Pricing rules, stock rules and fraud rules stay in their subsystems.
- **Capture is the pivot.** After it succeeds nothing is undone; before it, everything can be. A capture *timeout* is an unknown outcome: void-and-cancel could be wrong, so production code checks the payment status before compensating.
- When the subsystems are separate services, this facade **is** a saga orchestrator; durability across crashes then matters (see [Saga Pattern](INTERVIEW_QUESTIONS.md#9-saga-pattern-choreography-vs-orchestration)).
- Testing: unit-test the facade with stubbed subsystems: the success path, a failure at each step, and the compensation order. The subsystems keep their own tests.
- Eleven constructor parameters is a smell: group them (a `PricingService` facade in front of price, promotion, tax and shipping, as done above) or split the facade by use case.

**Facade vs God Class:**

```yaml
Facade (good):
  - SIMPLIFIES a complex subsystem
  - Delegates work to subsystem (doesn't do the work itself)
  - Doesn't contain business logic — orchestrates calls
  - Easy to test (mock subsystem dependencies)
  - Single responsibility: "simplify the interface"

God Class (bad):
  - CONCENTRATES logic that should be distributed
  - Does the work itself instead of delegating
  - Contains business rules, validations, data access
  - Hard to test (tight coupling to everything)
  - Multiple responsibilities

KEY DISTINCTION:
  Facade: delegates to subsystem classes
  God class: implements everything itself

  Facade: OrderFacade calls inventory.validate, pricing.calculate, ...
  God class: OrderProcessor.validate_inventory, calculate_pricing, ...
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Simplification** | Client calls one method instead of 14 steps across 7 services |
| **Subsystem delegation** | Facade delegates to services, doesn't implement business logic itself |
| **Compensation** | Facade handles failure compensation — client doesn't need to know |
| **vs God class** | Explains that Facade orchestrates, God class implements |

---

## 9. Command Pattern

**Q:** "Design an undoable text editor operations system (insert, delete, replace) using the Command pattern. Then extend it to support macro recording, queuing, and logging. How would you handle commands that can't be undone?"

**What They're Really Testing:** Whether you understand Command as a way to parameterize, queue, log, and undo operations, and can design for edge cases like irreversible commands.

!!! abstract "Pattern card"
    **Intent (GoF):** encapsulate a request as an object, so you can parameterize clients with requests, queue or log them, and support undo.<br>
    **Structure:** *Command* interface (`execute`, optionally `undo`); *ConcreteCommands* hold the *Receiver* and the arguments, plus whatever state undo needs; the *Invoker* (history, queue, button) triggers commands without knowing what they do; the *Client* creates them.<br>
    **Use when:** you need undo/redo, macros, queuing, scheduling, retries or an audit log of operations. Job queues, CQRS commands and event-sourced command handlers are the same idea at service scale.<br>
    **Don't use when:** a callback or lambda would do (no undo, no queuing, no logging); a class per operation is then ceremony.

### Answer

**Command Pattern for an Undoable Text Editor (runs as-is):**

```python
from abc import ABC, abstractmethod
from collections import deque


class Command(ABC):
    reversible = True
    barrier = False      # irreversible AND later undos would be unsafe (send, publish, pay)

    @abstractmethod
    def execute(self) -> None: ...

    def undo(self) -> None:
        raise NotImplementedError(f"{type(self).__name__} cannot be undone")


class TextEditor:                                  # Receiver
    def __init__(self):
        self.content = ""

    def insert(self, pos: int, text: str) -> None:
        self.content = self.content[:pos] + text + self.content[pos:]

    def delete(self, pos: int, length: int) -> str:
        removed = self.content[pos:pos + length]
        self.content = self.content[:pos] + self.content[pos + length:]
        return removed


class InsertCommand(Command):
    def __init__(self, editor: TextEditor, pos: int, text: str):
        self.editor, self.pos, self.text = editor, pos, text

    def execute(self):
        self.editor.insert(self.pos, self.text)

    def undo(self):
        self.editor.delete(self.pos, len(self.text))


class DeleteCommand(Command):
    def __init__(self, editor: TextEditor, pos: int, length: int):
        self.editor, self.pos, self.length = editor, pos, length
        self._removed = ""                         # state captured for undo

    def execute(self):
        self._removed = self.editor.delete(self.pos, self.length)

    def undo(self):
        self.editor.insert(self.pos, self._removed)


class SaveCommand(Command):
    reversible = False   # the file on disk can't be "unwritten", but the buffer's
                         # undo history is still valid, so it's not a barrier

    def __init__(self, editor: TextEditor, path: str):
        self.editor, self.path = editor, path

    def execute(self):
        with open(self.path, "w") as f:
            f.write(self.editor.content)


class MacroCommand(Command):                       # Composite of commands
    def __init__(self, commands: list[Command]):
        self.commands = list(commands)
        self.reversible = all(c.reversible for c in self.commands)
        self.barrier = any(c.barrier for c in self.commands)

    def execute(self):
        for c in self.commands:
            c.execute()

    def undo(self):
        for c in reversed(self.commands):          # undo in reverse order
            c.undo()


class CommandHistory:                              # Invoker
    def __init__(self, max_history: int = 1000):
        self._undo: deque[Command] = deque(maxlen=max_history)   # O(1) trimming
        self._redo: list[Command] = []
        self._recording: list[Command] | None = None

    def execute(self, cmd: Command) -> None:
        cmd.execute()
        if self._recording is not None:
            self._recording.append(cmd)
        if cmd.reversible:
            self._undo.append(cmd)
            self._redo.clear()                     # a new edit invalidates redo
        elif cmd.barrier:
            self._undo.clear()                     # e.g. after "send", undoing earlier
            self._redo.clear()                     # edits would diverge from what was sent

    def undo(self) -> bool:
        if not self._undo:
            return False
        cmd = self._undo.pop()
        cmd.undo()
        self._redo.append(cmd)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        cmd = self._redo.pop()
        cmd.execute()
        self._undo.append(cmd)
        return True

    def start_macro(self) -> None:
        self._recording = []

    def stop_macro(self) -> MacroCommand:
        macro, self._recording = MacroCommand(self._recording or []), None
        return macro


# ── USAGE ──────────────────────────────────────────────────
if __name__ == "__main__":
    editor, history = TextEditor(), CommandHistory()

    history.execute(InsertCommand(editor, 0, "Hello, World!"))
    history.execute(DeleteCommand(editor, 5, 7))
    print(editor.content)            # Hello!
    history.undo()
    print(editor.content)            # Hello, World!
    history.redo()
    print(editor.content)            # Hello!

    history.start_macro()
    history.execute(InsertCommand(editor, 0, "> "))
    history.execute(InsertCommand(editor, len(editor.content), " <"))
    wrap = history.stop_macro()
    print(editor.content)            # > Hello! <

    history.undo(); history.undo()   # undo the two recorded steps individually
    print(editor.content)            # Hello!
    history.execute(wrap)            # replay the macro as ONE command
    print(editor.content)            # > Hello! <
    history.undo()                   # ...and undo it as one step
    print(editor.content)            # Hello!
```

Design points:

- **Undo needs captured state.** `DeleteCommand` stores the removed text at execute time; it can't be recomputed later. The alternative is the **Memento** pattern: snapshot editor state before each command. That's simpler but costs memory; real editors combine both.
- **Irreversible commands.** Some commands simply aren't undoable (save to disk), so they stay out of the undo stack. Others make earlier undos unsafe (send, publish, pay) and act as a **barrier** that clears history. Undoing something already sent needs a *new* compensating command (send a correction), which is exactly the saga idea.
- **Macros** are a Composite of commands: recorded while executing, replayed and undone as one unit, in reverse order.
- **Bounded history** via `deque(maxlen=…)`; `list.pop(0)` is O(n) per trim.
- **Collaborative editing** breaks simple position-based undo (someone else's edit shifts positions); that's where operational transforms or CRDTs come in.

**Command Queue for Async Processing:**

```python
# ── COMMAND QUEUE (for async/remote execution) ────────────
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

@dataclass
class QueuedCommand:
    """Wraps a command with metadata for queuing and retrying."""
    command: Command
    command_type: str
    created_at: datetime
    retry_count: int = 0
    max_retries: int = 3
    status: str = "pending"  # pending, running, completed, failed

class CommandQueue:
    """
    Processes commands asynchronously with retry logic.
    Useful for commands that involve I/O or remote calls.
    """

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._dlq: list[QueuedCommand] = []
        self._workers = []
        self._running = False

    async def enqueue(self, command: Command):
        """Add a command to the queue."""
        queued = QueuedCommand(
            command=command,
            command_type=type(command).__name__,
            created_at=datetime.now(),
        )
        await self._queue.put(queued)

    async def start(self, num_workers: int = 4):
        """Start worker pool to process commands."""
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(f"worker-{i}"))
            for i in range(num_workers)
        ]

    async def stop(self):
        """Gracefully stop workers."""
        self._running = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

    async def _worker(self, name: str):
        """Worker process: dequeue and execute commands."""
        while self._running:
            try:
                queued = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            queued.status = "running"
            try:
                # Commands that do blocking I/O shouldn't run on the event loop:
                await asyncio.to_thread(queued.command.execute)
                queued.status = "completed"
                logging.info(f"{name}: {queued.command_type} completed")

            except Exception as e:
                queued.retry_count += 1
                if queued.retry_count < queued.max_retries:
                    # Retrying is only safe for IDEMPOTENT commands.
                    # Sleeping here blocks this worker; production queues
                    # schedule a delayed redelivery instead (SQS visibility
                    # timeout, a retry topic with a delay).
                    await asyncio.sleep(2 ** queued.retry_count)
                    await self._queue.put(queued)
                else:
                    # Move to dead letter queue
                    self._dlq.append(queued)
                    queued.status = "failed"
                    logging.error(
                        f"{name}: {queued.command_type} failed: {e}"
                    )
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Undo/redo** | Implements undo by storing state needed to reverse (deleted text for delete) |
| **Irreversible commands** | Handles commands like Save that can't be undone |
| **Macro recording** | Records commands and replays as a single composed command |
| **Command queue** | Designs async processing with retry, backoff, and dead letter queue |

---

## 10. State Pattern

**Q:** "Design a vending machine state machine using the State pattern. The vending machine has states: Idle, Selecting Item, Processing Payment, Dispensing, Out of Stock, Maintenance. Walk through the transitions. How does State differ from Strategy?"

**What They're Really Testing:** Whether you understand State as a way to make state-dependent behavior explicit and extensible, and can distinguish it from Strategy (different algorithms, same interface vs different behaviors, same interface).

!!! abstract "Pattern card"
    **Intent (GoF):** allow an object to alter its behaviour when its internal state changes; the object will appear to change its class.<br>
    **Structure:** a *Context* holds a reference to the current *State* object and delegates every state-dependent call to it; each *ConcreteState* implements the behaviour for that state and decides the transition. Replaces scattered `if state == …` checks in every method.<br>
    **Use when:** behaviour differs substantially per state, and states have their own entry actions and rules (order lifecycle, connection handling, protocol parsers, vending machines).<br>
    **Don't use when:** behaviour is mostly the same and only the allowed transitions differ. An **enum plus a transition table** is shorter, easier to review, and easy to persist (which you need when the state lives in a database).

### Answer

**State Pattern for a vending machine (runs as-is):**

The question's "Selecting" and "Processing Payment" are merged into `HasMoneyState` for a coin machine, where payment is just the balance check. A card machine would add a real `AwaitingPaymentState`, because authorization is asynchronous and can time out.

```python
from __future__ import annotations


class VendingState:
    """Base state: every action is rejected unless a state overrides it.
    This keeps each concrete state down to the transitions it allows."""

    def __init__(self, machine: VendingMachine):
        self.m = machine

    def insert_money(self, cents: int):  self._reject("insert money")
    def select_item(self, item_id: str): self._reject("select an item")
    def cancel(self):                    self._reject("cancel")
    def refill(self, stock: dict):       self._reject("refill")
    def enter_maintenance(self):         self._reject("enter maintenance")
    def exit_maintenance(self):          self._reject("exit maintenance")

    def _reject(self, action: str):
        print(f"[{type(self).__name__}] can't {action} now")


class IdleState(VendingState):
    def insert_money(self, cents):
        self.m.balance += cents
        self.m.transition(self.m.has_money)

    def enter_maintenance(self):
        self.m.transition(self.m.maintenance)


class HasMoneyState(VendingState):
    def insert_money(self, cents):
        self.m.balance += cents

    def select_item(self, item_id):
        item = self.m.inventory.get(item_id)
        if not item or item["qty"] == 0:
            print(f"{item_id} unavailable")
        elif item["price"] > self.m.balance:
            print(f"insert {item['price'] - self.m.balance} more cents")
        else:
            self.m.selected = item_id
            self.m.transition(self.m.dispensing)
            self.m.dispensing.dispense()          # automatic transition, no user action

    def cancel(self):
        self.m.refund(self.m.balance)
        self.m.transition(self.m.idle)


class DispensingState(VendingState):
    def dispense(self):
        item = self.m.inventory[self.m.selected]
        item["qty"] -= 1
        change = self.m.balance - item["price"]
        print(f"dispensing {self.m.selected}")
        self.m.balance, self.m.selected = 0, None
        if change:
            self.m.refund(change)
        self.m.transition(self.m.sold_out if self.m.is_empty() else self.m.idle)


class SoldOutState(VendingState):
    def insert_money(self, cents):
        self.m.refund(cents)                      # give the coins straight back

    def enter_maintenance(self):
        self.m.transition(self.m.maintenance)


class MaintenanceState(VendingState):
    def refill(self, stock):
        for item_id, item in stock.items():
            self.m.inventory.setdefault(item_id, {"price": item["price"], "qty": 0})
            self.m.inventory[item_id]["qty"] += item["qty"]

    def exit_maintenance(self):
        self.m.transition(self.m.sold_out if self.m.is_empty() else self.m.idle)


class VendingMachine:
    """Context: holds data and the current state, delegates every action."""

    def __init__(self):
        self.balance = 0                          # cents, never floats
        self.selected: str | None = None
        self.inventory: dict[str, dict] = {}
        self.idle, self.has_money = IdleState(self), HasMoneyState(self)
        self.dispensing, self.sold_out = DispensingState(self), SoldOutState(self)
        self.maintenance = MaintenanceState(self)
        self.state: VendingState = self.sold_out  # empty machine starts sold out

    def transition(self, new: VendingState):
        print(f"  {type(self.state).__name__} -> {type(new).__name__}")
        self.state = new

    def refund(self, cents: int):
        print(f"returning {cents} cents")

    def is_empty(self) -> bool:
        return all(i["qty"] == 0 for i in self.inventory.values())

    # Public API: pure delegation
    def insert_money(self, cents):  self.state.insert_money(cents)
    def select_item(self, item_id): self.state.select_item(item_id)
    def cancel(self):               self.state.cancel()
    def refill(self, stock):        self.state.refill(stock)
    def enter_maintenance(self):    self.state.enter_maintenance()
    def exit_maintenance(self):     self.state.exit_maintenance()


# ── USAGE ──────────────────────────────────────────────────
vm = VendingMachine()
vm.enter_maintenance()
vm.refill({"cola": {"price": 150, "qty": 1}})
vm.exit_maintenance()                 #   MaintenanceState -> IdleState
vm.select_item("cola")                # [IdleState] can't select an item now
vm.insert_money(100)                  #   IdleState -> HasMoneyState
vm.select_item("cola")                # insert 50 more cents
vm.insert_money(100)
vm.select_item("cola")                # dispensing cola, returning 50 cents,
                                      #   DispensingState -> SoldOutState
vm.insert_money(25)                   # returning 25 cents
```

Things worth pointing out:

- The base class **rejects everything by default**, so each state lists only the transitions it allows, and invalid actions get one consistent error path.
- **Automatic transitions** (dispensing finishes, then Idle or SoldOut) happen inside the state, not because the caller remembered to call `dispense()`. A state machine that waits for a call nobody makes is stuck forever.
- **Money is integer cents.** Floats give change like `0.30000000000000004`.
- **Maintenance is a state with guarded entry**, not a back door that overwrites `current_state` mid-transaction and loses the customer's balance.

**The lighter alternative: enum + transition table**

```python
from enum import Enum, auto

class S(Enum):
    IDLE = auto(); HAS_MONEY = auto(); DISPENSING = auto(); SOLD_OUT = auto(); MAINTENANCE = auto()

TRANSITIONS = {                                  # (state, event) -> next state
    (S.IDLE, "coin"): S.HAS_MONEY,
    (S.HAS_MONEY, "coin"): S.HAS_MONEY,
    (S.HAS_MONEY, "select_ok"): S.DISPENSING,
    (S.HAS_MONEY, "cancel"): S.IDLE,
    (S.DISPENSING, "done"): S.IDLE,
    (S.DISPENSING, "done_empty"): S.SOLD_OUT,
    (S.IDLE, "service"): S.MAINTENANCE,
    (S.SOLD_OUT, "service"): S.MAINTENANCE,
    (S.MAINTENANCE, "close"): S.IDLE,
}

def next_state(state: S, event: str) -> S:
    try:
        return TRANSITIONS[(state, event)]
    except KeyError:
        raise ValueError(f"illegal transition: {state.name} on {event!r}") from None
```

Choose the table when the states mostly gate *which events are legal* (order status, ticket workflow) and the state is stored in a database row. Choose State classes when each state has substantial behaviour of its own. Mature options: Spring Statemachine, XState (TypeScript), `python-statemachine`, or a durable workflow engine for long-running states.

**State vs Strategy:**

```yaml
Strategy Pattern:
  - Different ALGORITHMS for the same task
  - Client selects the strategy
  - Strategies don't know about each other
  - Example: PaymentGatewayStrategy (Stripe vs PayPal)

State Pattern:
  - Different BEHAVIORS based on internal state
  - State transitions are AUTOMATIC (triggered by events)
  - States usually know their successor states (or the context
    owns a transition table)
  - Example: VendingMachineState (Idle → Selecting → Payment → Dispensing)

When they look similar:
  Both use composition and delegation
  Both have a context that delegates to a state/strategy object

KEY DIFFERENCE:
  Strategy: caller chooses "which algorithm"
  State:     events determine "which state"

  Strategy: PaymentProcessor uses StripeStrategy (caller chooses)
  State:     VendingMachine transitions to ProcessingPaymentState
             (event-driven, automatic)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **State transitions** | Defines clear transitions: Idle → Selecting → Payment → Dispensing |
| **Invalid transition handling** | Handles out-of-order calls (e.g., dispense when idle) gracefully |
| **State vs Strategy** | Explains difference: Strategy = caller chooses algorithm, State = events drive transitions |
| **Maintenance state** | Includes a maintenance state that can only be entered/exited by authorized action |
| **Alternatives** | Knows when an enum + transition table beats a class per state |

---

## 11. Template Method Pattern

**Q:** "Your data pipeline processes files from different sources (S3, FTP, Local) through the same stages: download → validate → transform → load. 80% of the code is the same, 20% varies per source. Design this using Template Method. What are the hook methods? When would you prefer Strategy over Template Method?"

**What They're Really Testing:** Whether you understand Template Method as a way to reuse common algorithm structure while allowing subclasses to override specific steps, and can identify when Strategy or composition is a better fit.

!!! abstract "Pattern card"
    **Intent (GoF):** define the skeleton of an algorithm in a base-class method, deferring some steps to subclasses, so subclasses can redefine certain steps without changing the algorithm's structure.<br>
    **Structure:** an *AbstractClass* with a (non-overridable) `template_method()` that calls *primitive operations* (abstract, must override) and *hooks* (default no-op, may override); *ConcreteClasses* fill in the steps. "Don't call us, we'll call you."<br>
    **Use when:** several variants share a fixed sequence and differ in a few steps, and the variation is along **one** axis (frameworks: `unittest.TestCase.setUp`, Spring's `JdbcTemplate`, servlet `doGet`).<br>
    **Don't use when:** variation is along several independent axes (source × format × sink): inheritance multiplies subclasses (`S3CsvPostgresPipeline`, `FtpXmlPostgresPipeline` …). Compose strategies instead.

### Answer

**Template Method for Data Pipeline:**

```python
# ── ABSTRACT CLASS with template method ────────────────────
from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging

@dataclass
class PipelineContext:
    """Context passed through pipeline stages."""
    source_path: str
    destination: str
    raw_data: bytes = None
    validated_data: dict = None
    transformed_data: dict = None
    load_result: dict = None
    errors: list[str] = None

class DataPipeline(ABC):
    """
    Template Method: defines skeleton of data pipeline.
    Subclasses implement source-specific steps.
    """

    # ── TEMPLATE METHOD ───────────────────────────────────
    def run(self, source_path: str, destination: str) -> dict:
        """
        Template method: defines the algorithm skeleton. Not meant to be
        overridden (Java would mark it `final`).
          pre_process (hook) → connect → download → validate
          → transform (default: pass-through) → load → post_process (hook)
          on error: handle_error (hook); always: cleanup (hook)
        """
        context = PipelineContext(
            source_path=source_path,
            destination=destination,
            errors=[],
        )

        try:
            # Step 1: Connect to source
            self._pre_process(context)
            self._connect()

            # Step 2: Download
            context.raw_data = self._download(source_path)

            # Step 3: Validate
            context.validated_data = self._validate(context.raw_data)

            # Step 4: Transform
            context.transformed_data = self._transform(
                context.validated_data
            )

            # Step 5: Load
            context.load_result = self._load(
                context.transformed_data,
                destination,
            )

            # Step 6: Post-process (hook)
            self._post_process(context)

            return {
                'success': True,
                'destination': destination,
                'records_loaded': context.load_result,
            }

        except Exception as e:
            self._handle_error(context, e)
            return {
                'success': False,
                'error': str(e),
                'errors': context.errors,
            }

        finally:
            self._cleanup(context)

    # ── ABSTRACT METHODS (subclasses MUST implement) ───────
    @abstractmethod
    def _connect(self):
        """Establish connection to the source."""
        pass

    @abstractmethod
    def _download(self, source_path: str) -> bytes:
        """Download data from the source."""
        pass

    @abstractmethod
    def _validate(self, raw_data: bytes) -> dict:
        """Validate the downloaded data."""
        pass

    @abstractmethod
    def _load(self, transformed_data: dict,
              destination: str) -> int:
        """Load transformed data to destination."""
        pass

    # ── DEFAULT METHODS (optional override) ────────────────
    def _transform(self, validated_data: dict) -> dict:
        """
        Default transformation: pass-through.
        Subclasses can override for custom transformations.
        """
        return validated_data

    # ── HOOK METHODS (optional, do nothing by default) ─────
    def _pre_process(self, context: PipelineContext):
        """
        Hook: called before download.
        Subclasses can override for setup, logging, metrics.
        """
        logging.info(f"Starting pipeline: {context.source_path}")

    def _post_process(self, context: PipelineContext):
        """
        Hook: called after successful load.
        Subclasses can override for cleanup, notifications.
        """
        logging.info(f"Pipeline complete: {context.source_path}")

    def _handle_error(self, context: PipelineContext, error: Exception):
        """
        Hook: called on error.
        Subclasses can override for custom error handling.
        """
        context.errors.append(str(error))
        logging.error(f"Pipeline failed: {error}")

    def _cleanup(self, context: PipelineContext):
        """
        Hook: always called, even on error.
        Subclasses can override for resource cleanup.
        """
        pass


# ── CONCRETE IMPLEMENTATIONS ───────────────────────────────

class S3DataPipeline(DataPipeline):
    """Pipeline that reads from AWS S3."""

    def __init__(self, bucket: str, region: str = 'us-east-1'):
        self.bucket = bucket
        self.region = region
        self.s3_client = None

    def _connect(self):
        import boto3
        # No keys in code: boto3's default credential chain picks up the
        # IAM role (EKS Pod Identity / IRSA, instance profile) or SSO session.
        self.s3_client = boto3.client('s3', region_name=self.region)
        logging.info(f"Connected to S3 bucket: {self.bucket}")

    def _download(self, source_path: str) -> bytes:
        response = self.s3_client.get_object(
            Bucket=self.bucket, Key=source_path
        )
        return response['Body'].read()

    def _validate(self, raw_data: bytes) -> dict:
        # CSV validation for S3 sources
        import csv
        import io
        reader = csv.DictReader(io.StringIO(raw_data.decode()))
        rows = list(reader)
        if not rows:
            raise ValueError("Empty CSV file")
        return {
            'format': 'csv',
            'headers': reader.fieldnames,
            'row_count': len(rows),
            'rows': rows,
        }

    def _transform(self, validated_data: dict) -> dict:
        # S3-specific transformation: date parsing, type casting
        import datetime
        for row in validated_data['rows']:
            if 'date' in row:
                row['date'] = datetime.datetime.strptime(
                    row['date'], '%Y-%m-%d'
                ).isoformat()
        return validated_data

    def _load(self, transformed_data: dict,
              destination: str) -> int:
        # Load to database
        import psycopg2
        conn = psycopg2.connect(destination)
        try:
            with conn, conn.cursor() as cur:      # `with conn` = one transaction
                cur.executemany(
                    "INSERT INTO s3_data (id, date, amount) "
                    "VALUES (%(id)s, %(date)s, %(amount)s)",
                    transformed_data['rows'],
                )
        finally:
            conn.close()                          # psycopg2's `with` doesn't close
        return len(transformed_data['rows'])

    def _cleanup(self, context: PipelineContext):
        if self.s3_client:
            self.s3_client.close()


class FTPDataPipeline(DataPipeline):
    """Pipeline that reads from FTP server."""

    def __init__(self, host: str, username: str, password: str):
        self.host = host
        self.username = username
        self.password = password
        self.ftp = None

    def _connect(self):
        from ftplib import FTP_TLS
        self.ftp = FTP_TLS(self.host)          # plain FTP sends the password in clear text
        self.ftp.login(self.username, self.password)
        self.ftp.prot_p()                      # encrypt the data channel too
        logging.info(f"Connected to FTP: {self.host}")

    def _download(self, source_path: str) -> bytes:
        import io
        buffer = io.BytesIO()
        self.ftp.retrbinary(f"RETR {source_path}", buffer.write)
        return buffer.getvalue()

    def _validate(self, raw_data: bytes) -> dict:
        # XML validation for FTP sources
        import xml.etree.ElementTree as ET
        root = ET.fromstring(raw_data)   # untrusted XML: prefer defusedxml
        return {
            'format': 'xml',
            'root_tag': root.tag,
            'row_count': len(root),
            'rows': [child.attrib for child in root],
        }

    def _load(self, transformed_data: dict,
              destination: str) -> int:
        # Load to the same database but different table
        import psycopg2
        conn = psycopg2.connect(destination)
        try:
            with conn, conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO ftp_data (id, payload) VALUES (%(id)s, %(payload)s)",
                    transformed_data['rows'],
                )
        finally:
            conn.close()
        return len(transformed_data['rows'])

    def _cleanup(self, context: PipelineContext):
        if self.ftp:
            self.ftp.quit()
```

**Template Method vs Strategy:**

```yaml
Template Method:
  - Inheritance-based: subclass overrides specific steps
  - Shares the algorithm STRUCTURE (order of steps)
  - Steps CAN access shared state (self)
  - Use: when the algorithm skeleton is fixed,
         but some steps vary

Strategy:
  - Composition-based: inject a strategy object
  - Shares the algorithm INTERFACE (inputs/outputs)
  - Strategies are independent objects
  - Use: when the entire algorithm varies,
         or when you need to switch at runtime

HOW TO CHOOSE:
  Template Method: 80% same code, 20% varies
                   (the "skeleton" is fixed)
  Strategy:         100% of the algorithm varies
                   (different algorithms entirely)

EXAMPLE:
  Template Method: DataPipeline (download → validate → transform → load)
                   The skeleton never changes, only implementation details

  Strategy:         PaymentProcessor (charge with Stripe vs PayPal)
                   The entire charging algorithm is different
```

**The composition alternative (what most modern pipelines do):**

```python
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

class Source(Protocol):
    def read(self, path: str) -> bytes: ...

class Sink(Protocol):
    def write(self, rows: list[dict]) -> int: ...

@dataclass
class Pipeline:
    source: Source                                     # S3Source, FtpSource, LocalSource
    parse: Callable[[bytes], list[dict]]               # parse_csv, parse_xml
    sink: Sink                                         # PostgresSink, BigQuerySink
    transforms: Iterable[Callable[[list[dict]], list[dict]]] = ()

    def run(self, path: str) -> int:                   # the skeleton still lives in ONE place
        rows = self.parse(self.source.read(path))
        for transform in self.transforms:
            rows = transform(rows)
        return self.sink.write(rows)

# Pipeline(S3Source(bucket), parse_xml, PostgresSink(dsn)) — no new subclass needed
```

The fixed sequence is still there (that's the Template Method's real value), but each axis varies independently and is testable on its own. Rule of thumb: Template Method for frameworks and one axis of variation; composition of strategies once a second axis appears.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Template method** | Defines the algorithm skeleton in the base class |
| **Abstract vs hook** | Distinguishes between required (abstract) and optional (hook) overrides |
| **Hollywood principle** | Applies "Don't call us, we'll call you" — base class calls subclass methods |
| **vs Strategy** | Explains when inheritance (Template Method) is better than composition (Strategy) |

---

## 12. Pattern Selection — Production Decision Framework

**Q:** "You're reviewing a codebase with 100K+ lines. How do you identify which design patterns are being used — and misused? What's your framework for choosing a pattern for a new problem?"

**What They're Really Testing:** Whether you have a principled approach to pattern selection, and can recognize when patterns are being applied correctly or incorrectly in real code.

### Answer

**Pattern Identification in Existing Code:**

```python
# ── HOW TO IDENTIFY PATTERNS IN CODE ──────────────────────
#
# Look for these "smells" that indicate which pattern is in use:

# 1. STRATEGY: Classes with same interface, different implementations
#    → Look for: ABC with @abstractmethod, multiple subclasses
#    → Smell: Monolithic if/elif chain that selects behavior
#    → Fix: Strategy pattern

# 2. OBSERVER: Subscribe/notify patterns
#    → Look for: register(), subscribe(), notify(), update()
#    → Smell: Direct coupling between event producer and consumer
#    → Fix: Introduce event bus

# 3. FACTORY: Creation logic that depends on type
#    → Look for: if type == 'x': return X() elif type == 'y': return Y()
#    → Smell: Creation logic scattered across codebase
#    → Fix: Factory method or abstract factory

# 4. SINGLETON: Global state with limited instances
#    → Look for: _instance = None, __new__ override
#    → Smell: Module-level variables used as global state
#    → Fix: DI container with singleton scope

# 5. BUILDER: Chained method calls for construction
#    → Look for: .with_xxx().set_yyy().build()
#    → Smell: Constructor with 8+ parameters
#    → Fix: Builder pattern

# 6. ADAPTER: Wrapper that translates interfaces
#    → Look for: class FooAdapter: wraps another class
#    → Smell: All code uses one interface, a new library has different one
#    → Fix: Adapter pattern

# 7. DECORATOR: Wrapper that adds behavior
#    → Look for: class FooMiddleware(Foo): __init__(self, wrapped)
#    → Smell: Cross-cutting concerns mixed with business logic
#    → Fix: Decorator pattern

# 8. COMMAND: Actions as objects
#    → Look for: class XxxCommand: execute(), undo()
#    → Smell: Undo/redo logic scattered across UI code
#    → Fix: Command pattern
```

**Pattern Decision Framework:**

```python
def choose_pattern(problem: ProblemDescription) -> str:
    """
    Decision framework for selecting a design pattern.

    Questions to ask:
      1. What varies? (the key insight)
      2. How does it vary? (by type? by state? by algorithm?)
      3. What can't I change? (existing interfaces, APIs)
      4. What's the lifecycle? (static? runtime switchable?)
      5. What's the relationship? (one-to-one? one-to-many?)
    """

    # ── CREATIONAL PATTERNS ───────────────────────────────
    if problem.type == 'object_creation':
        if problem.multiple_products and problem.product_family:
            return "Abstract Factory"
        elif problem.one_product_multiple_variants:
            return "Factory Method"
        elif problem.complex_construction:
            return "Builder"
        elif problem.one_instance_global:
            if problem.is_infrastructure:
                return "Singleton (DI container scope)"
            else:
                return "Dependency Injection (not Singleton)"

    # ── STRUCTURAL PATTERNS ──────────────────────────────
    if problem.type == 'interface_or_structure':
        if problem.incompatible_interfaces:
            return "Adapter"
        elif problem.add_responsibilities_dynamically:
            return "Decorator"
        elif problem.simplify_complex_system:
            return "Facade"
        elif problem.control_access:
            return "Proxy"

    # ── BEHAVIORAL PATTERNS ──────────────────────────────
    if problem.type == 'behavior_or_algorithm':
        if problem.switchable_algorithms:
            if problem.algorithm_skeleton_fixed:
                return "Template Method"
            else:
                return "Strategy"
        elif problem.state_dependent_behavior:
            return "State"
        elif problem.undoable_operations:
            return "Command"
        elif problem.one_to_many_notification:
            return "Observer"

    return "No pattern needed — use simpler approach"
```

**Pattern Misuse Detection — Code Review Checklist:**

```yaml
CHECKLIST: Pattern misuse in code review

SINGLETON MISUSE:
  [ ] Is the singleton used for global convenience, not genuine single-instance need?
  [ ] Does the singleton make unit testing impossible?
  [ ] Fix: Use DI with singleton scope instead

FACTORY MISUSE:
  [ ] Does the factory just call a constructor with no additional logic?
  [ ] Is a simple dict lookup sufficient instead of a factory class?
  [ ] Fix: Replace with dict of callables or direct construction

OBSERVER MISUSE:
  [ ] Are observers creating memory leaks (forgetting to unsubscribe)?
  [ ] Is the notification storm overwhelming the system?
  [ ] Fix: Use weak references, batch notifications, async delivery

STRATEGY MISUSE:
  [ ] Are all strategies nearly identical (90%+ code reuse)?
  [ ] Is the pattern being used when a simple if/else would suffice?
  [ ] Fix: Use Template Method for shared structure, Strategy for different algorithms

DECORATOR MISUSE:
  [ ] Is the decorator modifying behavior in ways that violate LSP?
  [ ] Is the decorator stack unpredictable (order-dependent)?
  [ ] Fix: Ensure each decorator adds a single responsibility, document order

GOD CLASS MISUSE (disguised as Facade):
  [ ] Does the "facade" contain business logic instead of just delegating?
  [ ] Does the "facade" need to change when business rules change?
  [ ] Fix: Move logic to subsystem classes, keep Facade as pure delegation
```

**Pattern Selection Heuristics:**

```python
# ── SIMPLICITY RULE ───────────────────────────────────────
# Before applying a pattern, ask:
#   "Can I solve this with a function, a dict, or a simple class?"
# If yes, skip the pattern.

# ── "WHAT VARIES?" RULE ───────────────────────────────────
# The Gang of Four principle: "Encapsulate what varies."
# Identify WHAT varies, then choose the pattern that encapsulates it.
#
#   Algorithm varies  → Strategy or Template Method
#   Object creation   → Factory Method or Abstract Factory
#   State varies      → State pattern
#   Notification      → Observer
#   Interface varies  → Adapter
#   Responsibilities  → Decorator

# ── YAGNI RULE ────────────────────────────────────────────
# "You Aren't Gonna Need It"
# Don't apply a pattern "just in case" you'll need it later.
# Apply patterns when the pain point is REAL, not hypothetical.
# It's easier to introduce a pattern later than to remove one.

# ── TESTABILITY RULE ──────────────────────────────────────
# If the pattern makes testing harder, it's probably wrong.
# A good pattern DECOUPLES dependencies (improves testability).
# Singleton, Service Locator, and global state reduce testability.

# ── TEAM FAMILIARITY RULE ─────────────────────────────────
# Consider your team's familiarity with the pattern.
# A simple if/else that everyone understands is better
# than a perfect Abstract Factory that no one can maintain.
```

**Other patterns interviewers bring up (one line each):**

| Pattern | Intent | Typical production use | Watch out for |
|---------|--------|------------------------|---------------|
| **Proxy** | Stand-in with the *same* interface that controls access | Lazy loading (ORM relations), remote stubs (gRPC clients), caching or auth proxies | Hidden latency: a "field access" that is really a network call (N+1 queries) |
| **Composite** | Treat a tree of objects and single objects uniformly | UI trees, file systems, org charts, `MacroCommand` above | Operations that don't make sense on leaves |
| **Chain of Responsibility** | Pass a request along handlers until one handles it | Approval workflows, exception handlers, validation pipelines | Requests that fall off the end silently |
| **Iterator / Generator** | Traverse without exposing the structure | Python generators, Java streams, paginated API clients | Holding cursors/connections open while iterating |
| **Repository** | Collection-like interface over persistence for an aggregate | DDD domain layer, keeping SQL out of business logic | Generic `Repository<T>` with 40 query methods: a leaky DAO |
| **Unit of Work** | Track changes and commit them in one transaction | SQLAlchemy `Session`, EF Core `DbContext`, Hibernate session | Long-lived sessions holding stale data and locks |
| **Specification** | Business rules as composable predicate objects | Eligibility and filtering rules reused across query and validation | Over-abstraction for two simple filters |
| **Dependency Injection** | Objects receive their collaborators instead of creating them | Every testable codebase; Spring, Guice, FastAPI `Depends` | Container magic that hides the wiring; prefer constructor injection |

Distributed-systems patterns (circuit breaker, bulkhead, outbox, saga, CQRS, strangler fig) are covered in [Software Architecture Q&A](INTERVIEW_QUESTIONS.md).

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pattern identification** | Can identify patterns from code structure (smells) |
| **Decision framework** | Has a structured approach to choosing patterns |
| **Misuse detection** | Can identify when patterns are applied incorrectly |
| **Simplicity first** | Starts with "no pattern" and adds patterns only when justified |

---

> *Master these patterns not by memorizing UML diagrams, but by understanding the underlying principles: encapsulate what varies, program to interfaces, favor composition over inheritance, and follow the Single Responsibility Principle. Patterns are solutions to recurring problems — not recipes to be followed blindly.*

