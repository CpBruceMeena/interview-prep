# 🧠 Pub-Sub System LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![Class Diagram](pub-sub-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

How are messages delivered? (Sync, async, reliable?) Is there ordering/priority? How do subscribers register? What happens if a subscriber fails?

## Phase 1: Identify the Nouns

> *"Publishers send messages to topics. Subscribers receive messages from topics they've subscribed to."*

| Noun | Decision | Why |
|------|----------|-----|
| Message | Regular Class | Has payload, topic, priority, headers |
| MessageQueue | Regular Class | Stores and orders pending messages |
| Subscription | Regular Class | Links a subscriber to a topic |
| Topic | Regular Class | Manages subscribers + message queue for a topic |
| MessageBroker | Facade | Main entry point |
| Subscriber | ABC | Observer pattern |
| DeliveryStrategy | ABC | Strategy pattern |
| MessagePriority | Enum | LOW, NORMAL, HIGH, CRITICAL |

## Phase 2: Enums First

```python
class MessagePriority(Enum):
    LOW = 0; NORMAL = 1; HIGH = 2; CRITICAL = 3
```

Note the integer values — they enable priority-based sorting in the queue.

## Phase 3: dataclass vs `__init__`

- **`Message`**: Regular `__init__` — has behavior (add_header, get_header) and auto-generated ID
- **`MessageQueue`**: Regular — complex state with thread-safe operations
- **`Topic`**: Regular — manages subscribers + queue
- **`Subscription`**: Regular — links topic + subscriber
- **Subscribers**: Regular — each implements `on_message()`

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Store message | `MessageQueue.enqueue()` | Queue owns ordering |
| Deliver to subscriber | `Subscription.deliver()` | Subscription knows who to deliver to |
| Subscribe/unsubscribe | `Topic.subscribe()`/`unsubscribe()` | Topic manages its subscribers |
| Route message to topic | `MessageBroker.publish()` | Broker knows all topics |
| Choose delivery method | `DeliveryStrategy.deliver()` | Strategy pattern |

## Phase 5: Observer + Strategy Patterns

**Observer (core pattern):**
```python
class Subscriber(ABC):
    def on_message(self, message: Message): pass

class ConsoleSubscriber(Subscriber):  # Prints to console
class FilteringSubscriber(Subscriber): # Decorator pattern on subscriber
```

**Strategy (delivery):**
```python
class DeliveryStrategy(ABC):
    def deliver(self, subscription, message) -> bool

class DirectDelivery(DeliveryStrategy):     # Synchronous
class AsyncDelivery(DeliveryStrategy):      # Thread-based
class ReliableDelivery(DeliveryStrategy):   # With retries
```

## Phase 6: Decorator Pattern on Subscribers

```python
class FilteringSubscriber(Subscriber):
    """Wraps another subscriber, filters messages before passing on."""
    def __init__(self, subscriber: Subscriber, filter_fn):
        self._subscriber = subscriber
        self._filter = filter_fn
    
    def on_message(self, message):
        if self._filter(message):
            self._subscriber.on_message(message)
```

This is composition over inheritance — wrapping behavior.

## Phase 7: Thread Safety

The `MessageQueue` uses a lock for thread-safe operations. The `AsyncDelivery` creates new threads for each delivery.

## Phase 8: Quick Checklist

✅ **Observer Pattern:** Subscribers observe topics
✅ **Strategy Pattern:** Delivery methods are swappable
✅ **Decorator Pattern:** FilteringSubscriber wraps behavior
✅ **SRP:** MessageQueue, Topic, Subscription each own their concern
✅ **Thread-safety:** Locks protect shared state
