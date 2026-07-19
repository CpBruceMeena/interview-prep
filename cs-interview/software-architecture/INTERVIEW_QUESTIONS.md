# 🏗️ Software Architecture — Staff-Level Interview Questions

> *12 questions covering microservices, CQRS, event sourcing, observability, and architecture patterns — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [Microservices Decomposition: Domain-Driven Design](#1-microservices-decomposition-domain-driven-design)
2. [CQRS & Event Sourcing](#2-cqrs-event-sourcing)
3. [Event-Driven Architecture: Kafka Internals](#3-event-driven-architecture-kafka-internals)
4. [API Gateway vs Service Mesh](#4-api-gateway-vs-service-mesh)
5. [Idempotency & Exactly-Once Semantics](#5-idempotency-exactly-once-semantics)
6. [Circuit Breaker & Bulkhead Patterns](#6-circuit-breaker-bulkhead-patterns)
7. [Graceful Degradation & Fallbacks](#7-graceful-degradation-fallbacks)
8. [Observability: Logging, Metrics, Tracing](#8-observability-logging-metrics-tracing)
9. [Saga Pattern: Choreography vs Orchestration](#9-saga-pattern-choreography-vs-orchestration)
10. [Backpressure & Reactive Systems](#10-backpressure-reactive-systems)
11. [Migration Strategies: Strangler Fig](#11-migration-strategies-strangler-fig)
12. [Configuration Management & Feature Flags](#12-configuration-management-feature-flags)

---

## 1. Microservices Decomposition

**Q:** "We have a monolith e-commerce platform (auth, catalog, cart, orders, payments, shipping — all in one codebase). Walk me through your methodology for decomposing this into microservices using Domain-Driven Design. How do you identify bounded contexts? How do you handle shared data like user profiles?"

**What They're Really Testing:** Whether you understand DDD's strategic design patterns and can identify bounded contexts vs sub-domains vs aggregate roots.

### Answer

**Event Storming — Identifying Bounded Contexts:**

```
Domain Events (key moments in the system):
─→ User Registered
─→ Product Added to Catalog
─→ Item Added to Cart
─→ Cart Checked Out
─→ Order Placed
─→ Payment Authorized
─→ Payment Captured
─→ Order Shipped
─→ Item Delivered
─→ Order Cancelled

Bounded Contexts (grouped by ubiquitous language):

┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│ Identity & Auth    │  │ Catalog            │  │ Cart               │
│                    │  │                    │  │                    │
│ • User             │  │ • Product          │  │ • Cart            │
│ • Credential       │  │ • Category         │  │ • CartItem        │
│ • Session          │  │ • Inventory        │  │ • Price (snapshot)│
│ • Role             │  │ • Price            │  │                     │
│                    │  │                    │  │                     │
│ Language: "user",  │  │ Language: "item",  │  │ Language: "cart",  │
│ "register", "login"│  │ "catalog", "SKU"   │  │ "checkout","add"   │
└────────────────────┘  └────────────────────┘  └────────┬───────────┘
                                                          │
                                                          ▼
┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│ Orders             │  │ Payments           │  │ Shipping           │
│                    │  │                    │  │                    │
│ • Order            │  │ • Authorization    │  │ • Shipment         │
│ • OrderLine        │  │ • Capture          │  │ • Tracking         │
│ • OrderStatus      │  │ • Refund           │  │ • Carrier          │
│                    │  │ • Transaction      │  │ • Label            │
│                    │  │                    │  │                    │
│ Language: "order", │  │ Language: "pay",   │  │ Language: "ship",  │
│ "fulfill", "cancel"│  │ "refund", "auth"   │  │ "carrier","track"  │
└────────────────────┘  └────────────────────┘  └────────────────────┘
```

**Shared Data — User Profiles Across Contexts:**

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/arch-microservices-decomposition.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Microservices Decomposition — Monolith → Bounded Contexts with Anti-Corruption Layer. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



```yaml
The problem: Every context needs SOME user data, but they can't all
             share the User table.

Solution: Each context gets its OWN representation:

# Identity context (source of truth):
users:
  id: uuid
  email: string
  password_hash: string
  roles: string[]

# Orders context (cached copy, event-sourced):
order_users:
  user_id: uuid (PK, FK to orders only)
  email: string (copied FROM UserRegistered event)
  shipping_address: string (updated FROM UserUpdated event)

# The event flows:
UserRegistered:
  → Orders service creates order_users record
  → Cart service creates cart for user
  → Shipping service creates empty profile

# This means:
# - Orders service never calls Identity service's API
# - If Identity is down, orders can still process (has cached data)
# - Data is eventually consistent (acceptable for order processing)
# - Trade-off: slight delay in address updates
```

**Anti-Corruption Layer:**

```python
# When Catalog context talks to Inventory in Shipping context:
# (different languages for "stock")

class InventoryAcl:
    """Anti-Corruption Layer between Catalog and Shipping contexts"""

    def __init__(self, shipping_client):
        self.shipping = shipping_client

    def get_available_quantity(self, sku: str) -> int:
        # Shipping context calls it "item_code" and "units_available"
        raw = self.shipping.get_stock_level(item_code=sku)
        # Transform to Catalog context language
        return {
            "sku": sku,
            "quantity": raw["units_available"],
            "warehouse": raw["location_name"]
        }

    def reserve_stock(self, sku: str, quantity: int):
        # Shipping context uses "allocate" not "reserve"
        self.shipping.allocate(item_code=sku, units=quantity)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Bounded contexts** | Identifies them by ubiquitous language, not by department |
| **Shared data** | Uses event-sourced local copies, not shared tables |
| **ACL** | Mentions anti-corruption layer for translating between contexts |
| **Aggregate boundaries** | Understands transaction boundaries (one aggregate per transaction) |

---

## 2. CQRS & Event Sourcing

**Q:** "Design a banking system using CQRS and event sourcing. Show me the write path (command → event → aggregate) and read path (materialized view). How do you handle eventual consistency between the command and query sides when a user makes a transfer and immediately checks their balance?"

**What They're Really Testing:** Whether you understand CQRS as a consistency trade-off, not just a pattern, and can design for the read-your-write problem.

### Answer

**CQRS + Event Sourcing Architecture:**

```
Write Side (Command Model)                  Read Side (Query Model)
┌─────────────────────────┐                 ┌──────────────────────┐
│ Command Bus             │                 │ Materialized Views   │
│                         │                 │                      │
│ ┌─────────────────────┐ │                 │ ┌──────────────────┐ │
│ │ Command: Transfer   │ │                 │ │ account_summary  │ │
│ │ From: A              │ │                 │ │ - balance        │ │
│ │ To: B                │ │                 │ │ - last_10_txns   │ │
│ │ Amount: 100          │ │                 │ └──────────────────┘ │
│ └─────────┬───────────┘ │                 │                      │
│           │             │                 │ ┌──────────────────┐ │
│           ▼             │                 │ │ daily_report    │ │
│ ┌─────────────────────┐ │                 │ │ - total_txns    │ │
│ │ Aggregate: Account  │ │                 │ │ - total_volume   │ │
│ │                     │ │                 │ └──────────────────┘ │
│ │ Validate: balance > │ │                 └──────┬───────────────┘
│ │          100         │ │                        │
│ │ Apply: deduct 100   │ │                        │ (async projection)
│ │ Append event to     │ │                        │
│ │ event store          │ │                        │
│ └─────────┬───────────┘ │                        │
│           │             │                        │
└───────────┼─────────────┘                        │
            │                                      │
            ▼                                      │
┌─────────────────────────┐                        │
│ Event Store             │                        │
│ (immutable append-log)  │                        │
│                         │                        │
│ ┌─────────────────────┐ │                        │
│ │ Account A:          │ │                        │
│ │ - Opened(0)        │ │                        │
│ │ - Deposited(1000)  │ │                        │
│ │ - Transferred(-100)│ │────────────────────────►│
│ └─────────────────────┘ │  Event Bus (Kafka)     │
└─────────────────────────┘                        │
                                                   │
                                                   ▼
                                          ┌──────────────────────┐
                                          │ Read Model Projector  │
                                          │                       │
                                          │ on Transferred:       │
                                          │   UPDATE balance      │
                                          │   INSERT transaction  │
                                          └──────────────────────┘
```

**Command Model (Aggregate):**

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/arch-cqrs-event-sourcing.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — CQRS + Event Sourcing — Command → Aggregate → Event Store → Projector → Materialized View. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



```python
@aggregate
class Account:
    def __init__(self):
        self.id = None
        self.balance = 0
        self.version = 0

    def handle_transfer(self, cmd: TransferCommand):
        # Validate business rules
        if self.balance < cmd.amount:
            raise InsufficientFunds(self.balance, cmd.amount)

        # Only append events — don't modify state directly
        return [
            Debited(account_id=self.id,
                    amount=cmd.amount,
                    transaction_id=cmd.transaction_id),
            Credited(account_id=cmd.target_account,
                     amount=cmd.amount,
                     transaction_id=cmd.transaction_id),
        ]

    def apply_debited(self, event: Debited):
        self.balance -= event.amount
        self.version += 1

    def apply_credited(self, event: Credited):
        self.balance += event.amount
        self.version += 1
```

**Read-Your-Write Problem — The Fix:**

```python
# Problem: User transfers, reads balance — sees OLD balance
# because projector hasn't processed the event yet.

# Solution 1: Optimistic UI (most common)
class TransferService:
    def transfer_and_return(self, cmd):
        # 1. Execute command (synchronous — goes to event store)
        events = self.command_bus.dispatch(cmd)

        # 2. Wait for projection to catch up
        #    (projector maintains a "last processed event ID")
        projection_lag = self.projection_tracker.get_lag()
        if projection_lag > 0:
            # For the user's session, subscribe to events
            # and wait for their transaction to be projected
            self.event_bus.subscribe(
                event_type="TransactionProcessed",
                filter={"transaction_id": cmd.transaction_id},
                timeout_ms=500,
            )

        # 3. Read from materialized view (now consistent)
        return self.query_model.get_account_summary(cmd.account_id)

# Solution 2: Read-model co-location
# Store the current balance directly in the event store:
#   After writing Debit event, also update a "current_snapshot"
#   in the same transaction!

class EventStoreWithSnapshot:
    def append_and_read(self, stream_id, events):
        with self.transaction():
            # Write events
            self.append_events(stream_id, events)
            # Update snapshot immediately
            snapshot = self.rebuild_snapshot(stream_id)
            self.save_snapshot(stream_id, snapshot)
        return snapshot.current_balance

# Solution 3: CQRS with synchronous projection
# (sacrifices write-side performance for read-your-write)
class SynchronousProjector:
    def append_events(self, stream_id, events):
        # Write to event store
        positions = self.event_store.append(stream_id, events)
        # Immediately update materialized view
        for event in events:
            self.project_event(event)
        return positions

# Usually Solution 2 (snapshot in event store) is the best balance.
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Aggregate design** | Understands aggregates as consistency boundaries, not data holders |
| **Event immutability** | Knows events are appended, never modified |
| **Read-your-write** | Proposes a concrete solution (snapshot, synchronous write-through) |
| **Trade-off** | Acknowledges CQRS adds complexity — justifies why it's needed here |

---

## 3. Event-Driven Architecture: Kafka Internals

**Q:** "Design an event-driven order processing system using Kafka. Trace a message from producer to consumer. How does Kafka achieve its throughput? Specifically, explain the log-segment structure, ISR replication, and consumer group rebalancing."

**Answer:**

```
Kafka Log Segment Structure:

Topic: orders, Partition: 0

┌─────────────────────────────────────────────────────┐
│  Segment 1 (00000000000000000000.log)               │
│  ├── OrderCreated{id: 1, user: 42, total: $100}   │  ← Offset 0
│  ├── OrderCreated{id: 2, user: 99, total: $250}   │  ← Offset 1
│  └── OrderShipped{id: 1, carrier: UPS}            │  ← Offset 2
├─────────────────────────────────────────────────────┤
│  Segment 2 (00000000000000000003.log)               │
│  ├── OrderCreated{id: 3, user: 7, total: $50}     │  ← Offset 3
│  └── ...                                            │
├─────────────────────────────────────────────────────┤
│  Segment 3 (active segment, currently writing)      │
│  └── OrderCancelled{id: 2, reason: "out of stock"} │  ← Offset N
├─────────────────────────────────────────────────────┤
│  Index files (for O(1) offset lookups):             │
│  └── 00000000000000000000.index                     │
│  └── 00000000000000000000.timeindex                 │
└─────────────────────────────────────────────────────┘

ISR (In-Sync Replicas):
  Leader tracks replicas that have replicated within
  replica.lag.time.max.ms (default 30s)
  
  Write path:
  1. Producer sends to partition LEADER
  2. Leader appends to local log
  3. Leader waits for all IN-SYNC replicas to ack
     (min.insync.replicas = 2)
  4. Leader sends back acknowledgement
  
  Failure:
  - If follower falls behind > 30s → removed from ISR
  - When leader crashes: new leader elected from ISR
  - Data loss: only if ALL in-sync replicas are lost

Consumer Group Rebalancing:
  1. Consumer joins group → sends JoinGroup to coordinator
  2. Coordinator picks leader (first consumer)
  3. Leader gets member list, assigns partitions using
     RangeAssignor or RoundRobinAssignor
  4. Leader sends SyncGroup with assignments
  5. All consumers receive their partition assignments
  6. Each consumer starts fetching from assigned partitions
  
  During rebalance: ALL consumers STOP processing (stop-the-world)
  Recent KIP-848: Cooperative rebalancing (incremental)
```

---

## 4. API Gateway vs Service Mesh

**Q:** "You're designing the infrastructure layer for 50 microservices. Compare Kong/NGINX (API Gateway) vs Istio/Linkerd (Service Mesh). When would you use both?"

**Answer:**

```
API Gateway (North-South traffic): Client → Gateway → Services
  - Handles: auth, rate limiting, TLS termination, routing
  - One per environment (staging, prod)
  - Deployed at edge

Service Mesh (East-West traffic): Service → Sidecar → Service
  - Handles: mTLS, retries, circuit breaking, observability
  - Sidecar per pod (Istio: Envoy, Linkerd: Rust-based)
  - Transparent to application code

When to use both:
  API Gateway at edge (external traffic)
  Service Mesh internally (internal service-to-service)
  
  Client → API Gateway (auth, rate limit) → Service A
                                                    │
                                              (sidecar mTLS)
                                                    │
                                              Service B → Service C
```

---

## 5. Idempotency & Exactly-Once Semantics

**Q:** "Design a payment processing system that guarantees exactly-once processing. How do you handle retries, duplicate requests, and failures at the infrastructure level? Walk me through the idempotency key pattern and the transactional outbox pattern."

**What They're Really Testing:** Whether you understand that exactly-once is about idempotency + deduplication, not about preventing failures. They want to see you handle the distributed systems reality of at-least-once delivery paired with idempotent consumers.

### Answer

**The Problem:**

```
Client                    Payment Service              Payment Gateway
  │                             │                            │
  │──── POST /charge (1) ──────►│                            │
  │                             │─── charge() ──────────────►│
  │                             │         (timeout)          │
  │                             │◄───────────────────────────│
  │  (client retries)           │                            │
  │──── POST /charge (2) ──────►│  ← Duplicate!             │
  │                             │  How do we avoid          │
  │                             │  charging twice?           │
```

**Solution 1: Idempotency Key Pattern**

```python
import uuid
from flask import request, jsonify

class PaymentService:
    def __init__(self):
        self.db = Database()
        self.gateway = PaymentGateway()

    def charge(self):
        idempotency_key = request.headers["Idempotency-Key"]
        payload = request.json

        # Check if this key has been processed
        existing = self.db.query(
            "SELECT status FROM idempotency_keys "
            "WHERE key = :key",
            {"key": idempotency_key}
        )

        if existing:
            # Already processed — return cached result
            return jsonify(existing.result), existing.status_code

        # Process the charge
        try:
            result = self.gateway.charge(payload["amount"], payload["currency"])

            # Record the idempotency key in the same transaction
            self.db.execute("""
                INSERT INTO idempotency_keys (key, result, status_code, created_at)
                VALUES (:key, :result, :status, NOW())
            """, {
                "key": idempotency_key,
                "result": result,
                "status": 200
            })

            return jsonify(result), 200

        except GatewayError as e:
            # Only record FAILED status for certain errors
            # (retriable errors: don't record — allow retry)
            if not e.retriable:
                self.db.execute("""
                    INSERT INTO idempotency_keys (key, result, status_code)
                    VALUES (:key, :error, :status)
                """, {
                    "key": idempotency_key,
                    "error": str(e),
                    "status": 422
                })
            raise
```

**Solution 2: Transactional Outbox Pattern**

```
Problem: What if the DB write succeeds but the Kafka publish fails?
         You've charged the customer but the event is lost.

                  ┌──────────────┐
     Request ────►│  API Handler  │
                  └──────┬───────┘
                         │
                ┌────────▼────────┐
                │   DB Transaction │
                │   1. INSERT INTO │
                │      outbox(msg) │
                │   2. INSERT INTO │
                │      idempotency │
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │  Outbox Relay    │  ← Polls outbox table
                │  (separate proc) │    publishes to Kafka
                │                  │    deletes after ack
                └────────┬────────┘
                         │
                         ▼
                    Kafka Topic
```

```python
class OutboxRelay:
    """Separate process that polls the outbox table."""

    def poll_and_publish(self):
        # Fetch unsent messages
        messages = self.db.query("""
            SELECT id, topic, payload, created_at
            FROM outbox
            WHERE published = FALSE
            ORDER BY created_at ASC
            LIMIT 100
            FOR UPDATE SKIP LOCKED
        """)

        for msg in messages:
            try:
                # Send to Kafka
                self.kafka.produce(msg.topic, msg.payload)
                self.kafka.flush()

                # Mark as published (same DB connection)
                self.db.execute(
                    "UPDATE outbox SET published = TRUE WHERE id = :id",
                    {"id": msg.id}
                )
            except Exception as e:
                # Will retry on next poll
                self.logger.error(f"Failed to publish {msg.id}: {e}")

# Alternative: CDC-based outbox (Debezium)
# Instead of polling, read the DB binlog directly
#   DB: WAL/binlog → Debezium connector → Kafka
# Pros: No-polling, low latency
# Cons: Requires CDC infrastructure
```

**Solution 3: Dedup Consumer**

```python
class DedupConsumer:
    """Kafka consumer that deduplicates messages."""

    def __init__(self):
        self.processed = RedisCache()  # TTL: 7 days

    def process_message(self, msg):
        message_id = msg.headers["message_id"]

        # Check if already processed
        if self.processed.get(message_id):
            self.logger.info(f"Skipping duplicate: {message_id}")
            self.consumer.commit()  # Commit offset
            return

        # Process
        try:
            self.handle_payment(msg.value)

            # Mark as processed BEFORE committing
            self.processed.set(message_id, "done", ttl=604800)
            self.consumer.commit()

        except RetriableError:
            # Don't mark as processed — allow retry
            raise

        except FatalError:
            # Mark as processed + dead-letter
            self.processed.set(message_id, "dead", ttl=604800)
            self.dead_letter_queue.send(msg)
            self.consumer.commit()
```

**Exactly-Once Semantics — Summary:**

```
Layer          Technique                    Guarantees
─────────────────────────────────────────────────────────────────
Producer       Idempotent producer          No duplicate sends
               (enable.idempotence=true)    within producer session

Broker         acks=all + ISR               No data loss
               min.insync.replicas=2

Consumer       Idempotency key + dedup      No duplicate processing
               Transactional outbox         No missed processing
                                             (at-least-once)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Idempotency key** | Understands it must be stored in DB with unique constraint; cached result returned on retry |
| **Transactional outbox** | Can explain why dual-writes fail and how outbox pattern solves it |
| **Dedup scope** | Knows dedup window must exceed max retry interval |
| **Failure modes** | Distinguishes between retriable vs non-retriable errors; dead-letter queues |

---

## 6. Circuit Breaker & Bulkhead Patterns

**Q:** "Your payment service depends on three external providers (Stripe, PayPal, Braintree). If Braintree starts timing out, it's exhausting your thread pool and causing Stripe calls to also fail. Design a solution using circuit breaker and bulkhead patterns."

**What They're Really Testing:** Whether you understand that circuit breakers prevent cascading failures and bulkheads isolate failure domains. They want to see you combine both patterns with concrete thresholds and recovery strategies.

### Answer

**Circuit Breaker State Machine:**

```
                    ┌─────────────────────┐
                    │      CLOSED         │
                    │  (normal operation) │
                    │  failure_count = 0   │
                    └──────────┬──────────┘
                               │ failure_threshold
                               │ exceeded (e.g., 5/10)
                               ▼
                    ┌─────────────────────┐
                    │       OPEN          │
                    │  (rejecting fast)    │
                    │  timeout = 30s       │
                    └──────────┬──────────┘
                               │ timeout expires
                               ▼
                    ┌─────────────────────┐
                    │     HALF-OPEN       │
                    │  (probing)          │
                    │  allow 1 request     │
                    └──────────┬──────────┘
                          ┌────┴────┐
                          │         │
                      success    failure
                          │         │
                          ▼         ▼
                    ┌─────────┐ ┌─────────┐
                    │ CLOSED   │ │ OPEN    │
                    └─────────┘ └─────────┘
```

```python
import time
import threading
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreaker:
    def __init__(self, name, failure_threshold=5, recovery_timeout=30, half_open_max=1):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_requests = 0
        self.lock = threading.Lock()

    def call(self, fn, fallback=None):
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self._transition_to_half_open()
            else:
                return self._fail_fast(fallback)

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_requests >= self.half_open_max:
                return self._fail_fast(fallback)
            self.half_open_requests += 1

        try:
            result = fn()
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            if fallback:
                return fallback(e)
            raise

    def _on_success(self):
        with self.lock:
            if self.state == CircuitState.HALF_OPEN:
                print(f"[{self.name}] HALF_OPEN → CLOSED (probe succeeded)")
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.half_open_requests = 0

    def _on_failure(self):
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                print(f"[{self.name}] CLOSED → OPEN (failures={self.failure_count})")
                self.state = CircuitState.OPEN

    def _transition_to_half_open(self):
        with self.lock:
            print(f"[{self.name}] OPEN → HALF_OPEN (timeout expired)")
            self.state = CircuitState.HALF_OPEN
            self.half_open_requests = 0

    def _fail_fast(self, fallback):
        if fallback:
            return fallback(CircuitBreakerOpenError(self.name))
        raise CircuitBreakerOpenError(self.name)

# Usage
stripe_cb = CircuitBreaker("stripe", failure_threshold=5, recovery_timeout=30)

def charge_with_stripe(amount):
    return stripe_cb.call(
        lambda: stripe_client.charge(amount),
        fallback=lambda e: {"status": "degraded", "provider": "stripe", "error": str(e)}
    )
```

**Bulkhead Pattern — Thread Pool Isolation:**

```
Without Bulkhead (shared thread pool):
┌─────────────────────────────────────────────┐
│            Thread Pool (10 threads)          │
├─────┬─────┬─────┬─────┬─────┬─────┬─────┬─►│
│     │     │     │     │     │     │     │   │
│ S1  │ S2  │ S3  │ S4  │ S5  │ S6  │ S7  │   │
│(OK) │(OK) │(OK) │(OK) │(OK) │(OK) │(OK) │   │
├─────┴─────┴─────┴─────┴─────┴─────┴─────┴─►│
│  ⚠ Braintree (slow) occupies 3 threads      │
│  → Stripe requests can't get threads         │
└─────────────────────────────────────────────┘

With Bulkhead (isolated pools):
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Stripe Pool     │  │ PayPal Pool     │  │ Braintree Pool  │
│ (4 threads)     │  │ (3 threads)     │  │ (3 threads)     │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ S1 S2 S3 S4     │  │ P1 P2 P3        │  │ B1 B2 B3        │
│ (all working)   │  │ (all working)   │  │ ⚠ all stuck!   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
                                            But Stripe/PayPal
                                            are still working!
```

```python
from concurrent.futures import ThreadPoolExecutor
import time

class Bulkhead:
    def __init__(self, name, max_concurrent=3, queue_size=10):
        self.name = name
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self.semaphore = Semaphore(max_concurrent + queue_size)

    def call(self, fn, timeout=5):
        if not self.semaphore.acquire(timeout=1):  # Wait max 1s for queue slot
            raise BulkheadFullError(f"{self.name} bulkhead is full")

        try:
            future = self.executor.submit(fn)
            return future.result(timeout=timeout)
        except TimeoutError:
            raise BulkheadTimeoutError(f"{self.name} timed out after {timeout}s")
        finally:
            self.semaphore.release()

# Usage
class PaymentOrchestrator:
    def __init__(self):
        self.bulkheads = {
            "stripe": Bulkhead("stripe", max_concurrent=4, queue_size=20),
            "paypal": Bulkhead("paypal", max_concurrent=3, queue_size=15),
            "braintree": Bulkhead("braintree", max_concurrent=3, queue_size=10),
        }
        self.circuit_breakers = {
            "stripe": CircuitBreaker("stripe"),
            "paypal": CircuitBreaker("paypal"),
            "braintree": CircuitBreaker("braintree"),
        }

    def charge(self, provider, amount):
        cb = self.circuit_breakers[provider]
        bh = self.bulkheads[provider]

        return cb.call(
            lambda: bh.call(lambda: self._call_provider(provider, amount)),
            fallback=lambda e: self._fallback_to_next_provider(provider, amount, e)
        )

    def _call_provider(self, provider, amount):
        clients = {
            "stripe": stripe_client,
            "paypal": paypal_client,
            "braintree": braintree_client,
        }
        return clients[provider].charge(amount)

    def _fallback_to_next_provider(self, failed_provider, amount, error):
        logger.warning(f"{failed_provider} failed, trying fallback: {error}")
        for provider in ["stripe", "paypal", "braintree"]:
            if provider != failed_provider:
                try:
                    return self.charge(provider, amount)
                except Exception:
                    continue
        raise AllProvidersFailed("All payment providers unavailable")
```

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/arch-circuit-breaker.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Circuit Breaker Pattern — Closed → Open → Half-Open states protecting against cascading failures. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Circuit states** | Explains Closed → Open → Half-Open with concrete thresholds |
| **Bulkhead isolation** | Uses separate thread pools/semaphores per dependency |
| **Combined pattern** | Applies circuit breaker ON TOP OF bulkhead (failure detection + isolation) |
| **Fallback strategy** | Has cascading fallback to other providers |
| **Recovery** | Half-Open probing with gradual recovery, not immediate reset |

---

## 7. Graceful Degradation & Fallbacks

**Q:** "Your recommendation service depends on a real-time ML model. If the model service goes down, what happens to your product pages? Design a graceful degradation strategy that keeps the site functional."

**What They're Really Testing:** Whether you distinguish between critical-path and non-critical-path dependencies, and can design fallback chains that degrade features without crashing the whole page.

### Answer

**Degradation Hierarchy:**

```
Product Page Dependencies (ranked by criticality):

CRITICAL (page cannot render without these):
  └── Product catalog DB
  └── Price service

IMPORTANT (degrade gracefully):
  └── Inventory/stock status       → show "Check availability"
  └── User session/auth            → show cached/guest view

NICE-TO-HAVE (silently disable):
  └── Personalized recommendations → show generic "Trending"
  └── Reviews & ratings            → show cached snapshot
  └── Recently viewed              → hide section
  └── ML-powered search ranking    → fall back to keyword match
```

```python
class ProductPageService:
    def __init__(self):
        self.cache = RedisCache()
        self.catalog = CatalogClient()
        self.inventory = InventoryClient()
        self.recommendations = RecommendationClient()
        self.reviews = ReviewClient()

    def get_product_page(self, product_id: str, user_id: str | None):
        # 1. Critical path — no fallback, must succeed
        product = self.catalog.get_product(product_id)

        # 2. Inventory — degraded fallback
        inventory = self._get_inventory_with_fallback(product_id)

        # 3. Recommendations — degraded fallback
        recommendations = self._get_recommendations_with_fallback(user_id, product_id)

        # 4. Reviews — degraded fallback
        reviews = self._get_reviews_with_fallback(product_id)

        return self._assemble_page(product, inventory, recommendations, reviews)

    def _get_inventory_with_fallback(self, product_id: str) -> dict:
        try:
            return self.inventory.check_stock(product_id)
        except (TimeoutError, ConnectionError):
            # Fallback 1: Try cache
            cached = self.cache.get(f"inventory:{product_id}")
            if cached:
                return cached

            # Fallback 2: Return stale/unknown status
            logger.warning(f"Inventory unavailable for {product_id}, showing unknown")
            return {
                "in_stock": None,        # Frontend shows "Check availability"
                "quantity": 0,
                "estimated_delivery": None
            }

    def _get_recommendations_with_fallback(self, user_id: str | None, product_id: str):
        if not user_id:
            return self._get_generic_recommendations()

        try:
            return self.recommendations.get_personalized(user_id, product_id)
        except Exception:
            # Fallback 1: Cached recommendations
            cached = self.cache.get(f"recs:{user_id}:{product_id}")
            if cached:
                return cached

            # Fallback 2: Generic trending products
            return self._get_generic_recommendations()

    def _get_generic_recommendations(self):
        # Pre-computed, refreshed every hour
        return self.cache.get("trending:products") or []

    def _get_reviews_with_fallback(self, product_id: str):
        try:
            return self.reviews.get_reviews(product_id)
        except Exception:
            # Fallback: Cached snapshot (stale, but better than nothing)
            cached = self.cache.get(f"reviews:{product_id}:snapshot")
            if cached:
                logger.info(f"Serving stale reviews for {product_id}")
                return cached
            # Last resort: No reviews section
            return []
```

**Hystrix-Inspired Fallback Chain:**

```python
# Netflix Hystrix (now in maintenance) / Resilience4j patterns

class RecommendationCommand:
    """Encapsulates a fallback chain for a single dependency."""

    FALLBACK_CHAIN = [
        ("primary_ml", lambda: recommendations.ml_model(user_id, product_id), 100),
        ("cached", lambda: cache.get(f"recs:{user_id}:{product_id}"), 50),
        ("trending_fallback", lambda: get_trending_products(), 20),
    ]

    def execute(self, user_id, product_id):
        errors = []
        for name, fn, timeout_ms in self.FALLBACK_CHAIN:
            try:
                result = self._with_timeout(fn, timeout_ms / 1000)
                if result:
                    logger.info(f"Recommendation via: {name}")
                    return result
            except Exception as e:
                errors.append((name, str(e)))
                continue

        # All fallbacks exhausted — return empty
        logger.error(f"All fallbacks failed: {errors}")
        return []
```

**Timeout Budgets & Priority Queuing:**

```python
class DegradationManager:
    """
    Manages timeout budgets for page assembly.
    If the total page assembly time exceeds 500ms,
    non-critical requests are cancelled.

    E.g., recommendations had 200ms budget → if exceeded,
    skip it and show fallback.
    """

    def __init__(self):
        self.budgets = {
            "catalog": 100,         # ms
            "inventory": 100,
            "price": 50,
            "recommendations": 150,  # Can be skipped
            "reviews": 100,          # Can be skipped
        }
        self.total_budget = 500     # ms
        self.start_time = None

    def can_afford(self, dependency: str) -> bool:
        elapsed = (time.time() - self.start_time) * 1000
        remaining = self.total_budget - elapsed
        return remaining >= self.budgets.get(dependency, 0)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Criticality tiers** | Separates dependencies into must-have vs nice-to-have |
| **Fallback chain** | Multiple fallbacks: primary → cache → generic → empty |
| **Stale data tolerance** | Understands when stale data is acceptable and for how long |
| **Timeout budgets** | Manages page assembly time; cancels non-critical requests |

---

## 8. Observability: Logging, Metrics, Tracing

**Q:** "Your platform has 50 microservices. A customer reports that their order was charged but never shipped. Walk me through how you'd debug this using logs, metrics, and traces. What specific tools and data formats would you use?"

**What They're Really Testing:** Whether you understand the three pillars of observability and can connect them to debug production issues. They want to see you trace a request across services using correlation IDs, RED metrics, and distributed tracing.

### Answer

**The Three Pillars in Action:**

```
┌─────────────────────────────────────────────────────────┐
│                   OBSERVABILITY TRIFECTA                │
├────────────┬────────────────────┬───────────────────────┤
│  LOGS      │    METRICS         │     TRACES            │
├────────────┼────────────────────┼───────────────────────┤
│ Structured │ RED:               │ Distributed spans:    │
│ JSON lines │   Rate             │   order-service       │
│ {           │   Errors           │     → payment-svc    │
│   ts,       │   Duration         │       → stripe-api   │
│   level,    │ USE:               │     → shipping-svc   │
│   msg,      │   Utilization      │       → warehouse    │
│   trace_id, │   Saturation       │                       │
│   service,  │   Errors           │ OpenTelemetry:        │
│   duration  │                    │   W3C traceparent     │
│ }           │ Prometheus +       │   header propagation  │
│             │ Grafana dashboards │                       │
└────────────┴────────────────────┴───────────────────────┘
```

**1. Structured Logging — The Right Way:**

```python
import structlog
from contextvars import ContextVar

trace_id_var = ContextVar("trace_id", default=None)

# DON'T do this:
logger.info(f"Order {order_id} created for user {user_id}")
# → Can't search, can't filter, fragile parsing

# DO this:
logger.info("order.created", extra={
    "order_id": "ord_123",
    "user_id": "usr_456",
    "amount": 100.00,
    "currency": "USD",
    "payment_method": "visa",
    "trace_id": "abc123",
    "service": "order-service",
    "version": "1.2.3",
})
# → Output: {"event": "order.created", "order_id": "ord_123", ...}
# → ElasticSearch: filter by order_id, group by trace_id

# Context propagation with structlog:
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
)
```

**2. RED Metrics — Service Health at a Glance:**

```python
from prometheus_client import Counter, Histogram, Gauge

# RED: Rate, Errors, Duration
orders_total = Counter("orders_total", "Total orders", ["status"])
order_duration = Histogram(
    "order_duration_seconds",
    "Order processing time",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
active_requests = Gauge("active_requests", "Currently processing requests")

# Per-endpoint metrics
request_rate = Counter("http_requests_total", "HTTP requests", ["method", "path", "status"])
request_latency = Histogram(
    "http_request_duration_seconds",
    "HTTP latency",
    ["method", "path"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0],
)

# USE: Utilization, Saturation, Errors (for infrastructure)
cpu_usage = Gauge("node_cpu_usage_percent", "CPU utilization", ["host"])
db_connections = Gauge("db_connections_active", "Active DB connections")
queue_depth = Gauge("queue_depth", "Message queue depth")

# Production SLIs:
#   Order creation latency: p99 < 2s
#   Payment success rate: > 99.5%
#   Error rate: < 0.1%
#   Queue depth: < 1000
```

**3. Distributed Tracing — Following a Request Across Services:**

```
Trace: abc123 (order creation)
│
├── Span: POST /orders [order-service, 245ms]
│   ├── Span: validate_user [order-service → auth-service, 50ms]
│   │   └── Tags: user_id="usr_456", auth_method="token"
│   │
│   ├── Span: check_inventory [order-service → inventory-service, 30ms]
│   │   └── Tags: sku="SKU-001", quantity=2, in_stock=true
│   │
│   ├── Span: process_payment [order-service → payment-service, 145ms]
│   │   ├── Span: authorize [payment-service → stripe-api, 120ms]
│   │   │   └── Tags: amount=100.00, currency="USD", status="authorized"
│   │   └── Span: update_balance [payment-service → ledger-db, 20ms]
│   │
│   └── Span: create_shipment [order-service → shipping-service, 20ms]
│       └── Span: reserve_package [shipping-service → warehouse-db, 15ms]
│           └── Tags: warehouse_id="WH-01", estimated_ship="2026-07-20"
│
└── Trace Tags: order_id="ord_123", user_id="usr_456", total=100.00
```

**OpenTelemetry Implementation:**

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp import OTLPSpanExporter
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Setup
provider = TracerProvider()
processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otel-collector:4317"))
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

# Auto-instrument HTTP clients
RequestsInstrumentor().instrument()

# Manual span creation
tracer = trace.get_tracer("order-service")

def process_order(order_id: str):
    with tracer.start_as_current_span("process_order") as span:
        span.set_attribute("order_id", order_id)

        # Span context propagates automatically via W3C traceparent
        with tracer.start_as_current_span("validate_payment") as child_span:
            child_span.set_attribute("amount", 100.00)
            result = payment_client.charge(order_id)

        if result["status"] == "failed":
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            span.record_exception(PaymentError(result["reason"]))
```

**Debugging the "Charged but Not Shipped" Scenario:**

```python
# Step 1: Find the trace
trace_id = query_logs(
    "SELECT trace_id FROM orders WHERE order_id = 'ord_123'"
)

# Step 2: Trace the full request
spans = query_traces(trace_id)
# → Shows: authorized at 10:00:05, BUT shipping never called
#   No "create_shipment" span exists!

# Step 3: Check order-service logs at 10:00:05
log_entry = query_logs(
    service="order-service",
    trace_id=trace_id,
)
# → "Failed to publish OrderPlaced event: Kafka timeout"
#    Order was charged, but the event was never sent to shipping

# Step 4: Root cause
# → The order-service's Kafka producer had a connection timeout
# → No dead-letter queue or retry mechanism
# → The order was committed (payment captured) but event was lost

# Step 5: Fix
# → Implement transactional outbox pattern
#   (write event to DB in same txn as order update)
# → Add DLQ for failed events with alerting
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Structured logging** | JSON format with trace_id, service, and correlation IDs |
| **RED metrics** | Monitors Rate/Errors/Duration per endpoint |
| **USE metrics** | Monitors Utilization/Saturation/Errors for infrastructure |
| **Distributed tracing** | Uses OpenTelemetry/W3C traceparent; can trace across services |
| **Debugging workflow** | Connects logs + metrics + traces to pinpoint root cause |
| **SLIs/SLOs** | Defines concrete targets (p99 < 2s, error rate < 0.1%) |

---

## 9. Saga Pattern: Choreography vs Orchestration

**Q:** "Design an order fulfillment flow: reserve inventory → charge payment → schedule shipment. If payment fails, release inventory. If shipment fails, refund payment. Compare choreography-based (event-driven) vs orchestration-based (central coordinator) sagas."

**What They're Really Testing:** Whether you understand sagas as a pattern for distributed transactions without distributed locking. They want to see you handle compensating transactions and compare the two approaches with concrete trade-offs.

### Answer

**Saga Structure:**

```
Saga: Order Fulfillment

Forward Operations:
  1. Reserve Inventory    → compensate: Release Inventory
  2. Charge Payment       → compensate: Refund Payment
  3. Schedule Shipment    → compensate: Cancel Shipment

If any step fails → execute compensating transactions
in REVERSE order (rollback).
```

**Approach 1: Choreography (Event-Driven)**

```
┌─────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Order  │     │Inventory │     │ Payment  │     │ Shipping │
│ Service │     │ Service  │     │ Service  │     │ Service  │
└────┬────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
     │               │                │                │
     │ OrderCreated   │                │                │
     │──────────────►│                │                │
     │               │ InventoryReserved               │
     │               │────────────────────────────────►│ (1)
     │               │                │                │
     │              Payment Charged                   │
     │               │◄───────────────│                │ (2)
     │               │                │                │
     │               │               ShipmentScheduled │
     │               │               │◄───────────────│ (3)
     │               │                │                │
     │               │   OrderCompleted                │
     │◄──────────────│─────────────────────────────────│
```

```python
# Choreography: Each service listens for events and emits new events
# No central coordinator

# Order Service
class OrderSaga:
    def create_order(self):
        order = self.db.create_order(status="PENDING")
        self.event_bus.publish(OrderCreated(order.id, order.items, order.total))
        # Done — the rest is reactive

    def on_order_completed(self, event: OrderCompleted):
        self.db.update_order(event.order_id, status="COMPLETED")

    def on_order_failed(self, event: OrderFailed):
        self.db.update_order(event.order_id, status="FAILED")

# Inventory Service
class InventorySaga:
    @subscribe(OrderCreated)
    def reserve(self, event: OrderCreated):
        try:
            self.inventory.reserve(event.items)
            self.event_bus.publish(InventoryReserved(event.order_id))
        except InsufficientStock:
            self.event_bus.publish(OrderFailed(event.order_id, "out_of_stock"))

    @subscribe(PaymentFailed)
    def release(self, event: PaymentFailed):
        # Compensating transaction
        self.inventory.release(event.order_id)
        self.event_bus.publish(InventoryReleased(event.order_id))

# Payment Service
class PaymentSaga:
    @subscribe(InventoryReserved)
    def charge(self, event: InventoryReserved):
        try:
            self.payment.charge(event.order_id, event.amount)
            self.event_bus.publish(PaymentCharged(event.order_id))
        except PaymentDeclined:
            self.event_bus.publish(PaymentFailed(event.order_id))

    @subscribe(ShipmentFailed)
    def refund(self, event: ShipmentFailed):
        # Compensating transaction
        self.payment.refund(event.order_id)
        self.event_bus.publish(PaymentRefunded(event.order_id))

# Shipping Service
class ShippingSaga:
    @subscribe(PaymentCharged)
    def schedule(self, event: PaymentCharged):
        try:
            self.shipping.schedule(event.order_id, event.address)
            self.event_bus.publish(ShipmentScheduled(event.order_id))
        except ShippingUnavailable:
            self.event_bus.publish(ShipmentFailed(event.order_id))
```

**Approach 2: Orchestration (Central Coordinator)**

```
┌──────────────────────────────────────────────────────┐
│              Saga Orchestrator                       │
│  ┌────────────┐  ┌────────────┐  ┌──────────────┐   │
│  │ Step 1:    │  │ Step 2:    │  │ Step 3:      │   │
│  │ Reserve    │──► Charge     │──► Schedule     │   │
│  │ Inventory  │  │ Payment    │  │ Shipment     │   │
│  │  (call     │  │  (call     │  │  (call       │   │
│  │   Inventory│  │   Payment  │  │   Shipping)  │   │
│  │   Service) │  │   Service) │  │              │   │
│  └─────┬──────┘  └─────┬──────┘  └──────┬───────┘   │
│        │               │                │           │
│        ▼               ▼                ▼           │
│  ┌─────────────────────────────────────────────┐   │
│  │ Compensating Transactions (if any step fails) │   │
│  │ Step 3 fail → refund payment → release inv   │   │
│  └─────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```

```python
class SagaOrchestrator:
    """Central coordinator — holds saga state and manages execution."""

    def __init__(self):
        self.saga_store = PostgreSQL()     # Persists saga state
        self.inventory = InventoryClient()
        self.payment = PaymentClient()
        self.shipping = ShippingClient()

    def execute_order_saga(self, order_id: str, items: list, amount: float, address: str):
        saga = Saga(order_id, steps=[
            SagaStep(
                name="reserve_inventory",
                action=lambda: self.inventory.reserve(items),
                compensate=lambda: self.inventory.release(order_id),
            ),
            SagaStep(
                name="charge_payment",
                action=lambda: self.payment.charge(order_id, amount),
                compensate=lambda: self.payment.refund(order_id),
            ),
            SagaStep(
                name="schedule_shipment",
                action=lambda: self.shipping.schedule(order_id, address),
                compensate=lambda: self.shipping.cancel(order_id),
            ),
        ])
        self.saga_store.save(saga)
        return self._execute(saga)

    def _execute(self, saga: Saga):
        completed = []

        for step in saga.steps:
            try:
                step.action()
                completed.append(step)
                saga.current_step = step.name
                self.saga_store.save(saga)
            except Exception as e:
                logger.error(f"Saga {saga.id} failed at {step.name}: {e}")
                # Compensate in REVERSE order
                self._compensate(completed[::-1])
                saga.status = "FAILED"
                self.saga_store.save(saga)
                raise SagaFailedError(saga.id, step.name, e)

        saga.status = "COMPLETED"
        self.saga_store.save(saga)

    def _compensate(self, steps_to_undo: list[SagaStep]):
        for step in steps_to_undo:
            try:
                step.compensate()
                logger.info(f"Compensation succeeded for {step.name}")
            except Exception as e:
                # Compensation failure — needs manual intervention
                logger.error(f"COMPENSATION FAILED for {step.name}: {e}")
                self._alert_oncall(saga_id, step.name, str(e))
```

**Comparison:**

```
Characteristic        Choreography                  Orchestration
──────────────────────────────────────────────────────────────────
Coordination          Event-driven (indirect)       Central coordinator (direct)
Complexity            Low per-service               Higher coordinator, simpler services
Failure handling      Implicit (events flow)        Explicit (compensation steps)
Visibility            Harder (scattered events)     Easier (single saga store)
Coupling              Tight to event schema         Loose (services only know coordinator)
Testing               Complex (many moving parts)   Simpler (mock coordinator)
Latency               Lower (direct events)         Slightly higher (coordinator hop)
When to use           Simple linear workflows       Complex branching workflows
```

**Choosing Between Them:**

```python
# Use CHOREOGRAPHY when:
# - 2-3 simple steps, clear linear flow
# - Each step has clear compensating event
# - Teams own their event schema independently
# Example: User registration → Send welcome email → Create default workspace

# Use ORCHESTRATION when:
# - Complex branching (if/then/else in saga)
# - Need visibility into long-running sagas
# - Multiple teams, need strict coordination
# Example: Order fulfillment with inventory checks,
#          payment routing, shipping carrier selection
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Compensating transactions** | Understands each forward operation needs a reverse operation |
| **Choreography vs orchestration** | Can compare both approaches with trade-offs |
| **Failure handling** | Saga fails at step 3 → compensates step 2, then step 1 (reverse order) |
| **State persistence** | Saves saga progress to DB — survives crashes |
| **Compensation failure** | Knows when compensation fails, needs manual/alert intervention |

---

## 10. Backpressure & Reactive Systems

**Q:** "Your order service processes 10,000 orders/minute from the web tier, but the downstream inventory service can only handle 2,000 updates/minute. Design a backpressure mechanism that prevents inventory service from crashing."

**What They're Really Testing:** Whether you understand the producer-consumer throughput mismatch problem and can design pull-based backpressure, not just rate limiting.

### Answer

**The Problem:**

```
Producer (Web Tier): 10,000 req/min  ──►  Consumer (Inventory): 2,000 req/min
                                                  │
                        Unbounded queue grows ────►│
                        until memory OOM           │
                                                   ▼
                                              (crashes)
```

**Solution 1: Pull-Based Backpressure (Reactive Streams)**

```
Reactive Streams Protocol:

Web Tier                  Queue                   Inventory
  │                         │                        │
  │                         │◄──── request(100) ─────│
  │──── send(100 items) ──►│                        │
  │   (only sends 100)     │── process 100 ────────►│
  │                         │                        │
  │                         │◄──── request(50) ─────│
  │──── send(50 items) ───►│                        │
  │                         │── process 50 ────────►│
```

```python
import asyncio
from asyncio import Queue

class ReactiveBuffer:
    """Implements Reactive Streams request(N) semantics."""

    def __init__(self, consumer, max_buffer=1000):
        self.consumer = consumer
        self.queue = Queue(maxsize=max_buffer)
        self.demand = 0  # How many items consumer wants
        self._running = False

    async def on_request(self, n: int):
        """Called by consumer to request N items."""
        self.demand += n
        if not self._running:
            self._running = True
            asyncio.create_task(self._drain())

    async def on_next(self, item):
        """Called by producer to send an item."""
        if self.demand <= 0:
            # Backpressure — can't accept more
            raise BufferOverflowError("No demand — reject or buffer")
        await self.queue.put(item)
        self.demand -= 1

    async def _drain(self):
        while self.queue.qsize() > 0 or self.demand > 0:
            items = []
            for _ in range(min(self.demand, self.queue.qsize())):
                items.append(await self.queue.get())
            if items:
                await self.consumer.process(items)

# Usage
class InventoryConsumer:
    def __init__(self):
        self.buffer = ReactiveBuffer(self, max_buffer=500)
        self.processing_rate = 2000  # items/minute

    async def process(self, items):
        # Process inventory updates
        for item in items:
            await self.db.update_stock(item)
        # Request more
        await self.buffer.on_request(len(items))
```

**Solution 2: Bounded Queue + Load Shedding**

```python
class BoundedQueue:
    """Fixed-size queue with configurable overflow behavior."""

    def __init__(self, max_size=1000, overflow_policy="drop_newest"):
        self.queue = asyncio.Queue(maxsize=max_size)
        self.overflow_policy = overflow_policy
        self.dropped_count = 0

    async def try_put(self, item):
        try:
            self.queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            self.dropped_count += 1
            if self.overflow_policy == "drop_oldest":
                # Remove oldest item to make space
                try:
                    self.queue.get_nowait()
                    self.queue.put_nowait(item)
                    return True
                except asyncio.QueueEmpty:
                    return False
            elif self.overflow_policy == "reject":
                # Send error to caller
                raise BackpressureError("Service busy, try again")
            return False

    @property
    def utilization(self) -> float:
        return self.queue.qsize() / self.queue.maxsize

# Monitoring queue depth
class BackpressureMonitor:
    """Alerts when backpressure builds up."""

    def check(self, queue: BoundedQueue):
        utilization = queue.utilization
        if utilization > 0.9:
            # Critical — scale up consumer
            self.alert("Queue 90% full — add more consumers")
        elif utilization > 0.7:
            # Warning — approaching limit
            self.logger.warning(f"Queue utilization: {utilization:.0%}")
```

**Solution 3: Adaptive Rate Limiting**

```python
class AdaptiveRateLimiter:
    """
    Dynamically adjusts producer rate based on consumer health.

    Feedback loop:
      Consumer latency ↑ → reduce producer rate
      Consumer latency ↓ → increase producer rate
    """

    def __init__(self, target_latency_ms=100, min_rate=100, max_rate=10000):
        self.target_latency = target_latency_ms
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.current_rate = max_rate

    def update_rate(self, observed_latency_ms: float):
        # PID controller-inspired adjustment
        error = self.target_latency - observed_latency_ms
        adjustment = error / self.target_latency  # Normalized [-1, 1]

        if observed_latency_ms > self.target_latency * 1.5:
            # Latency too high — aggressive reduction
            self.current_rate *= (1 + adjustment)  # e.g., * 0.5
        elif observed_latency_ms < self.target_latency * 0.5:
            # Latency low — increase rate
            self.current_rate *= (1 - adjustment * 0.5)  # * 1.25

        self.current_rate = max(self.min_rate, min(self.max_rate, self.current_rate))

    def should_accept(self) -> bool:
        # Token bucket approach
        return random.random() < (self.current_rate / self.max_rate)
```

**Backpressure Strategies Comparison:**

```
Strategy            How It Works              Best For
────────────────────────────────────────────────────────────────
Reactive Streams    Consumer requests(N)      Reliable processing,
(request(N))                                  precise control

Bounded Queue       Fixed-size buffer,        Bursty traffic,
                    drop if full              tolerable data loss

Adaptive Rate       Adjust producer rate      Variable consumer
Limiting            based on feedback         capacity

Circuit Breaker     Reject all when           Complete consumer
                    unhealthy                 failure

Load Shedding       Drop low-priority         Tiered service
                    requests first            levels
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pull-based flow** | Consumer requests N items, producer sends at most N |
| **Bounded queues** | Fixed-size buffer prevents OOM |
| **Feedback loop** | Consumer health metrics adjust producer rate |
| **Overflow policy** | Explicit strategy for queue-full scenarios (drop, reject, shed) |
| **Monitoring** | Tracks queue depth, utilization, dropped count |

---

## 11. Migration Strategies: Strangler Fig

**Q:** "Your team has a 10-year-old monolith processing 1M orders/day. You need to migrate to microservices without downtime. Walk me through your migration strategy using the Strangler Fig pattern."

**What They're Really Testing:** Whether you understand incremental migration vs big-bang rewrites. They want to see concrete routing, data migration, and rollback strategies.

### Answer

**Strangler Fig Pattern — Three Phases:**

```
Phase 1: Intercept & Route
                          ┌─────────────────┐
Client ──► Proxy ──┬────►│  Monolith       │
(Legacy URL)       │     │  (handles ALL)  │
                   │     └─────────────────┘
                   │
                   └────►│  New Service    │  (new feature only)
                         └─────────────────┘

Phase 2: Incremental Migration
                          ┌─────────────────┐
Client ──► Proxy ──┬────►│  Monolith       │
                   │     │  (orders ONLY)   │
                   │     └─────────────────┘
                   │
                   ├────►│  Auth Service   │  (migrated)
                   ├────►│  Catalog        │  (migrated)
                   └────►│  Payments       │  (migrated)

Phase 3: Monolith Retired
                          ┌─────────────────┐
Client ──► Proxy ──┬────►│  Auth Service   │
                   ├────►│  Catalog        │
                   ├────►│  Orders         │
                   └────►│  Payments       │
                         └─────────────────┘
             (Monolith decommissioned)
```

**Implementation — Proxy Layer (Feature Flags + Routing):**

```python
class MigrationProxy:
    """
    Routes traffic to monolith or new service based on feature flag.
    Can route by user_id, percentage, or specific criteria.
    """

    def __init__(self):
        self.migration_config = self._load_config()

    def route_request(self, request):
        path = request.path
        user_id = request.headers.get("X-User-Id")

        # Check if this path is migrated for this user
        migration = self.migration_config.get_migration(path)

        if not migration:
            # No migration configured → monolith
            return self._call_monolith(request)

        if migration.should_route(user_id):
            # Route to new service
            return self._call_microservice(request, migration.target_service)
        else:
            # Still on monolith
            return self._call_monolith(request)

    def _call_monolith(self, request):
        return httpx.post(
            "http://monolith.internal",
            content=request.body,
            headers=request.headers,
        )

    def _call_microservice(self, request, service):
        return httpx.post(
            f"http://{service}.internal",
            content=request.body,
            headers=self._transform_headers(request, service),
        )

# Configuration (canary deployment)
canary_config = {
    "routes": [
        {
            "path": "/api/orders/**",
            "target": "orders-service",
            "rollout": {"type": "percentage", "value": 5},          # 5% of traffic
            # "rollout": {"type": "user_ids", "values": ["1", "42"]},  # Specific users
            # "rollout": {"type": "internal_only", "ips": ["10.x.x.x"]}, # Internal testing
        }
    ]
}
```

**Data Migration — Dual Writes & Verification:**

```python
class DataMigrator:
    """
    Strategy: Write to both systems, read from new system.
    Backfill historical data in batches.
    """

    def __init__(self):
        self.legacy_db = MySQL()
        self.new_db = PostgreSQL()

    def dual_write(self, order_data):
        """Write to both databases in the same transaction."""
        order_id = self.legacy_db.insert("orders", order_data)
        self.new_db.insert("orders", {
            **order_data,
            "legacy_id": order_id,  # Link for verification
            "migrated_at": datetime.utcnow(),
        })
        return order_id

    def verify_consistency(self, batch_size=1000):
        """Verify that data matches between old and new systems."""
        last_id = 0
        while True:
            batch = self.legacy_db.query(f"""
                SELECT * FROM orders
                WHERE id > {last_id}
                ORDER BY id
                LIMIT {batch_size}
            """)
            if not batch:
                break

            for legacy_order in batch:
                new_order = self.new_db.query(
                    "SELECT * FROM orders WHERE legacy_id = :id",
                    {"id": legacy_order["id"]},
                )
                if not new_order:
                    self._report_missing(legacy_order["id"])
                elif not self._matches(legacy_order, new_order):
                    self._report_mismatch(legacy_order["id"], legacy_order, new_order)

            last_id = batch[-1]["id"]

    def backfill_history(self, start_date, end_date):
        """Batch migrate historical data (run during low traffic)."""
        for batch in self.legacy_db.stream_orders(start_date, end_date, batch_size=500):
            for order in batch:
                self.new_db.insert("orders", self._transform(order))
            self._checkpoint(start_date, batch[-1]["created_at"])
```

**Rollback Strategy:**

```python
class RollbackManager:
    """
    Every migration has a rollback plan.
    If errors exceed threshold → revert to monolith.
    """

    def __init__(self, proxy: MigrationProxy):
        self.proxy = proxy
        self.metrics = {
            "monolith_errors": 0,
            "new_errors": 0,
            "total_requests": 0,
        }

    def record_result(self, target: str, success: bool):
        self.metrics["total_requests"] += 1
        if target == "monolith":
            self.metrics["monolith_errors"] += 0 if success else 1
        else:
            self.metrics["new_errors"] += 0 if success else 1

    def should_rollback(self) -> bool:
        if self.metrics["total_requests"] < 100:
            return False  # Not enough data

        new_error_rate = self.metrics["new_errors"] / self.metrics["total_requests"]
        monolith_error_rate = self.metrics["monolith_errors"] / self.metrics["total_requests"]

        # Rollback if new service is 2x worse than monolith
        return new_error_rate > monolith_error_rate * 2 or new_error_rate > 0.05

    def rollback(self, path: str):
        logger.warning(f"Rolling back {path} — error rate too high")
        self.proxy.migration_config.disable_migration(path)
        # Alert on-call
        self._alert(f"Rolled back {path}")
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Incremental approach** | Migrates one feature at a time, not big-bang |
| **Proxy/routing** | Feature flags or proxy layer to split traffic |
| **Dual writes** | Writes to both systems during migration for safety |
| **Verification** | Compares old vs new data for consistency |
| **Rollback** | Automatic rollback if error rate exceeds threshold |
| **Backfill** | Batches historical data migration during low traffic |

---

## 12. Configuration Management & Feature Flags

**Q:** "Design a configuration management system for 200 microservices across 5 environments (dev, staging, prod-us, prod-eu, prod-asia). How do you manage feature flags, rollouts, and detect configuration drift?"

**What They're Really Testing:** Whether you understand that configuration is code and should follow the same CI/CD pipelines. They want to see GitOps-based config management with drift detection.

### Answer

**Architecture: Centralized Config with GitOps**

```
                           ┌─────────────────────┐
                           │  Git Repository      │
                           │  (configs as code)   │
                           │                     │
                           │  dev/config.yaml     │
                           │  staging/config.yaml │
                           │  prod/config.yaml    │
                           └──────────┬──────────┘
                                      │
                                      │ git push
                                      ▼
                          ┌─────────────────────┐
                          │  Config Controller   │
                          │  (ArgoCD / Flux)     │
                          │                     │
                          │  Syncs config from   │
                          │  git to Etcd/Consul  │
                          └──────────┬──────────┘
                                      │
                          ┌───────────┴───────────┐
                          │                       │
                          ▼                       ▼
                   ┌──────────────┐      ┌──────────────┐
                   │  Etcd/Consul │      │  Feature Flag │
                   │  (key-value) │      │  Service      │
                   │              │      │  (LaunchDarkly│
                   │  /config/    │      │   /Flagsmith) │
                   │   prod/db/   │      │              │
                   │   port: 5432 │      │  flags:       │
                   └──────┬───────┘      │  new-checkout:│
                          │              │    prod: 10%  │
                          │              └──────┬───────┘
                          │                     │
                          └─────────┬───────────┘
                                    │
                          ┌─────────▼─────────┐
                          │  Service Sidecars  │
                          │  (config watchers) │
                          │                    │
                          │  Watch config      │
                          │  changes → hot     │
                          │  reload            │
                          └────────────────────┘
```

**1. Configuration As Code (GitOps):**

```yaml
# prod/config.yaml — Centralized config
database:
  host: "postgres-cluster.prod.svc"
  port: 5432
  pool_size: 20
  max_connections: 100

redis:
  host: "redis-cluster.prod.svc"
  port: 6379
  timeout_ms: 500

observability:
  log_level: "INFO"
  tracing_sample_rate: 0.1   # 10% sampling in prod
  metrics_interval: 15        # seconds
```

```python
class ConfigManager:
    """Hot-reloads config from Etcd on changes."""

    def __init__(self, service_name: str, environment: str):
        self.service = service_name
        self.env = environment
        self.config = {}
        self._watch_config()

    def _watch_config(self):
        config_path = f"/config/{self.env}/{self.service}"

        # Initial load
        self.config = self._load_from_etcd(config_path)

        # Watch for changes
        def on_change(new_config):
            logger.info(f"Config changed: {new_config}")
            self.config = new_config
            # Trigger hot-reload hooks
            self._on_config_changed()

        self.etcd.watch(config_path, on_change)

    def get(self, key: str, default=None):
        # Support nested keys: "database.pool_size"
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default
```

**2. Feature Flags — Gradual Rollouts:**

```python
class FeatureFlagService:
    """
    Manages feature flags with gradual rollout, A/B testing,
    and targeted activation.
    """

    def __init__(self, store: RedisCache):
        self.store = store

    def is_enabled(self, flag: str, user: UserContext) -> bool:
        flag_config = self.store.hgetall(f"flag:{flag}")
        if not flag_config:
            return False

        # 1. Kill switch — override everything
        if flag_config.get("kill"):
            return False

        # 2. User-specific override
        if user.id in flag_config.get("user_whitelist", []):
            return True

        # 3. Environment-based
        if flag_config.get("environment") and user.environment != flag_config["environment"]:
            return False

        # 4. Percentage rollout
        rollout_pct = int(flag_config.get("rollout_percentage", 0))
        if rollout_pct < 100:
            # Consistent hashing — same user always gets same result
            hash_value = hash(f"{flag}:{user.id}") % 100
            if hash_value >= rollout_pct:
                return False

        # 5. Target groups
        if "targeting" in flag_config:
            for rule in flag_config["targeting"]:
                if self._matches_rule(rule, user):
                    return rule["enabled"]

        return True

    def _matches_rule(self, rule: dict, user: UserContext) -> bool:
        if rule["type"] == "beta_tester":
            return user.email in self._get_beta_testers()
        if rule["type"] == "geo":
            return user.geo_region in rule["regions"]
        if rule["type"] == "plan":
            return user.subscription_plan in rule["plans"]
        return False


# Feature flag configuration (stored in Etcd/Redis)
flag_config = {
    "new_checkout_flow": {
        "rollout_percentage": 10,           # 10% of users
        "environment": "prod-us",           # Only US prod
        "user_whitelist": ["user_1", "user_42"],  # Internal testers
        "kill": False,                       # Emergency off switch
        "targeting": [
            {"type": "beta_tester", "enabled": True},
            {"type": "plan", "plans": ["enterprise"], "enabled": True},
        ],
    }
}
```

**3. Configuration Drift Detection:**

```python
class DriftDetector:
    """
    Detects when a service's actual config differs from
    the Git-defined desired config.
    """

    def __init__(self):
        self.desired_config = self._load_from_git()
        self.actual_config = {}  # Reported by services

    def report_actual(self, service: str, environment: str, config: dict):
        """Called by services on startup and config change."""
        key = f"{environment}/{service}"
        self.actual_config[key] = config
        self._check_drift(key)

    def _check_drift(self, key: str):
        desired = self.desired_config.get(key, {})
        actual = self.actual_config.get(key, {})

        diff = self._deep_diff(desired, actual)
        if diff:
            logger.warning(f"Config drift detected for {key}: {diff}")
            self._alert(
                severity="warning",
                message=f"Config drift: {key}",
                details={"desired": desired, "actual": actual, "diff": diff},
            )

    def _deep_diff(self, desired, actual, path=""):
        diffs = []
        all_keys = set(desired.keys()) | set(actual.keys())

        for key in all_keys:
            full_path = f"{path}.{key}" if path else key

            if key not in desired:
                diffs.append(f"{full_path}: extra in actual")
            elif key not in actual:
                diffs.append(f"{full_path}: missing in actual")
            elif isinstance(desired[key], dict) and isinstance(actual[key], dict):
                diffs.extend(self._deep_diff(desired[key], actual[key], full_path))
            elif desired[key] != actual[key]:
                diffs.append(f"{full_path}: {desired[key]} ≠ {actual[key]}")

        return diffs
```

**4. Secrets Management (not in config files):**

```python
# NEVER store secrets in config files!
# Use a dedicated secrets manager:

class SecretsManager:
    def __init__(self):
        self.vault = HashiCorpVault()

    def get_secret(self, path: str) -> str:
        # Secrets are injected as environment variables at deploy time,
        # or fetched at runtime from Vault with automatic rotation.
        return self.vault.read(f"secrets/{self.env}/{path}")

# In deployment pipeline:
#   k8s deployment gets secrets from Vault, not from git
#   k8s SealedSecrets: encrypted in git, decrypted by controller

# Example: Kubernetes External Secrets Operator
# apiVersion: external-secrets.io/v1beta1
# kind: ExternalSecret
# spec:
#   refreshInterval: "1h"
#   secretStoreRef:
#     name: vault-backend
#   target:
#     name: my-service-secrets
#   data:
#   - secretKey: db_password
#     remoteRef:
#       key: /prod/db/password
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **GitOps** | Config stored in git, synced by controller (ArgoCD/Flux) |
| **Hot reload** | Watches config changes and reloads without restart |
| **Feature flags** | Gradual rollout (percentage, target groups, geo, A/B) |
| **Drift detection** | Compares desired (git) vs actual (running) config; alerts on mismatch |
| **Secrets** | Uses Vault/external-secrets-operator, NOT git for secrets |
| **Kill switch** | Emergency off-switch that bypasses all other flag rules |

---

> *Each topic here has been expanded to full staff-level depth with code examples and evaluation rubrics. See the companion cs-interview README for extended treatments.*
