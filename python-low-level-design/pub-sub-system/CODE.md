# Pub-Sub System — Implementation

> Python implementation of the Pub-Sub System system following SOLID principles and design patterns.

```python
"""
Pub-Sub Messaging System - Low Level Design
--------------------------------------------
Design Principles: SOLID, Observer Pattern, Strategy Pattern
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Set, Callable, Any
from datetime import datetime
import threading
import uuid


class MessagePriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class Message:
    """Represents a message in the pub-sub system"""

    def __init__(self, topic: str, payload: Any,
                 priority: MessagePriority = MessagePriority.NORMAL,
                 message_id: Optional[str] = None):
        self._message_id = message_id or str(uuid.uuid4())
        self._topic = topic
        self._payload = payload
        self._priority = priority
        self._timestamp = datetime.now()
        self._headers: Dict[str, str] = {}

    @property
    def message_id(self) -> str:
        return self._message_id

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def payload(self) -> Any:
        return self._payload

    @property
    def priority(self) -> MessagePriority:
        return self._priority

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    def add_header(self, key: str, value: str) -> None:
        self._headers[key] = value

    def get_header(self, key: str) -> Optional[str]:
        return self._headers.get(key)

    def __str__(self) -> str:
        return f"Msg[{self._message_id[:8]}]({self._topic})"


# --- Subscriber (Observer Pattern) ---

class Subscriber(ABC):
    """Interface for subscribers"""

    @abstractmethod
    def on_message(self, message: Message) -> None:
        pass

    @property
    @abstractmethod
    def subscriber_id(self) -> str:
        pass


class ConsoleSubscriber(Subscriber):
    """Prints messages to console"""

    def __init__(self, name: str):
        self._name = name
        self._id = str(uuid.uuid4())

    @property
    def subscriber_id(self) -> str:
        return self._id

    def on_message(self, message: Message) -> None:
        print(f"  [{self._name}] Received: {message} -> {message.payload}")

    def __str__(self) -> str:
        return self._name


class FilteringSubscriber(Subscriber):
    """Decorator pattern: only passes messages matching a predicate"""

    def __init__(self, subscriber: Subscriber, filter_fn: Callable[[Message], bool]):
        self._subscriber = subscriber
        self._filter = filter_fn
        self._id = subscriber.subscriber_id

    @property
    def subscriber_id(self) -> str:
        return self._id

    def on_message(self, message: Message) -> None:
        if self._filter(message):
            self._subscriber.on_message(message)


# --- Subscription (SRP) ---

class Subscription:
    """Single Responsibility: Manages the relationship between topic and subscriber"""

    def __init__(self, topic: str, subscriber: Subscriber):
        self._topic = topic
        self._subscriber = subscriber
        self._created_at = datetime.now()

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def subscriber(self) -> Subscriber:
        return self._subscriber

    def deliver(self, message: Message) -> None:
        self._subscriber.on_message(message)


# --- Message Queue (SRP) ---

class MessageQueue:
    """Single Responsibility: Stores and orders messages"""

    def __init__(self):
        self._queue: List[Message] = []
        self._lock = threading.Lock()

    def enqueue(self, message: Message) -> None:
        with self._lock:
            self._queue.append(message)
            # Sort by priority (higher priority first)
            self._queue.sort(key=lambda m: m.priority.value, reverse=True)

    def dequeue(self) -> Optional[Message]:
        with self._lock:
            if not self._queue:
                return None
            return self._queue.pop(0)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    def peek(self) -> Optional[Message]:
        with self._lock:
            return self._queue[0] if self._queue else None


# --- Delivery Strategy (Strategy Pattern - OCP) ---

class DeliveryStrategy(ABC):
    """Interface Segregation: Delivery mechanism"""

    @abstractmethod
    def deliver(self, subscription: Subscription, message: Message) -> bool:
        pass


class DirectDelivery(DeliveryStrategy):
    """Deliver immediately to subscriber"""

    def deliver(self, subscription: Subscription, message: Message) -> bool:
        try:
            subscription.deliver(message)
            return True
        except Exception as e:
            print(f"  Delivery failed: {e}")
            return False


class AsyncDelivery(DeliveryStrategy):
    """Deliver asynchronously in a separate thread"""

    def deliver(self, subscription: Subscription, message: Message) -> bool:
        thread = threading.Thread(target=subscription.deliver, args=(message,))
        thread.daemon = True
        thread.start()
        return True


class ReliableDelivery(DeliveryStrategy):
    """Retry delivery on failure"""

    def __init__(self, max_retries: int = 3, base_delay: float = 0.1):
        self._max_retries = max_retries
        self._base_delay = base_delay

    def deliver(self, subscription: Subscription, message: Message) -> bool:
        import time
        for attempt in range(self._max_retries):
            try:
                subscription.deliver(message)
                return True
            except Exception as e:
                if attempt < self._max_retries - 1:
                    sleep_time = self._base_delay * (2 ** attempt)
                    print(f"  Retry {attempt + 1}/{self._max_retries} in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                else:
                    print(f"  Delivery failed after {self._max_retries} attempts: {e}")
        return False


# --- Broker / Topic Manager (Facade / SRP) ---

class Topic:
    """Represents a topic with its subscribers"""

    def __init__(self, name: str):
        self._name = name
        self._subscribers: Dict[str, Subscription] = {}
        self._message_queue = MessageQueue()

    @property
    def name(self) -> str:
        return self._name

    @property
    def message_queue(self) -> MessageQueue:
        return self._message_queue

    def subscribe(self, subscriber: Subscriber) -> None:
        sub = Subscription(self._name, subscriber)
        self._subscribers[subscriber.subscriber_id] = sub
        print(f"  Subscriber '{subscriber}' subscribed to '{self._name}'")

    def unsubscribe(self, subscriber_id: str) -> None:
        sub = self._subscribers.pop(subscriber_id, None)
        if sub:
            print(f"  Subscriber '{sub.subscriber}' unsubscribed from '{self._name}'")

    def publish(self, message: Message) -> None:
        self._message_queue.enqueue(message)

    def deliver_all(self, delivery_strategy: DeliveryStrategy) -> int:
        """Deliver all queued messages. Returns count delivered."""
        delivered = 0
        while True:
            message = self._message_queue.dequeue()
            if not message:
                break
            for sub in list(self._subscribers.values()):
                if delivery_strategy.deliver(sub, message):
                    delivered += 1
        return delivered

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class MessageBroker:
    """Facade for the entire pub-sub system"""

    def __init__(self, name: str = "DefaultBroker"):
        self._name = name
        self._topics: Dict[str, Topic] = {}
        self._delivery_strategy: DeliveryStrategy = DirectDelivery()
        self._lock = threading.Lock()

    def create_topic(self, topic_name: str) -> Topic:
        with self._lock:
            if topic_name not in self._topics:
                self._topics[topic_name] = Topic(topic_name)
                print(f"Topic '{topic_name}' created")
            return self._topics[topic_name]

    def delete_topic(self, topic_name: str) -> None:
        with self._lock:
            self._topics.pop(topic_name, None)
            print(f"Topic '{topic_name}' deleted")

    def subscribe(self, topic_name: str, subscriber: Subscriber) -> None:
        topic = self._topics.get(topic_name)
        if not topic:
            topic = self.create_topic(topic_name)
        topic.subscribe(subscriber)

    def unsubscribe(self, topic_name: str, subscriber_id: str) -> None:
        topic = self._topics.get(topic_name)
        if topic:
            topic.unsubscribe(subscriber_id)

    def publish(self, topic_name: str, payload: Any,
                priority: MessagePriority = MessagePriority.NORMAL) -> Optional[str]:
        topic = self._topics.get(topic_name)
        if not topic:
            print(f"Topic '{topic_name}' does not exist")
            return None

        message = Message(topic_name, payload, priority)
        topic.publish(message)
        return message.message_id

    def flush(self) -> Dict[str, int]:
        """Deliver all pending messages. Returns topic -> delivered count."""
        results = {}
        for topic_name, topic in self._topics.items():
            count = topic.deliver_all(self._delivery_strategy)
            if count > 0:
                results[topic_name] = count
        return results

    def set_delivery_strategy(self, strategy: DeliveryStrategy) -> None:
        self._delivery_strategy = strategy

    def get_topic(self, topic_name: str) -> Optional[Topic]:
        return self._topics.get(topic_name)


# --- Demo ---

def demo():
    print("=== Pub-Sub Messaging System Demo ===")
    print("=" * 50)

    # Create broker
    broker = MessageBroker("MainBroker")
    broker.set_delivery_strategy(DirectDelivery())

    # Create topics
    broker.create_topic("orders")
    broker.create_topic("notifications")
    broker.create_topic("analytics")

    # Create subscribers
    email_service = ConsoleSubscriber("EmailService")
    sms_service = ConsoleSubscriber("SMSService")
    analytics_service = ConsoleSubscriber("AnalyticsService")
    logging_service = ConsoleSubscriber("Logger")

    # Subscribe to topics
    broker.subscribe("orders", email_service)
    broker.subscribe("orders", logging_service)
    broker.subscribe("notifications", sms_service)
    broker.subscribe("notifications", logging_service)
    broker.subscribe("analytics", analytics_service)

    # Publish messages
    print("\n--- Publishing Messages ---")
    broker.publish("orders", {"order_id": 123, "item": "Laptop", "amount": 1500.00})
    broker.publish("notifications", {"user_id": 456, "message": "Your order has shipped!"})
    broker.publish("analytics", {"event": "page_view", "page": "/checkout", "duration": 45.2})

    # Deliver all
    print("\n--- Delivering ---")
    results = broker.flush()
    for topic, count in results.items():
        print(f"  {topic}: {count} messages delivered")

    # Advanced: Filtered subscriber
    print("\n--- Filtered Subscriber (Priority > NORMAL) ---")
    high_priority_only = FilteringSubscriber(
        ConsoleSubscriber("UrgentHandler"),
        lambda m: m.priority.value >= MessagePriority.HIGH.value
    )
    broker.subscribe("orders", high_priority_only)
    broker.publish("orders", {"order_id": 789, "type": "premium"}, MessagePriority.HIGH)
    broker.flush()

    # Async delivery demo
    print("\n--- Async Delivery Demo ---")
    broker.set_delivery_strategy(AsyncDelivery())
    broker.publish("notifications", {"bulk": True, "count": 1000})
    broker.flush()
    import time
    time.sleep(0.5)  # Wait for async delivery


if __name__ == "__main__":
    demo()
```

---

## ▶️ How to Run

```bash
cd low-level-design/pub-sub-system
python pub_sub_system.py
```

## 🧩 Design Patterns

See the [Interview Questions](INTERVIEW_QUESTIONS.md) for a detailed breakdown of design patterns and SOLID principles applied in this implementation.
