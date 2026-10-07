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
from collections import OrderedDict, defaultdict, deque
from concurrent.futures import Future
import queue
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
    1. Singleton: Ensures a single logging instance across the app.
       Creation must be thread-safe: two threads can both see
       `_instance is None`. Double-checked locking fixes it (below).
    2. Strategy (Appender): Different output targets (console, file,
       network) behind one interface
    3. Observer-like fan-out: every registered appender receives each
       record (per-appender level filters are a natural extension)
    4. Configurable log level filtering

    WHAT THEY PROBE NEXT:
    ─────────────────────
    • Singletons hurt testability (hidden global state); prefer passing
      a logger in, or a module-level instance — Python modules are
      already singletons, and the stdlib `logging.getLogger(name)` is
      the production answer
    • Don't block the request path on slow appenders: hand records to a
      queue drained by a background thread (logging.handlers.QueueHandler)
    • Structured (JSON) logs with request/trace IDs for correlation
    """

    _instance: Optional['Logger'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:                 # Fast path, no lock
            with cls._lock:
                if cls._instance is None:         # Re-check under lock
                    instance = super().__new__(cls)
                    instance._appenders = []
                    instance._min_level = LogLevel.DEBUG
                    cls._instance = instance
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
    Token Bucket: Tokens refill at a constant rate up to `capacity`.
    Each request consumes one token.

    • Allows bursts up to `capacity`, then a steady `refill_rate`/s
    • O(1) time and memory per key: refill lazily from the elapsed time
      instead of running a timer
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
    """
    Sliding window log — maintains timestamps of recent requests.

    • Exact (no boundary burst like a fixed window), but stores up to
      max_requests timestamps per key: O(limit) memory per user
    • Sliding window COUNTER approximates it with two counters per key:
      prev_count * overlap_fraction + curr_count
    """
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.logs: Dict[str, deque] = {}

    def allow_request(self, key: str, timestamp: float) -> bool:
        log = self.logs.setdefault(key, deque())
        # Remove expired entries (deque.popleft is O(1); list.pop(0) is O(n))
        while log and log[0] <= timestamp - self.window_seconds:
            log.popleft()
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
    3. Thread-safe: a check-then-decrement is a race, so the facade
       serialises calls with a lock (one global lock is simple; stripe
       locks by key hash if it becomes a bottleneck)
    4. time.monotonic(), not time.time(): wall-clock time can jump
       backwards (NTP), which would mint or destroy tokens

    WHAT THEY PROBE NEXT:
    ─────────────────────
    • Many app servers → shared state in Redis; make check+update atomic
      with a Lua script (or INCR + EXPIRE for a fixed window)
    • Fail open or fail closed when the limiter store is down?
    • Return HTTP 429 with Retry-After; limit per user, per IP, per API key
    """
    def __init__(self, strategy: RateLimitStrategy):
        self.strategy = strategy
        self._lock = threading.Lock()

    def allow_request(self, key: str) -> bool:
        with self._lock:
            return self.strategy.allow_request(key, time.monotonic())


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

    # Without __eq__, `req in list` compares identity and every duplicate
    # call would be queued again
    def __eq__(self, other: object) -> bool:
        return (isinstance(other, Request) and self.floor == other.floor
                and self.direction == other.direction)

    def __hash__(self) -> int:
        return hash((self.floor, self.direction))


class Elevator:
    """
    Elevator with state machine for movement and door operations.

    THOUGHT PROCESS:
    ────────────────
    1. State machine: MOVING → STOPPED → DOORS_OPEN → DOORS_CLOSED
       (an enum + transitions here; the full State pattern gives each
       state its own class)
    2. Scheduling here is simple: head toward the OLDEST request, but
       stop at any requested floor passed on the way. The usual
       follow-up is SCAN/LOOK: keep going in one direction while there
       are requests ahead, then reverse (the "elevator algorithm" from
       disk scheduling), which avoids starving far floors under SSTF.
    3. Observer: notify displays / the controller when the car arrives
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
    1. Prefer the closest idle elevator or one already heading in the
       requested direction; otherwise fall back to the closest working
       elevator so the request is never dropped
    2. Refinement: "heading the same way" should also mean "and hasn't
       passed the floor yet"; real systems score cars by estimated
       time of arrival
    3. Observer pattern: Track elevator states and notify on events
    """

    def __init__(self, num_elevators: int, num_floors: int):
        self.elevators = [Elevator(i + 1, num_floors) for i in range(num_elevators)]

    def request_elevator(self, floor: int, direction: Direction) -> Optional[int]:
        """Find and assign the best elevator for the request."""
        working = [e for e in self.elevators
                   if e.state != ElevatorState.MAINTENANCE]
        # Prefer elevators idle or already moving in the request's direction
        preferred = [e for e in working
                     if e.direction in (direction, Direction.IDLE)]
        candidates = preferred or working
        best_elevator = min(candidates,
                            key=lambda e: abs(e.current_floor - floor),
                            default=None)

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
    4. This version delivers SYNCHRONOUSLY on the publisher's thread: a
       slow subscriber slows the publisher, and an exception in one
       subscriber stops delivery to the rest. Real brokers decouple with
       a queue per subscriber (or per consumer group) and worker threads.

    WHAT THEY PROBE NEXT:
    ─────────────────────
    • Delivery guarantees: at-most-once vs at-least-once (acks +
      retries → consumers must be idempotent); "exactly-once" needs
      dedup or transactions end to end
    • Ordering: per topic/partition only (Kafka orders within a
      partition, not across a topic)
    • Retention and replay: Topic.messages here grows forever; real
      systems keep a bounded log with per-consumer offsets
    • Backpressure for slow consumers; dead-letter queues

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

class ThreadPool:
    """
    Fixed-size Thread Pool for concurrent task execution.

    THOUGHT PROCESS:
    ────────────────
    1. N long-lived worker threads pull tasks from a shared, thread-safe
       blocking queue (producer-consumer). Reusing threads avoids paying
       thread creation per task and caps concurrency.
    2. submit() wraps the callable with a Future so callers can wait for
       the result or the exception — never swallow worker exceptions.
    3. Graceful shutdown: enqueue one sentinel (None) per worker AFTER
       the pending tasks; each worker exits when it reads one, so queued
       work finishes first. Then join the threads.
    4. Python's GIL means threads speed up I/O-bound work, not CPU-bound
       Python code (use processes for that; free-threaded 3.13+ builds
       change this). In production use concurrent.futures.
       ThreadPoolExecutor.

    WHAT THEY PROBE NEXT:
    ─────────────────────
    • Bounded queue + rejection policy (block, drop, caller-runs) to
      apply backpressure instead of growing memory without limit
    • Sizing: ~#cores for CPU-bound; more for I/O-bound (Little's law:
      threads ≈ throughput × latency)
    • Deadlock: a task that waits on another task in the same pool can
      starve the pool

    COMPLEXITY:
    ──────────
    Submit: O(1) — Enqueue task
    Space: O(n + q) — n threads plus q queued tasks
    """

    _SENTINEL = None

    def __init__(self, num_threads: int = 4):
        self.num_threads = num_threads
        self._tasks: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._shutdown = False
        self._lock = threading.Lock()
        self._threads = [threading.Thread(target=self._worker, daemon=True)
                         for _ in range(num_threads)]
        for t in self._threads:
            t.start()

    def _worker(self) -> None:
        while True:
            item = self._tasks.get()          # Blocks until work arrives
            if item is self._SENTINEL:
                return
            future, fn, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue                      # Cancelled before it ran
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:      # Report, don't kill the worker
                future.set_exception(exc)

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("cannot submit after shutdown")
            future: Future = Future()
            self._tasks.put((future, fn, args, kwargs))
            return future

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            for _ in self._threads:
                self._tasks.put(self._SENTINEL)   # Queued after real work
        if wait:
            for t in self._threads:
                t.join()


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
    4. Unique IDs at scale: a counter per shard with pre-allocated ID
       ranges, or a Snowflake-style ID — no collisions to handle.
       Hashing the URL instead (take 7 chars of a hash) needs collision
       checks and retries.
    5. Sequential IDs are guessable: anyone can enumerate links. Shuffle
       the ID with a bijective permutation, or use random codes when
       links may be private.

    Design Considerations:
    ─────────────────────
    • 62^7 = 3.5 trillion unique URLs with 7 characters
    • Read-heavy: Use cache (LRU) for popular URLs
    • Rate limiting per user to prevent abuse
    • Redirection: 301 is cached by browsers (fewer hits, but you lose
      click analytics and can't change the target); 302/307 sends every
      click through you
    • Analytics: Track clicks, referrers, geographic data

    COMPLEXITY:
    ──────────
    Encode: O(log₆₂ id) — one step per output character (≤ 7 here)
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
# DESIGN 7: LRU Cache (Hash Map + Doubly Linked List)
# ════════════════════════════════════════════════════════════════════════

class _DNode:
    """Doubly linked list node holding one cache entry."""
    __slots__ = ("key", "value", "prev", "next")

    def __init__(self, key: int = 0, value: int = 0):
        self.key = key
        self.value = value
        self.prev: Optional['_DNode'] = None
        self.next: Optional['_DNode'] = None


class LRUCacheDLL:
    """
    QUESTION:
    ─────────
    Design a Least Recently Used cache with get(key) and put(key, value),
    both O(1). When full, put evicts the least recently used key.
    (Hashing Q7 shows the OrderedDict shortcut; interviewers usually want
    this version.)

    THOUGHT PROCESS:
    ────────────────
    1. O(1) lookup → hash map key → node
    2. O(1) "move to most-recent" and "evict least-recent" → doubly
       linked list ordered by recency (singly linked can't unlink a node
       in O(1) without its predecessor)
    3. Sentinel head and tail nodes remove every empty-list / edge-node
       special case: head.next is the MRU entry, tail.prev the LRU one
    4. Store the KEY in the node too, so eviction can delete the map
       entry for the tail node

    COMPLEXITY:
    ──────────
    get / put: O(1)
    Space: O(capacity)

    WHAT THEY PROBE NEXT:
    ─────────────────────
    • Thread safety: get() mutates the list, so even reads need the lock
      (or shard the cache by key hash, one lock per shard)
    • TTL expiry; size by bytes instead of entry count
    • LRU's weakness: one big scan flushes the hot set. Variants: LRU-K,
      2Q, segmented LRU, W-TinyLFU (Caffeine); Redis uses sampled
      approximate LRU/LFU instead of a global list
    """

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.map: Dict[int, _DNode] = {}
        self.head = _DNode()               # Sentinel: head.next = MRU
        self.tail = _DNode()               # Sentinel: tail.prev = LRU
        self.head.next = self.tail
        self.tail.prev = self.head

    def _unlink(self, node: _DNode) -> None:
        node.prev.next = node.next
        node.next.prev = node.prev

    def _push_front(self, node: _DNode) -> None:
        node.prev, node.next = self.head, self.head.next
        self.head.next.prev = node
        self.head.next = node

    def get(self, key: int) -> int:
        node = self.map.get(key)
        if node is None:
            return -1
        self._unlink(node)                 # Mark as most recently used
        self._push_front(node)
        return node.value

    def put(self, key: int, value: int) -> None:
        if self.capacity <= 0:
            return
        node = self.map.get(key)
        if node:
            node.value = value
            self._unlink(node)
            self._push_front(node)
            return
        if len(self.map) == self.capacity:
            lru = self.tail.prev           # Evict least recently used
            self._unlink(lru)
            del self.map[lru.key]
        node = _DNode(key, value)
        self.map[key] = node
        self._push_front(node)


# ════════════════════════════════════════════════════════════════════════
# DESIGN 8: LFU Cache (Frequency Buckets, O(1))
# ════════════════════════════════════════════════════════════════════════

class LFUCache:
    """
    QUESTION:
    ─────────
    Design a Least Frequently Used cache: get and put in O(1). When
    full, evict the key with the lowest use count; break ties by
    evicting the least recently used among them.

    THOUGHT PROCESS:
    ────────────────
    1. A heap keyed by (count, last_used) gives O(log n), but every get
       changes a key's count → expensive updates.
    2. O(1) idea: group keys by frequency.
       - key_to_val, key_to_freq: plain maps
       - freq_to_keys: freq → OrderedDict of keys in LRU order
       - min_freq: the smallest frequency that currently has keys
    3. Touching a key moves it from bucket f to bucket f + 1 (append at
       the MRU end). If bucket f became empty and f == min_freq, then
       min_freq = f + 1 — it can only go up by one on a touch.
    4. Inserting a NEW key always resets min_freq = 1.
    5. Evict: pop the oldest key from freq_to_keys[min_freq].

    COMPLEXITY:
    ──────────
    get / put: O(1)
    Space: O(capacity)

    TRADE-OFF:
    ──────────
    Pure LFU keeps formerly-hot keys forever (counts never decay); real
    systems age counts (Redis LFU decays its logarithmic counter over
    time; TinyLFU uses periodic halving).
    """

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.key_to_val: Dict[int, int] = {}
        self.key_to_freq: Dict[int, int] = {}
        self.freq_to_keys: Dict[int, OrderedDict] = defaultdict(OrderedDict)
        self.min_freq = 0

    def _touch(self, key: int) -> None:
        """Move key from its frequency bucket to the next one."""
        f = self.key_to_freq[key]
        del self.freq_to_keys[f][key]
        if not self.freq_to_keys[f]:
            del self.freq_to_keys[f]
            if self.min_freq == f:
                self.min_freq = f + 1
        self.key_to_freq[key] = f + 1
        self.freq_to_keys[f + 1][key] = None    # MRU end of the bucket

    def get(self, key: int) -> int:
        if key not in self.key_to_val:
            return -1
        self._touch(key)
        return self.key_to_val[key]

    def put(self, key: int, value: int) -> None:
        if self.capacity <= 0:
            return
        if key in self.key_to_val:
            self.key_to_val[key] = value
            self._touch(key)
            return
        if len(self.key_to_val) == self.capacity:
            bucket = self.freq_to_keys[self.min_freq]
            evict, _ = bucket.popitem(last=False)   # LRU within min freq
            if not bucket:
                del self.freq_to_keys[self.min_freq]
            del self.key_to_val[evict]
            del self.key_to_freq[evict]
        self.key_to_val[key] = value
        self.key_to_freq[key] = 1
        self.freq_to_keys[1][key] = None
        self.min_freq = 1


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
    futures = [pool.submit(lambda x: x * x, i) for i in range(1, 6)]
    failing = pool.submit(lambda: 1 / 0)
    pool.shutdown(wait=True)
    print(f"   Squares computed by 3 workers: {[f.result() for f in futures]}")
    print(f"   Exception surfaced via Future: {type(failing.exception()).__name__}")

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

    # Design 7: LRU Cache
    print("\n7️⃣  LRU Cache (Hash Map + Doubly Linked List)")
    print("-" * 40)
    lru = LRUCacheDLL(2)
    lru.put(1, 1)
    lru.put(2, 2)
    print(f"   put(1), put(2), get(1) → {lru.get(1)}")
    lru.put(3, 3)                      # Evicts key 2 (least recently used)
    print(f"   put(3) evicts 2 → get(2) = {lru.get(2)}, get(3) = {lru.get(3)}")

    # Design 8: LFU Cache
    print("\n8️⃣  LFU Cache (Frequency Buckets)")
    print("-" * 40)
    lfu = LFUCache(2)
    lfu.put(1, 1)
    lfu.put(2, 2)
    lfu.get(1)                         # freq(1) = 2, freq(2) = 1
    lfu.put(3, 3)                      # Evicts key 2 (lowest frequency)
    print(f"   put(1), put(2), get(1), put(3) → get(2) = {lfu.get(2)}, "
          f"get(1) = {lfu.get(1)}, get(3) = {lfu.get(3)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
