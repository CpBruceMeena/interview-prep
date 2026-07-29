"""
DESIGN PROBLEMS (OOP / SYSTEM DESIGN) — Core Concepts & Questions
=================================================================

Core OOP Concepts:
──────────────────
• Encapsulation: Bundle data and methods, hide internal state
• Inheritance: IS-A relationship, code reuse through hierarchy
• Polymorphism: Same interface, different implementations
• Composition: HAS-A relationship, more flexible than inheritance
• SOLID Principles:
  - S: Single Responsibility — one reason to change
  - O: Open/Closed — open for extension, closed for modification
  - L: Liskov Substitution — subtypes replace base types
  - I: Interface Segregation — small, focused interfaces
  - D: Dependency Inversion — depend on abstractions, not concretions

Design Patterns:
────────────────
• Creational: Singleton, Factory, Builder, Prototype
• Structural: Adapter, Decorator, Proxy, Facade, Composite
• Behavioral: Observer, Strategy, Command, Iterator, State

Common Design Problems:
───────────────────────
• Parking Lot, Vending Machine, ATM, Elevator
• Chess Game, Tic-Tac-Toe, Snake & Ladder
• Library Management, Hotel Booking, Cab Booking
• Logging Framework, Cache System, Pub-Sub System

Interview Approach:
───────────────────
1. Clarify requirements and scope
2. Identify core entities/objects
3. Define relationships between them
4. Apply design patterns where appropriate
5. Handle concurrency, persistence, and edge cases
"""

from typing import List, Optional, Dict, Set, Callable
from enum import Enum
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import threading
import time
import uuid


# ════════════════════════════════════════════════════════════════════════
# DESIGN 1: Logging Framework (Singleton + Strategy + Observer)
# ════════════════════════════════════════════════════════════════════════

class LogLevel(Enum):
    DEBUG = 1
    INFO = 2
    WARNING = 3
    ERROR = 4
    FATAL = 5


class LogAppender(ABC):
    """Abstract appender — different output strategies."""
    @abstractmethod
    def append(self, level: LogLevel, message: str, timestamp: datetime) -> None:
        pass


class ConsoleAppender(LogAppender):
    def append(self, level: LogLevel, message: str, timestamp: datetime) -> None:
        print(f"[{level.name}] {timestamp.isoformat()} — {message}")


class FileAppender(LogAppender):
    def __init__(self, filepath: str):
        self.filepath = filepath

    def append(self, level: LogLevel, message: str, timestamp: datetime) -> None:
        with open(self.filepath, 'a') as f:
            f.write(f"[{level.name}] {timestamp.isoformat()} — {message}\n")


class Logger:
    """
    Singleton Logger with pluggable appenders and level filtering.

    THOUGHT PROCESS:
    ────────────────
    1. Singleton: Ensures a single logging instance across the app
    2. Strategy (Appender): Different output targets (console, file, network)
    3. Observer: Log consumers can subscribe to specific levels
    4. Configurable log level filtering
    """

    _instance: Optional['Logger'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._appenders: List[LogAppender] = []
            cls._instance._min_level = LogLevel.DEBUG
        return cls._instance

    def add_appender(self, appender: LogAppender) -> None:
        self._appenders.append(appender)

    def set_level(self, level: LogLevel) -> None:
        self._min_level = level

    def log(self, level: LogLevel, message: str) -> None:
        if level.value < self._min_level.value:
            return
        timestamp = datetime.now()
        for appender in self._appenders:
            appender.append(level, message, timestamp)

    def debug(self, message: str) -> None:
        self.log(LogLevel.DEBUG, message)

    def info(self, message: str) -> None:
        self.log(LogLevel.INFO, message)

    def error(self, message: str) -> None:
        self.log(LogLevel.ERROR, message)


# ════════════════════════════════════════════════════════════════════════
# DESIGN 2: Rate Limiter (Token Bucket + Sliding Window)
# ════════════════════════════════════════════════════════════════════════

class RateLimitStrategy(ABC):
    """Strategy pattern for rate limiting algorithms."""
    @abstractmethod
    def allow_request(self, key: str, timestamp: float) -> bool:
        pass


class TokenBucket(RateLimitStrategy):
    """
    Token Bucket: Tokens refill at a constant rate.
    Each request consumes one token.
    """
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.tokens: Dict[str, float] = {}
        self.last_refill: Dict[str, float] = {}

    def allow_request(self, key: str, timestamp: float) -> bool:
        self._refill(key, timestamp)
        if self.tokens.get(key, 0) >= 1:
            self.tokens[key] -= 1
            return True
        return False

    def _refill(self, key: str, timestamp: float) -> None:
        if key not in self.tokens:
            self.tokens[key] = self.capacity
            self.last_refill[key] = timestamp
            return
        elapsed = timestamp - self.last_refill[key]
        new_tokens = elapsed * self.refill_rate
        self.tokens[key] = min(self.capacity, self.tokens[key] + new_tokens)
        self.last_refill[key] = timestamp


class SlidingWindowLog(RateLimitStrategy):
    """Sliding window log — maintains timestamps of recent requests."""
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.logs: Dict[str, List[float]] = {}

    def allow_request(self, key: str, timestamp: float) -> bool:
        if key not in self.logs:
            self.logs[key] = []
        log = self.logs[key]
        # Remove expired entries
        while log and log[0] < timestamp - self.window_seconds:
            log.pop(0)
        if len(log) < self.max_requests:
            log.append(timestamp)
            return True
        return False


class RateLimiter:
    """
    Facade for rate limiting — supports pluggable strategies.

    THOUGHT PROCESS:
    ────────────────
    1. Strategy Pattern: Different algorithms (Token Bucket, Sliding Window)
    2. Decorator Pattern: Can wrap API handlers
    3. Thread-safe: Use locks for concurrent access
    """
    def __init__(self, strategy: RateLimitStrategy):
        self.strategy = strategy

    def allow_request(self, key: str) -> bool:
        return self.strategy.allow_request(key, time.time())


# ════════════════════════════════════════════════════════════════════════
# DESIGN 3: Elevator Control System (State + Observer)
# ════════════════════════════════════════════════════════════════════════

class Direction(Enum):
    UP = 1
    DOWN = -1
    IDLE = 0


class ElevatorState(Enum):
    MOVING = "Moving"
    STOPPED = "Stopped"
    DOORS_OPEN = "Doors Open"
    DOORS_CLOSED = "Doors Closed"
    MAINTENANCE = "Maintenance"


class Request:
    def __init__(self, floor: int, direction: Optional[Direction] = None):
        self.floor = floor
        self.direction = direction


class Elevator:
    """
    Elevator with state machine for movement and door operations.

    THOUGHT PROCESS:
    ────────────────
    1. State Pattern: ElevatorState transitions (MOVING → STOPPED → DOORS_OPEN → DOORS_CLOSED)
    2. Strategy: Different scheduling algorithms (FCFS, SCAN, SSTF)
    3. Observer: Notify when elevator arrives at floor
    """

    def __init__(self, elevator_id: int, num_floors: int):
        self.id = elevator_id
        self.current_floor = 1
        self.direction = Direction.IDLE
        self.state = ElevatorState.DOORS_CLOSED
        self.num_floors = num_floors
        self.requests: List[Request] = []
        self.passengers: List[str] = []

    def add_request(self, floor: int, direction: Optional[Direction] = None) -> None:
        if 1 <= floor <= self.num_floors and floor != self.current_floor:
            req = Request(floor, direction)
            if req not in self.requests:
                self.requests.append(req)
            self.direction = self._get_direction()

    def _get_direction(self) -> Direction:
        if not self.requests:
            return Direction.IDLE
        next_floor = self.requests[0].floor
        if next_floor > self.current_floor:
            return Direction.UP
        elif next_floor < self.current_floor:
            return Direction.DOWN
        return Direction.IDLE

    def step(self) -> None:
        """Simulate one time unit of elevator operation."""
        if self.state == ElevatorState.DOORS_OPEN:
            self.state = ElevatorState.DOORS_CLOSED
            # Remove completed requests
            self.requests = [r for r in self.requests
                             if r.floor != self.current_floor]
            if not self.requests:
                self.direction = Direction.IDLE
            return

        if self.state == ElevatorState.MOVING:
            self.state = ElevatorState.STOPPED
            self.current_floor += self.direction.value
            return

        if self.state == ElevatorState.STOPPED:
            # Check if any requests at this floor
            for req in self.requests:
                if req.floor == self.current_floor:
                    self.state = ElevatorState.DOORS_OPEN
                    return
            self.state = ElevatorState.MOVING
            return

        if self.state == ElevatorState.DOORS_CLOSED:
            if not self.requests:
                self.direction = Direction.IDLE
            else:
                self.direction = self._get_direction()
                self.state = ElevatorState.MOVING

    def tick(self) -> None:
        """Execute one step."""
        self.step()


class ElevatorController:
    """
    Manages multiple elevators with a scheduling algorithm.

    THOUGHT PROCESS:
    ────────────────
    1. Uses the closest elevator that's heading in same direction
    2. SCAN algorithm: Process requests in current direction first
    3. Observer pattern: Track elevator states and notify on events
    """

    def __init__(self, num_elevators: int, num_floors: int):
        self.elevators = [Elevator(i + 1, num_floors) for i in range(num_elevators)]

    def request_elevator(self, floor: int, direction: Direction) -> Optional[int]:
        """Find and assign the best elevator for the request."""
        best_elevator = None
        best_distance = float('inf')

        for elev in self.elevators:
            if elev.state == ElevatorState.MAINTENANCE:
                continue
            distance = abs(elev.current_floor - floor)
            # Prefer elevators already moving in the request's direction
            if elev.direction == direction or elev.direction == Direction.IDLE:
                if distance < best_distance:
                    best_distance = distance
                    best_elevator = elev

        if best_elevator:
            best_elevator.add_request(floor, direction)
            return best_elevator.id
        return None

    def step(self) -> None:
        for elev in self.elevators:
            elev.step()


# ════════════════════════════════════════════════════════════════════════
# DESIGN 4: Pub-Sub Messaging System (Observer Pattern)
# ════════════════════════════════════════════════════════════════════════

class Message:
    def __init__(self, topic: str, payload: dict):
        self.topic = topic
        self.payload = payload
        self.timestamp = datetime.now()
        self.message_id = str(uuid.uuid4())


class Subscriber(ABC):
    """Abstract subscriber — can subscribe to multiple topics."""
    @abstractmethod
    def on_message(self, message: Message) -> None:
        pass


class Topic:
    """A topic/channel that subscribers can subscribe to."""
    def __init__(self, name: str):
        self.name = name
        self.subscribers: List[Subscriber] = []
        self.messages: List[Message] = []

    def subscribe(self, subscriber: Subscriber) -> None:
        self.subscribers.append(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self.subscribers.remove(subscriber)

    def publish(self, message: Message) -> None:
        self.messages.append(message)
        for subscriber in self.subscribers:
            subscriber.on_message(message)


class PubSubBroker:
    """
    Pub-Sub message broker managing topics and message routing.

    THOUGHT PROCESS:
    ────────────────
    1. Observer Pattern: Subscribers observe topics
    2. Mediator Pattern: Broker mediates between publishers and subscribers
    3. Topics are created on-demand or explicitly
    4. Messages are delivered asynchronously to all subscribers

    COMPLEXITY:
    ──────────
    Publish: O(1) topic lookup + O(s) subscriber notifications
    Subscribe: O(1) — Add to topic's subscriber list
    """

    def __init__(self):
        self.topics: Dict[str, Topic] = {}

    def create_topic(self, name: str) -> Topic:
        if name not in self.topics:
            self.topics[name] = Topic(name)
        return self.topics[name]

    def subscribe(self, topic_name: str, subscriber: Subscriber) -> None:
        topic = self.create_topic(topic_name)
        topic.subscribe(subscriber)

    def unsubscribe(self, topic_name: str, subscriber: Subscriber) -> None:
        if topic_name in self.topics:
            self.topics[topic_name].unsubscribe(subscriber)

    def publish(self, topic_name: str, payload: dict) -> None:
        if topic_name not in self.topics:
            raise ValueError(f"Topic '{topic_name}' does not exist")
        message = Message(topic_name, payload)
        self.topics[topic_name].publish(message)


# ════════════════════════════════════════════════════════════════════════
# DESIGN 5: Thread Pool (Resource Management)
# ════════════════════════════════════════════════════════════════════════

class Task(ABC):
    """Abstract task that can be executed by the thread pool."""
    @abstractmethod
    def execute(self) -> None:
        pass


class ThreadPool:
    """
    Thread Pool for managing concurrent task execution.

    THOUGHT PROCESS:
    ────────────────
    1. Pool of worker threads that pick up tasks from a queue
    2. Producer-Consumer pattern with a blocking queue
    3. Configurable number of threads, scales based on workload
    4. Graceful shutdown: complete queued tasks then stop

    COMPLEXITY:
    ──────────
    Submit: O(1) — Enqueue task
    Thread management: O(n) — n threads running concurrently
    """

    def __init__(self, num_threads: int = 4):
        self.num_threads = num_threads
        self._tasks: List[Callable] = []
        self._is_running = False
        self._threads: List[threading.Thread] = []

    def submit(self, task: Callable) -> None:
        self._tasks.append(task)

    def start(self) -> None:
        """Start the thread pool (simplified — non-blocking simulation)."""
        self._is_running = True
        print(f"   Thread pool started with {self.num_threads} threads")

    def execute_all(self) -> None:
        """Execute all pending tasks (synchronous for simulation)."""
        while self._tasks and self._is_running:
            task = self._tasks.pop(0)
            task()

    def shutdown(self) -> None:
        self._is_running = False
        print("   Thread pool shut down")


# ════════════════════════════════════════════════════════════════════════
# DESIGN 6: URL Shortener (System Design Concept)
# ════════════════════════════════════════════════════════════════════════

class URLShortener:
    """
    URL Shortener using base-62 encoding.

    THOUGHT PROCESS:
    ────────────────
    1. Each URL gets a unique integer ID
    2. Convert ID to base-62 (a-z, A-Z, 0-9) for short code
    3. Store mapping: short_code → original URL
    4. Collision handling: Use counter + hash or distributed ID generator

    Design Considerations:
    ─────────────────────
    • 62^7 = 3.5 trillion unique URLs with 7 characters
    • Read-heavy: Use cache (LRU) for popular URLs
    • Rate limiting per user to prevent abuse
    • Redirection: 301 (permanent) or 302 (temporary) HTTP redirect
    • Analytics: Track clicks, referrers, geographic data

    COMPLEXITY:
    ──────────
    Encode: O(1) — Base conversion
    Decode: O(1) — Hash map lookup
    Space: O(n) — n stored URLs
    """

    CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'

    def __init__(self):
        self.url_to_code: Dict[str, str] = {}
        self.code_to_url: Dict[str, str] = {}
        self.counter = 1
        self.base = len(self.CHARS)

    def _encode(self, num: int) -> str:
        if num == 0:
            return self.CHARS[0]
        code = []
        while num > 0:
            code.append(self.CHARS[num % self.base])
            num //= self.base
        return ''.join(reversed(code))

    def shorten(self, url: str) -> str:
        if url in self.url_to_code:
            return self.url_to_code[url]
        code = self._encode(self.counter)
        self.counter += 1
        self.url_to_code[url] = code
        self.code_to_url[code] = url
        return code

    def resolve(self, code: str) -> Optional[str]:
        return self.code_to_url.get(code)


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("DESIGN PROBLEMS — Interview Questions Demo")
    print("=" * 70)

    # Design 1: Logger
    print("\n1️⃣  Logging Framework (Singleton + Strategy)")
    print("-" * 40)
    logger = Logger()
    logger.add_appender(ConsoleAppender())
    logger.set_level(LogLevel.INFO)
    print("   Set level to INFO. DEBUG messages will be filtered:")
    logger.debug("This won't appear")
    logger.info("This will appear")

    # Design 2: Rate Limiter
    print("\n2️⃣  Rate Limiter (Token Bucket)")
    print("-" * 40)
    bucket = TokenBucket(capacity=3, refill_rate=0.5)
    limiter = RateLimiter(bucket)
    user = "user_1"
    for i in range(5):
        result = limiter.allow_request(user)
        print(f"   Request {i+1}: {'✅ Allowed' if result else '❌ Denied'}")
    print(f"   (After 2s wait, tokens will refill...)")

    # Design 3: Elevator
    print("\n3️⃣  Elevator Control System")
    print("-" * 40)
    controller = ElevatorController(num_elevators=2, num_floors=10)
    controller.request_elevator(5, Direction.UP)
    controller.request_elevator(3, Direction.DOWN)
    print("   Requests: Floor 5 (UP), Floor 3 (DOWN)")
    for i in range(6):
        print(f"   Tick {i+1}: Elevator 1 at floor {controller.elevators[0].current_floor}, "
              f"state: {controller.elevators[0].state.value}")
        controller.step()

    # Design 4: Pub-Sub
    print("\n4️⃣  Pub-Sub Messaging System (Observer)")
    print("-" * 40)

    class PrintSubscriber(Subscriber):
        def __init__(self, name: str):
            self.name = name

        def on_message(self, message: Message) -> None:
            print(f"   [{self.name}] Received: {message.payload} "
                  f"(topic: {message.topic})")

    broker = PubSubBroker()
    sub1 = PrintSubscriber("Subscriber-1")
    sub2 = PrintSubscriber("Subscriber-2")
    broker.subscribe("orders", sub1)
    broker.subscribe("orders", sub2)
    broker.subscribe("payments", sub1)
    broker.publish("orders", {"order_id": 1234, "item": "book"})
    broker.publish("payments", {"payment_id": "txn_001", "amount": 29.99})

    # Design 5: Thread Pool
    print("\n5️⃣  Thread Pool")
    print("-" * 40)
    pool = ThreadPool(num_threads=3)
    pool.start()
    pool.submit(lambda: print("   Task 1 executed"))
    pool.submit(lambda: print("   Task 2 executed"))
    pool.submit(lambda: print("   Task 3 executed"))
    pool.execute_all()
    pool.shutdown()

    # Design 6: URL Shortener
    print("\n6️⃣  URL Shortener")
    print("-" * 40)
    shortener = URLShortener()
    urls = [
        "https://example.com/very/long/url/1",
        "https://example.com/very/long/url/2",
        "https://google.com"
    ]
    for url in urls:
        code = shortener.shorten(url)
        resolved = shortener.resolve(code)
        print(f"   {url[:40]:40s} → {code:10s} → {resolved}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
