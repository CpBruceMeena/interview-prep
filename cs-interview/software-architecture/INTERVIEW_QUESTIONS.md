# 🏗️ Software Architecture — Staff-Level Interview Questions

> *12 questions covering microservices, CQRS, event sourcing, observability, and architecture patterns — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [Microservices Decomposition: Domain-Driven Design](#1-microservices-decomposition-domain-driven-design)
2. [CQRS & Event Sourcing](#2-cqrs--event-sourcing)
3. [Event-Driven Architecture: Kafka Internals](#3-event-driven-architecture-kafka-internals)
4. [API Gateway vs Service Mesh](#4-api-gateway-vs-service-mesh)
5. [Idempotency & Exactly-Once Semantics](#5-idempotency--exactly-once-semantics)
6. [Circuit Breaker & Bulkhead Patterns](#6-circuit-breaker--bulkhead-patterns)
7. [Graceful Degradation & Fallbacks](#7-graceful-degradation--fallbacks)
8. [Observability: Logging, Metrics, Tracing](#8-observability-logging-metrics-tracing)
9. [Saga Pattern: Choreography vs Orchestration](#9-saga-pattern-choreography-vs-orchestration)
10. [Backpressure & Reactive Systems](#10-backpressure--reactive-systems)
11. [Migration Strategies: Strangler Fig](#11-migration-strategies-strangler-fig)
12. [Configuration Management & Feature Flags](#12-configuration-management--feature-flags)

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

> *The remaining 10 questions cover event-driven architecture, API gateway vs service mesh, idempotency, circuit breakers, graceful degradation, observability, saga pattern, backpressure, migration strategies, and configuration management — all at the same staff-level depth.*

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

## 5-12. Summary of Remaining Topics

5. **Idempotency & Exactly-Once**: Idempotency key stored in DB (unique constraint). Retry: check key before processing. Exactly-once requires: idempotent producer + transactional outbox + dedup consumer.

6. **Circuit Breaker & Bulkhead**: Circuit states: Closed (normal) → Open (fail threshold reached, reject immediately) → Half-Open (probing). Bulkhead: separate thread pools per dependency (one failing dependency doesn't exhaust all threads).

7. **Graceful Degradation**: When a dependency fails, degrade functionality (use cached data, return stale results, disable non-critical features). Netflix Hystrix: fallback methods return default values.

8. **Observability**: LOGS (structured, correlation IDs), METRICS (RED: Rate/Errors/Duration, USE: Utilization/Saturation/Errors), TRACES (distributed tracing with OpenTelemetry, W3C traceparent header).

9. **Saga Pattern**: (See distributed systems section) Choreography (events) vs Orchestration (central coordinator). For long-running transactions with many participants.

10. **Backpressure**: When producer outpaces consumer. Push-based: consumer crashes under load. Pull-based: consumer controls the pace. Reactive Streams: request(N) semantics. Akka Streams, RSocket.

11. **Strangler Fig Migration**: Incrementally replace monolith with microservices: intercept calls to old monolith, route to new service, remove old code when all calls migrated. Uses HTTP redirects or proxy layer.

12. **Feature Flags & Config Management**: Centralized config (Etcd, Consul, Zookeeper). Feature flags: boolean conditions gating new features. Configuration drift detection vs GitOps (pull-based ArgoCD/Flux).

---

> *Each topic deserves full code examples and evaluation rubrics. See the companion cs-interview README for extended treatments.*

