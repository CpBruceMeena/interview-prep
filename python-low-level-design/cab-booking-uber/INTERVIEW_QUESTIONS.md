# Cab Booking Service (Uber) - Interview Questions & Answers

> **Target Level:** Senior / Staff Engineer  
> **Evaluation Focus:** Matching under concurrency, trip state machine, geo-spatial indexing, surge, event-driven ingestion, failure handling

---

## Question 1: Core Design
**Interviewer:** *"Design a cab booking system like Uber — rider requests, driver matching, trip management, fare calculation."*

### 🎯 Expected Answer

**Domain Model:**
```
Rider ──→ Trip ──→ Driver
  │        │         ├── CabType (Mini, Sedan, SUV, ...)
  │        │         ├── CabStatus (AVAILABLE, BOOKED, ON_TRIP, OFFLINE)
  │        │         └── position lives in the GeoIndex, not on the Driver
  │        └── fare (Decimal, quoted at request), surge_multiplier, status
  └── at most one active trip
```

**Trip State Machine (as implemented):**
```
REQUESTED → ACCEPTED → DRIVER_ARRIVED → STARTED → COMPLETED
    │  ↺ decline       │                    │
    └──────────────────┴────────────────────┴──→ CANCELLED   (no cancel once STARTED)
```

**Key decisions:**
1. **Search → rank → claim.** Geo search finds candidates, a strategy ranks them, an atomic `try_claim()` books one. Losing a claim moves to the next candidate.
2. **Transitions in a table**, enforced under the trip's lock. Driver status follows the trip.
3. **Pricing as Strategy + Decorator** (`SurgePricing(StandardPricing(...))`), money as `Decimal`.
4. **Geo index behind one method** so linear scan → geohash → Redis GEO is a swap, not a rewrite.

---

## Question 2: Geo-spatial Indexing — Which and Why?
**Interviewer:** *"Compare geohash, quadtree, H3/S2, Redis GEO and PostGIS for finding nearby drivers."*

### 🎯 Answer

| Option | How it works | Strengths | Weaknesses |
|--------|--------------|-----------|------------|
| **Geohash** (and Redis GEO, which is a 52-bit geohash as a sorted-set score) | Interleave lat/lng bits; nearby points usually share a prefix | Simple, 1-D sortable, works in any ordered KV store | Cells are rectangles that distort with latitude; points near a cell edge can have totally different prefixes, so you **must query the 8 neighbours** |
| **Quadtree** (in-memory) | Recursively split a box when it holds > K points | Adapts to density (Manhattan vs suburbs) | Rebalancing on 33K moves/s; hard to shard; in-process only |
| **H3** (Uber) / **S2** (Google) | Hierarchical hexagons / sphere-projected squares, 64-bit cell ids | Uniform neighbours (H3), good for aggregation (surge, heatmaps), `grid_disk` for k-rings | Library, not a database; you still need a store keyed by cell id |
| **Redis GEO** | `GEOADD`, `GEOSEARCH ... BYRADIUS ... ASC COUNT n` | Sub-millisecond server time, trivial to run | Single key lives on one shard, so shard by city (or city+cell); in-memory only |
| **PostGIS** | GiST index on `GEOGRAPHY(Point)`, `ST_DWithin` | Polygons, joins, durability | Each location ping is an MVCC row update + index churn; 33K updates/s on one table means vacuum pain |

`GEOSEARCH` costs O(N + log M): N points in the bounding cells scanned, M in the shape. `GEORADIUS` is deprecated since Redis 6.2 in favour of `GEOSEARCH`.

**What I'd pick:** Redis GEO keyed per city and cab type (`drivers:available:{city}:{type}`) for the hot path, H3 resolution 8 cells for surge zones and analytics, PostGIS only for durable history and ad-hoc queries. The in-memory position index is **rebuildable**: every driver re-pings within ~3 s, so losing it costs one ping interval, not data.

The LLD (`GeoIndex`) mirrors Redis: a sorted list by geohash, radius search = 9 prefix-range scans at a precision whose cell is ≥ the radius, then exact haversine filter.

---

## Question 3: "Two riders request at the same time and the same driver is nearest. What happens?"

### 🎯 Answer

With check-then-act (`if driver.is_available(): driver.status = BOOKED`) both requests book the driver. The
fix is to make reservation a single atomic step and treat failure as "try the next one":

```python
for driver in strategy.rank(pickup, candidates):
    if driver.try_claim():          # CAS: AVAILABLE -> BOOKED under the driver's lock
        return driver
```

**In production**, the same CAS is one of:
- **Redis:** `SET driver:{id}:assignment {trip_id} NX PX 15000`. The TTL is the offer timeout; if the matcher dies, the lock frees itself.
- **SQL:** `UPDATE drivers SET status='BOOKED', trip_id=? WHERE id=? AND status='AVAILABLE'` and check rows affected = 1.
- **Single-writer:** route all matching for a geo cell to one partition/actor (Uber's dispatch shards by area), which removes the race instead of arbitrating it.

Follow-up push: *"What if the claim succeeds but the service crashes before creating the trip?"* The Redis TTL / a reaper releases claims with no trip after N seconds. Never rely on the crashed process to clean up.

Also mention the rider side: the same rider double-tapping. Reserve the rider (`_active_trip_by_rider`) before matching, or make `request_ride` idempotent with a client-supplied request id.

---

## Question 4: "Now the driver can decline. Add it."

### 🎯 Answer

That is why `REQUESTED` exists separately from `ACCEPTED`. `decline_trip` (also called by an offer-timeout timer):
1. Under the trip lock, check status is still `REQUESTED`.
2. Add the driver to `trip.declined_by`, set them back to `AVAILABLE`.
3. Re-run the claim loop excluding `declined_by`; on success reassign, otherwise cancel with "no driver accepted".

Edge cases: decline arriving after accept (rejected by the state check); the timeout and an accept racing (trip lock gives one winner); repeatedly offering the same driver (excluded set).

---

## Question 5: "Rider cancels while the driver presses Start."

### 🎯 Answer

Both actions take `trip.lock`, then validate against the transition table. Whichever gets the lock first wins; the other gets `InvalidTransitionError` and the client shows "trip already started" / "trip was cancelled". Driver status is changed inside the same critical section, so it can never disagree with the trip. In a service: `UPDATE trips SET status='STARTED', version=version+1 WHERE id=? AND status='DRIVER_ARRIVED' AND version=?` gives the same guarantee without an in-process lock.

---

## Question 6: GPS Ingestion Pipeline
**Interviewer:** *"Ingest location updates from 100K drivers every 3 seconds."*

### 🎯 Answer

**Numbers:** 100K / 3 s ≈ 33K updates/s. At ~100 bytes each that is ~3.3 MB/s, ~290 GB/day raw.

```
Driver app ──WebSocket (protobuf)──▶ Gateway ──▶ Kafka gps.raw.updates (key = driver_id)
                                                     │
                                         Stream processor (consumer group)
                                           ├── validate (bad → gps.dlq)
                                           ├── drop if ts < last ts for driver
                                           ├── GEOADD drivers:available:{city}:{type}
                                           ├── zone = H3 cell → gps.enriched.locations
                                           └── commit offset after the write
                                                     │
                                         Zone aggregator (tumbling 30 s window) → gps.zone.driver_counts
                                         History sink → Cassandra (TTL 90 days)
```

**Decisions that matter:**
1. **Key by `driver_id`** so one driver's pings are ordered within a partition.
2. **At-least-once + idempotent consumer.** Commit after the Redis write; on replay the timestamp guard ignores anything not newer. (`enable.idempotence=true` on the producer only stops duplicate *appends* from producer retries; it does not give exactly-once into Redis.)
3. **Don't compact the raw topic** — it's an event stream with time retention. If you need "latest position per driver" for bootstrapping, publish a separate compacted topic keyed by driver.
4. **Redis memory policy `noeviction`**, sized for peak. `allkeys-lru` could evict the *entire* geo key (it is one key) and silently empty the index.
5. **Backpressure:** if Redis is slow, pause partitions rather than buffering unbounded in memory. Stale positions are worth less than fresh ones, so on long lag it's fine to skip ahead to the latest offset.

**Failure modes:** broker loss (RF=3, `min.insync.replicas=2`, `acks=all`); processor crash (rebalance, replay from last commit, harmless because idempotent); Redis failover (async replication can lose the last second of positions, which the next ping fixes).

---

## Question 7: Zone-Based Surge
**Interviewer:** *"How do you create zones and count drivers per zone in real time?"*

### 🎯 Answer

**Zones:** H3 cells. Resolution 8 (≈ 0.74 km², ≈ 0.46 km edge) is a sensible surge granularity in a dense city; resolution 7 (≈ 5.2 km²) for suburbs. Zone lookup is O(1): `h3.latlng_to_cell(lat, lng, 8)`.

```python
import h3, math   # h3 >= 4 API

def zones_covering(lat, lng, radius_km, res=8):
    center = h3.latlng_to_cell(lat, lng, res)
    spacing_km = math.sqrt(3) * h3.average_hexagon_edge_length(res, unit="km")  # centre-to-centre
    return h3.grid_disk(center, math.ceil(radius_km / spacing_km))
```

The LLD uses geohash-6 cells (`ZoneManager`) for the same O(1) lookup without a library.

**Counting drivers per zone (supply):** count each driver once, in their *latest* zone, and only if AVAILABLE.

- **Redis:** on each ping, if the zone changed: `ZREM zone:{old}:drivers id`; always `ZADD zone:{new}:drivers <ts> id`. Count with `ZREMRANGEBYSCORE zone:{z}:drivers -inf <now-30s>` then `ZCARD`. (A hash with `EXPIRE` doesn't work: the TTL applies to the whole hash, not each driver, and a driver who leaves stays counted.)
- **Stream:** windowed aggregation keyed by zone over the enriched topic; this is what `ZoneAnalyticsAggregator` simulates.

**Demand:** ride requests per zone per window (count unmatched requests too; that's the signal).

**Surge function:** a step or smooth function of demand/supply, with **no surge when demand is zero**, a cap, hysteresis (decay over minutes rather than dropping instantly, so drivers don't chase flickering zones), and smoothing across neighbouring cells so adjacent zones don't differ by 2×. Lock the multiplier into the quote at request time; a rider must never be charged a surge they didn't see.

---

## Question 8: Failure Handling & Idempotency

| Scenario | Handling |
|----------|----------|
| Rider retries `request_ride` after a timeout | Client sends `Idempotency-Key`; server stores key → trip id (`trips.idempotency_key UNIQUE`) and returns the existing trip |
| Matcher crashes after claiming a driver | Claim has a TTL / reaper; driver returns to AVAILABLE |
| Driver app offline mid-offer | Offer timeout → `decline_trip` → re-match |
| Driver app offline mid-trip | Trip stays STARTED; positions resume on reconnect; ops alert after N minutes |
| Payment capture fails at completion | Trip still COMPLETED; payment is a separate state machine with retries and an outbox event |
| Duplicate trip events to consumers | Consumers dedupe by (trip_id, status/version) |
| Redis GEO lost | Rebuilt from the next ~3 s of pings; fall back to PostGIS meanwhile if needed |

Trip status changes should be written with an **outbox**: update `trips` and insert into `outbox` in one DB transaction; a relay publishes to Kafka. Publishing directly after commit loses events on crash.

---

## Question 9: Testing Strategy

- **Unit:** pricing (exact `Decimal`s), surge curve edges (0/0, 0 supply), every legal and illegal transition, geohash known values, neighbour search across a cell edge and the antimeridian, stale-update rejection.
- **Concurrency:** N riders × 1 driver → exactly 1 trip, repeated in a loop; N riders × N drivers → N trips, N distinct drivers (proves losers fall through); cancel vs start → exactly one winner and consistent driver status. Use a `threading.Barrier` to line threads up.
- **Mutation check:** replace `try_claim` with a racy version and confirm the test fails (it does in `test_cab_booking.py`).
- **Service level:** contract tests for events; a soak test replaying recorded GPS through the pipeline; chaos test killing the matcher between claim and trip creation.

---

## Question 10: Fraud — GPS Spoofing
**Interviewer:** *"How do you detect GPS spoofing?"*

### 🎯 Answer

| Signal | Check |
|--------|-------|
| Impossible speed | distance between consecutive pings / Δt > ~200 km/h in a city |
| Teleport on reconnect | large jump after a gap with no plausible route |
| Mock-location flag / rooted device | OS APIs, device attestation (Play Integrity / App Attest) |
| Cell / Wi-Fi disagreement | network-derived location far from GPS fix |
| Surge gaming | clusters of drivers going offline together just before a surge and reappearing after |

Real-time checks (speed, mock flag) run in the stream processor; behavioural ones run in batch and feed a risk score.

---

## Question 11: GPS Loss (Tunnels)

Dead reckoning from last speed and heading, with confidence decaying over ~30 s:

```python
def estimate(last: Location, speed_kmh: float, heading_deg: float, elapsed_s: float) -> Location | None:
    if elapsed_s > 30:
        return None                                   # too stale: mark position unknown
    km = speed_kmh * elapsed_s / 3600
    d_lat = km * math.cos(math.radians(heading_deg)) / 111.32
    d_lng = km * math.sin(math.radians(heading_deg)) / (111.32 * math.cos(math.radians(last.lat)))
    return Location(last.lat + d_lat, last.lng + d_lng)
```

Tag estimated positions; exclude them from surge counts; on re-acquisition snap to the real fix. In practice map-matching to the road graph does far better than straight-line dead reckoning.

---

## Question 12: Pool Rides

Batch pool requests per zone for 15–30 s. For a candidate pair, compute the best insertion order (e.g. P1 → P2 → D1 → D2 vs P1 → P2 → D2 → D1) on road-network ETAs, and accept only if each rider's extra time ≤ their detour budget (say 5–8 min). Driver gets `seats_free`; the claim becomes "decrement seats if enough" — still a CAS. Pricing: each rider gets a discount quoted up front, independent of whether a match is eventually found.

---

## Question 13: Design Patterns

| Pattern | Where (in code) |
|---------|-----------------|
| **Strategy** | `PricingStrategy`, `DriverMatchingStrategy.rank()` |
| **Decorator** | `SurgePricing` wraps any `PricingStrategy` (tolls, discounts compose the same way) |
| **State machine (table-driven)** | `_TRANSITIONS` + `Trip._move()` |
| **Facade** | `CabBookingService` |
| **Pub/Sub** | `KafkaBroker` topics consumed by the stream processors |

---

## ⚠️ Common Mistakes

1. Check-then-act on driver availability (the double-booking bug), or "fixing" it with one global lock around all matching.
2. Treating a failed claim as "no driver available" instead of trying the next candidate.
3. A geohash prefix search that ignores the 8 neighbouring cells.
4. Claiming geohash/Redis GEO lookup is "O(log N)" with no mention of the M points scanned.
5. No transition validation: cancelling a completed trip frees a driver who may be on another trip.
6. Floats for money; computing the fare at completion from a surge the rider never saw.
7. Surge > 1 in a zone with zero demand; counting a moving driver in every zone they passed through.
8. Driver location stored on the `Driver` row and in the index, updated in two places that drift.
9. Library code that `print`s instead of returning or raising.

---

## 🎚️ Senior vs Staff Signal

- **Senior:** clean entities and strategies, a correct state machine, an atomic claim that falls through to the next driver, and tests that prove it. Knows Redis GEO and geohash neighbours.
- **Staff:** all of that, plus frames the problem in numbers (33K writes/s, rebuildable index, one ping interval of loss is acceptable), chooses *where* consistency is needed (the claim and the trip row) and where it isn't (positions, surge), names the production equivalents of each lock (`SET NX PX`, conditional UPDATE, per-cell single writer), designs for crash-between-steps (TTL claims, outbox, idempotency keys), and talks about surge as a product/fairness problem, not just a formula.
