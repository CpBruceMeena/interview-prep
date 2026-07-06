# 🔄 Distributed Transaction Patterns — Principal Engineer Deep-Dive

> *12 patterns & interview questions covering 2PC, 3PC, Saga, Outbox, TCC, Idempotency, Dual-Write, and production trade-offs — every answer expects principal engineer-level depth.*

---

## Table of Contents

1. [The Core Problem: Distributed Consistency](#1-the-core-problem-distributed-consistency)
2. [Two-Phase Commit (2PC) — Detailed Protocol & Failure Modes](#2-two-phase-commit-2pc-detailed-protocol-failure-modes)
3. [Three-Phase Commit (3PC) — Why It's Rarely Used](#3-three-phase-commit-3pc-why-its-rarely-used)
4. [Saga Pattern — Choreography vs Orchestration](#4-saga-pattern-choreography-vs-orchestration)
5. [Transactional Outbox Pattern — Reliable Event Publishing](#5-transactional-outbox-pattern-reliable-event-publishing)
6. [TCC (Try-Confirm/Cancel) Pattern](#6-tcc-try-confirmcancel-pattern)
7. [Dual-Write Problem & Solutions](#7-dual-write-problem-solutions)
8. [Idempotency & Exactly-Once Semantics](#8-idempotency-exactly-once-semantics)
9. [Compensating Transaction Design](#9-compensating-transaction-design)
10. [Pattern Comparison & Decision Matrix](#10-pattern-comparison-decision-matrix)
11. [Production Anti-Patterns & Pitfalls](#11-production-anti-patterns-pitfalls)
12. [End-to-End System Design Interview](#12-end-to-end-system-design-interview)

---

## 1. The Core Problem: Distributed Consistency

**Q:** "A customer places an order: we need to reserve inventory, charge the payment card, and schedule shipping across three different microservices, each with its own database. Explain why a simple ACID transaction can't work here, and what fundamental trade-offs any solution must make."

**What They're Really Testing:** Whether you deeply understand the impossibility of distributed ACID without coordination overhead, and can articulate the consistency/availability/latency trade-off space.

### Answer

**Why Local ACID Doesn't Scale Across Services:**

```
Each service has its own database with local ACID:

┌─────────────────────────────────────────────────────┐
│                  Order Service                        │
│  BEGIN TX                                            │
│    INSERT INTO orders (id, status) VALUES (1, 'pending') │
│    CALL http://inventory/reserve(1)  ← OUTSIDE TX!  │
│    CALL http://payment/charge(100)   ← OUTSIDE TX!  │
│    CALL http://shipping/schedule(1)  ← OUTSIDE TX!  │
│    UPDATE orders SET status = 'confirmed'           │
│  COMMIT TX                                           │
│  ───────────────────────────────────────────────────  │
│  Problem: If the DB commit succeeds but inventory     │
│  call fails, the order is 'confirmed' but inventory   │
│  was never reserved. Data inconsistency!              │
└─────────────────────────────────────────────────────┘

Three-Vendor Problem (also called the "distributed transaction dilemma"):
  We need atomicity across three independent systems.
  But each system has its own transaction manager.
  No single transaction coordinator can span all three.
```

**The Fundamental Trade-offs:**

```
Any solution to distributed consistency must navigate:

                 ┌──── CONSISTENCY ─────┐
                 │  • Strong: all see   │
                 │    same state now    │
                 │  • Eventual:         │
                 │    eventually agree  │
                 └──────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ▼                  ▼                  ▼
┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│ AVAILABILITY│    │   LATENCY   │    │  THROUGHPUT  │
│ • 2PC blocks│    │ • 2PC = 4+RTT│   │ • 2PC serial │
│ • Saga async│    │ • Saga = 2RTT│   │ • Saga async │
└─────────────┘    └──────────────┘    └──────────────┘

The FLP impossibility result: in an asynchronous system,
no deterministic consensus protocol can guarantee both
safety and liveness with even one crash failure.

→ This means: you MUST choose between blocking (2PC/3PC)
  and eventual consistency (Saga/Outbox).
```

**Decision Tree for Choosing a Pattern:**

```python
def choose_transaction_pattern(requirements: dict) -> str:
    """
    requirements:
      - strong_consistency: bool
      - max_latency_ms: int
      - throughput_tps: int
      - participant_count: int
      - can_design_compensations: bool
      - requires_xa: bool  # JTA, WS-AtomicTransaction
    """
    if requirements['strong_consistency']:
        if requirements['participant_count'] <= 3 and \
           not requirements['can_design_compensations']:
            return "2PC or XA transaction"
        elif requirements['max_latency_ms'] > 100:
            return "3PC (to avoid blocking)"
        else:
            return "2PC with coordinator HA"

    # Eventual consistency path
    if not requirements['can_design_compensations']:
        raise ValueError("Must design compensations for async patterns")

    if requirements['throughput_tps'] < 1000 and \
       requirements['participant_count'] <= 5:
        return "Orchestration Saga + Outbox"

    if requirements['participant_count'] > 10:
        return "Choreography Saga + Outbox"

    if requirements['requires_xa']:
        return "TCC (Try-Confirm/Cancel)"

    return "Saga + Outbox (the default production choice)"
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **FLP theorem** | Explains the fundamental impossibility of consensus in async systems |
| **Trade-off space** | Maps consistency, availability, latency, throughput trade-offs |
| **Pattern selection** | Can write a decision function with concrete thresholds |
| **Production nuance** | Doesn't say "X is always better" — qualifies with constraints |

---

## 2. Two-Phase Commit (2PC) — Detailed Protocol & Failure Modes

**Q:** "Walk me through the 2PC protocol in detail, including the write-ahead log contents. What happens when the coordinator crashes after phase 1? What happens when a participant crashes during phase 2? How do XA transactions implement 2PC in practice? What is the 'blocking problem' exactly and how long can it last?"

**What They're Really Testing:** Whether you understand 2PC at the protocol level — not just the high-level flow — including the write-ahead log records, timeout handling, and the specific conditions that cause blocking.

### Answer

**Write-Ahead Log (WAL) in 2PC:**

```
Every 2PC coordinator and participant MUST write to a write-ahead log
before sending any network message. This is the key to crash recovery.

COORDINATOR WAL:
┌──────────────────────────────────────────────────────────────┐
│ Record 1: [BEGIN_2PC, transaction_id=T1, participants=[A,B,C]] │
│ Record 2: [SEND_PREPARE, T1, target=ALL]                      │
│ Record 3: [RECV_VOTE, T1, participant=A, vote=YES]            │
│ Record 4: [RECV_VOTE, T1, participant=B, vote=YES]            │
│ Record 5: [RECV_VOTE, T1, participant=C, vote=YES]            │
│ Record 6: [DECISION, T1, decision=COMMIT] ← flushed to disk    │
│           (point of no return!)                                │
│ Record 7: [SEND_COMMIT, T1, target=ALL]                       │
│ Record 8: [RECV_ACK, T1, participant=A, ack=COMMITTED]        │
│ Record 9: [RECV_ACK, T1, participant=B, ack=COMMITTED]        │
│ Record 10: [RECV_ACK, T1, participant=C, ack=COMMITTED]       │
│ Record 11: [END_2PC, T1]                                       │
└──────────────────────────────────────────────────────────────┘

PARTICIPANT WAL:
┌──────────────────────────────────────────────────────────────┐
│ Record 1: [PREPARE_REQ, T1, coordinator=COORD]                │
│ Record 2: [PREPARED, T1, resources_locked=[stock_42, fund_7]] │
│           (forces write to disk before sending VOTE_YES!)      │
│ Record 3: [COMMIT_REQ, T1]                                     │
│ Record 4: [COMMITTED, T1]                                      │
└──────────────────────────────────────────────────────────────┘

KEY INSIGHT: Record 2 in the PARTICIPANT WAL must be fsync()'d
to disk BEFORE the participant sends VOTE_YES to the coordinator.
This ensures the participant can recover to the PREPARED state
even after a crash.
```

**Complete Protocol Walkthrough with Timing:**

```
Phase 1: Prepare
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│              │ PREPARE │              │ PREPARE │              │
│ Coordinator  │────────►│ Participant A│────────►│ Participant B│
│              │         │              │         │              │
│              │◄── VOTE_YES(disk) ────┤         │              │
│              │         │              │◄── VOTE_YES(disk) ────┤
│              │         │              │         │              │
└──────────────┘         └──────────────┘         └──────────────┘

Phase 2: Commit (only if ALL votes = YES)
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│              │ COMMIT  │              │ COMMIT  │              │
│ Coordinator  │────────►│ Participant A│────────►│ Participant B│
│              │         │              │         │              │
│              │◄── ACK ────┤          │         │              │
│              │         │              │◄── ACK ────┤          │
└──────────────┘         └──────────────┘         └──────────────┘
```

**Failure Mode 1 — Coordinator crashes after Phase 1 (THE BLOCKING PROBLEM):**

```
Timeline:
  t0: Coordinator sends PREPARE to all participants
  t1: All participants PREPARED and fsync'd, sent VOTE_YES
  t2: Coordinator receives all VOTE_YES
  t3: Coordinator writes [DECISION, T1, decision=COMMIT] ← fsync'd!
  t4: ⚡ COORDINATOR CRASHES before sending COMMIT messages
  t5: Participants are in PREPARED state:
        - Resources are LOCKED (rows, funds, inventory)
        - Can't commit (don't know the decision)
        - Can't rollback (might have been COMMIT)
        - They are BLOCKING
  t6-t∞: Participants poll coordinator — NO RESPONSE

Duration of blocking:
  - If coordinator has HA (standby): standby reads WAL, sends COMMIT
    → Blocking duration: ~10-30 seconds (failover time)
  - Without HA: manual intervention
    → Blocking duration: MINUTES to HOURS
    → DBA must query coordinator logs or use heuristic commit

MITIGATION FOR COORDINATOR CRASH:
  - Coordinator writes [DECISION] BEFORE sending Phase 2 messages
  - Recovery: new coordinator reads WAL from disk
  - If [DECISION] exists → sends the recorded decision
  - If no [DECISION] → sends ROLLBACK (unilaterally abort)

But what if coordinator crashes BEFORE writing [DECISION]?
  - No decision was made
  - Participants must ROLLBACK (safe because no commit was ordered)
```

**Failure Mode 2 — Participant crashes after PREPARE:**

```
Timeline:
  t0: Participant receives PREPARE, locks resources, writes WAL
  t1: ⚡ PARTICIPANT CRASHES before sending VOTE_YES
  t2: Coordinator times out waiting for vote from this participant
  t3: Coordinator decides to ROLLBACK (any NO or timeout = abort)
  t4: Participant restarts, reads WAL:
        - Finds [PREPARE_REQ] but no [COMMIT_REQ]
        - Asks coordinator: "What was the decision for T1?"
        - Coordinator says: "ROLLBACK"
        - Participant releases locks, writes [ABORTED] to WAL

If participant crashes AFTER sending VOTE_YES but BEFORE receiving COMMIT:
  - Participant restarts, finds [PREPARED] in WAL
  - Polls coordinator until COMMIT or ROLLBACK arrives
  - This is fine — not blocking (participant CAN recover)
```

**XA Transactions (JTA) — Practical 2PC:**

```sql
-- X/Open XA standard for distributed transactions
-- Used by: Java JTA, PostgreSQL, Oracle, DB2

-- Phase 1: Prepare
xa start 'xid123';           -- Begin XA branch
  UPDATE inventory SET stock = stock - 1 WHERE id = 42;
  UPDATE payments SET balance = balance - 100 WHERE user = 7;
xa end 'xid123';
xa prepare 'xid123';         -- Phase 1: prepare (writes WAL, locks)

-- Phase 2: Commit (by transaction manager)
xa commit 'xid123';          -- Phase 2: commit

-- Or rollback:
xa rollback 'xid123';
```

**Performance Characteristics of 2PC:**

```python
# 2PC latency model:
# L = (N + 1) * RTT + 2 * FSYNC + N * FSYNC + N * LOCK_TIME
# Where:
#   N = number of participants
#   RTT = network round-trip time (~0.5ms in same DC, ~50ms cross-region)
#   FSYNC = disk flush time (~2-10ms for HDD, ~0.1ms for SSD/NVMe)
#   LOCK_TIME = time to acquire database locks

# For 3 participants in same datacenter:
# L = 4 * 0.5ms + 2 * 2ms + 3 * 2ms + 3 * 1ms
# L = 2ms + 4ms + 6ms + 3ms = 15ms

# For 3 participants cross-region:
# L = 4 * 50ms + 2 * 2ms + 3 * 2ms + 3 * 1ms
# L = 200ms + 4ms + 6ms + 3ms = 213ms

# Throughput limit with single coordinator:
# TP = 1 / L ≈ 66 tps (same DC), ~4.7 tps (cross-region)
# This is why 2PC doesn't scale!
```

**When 2PC Is Actually Acceptable:**

```yaml
Acceptable uses:
  - Within a single datacenter (low latency)
  - Small number of participants (2-3)
  - Short-lived transactions (< 1 second)
  - High-value operations (financial transfers, trading)
  - When compensations are impossible or too risky

Unacceptable uses:
  - Cross-datacenter (high latency kills throughput)
  - Many participants (> 5)
  - Long-running transactions (> 10 seconds)
  - High-throughput systems (> 100 tps)
  - Microservices (different tech stacks, different databases)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **WAL details** | Can describe the exact WAL records written by coordinator and participants |
| **Blocking duration** | Quantifies blocking time — not just "it blocks" but HOW LONG |
| **Crash recovery** | Explains log-based recovery: reading WAL, determining decision, replaying |
| **XA mechanics** | Familiar with XA SQL syntax, knows prepare/commit/rollback phases |
| **Latency model** | Computes 2PC latency from first principles (RTT, fsync, locks) |

---

## 3. Three-Phase Commit (3PC) — Why It's Rarely Used

**Q:** "Explain how 3PC attempts to solve the blocking problem of 2PC. Why is 3PC still vulnerable to network partitions? Why is it rarely used in production despite being 'non-blocking'?""

**What They're Really Testing:** Whether you understand that 3PC's non-blocking property depends on network assumptions that don't hold in practice, and can articulate the subtle failure modes.

### Answer

**3PC Protocol — The Three Phases:**

```
Phase 1: CanCommit (query, no locks)
Phase 2: PreCommit (prepare with timeout-based recovery)
Phase 3: DoCommit (commit or abort)

┌──────────┐    CanCommit    ┌──────────┐
│          │────────────────►│          │
│          │◄── VOTE_YES ────┤          │
│          │                 │          │
│          │    PreCommit    │          │
│  COORD   │────────────────►│  PARTA   │
│          │◄── ACK ─────────┤          │
│          │                 │          │
│          │    DoCommit     │          │
│          │────────────────►│          │
│          │◄── ACK ─────────┤          │
└──────────┘                 └──────────┘
```

**3PC Timeout-Based Recovery (The Key Difference from 2PC):**

```
SCENARIO: Coordinator crashes after PreCommit

Timeline:
  t0: Coordinator sends CanCommit → all VOTE_YES
  t1: Coordinator sends PreCommit  → all ACK
  t2: ⚡ COORDINATOR CRASHES before DoCommit

3PC Recovery (NOT blocking like 2PC):
  t3: Participant A times out waiting for DoCommit
  t4: A sends QUERY to Participant B: "Did you receive DoCommit?"
  t5: B also timed out → both in PreCommit state
  t6: A and B agree: majority have PreCommit → COMMIT
  t7: A and B COMMIT unilaterally

Why this works (the insight):
  - PreCommit means ALL participants agreed to commit
  - If any participant received DoCommit, they tell the others
  - If no participant received DoCommit, but ALL got PreCommit,
    the majority can safely decide to commit
  - This avoids the 2PC blocking problem!

Formal guarantee:
  3PC is NON-BLOCKING as long as the network is synchronous
  (bounded message delays).
```

**Why 3PC Fails Under Network Partitions:**

```
SCENARIO: Network partition during PreCommit

             ┌──────────────────┐
             │    COORDINATOR   │
             │  (sends PreCommit)│
             └────────┬─────────┘
                      │
              ┌───────┴───────┐
              │               │
         ┌────▼────┐    ┌────▼────┐
         │  PART A │    │  PART B │  ← Network Partition!
         │(receives│    │(doesn't│
         │PreCommit)│    │receive) │
         └─────────┘    └─────────┘

  Part A (receives PreCommit):
    - Times out → asks others
    - Can't reach Part B (partitioned!)
    - Only itself in majority → can't reach consensus
    - BLOCKED!

  Part B (doesn't receive PreCommit):
    - Times out waiting for PreCommit
    - Knows CanCommit was sent (Phase 1)
    - But unsure if PreCommit was sent to others
    - Must ABORT to be safe (can't decide COMMIT without PreCommit knowledge)
    - But PART A might COMMIT! → DIVERGENCE!

Result: 3PC can still BLOCK during network partitions
  - The non-blocking property requires a SYNCHRONOUS network
  - In asynchronous networks (the real world), 3PC degrades to 2PC behavior
  - This is WHY 3PC is rarely used in practice!
```

**Why 3PC Is Rarely Used (Production Reality):**

```yaml
Reasons 3PC isn't used:

1. Network Partitions Are Common:
   - 3PC only works in synchronous networks
   - Real-world networks are asynchronous (delays, drops)
   - Under asynchrony, 3PC blocks just like 2PC

2. Extra Round Trip:
   - 3PC: 3 phases = CanCommit + PreCommit + DoCommit
   - 2PC: 2 phases = Prepare + Commit
   - 3PC adds 1 RTT (50% more latency)
   - For cross-region: adds 50-100ms

3. Complexity:
   - Timeout-based recovery is hard to get right
   - Participants must track state transitions carefully
   - Majority voting during recovery adds complexity

4. Better Alternatives Exist:
   - For synchronous networks: 2PC is simpler and works fine
   - For async networks: Saga patterns are the production choice
   - Paxos/Raft give consensus with better properties

Historical note: 3PC was proposed by Skeen & Stonebraker in 1983.
It was influential as a theoretical contribution but never gained
wide production adoption due to the network partition problem.
```

**3PC vs 2PC Comparison:**

```yaml
Property               2PC                 3PC
─────────────────────────────────────────────────────
Phases                 2 (Prepare, Commit) 3 (CanCommit, PreCommit, DoCommit)
Network RTTs           2                    3
Blocking on crash      YES                  YES (under partition)
Blocking on partition  YES                  YES (degraded)
Coordination overhead  Low                  Medium
Implementation         Simple               Complex
Production adoption    High (XA/JTA)        Very low
Network assumption     None (any)           Synchronous required
Timeout recovery       No                   Yes (majority vote)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Timeout recovery** | Explains how participants can commit/abort without coordinator in 3PC |
| **Partition failure** | Shows why 3PC fails under async networks (the fundamental flaw) |
| **RTT cost** | Quantifies the extra latency phase (50% more network trips) |
| **Production reality** | Can articulate why theory (non-blocking) ≠ practice (still blocks) |

---

## 4. Saga Pattern — Choreography vs Orchestration

**Q:** "Design an order-to-shipment workflow that spans 5 microservices using the Saga pattern. Walk through both choreography and orchestration approaches. What happens when a compensating transaction fails? How do you handle the 'lost compensation' problem? How do you ensure idempotent compensations? Now make it resilient to production failures."

**What They're Really Testing:** Whether you understand Sagas not just as a pattern, but as a distributed state machine with real failure modes: lost compensations, partial failures, timeout cascades, and zombie transactions.

### Answer

**Choreography Saga — Event-Driven Flow:**

```
ORDER SERVICE        INVENTORY SVC       PAYMENT SVC       SHIPPING SVC       NOTIFICATION SVC
    │                     │                    │                  │                    │
    │──OrderCreated─────► │                    │                  │                    │
    │                     │──StockReserved───► │                  │                    │
    │                     │                    │──PaymentCharged─►│                    │
    │                     │                    │                  │──LabelCreated─────►│
    │                     │                    │                  │                    │──EmailSent
    │                     │                    │                  │                    │
    │                     │                    │                  │                    │
    │           ── FAILURE PATH ──            │                  │                    │
    │                     │    StockReserveFailed                │                    │
    │◄────────────────────┤                    │                  │                    │
    │(no compensation     │                    │                  │                    │
    │ needed — nothing    │                    │                  │                    │
    │ happened before)    │                    │                  │                    │
    │                     │                    │                  │                    │
    │                     │  PaymentFailed     │                  │                    │
    │◄────────────────────┤◄───────────────────┤                  │                    │
    │ (compensate:        │   (compensate:     │                  │                    │
    │  notify user)       │    release stock)  │                  │                    │
    │                     │                    │                  │                    │
    │                     │                    │  ShipFailed      │                    │
    │◄────────────────────┤◄───────────────────┤◄─────────────────┤                    │
    │ (compensate:        │   (compensate:     │  (compensate:    │                    │
    │  notify user)       │    release stock)  │   refund charge) │                    │
    │                     │                    │                  │                    │
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: How does Inventory know to release stock for a payment failure?                  │
│ Answer: Payment service publishes "PaymentFailed" event. Inventory subscribes.            │
│                                                                                           │
│ PROBLEM: What if Inventory was DOWN when PaymentFailed was published?                     │
│ Answer: Event is persisted in Kafka. Inventory replays from last offset.                  │
│                                                                                           │
│ PROBLEM: What if PaymentFailed was delivered but Inventory crashed before releasing?      │
│ Answer: At-least-once delivery. On restart, Inventory replays from committed offset.       │
│         ReleaseStock must be IDEMPOTENT (using order_id as idempotency key).              │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

**Orchestration Saga — Central Coordinator:**

```python
import enum
import json
from dataclasses import dataclass
from typing import Optional

class SagaStatus(enum.Enum):
    PENDING = "PENDING"
    STEP_COMPLETED = "STEP_COMPLETED"
    COMPLETED = "COMPLETED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    FAILED = "FAILED"

@dataclass
class SagaState:
    saga_id: str
    status: SagaStatus
    current_step: int
    completed_steps: list[int]
    compensating_steps: list[int]
    error_message: Optional[str] = None
    payload: dict = None  # Business data

class OrchestrationSaga:
    """
    Saga coordinator with persistent state machine.
    Each step is idempotent. Compensations are retriable.
    """

    STEPS = [
        ("reserve_stock", InventoryService.reserve, InventoryService.release),
        ("charge_card", PaymentService.charge, PaymentService.refund),
        ("create_label", ShippingService.create_label, ShippingService.void_label),
        ("send_email", NotificationService.send, NotificationService.undo_send),
    ]

    def __init__(self, db, event_bus, max_retries=3):
        self.db = db  # PostgreSQL for saga state
        self.event_bus = event_bus  # Kafka for step execution
        self.max_retries = max_retries

    async def start_saga(self, saga_id: str, payload: dict) -> SagaState:
        state = SagaState(
            saga_id=saga_id,
            status=SagaStatus.PENDING,
            current_step=0,
            completed_steps=[],
            compensating_steps=[],
            payload=payload,
        )
        await self._persist_state(state)
        await self._execute_step(state)
        return state

    async def _execute_step(self, state: SagaState):
        """Execute the current step with retries and timeout."""
        step_name, step_fn, _ = self.STEPS[state.current_step]

        for attempt in range(1, self.max_retries + 1):
            try:
                # Send command to the service via event bus
                # Service executes and publishes result
                result = await self._send_command_with_timeout(
                    step_name,
                    state.payload,
                    timeout_seconds=30,
                )

                # Update state
                state.current_step += 1
                state.completed_steps.append(state.current_step - 1)
                state.status = SagaStatus.STEP_COMPLETED
                await self._persist_state(state)

                # Check if saga is complete
                if state.current_step >= len(self.STEPS):
                    state.status = SagaStatus.COMPLETED
                    await self._persist_state(state)
                    await self._notify_completion(state.saga_id)
                    return

                # Execute next step
                await self._execute_step(state)
                return

            except TimeoutError as e:
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                await self._fail_saga(state, f"Step {step_name} failed after {self.max_retries} retries: {e}")
                return

            except NonRetriableError as e:
                # e.g., payment declined, insufficient stock
                await self._fail_saga(state, f"Step {step_name} failed: {e}")
                return

    async def _fail_saga(self, state: SagaState, error: str):
        """Execute compensating transactions in REVERSE order."""
        state.status = SagaStatus.COMPENSATING
        state.error_message = error
        await self._persist_state(state)

        # Execute compensations for completed steps, in reverse
        for step_idx in reversed(state.completed_steps):
            step_name, _, comp_fn = self.STEPS[step_idx]
            try:
                await self._send_command_with_timeout(
                    f"compensate_{step_name}",
                    state.payload,
                    timeout_seconds=30,
                )
                state.compensating_steps.append(step_idx)
            except Exception as comp_error:
                # Compensation failed! This is CRITICAL.
                # We must NOT give up — compensations must eventually succeed.
                # Publish to dead-letter queue for manual intervention.
                await self._publish_to_dlq(
                    saga_id=state.saga_id,
                    step=step_name,
                    error=str(comp_error),
                )
                # Continue with other compensations
                continue

        state.status = SagaStatus.COMPENSATED
        await self._persist_state(state)
        await self._notify_failure(state.saga_id, error)
```

**The "Lost Compensation" Problem — And How to Solve It:**

```python
# PROBLEM:
# Compensation for step 2 (refund) succeeded, but compensation for step 1
# (release stock) failed. The system is now in an inconsistent state:
#   - Payment refunded
#   - Stock NOT released
#
# The compensation was "lost" — the failure means the system is in an
# intermediate state that no one is acting on.

# SOLUTION 1: Saga recovery daemon (background worker)
class SagaRecoveryWorker:
    """
    Background worker that scans for stuck sagas and retries compensations.
    Runs every 30 seconds.
    """

    async def recover_stuck_sagas(self):
        stuck = await self.db.query("""
            SELECT * FROM saga_state
            WHERE status = 'COMPENSATING'
              AND updated_at < NOW() - INTERVAL '5 minutes'
        """)

        for saga in stuck:
            await self._retry_compensations(saga)

    async def _retry_compensations(self, saga: SagaState):
        """Retry all compensations that haven't been acknowledged."""
        for step_idx in saga.completed_steps:
            if step_idx in saga.compensating_steps:
                continue  # Already compensated

            step_name, _, comp_fn = self.STEPS[step_idx]
            try:
                await comp_fn(saga.payload)
                saga.compensating_steps.append(step_idx)
            except Exception:
                continue  # Will retry in next recovery cycle

        # Check if all compensations done
        if set(saga.compensating_steps) == set(saga.completed_steps):
            saga.status = SagaStatus.COMPENSATED
            await self._persist_state(saga)

# SOLUTION 2: Dead letter queue with manual intervention
# When a compensation keeps failing, send it to DLQ:
class DLQHandler:
    """
    Monitors dead letter queue for failed compensations.
    Each DLQ message includes full context for manual or automated replay.
    """

    async def process_dlq(self):
        messages = await self.kafka.consume("saga.dlq")
        for msg in messages:
            saga_id = msg["saga_id"]
            step = msg["step"]
            error = msg["error"]
            retry_count = msg.get("retry_count", 0)

            if retry_count < 10:
                # Auto-retry with backoff
                await asyncio.sleep(2 ** retry_count * 60)  # 1min, 2min, 4min, ...
                try:
                    await self._execute_compensation(saga_id, step)
                except Exception:
                    msg["retry_count"] = retry_count + 1
                    await self.kafka.produce("saga.dlq", msg)
            else:
                # Escalate to human
                await self._notify_ops(f"Saga {saga_id}: compensation {step} keeps failing")

# SOLUTION 3: Idempotent compensations
# Every compensation must be IDEMPOTENT — running it multiple times
# must produce the same result as running it once.

class IdempotentPaymentService:
    def refund(self, order_id: str, amount: float) -> bool:
        # Check if already refunded
        existing = self.db.query(
            "SELECT status FROM refunds WHERE order_id = %s",
            (order_id,)
        )
        if existing and existing['status'] == 'COMPLETED':
            return True  # Already done — idempotent NO-OP

        # Process refund
        result = self.payment_gateway.refund(order_id, amount)

        # Record result
        self.db.execute(
            "INSERT INTO refunds (order_id, amount, status) "
            "VALUES (%s, %s, 'COMPLETED') "
            "ON CONFLICT (order_id) DO NOTHING",
            (order_id, amount)
        )
        return result
```

**Choreography vs Orchestration — Production Trade-offs:**

```yaml
CHOREOGRAPHY SAGA:
  Pros:
    + Decentralized — no single point of failure
    + Each service only knows about its own events
    + Scales naturally with event bus partitioning
  Cons:
    - Impossible to see the full workflow in one place
    - "Saga is all over the place" — hard to debug
    - Eventual consistency chain can break at any point
    - Cyclic dependencies between services (event spaghetti)
    - No single place for timeout management
  Use: Simple linear flows with < 5 participants

ORCHESTRATION SAGA:
  Pros:
    + Centralized state machine — full visibility
    + Timeout, retry, and compensation logic in one place
    + Easy to add monitoring, metrics, and tracing
    + No cyclic dependencies between services
  Cons:
    - Coordinator is a potential bottleneck
    - Coordinator is a SPOF (unless HA)
    - Coordinator must be versioned and backward-compatible
  Use: Complex workflows, long-running sagas, compliance-heavy

PRODUCTION CHOICE (for > 99% of cases):
  ORCHESTRATION SAGA + OUTBOX PATTERN
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Failed compensation** | Articulates the "lost compensation" problem and designs a DLQ + recovery worker |
| **Idempotent compensations** | Implements idempotency keys with ON CONFLICT DO NOTHING pattern |
| **Choreography vs orchestration** | Gives concrete trade-offs with examples, not just abstract benefits |
| **Timeout management** | Uses exponential backoff, distinguishes retriable vs non-retriable errors |
| **Recovery daemon** | Designs a background worker that rescues stuck sagas |

---

## 5. Transactional Outbox Pattern — Reliable Event Publishing

**Q:** "We have a microservice that needs to publish events to Kafka whenever a database row changes. The naive approach (write to DB then publish to Kafka) has a race condition: what if the DB write succeeds but Kafka publish fails? Or the Kafka publish succeeds but the DB transaction rolls back? Design a reliable solution. How do you scale it to 10K events/second? Compare polling vs CDC-based approaches."

**What They're Really Testing:** Whether you understand the dual-write problem in depth and can design a production-grade outbox implementation with concrete trade-offs.

### Answer

**The Dual-Write Problem:**

```python
# NAIVE APPROACH — RACE CONDITION:
def create_order(order_data):
    with db.transaction():
        order = db.execute("INSERT INTO orders VALUES (...)")

    # ⚠️ If this fails, we have an order in DB but no event!
    # ⚠️ If this succeeds but DB transaction rolls back, event with phantom data!
    kafka.produce("order.created", order.to_json())

# PROBLEM 1: DB succeeds, Kafka fails
#   → Order exists in DB, no event published
#   → Downstream services don't know about the order
#   → Silent data loss!

# PROBLEM 2: Kafka succeeds, DB rolls back
#   → Event published but order doesn't exist
#   → Phantom event consumed by downstream services
#   → Inventory reserved for nothing!

# PROBLEM 3: Exactly-once delivery?
#   → Kafka provides at-least-once delivery
#   → If producer crashes before ack, message is re-sent
#   → Downstream must handle duplicates anyway
```

**The Outbox Pattern — Solution:**

```sql
-- Same database transaction writes to an OUTBOX table:
CREATE TABLE outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type VARCHAR(100) NOT NULL,    -- e.g., 'order'
    aggregate_id VARCHAR(100) NOT NULL,      -- e.g., order_id
    event_type VARCHAR(100) NOT NULL,        -- e.g., 'OrderCreated'
    payload JSONB NOT NULL,                  -- event data
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,               -- NULL = not yet published
    retry_count INT DEFAULT 0,
    idempotency_key VARCHAR(255) UNIQUE     -- prevent duplicates
);

CREATE INDEX idx_outbox_unpublished ON outbox
    WHERE published_at IS NULL
    ORDER BY created_at ASC;
```

```python
# CORRECT APPROACH — Outbox in same DB transaction:
def create_order_with_outbox(order_data):
    with db.transaction():
        # 1. Business operation
        order = db.execute(
            "INSERT INTO orders (...) VALUES (...) RETURNING id"
        )

        # 2. Outbox record in SAME transaction
        db.execute("""
            INSERT INTO outbox (aggregate_type, aggregate_id, event_type,
                                payload, idempotency_key)
            VALUES ('order', %s, 'OrderCreated', %s, %s)
        """, (
            order['id'],
            json.dumps(order_data),
            f"order-created-{order['id']}",  # Idempotency key
        ))

    # ⚠️ Both or neither — guaranteed by ACID!
    # If this line fails, the DB transaction rolls back.
    # The outbox publisher handles eventual delivery.
```

**Outbox Publisher — Polling-Based:**

```python
class PollingOutboxPublisher:
    """
    Background worker that polls the outbox table and publishes
    events to Kafka. Designed for at-least-once delivery.
    """

    def __init__(self, db_pool, kafka_producer, batch_size=100, poll_interval_ms=100):
        self.db = db_pool
        self.kafka = kafka_producer
        self.batch_size = batch_size
        self.poll_interval_ms = poll_interval_ms
        self.running = True

    async def run(self):
        """Main loop — runs as a background task."""
        while self.running:
            try:
                messages = await self._fetch_unpublished()
                if messages:
                    await self._publish_batch(messages)
                else:
                    await asyncio.sleep(self.poll_interval_ms / 1000)
            except Exception as e:
                logger.error(f"Outbox publisher error: {e}")
                await asyncio.sleep(1.0)  # Back off on error

    async def _fetch_unpublished(self) -> list[dict]:
        """Fetch unpublished messages, oldest first."""
        return await self.db.fetch("""
            SELECT id, event_type, payload, idempotency_key
            FROM outbox
            WHERE published_at IS NULL
              AND retry_count < 10             -- Max retries before DLQ
              AND (next_retry_at IS NULL OR next_retry_at <= NOW())
            ORDER BY created_at ASC
            LIMIT $1
            FOR UPDATE SKIP LOCKED             -- Don't block other publishers
        """, self.batch_size)

    async def _publish_batch(self, messages: list[dict]):
        """Publish messages to Kafka and mark as published."""
        async with self.db.transaction():
            for msg in messages:
                try:
                    # Publish with idempotency key (Kafka exactly-once)
                    await self.kafka.produce(
                        topic=msg['event_type'],
                        value=msg['payload'],
                        key=msg['idempotency_key'],  # For partitioning
                        headers={'idempotency_key': msg['idempotency_key']},
                    )

                    # Mark as published
                    await self.db.execute(
                        "UPDATE outbox SET published_at = NOW() WHERE id = $1",
                        msg['id'],
                    )

                except Exception as e:
                    # Increment retry count, set exponential backoff
                    await self.db.execute("""
                        UPDATE outbox
                        SET retry_count = retry_count + 1,
                            next_retry_at = NOW() + INTERVAL '1 second' * (2 ^ retry_count)
                        WHERE id = $1
                    """, msg['id'])

                    if msg['retry_count'] >= 10:
                        # Move to DLQ
                        await self._move_to_dlq(msg)
```

**Outbox Publisher — CDC-Based (Change Data Capture):**

```sql
-- Alternative: Use PostgreSQL logical replication / Debezium
-- Instead of polling, let the DB's WAL push changes to us

-- 1. Create a publication for the outbox table
CREATE PUBLICATION outbox_pub FOR TABLE outbox;

-- 2. Debezium connector reads the WAL and publishes to Kafka
--    No polling needed! Sub-millisecond latency.

-- 3. Kafka Streams or ksqlDB to transform WAL events into domain events

-- Benefits of CDC approach:
--   • Sub-millisecond latency vs 100ms polling
--   • No load on DB from polling queries
--   • Scales naturally with WAL throughput
--   • Debezium handles exactly-once semantics

-- Drawbacks:
--   • Infrastructure complexity (Debezium, Kafka Connect)
--   • WAL must be retained until events are published
--   • Schema changes require careful handling
```

**Polling vs CDC — Comparison:**

```yaml
Aspect               Polling-Based                  CDC-Based (Debezium)
────────────────────────────────────────────────────────────────────
Latency              50-500ms (configurable)        <10ms (WAL streaming)
DB Load              SELECT queries on outbox       Minimal (WAL reader)
                    table (can be optimized)
Complexity           Simple SQL + background        Kafka Connect cluster,
                    worker                         Debezium config
Scaling              Multiple publishers with       Partitions by table/row
                    FOR UPDATE SKIP LOCKED
Exactly-once         At-least-once (dedup on        At-least-once
                    consumer side)
Schema changes       Easy (add columns to           Must handle schema
                    outbox table)                   evolution carefully
Dependency           Only the application DB        Requires Kafka + Connect
Monitoring           Check outbox table size,       Check Debezium lag,
                    lag (created_at vs NOW())       Connect task status
```

**Scaling the Outbox to 10K Events/Second:**

```python
# STRATEGY 1: Partition the outbox table
# Instead of one outbox table, use multiple tables or partitions:

CREATE TABLE outbox_shard_0 PARTITION OF outbox
    FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE outbox_shard_1 PARTITION OF outbox
    FOR VALUES WITH (MODULUS 4, REMAINDER 1);
-- ... shard 2, shard 3

# Each shard has its own publisher worker.
# Idempotency key determines the shard:
# shard = hash(idempotency_key) % NUM_SHARDS

# STRATEGY 2: Dedicated outbox database
# Separate PostgreSQL instance for the outbox table.
# Application writes to both business DB and outbox DB in a
# distributed transaction (or use 2PC between them).
# This isolates the business DB from outbox load.

# STRATEGY 3: Batch publishing
# Instead of one Kafka message per outbox row, batch multiple
# events into a single Kafka message (if ordering allows).
# Reduces Kafka producer overhead at the cost of latency.

# STRATEGY 4: Idempotency key dedup at DB level
# Since idempotency_key is UNIQUE, duplicate inserts fail silently.
# This allows retrying the entire business transaction safely:
def create_order_safe(order_data):
    # Generate idempotency key at the API level
    idempotency_key = order_data.get('idempotency_key', str(uuid4()))

    with db.transaction():
        # Try to insert outbox record first — if exists, it's a retry
        result = db.execute("""
            INSERT INTO outbox (idempotency_key, ...)
            VALUES (%s, ...)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
        """, (idempotency_key,))

        if result:
            # First time processing — execute business logic
            order = db.execute("INSERT INTO orders (...) VALUES (...)")
        else:
            # Already processed — fetch previous result
            order = db.execute("SELECT * FROM orders WHERE ...")

    return order
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Dual-write problem** | Explains both failure modes (DB succeeds/Kafka fails and vice versa) |
| **Transactional outbox** | Implements outbox in same DB transaction with idempotency key |
| **Polling vs CDC** | Compares both with concrete latency, load, and complexity numbers |
| **Scaling** | Proposes partitioning, dedicated DB, batch publishing for throughput |
| **Dead letter queue** | Handles failed publishes with retry count, backoff, and DLQ escalation |

---

## 6. TCC (Try-Confirm/Cancel) Pattern

**Q:** "Explain the TCC pattern. How is it different from Saga? When would you use TCC instead of Saga? Walk through a concrete example of reserving a hotel room using TCC."

**What They're Really Testing:** Whether you understand TCC as a reservation-based pattern that bridges the gap between 2PC (strong locks) and Saga (no locks).

### Answer

**TCC Overview:**

```
TCC is a compromise between 2PC and Saga:

  2PC:  Lock resources → Commit or Abort  (blocking on locks)
  TCC:  Try (reserve) → Confirm (use) or Cancel (release)  (short-lived holds)
  Saga: Do → Compensate (no holds, full rollback needed)

TCC Three Phases:

Phase 1: Try
  - Reserve the resource (hold, don't consume)
  - Example: authorize $100 on credit card, don't capture yet
  - Example: mark hotel room as "pending" but not "booked"
  - Returns: "tentative confirmation ID" for later reference

Phase 2: Confirm
  - Actually consume the reserved resource
  - Example: capture the authorized payment
  - Example: mark hotel room as "booked"
  - Must succeed (retry until done)
  - Called AFTER all Try phases succeeded

Phase 3: Cancel
  - Release the reserved resource
  - Example: void the authorization
  - Example: mark hotel room as "available" again
  - Called if ANY Try phase fails
```

**Concrete Example — Hotel Booking:**

```python
class TCCHotelBooking:
    """
    TCC pattern for booking a hotel room.
    Phase 1: Try — hold the room temporarily
    Phase 2: Confirm — finalize the booking
    Phase 3: Cancel — release the hold
    """

    # ── Phase 1: Try (reserve) ──────────────────────────
    def try_book_room(self, booking_id: str, room_id: str,
                      guest: str, checkin: date, checkout: date) -> str:
        """
        Reserve the room for a limited time (e.g., 15 minutes).
        Returns a hold_id for confirmation/cancellation.
        """
        with self.db.transaction():
            # Check if room is available
            existing = self.db.fetch("""
                SELECT 1 FROM reservations
                WHERE room_id = $1
                  AND status IN ('CONFIRMED', 'HELD')
                  AND checkin < $3 AND checkout > $2
                FOR UPDATE  -- Lock the row for checking
            """, room_id, checkin, checkout)

            if existing:
                raise RoomNotAvailable(room_id, checkin, checkout)

            # Create a HOLD (not confirmed)
            hold = self.db.fetch("""
                INSERT INTO reservations (room_id, guest, checkin, checkout,
                                          status, hold_expires_at)
                VALUES ($1, $2, $3, $4, 'HELD', NOW() + INTERVAL '15 minutes')
                RETURNING id
            """, room_id, guest, checkin, checkout)

            # Start a background timer to auto-cancel if not confirmed
            self._schedule_auto_cancel(hold['id'], timeout_minutes=15)

            return hold['id']  # Return the hold_id

    # ── Phase 2: Confirm (use) ──────────────────────────
    def confirm_booking(self, hold_id: str):
        """
        Confirm the booking. Must be idempotent.
        Called after ALL Try phases succeeded across all services.
        """
        with self.db.transaction():
            hold = self.db.fetch("""
                SELECT status FROM reservations WHERE id = $1 FOR UPDATE
            """, hold_id)

            if not hold:
                raise BookingNotFound(hold_id)

            if hold['status'] == 'CONFIRMED':
                return  # Already confirmed — idempotent

            if hold['status'] == 'CANCELLED':
                raise HoldExpired(hold_id)  # Auto-cancelled by timer

            if hold['hold_expires_at'] < datetime.now():
                raise HoldExpired(hold_id)  # Hold timed out

            # Confirm the booking
            self.db.execute("""
                UPDATE reservations
                SET status = 'CONFIRMED', hold_expires_at = NULL
                WHERE id = $1
            """, hold_id)

    # ── Phase 3: Cancel (release) ───────────────────────
    def cancel_booking(self, hold_id: str):
        """
        Cancel the booking and release the room.
        Must be idempotent.
        """
        with self.db.transaction():
            status = self.db.fetch("""
                UPDATE reservations
                SET status = 'CANCELLED', hold_expires_at = NULL
                WHERE id = $1 AND status = 'HELD'
                RETURNING status
            """, hold_id)

            # If already cancelled or not found, it's fine (idempotent)
```

**TCC vs Saga vs 2PC:**

```yaml
Aspect              2PC                  TCC                   Saga
──────────────────────────────────────────────────────────────────────────
Resource locking    Long (tx duration)  Short (hold timeout)  None (immediate
                                                                 release)
Consistency         Strong              Strong (during hold)  Eventual
Latency             High (locks held)   Medium (short hold)   Low (no hold)
Compensation        Rollback (automatic) Cancel (explicit)     Compensating action
Failure handling    Coordinator decides  Timeout auto-cancel   DLQ + recovery
Implementation      DB/XA support       Application code      Application code
Use case            Financial, short     Hotel booking,        Long-running
                    transactions         payment auth          workflows

PRODUCTION RECOMMENDATION:
  - Need strong consistency + short holds → TCC
  - Need atomicity across heterogeneous systems → 2PC/XA
  - Need long-running workflows → Saga
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Hold semantics** | Explains the temporary hold with timeout, auto-cancel for expired holds |
| **Idempotent confirm/cancel** | Both confirm and cancel must be safe to retry |
| **TCC vs Saga** | Explains TCC as the middle ground between 2PC and Saga |
| **Auto-cancel** | Mentions background timer to clean up expired holds |

---

## 7. Dual-Write Problem & Solutions

**Q:** "Define the dual-write problem in distributed systems. List all the known solutions and their trade-offs. How do you ensure atomicity when writing to a database AND publishing a message to a message queue?"

**What They're Really Testing:** Whether you know the full landscape of dual-write solutions, not just the outbox pattern.

### Answer

**The Dual-Write Problem Defined:**

```
Any time you need to write to TWO different systems atomically,
you have a dual-write problem. Common examples:

  1. Database + Message Queue (most common)
     - INSERT INTO orders + kafka.produce("order_created")
  
  2. Database + Cache
     - UPDATE users SET name = 'X' + redis.set("user:123", new_data)
  
  3. Database + Search Index
     - INSERT INTO products + elasticsearch.index(product)
  
  4. Database + Another Database
     - INSERT INTO service_a.users + INSERT INTO service_b.accounts

The fundamental challenge:
  You need atomicity across two independent systems.
  No single transaction coordinator spans both.
  Any one of them can fail independently.
```

**Solutions Landscape:**

```
┌────────────────────────────────────────────────────────────────────┐
│                    DUAL-WRITE SOLUTIONS                             │
├────────────────┬─────────────────┬────────────────┬─────────────────┤
│  OUTBOX PATTERN │  CDC (Debezium) │  TRANSACTIONAL  │  TWO-PHASE     │
│  (same DB tx)   │  (WAL reading)   │  DUAL-WRITE    │  COMMIT (XA)   │
├────────────────┼─────────────────┼────────────────┼─────────────────┤
│ Event written   │ DB writes WAL   │ Write to both  │ XA coordinator  │
│ in same DB tx   │ Debezium reads  │ in same app    │ coordinates     │
│ Background      │ WAL → Kafka     │ Best-effort    │ both systems    │
│ publisher       │                  │ with retry     │                 │
├────────────────┼─────────────────┼────────────────┼─────────────────┤
│ Simplicity: ★★★★│ Latency: ★★★★★  │ Simplicity: ★★ │ Consistency:    │
│ Reliability:    │ Complexity: ★★  │ Reliability: ★ │ ★★★★★          │
│ ★★★★★           │                  │                │ Complexity: ★   │
│ Latency: ★★★    │                  │                │ Performance: ★  │
└────────────────┴─────────────────┴────────────────┴─────────────────┘

┌────────────────┬─────────────────┬────────────────┬─────────────────┐
│  EVENTUALLY    │  SAGA PATTERN    │ EVENT SOURCING │  KAFKA WITH     │
│  CONSISTENT    │  (compensations) │ (events as     │  COMPACTED      │
│  RETRY         │                  │  source of     │  TOPIC + LOG    │
│                │                  │  truth)        │                  │
├────────────────┼─────────────────┼────────────────┼─────────────────┤
│ Accept data    │ Compensate if   │ Store events   │ Write to Kafka  │
│ may diverge    │ secondary write  │ as primary DB  │ first, replay   │
│ Fix later with │ fails           │ Rebuild other  │ to rebuild      │
│ reconciliation │                  │ systems from   │ other systems   │
│                │                  │ events         │                  │
├────────────────┼─────────────────┼────────────────┼─────────────────┤
│ Simplicity:    │ Complexity: ★★  │ Complexity:    │ Complexity: ★★ │
│ ★★★★★           │ Consistency: ★★★ │ ★★★            │ Consistency:    │
│ Consistency: ★ │                  │ Consistency:   │ ★★★★           │
│                │                  │ ★★★★★          │                 │
└────────────────┴─────────────────┴────────────────┴─────────────────┘
```

**Pattern 1: Best-Effort Dual Write with Retry:**

```python
# ⚠️ SIMPLEST BUT WEAKEST APPROACH:
# No atomicity guarantee. Use only for non-critical data.

def update_user_and_cache(user_id, name):
    try:
        # Write to DB
        db.execute("UPDATE users SET name = %s WHERE id = %s", (name, user_id))

        # Write to cache (best-effort)
        try:
            redis.set(f"user:{user_id}", name)
        except Exception:
            logger.error(f"Cache update failed for user {user_id}")
            # Cache will be populated on next read (lazy loading)
            pass

    except Exception:
        # DB failed — nothing to do
        raise
```

**Pattern 2: Transactional Outbox (recommended):**

```python
# Covered in detail in Section 5.
# The gold standard for production systems.
```

**Pattern 3: CDC-Based (Kafka Connect / Debezium):**

```python
# Covered in detail in Section 5.
# Best latency, no application-level polling.
```

**Pattern 4: Event Sourcing (events as source of truth):**

```python
# Instead of writing to both DB and queue, write ONLY events:
class EventSourcedOrderService:
    def create_order(self, order_data):
        # The EVENT is the source of truth — not the DB!
        event = OrderCreated(
            order_id=order_data['id'],
            user_id=order_data['user_id'],
            amount=order_data['amount'],
            items=order_data['items'],
        )

        # Append to event store
        self.event_store.append("orders", event)

        # Event store publishes to all subscribers
        # Downstream services build their own state from events

    # NO DUAL-WRITE! Single write to event store.
    # Subscribers: OrderService builds current state
    #              PaymentService processes payment
    #              InventoryService reserves stock
    #              NotificationService sends email
```

**Pattern 5: Kafka as Source of Truth + Compacted Topic:**

```python
# Write ONLY to Kafka, use compacted topic + state store
# to rebuild database state:

class KafkaFirstOrderService:
    def create_order(self, order_data):
        # 1. Write to Kafka FIRST
        produce_result = self.kafka.produce(
            topic="orders",
            key=order_data['id'],  # Key for compaction
            value=order_data,
            headers={'event_type': 'OrderCreated'},
        )

        # 2. Kafka consumer updates the database
        # This is ASYNC — the DB eventually reflects Kafka
        # But we told the client "order created" before DB writes!

    def get_order(self, order_id):
        # Option A: Read from DB (eventually consistent)
        # Option B: Read from Kafka Streams state store (stronger)

# The insight: Kafka log = source of truth.
# Database = materialized view of the log.
# No dual-write because you only write to ONE system (Kafka).
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Full landscape** | Can list 5+ dual-write solutions with trade-offs |
| **Outbox depth** | Explains the outbox pattern as the pragmatic choice for most systems |
| **Kafka-first** | Mentions writing to Kafka first and rebuilding state from log |
| **Event sourcing** | Suggests event sourcing as the most consistent but most complex approach |

---

## 8. Idempotency & Exactly-Once Semantics

**Q:** "We need exactly-once processing for a payment system. Explain why true exactly-once is impossible in distributed systems. Then design a practical implementation that achieves 'effectively once' using idempotency keys. Include the API design, database schema, and failure scenarios."

**What They're Really Testing:** Whether you understand that exactly-once means idempotent-at-least-once, and can design the full idempotency infrastructure: API → service → persistence → messaging.

### Answer

**Why True Exactly-Once Is Impossible:**

```
FLP Impossibility Result:
  In an asynchronous distributed system, no protocol can guarantee
  both safety and liveness in the presence of failures.

  → You can't know if a message was processed or not after a timeout.
  → The sender MUST retry on timeout.
  → Retries GUARANTEE at-least-once delivery.

So "exactly-once" in practice = idempotent at-least-once.

  At-least-once: You may process the same message multiple times.
  Idempotent: Processing it twice has the same effect as once.
  Result: You observe "exactly-once" from the outside.
```

**Full Idempotency Architecture:**

```python
# ── LAYER 1: API-level idempotency key ──────────────────
# Client sends idempotency-key header. Server deduplicates.

from flask import Flask, request, jsonify
import uuid

app = Flask(__name__)

class PaymentAPI:
    def __init__(self, db, kafka_producer):
        self.db = db
        self.kafka = kafka_producer

    def charge(self, amount: float, currency: str,
               source: str, idempotency_key: str = None) -> dict:
        """
        Charge a payment source. Idempotent by design.

        Idempotency key:
          - Generated by client (e.g., uuid4)
          - Sent as 'Idempotency-Key' header
          - Stored for at least 24 hours
          - If same key arrives again, return cached result

        Guarantees:
          - Client can retry ANY failed request safely
          - Charge is processed exactly-once (effectively)
          - Response is identical for retries
        """

        if not idempotency_key:
            idempotency_key = str(uuid.uuid4())

        # Check if we've seen this key before
        existing = self.db.fetch("""
            SELECT response_body, status_code, created_at
            FROM idempotency_keys
            WHERE idempotency_key = %s
        """, (idempotency_key,))

        if existing:
            # Return the CACHED response — retry of a completed request
            return {
                'status': existing['status_code'],
                'body': existing['response_body'],
                'cached': True,
            }

        # NEW request — process it
        # Use a DB-level lock to prevent double processing
        lock_acquired = self.db.execute("""
            INSERT INTO idempotency_locks (idempotency_key, created_at)
            VALUES (%s, NOW())
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
        """, (idempotency_key,))

        if not lock_acquired:
            # Another request is processing this key — wait or retry
            raise RetryLater("Another request is processing this idempotency key")

        try:
            # Process the payment
            result = self._process_charge(amount, currency, source)

            # Cache the response
            response_body = json.dumps({'charge_id': result['id'], 'status': 'succeeded'})
            self.db.execute("""
                INSERT INTO idempotency_keys (idempotency_key, response_body,
                                              status_code, created_at)
                VALUES (%s, %s, 200, NOW())
            """, (idempotency_key, response_body))

            # Remove the lock
            self.db.execute("""
                DELETE FROM idempotency_locks WHERE idempotency_key = %s
            """, (idempotency_key,))

            return json.loads(response_body)

        except Exception as e:
            # For certain errors, we can retry
            if self._is_retriable(e):
                # Don't cache the error — client will retry
                self.db.execute("""
                    DELETE FROM idempotency_locks WHERE idempotency_key = %s
                """, (idempotency_key,))
                raise

            # Permanent failure — cache the error too
            error_body = json.dumps({'error': str(e)})
            self.db.execute("""
                INSERT INTO idempotency_keys (idempotency_key, response_body,
                                              status_code, created_at)
                VALUES (%s, %s, 400, NOW())
            """, (idempotency_key, error_body))

            self.db.execute("""
                DELETE FROM idempotency_locks WHERE idempotency_key = %s
            """, (idempotency_key,))

            raise

    def _process_charge(self, amount, currency, source):
        # Process with payment gateway
        # Must generate unique charge_id (e.g., from payment gateway)
        return self.payment_gateway.charge(amount, currency, source)

    def _is_retriable(self, error):
        return isinstance(error, (TimeoutError, ConnectionError, ServiceUnavailable))
```

```sql
-- ── LAYER 2: Database schema for idempotency ────────────

-- Idempotency key table (for API-level dedup)
CREATE TABLE idempotency_keys (
    idempotency_key VARCHAR(255) PRIMARY KEY,
    response_body JSONB NOT NULL,
    status_code INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- TTL: delete after 24 hours
    -- (or use partitioned table by created_at)
);

-- Idempotency lock table (to prevent concurrent processing)
CREATE TABLE idempotency_locks (
    idempotency_key VARCHAR(255) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- TTL: auto-release after 60 seconds
    -- (lock can be stale if worker crashes)
);

-- Index for fast cleanup
CREATE INDEX idx_idempotency_created ON idempotency_keys(created_at);
```

```python
# ── LAYER 3: Messaging idempotency (consumer side) ──────

class IdempotentMessageConsumer:
    """
    Consumes Kafka messages idempotently.
    Uses a dedup table to prevent double-processing.
    """

    def __init__(self, db, kafka_consumer):
        self.db = db
        self.consumer = kafka_consumer

    async def process_message(self, message):
        """
        Process a Kafka message idempotently.

        The idempotency key comes from:
          - message.key (if producer set it)
          - message.headers['idempotency_key']
          - Or a deterministic function of message content
        """
        idempotency_key = self._extract_idempotency_key(message)

        # Try to claim this message
        claimed = await self.db.execute("""
            INSERT INTO processed_messages (message_id, idempotency_key,
                                           topic, partition, offset,
                                           processed_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
        """, (
            message.id,
            idempotency_key,
            message.topic,
            message.partition,
            message.offset,
        ))

        if not claimed:
            # Already processed — skip
            logger.info(f"Skipping duplicate message {message.id}")
            return

        # Process the message
        try:
            await self._handle_message(message)
        except Exception as e:
            # Remove the claim so we can retry
            await self.db.execute("""
                DELETE FROM processed_messages
                WHERE idempotency_key = $1
            """, idempotency_key)
            raise

    def _extract_idempotency_key(self, message) -> str:
        """Extract or generate idempotency key from message."""
        # First choice: explicit key from headers
        if 'idempotency_key' in (message.headers or {}):
            return message.headers['idempotency_key']

        # Second choice: Kafka message key
        if message.key:
            return f"{message.topic}:{message.partition}:{message.key}"

        # Fallback: offset-based (less ideal)
        return f"{message.topic}:{message.partition}:{message.offset}"
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **FLP justification** | Explains WHY exactly-once is impossible (FLP theorem) |
| **Idempotency key flow** | Designs API → DB → messaging idempotency end-to-end |
| **Concurrent requests** | Uses INSERT ON CONFLICT + lock table to prevent double processing |
| **Retriable vs permanent** | Distinguishes errors that can be retried vs those that should be cached as failures |

---

## 9. Compensating Transaction Design

**Q:** "Design a compensating transaction framework for a flight booking system. What makes a good compensating transaction? How do you handle compensations that fail? How do you prevent compensations from being lost?"

**What They're Really Testing:** Whether you understand that compensations are business actions, not technical rollbacks, and can design them with the same care as forward transactions.

### Answer

**What Makes a Good Compensation:**

```
GOOD compensation: A business action that semantically undoes
                   a previous action.

  Forward:  Reserve inventory → Compensation: Release inventory
  Forward:  Charge credit card → Compensation: Refund credit card
  Forward:  Book hotel room    → Compensation: Cancel hotel booking
  Forward:  Send email         → Compensation: Send follow-up email
                                     ("We're sorry, your order was cancelled")

BAD compensation: Trying to "rollback" a side effect.

  Forward:  Send notification → Compensation: "Unsend" the notification
  (IMPOSSIBLE — you can't un-ring a bell)
  (Instead: send a corrective notification)

PRINCIPLES:
  1. Compensations are SEMANTIC — they mirror business actions, not DB changes
  2. Compensations must be IDEMPOTENT — retrying is safe
  3. Compensations must be REVERSIBLE — if compensation fails, system must
     remain in a known state
  4. Compensations should be COMMUTATIVE — order of compensations shouldn't
     (usually) matter
  5. Compensations should have a DEADLINE — eventually they must succeed or
     escalate to manual intervention
```

**Concrete Implementation — Flight Booking Saga:**

```python
class FlightBookingSaga:
    """
    Saga for booking a flight with compensation support.

    Steps:
      1. Reserve seats (hold for 15 min)
      2. Charge payment
      3. Issue ticket
      4. Send confirmation

    Compensations:
      1. Cancel seat reservation
      2. Refund payment
      3. Void ticket
      4. (No compensation needed for email — or send cancellation email)
    """

    # ── STEP 1: Reserve seats ────────────────────────────
    async def step_reserve_seats(self, booking: Booking) -> StepResult:
        """Reserve seats on the flight. Hold for 15 minutes."""
        try:
            reservation = await self.flight_api.hold_seats(
                flight_id=booking.flight_id,
                seats=booking.seats,
                hold_duration_minutes=15,
                reference=booking.booking_id,
            )
            return StepResult(
                step="reserve_seats",
                success=True,
                data={'reservation_code': reservation.code},
            )
        except FlightFullError:
            return StepResult(step="reserve_seats", success=False,
                              error="Flight is full", retriable=False)
        except TimeoutError:
            return StepResult(step="reserve_seats", success=False,
                              error="Flight API timeout", retriable=True)

    # ── COMPENSATION 1: Cancel reservation ───────────────
    async def compensate_reserve_seats(self, booking: Booking,
                                       step_data: dict) -> CompResult:
        """
        Cancel the seat reservation.

        IDEMPOTENT: If already cancelled, return success.
        MUST SUCCEED: Retry with backoff.
        """
        reservation_code = step_data['reservation_code']
        for attempt in range(5):
            try:
                await self.flight_api.cancel_hold(reservation_code)
                return CompResult(step="reserve_seats", success=True)
            except Exception as e:
                if attempt == 4:
                    # Failed after all retries — DLQ
                    return CompResult(
                        step="reserve_seats",
                        success=False,
                        error=str(e),
                        dlq=True,  # Requires manual intervention
                    )
                await asyncio.sleep(2 ** attempt)

    # ── STEP 2: Charge payment ───────────────────────────
    async def step_charge_payment(self, booking: Booking) -> StepResult:
        """Charge the customer's payment method."""
        try:
            charge = await self.payment_gateway.charge(
                amount=booking.total_amount,
                currency='USD',
                source=booking.payment_token,
                idempotency_key=f"charge-{booking.booking_id}",
            )
            return StepResult(
                step="charge_payment",
                success=True,
                data={'charge_id': charge.id, 'amount': charge.amount},
            )
        except CardDeclinedError:
            return StepResult(step="charge_payment", success=False,
                              error="Card declined", retriable=False)
        except InsufficientFundsError:
            return StepResult(step="charge_payment", success=False,
                              error="Insufficient funds", retriable=False)

    # ── COMPENSATION 2: Refund payment ───────────────────
    async def compensate_charge_payment(self, booking: Booking,
                                        step_data: dict) -> CompResult:
        """
        Refund the charged amount.

        IMPORTANT: Different from void! A void happens before settlement
        (within 24h), a refund happens after settlement.
        Both are idempotent.
        """
        charge_id = step_data['charge_id']
        amount = step_data['amount']
        try:
            # Check if already refunded
            refund_status = await self.payment_gateway.get_refund_status(
                charge_id=charge_id,
                idempotency_key=f"refund-{booking.booking_id}",
            )
            if refund_status in ('completed', 'pending'):
                return CompResult(step="charge_payment", success=True)

            # Process refund
            await self.payment_gateway.refund(
                charge_id=charge_id,
                amount=amount,
                reason="booking_cancelled",
                idempotency_key=f"refund-{booking.booking_id}",
            )
            return CompResult(step="charge_payment", success=True)

        except Exception as e:
            return CompResult(step="charge_payment", success=False,
                              error=str(e), dlq=True)
```

**Handling Failed Compensations — The Compensation Store:**

```sql
-- Every compensation attempt is recorded:
CREATE TABLE compensation_attempts (
    id BIGSERIAL PRIMARY KEY,
    saga_id UUID NOT NULL,
    step_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,  -- 'PENDING', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED'
    error_message TEXT,
    attempt_number INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Unresolved compensations (DLQ for sagas):
CREATE TABLE unresolved_compensations (
    id BIGSERIAL PRIMARY KEY,
    saga_id UUID NOT NULL,
    booking_id UUID NOT NULL,
    step_name VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    error_message TEXT NOT NULL,
    retry_count INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'PENDING',  -- PENDING, RESOLVED, ESCALATED
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    escalated_at TIMESTAMPTZ
);
```

```python
# ── Saga Compensation Monitor ─────────────────────────────
class SagaCompensationMonitor:
    """
    Background worker that monitors and retries failed compensations.
    Runs every minute.
    """

    async def retry_failed_compensations(self):
        """Find and retry failed compensations."""
        unresolved = await self.db.fetch("""
            SELECT * FROM unresolved_compensations
            WHERE status = 'PENDING'
              AND retry_count < 10
              AND (last_retry_at IS NULL OR last_retry_at < NOW() - INTERVAL '5 minutes')
            ORDER BY created_at ASC
            LIMIT 100
        """)

        for comp in unresolved:
            await self._attempt_compensation(comp)

    async def _attempt_compensation(self, comp):
        """Attempt a compensation with full context."""
        saga = await self._load_saga(comp['saga_id'])
        step_data = saga['step_data'][comp['step_name']]

        try:
            # Execute the compensation with full business context
            await self._execute_compensation(
                step_name=comp['step_name'],
                booking_id=comp['booking_id'],
                step_data=step_data,
            )

            # Mark as resolved
            await self.db.execute("""
                UPDATE unresolved_compensations
                SET status = 'RESOLVED', updated_at = NOW()
                WHERE id = $1
            """, comp['id'])

        except Exception as e:
            await self.db.execute("""
                UPDATE unresolved_compensations
                SET retry_count = retry_count + 1,
                    last_retry_at = NOW()
                WHERE id = $1
            """, comp['id'])

            if comp['retry_count'] >= 10:
                await self._escalate_to_human(comp)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Semantic compensations** | Explains compensations as business actions (refund), not DB rollbacks |
| **Idempotent compensation** | Checks if already compensated before acting (GET-refund-status before refund) |
| **Failed compensation handling** | Designs retry queue, escalation to humans for stuck compensations |
| **Compensation store** | Persists compensation attempts and unresolved compensations |

---

## 10. Pattern Comparison & Decision Matrix

**Q:** "I have 6 different scenarios. Walk through which pattern you'd choose for each and why."

**What They're Really Testing:** Whether you can apply patterns to real scenarios with concrete rationale.

### Answer

**Decision Matrix:**

```yaml
SCENARIO 1: Payment transfer between two accounts in the same bank
Constraints: Strong consistency required, short duration, < 100ms
Pattern: 2PC (or local ACID if same DB)
Rationale: Same database, short transaction, strong consistency needed.
           No compensations needed (just ROLLBACK on failure).

SCENARIO 2: Order processing across 5 microservices (inventory, payment, shipping, notification, analytics)
Constraints: 1000 orders/second, < 2s total, compensations possible
Pattern: Orchestration Saga + Transactional Outbox
Rationale: High throughput rules out 2PC. Compensations are business
           actions (refund, restock). Orchestrator provides visibility.
           Outbox ensures reliable event publishing.

SCENARIO 3: Hotel reservation system with 15-minute hold
Constraints: Must guarantee room isn't double-booked, temporary hold
Pattern: TCC (Try-Confirm/Cancel)
Rationale: Short-term hold prevents double-booking without long locks.
           Auto-cancel if confirmation doesn't arrive in 15 minutes.
           Confirm is idempotent.

SCENARIO 4: Cross-cloud data replication (AWS → GCP)
Constraints: 50ms RTT, 10K events/second
Pattern: CDC-based Outbox (Debezium)
Rationale: High latency makes 2PC/3PC unusable (adds 200ms+).
           Debezium reads WAL with <10ms latency.
           No application-level code needed.

SCENARIO 5: Legacy monolith migration to microservices
Constraints: 200K LOC, 30 tables, 2-month migration timeline
Pattern: Strangler Fig + Outbox for events
Rationale: Outbox events are the "strangler" interface — new microservices
           consume events from the monolith's outbox without direct DB access.

SCENARIO 6: Audit log that must NEVER lose events
Constraints: Zero data loss, 100 events/second, multi-cloud
Pattern: Outbox (with synchronous fsync) + CDC replication
Rationale: Events written in same DB transaction as business data.
           CDC replicates to Kafka with exactly-once semantics.
           Dual path: primary (CDC) and fallback (polling).
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Scenario application** | Maps patterns to concrete constraints, not abstract preferences |
| **Trade-off reasoning** | Explains WHY a pattern works for each scenario with quantifiable reasons |
| **Pattern combinations** | Combines patterns (Saga + Outbox, Strangler Fig + Outbox) |

---

## 11. Production Anti-Patterns & Pitfalls

**Q:** "What are the most common distributed transaction anti-patterns you've seen in production? How do you detect and fix them?"

**What They're Really Testing:** Real production experience with distributed transactions gone wrong.

### Answer

**Anti-Pattern 1: Distributed Transaction as a Service Call**

```python
# 🔴 ANTI-PATTERN: Making HTTP calls inside a DB transaction
def create_order(order_data):
    with db.transaction():
        order = db.execute("INSERT INTO orders ...")

        # HTTP call INSIDE transaction — LOCKS held during network!
        response = requests.post(
            "http://payment-service/charge",
            json={'order_id': order['id']},
            timeout=30,  # Lock held for 30 seconds!
        )

        # Wait, what if payment times out?
        # Transaction is open — holding row locks on orders table
        # Other operations on orders table now BLOCK
    # Transaction finally commits or rolls back after 30 seconds

# PROBLEMS:
# - Locks held during network I/O (can be seconds or minutes!)
# - Transaction scope is unbounded — can't predict duration
# - Cascading lock contention across the system
# - Connection pool exhaustion from long-held connections

# ✅ FIX: Outbox pattern — write to outbox in transaction,
#        let background publisher handle the HTTP call
```

**Anti-Pattern 2: Nested Sagas (Saga Inception)**

```python
# 🔴 ANTI-PATTERN: A compensation step starts ANOTHER saga
async def compensate_order(booking_id):
    # This compensation starts a saga that could FAIL
    result = await cancel_flight_saga(booking_id)
    if result.status == 'COMPENSATED':
        # What if cancel_flight_saga triggers ITS OWN compensation path?
        # → CASCADING ROLLBACKS that never settle
        pass

# PROBLEMS:
# - Cascading compensations: A compensates, compensation triggers B,
#   B's compensation triggers C... theoretically infinite
# - Can't reason about the system's state
# - Compensations that should be simple become complex sagas

# ✅ FIX: Compensations should be SIMPLE and ISOLATED
#        One compensation = one idempotent action
#        No saga inside a saga
```

**Anti-Pattern 3: Mixing Sync and Async in the Same Flow**

```python
# 🔴 ANTI-PATTERN: Part sync, part async
def create_order(order_data):
    # Sync: must complete immediately
    order = order_service.create(order_data)

    # Async: fire and forget
    kafka.produce("order.created", order)

    # Sync: must happen after async?!
    payment = payment_service.charge(order.id)
    # ⚠️ Payment might process BEFORE inventory reserves stock
    # ⚠️ Or inventory might reserve AFTER payment

# PROBLEM: Unclear ordering between sync and async paths
#          Race conditions in the time window between sync and async

# ✅ FIX: All-or-nothing. Either:
#   - Everything sync (orchestration saga with step-by-step execution)
#   - Everything async (choreography saga via events)
#   Don't mix sync and async for the same workflow
```

**Anti-Pattern 4: Forgetting About Compensation TTL**

```python
# 🔴 ANTI-PATTERN: No timeout on holds
# TCC for hotel room: Try holds the room indefinitely
def try_book_room(room_id):
    hold = db.execute("""
        INSERT INTO holds (room_id, status) VALUES ($1, 'HELD')
    """, room_id)
    return hold['id']
    # ⚠️ No expiry! If Confirm never comes, room is held forever.

# ✅ FIX: Always set TTL on holds
def try_book_room(room_id):
    hold = db.execute("""
        INSERT INTO holds (room_id, status, hold_expires_at)
        VALUES ($1, 'HELD', NOW() + INTERVAL '15 minutes')
    """, room_id)

    # Schedule auto-cleanup
    schedule(hold['id'], cancel_hold, delay=16 * 60)  # After TTL + grace period
    return hold['id']
```

**Anti-Pattern 5: State Without Recovery**

```python
# 🔴 ANTI-PATTERN: Saga state is only in memory
class SagaCoordinator:
    def __init__(self):
        self.state = {}  # In-memory only!

    async def execute(self, saga_id, steps):
        self.state[saga_id] = SagaState(current_step=0)
        # ⚠️ If coordinator crashes, ALL sagas are lost!

# ✅ FIX: Persist saga state to database
class SagaCoordinator:
    def __init__(self, db):
        self.db = db

    async def save_checkpoint(self, saga_id, step, status):
        await self.db.execute("""
            INSERT INTO saga_state (saga_id, current_step, status, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (saga_id) DO UPDATE
            SET current_step = $2, status = $3, updated_at = NOW()
        """, saga_id, step, status)
```

**Anti-Pattern 6: Non-Idempotent Compensations**

```python
# 🔴 ANTI-PATTERN: Compensation is NOT idempotent
def refund_payment(order_id):
    # What if this is called TWICE?
    payment_gateway.refund(order_id)  # ⚠️ Refunds the customer TWICE!

# ✅ FIX: Check before acting
def refund_payment(order_id):
    # Atomic check-and-act
    result = db.execute("""
        UPDATE payment_transactions
        SET refund_status = 'REFUNDED',
            refunded_at = NOW()
        WHERE order_id = $1
          AND refund_status IS NULL
        RETURNING id
    """, order_id)

    if result:
        # Only first call processes the refund
        payment_gateway.refund(order_id, idempotency_key=f"refund-{order_id}")
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Real anti-patterns** | Identifies concrete anti-patterns with code examples from production |
| **HTTP in transaction** | Spots the lock-holding-during-I/O anti-pattern immediately |
| **Cascading compensations** | Understands the saga-inception problem |
| **State persistence** | Knows that saga state must be persisted for crash recovery |

---

## 12. End-to-End System Design Interview

**Q:** "Design a ticket booking system (like Ticketmaster) that handles:
- 10,000 concurrent users trying to book the same popular event
- 1M events/day with 10,000 seats max per event
- Payment processing with exactly-once semantics
- Seat selection with guaranteed no-double-booking
- The system MUST NOT oversell"

**What They're Really Testing:** Whether you can compose multiple distributed transaction patterns into a coherent system design, handling contention, consistency, and scale.

### Answer

**System Architecture Overview:**

```yaml
┌─────────────────────────────────────────────────────────────────┐
│                        API GATEWAY                               │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────────┐   │
│  │ Search      │  │ Seat Select │  │ Booking               │   │
│  │ (read-only) │  │ (read-only) │  │ (write, idempotent)   │   │
│  └─────────────┘  └─────────────┘  └───────────┬───────────┘   │
└──────────────────────────────────────────────────┼──────────────┘
                                                   │
┌──────────────────────────────────────────────────┼──────────────┐
│                                                  │              │
│  ┌───────────────────────────────────────────────▼────────────┐ │
│  │              BOOKING ORCHESTRATOR (Saga Coordinator)       │ │
│  │                                                           │ │
│  │  Step 1: Reserve Seats (TCC Try — 10 min hold)           │ │
│  │  Step 2: Process Payment (idempotent, outbox)            │ │
│  │  Step 3: Issue Tickets (idempotent)                      │ │
│  │  Step 4: Send Confirmation (email outbox)                │ │
│  │                                                           │ │
│  │  Compensation 3: Void Tickets                             │ │
│  │  Compensation 2: Refund Payment                           │ │
│  │  Compensation 1: Release Seats (auto if TTL expires)     │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌─────────┐  │
│  │ Seat       │  │ Payment    │  │ Ticket     │  │ Outbox  │  │
│  │ Service    │  │ Service    │  │ Service    │  │ Pub.    │  │
│  │ (TCC)      │  │ (idempotent)│  │ (idempotent)│  │(CDC)   │  │
│  └────────────┘  └────────────┘  └────────────┘  └─────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Seat Reservation (TCC with Optimistic Locking):**

```sql
-- Seat reservation with optimistic locking and hold timeout:

-- Schema:
CREATE TABLE seats (
    id INT PRIMARY KEY,
    event_id INT NOT NULL,
    section VARCHAR(10),
    row_num INT,
    seat_num INT,
    version INT NOT NULL DEFAULT 0,  -- Optimistic lock
    status VARCHAR(20) DEFAULT 'AVAILABLE',  -- AVAILABLE, HELD, BOOKED
    hold_expires_at TIMESTAMPTZ,
    booking_id UUID,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_seats_event ON seats(event_id, status);

-- TCC Phase 1: Try (reserve seat with 10-minute hold)
-- Using optimistic locking to prevent contention:
def reserve_seats(event_id, seat_ids, booking_id):
    with db.transaction():
        for seat_id in seat_ids:
            updated = db.execute("""
                UPDATE seats
                SET status = 'HELD',
                    hold_expires_at = NOW() + INTERVAL '10 minutes',
                    booking_id = $1,
                    version = version + 1,
                    updated_at = NOW()
                WHERE id = $2
                  AND event_id = $3
                  AND status = 'AVAILABLE'
                  AND version = (
                      SELECT version FROM seats WHERE id = $2
                  )
                RETURNING version
            """, booking_id, seat_id, event_id)

            if not updated:
                # Seat already taken or held — rollback entire reservation
                self._release_all(event_id, seat_ids, booking_id)
                raise SeatNotAvailable(seat_id)

    return True  # All seats reserved

# Handle contention for popular events:
# 10000 users trying to book the same event:
# → Each user's transaction checks seats individually
# → First user to UPDATE wins (optimistic locking)
# → Other users get SeatNotAvailable (they see "sold out" instantly)
# → No queueing needed! Optimistic concurrency handles it.
```

**Payment Processing (Idempotent + Outbox):**

```python
# Payment step with exactly-once semantics:
def process_payment(booking_id, amount, payment_token):
    # Outbox pattern — write to outbox in same transaction
    with db.transaction():
        # 1. Insert payment record
        payment = db.execute("""
            INSERT INTO payments (booking_id, amount, status)
            VALUES ($1, $2, 'PROCESSING')
            RETURNING id
        """, booking_id, amount)

        # 2. Write to outbox (same transaction!)
        db.execute("""
            INSERT INTO outbox (event_type, aggregate_id, payload,
                               idempotency_key)
            VALUES ('payment.process', $1, $2, $3)
        """, booking_id, json.dumps({
            'payment_id': payment['id'],
            'amount': amount,
            'token': payment_token,
        }), f"payment-{booking_id}")

    # 3. Outbox publisher sends payment to external gateway
    # 4. Gateway webhook updates payment status
    # 5. On webhook: update payment + booking status in same transaction
```

**Exactly-Once Webhook Handling:**

```python
# Payment gateway sends webhooks. We handle them idempotently:
@app.route('/webhook/payment', methods=['POST'])
async def payment_webhook():
    payload = request.json
    event_id = payload['event_id']  # Unique event from payment gateway

    # Dedup: check if we already processed this webhook
    processed = await db.fetch("""
        INSERT INTO webhook_events (event_id, event_type, payload,
                                    processed_at)
        VALUES ($1, 'payment.update', $2, NOW())
        ON CONFLICT (event_id) DO NOTHING
        RETURNING id
    """, event_id, json.dumps(payload))

    if not processed:
        return jsonify({'status': 'duplicate'}), 200

    # Process the webhook
    booking_id = payload['booking_id']
    payment_status = payload['status']

    if payment_status == 'succeeded':
        # Move to next saga step (issue tickets)
        await booking_orchestrator.complete_step(
            booking_id, 'payment', {'status': 'succeeded'}
        )
    elif payment_status == 'failed':
        # Start compensation flow
        await booking_orchestrator.fail_step(
            booking_id, 'payment', 'Payment failed'
        )

    return jsonify({'status': 'processed'}), 200
```

**Scaling for Popular Events (The Taylor Swift Problem):**

```yaml
PROBLEM: 10,000 concurrent users trying to book 20,000 seats
SOLUTION: Tiered booking queue + optimistic locking

1. Pre-booking queue:
   - Users join a virtual waiting room (Cloudflare Queue or custom)
   - Queue position assigned randomly (not FIFO — prevents scalpers)
   - User gets a session with a TTL when their turn arrives

2. Booking session:
   - User has 5 minutes to select and book seats
   - During this time, selected seats are HELD (TCC Phase 1)
   - If session expires, seats are released

3. Optimistic locking handles conflicts:
   - If two users select the same seat, the second gets an error
   - "Seat A12 is no longer available. Please select another seat."
   - User can immediately select a different seat (cache refreshes)

4. Payment:
   - 10-minute window to complete payment
   - After 10 minutes, held seats are released (auto cancellation)

5. Monitoring:
   ┌────────────────────────────────────────────────────┐
   │ Dashboard: Taylor Swift Booking                     │
   │                                                     │
   │ Total users in queue: 15,342                       │
   │ Active booking sessions: 2,150                     │
   │ Seats held: 8,341 / 20,000                         │
   │ Seats booked: 3,207                                │
   │ Seats released (expired): 1,234                    │
   │ Payment success rate: 94.2%                        │
   │ Average booking time: 3 min 42 sec                 │
   └────────────────────────────────────────────────────┘
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pattern composition** | Combines TCC (seat hold), Saga (booking flow), Outbox (reliable events) |
| **Contention handling** | Uses optimistic locking, not pessimistic locking, for high-concurrency hotspots |
| **Scalability** | Designs virtual waiting room, TTL-based holds, auto-expiry |
| **End-to-end flow** | Walks through the complete flow from seat selection to ticket issuance |

---

> *Master these patterns and you'll be prepared for the most rigorous distributed transaction questions at Staff/Principal Engineer interviews.*

