# Cab Booking Service (Uber) - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Real-time systems, matching algorithms, dynamic pricing, geo-spatial indexing

---

## Question 1: Core Design
**Interviewer:** *"Design a cab booking system like Uber — rider requests, driver matching, trip management, fare calculation."*

### 🎯 Expected Answer

**Domain Model:**
```
Rider ──→ Trip ──→ Driver
  │                │
  └── Location     ├── CabType (Mini, Sedan, SUV)
                   ├── Status (Available, Booked, OnTrip, Offline)
                   └── CurrentLocation
```

**Trip State Machine:**
```
REQUESTED → ACCEPTED → STARTED → COMPLETED
    │          │                    │
    └── CANCELLED                  └── (payment processed)
```

**Key Architectural Decision: Separate Pricing from Matching**
```python
class PricingStrategy(ABC):
    @abstractmethod
    def calculate_fare(self, distance_km, duration_min): pass

class DriverMatchingStrategy(ABC):
    @abstractmethod
    def find_driver(self, pickup, cab_type, drivers): pass
```

Both use Strategy pattern. You can swap in surge pricing without touching matching, or change from nearest-driver to highest-rated without touching pricing. **SRP + OCP in one pattern.**

---

## Question 2: Driver Matching Algorithms
**Interviewer:** *"Compare different driver matching strategies."*

### 🎯 Deep Dive

| Strategy | Pros | Cons | Best For |
|----------|------|------|----------|
| **Nearest Driver** | Min wait time | May cluster drivers | Default |
| **Highest Rated** | Better ride quality | Longer waits | Premium tier |
| **Batched Matching** | Global optimum | Latency (batch window) | High density |
| **Opportunistic** | Driver next-dropoff | Complexity | Low density |

**Nearest Driver with Geo-Spatial Indexing:**
```python
# Use a spatial index (QuadTree, R-Tree, or Redis Geo)
def find_nearest(pickup: Location, radius_km: float = 5.0):
    # Redis GEO command: calculates distance, returns sorted
    nearby = redis.georadius(
        "drivers:available",
        pickup.lng, pickup.lat,
        radius_km, unit="km",
        withcoord=True, withdist=True
    )
    return nearby[:5]  # Top 5 closest
```

**Why not just compute Euclidean distance for all drivers?** With 10K+ drivers in a city, O(n) scan per ride request is 10K distance calculations. Geo-indexing gives O(log n) lookup. Redis Geo uses sorted sets internally with geohash encoding — million-point queries in milliseconds.

---

## Question 3: Surge Pricing
**Interviewer:** *"How would you implement surge pricing?"*

### 🎯 Answer

**Zone-based dynamic pricing:**
```python
class SurgeEngine:
    def get_surge_multiplier(self, zone_id: str) -> float:
        supply = self._available_drivers_in_zone(zone_id)
        demand = self._ride_requests_in_window(zone_id, window_minutes=5)
        
        if supply == 0: return 2.5  # Max surge
        ratio = demand / supply
        
        if ratio > 3.0: return 2.0
        if ratio > 2.0: return 1.5
        if ratio > 1.5: return 1.25
        return 1.0
```

**Real-world considerations:**
- **Geofencing**: Partition city into hexagon zones (~500m across)
- **Leading indicator**: Use airport flight arrivals to predict demand surge
- **Traffic data**: Factor in current traffic for ETA and pricing
- **Events**: Pre-load surge for concerts, sports events (API integration with Ticketmaster)
- **Sticky surge**: Surge decays slowly (over 5 min), not instantly — prevents drivers from gaming

---

## Question 4: Real-time Location Tracking
**Interviewer:** *"How do you track driver locations in real-time?"*

### 🎯 Architecture

```
Driver App ──(WebSocket)──▶ Location Service ──▶ Redis Geo
                                      │
                                      └──▶ Kafka ──▶ Analytics/ETL
```

**GPS polling optimization:**
- **Moving**: Send location every 3 seconds
- **Stationary**: Send every 30 seconds (battery optimization)
- **Trip active**: Every 2 seconds for ETA accuracy
- **Dead reckoning**: If connection drops, estimate position from last speed/direction

---

## Question 5: Payment & Billing
**Interviewer:** *"Design the payment system for cab rides."*

### 🎯 Answer

```python
class RidePayment:
    def calculate_final_fare(self, trip):
        base_fare = self._pricing.calculate_fare(trip.distance, trip.duration)
        surge = self._surge_engine.get_surge(trip.zone, trip.time)
        tolls = self._road_tolls(trip.route)
        waiting = self._waiting_charge(trip.waiting_minutes)
        tip = trip.tip_amount
        
        return (base_fare * surge) + tolls + waiting + tip
```

**Pre-authorization:** Authorize card for estimated fare before ride starts. On completion, capture the final amount. If final > estimate, second authorization needed.

---

## Question 6: Scalability for City-Wide Coverage

**Architecture:**
```
                ┌─────────────┐
Rider App ─────▶│  API GW      │──▶ Rate Limiter
                │  (SSL term)  │──▶ Auth Service
                └──────┬──────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
    ┌─────▼────┐ ┌────▼────┐ ┌────▼────┐
    │ Mumbai   │ │ Delhi   │ │ Other   │
    │ Cluster  │ │ Cluster │ │ Cities  │
    └──────────┘ └─────────┘ └─────────┘
```

**Per-city isolation:** Each city has its own Redis Geo, driver pool, and pricing engine. Cross-city trips use inter-cluster communication.

---

## Question 7: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | Pricing, Matching | Interchangeable algorithms |
| **Observer** | Location updates | Real-time UI, event stream |
| **State** | Trip lifecycle | Clean status transitions |
| **Facade** | CabBookingService | Unified API surface |
| **Factory** | Driver/Rider creation | Config-driven setup |
| **Singleton** | Region manager | Single point of coordination |
