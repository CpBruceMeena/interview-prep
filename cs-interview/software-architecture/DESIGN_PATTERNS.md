# 🏗️ Software Design Patterns — Principal Engineer Deep-Dive

> *12 patterns with production-grade implementations, interview questions, and principal engineer–level analysis. Covers creational, structural, and behavioral patterns — not just what they are, but when and why to use them in real systems.*

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
    raw_response: dict = None

class PaymentGatewayStrategy(ABC):
    """Interface for all payment gateway strategies."""

    @abstractmethod
    def charge(self, amount: float, currency: str,
               source: dict) -> PaymentResult:
        """Charge a payment source."""
        pass

    @abstractmethod
    def refund(self, transaction_id: str,
               amount: Optional[float] = None) -> PaymentResult:
        """Refund a transaction."""
        pass

    @abstractmethod
    def get_rate_limit(self) -> int:
        """Returns max requests per second for this gateway."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Health check for this gateway."""
        pass

# ── CONCRETE STRATEGIES ─────────────────────────────────────

class StripeStrategy(PaymentGatewayStrategy):
    def __init__(self, api_key: str, webhook_secret: str):
        self.client = StripeClient(api_key)
        self.webhook_secret = webhook_secret
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            reset_timeout=30,
        )

    def charge(self, amount: float, currency: str,
               source: dict) -> PaymentResult:
        try:
            # Wrap in circuit breaker
            return self._circuit_breaker.call(
                self._do_charge, amount, currency, source
            )
        except CircuitBreakerOpen:
            return PaymentResult(
                success=False,
                error_message="Stripe circuit breaker open",
            )

    def _do_charge(self, amount: float, currency: str,
                   source: dict) -> PaymentResult:
        try:
            intent = self.client.payment_intents.create(
                amount=int(amount * 100),  # Stripe uses cents
                currency=currency.lower(),
                payment_method=source['payment_method_id'],
                confirm=True,
                idempotency_key=source.get('idempotency_key'),
            )
            return PaymentResult(
                success=True,
                transaction_id=intent.id,
                raw_response=intent.to_dict(),
            )
        except stripe.error.CardError as e:
            return PaymentResult(
                success=False,
                error_message=f"Card declined: {e.user_message}",
            )
        except stripe.error.RateLimitError:
            # Backoff and retry handled by caller
            raise

    def refund(self, transaction_id: str,
               amount: Optional[float] = None) -> PaymentResult:
        try:
            refund = self.client.refunds.create(
                payment_intent=transaction_id,
                amount=int(amount * 100) if amount else None,
            )
            return PaymentResult(success=True, transaction_id=refund.id)
        except Exception as e:
            return PaymentResult(success=False, error_message=str(e))

    def get_rate_limit(self) -> int:
        return 100  # Stripe: 100 req/s

    def is_available(self) -> bool:
        try:
            self.client.balance.retrieve()
            return True
        except Exception:
            return False


class PayPalStrategy(PaymentGatewayStrategy):
    def __init__(self, client_id: str, client_secret: str):
        self.client = PayPalClient(client_id, client_secret)

    def charge(self, amount: float, currency: str,
               source: dict) -> PaymentResult:
        try:
            order = self.client.order.create({
                'intent': 'CAPTURE',
                'purchase_units': [{
                    'amount': {
                        'currency_code': currency,
                        'value': str(amount),
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
               amount: Optional[float] = None) -> PaymentResult:
        try:
            refund = self.client.payment.refund(
                transaction_id,
                amount=str(amount) if amount else None,
            )
            return PaymentResult(success=True, transaction_id=refund.id)
        except Exception as e:
            return PaymentResult(success=False, error_message=str(e))

    def get_rate_limit(self) -> int:
        return 50  # PayPal: 50 req/s

    def is_available(self) -> bool:
        try:
            self.client.auth.get_token()
            return True
        except Exception:
            return False


class SquareStrategy(PaymentGatewayStrategy):
    """Similar implementation for Square..."""
    pass

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
            ),
            'paypal': PayPalStrategy(
                client_id=os.environ['PAYPAL_CLIENT_ID'],
                client_secret=os.environ['PAYPAL_CLIENT_SECRET'],
            ),
            'square': SquareStrategy(
                access_token=os.environ['SQUARE_ACCESS_TOKEN'],
            ),
        }

    def process_payment(self, amount: float, currency: str,
                        source: dict, preferred: str = None) -> PaymentResult:
        """
        Process a payment, automatically selecting the best gateway.

        Selection criteria:
          1. Use preferred gateway if available and healthy
          2. Fall back to next available gateway
          3. Consider rate limits and current load
        """
        if preferred and preferred in self.gateways:
            gateway = self.gateways[preferred]
            if gateway.is_available():
                result = gateway.charge(amount, currency, source)
                if result.success:
                    return self._enrich_result(result, preferred)
                # Fall through to fallback

        # Fallback: try other gateways
        for name, gateway in self.gateways.items():
            if name == preferred:
                continue  # Already tried
            if not gateway.is_available():
                continue
            if self._is_rate_limited(gateway):
                continue

            result = gateway.charge(amount, currency, source)
            if result.success:
                return self._enrich_result(result, name)

        return PaymentResult(
            success=False,
            error_message="All payment gateways failed",
        )

    def _is_rate_limited(self, gateway: PaymentGatewayStrategy) -> bool:
        """Check if gateway is approaching its rate limit."""
        current_rate = self._get_current_rate(gateway)
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
  1. You have only 2 variations (use if/else or ternary)
  2. The algorithm never changes at runtime
  3. The algorithm is a simple one-liner
  4. You're using a language with first-class functions
     (use function passing instead)
  5. The strategies share 90%+ code (use Template Method instead)

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

---

## 2. Observer Pattern

**Q:** "Design an event-driven notification system where users can subscribe to different types of events (order updates, price changes, inventory alerts). The system must support both push and pull models, handle subscriber failures gracefully, and scale to 10K events/second. Implement this using the Observer pattern, then critique its limitations."

**What They're Really Testing:** Whether you understand the Observer pattern's strengths (decoupling) and weaknesses (memory leaks, notification storms, subscriber failure propagation) from production experience.

### Answer

**Observer Pattern — Basic Structure:**

```python
# ── OBSERVABLE (Subject) ───────────────────────────────────
from abc import ABC, abstractmethod
from typing import Any, Callable
import weakref
import asyncio
import logging

class Observable:
    """
    Observable subject that maintains a list of observers.
    Uses weak references to prevent memory leaks.
    """

    def __init__(self):
        # Weak set — observers can be garbage collected
        self._observers: set[weakref.ref] = set()
        self._lock = asyncio.Lock()

    def attach(self, observer: 'Observer'):
        """Subscribe an observer. Uses weak reference."""
        self._observers.add(weakref.ref(observer))

    def detach(self, observer: 'Observer'):
        """Unsubscribe an observer."""
        self._observers.discard(weakref.ref(observer))

    async def notify(self, event: Any):
        """Notify all observers of an event."""
        dead_refs = []
        async with self._lock:
            for ref in self._observers:
                observer = ref()
                if observer is None:
                    dead_refs.append(ref)
                    continue
                try:
                    await observer.update(self, event)
                except Exception as e:
                    # Isolate observer failures — one failing observer
                    # should NOT affect other observers
                    logging.error(f"Observer failed: {e}")

        # Clean up dead references
        for ref in dead_refs:
            self._observers.discard(ref)


class Observer(ABC):
    """Observer interface."""

    @abstractmethod
    async def update(self, subject: Observable, event: Any):
        """Receive notification from subject."""
        pass
```

**Production-Grade Observer with Push and Pull Models:**

```python
# ── PUSH MODEL: Subject pushes event data to observers ─────
# Simple, but can overload observers with irrelevant data.

class PushNotificationObserver(Observer):
    async def update(self, subject: Observable, event: Any):
        """Receive pushed event data."""
        if event.type == 'order.shipped':
            await self.send_push_notification(
                user_id=event.user_id,
                message=f"Your order {event.order_id} has shipped!"
            )

# ── PULL MODEL: Observer fetches what it needs ─────────────
# More efficient — observers control what they consume.

class PullNotificationObserver(Observer):
    """
    Observer uses PULL model: receives only a notification
    that SOMETHING changed, then fetches relevant data.
    """

    async def update(self, subject: Observable, event: Any):
        """
        Subject only sends minimal info: "something changed".
        Observer pulls the data it actually needs.
        """
        # Only interested in price changes
        if event.type != 'price.changed':
            return

        # Pull the actual data we need
        affected_products = await self.get_watched_product_ids()
        for product_id in affected_products:
            new_price = await self.fetch_price(product_id)
            if self.should_notify(product_id, new_price):
                await self.send_price_alert(product_id, new_price)

    async def get_watched_product_ids(self) -> list[int]:
        # Observer pulls its own watchlist
        return await db.fetch(
            "SELECT product_id FROM user_watchlists WHERE user_id = $1",
            self.user_id,
        )

    async def fetch_price(self, product_id: int) -> float:
        # Pull specific data from subject
        return await price_service.get_price(product_id)
```

**Event Bus — Decoupled Observer:**

```python
# ── EVENT BUS: Decoupled Observer ───────────────────────────
# In production, direct Subject-Observer coupling is rare.
# Instead, use an event bus (pub-sub) for complete decoupling.

class EventBus:
    """
    Central event bus. Publishers and subscribers are fully
    decoupled — they don't know about each other.
    """

    def __init__(self):
        # {event_type: [list of handlers]}
        self._handlers: dict[str, list[Callable]] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: str, handler: Callable):
        """Subscribe a handler to an event type."""
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable):
        """Unsubscribe a handler."""
        with self._lock:
            if event_type in self._handlers:
                self._handlers[event_type].remove(handler)

    async def publish(self, event_type: str, event_data: Any):
        """Publish an event to all subscribers."""
        handlers = self._handlers.get(event_type, []).copy()  # Thread-safe copy
        for handler in handlers:
            try:
                await handler(event_data)
            except Exception as e:
                # Isolate failures
                logging.error(f"Handler {handler.__name__} failed: {e}")

    def subscribe_weak(self, event_type: str, handler: Callable):
        """
        Subscribe with weak reference to prevent memory leaks.
        If the handler's owner object is garbage collected,
        the subscription is automatically removed.
        """
        weak_handler = weakref.ref(handler)

        def wrapper(event_data):
            actual_handler = weak_handler()
            if actual_handler:
                return actual_handler(event_data)
            # Auto-unsubscribe
            self.unsubscribe(event_type, wrapper)

        self.subscribe(event_type, wrapper)


# ── USAGE ──────────────────────────────────────────────────

event_bus = EventBus()

# Subscribe (Observer)
class OrderNotifier:
    def __init__(self):
        # Subscribe with bound method
        event_bus.subscribe('order.created', self.on_order_created)
        event_bus.subscribe('order.shipped', self.on_order_shipped)

    async def on_order_created(self, event):
        await email_service.send_confirmation(event['order_id'])

    async def on_order_shipped(self, event):
        await sms_service.send_tracking(
            event['user_phone'],
            event['tracking_number'],
        )

    def __del__(self):
        # Clean up — unsubscribe to prevent memory leaks
        event_bus.unsubscribe('order.created', self.on_order_created)
        event_bus.unsubscribe('order.shipped', self.on_order_shipped)

# Publish (Subject)
class OrderService:
    async def create_order(self, order_data):
        order = await self.db.create_order(order_data)
        # Publish event — no knowledge of who's listening
        await event_bus.publish('order.created', {
            'order_id': order.id,
            'user_id': order.user_id,
            'amount': order.amount,
        })
        return order
```

**Observer Anti-Patterns & Pitfalls:**

```python
# 🔴 ANTI-PATTERN 1: Notification Storm
class PriceUpdateObservable(Observable):
    async def update_price(self, product_id, new_price):
        # This triggers ALL observers — potentially 1000s!
        # Each observer might make DB calls, API calls, etc.
        await self.notify(PriceChanged(product_id, new_price))

# PROBLEM: Cascade of notifications
#   Price update → notify 1000 observers
#   Each observer makes an API call
#   API latency: 100ms
#   Total: 1000 × 100ms = 100 seconds of processing!
#   Eventual timeout, cascading failures

# ✅ FIX: Batch notifications
class BatchPriceUpdateObservable(Observable):
    def __init__(self):
        super().__init__()
        self._pending_updates = []
        self._flush_task = asyncio.create_task(self._periodic_flush())

    def update_price(self, product_id, new_price):
        self._pending_updates.append((product_id, new_price))

    async def _periodic_flush(self):
        while True:
            await asyncio.sleep(0.1)  # 100ms batch window
            if self._pending_updates:
                batch = self._pending_updates.copy()
                self._pending_updates.clear()
                await self.notify(BatchPriceChanged(batch))


# 🔴 ANTI-PATTERN 2: Memory Leak (forgetting to unsubscribe)
class LeakyComponent:
    def __init__(self, event_bus):
        # Subscribe but NEVER unsubscribe
        event_bus.subscribe('data.updated', self.on_data_updated)

    def on_data_updated(self, event):
        print(f"Data updated: {event}")

    # ❌ No __del__ to unsubscribe!
    # When LeakyComponent is garbage collected:
    #   - event_bus still holds a reference to on_data_updated
    #   - on_data_updated holds a reference to self (bound method)
    #   → LeakyComponent is NEVER garbage collected!
    #   → MEMORY LEAK

# ✅ FIX: Use weakref or explicit cleanup
class CleanComponent:
    def __init__(self, event_bus):
        # Subscribe with weak reference
        event_bus.subscribe_weak('data.updated', self.on_data_updated)
        # OR: store the handler for later cleanup
        self._handler = self.on_data_updated
        event_bus.subscribe('data.updated', self._handler)

    def cleanup(self):
        """Explicit cleanup — call when component is destroyed."""
        event_bus.unsubscribe('data.updated', self._handler)


# 🔴 ANTI-PATTERN 3: Synchronous notification in async system
class SyncObservable(Observable):
    def notify(self, event):
        # SYNCHRONOUS — blocks the publisher!
        for observer in self._observers:
            observer.update(self, event)  # Blocks until done!
        # If one observer takes 5 seconds, publisher is blocked 5 seconds

# ✅ FIX: Async notification with timeout
class AsyncObservable(Observable):
    async def notify(self, event):
        async with self._lock:
            tasks = []
            for ref in self._observers:
                observer = ref()
                if observer:
                    task = asyncio.create_task(
                        self._safe_notify(observer, event)
                    )
                    tasks.append(task)
            # Fire and forget — don't wait for all
            # (or wait with timeout: asyncio.wait(tasks, timeout=5))

    async def _safe_notify(self, observer, event, timeout=5):
        try:
            await asyncio.wait_for(
                observer.update(self, event),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logging.warning(f"Observer {observer} timed out")
        except Exception as e:
            logging.error(f"Observer {observer} failed: {e}")
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Push vs pull** | Explains both models and when to use each |
| **Memory leaks** | Identifies the leak-via-subscription problem and proposes weakref solution |
| **Isolation** | Ensures one failing observer doesn't affect others |
| **Event bus** | Mentions decoupled pub-sub as the production alternative to direct Subject-Observer |
| **Thundering herd** | Identifies notification storms and proposes batching |

---

## 3. Factory Method & Abstract Factory

**Q:** "Design a document processing system that handles PDF, Word, HTML, and Markdown documents. Documents need different parsers, renderers, and exporters. Walk through both Factory Method and Abstract Factory patterns. When would you choose one over the other? When is a factory just unnecessary complexity?"

**What They're Really Testing:** Whether you understand factories as a way to manage object creation when constructors aren't enough, and can distinguish between genuine creation complexity and over-engineering.

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
        self.content = self._parse(path)  # Factory method call
        self._renderer = self._create_renderer()  # Factory method

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


# ── FACTORY METHOD WITH PARAMETER ───────────────────────────
# Alternative: a static factory method that decides based on input

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
        print("Light button clicked")

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

class DarkTextField(TextField):
    def render(self):
        return "[ Dark Text Field ]"

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
  - Example: Document._parse()

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

---

## 4. Singleton Pattern — When It's OK and When It's Not

**Q:** "Singleton is often called an anti-pattern. Defend it: when is Singleton actually the right choice in production? Then critique it: why is it problematic for testing and dependency management? Show me a thread-safe Singleton implementation and a Dependency Injection alternative."

**What They're Really Testing:** Whether you understand the Singleton debate at a nuanced level — not "Singleton is always bad" or "Singleton is always good" — but when it genuinely helps and when it hurts.

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
  - Connection pool: YES — you can't have 50 pools to the same DB
  - Logger: YES — you want all logs in one place
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
| **Thread safety** | Implements thread-safe singleton with double-checked locking |
| **When singleton works** | Identifies genuine single-instance needs (pools, config) |
| **Testing critique** | Shows how singleton makes testing impossible and DI makes it easy |
| **DI container** | Proposes DI framework with singleton scope for app-wide dependencies |

---

## 5. Builder Pattern

**Q:** "Design a query builder for a database that constructs complex SQL queries programmatically. Walk through the Builder pattern. How does it handle the 'telescoping constructor' problem? When does a builder become over-engineering?"

**What They're Really Testing:** Whether you understand the Builder pattern's primary use case — constructing complex objects with many optional parameters — and can distinguish it from simple named parameters.

### Answer

**The Telescoping Constructor Problem:**

```python
# ── THE PROBLEM: Telescoping constructors ───────────────────
class Query:
    """A database query with many optional parameters."""

    def __init__(self, table: str, select: list = None,
                 where: dict = None, order_by: str = None,
                 limit: int = None, offset: int = None,
                 join: list = None, group_by: list = None,
                 having: dict = None, distinct: bool = False):
        self.table = table
        self.select = select or ['*']
        self.where = where or {}
        self.order_by = order_by
        self.limit = limit
        self.offset = offset
        self.join = join or []
        self.group_by = group_by or []
        self.having = having or {}
        self.distinct = distinct

# Usage — hard to read, easy to make mistakes:
query = Query(
    table='users',
    select=['id', 'name', 'email'],
    where={'status': 'active', 'age__gt': 18},
    order_by='name',
    limit=10,
    offset=20,
    join=[('orders', 'users.id = orders.user_id')],
)

# What if I miss an argument? What's the 6th positional arg?
# Hard to read, easy to swap arguments!
```

**Builder Pattern Solution:**

```python
# ── BUILDER ─────────────────────────────────────────────────
class QueryBuilder:
    """
    Builds SQL queries step by step.
    Each method returns self — enables method chaining.
    """

    def __init__(self):
        self._table = None
        self._select = ['*']
        self._where = {}
        self._order_by = None
        self._limit = None
        self._offset = None
        self._joins = []
        self._group_by = []
        self._having = {}
        self._distinct = False
        self._params = []  # Parameterized query params

    def table(self, table_name: str):
        """Set the table to query."""
        self._table = table_name
        return self

    def select(self, *columns: str):
        """Select specific columns."""
        self._select = list(columns) if columns else ['*']
        return self

    def where(self, condition: str, *params):
        """Add a WHERE condition."""
        if isinstance(condition, dict):
            self._where.update(condition)
        else:
            # Raw condition: where("age > %s", 18)
            self._where[condition] = True
            self._params.extend(params)
        return self

    def order_by(self, column: str, direction: str = 'ASC'):
        """Add ORDER BY clause."""
        self._order_by = f"{column} {direction}"
        return self

    def limit(self, n: int):
        """Add LIMIT clause."""
        self._limit = n
        return self

    def offset(self, n: int):
        """Add OFFSET clause."""
        self._offset = n
        return self

    def join(self, table: str, on: str, join_type: str = 'INNER'):
        """Add a JOIN clause."""
        self._joins.append(f"{join_type} JOIN {table} ON {on}")
        return self

    def group_by(self, *columns: str):
        """Add GROUP BY clause."""
        self._group_by = list(columns)
        return self

    def having(self, condition: str):
        """Add HAVING condition."""
        self._having[condition] = True
        return self

    def distinct(self):
        """Add DISTINCT modifier."""
        self._distinct = True
        return self

    def build(self) -> 'Query':
        """
        Build the final Query object.
        Validates that required fields are set.
        """
        if not self._table:
            raise ValueError("Table name is required")

        return Query(
            table=self._table,
            select=self._select,
            where=self._where,
            order_by=self._order_by,
            limit=self._limit,
            offset=self._offset,
            joins=self._joins,
            group_by=self._group_by,
            having=self._having,
            distinct=self._distinct,
        )

    def build_sql(self) -> tuple[str, list]:
        """Build the SQL string directly."""
        parts = []

        # SELECT clause
        select_clause = "SELECT "
        if self._distinct:
            select_clause += "DISTINCT "
        select_clause += ", ".join(self._select)
        parts.append(select_clause)

        # FROM clause
        parts.append(f"FROM {self._table}")

        # JOIN clauses
        parts.extend(self._joins)

        # WHERE clause
        if self._where:
            conditions = []
            for key, value in self._where.items():
                if key.endswith('__gt'):
                    conditions.append(f"{key[:-4]} > %s")
                    self._params.append(value)
                elif key.endswith('__lt'):
                    conditions.append(f"{key[:-4]} < %s")
                    self._params.append(value)
                elif isinstance(value, list):
                    placeholders = ", ".join(["%s"] * len(value))
                    conditions.append(f"{key} IN ({placeholders})")
                    self._params.extend(value)
                else:
                    conditions.append(f"{key} = %s")
                    self._params.append(value)
            parts.append(f"WHERE {' AND '.join(conditions)}")

        # GROUP BY
        if self._group_by:
            parts.append(f"GROUP BY {', '.join(self._group_by)}")

        # HAVING
        if self._having:
            parts.append(f"HAVING {' AND '.join(self._having.keys())}")

        # ORDER BY
        if self._order_by:
            parts.append(f"ORDER BY {self._order_by}")

        # LIMIT
        if self._limit is not None:
            parts.append(f"LIMIT {self._limit}")

        # OFFSET
        if self._offset is not None:
            parts.append(f"OFFSET {self._offset}")

        return " ".join(parts), self._params


# ── USAGE ───────────────────────────────────────────────────

# Clear, readable method chaining:
query = (
    QueryBuilder()
    .table('users')
    .select('id', 'name', 'email')
    .where('status', 'active')
    .where('age__gt', 18)
    .order_by('name')
    .limit(10)
    .offset(20)
    .join('orders', 'users.id = orders.user_id')
    .build()
)

# Alternative: build SQL directly
sql, params = (
    QueryBuilder()
    .table('users')
    .select('id', 'name')
    .where('status', 'active')
    .order_by('created_at', 'DESC')
    .limit(100)
    .build_sql()
)
# sql == "SELECT id, name FROM users WHERE status = %s ORDER BY created_at DESC LIMIT 100"
# params == ['active']
```

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
  1. Construction has 5+ optional parameters
  2. Some parameters depend on each other
     (e.g., offset requires limit)
  3. The object is IMMUTABLE after construction
  4. Construction has VALIDATION logic
     (e.g., table name is required, offset requires limit)
  5. You want method CHAINING for readability
  6. The same construction process creates different
     representations (e.g., SQL string vs Query object)

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
| **Build vs build_sql** | Shows how same builder creates different representations |
| **Over-engineering** | Identifies when named parameters or dataclass replace builder |

---

## 6. Adapter Pattern

**Q:** "Your team is migrating from an old payment gateway to a new one. The old gateway has interface A, the new one has interface B. You can't modify either interface. Design an Adapter to make the new gateway work with the old code. How does this differ from the Facade pattern?"

**What They're Really Testing:** Whether you understand Adapter as an interface compatibility pattern, and can distinguish it from Facade (simplification) and Proxy (control).

### Answer

**The Problem — Incompatible Interfaces:**

```python
# ── OLD INTERFACE (can't modify) ───────────────────────────
class OldPaymentGateway:
    """Legacy payment gateway. Used everywhere."""

    def process_payment(self, amount: float, currency: str,
                        card_number: str, expiry: str, cvv: str) -> dict:
        """Process payment with raw card details."""
        return {
            'success': True,
            'transaction_id': 'TX_12345',
            'amount': amount,
            'currency': currency,
        }

    def refund_payment(self, transaction_id: str) -> dict:
        """Refund a previous payment."""
        return {'success': True, 'transaction_id': transaction_id}


# ── NEW INTERFACE (also can't modify) ──────────────────────
class NewPaymentGateway:
    """Modern payment gateway. Different interface."""

    def create_payment_intent(self, amount_cents: int,
                               currency: str) -> str:
        """Create a payment intent. Returns intent ID."""
        return "pi_67890"

    def confirm_payment_intent(self, intent_id: str,
                                payment_method_id: str) -> dict:
        """Confirm a payment intent with a payment method."""
        return {
            'id': intent_id,
            'status': 'succeeded',
            'amount': amount_cents,
        }

    def create_refund(self, payment_intent_id: str,
                      amount_cents: int = None) -> dict:
        """Create a refund."""
        return {'id': 'ref_12345', 'status': 'succeeded'}
```

**Adapter Pattern Solution:**

```python
# ── TARGET INTERFACE (what old code expects) ───────────────
class PaymentGateway(ABC):
    """Abstract interface that old code depends on."""

    @abstractmethod
    def process_payment(self, amount: float, currency: str,
                        card_number: str, expiry: str,
                        cvv: str) -> dict:
        pass

    @abstractmethod
    def refund_payment(self, transaction_id: str) -> dict:
        pass


# ── ADAPTER: Makes NewPaymentGateway work like OldPaymentGateway ──
class NewPaymentAdapter(PaymentGateway):
    """
    Adapter that translates the OLD interface calls
    to the NEW interface.

    This allows the system to switch from OldPaymentGateway
    to NewPaymentGateway WITHOUT changing any client code.
    """

    def __init__(self, new_gateway: NewPaymentGateway):
        self.gateway = new_gateway
        # Payment method storage (in production, use a vault)
        self._payment_methods: dict[str, str] = {}

    def process_payment(self, amount: float, currency: str,
                        card_number: str, expiry: str,
                        cvv: str) -> dict:
        """
        Translate old process_payment call to new interface.

        1. Create payment method from card details
        2. Create payment intent
        3. Confirm payment intent
        """
        # Step 1: Create payment method (new interface)
        payment_method_id = self._tokenize_card(card_number, expiry, cvv)
        self._payment_methods[card_number[-4:]] = payment_method_id

        # Step 2: Create intent (new interface uses cents)
        amount_cents = int(amount * 100)
        intent_id = self.gateway.create_payment_intent(
            amount_cents, currency
        )

        # Step 3: Confirm intent
        result = self.gateway.confirm_payment_intent(
            intent_id, payment_method_id
        )

        # Step 4: Translate result back to old format
        return {
            'success': result['status'] == 'succeeded',
            'transaction_id': result['id'],
            'amount': amount,
            'currency': currency,
        }

    def refund_payment(self, transaction_id: str) -> dict:
        """
        Translate old refund call to new interface.
        """
        # Old format: "TX_12345"
        # New format: "pi_67890"
        # We need to extract the payment intent ID
        intent_id = self._extract_intent_id(transaction_id)

        result = self.gateway.create_refund(intent_id)

        return {
            'success': result['status'] == 'succeeded',
            'transaction_id': result['id'],
        }

    def _tokenize_card(self, card_number: str, expiry: str,
                       cvv: str) -> str:
        """Tokenize card details into a payment method ID."""
        # In production: call payment gateway's tokenization API
        # Never store raw card numbers!
        return f"pm_{hash(card_number)}"

    def _extract_intent_id(self, transaction_id: str) -> str:
        """Extract payment intent ID from old transaction ID."""
        # Map old IDs to new IDs (stored during process_payment)
        return transaction_id.replace("TX_", "pi_")


# ── CLIENT CODE (unchanged!) ───────────────────────────────

class CheckoutService:
    """
    Client code that uses the old interface.
    Works with OldPaymentGateway OR NewPaymentAdapter —
    both implement the same interface.
    """

    def __init__(self, payment_processor: PaymentGateway):
        self.payment = payment_processor  # Can be old or new!

    def checkout(self, cart_total: float, card_info: dict) -> dict:
        return self.payment.process_payment(
            amount=cart_total,
            currency='USD',
            card_number=card_info['number'],
            expiry=card_info['expiry'],
            cvv=card_info['cvv'],
        )


# ── USAGE ──────────────────────────────────────────────────

# Old system:
# old_gateway = OldPaymentGateway()
# checkout = CheckoutService(old_gateway)

# New system (with adapter):
new_gateway = NewPaymentGateway()
adapter = NewPaymentAdapter(new_gateway)
checkout = CheckoutService(adapter)  # Same CheckoutService, no changes!

result = checkout.checkout(99.99, {
    'number': '4111111111111111',
    'expiry': '12/25',
    'cvv': '123',
})
```

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

  Adapter: \"Make this API look like that API\"
  Facade: \"Give me a simple way to use this complex system\"
  Proxy: \"I'm standing in front of the real object\"
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Interface translation** | Adapter converts old interface calls to new ones without changing client code |
| **Adapter vs Facade** | Clearly distinguishes between interface conversion (Adapter) and simplification (Facade) |
| **Object vs class adapter** | Uses object adapter (composition) over class adapter (inheritance) for flexibility |
| **Idiomatic translation** | Translates data formats (cents vs dollars, TX_ vs pi_) correctly |

---

## 7. Decorator Pattern

**Q:** "Design a middleware system for an HTTP server where each request passes through multiple processing stages: authentication, rate limiting, logging, caching, and compression. The order and combination of stages varies per route. Use the Decorator pattern. How is this different from the Chain of Responsibility pattern?"

**What They're Really Testing:** Whether you understand Decorator as a way to add responsibilities to objects dynamically, and can distinguish it from Chain of Responsibility (where handlers decide whether to pass the request).

### Answer

**Decorator Pattern for HTTP Middleware:**

```python
# ── COMPONENT INTERFACE ────────────────────────────────────
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class Request:
    method: str
    path: str
    headers: dict
    body: Optional[bytes] = None
    user: Optional[dict] = None
    client_ip: str = ""

@dataclass
class Response:
    status_code: int
    headers: dict
    body: bytes

class HttpHandler(ABC):
    """Base component: handles an HTTP request."""

    @abstractmethod
    async def handle(self, request: Request) -> Response:
        pass


# ── CONCRETE COMPONENT: Base handler ────────────────────────
class BaseHttpHandler(HttpHandler):
    """The actual request handler — sends request to the app."""

    def __init__(self, app):
        self.app = app

    async def handle(self, request: Request) -> Response:
        return await self.app.dispatch(request)


# ── DECORATOR BASE ─────────────────────────────────────────
class Middleware(HttpHandler):
    """
    Base Decorator: wraps another handler.
    Subclasses add behavior before/after calling wrapped handler.
    """

    def __init__(self, wrapped: HttpHandler):
        self._wrapped = wrapped

    @abstractmethod
    async def handle(self, request: Request) -> Response:
        pass


# ── CONCRETE DECORATORS ────────────────────────────────────

class AuthenticationMiddleware(Middleware):
    """Decorator: adds authentication."""

    def __init__(self, wrapped: HttpHandler, jwt_secret: str):
        super().__init__(wrapped)
        self.jwt_secret = jwt_secret

    async def handle(self, request: Request) -> Response:
        # BEFORE: Authenticate the request
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response(
                status_code=401,
                headers={'Content-Type': 'application/json'},
                body=b'{"error": "Missing or invalid token"}',
            )

        token = auth_header[7:]  # Remove 'Bearer '
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=['HS256'])
            request.user = payload
        except jwt.ExpiredSignatureError:
            return Response(
                status_code=401,
                headers={'Content-Type': 'application/json'},
                body=b'{"error": "Token expired"}',
            )
        except jwt.InvalidTokenError:
            return Response(
                status_code=401,
                headers={'Content-Type': 'application/json'},
                body=b'{"error": "Invalid token"}',
            )

        # Call the next handler in the chain
        return await self._wrapped.handle(request)


class RateLimitingMiddleware(Middleware):
    """Decorator: adds rate limiting."""

    def __init__(self, wrapped: HttpHandler,
                 redis_client, max_requests: int = 100,
                 window_seconds: int = 60):
        super().__init__(wrapped)
        self.redis = redis_client
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def handle(self, request: Request) -> Response:
        # BEFORE: Check rate limit
        client_ip = request.client_ip
        key = f"ratelimit:{client_ip}"

        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, self.window_seconds)

        if current > self.max_requests:
            return Response(
                status_code=429,
                headers={
                    'Content-Type': 'application/json',
                    'X-RateLimit-Limit': str(self.max_requests),
                    'X-RateLimit-Remaining': '0',
                    'Retry-After': str(self.window_seconds),
                },
                body=b'{"error": "Rate limit exceeded"}',
            )

        # Add rate limit headers to the response
        response = await self._wrapped.handle(request)

        # AFTER: Add rate limit info
        response.headers['X-RateLimit-Limit'] = str(self.max_requests)
        response.headers['X-RateLimit-Remaining'] = str(
            self.max_requests - current
        )

        return response


class LoggingMiddleware(Middleware):
    """Decorator: adds request/response logging."""

    def __init__(self, wrapped: HttpHandler, logger):
        super().__init__(wrapped)
        self.logger = logger

    async def handle(self, request: Request) -> Response:
        # BEFORE: Log the request
        start_time = time.time()
        self.logger.info(
            f"→ {request.method} {request.path} from {request.client_ip}"
        )

        # Call the next handler
        response = await self._wrapped.handle(request)

        # AFTER: Log the response with timing
        duration_ms = (time.time() - start_time) * 1000
        self.logger.info(
            f"← {response.status_code} {request.path} "
            f"({duration_ms:.0f}ms)"
        )

        # Add timing header
        response.headers['X-Response-Time'] = f"{duration_ms:.0f}ms"
        return response


class CachingMiddleware(Middleware):
    """Decorator: adds response caching."""

    def __init__(self, wrapped: HttpHandler,
                 cache_client, ttl_seconds: int = 300):
        super().__init__(wrapped)
        self.cache = cache_client
        self.ttl = ttl_seconds

    async def handle(self, request: Request) -> Response:
        # Only cache GET requests
        if request.method != 'GET':
            return await self._wrapped.handle(request)

        # Check cache
        cache_key = f"http:{request.method}:{request.path}"
        cached = await self.cache.get(cache_key)
        if cached:
            return Response(
                status_code=200,
                headers={'Content-Type': 'application/json',
                         'X-Cache': 'HIT'},
                body=cached,
            )

        # Cache miss — get from next handler
        response = await self._wrapped.handle(request)

        # Cache the response (only 200 OK)
        if response.status_code == 200:
            await self.cache.setex(
                cache_key, self.ttl, response.body
            )

        response.headers['X-Cache'] = 'MISS'
        return response


class CompressionMiddleware(Middleware):
    """Decorator: adds response compression."""

    async def handle(self, request: Request) -> Response:
        # BEFORE: Check if client accepts compression
        accept_encoding = request.headers.get('Accept-Encoding', '')

        response = await self._wrapped.handle(request)

        # AFTER: Compress if client accepts gzip
        if 'gzip' in accept_encoding and len(response.body) > 1024:
            compressed = gzip.compress(response.body)
            response.body = compressed
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = str(len(compressed))

        return response


# ── USAGE: Building middleware stacks ──────────────────────

# Per-route middleware configuration:
# Public routes: just rate limiting + logging
# Protected routes: auth + rate limiting + logging + caching
# Admin routes: auth + rate limiting + logging + audit

def build_middleware_stack(app, route_config: dict) -> dict[str, HttpHandler]:
    """Build a middleware stack for each route type."""
    stacks = {}

    for route_type, config in route_config.items():
        # Start with base handler
        handler: HttpHandler = BaseHttpHandler(app)

        # Wrap with middleware in REVERSE order (outermost first)
        # The order matters: auth before rate limit? Or rate limit before auth?
        # Typically: log → auth → rate limit → cache → handler

        if config.get('compression'):
            handler = CompressionMiddleware(handler)

        if config.get('caching'):
            handler = CachingMiddleware(handler, redis_client)

        if config.get('rate_limiting'):
            handler = RateLimitingMiddleware(handler, redis_client)

        if config.get('auth'):
            handler = AuthenticationMiddleware(handler, jwt_secret)

        if config.get('logging'):
            handler = LoggingMiddleware(handler, logger)

        stacks[route_type] = handler

    return stacks


# Configuration:
route_config = {
    'public': {
        'logging': True,
        'rate_limiting': True,
        'rate_limit': 20,  # 20 req/min for public
        'caching': True,
        'compression': True,
    },
    'protected': {
        'auth': True,
        'logging': True,
        'rate_limiting': True,
        'rate_limit': 100,  # 100 req/min for authenticated
        'caching': True,
        'compression': True,
    },
    'admin': {
        'auth': True,
        'logging': True,
        'rate_limiting': True,
        'rate_limit': 500,
        'compression': True,
        # No caching for admin — always fresh data
    },
}

middleware_stacks = build_middleware_stack(app, route_config)
```

**Decorator vs Chain of Responsibility:**

```yaml
Decorator:
  - ALL handlers always run (before and/or after)
  - Each handler adds behavior around the next
  - Handlers don't decide whether to pass the request
  - Use: adding cross-cutting concerns (logging, auth, timing)

Chain of Responsibility:
  - EACH handler decides whether to process or pass
  - A request may stop at any handler in the chain
  - Handlers can short-circuit the chain
  - Use: routing, fallback handlers, multi-step validation

DIFFERENCES:
  - Decorator: wraps (all layers execute)
  - Chain: passes (request stops at first matching handler)

  Decorator: Authentication → RateLimit → Logging → Handler
    (ALL execute: authenticate, rate-limit, log, then handle)

  Chain: Validation → Auth → Cache → Handler
    (Validation passes if valid → Auth passes if authorized →
     Cache returns if hit → Handler only if all pass)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Before/after** | Adds behavior both before and after calling wrapped handler |
| **Middleware stack** | Builds ordered middleware stacks per route with different configurations |
| **vs Chain of Responsibility** | Explains Decorator runs all layers; Chain stops at first match |
| **Production awareness** | Adds concrete middleware: JWT auth, rate limiting, caching, compression |

---

## 8. Facade Pattern

**Q:** "You're onboarding a new team member who needs to place orders in your complex e-commerce system. The order process touches 7 services with 15+ steps. Design a Facade that simplifies this. How do you test a Facade? How is Facade different from just a 'god class'?"

**What They're Really Testing:** Whether you understand Facade as a simplification layer, and can distinguish it from a god class that centralizes too much logic.

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

**Facade Pattern Solution:**

```python
# ── FACADE: Simplified interface ────────────────────────────
class OrderFacade:
    """
    Facade that simplifies the order placement process.
    Client only needs to call ONE method.
    """

    def __init__(self, inventory, pricing, promotion, tax,
                 shipping, payment, order, notification,
                 analytics, loyalty, cache):
        self.inventory = inventory
        self.pricing = pricing
        self.promotion = promotion
        self.tax = tax
        self.shipping = shipping
        self.payment = payment
        self.order = order
        self.notification = notification
        self.analytics = analytics
        self.loyalty = loyalty
        self.cache = cache

    async def place_order(self, user_id: str, items: list,
                          payment_info: dict,
                          shipping_address: dict) -> OrderResult:
        """
        Simplified interface: place an order.
        Client doesn't need to know the 14 steps.
        Doesn't need to know about 7 services.
        """
        try:
            # Validate & calculate
            await self._validate_inventory(items)
            price_summary = await self._calculate_pricing(
                items, user_id, shipping_address
            )

            # Authorize payment
            auth = await self.payment.authorize(
                user_id, price_summary.total, payment_info
            )

            # Reserve & create
            await self._reserve_inventory(items)
            order = await self.order.create(
                user_id, items, price_summary, shipping_address
            )

            # Finalize
            await self.payment.capture(auth['id'], price_summary.total)
            await self.shipping.schedule(
                order['id'], items, shipping_address
            )

            # Post-processing (async — don't block the response)
            asyncio.ensure_future(self._post_process(
                user_id, order['id'], price_summary.total
            ))

            return OrderResult(
                success=True,
                order_id=order['id'],
                total=price_summary.total,
                message="Order placed successfully",
            )

        except Exception as e:
            # Compensation logic is HERE, not in client code
            await self._compensate(order_id=order.get('id'))
            return OrderResult(
                success=False,
                error=str(e),
            )

    async def _validate_inventory(self, items: list):
        """Subsystem validation — hidden from client."""
        for item in items:
            if not await self.inventory.is_available(item['id'], item['qty']):
                raise InventoryError(f"Item {item['id']} not available")

    async def _calculate_pricing(self, items: list, user_id: str,
                                  shipping_address: dict) -> PriceSummary:
        """Complex pricing calculation — hidden from client."""
        subtotal = sum(
            await self.pricing.get_price(item['id']) * item['qty']
            for item in items
        )
        promo = await self.promotion.get_applicable_promotions(user_id, items)
        discount = await self.promotion.calculate_discount(promo, subtotal)
        tax = await self.tax.calculate_tax(shipping_address, subtotal - discount)
        shipping = await self.shipping.calculate_cost(items, shipping_address)
        return PriceSummary(
            subtotal=subtotal,
            discount=discount,
            tax=tax,
            shipping=shipping,
            total=subtotal - discount + tax + shipping,
        )

    async def _reserve_inventory(self, items: list):
        """Bulk inventory reservation — hidden from client."""
        for item in items:
            await self.inventory.reserve(item['id'], item['qty'])

    async def _post_process(self, user_id: str, order_id: str, total: float):
        """Post-order tasks — fire and forget."""
        await asyncio.gather(
            self.notification.send_order_confirmation(user_id, order_id),
            self.analytics.track_order(user_id, order_id, total),
            self.loyalty.add_points(user_id, total),
            self.cache.invalidate(f"user:{user_id}:cart"),
            return_exceptions=True,  # Don't fail if one task fails
        )

    async def _compensate(self, order_id: str = None):
        """Compensation logic — hidden from client."""
        if order_id:
            await self.order.cancel(order_id)
        # Log failure for monitoring
        logging.error("Order placement failed, compensations executed")


# ── CLIENT CODE ────────────────────────────────────────────

# Client only needs to know about OrderFacade!
async def handle_checkout(request):
    facade = OrderFacade(
        inventory=inventory_service,
        pricing=pricing_service,
        # ... inject all 11 dependencies
    )

    result = await facade.place_order(
        user_id=request.user_id,
        items=request.cart_items,
        payment_info=request.payment,
        shipping_address=request.shipping_address,
    )

    return jsonify(result.to_dict())
```

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

### Answer

**Command Pattern for Undoable Text Editor:**

```python
# ── COMMAND INTERFACE ──────────────────────────────────────
from abc import ABC, abstractmethod
from dataclasses import dataclass

class Command(ABC):
    """Represents an operation that can be executed and undone."""

    @abstractmethod
    def execute(self):
        """Execute the command."""
        pass

    @abstractmethod
    def undo(self):
        """Undo the command."""
        pass

    @abstractmethod
    def is_reversible(self) -> bool:
        """Can this command be undone?"""
        pass


# ── RECEIVER: The text editor state ────────────────────────
@dataclass
class EditorState:
    """Immutable snapshot of editor state for undo/redo."""
    content: str
    cursor_position: int
    selection: tuple[int, int] | None = None


class TextEditor:
    """Receiver — the actual object that performs operations."""

    def __init__(self):
        self.content = ""
        self.cursor_position = 0

    def insert(self, position: int, text: str):
        """Insert text at position."""
        self.content = self.content[:position] + text + self.content[position:]
        self.cursor_position = position + len(text)

    def delete(self, position: int, length: int) -> str:
        """Delete text and return the deleted text (for undo)."""
        deleted = self.content[position:position + length]
        self.content = self.content[:position] + self.content[position + length:]
        self.cursor_position = position
        return deleted

    def replace(self, position: int, length: int, new_text: str) -> str:
        """Replace text and return the replaced text (for undo)."""
        replaced = self.content[position:position + length]
        self.content = self.content[:position] + new_text + self.content[position + length:]
        self.cursor_position = position + len(new_text)
        return replaced


# ── CONCRETE COMMANDS ──────────────────────────────────────

class InsertCommand(Command):
    """Inserts text. Can be undone by deleting the same text."""

    def __init__(self, editor: TextEditor, position: int, text: str):
        self.editor = editor
        self.position = position
        self.text = text

    def execute(self):
        self.editor.insert(self.position, self.text)

    def undo(self):
        # Undo insert = delete the same text
        self.editor.delete(self.position, len(self.text))

    def is_reversible(self):
        return True


class DeleteCommand(Command):
    """Deletes text. Can be undone by re-inserting the deleted text."""

    def __init__(self, editor: TextEditor, position: int, length: int):
        self.editor = editor
        self.position = position
        self.length = length
        self._deleted_text = None  # Store for undo

    def execute(self):
        self._deleted_text = self.editor.delete(self.position, self.length)

    def undo(self):
        # Undo delete = re-insert the deleted text
        if self._deleted_text:
            self.editor.insert(self.position, self._deleted_text)

    def is_reversible(self):
        return True


class ReplaceCommand(Command):
    """Replaces text. Can be undone by reversing the replacement."""

    def __init__(self, editor: TextEditor, position: int,
                 length: int, new_text: str):
        self.editor = editor
        self.position = position
        self.length = length
        self.new_text = new_text
        self._replaced_text = None

    def execute(self):
        self._replaced_text = self.editor.replace(
            self.position, self.length, self.new_text
        )

    def undo(self):
        # Undo replace = replace new text with old text
        if self._replaced_text:
            self.editor.replace(
                self.position, len(self.new_text), self._replaced_text
            )

    def is_reversible(self):
        return True


class SaveCommand(Command):
    """Saves the file. Can NOT be undone (already written to disk)."""

    def __init__(self, editor: TextEditor, file_path: str):
        self.editor = editor
        self.file_path = file_path

    def execute(self):
        with open(self.file_path, 'w') as f:
            f.write(self.editor.content)
        print(f"Saved to {self.file_path}")

    def undo(self):
        raise NotImplementedError("Save cannot be undone")

    def is_reversible(self):
        return False


# ── INVOKER: Command history with undo/redo ───────────────
class CommandHistory:
    """Manages command execution with undo/redo capability."""

    def __init__(self, max_history: int = 1000):
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._max_history = max_history
        self._macro_recording = False
        self._macro_commands: list[Command] = []

    def execute(self, command: Command):
        """Execute a command and add to history."""
        command.execute()
        self._undo_stack.append(command)
        self._redo_stack.clear()  # New action invalidates redo

        # Keep history bounded
        if len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)

    def undo(self) -> bool:
        """Undo the last command. Returns False if nothing to undo."""
        if not self._undo_stack:
            return False

        command = self._undo_stack.pop()
        if not command.is_reversible():
            print(f"Warning: {type(command).__name__} cannot be undone")
            return False

        command.undo()
        self._redo_stack.append(command)
        return True

    def redo(self) -> bool:
        """Redo the last undone command."""
        if not self._redo_stack:
            return False

        command = self._redo_stack.pop()
        command.execute()
        self._undo_stack.append(command)
        return True

    def start_macro(self):
        """Start recording commands into a macro."""
        self._macro_recording = True
        self._macro_commands = []

    def stop_macro(self) -> Command:
        """Stop recording and return the macro as a command."""
        self._macro_recording = False
        macro = MacroCommand(self._macro_commands)
        self._macro_commands = []
        return macro


class MacroCommand(Command):
    """A command composed of multiple sub-commands (macro)."""

    def __init__(self, commands: list[Command]):
        self.commands = commands

    def execute(self):
        for cmd in self.commands:
            cmd.execute()

    def undo(self):
        # Undo in REVERSE order
        for cmd in reversed(self.commands):
            if cmd.is_reversible():
                cmd.undo()

    def is_reversible(self):
        return all(cmd.is_reversible() for cmd in self.commands)


# ── USAGE ──────────────────────────────────────────────────

# Editor setup
editor = TextEditor()
history = CommandHistory()

# Normal editing
history.execute(InsertCommand(editor, 0, "Hello, World!"))
print(editor.content)  # "Hello, World!"

history.execute(DeleteCommand(editor, 5, 7))
print(editor.content)  # "Hello!"

# Undo
history.undo()
print(editor.content)  # "Hello, World!"

# Redo
history.redo()
print(editor.content)  # "Hello!"

# Macro recording
history.start_macro()
history.execute(InsertCommand(editor, 0, "Start: "))
history.execute(InsertCommand(editor, len(editor.content), " End"))
macro = history.stop_macro()

# Execute macro as a single command
history.execute(macro)
print(editor.content)  # "Start: Hello! End"

# Undo entire macro (undoes all commands in reverse)
history.undo()
print(editor.content)  # "Hello!"
```

**Command Queue for Async Processing:**

```python
# ── COMMAND QUEUE (for async/remote execution) ────────────
import asyncio
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
                queued.command.execute()
                queued.status = "completed"
                logging.info(f"{name}: {queued.command_type} completed")

            except Exception as e:
                queued.retry_count += 1
                if queued.retry_count < queued.max_retries:
                    # Re-enqueue with exponential backoff
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

### Answer

**State Pattern for Vending Machine:**

```python
# ── CONTEXT ────────────────────────────────────────────────
class VendingMachine:
    """
    Context: maintains current state and delegates behavior.
    """

    def __init__(self):
        self.balance = 0.0
        self.selected_item = None
        self.inventory = {}  # {item_id: {'price': float, 'quantity': int}}

        # All possible states
        self.idle_state = IdleState(self)
        self.selecting_state = SelectingState(self)
        self.processing_payment_state = ProcessingPaymentState(self)
        self.dispensing_state = DispensingState(self)
        self.out_of_stock_state = OutOfStockState(self)
        self.maintenance_state = MaintenanceState(self)

        # Start in idle state
        self.current_state = self.idle_state
        self._reset_context()

    def _reset_context(self):
        """Reset context variables (not state)."""
        self.balance = 0.0
        self.selected_item = None

    # ── Delegate to current state ──────────────────────────
    def insert_money(self, amount: float):
        self.current_state.insert_money(amount)

    def select_item(self, item_id: str):
        self.current_state.select_item(item_id)

    def dispense(self):
        self.current_state.dispense()

    def cancel(self):
        self.current_state.cancel()

    def refill(self, inventory: dict):
        self.current_state.refill(inventory)

    def enter_maintenance(self):
        self.current_state = self.maintenance_state

    def exit_maintenance(self):
        self.current_state = self.idle_state

    def change_state(self, new_state: 'VendingMachineState'):
        """Transition to a new state."""
        print(f"State: {self.current_state.__class__.__name__} → "
              f"{new_state.__class__.__name__}")
        self.current_state = new_state


# ── STATE INTERFACE ────────────────────────────────────────
from abc import ABC, abstractmethod

class VendingMachineState(ABC):
    """Interface for all vending machine states."""

    def __init__(self, machine: VendingMachine):
        self.machine = machine

    @abstractmethod
    def insert_money(self, amount: float):
        """Insert money into the machine."""
        pass

    @abstractmethod
    def select_item(self, item_id: str):
        """Select an item to purchase."""
        pass

    @abstractmethod
    def dispense(self):
        """Dispense the selected item."""
        pass

    @abstractmethod
    def cancel(self):
        """Cancel the current transaction and refund."""
        pass

    @abstractmethod
    def refill(self, inventory: dict):
        """Refill the machine's inventory."""
        pass


# ── CONCRETE STATES ────────────────────────────────────────

class IdleState(VendingMachineState):
    """Machine is waiting for a customer."""

    def insert_money(self, amount: float):
        self.machine.balance += amount
        print(f"Inserted ${amount:.2f}. Balance: ${self.machine.balance:.2f}")
        self.machine.change_state(self.machine.selecting_state)

    def select_item(self, item_id: str):
        print("Please insert money first")

    def dispense(self):
        print("Please insert money and select an item first")

    def cancel(self):
        print("Nothing to cancel")

    def refill(self, inventory: dict):
        self.machine.inventory.update(inventory)
        print(f"Refilled inventory with {len(inventory)} items")
        if not self.machine.inventory:
            self.machine.change_state(self.machine.out_of_stock_state)


class SelectingState(VendingMachineState):
    """Customer has inserted money and is selecting an item."""

    def insert_money(self, amount: float):
        self.machine.balance += amount
        print(f"Inserted ${amount:.2f}. Balance: ${self.machine.balance:.2f}")

    def select_item(self, item_id: str):
        if item_id not in self.machine.inventory:
            print(f"Item {item_id} not found")
            return

        item = self.machine.inventory[item_id]
        if item['quantity'] <= 0:
            print(f"Item {item_id} is out of stock")
            return

        if item['price'] > self.machine.balance:
            print(f"Price: ${item['price']:.2f}. "
                  f"Insufficient balance: ${self.machine.balance:.2f}")
            return

        self.machine.selected_item = item_id
        print(f"Selected {item_id} — ${item['price']:.2f}")
        self.machine.change_state(self.machine.processing_payment_state)

    def dispense(self):
        print("Please select an item first")

    def cancel(self):
        print(f"Refunding ${self.machine.balance:.2f}")
        self.machine.balance = 0.0
        self.machine.change_state(self.machine.idle_state)

    def refill(self, inventory: dict):
        print("Cannot refill during active transaction")


class ProcessingPaymentState(VendingMachineState):
    """Payment is being processed."""

    def insert_money(self, amount: float):
        self.machine.balance += amount
        print(f"Inserted ${amount:.2f}. Balance: ${self.machine.balance:.2f}")

    def select_item(self, item_id: str):
        print(f"Already selected {self.machine.selected_item}. "
              f"Dispensing in progress")

    def dispense(self):
        item = self.machine.inventory[self.machine.selected_item]
        change = self.machine.balance - item['price']

        # Process payment
        print(f"Charging ${item['price']:.2f}")
        self.machine.inventory[self.machine.selected_item]['quantity'] -= 1
        self.machine.balance = 0.0

        print(f"Dispensing {self.machine.selected_item}...")
        self.machine.change_state(self.machine.dispensing_state)

        if change > 0:
            print(f"Returning change: ${change:.2f}")

    def cancel(self):
        print(f"Cancelling. Refunding ${self.machine.balance:.2f}")
        self.machine.balance = 0.0
        self.machine.selected_item = None
        self.machine.change_state(self.machine.idle_state)

    def refill(self, inventory: dict):
        print("Cannot refill during active transaction")


class DispensingState(VendingMachineState):
    """Item is being dispensed (possibly with change)."""

    def insert_money(self, amount: float):
        print("Please wait, dispensing in progress")

    def select_item(self, item_id: str):
        print("Please wait, dispensing in progress")

    def dispense(self):
        print("Already dispensing")

    def cancel(self):
        print("Too late, item is being dispensed")

    def refill(self, inventory: dict):
        print("Cannot refill during active transaction")

    def on_dispense_complete(self):
        """Called when dispense is done (simulated by timer)."""
        self.machine.selected_item = None

        # Check if machine is out of stock
        all_empty = all(
            item['quantity'] <= 0
            for item in self.machine.inventory.values()
        )
        if all_empty:
            self.machine.change_state(self.machine.out_of_stock_state)
        else:
            self.machine.change_state(self.machine.idle_state)


class OutOfStockState(VendingMachineState):
    """All items are sold out."""

    def insert_money(self, amount: float):
        print("Machine is out of stock. Money returned.")
        # Return the money immediately

    def select_item(self, item_id: str):
        print("Machine is out of stock")

    def dispense(self):
        print("Machine is out of stock")

    def cancel(self):
        print("Nothing to cancel")

    def refill(self, inventory: dict):
        self.machine.inventory.update(inventory)
        print(f"Refilled! {len(inventory)} items added.")
        self.machine.change_state(self.machine.idle_state)


class MaintenanceState(VendingMachineState):
    """Maintenance mode — technician can access internals."""

    def insert_money(self, amount: float):
        print("Machine is in maintenance mode")

    def select_item(self, item_id: str):
        print("Machine is in maintenance mode")

    def dispense(self):
        print("Machine is in maintenance mode")

    def cancel(self):
        print("Machine is in maintenance mode")

    def refill(self, inventory: dict):
        self.machine.inventory.update(inventory)
        print(f"Refilled! {len(inventory)} items.")

    def exit_maintenance(self):
        """Technician exits maintenance mode."""
        all_empty = all(
            item['quantity'] <= 0
            for item in self.machine.inventory.values()
        )
        if all_empty:
            self.machine.change_state(self.machine.out_of_stock_state)
        else:
            self.machine.change_state(self.machine.idle_state)
```

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
  - States know about other states (transitions)
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

---

## 11. Template Method Pattern

**Q:** "Your data pipeline processes files from different sources (S3, FTP, Local) through the same stages: download → validate → transform → load. 80% of the code is the same, 20% varies per source. Design this using Template Method. What are the hook methods? When would you prefer Strategy over Template Method?"

**What They're Really Testing:** Whether you understand Template Method as a way to reuse common algorithm structure while allowing subclasses to override specific steps, and can identify when Strategy or composition is a better fit.

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
        Template method: defines the algorithm skeleton.
        Steps:
          1. Download (abstract — subclass provides)
          2. Validate (abstract — subclass provides)
          3. Transform (abstract or default)
          4. Load (abstract — subclass provides)
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

    def __init__(self, bucket: str, aws_access_key: str,
                 aws_secret_key: str, region: str = 'us-east-1'):
        self.bucket = bucket
        self.access_key = aws_access_key
        self.secret_key = aws_secret_key
        self.region = region
        self.s3_client = None

    def _connect(self):
        import boto3
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )
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
        cursor = conn.cursor()

        for row in transformed_data['rows']:
            cursor.execute(
                "INSERT INTO data (columns) VALUES (...)",
                row,
            )

        conn.commit()
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
        from ftplib import FTP
        self.ftp = FTP(self.host)
        self.ftp.login(self.username, self.password)
        logging.info(f"Connected to FTP: {self.host}")

    def _download(self, source_path: str) -> bytes:
        import io
        buffer = io.BytesIO()
        self.ftp.retrbinary(f"RETR {source_path}", buffer.write)
        return buffer.getvalue()

    def _validate(self, raw_data: bytes) -> dict:
        # XML validation for FTP sources
        import xml.etree.ElementTree as ET
        root = ET.fromstring(raw_data)
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
        cursor = conn.cursor()

        for row in transformed_data['rows']:
            cursor.execute(
                "INSERT INTO ftp_data (columns) VALUES (...)",
                row,
            )

        conn.commit()
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

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pattern identification** | Can identify patterns from code structure (smells) |
| **Decision framework** | Has a structured approach to choosing patterns |
| **Misuse detection** | Can identify when patterns are applied incorrectly |
| **Simplicity first** | Starts with "no pattern" and adds patterns only when justified |

---

> *Master these patterns not by memorizing UML diagrams, but by understanding the underlying principles: encapsulate what varies, program to interfaces, favor composition over inheritance, and follow the Single Responsibility Principle. Patterns are solutions to recurring problems — not recipes to be followed blindly.*

