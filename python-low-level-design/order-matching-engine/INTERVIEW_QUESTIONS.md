# Order Matching Engine - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)
> **Evaluation Focus:** Data structures and complexity, price-time priority correctness, determinism, single-writer concurrency, recovery

---

## Question 1: Complexity
**Interviewer:** *"What does each operation cost in your book?"*

### 🎯 Expected Answer

L = price levels on one side, F = maker orders a taker fills, E = levels it empties.

| Operation | This implementation | Notes |
|-----------|--------------------|-------|
| Best bid/ask | O(1) amortized | Heap peek; stale tops popped at O(log L) each, and each price is pushed once per live period |
| Add order at existing level | O(1) | dict lookup + `OrderedDict` append |
| Add order at new level | O(log L) | heap push |
| Cancel | O(1) | `_live` dict + `OrderedDict.pop`; heap cleaned lazily |
| Match | O(F + E log L) | O(1) per fill; each emptied level costs a heap pop when it surfaces |
| FOK pre-check | O(L log L) | Sorts live levels; a tree map would make it O(k log L) for the k levels walked |
| Depth snapshot | O(L log L) | Off the hot path |

Memory: O(orders + levels). Stale heap entries are bounded by distinct prices touched, because `_in_heap` prevents duplicates.

Follow-up, *"how would you make it O(1)?"* Exchanges bound prices with price bands (e.g. ±X% of a reference price), so the set of valid ticks is small and known. Use an **array indexed by `price - band_low`** of level pointers plus a best-index pointer. Add/cancel/best are O(1); when the best level empties you scan forward to the next non-empty slot, which is usually a few slots away (a bitmap with find-first-set makes it a couple of instructions).

---

## Question 2: Why not floats? Why not Decimal everywhere?
**Interviewer:** *"Prices are money. What type do you use?"*

### 🎯 Answer

- `float` can't represent 0.1 exactly; `100.1 + 0.2 != 100.3`. A buy at 100.30 must match an ask at 100.30 with an exact compare, every time.
- `Decimal` is exact but slow, and `Decimal("101.0")` vs `Decimal("101.00")` differ in their string form, which bites when prices are serialized and used as keys elsewhere.
- **Integer ticks**: price = ticks × tick_size. Integer compare is exact and fast, and it's what real engines use (often fixed-point `int64`). Convert once at the gateway and reject off-tick prices there.
- Quantities are integers too (shares/lots). Fractional crypto quantities use the same idea with a "lot size".

---

## Question 3: Make it concurrent
**Interviewer:** *"Thousands of clients submit at once. Where do the locks go?"*

### 🎯 Answer

Nowhere inside the book. **One writer per symbol** (a sequencer) and a queue in front of it.

- Every order for a symbol competes for the same best price, so matching for one symbol is inherently serial. A lock per book just serializes the same work with extra contention and cache-line bouncing; per-price-level locks are wrong because a sweep spans levels and the best-price index is shared.
- **Determinism** is the bigger reason. With locks, the order in which threads acquire them is decided by the OS scheduler and isn't recorded, so you can't reproduce what happened. With a sequencer, the input order is the journal; replaying it reproduces every trade. That is what makes recovery, primary/backup replication and audit possible.
- **Latency**: no lock handoffs or context switches on the hot path, so tail latency stays flat. LMAX's published architecture ran its business logic on a single thread and reported millions of orders per second.
- **Scale out by symbol**: symbols are independent, so partition them across threads, cores and machines. A single hot symbol can't be split; you make its one thread fast (no allocation, no I/O, pre-sized structures).

In the code: `SymbolSequencer` owns the queue, `_seq`, the `Journal` and the `OrderBook`. Callers get a `Future`.

Follow-up, *"what's still shared?"* The `Journal` (readers on other threads, hence its lock), listeners (run on the sequencer thread, must be fast and non-throwing), and `MatchingEngine._sequencers` (built once in `__init__`, read-only afterwards).

---

## Question 4: Recovery
**Interviewer:** *"The engine process dies. What happens to the book?"*

### 🎯 Answer

**Event sourcing on the inputs.**

1. The sequencer journals each command with its `seq` **before** applying it. In production the journal is replicated (Raft, Aeron Cluster, Kafka with `acks=all` and `min.insync.replicas` ≥ 2) and the client is only acked after the entry is durable.
2. Every N commands (or seconds) write a snapshot of the book tagged with the last applied `seq`.
3. Recovery = load the latest snapshot, then `replay` the journal from `seq + 1`.
4. For fast failover, run a **hot standby** that consumes the same sequenced journal and applies it continuously (state machine replication). On primary failure the standby is already at the head; promote it. Comparing primary and standby outputs (trade ids, report hashes) catches non-determinism early.

What breaks determinism (and how this code avoids it): reading wall-clock time (time priority is `seq`), randomness, iterating hash sets/maps whose order isn't defined (Python dicts are insertion-ordered; `_in_heap` is never iterated), floating point, and multi-threaded mutation.

Journal inputs or outputs? Inputs: they're smaller, they're what must be ordered, and outputs are derivable. You still persist outputs (trades) for downstream consumers, but they are not the recovery source of truth.

---

## Question 5: FOK and IOC
**Interviewer:** *"Add fill-or-kill. Can't you just match and roll back?"*

### 🎯 Answer

No. Matching mutates makers and emits trades; rolling back means un-trading orders that downstream systems may already have seen. Do a **read-only pre-check**: walk crossing levels best-first summing `total_quantity` until it reaches the order quantity. Only then match. Because the book is single-writer, nothing can change between check and match. That's a check-then-act that would be a race under fine-grained locking.

IOC: match normally, then cancel the remainder instead of resting it. Market orders behave like IOC (they have no price to rest at), so market + GTC is rejected.

---

## Question 6: Modify / cancel-replace
**Interviewer:** *"A client wants to change their order. What happens to priority?"*

### 🎯 Answer

Standard exchange rule:
- **Quantity down**: keep time priority. Reduce `remaining` and the level's `total_quantity` in place.
- **Price change or quantity up**: lose priority. Implement as cancel + new order (new `seq`). Otherwise a client could reserve a place in the queue with 1 share and later turn it into 10,000.
- Race: the replace arrives after the order fully filled → reject the replace (same as a late cancel). Clients must handle "too late to cancel".

---

## Question 7: Self-trade prevention
**Interviewer:** *"The same firm's buy and sell cross. Is that OK?"*

### 🎯 Answer

Usually not: wash trades are a regulatory problem. Check `maker.client_id` (or account / STP group) against the taker in `_match` before filling. Modes exchanges offer:

| Mode | Effect |
|------|--------|
| Cancel newest | Cancel the incoming taker (remainder) |
| Cancel oldest | Cancel the resting maker, keep matching |
| Cancel both | Cancel both |
| Decrement | Reduce both by the smaller quantity, no trade printed |

Subtlety: with "cancel oldest", a self-matching maker at the front of the level is removed and matching continues with the next maker. Don't skip over it and leave it resting, or you break the FIFO invariant.

---

## Question 8: Stop orders / iceberg orders
**Interviewer:** *"Add stop-loss orders."*

### 🎯 Answer

- Stops don't sit in the visible book. Keep a **stop book** per side keyed by trigger price (buy stops trigger when last trade ≥ trigger, sell stops when ≤ trigger).
- After each command's trades, find triggered stops and convert them to market/limit orders. To stay deterministic, enqueue them in a defined order (trigger price, then original `seq`) and process them before the next external command. Triggered stops can trade and trigger more stops: loop until quiet, with a cap.
- **Iceberg**: `display_qty` shows on the book; when the visible slice is filled, the next slice is appended to the **back** of the level (it loses time priority). Depth feeds show only the displayed quantity.

---

## Question 9: Market data
**Interviewer:** *"How do other participants see the book?"*

### 🎯 Answer

From the event stream, never by reading the book:
- **L1**: best bid/ask + last trade. **L2**: aggregated quantity per price (our `snapshot()`). **L3**: every order (adds, cancels, executions), e.g. NASDAQ ITCH.
- Published as incremental updates with a sequence number, usually over UDP multicast. Consumers detect gaps and recover from a periodic snapshot channel or a retransmit service.
- The publisher must never back-pressure the engine. A slow consumer falls behind and re-syncs from a snapshot.

---

## Question 10: Testing strategy
**Interviewer:** *"How do you know it's correct?"*

### 🎯 Answer

1. **Example tests** for each rule: price priority, FIFO, maker price, partial fill both sides, sweep, IOC, FOK both ways, cancel and double cancel.
2. **Invariants checked after every command** (property-based / fuzz): the book is never crossed; per order `filled + resting + cancelled == quantity`; level `total_quantity` equals the sum of its orders; no order rests with `remaining == 0`.
3. **Replay equivalence**: random concurrent workload → journal → `replay` → identical book and trade list (in `test_order_matching_engine.py`).
4. **Reference model**: a naive O(n) matcher (sort all orders every time) run side by side on random inputs; outputs must match exactly.
5. **Golden files** of real-ish sessions for regression, plus latency benchmarks in CI for the production engine.

---

## Question 11: Scaling the design
**Interviewer:** *"How does this become an exchange?"*

### 🎯 Answer

Gateways (session, auth, ClOrdID dedupe) → pre-trade risk → sequencer (durable, replicated log per partition) → matching engine shards (by symbol) → market data + drop copy + clearing as journal consumers. See [High-Level Design](HIGH_LEVEL_DESIGN.md).

---

## ⚠️ Common mistakes

- Using `float` prices, or `time.time()` as time priority (two orders in the same microsecond, clock steps backwards, replay impossible).
- Trading at the taker's price instead of the maker's.
- `deque` per level with O(n) cancel, then claiming O(1) cancel.
- Forgetting to update the level's aggregate quantity on partial fills, so depth and FOK go wrong.
- Leaving empty levels in the book, so "best price" points at a level with no orders.
- Resting a market order, or resting an IOC remainder.
- FOK implemented as "match, then undo".
- Throwing exceptions for a late cancel. It's a normal race; reply with a reject.
- Putting locks around the book and calling it done, with no answer for determinism or recovery.
- Mutating the order object you returned to the client, so their "report" changes after the fact.

---

## 🎯 Senior vs Staff signal

- **Senior**: correct price-time matching with partial fills, sensible structures with the complexity stated correctly, clean extension to IOC/FOK/cancel, thread-safe via a single writer or a coarse lock, solid tests.
- **Staff**: leads with the invariants and the sequencer. Explains why determinism drives the whole architecture (replay, hot standby, audit) and what breaks it. Picks integer ticks without being asked. Knows the price-banded array trick and when it pays off. Separates commands from events, ack-after-durable, market data that never back-pressures the engine. Talks about operational controls: kill switch, cancel-on-disconnect, price bands / trading halts.
