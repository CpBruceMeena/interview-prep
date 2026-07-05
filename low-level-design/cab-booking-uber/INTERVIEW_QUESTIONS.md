# Cab Booking Service (Uber) - Interview Questions & Answers

> **Target Level:** Staff/Principal Engineer (10+ years)  
> **Evaluation Focus:** Real-time systems, geo-spatial indexing, event-driven architecture, distributed systems, fraud detection, system design at scale

---

## Question 1: Core Design
**Interviewer:** *"Design a cab booking system like Uber — rider requests, driver matching, trip management, fare calculation."*

### 🎯 Expected Answer (Staff Level)

**Domain Model:**
```
Rider ──→ Trip ──→ Driver
  │                │
  └── Location     ├── CabType (Mini, Sedan, SUV)
                   ├── Status (Available, Booked, OnTrip, Offline)
                   └── CurrentLocation (GEOGRAPHY Point)
```

**Trip State Machine:**
```
REQUESTED → ACCEPTED → DRIVER_ARRIVED → STARTED → COMPLETED
    │          │                              │
    └── CANCELLED                            └── (payment captured)
```

**Key Architectural Decisions:**
1. **Separate Pricing from Matching** (Strategy Pattern) — OCP compliance
2. **Geo-spatial indexing** (Redis GEO or PostGIS) — O(log N) lookup vs O(N) scan
3. **Event-driven via Kafka** — decouple services, enable replay, async processing
4. **Zone-based surge** — hexagonal grid for supply/demand tracking

---

## Question 2: GeoRadius Driver Matching (Deep Dive)
**Interviewer:** *"Compare different geospatial indexing approaches for driver matching. Walk through trade-offs."*

### 🎯 Staff-Level Answer

**Option 1: Redis GEO (Sorted Sets)**
```python
# Redis GEO
GEOADD drivers:available <lng> <lat> <driver_id>      # O(log N)
GEORADIUS drivers:available <lng> <lat> 3 km ASC COUNT 5  # O(log N + M)
```
- **Pros:** 5ms query, built-in geo commands, cluster mode for HA
- **Cons:** No polygon queries, limited to radius search, memory bound

**Option 2: PostGIS (Spatial Extension)**
```sql
-- PostGIS query
SELECT id, name, cab_type,
       ST_Distance(current_location, ST_MakePoint(-73.9857, 40.7484)::geography) / 1000 AS dist_km
FROM drivers
WHERE status = 'AVAILABLE'
  AND ST_DWithin(current_location, ST_MakePoint(-73.9857, 40.7484)::geography, 3000)
ORDER BY dist_km ASC LIMIT 5;
```
- **Pros:** Full spatial queries (polygons, intersections), ACID, joins with other tables
- **Cons:** 50ms query, heavier, more complex to scale

**Option 3: S2 / H3 (Google/Uber Grid)**
- **Pros:** Hierarchical, arbitrary precision, great for zone analytics
- **Cons:** Requires application-level library, not a database

**Decision Matrix for Staff Engineers:**
| Criterion | Redis GEO | PostGIS | H3 |
|-----------|-----------|---------|-----|
| Query latency | **5ms** | 50ms | 10ms |
| Polygon support | No | **Yes** | Cell-based |
| Persistence | In-memory | **Disk + WAL** | App-layer |
| Scaling | Cluster mode | Read replicas | Stateless |
| Geo-radius JOINs | App-layer | **SQL JOIN** | App-layer |
| **Best for** | Real-time matching | Zone analytics, history | Grid partitioning |

**Recommendation:** Redis GEO for real-time matching (p99 < 10ms), PostGIS for analytics/history, H3 for zone grid creation.

---

## Question 3: Kafka Event Pipeline for GPS Locations
**Interviewer:** *"Design a reliable Kafka pipeline for ingesting 33K GPS location updates per second from 100K drivers."*

### 🎯 Staff-Level Answer

**Pipeline Architecture:**
```
Driver GPS (3s) → WebSocket Gateway (protobuf binary)
                       │
                       ├── Kafka Producer (async, batch: 100ms/1000msgs)
                       │    └── Topic: gps.raw.updates (5 partitions, RF=3)
                       │
                       ├── Stream Processor (Kafka Streams / Flink)
                       │    ├── Deserialize protobuf
                       │    ├── Validate schema & geo-coordinates
                       │    ├── GEOADD driver location in Redis Geo
                       │    ├── Determine zone (H3 cell lookup)
                       │    ├── Enrich with speed, heading, accuracy
                       │    └── Publish to gps.enriched.locations
                       │
                       ├── Zone Analytics (30s tumbling window)
                       │    ├── Count distinct drivers per zone
                       │    ├── Calculate surge multiplier
                       │    └── Publish to gps.zone.driver_counts
                       │
                       └── Long-term Storage (Cassandra)
                            └── driver_location_history (TTL: 90 days)
```

**Key design decisions for Staff-level:**
1. **Partition count:** 5 partitions per city. Partition key = `driver_id` for ordered processing per driver.
2. **Rebalance strategy:** Cooperative rebalancing (Kafka 3.0+) to minimize stop-the-world during scale-up.
3. **Idempotent producer:** `enable.idempotence=true` for exactly-once semantics to Redis Geo.
4. **DLQ handling:** Malformed GPS messages → `gps.dlq` topic with 30-day retention for forensic analysis.
5. **Backpressure:** If Redis Geo write fails → buffer in Kafka consumer (pause partition, resume on recovery).
6. **Compaction:** `gps.raw.updates` uses log compaction to keep only latest per driver (for consumer replay).

**Failure modes:**
- **Kafka broker failure:** In-sync replicas (ISR) = 2; min.insync.replicas = 2 for producer `acks=all`
- **Stream processor crash:** Consumer group rebalances; offset committed after Redis Geo write (at-least-once)
- **Redis Geo cluster full:** Eviction policy = `allkeys-lru`; Redis is cache, not source of truth

---

## Question 4: Zone-Based Surge Pricing
**Interviewer:** *"How would you create zones and calculate the number of drivers in each zone in real-time?"*

### 🎯 Staff-Level Answer

**Zone Creation Strategy:**

1. **Use H3 hexagonal grid** (Uber's production library):
   - Resolution 10 (~500m hexagons) for city zones
   - Resolution 12 (~100m) for high-density areas (downtown)
   - Resolution 8 (~4km) for suburban coverage

```python
import h3

def create_city_zones(city_center_lat, city_center_lng, radius_km=10):
    """Create zones at multiple H3 resolutions."""
    # Center hex at resolution 10 (~500m)
    center_hex = h3.geo_to_h3(city_center_lat, city_center_lng, 10)
    
    # Get all hexes within radius
    hexes = h3.k_ring(center_hex, k=int(radius_km / 0.5))
    
    zones = []
    for hex_id in hexes:
        center = h3.h3_to_geo(hex_id)
        zones.append({
            "zone_id": hex_id,
            "center_lat": center[0],
            "center_lng": center[1],
            "area_km2": h3.hex_area(10),
            "resolution": 10
        })
    return zones
```

2. **Store in PostgreSQL:**
```sql
CREATE TABLE zones (
    zone_id VARCHAR(20) PRIMARY KEY,  -- H3 hex ID
    city_id UUID NOT NULL,
    center GEOGRAPHY(Point, 4326) NOT NULL,
    resolution INT NOT NULL,
    surge_multiplier DECIMAL(3,2) DEFAULT 1.0,
    last_updated TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_zones_city_res ON zones(city_id, resolution);
```

**Driver Counting per Zone (real-time):**

**Option A — Redis-based (real-time, ~5ms):**
```python
# When driver location updates:
HINCRBY zone:{zone_id}:drivers {driver_id} 1
EXPIRE zone:{zone_id}:drivers 30  # 30s TTL

# When checking drivers in zone:
driver_count = HLEN zone:{zone_id}:drivers
```

**Option B — Kafka Streams (windowed, ~30s):**
```sql
CREATE TABLE zone_driver_counts AS
SELECT zone_id, COUNT(DISTINCT driver_id) AS driver_count
FROM gps_enriched_locations_stream
WINDOW TUMBLING (SIZE 30 SECONDS)
GROUP BY zone_id;
```

**Option C — PostGIS (on-demand, ~200ms):**
```sql
SELECT z.zone_id, COUNT(d.id) AS driver_count
FROM zones z
LEFT JOIN drivers d ON ST_DWithin(d.current_location, z.center, z.radius_meters)
WHERE d.status = 'AVAILABLE'
  AND z.resolution = 10
GROUP BY z.zone_id;
```

---

## Question 5: Staff-Level — Driver Fraud Detection
**Interviewer:** *"How would you detect and prevent GPS spoofing fraud in a cab booking system?"*

### 🎯 Staff-Level Answer

**Multi-layered fraud detection:**

| Layer | Technique | Latency | Effectiveness |
|-------|-----------|---------|--------------|
| 1. Device-level | GPS + WiFi BSSID + Cell tower triangulation | Real-time (on-device) | Blocks 90% spoofing |
| 2. Server-level | Speed check (impossible speed = spoof) | Real-time | Blocks 95% |
| 3. ML-level | Behavioral patterns (gaming surge zones) | 5-min batch | Catches sophisticated fraud |
| 4. Manual review | Flagged driver review by ops team | 24h | Final escalation |

**Implementation (Layer 1 + 2):**
```python
def verify_location(driver_id, gps_lat, gps_lng, cell_towers, wifi_bssids):
    # 1. Cell tower triangulation
    cell_lat, cell_lng = triangulate(cell_towers)
    cell_dist = haversine(gps_lat, gps_lng, cell_lat, cell_lng)
    
    if cell_dist > 500:  # 500m discrepancy
        return FRAUD_FLAG
    
    # 2. Speed check
    prev_loc = get_previous_location(driver_id)
    if prev_loc:
        speed = calculate_speed(prev_loc, (gps_lat, gps_lng), time_elapsed)
        if speed > 250:  # Impossible speed
            return SPOOF_FLAG
    
    # 3. WiFi fingerprint matching
    wifis = lookup_known_wifis(wifi_bssids)
    if wifis and haversine(gps_lat, gps_lng, wifis.lat, wifis.lng) > 100:
        return FRAUD_FLAG
    
    return LEGITIMATE
```

---

## Question 6: Staff-Level — Dead Reckoning (GPS Loss)
**Interviewer:** *"How do you handle driver location tracking when GPS signal is lost (tunnels, garages)?"*

### 🎯 Staff-Level Answer

**Dead Reckoning System:**

```python
class DeadReckoningEngine:
    def estimate_position(self, driver_id, last_known_location, 
                          last_speed, last_heading, elapsed_seconds):
        """Estimate position using last known state."""
        if elapsed_seconds > 30:
            return None  # Too stale, mark driver as location-unknown
        
        # Convert speed from km/h to degrees per second
        speed_dps = (last_speed / 3600) / 111000  # degrees per second
        
        estimated_lat = last_known_location.lat + (
            speed_dps * elapsed_seconds * math.cos(math.radians(last_heading))
        )
        estimated_lng = last_known_location.lng + (
            speed_dps * elapsed_seconds * math.sin(math.radians(last_heading))
        )
        
        return Location(
            lat=estimated_lat,
            lng=estimated_lng,
            confidence=max(0, 1 - (elapsed_seconds / 30)),
            is_dead_reckoned=True
        )
```

**Staff-level considerations:**
- **Confidence scoring:** Tag dead-reckoned positions with confidence level; don't use low-confidence positions for surge/gamification
- **Radius widening:** When dead-reckoned, widen geo-radius search radius (3km → 5km) to account for error
- **On-recovery correction:** When GPS re-acquires, calculate drift vector and apply to subsequent estimates
- **Battery optimization:** Reduce GPS polling in known dead zones (pre-mapped tunnels) to save battery

---

## Question 7: Staff-Level — Pool/Scheduled Rides
**Interviewer:** *"Design a real-time ride pooling system (Uber Pool / Share) that matches riders going in similar directions."*

### 🎯 Staff-Level Answer

**Core algorithm:**
1. **Batching window:** Collect pool requests for 15-30 seconds per zone
2. **Clustering:** DBSCAN on pickup locations (500m epsilon, min 2 samples)
3. **Route optimization:** For each cluster, compute optimal sequence minimizing total detour
4. **Driver assignment:** Assign pooled trip to nearest driver with sufficient capacity

**Key metrics:**
```python
class PoolMatchQuality:
    def compute(self, rider1, rider2):
        # Route: pickup1 → pickup2 → dropoff1 → dropoff2
        total_original = rider1.distance + rider2.distance
        total_pooled = self.compute_route_distance(rider1, rider2)
        
        detour_pct = (total_pooled - total_original) / total_original
        time_penalty = detour_pct * 100  # minutes
        
        return {
            "matching_score": 1 - detour_pct,
            "time_penalty_min": time_penalty,
            "is_acceptable": time_penalty <= 5,  # Max 5 min extra
            "rider1_discount": 0.4,  # 40% off
            "rider2_discount": 0.3   # 30% off
        }
```

---

## Question 8: Staff-Level — System Reliability
**Interviewer:** *"How do you achieve 99.99% uptime for a real-time cab booking system?"*

### 🎯 Staff-Level Answer

**Four 9's strategy:**

| Component | Strategy | RTO | RPO |
|-----------|----------|-----|-----|
| API Gateway | Multi-AZ ALB + CloudFront | < 60s | 0 |
| Redis Geo | Cluster mode (3 shards + replicas) | < 10s | 0 |
| Kafka | 3 brokers, min.insync.replicas=2 | < 30s | < 1s |
| PostgreSQL | Multi-AZ RDS with standby | < 60s | < 1min |
| Cassandra | 5 nodes, RF=3, rack awareness | < 5s | 0 |

**Graceful degradation:**
- **Redis Geo down** → Fall back to PostGIS `ST_DWithin` (200ms vs 5ms)
- **PostgreSQL primary down** → Read from replica, writes queued to Kafka
- **Kafka broker down** → Rebalance, producers buffer in-memory (max 10s)
- **Driver app offline** → Dead reckoning on client, sync on reconnect

**Chaos engineering:**
- Weekly GameDay: kill Redis primary, measure impact
- Monthly: rebalance Kafka without partition loss
- Quarterly: full region failover test

---

## Question 9: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | Pricing, Matching, Surge calculation | Interchangeable algorithms at runtime |
| **Observer/Pub-Sub** | Kafka event bus, WebSocket updates | Decoupled event-driven communication |
| **State** | Trip lifecycle | Clean status transitions with guards |
| **Facade** | CabBookingService | Unified API surface over subsystems |
| **Factory** | Driver/Rider creation | Config-driven setup |
| **Decorator** | Pricing (base → surge → tolls → tip) | Composable fare calculation |
| **Chain of Responsibility** | Fraud detection pipeline | Each check can pass or escalate |

---

## Question 10: Evaluation Rubric (Staff Level)

| Score | What It Looks Like |
|-------|-------------------|
| **5 — Exceptional** | Questions requirements deeply. References real production experience (Uber/Lyft). Discusses trade-offs proactively. Brings up fraud, dead reckoning, and failure modes without prompting. |
| **4 — Strong** | Solid understanding of geo-spatial indexing, Kafka, and distributed systems. Can discuss trade-offs. Good production experience. |
| **3 — Competent** | Good OOD and basic system design. Knows Redis GEO exists. Can handle matching but misses edge cases. |
| **2 — Developing** | Basic classes work but no geo-spatial awareness. Linear scan O(N) matching. No failure handling. |
| **1 — Needs Growth** | No understanding of distributed systems. Single-server mental model. Can't discuss scale. |
