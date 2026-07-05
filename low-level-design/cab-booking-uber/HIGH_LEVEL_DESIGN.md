# 🏗️ Cab Booking Service (Uber) — High-Level Design

> **Target Level:** Staff/Principal Engineer | **Focus:** Geo-spatial indexing, event-driven architecture, real-time stream processing, distributed systems

---

## 1. SYSTEM OVERVIEW

**Purpose:** On-demand cab booking connecting riders with drivers in real-time with dynamic pricing.

**Scale:** 50 cities, 1M rides/day, 100K active drivers peak, 500 concurrent rides/minute per city

**Users:** Riders, Drivers, Operations team, Analytics

**Use Cases:** Request ride, Driver matching, Real-time tracking, Surge pricing, Payment & billing, Driver dispatch optimization

**Constraints:** <1s driver matching latency, 99.99% uptime, GPS accuracy <10m, sub-100ms ETA calculation

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌──────────────┐     ┌──────────────┐
│ Rider App    │     │ Driver App   │
│ (React       │     │ (React       │
│  Native)     │     │  Native)     │
└──────┬───────┘     └──────┬───────┘
       │                    │
       └────────┬───────────┘
                │ WebSocket / HTTPS
       ┌────────▼───────────┐
       │     API Gateway     │
       │ (Kong, SSL term)    │
       └────────┬───────────┘
                │
    ┌───────────┼───────────────┐
    │           │               │
┌───▼───┐  ┌────▼────┐  ┌──────▼────┐
│ Rider │  │ Driver  │  │ Trip      │
│ Svc   │  │ Svc     │  │ Svc       │
│ (Go)  │  │ (Go)    │  │ (Python)  │
└───┬───┘  └────┬────┘  └──────┬────┘
    │           │              │
    └───────────┼──────────────┘
                │
        ┌───────▼───────┐
        │   Kafka Bus    │
        │(GPS events,    │
        │ trip updates,  │
        │ zone analytics)│
        └───────┬───────┘
                │
    ┌───────────┼───────────────┐
    │           │               │
┌───▼───┐  ┌────▼────┐  ┌──────▼────┐
│ Redis │  │ Post-   │  │ Cassandra │
│ Geo   │  │ greSQL  │  │ (Location │
│       │  │ + PostGIS│  │  history) │
└───────┘  └─────────┘  └───────────┘
```

### Data Flow for a Ride Request

```
1. Rider opens app → sends pickup location
2. API Gateway routes to Rider Service
3. Rider Service calls Driver Service with pickup coords
4. Driver Service queries Redis GEO: GEORADIUS pickup 3km
5. Redis returns nearest available drivers (sorted by distance)
6. Driver Service selects closest driver, sends dispatch notification
7. Driver accepts → Trip Service creates trip record
8. Trip event published to Kafka topic 'trip.events'
9. Payment service (async consumer) processes pre-authorization
```

---

## 3. KAFKA EVENT-DRIVEN ARCHITECTURE

### Kafka Topics

| Topic | Partitions | Retention | Producers | Consumers | Message Schema |
|-------|-----------|-----------|-----------|-----------|----------------|
| `gps.raw.updates` | 5 per city | 7 days | Driver WS Gateway | GPS Stream Processor | `{driver_id, lat, lng, speed, heading, timestamp}` |
| `gps.enriched.locations` | 5 per city | 3 days | GPS Stream Processor | Zone Analytics, ETL | `{driver_id, location, zone_id, speed, heading, timestamp}` |
| `gps.zone.driver_counts` | 3 per city | 1 day | Zone Analytics | Surge Engine, Dashboard | `{zone_id, driver_count, surge_multiplier, timestamp}` |
| `trip.events` | 5 | 14 days | Trip Service | Payment, Notification, Analytics | `{trip_id, status, rider_id, driver_id, fare, ...}` |
| `gps.dlq` | 1 | 30 days | Failed messages | Dead-letter handler | `{error, original_message}` |

### GPS Location Update Pipeline

```ascii
┌─────────────┐     ┌────────────┐     ┌─────────────┐     ┌──────────────┐
│ Driver App  │────▶│ WebSocket  │────▶│  Kafka      │────▶│ GPS Stream   │
│ (GPS 3s)    │     │ Gateway    │     │ Raw Updates │     │ Processor     │
└─────────────┘     └────────────┘     └──────┬──────┘     └──────┬───────┘
                                              │                   │
                                              │         ┌─────────▼────────┐
                                              │         │  GeoIndex Update  │
                                              │         │  (Redis GEOADD)   │
                                              │         └─────────┬────────┘
                                              │                   │
                                              │         ┌─────────▼────────┐
                                              │         │  Zone Lookup     │
                                              │         │  (PostGIS query) │
                                              │         └─────────┬────────┘
                                              │                   │
                                              │         ┌─────────▼────────┐
                                              │         │  Kafka: Enriched │
                                              └─────────│  Locations Topic │
                                                        └─────────────────┘
```

**Staff-level considerations:**
- **Partition key:** `driver_id` → ensures same driver's events go to same partition for ordered processing
- **Idempotent producer:** Exactly-once semantics to avoid duplicate GPS updates
- **Dead letter queue:** Messages that fail enrichment (e.g., malformed GPS) go to `gps.dlq`
- **Backpressure:** If Redis Geo write fails, buffer in Kafka and replay; never drop location updates
- **Scaling:** Each city gets its own Kafka cluster to isolate blast radius

---

## 4. GEORADIUS DRIVER MATCHING

### Redis GEO Implementation

```python
# Production: Redis GEO with sorted sets
def find_nearest_drivers(pickup_lat, pickup_lng, radius_km=3, limit=5):
    drivers = redis.georadius(
        "drivers:available",
        pickup_lng, pickup_lat,      # Note: Redis uses (lng, lat) order
        radius_km, unit="km",
        withcoord=True, withdist=True,
        sort="ASC", count=limit
    )
    return drivers
```

### Progressive Radius Expansion

```
Pickup Location
    │
    ├── Query: GEORADIUS pickup 2km
    │   └── Found 3 drivers → pick closest
    │
    ├── Query: GEORADIUS pickup 2km → No results
    │   └── Query: GEORADIUS pickup 5km
    │       └── Found 1 driver → dispatch
    │
    ├── Query: GEORADIUS pickup 2km → No results
    │   └── Query: GEORADIUS pickup 5km → No results
    │       └── Query: GEORADIUS pickup 10km
    │           └── No results → "No cabs available"
```

**Staff-level considerations:**
- **Geohash precision trade-off:** Shorter geohash prefix = broader search = more O(log N) nodes to scan
- **Cache warming:** Pre-compute geohash prefixes for high-demand areas (airports, train stations)
- **Read-replicas:** Route GEORADIUS queries to Redis read-replicas to reduce primary write load
- **Race condition:** Driver status changes between GEORADIUS and dispatch → use optimistic locking with trip version
- **Grid partitioning:** Over-engineer by pre-sharding `drivers:available` by cab_type → `drivers:available:mini`, `drivers:available:suv`

---

## 5. ZONE MANAGEMENT & SURGE PRICING

### Hexagonal Grid Partitioning

```
City partitioned into ~500m hexagonal zones:
         ___
     ___/ Z \___
    / Z \___/ Z \
    \___/ Z \___/
    / Z \___/ Z \
    \___/   \___/

Benefits over square grids:
- All neighbors are equidistant
- Better circular radius approximation
- Minimizes zone-transition edge effects
```

### Zone Analytics Pipeline

```
Every 30 seconds (tumbling window):
┌─────────────────┐
│ Zone Analytics  │
│ Aggregator      │
│                 │
│ For each zone:  │
│   drivers =     │
│     COUNT(DISTINCT driver_id)  │
│     WHERE zone_id = Z AND      │
│     status = AVAILABLE         │
│                 │
│   requests =    │
│     COUNT(ride_requests)       │
│     WHERE zone_id = Z          │
│     IN LAST 5 MINUTES          │
│                 │
│   surge = f(drivers, requests) │
│                 │
│   Publish to    │
│   Kafka topic   │
└─────────────────┘
```

### Surge Multiplier Calculation

```python
def calculate_surge(driver_count: int, demand_count: int) -> float:
    if driver_count == 0:
        return 2.5  # Max surge
    
    ratio = demand_count / driver_count
    
    if ratio > 3.0:      return 2.0
    elif ratio > 2.0:    return 1.5
    elif ratio > 1.5:    return 1.25
    else:                return 1.0
    # Note: Surge decays with 5-minute half-life to prevent driver gaming
```

---

## 6. DATA MODEL

### PostgreSQL + PostGIS Tables

See [CODE.md](CODE.md) for the complete 9-table DDL schema.

**Key tables:**
- `riders` — user accounts, ratings, payment methods (JSONB)
- `drivers` — license, cab type, availability status, **GEOGRAPHY(Point)** for geo-radius queries
- `trips` — full trip state machine, fare breakdown, **GEOGRAPHY** pickup/dropoff
- `zones` — hexagonal zone definitions with **GIST spatial index**
- `driver_location_history` — **partitioned by month** for query performance
- `payments` — with idempotency key for exactly-once processing
- `surge_pricing_log` — time-series of zone supply/demand

### Redis Keys

```ascii
drivers:available              → GEO (sorted set of available drivers)
driver:{id}:status             → STRING (AVAILABLE/ON_TRIP/OFFLINE)
trip:{id}:state                → HASH (current trip state machine)
zone:{id}:surge                → STRING (current surge multiplier)
zone:{id}:driver_count         → STRING (number of available drivers)
```

---

## 7. STAFF-LEVEL INTERVIEW QUESTIONS & ANSWERS

### Q1: "How would you design the GPS location ingestion pipeline to handle 100K drivers updating every 3 seconds?"

**Expected Answer:**

**Scale calculation:** 100K drivers × 1 update/3s = ~33K writes/second. This is significant but manageable with proper partitioning.

**Architecture:**

```
Driver App ──(WebSocket, binary protobuf)──▶ WS Gateway (Nginx/HAProxy)
                                                     │
                                                     ├── Kafka producer (async, batching)
                                                     │    └── Topic: gps.raw.updates (5 partitions per city)
                                                     │
                                                     ├── Redis Geo write (synchronous, every 3rd update)
                                                     │    └── GEOADD drivers:available <lng> <lat> <driver_id>
                                                     │
                                                     └── Batch write to Cassandra (30s cadence)
                                                          └── driver_location_history (TTL: 90 days)
```

**Key decisions:**
1. **WebSocket with binary protocol (protobuf)** — 60% less bandwidth than JSON
2. **Adaptive polling** — 3s when moving, 30s when stationary (detect via accelerometer)
3. **Dead reckoning** — if GPS drops, estimate position from last known speed/direction
4. **Kalman filter** — smooth GPS noise at the app level before sending
5. **Write-behind cache** — Redis Geo is source of truth for real-time; Cassandra for history
6. **Kafka partitioning** — `driver_id` as partition key ensures ordered processing per driver

**Failure modes:**
- **Redis Geo cluster down:** Fall back to PostGIS `ST_DWithin` query with degraded SLA (200ms vs 5ms)
- **Kafka broker failure:** Rebalance partitions across remaining brokers; drivers re-publish on reconnect
- **GPS data corruption:** Schema validation at Kafka producer; DLQ for bad messages

---

### Q2: "How would you implement zone-based surge pricing at city scale?"

**Expected Answer:**

**Geo-fencing architecture:**

```
1. Partition city into ~500m hexagonal zones (~500 zones for a 10km² city)
2. Maintain zone state in Redis Hashes:
     HINCRBY zone:{id}:stats drivers 1    (when driver enters zone)
     HINCRBY zone:{id}:stats requests 1   (when ride requested in zone)
3. Run aggregation worker every 30 seconds:
     For each zone:
       supply = HGET zone:{id}:stats drivers
       demand = HGET zone:{id}:stats requests
       surge = f(supply, demand)
       HSET zone:{id}:stats surge {surge}
       EXPIRE zone:{id}:stats 60  (auto-reset supply/demand)
4. Publish zone stats to Kafka topic 'gps.zone.driver_counts'
5. Rider app reads surge via GET /api/zones/{zone_id}/surge
   (cached for 5 seconds at API Gateway)
```

**Sticky surge decay:** Surge doesn't drop instantly. If ratio drops below threshold, surge decays linearly over 5 minutes. This prevents drivers from gaming the system by waiting for surge to hit then immediately leaving.

**Leading indicators:**
- Airport flight arrivals → pre-load surge prediction
- Concert/sports event schedules → pre-load surge zones
- Weather data (rain = higher demand) → adjust base multiplier

---

### Q3: "Design a system to handle driver location updates during GPS signal loss in tunnels."

**Expected Answer:**

**Dead Reckoning System:**

```
┌─────────────────────────────────────────────┐
│ Mobile SDK (on-device)                      │
│                                              │
│  GPS available:                              │
│    → Send precise location every 3s          │
│    → Record: speed, heading, timestamp       │
│                                              │
│  GPS lost (tunnel, parking garage):          │
│    → Use last known speed + heading          │
│    → Estimate position:                      │
│         new_lat = last_lat + (speed * time * cos(heading)) / earth_radius
│         new_lng = last_lng + (speed * time * sin(heading)) / earth_radius
│    → Tag message: {dead_reckoning: true}     │
│    → Update every 1s (more frequent since    │
│       error accumulates faster)              │
│                                              │
│  GPS restored:                               │
│    → Send actual location with tag            │
│    → {corrected: true, drift_meters: X}      │
│    → Server applies correction to estimate    │
└─────────────────────────────────────────────┘
```

**Server-side handling:**
- Mark dead-reckoned locations with lower confidence score
- Don't use dead-reckoned locations for surge/gamification calculations
- Widen geo-radius search radius for dead-reckoned drivers
- On GPS re-acquisition, calculate drift and update ML models

---

### Q4: "How would you prevent driver fraud in a geo-spatial cab booking system?"

**Expected Answer:**

**Fraud vectors and mitigations:**

| Fraud Type | Detection | Mitigation |
|-----------|-----------|------------|
| **GPS spoofing** (fake location) | Compare GPS with cell tower triangulation + WiFi BSSID fingerprint | Two-factor location verification; flag discrepancies > 100m |
| **Route manipulation** (taking longer route) | ML model predicts expected route/duration per segment | Auto-adjust fare; flag outliers > 2σ from expected |
| **Fake ride requests** (driver self-booking) | Device fingerprinting; payment auth before dispatch | Require payment method for all rides; rate-limit per device |
| **Collusion** (rider and driver gaming surge) | Check if rider and driver share IP, device, or payment method | Ban both accounts on detection |
| **Bait-and-switch** (different car than registered) | Photo verification on trip start; AI model compares car photos | Penalize driver rating; suspend after N violations |

**GPS spoofing detection algorithm:**
```python
def detect_gps_spoofing(gps_location, cell_towers, wifi_bssids):
    # Cell tower triangulation
    cell_location = trilaterate(cell_towers)
    cell_distance = haversine(gps_location, cell_location)
    
    # WiFi fingerprint lookup (pre-mapped)
    wifi_location = lookup_wifi_bssid_db(wifi_bssids)
    wifi_distance = haversine(gps_location, wifi_location)
    
    # Combined score
    if cell_distance > 200 or wifi_distance > 100:
        return FRAUD_FLAG  # Likely spoofed
    
    # Speed check: impossible speeds = spoofing
    speed = calculate_speed(consecutive_updates)
    if speed > 250:  # km/h
        return SPOOF_FLAG
        
    return LEGITIMATE
```

---

### Q5: "Design an RTA (Real-Time Agreement) system for Uber pool / shared rides."

**Expected Answer:**

Core challenge: Match multiple riders going in the same direction, splitting fare, with minimum time penalty.

**Key components:**
- **Route similarity index:** Compare pickup/dropoff pairs using road network (not straight-line) distance
- **Time penalty budget:** Max 5 minutes extra per rider per shared trip
- **Dynamic pricing:** Pool rides are 30-50% cheaper than individual
- **Matching window:** 15-30 second batch window for pool requests in same zone

**Algorithm:**
```python
def match_pool_riders(pending_pool_requests, available_drivers):
    # 1. Cluster pending requests by pickup proximity
    clusters = dbscan_cluster(
        [r.pickup for r in pending_pool_requests],
        eps=500,  # 500m cluster radius
        min_samples=2
    )
    
    # 2. For each cluster, compute optimal sequence
    matched_pairs = []
    for cluster in clusters:
        # Compute pairwise route efficiency
        for r1, r2 in combinations(cluster, 2):
            # Optimized route: pickup1 → pickup2 → dropoff1 → dropoff2
            efficiency = compute_route_efficiency(r1, r2)
            
            if efficiency.detour_minutes <= 5:  # Within budget
                matched_pairs.append((r1, r2, efficiency))
    
    # 3. Assign to nearest driver with seat capacity
    return assign_to_drivers(matched_pairs, available_drivers)
```

---

### Q6: "How would you handle cross-city (inter-city) trips?"

For long trips spanning cities, the system needs:
- **Cross-cluster trip coordinator** — manages the trip state across city boundaries
- **ETA calculation** using inter-city driving time (not city-level model)
- **Pricing** that accounts for return trip deadhead (driver won't get a return fare)
- **Driver incentive** — premium payout for inter-city trips to compensate for return deadhead

**Architecture:**
```
Rider requests Mumbai → Pune (150km)
    │
    ├── Mumbai cluster evaluates: available drivers
    ├── Inter-city trip coordinator created
    ├── Fare: normal rate × 1.5 (deadhead adjustment)
    ├── Driver notified with deadhead compensation
    │
    ├── Trip starts in Mumbai cluster
    ├── On city boundary → trip state transfers to Pune cluster
    └── Trip completes in Pune cluster → deadhead payout processed
```

---

## 8. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale | Alternative |
|----------|--------|-----------|-------------|
| **Geo-index** | Redis GEO | 5ms query, O(log N), built-in geo commands | PostGIS (more features, 50ms) |
| **Event bus** | Kafka | Durable, replayable, ordered per partition | RabbitMQ (simpler, lower throughput) |
| **Zone shape** | Hexagonal | All neighbors equidistant, better than squares | H3 Uber library (production proven) |
| **Driver matching** | Progressive radius | Simple, predictable, easy to debug | ML-based (optimal but opaque) |
| **Surge calculation** | Fixed thresholds | Transparent, easier to tune | ML pricing (optimal but hard to explain) |
| **Location DB** | Cassandra | Writes optimized, TTL support, horizontal scaling | TimescaleDB (SQL interface, but more overhead) |

---

## 9. COST (Monthly)

| Component | Configuration | Cost |
|-----------|--------------|------|
| Compute (Go services) | ECS Fargate, 10 tasks × 2 vCPU | $5,000 |
| Redis Geo cluster | ElastiCache, r6g.xlarge, cluster mode (3 shards) | $1,500 |
| Kafka + Stream processing | MSK, 5 brokers, m5.large | $3,500 |
| PostgreSQL + PostGIS | RDS, db.r6g.large, Multi-AZ, 500GB | $3,000 |
| Cassandra (location history) | 5 nodes, i3.large | $2,000 |
| WebSocket Gateway | ALB + Nginx, auto-scaling | $1,500 |
| Maps API (Google) | Pay-per-use | $2,000 |
| Monitoring (CloudWatch, Datadog) | Metrics + traces | $1,500 |
| **Total** | | **$20,000** |
