# 🏗️ Cab Booking Service (Uber) — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Real-time matching, geo-spatial indexing, surge pricing, event-driven architecture

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
        │  Kafka / Redis │
        │ PubSub         │
        │(GPS events,    │
        │ trip updates)  │
        └───────┬───────┘
                │
    ┌───────────┼───────────────┐
    │           │               │
┌───▼───┐  ┌────▼────┐  ┌──────▼────┐
│ Redis │  │ Post-   │  │ S3/Blob   │
│ Geo   │  │ greSQL  │  │ (Trip     │
│       │  │         │  │  history) │
└───────┘  └─────────┘  └───────────┘
```

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Driver Service (Go)
- Maintains driver location in Redis Geo (updated every 3 seconds)
- Handles driver status (Available/Offline/OnTrip)
- Sends real-time location to nearby riders via WebSocket

**🔴 Interview Question:** *"How do you find the nearest available driver efficiently for millions of drivers?"*

**✅ Answer:** Use **Redis GEO** — geospatial indexing with sorted sets:
```python
def find_nearest_drivers(pickup_lat, pickup_lng, radius_km=3, limit=5):
    drivers = redis.georadius(
        "drivers:available",
        pickup_lng, pickup_lat,
        radius_km, unit="km",
        withcoord=True, withdist=True,
        sort="ASC", count=limit
    )
    return drivers
```
Redis GEO uses geohash encoding internally — queries are O(log N) for up to millions of points. Results cached for 1 second (driver position is stale by then anyway).

---

### Rider Service (Go)
- Matchmaking logic
- Fare estimate calculation
- Ride history

### Trip Service (Python)
- Trip state machine: REQUESTED → ACCEPTED → STARTED → COMPLETED → CANCELLED
- Fare calculation (base + distance + time + surge)
- Driver-rider matching via Kafka event

**🔴 Interview Question:** *"How does surge pricing work in real-time?"*

**✅ Answer:** Zone-based dynamic pricing:
1. **Partition city** into hexagonal zones (~500m each)
2. **Calculate supply/demand** per zone every 30 seconds:
   - Supply = drivers in zone with status AVAILABLE
   - Demand = ride requests in zone in last 5 minutes
3. **Surge multiplier**: `f(demand / supply)`:
   - ratio < 1.5: 1.0x (no surge)
   - ratio 1.5-2.0: 1.25x
   - ratio 2.0-3.0: 1.5x
   - ratio 3.0+: 2.0x+
4. **Sticky decay**: Surge decays over 5 minutes to prevent sudden drops (driver gaming)
5. **Notifications**: Inform rider of surge multiplier before confirming

---

### Real-time Location Tracking
- **Driver app:** GPS every 3 seconds (moving) / 30 seconds (stationary) via WebSocket
- **Reduction:** Kalman filter to smooth GPS noise
- **Dead reckoning:** If GPS drops, estimate position from last speed + heading

**🔴 Interview Question:** *"How do you handle the high volume of GPS data?"*

**✅ Answer:** Each city cluster handles its own GPS stream. ~100K drivers × 1 update/3 seconds = 33K writes/second. Pipeline:
1. Driver sends GPS → WebSocket Gateway
2. Gateway publishes to Kafka topic `gps.updates.{city}`
3. Stream processor (Flink) enriches and writes to Redis Geo
4. Redis Geo query for nearby driver search
5. Aggregated GPS stored in Cassandra for analytics (downsampled to 30s)

---

## 4. DATA MODEL

```sql
CREATE TABLE riders (
    id UUID, name TEXT, phone TEXT UNIQUE, rating DECIMAL(2,1)
);
CREATE TABLE drivers (
    id UUID, name TEXT, phone TEXT UNIQUE, license TEXT,
    cab_type TEXT, rating DECIMAL(2,1), status TEXT
);
CREATE TABLE trips (
    id UUID, rider_id UUID, driver_id UUID,
    pickup_lat DECIMAL(10,7), pickup_lng DECIMAL(10,7),
    dropoff_lat DECIMAL(10,7), dropoff_lng DECIMAL(10,7),
    fare DECIMAL(10,2), status TEXT,
    requested_at TIMESTAMP, completed_at TIMESTAMP
);
```

**Redis keys:**
```
drivers:available → GEO (all available drivers with location)
driver:{id}:status → STRING (AVAILABLE/ON_TRIP)
trip:{id}:state → HASH (full trip state)
```

---

## 5. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Matching | Nearest driver first | 70% of riders prioritize speed over rating |
| Pricing base | Distance + time + surge | Fair: captures both distance cost and demand |
| Route calc | Google Maps API | Don't reinvent — use best-in-class |
| Driver ETA | Current speed × distance | Adjusted for traffic via historical patterns |

---

## 6. COST (Monthly)

| Component | Cost |
|-----------|------|
| Compute (Go services) | $5,000 |
| Redis Geo cluster | $1,500 |
| PostgreSQL (per city) | $3,000 |
| Kafka + Stream processing | $2,500 |
| Maps API (Google) | $2,000 |
| **Total** | **$14,000** |
