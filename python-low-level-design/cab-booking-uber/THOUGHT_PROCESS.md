# 🧠 Cab Booking (Uber) LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

```mermaid
classDiagram
    direction LR
    class CabBookingService {
        +geo_index: GeoIndex
        +zone_manager: ZoneManager
        +broker: Optional~KafkaBroker~
        +zone_analytics: Optional~ZoneAnalyticsAggregator~
        -_matching: DriverMatchingStrategy
        -_trips: Dict~str, Trip~
        -_active_trip_by_rider: Dict~str, str~
        +register_rider(name: str, phone: str) Rider
        +register_driver(name: str, phone: str, license_number: str, cab_type: CabType) Driver
        +update_driver_location(driver_id: str, location: Location, ts: float) None
        +go_online(driver_id: str) bool
        +go_offline(driver_id: str) bool
        +request_ride(rider_id: str, pickup: Location, dropoff: Location, cab_type: CabType) Trip
        +accept_trip(trip_id: str) Trip
        +decline_trip(trip_id: str) Trip
        +driver_arrived(trip_id: str) Trip
        +start_trip(trip_id: str) Trip
        +complete_trip(trip_id: str) Decimal
        +cancel_trip(trip_id: str, reason: str) Trip
        +rate_driver(trip_id: str, stars: float) None
        +set_matching_strategy(strategy: DriverMatchingStrategy) None
    }
    class Rider {
        +rider_id: str
        +name: str
        +phone: str
    }
    class Driver {
        +driver_id: str
        +name: str
        +license_number: str
        +cab_type: CabType
        +status: CabStatus
        +rating: float
        +is_available() bool
        +compare_and_set(expected: CabStatus, new: CabStatus) bool
        +try_claim() bool
        +add_rating(stars: float) None
    }
    class Trip {
        <<dataclass>>
        +trip_id: str
        +rider: Rider
        +driver: Driver
        +pickup: Location
        +dropoff: Location
        +cab_type: CabType
        +fare: Decimal
        +surge_multiplier: Decimal
        +status: TripStatus
        +declined_by: Set~str~
        +accept() None
        +arrive() None
        +start() None
        +complete() Decimal
        +cancel(reason: str) None
        +reassign(new_driver: Driver) None
    }
    class Location {
        <<dataclass>>
        +lat: float
        +lng: float
        +distance_to(other: Location) float
    }
    class CabStatus {
        <<enumeration>>
        AVAILABLE
        BOOKED
        ON_TRIP
        OFFLINE
    }
    class TripStatus {
        <<enumeration>>
        REQUESTED
        ACCEPTED
        DRIVER_ARRIVED
        STARTED
        COMPLETED
        CANCELLED
    }
    class CabType {
        <<enumeration>>
        MINI
        SEDAN
        SUV
        PREMIUM
        AUTO
    }
    class PricingStrategy {
        <<abstract>>
        +calculate_fare(distance_km: float, duration_min: float) Decimal
    }
    class StandardPricing {
        -_card: RateCard
        +calculate_fare(distance_km: float, duration_min: float) Decimal
    }
    class SurgePricing {
        -_base: PricingStrategy
        -_multiplier: Decimal
        +calculate_fare(distance_km: float, duration_min: float) Decimal
    }
    class DriverMatchingStrategy {
        <<abstract>>
        +rank(pickup: Location, candidates: List~Tuple~) List~Driver~
    }
    class NearestDriverMatching
    class HighestRatedDriverMatching
    class GeoIndex {
        +PRECISION: int
        +upsert(driver_id: str, location: Location, ts: float) bool
        +remove(driver_id: str) None
        +location_of(driver_id: str) Optional~Location~
        +search(center: Location, radius_km: float) List~Tuple~
    }
    class KafkaBroker {
        +create_topic(name: str, partitions: int) None
        +produce(topic: str, key: str, value: dict) KafkaMessage
        +poll(topic: str, group: str, max_messages: int) List~KafkaMessage~
        +commit(group: str, msg: KafkaMessage) None
    }
    class Zone {
        <<dataclass>>
        +zone_id: str
        +center: Location
        +driver_count: int
        +ride_request_count: int
        +surge_multiplier: Decimal
        +update_supply_demand(driver_count: int, ride_requests: int) None
    }
    class ZoneManager {
        +PRECISION: int
        +zones: List~Zone~
        +zone_for(location: Location) Zone
        +get_zone(zone_id: str) Optional~Zone~
    }
    class GPSLocationStreamProcessor {
        +total_processed: int
        +poll(max_messages: int) int
    }
    class ZoneAnalyticsAggregator {
        +record_ride_request(pickup: Location) None
        +aggregate() List~Zone~
    }

    PricingStrategy <|-- StandardPricing
    PricingStrategy <|-- SurgePricing
    SurgePricing o-- PricingStrategy : wraps
    DriverMatchingStrategy <|-- NearestDriverMatching
    DriverMatchingStrategy <|-- HighestRatedDriverMatching

    CabBookingService *-- "*" Trip : trips
    CabBookingService o-- "*" Rider
    CabBookingService o-- "*" Driver
    CabBookingService *-- GeoIndex
    CabBookingService *-- ZoneManager
    CabBookingService o-- KafkaBroker
    CabBookingService *-- GPSLocationStreamProcessor
    CabBookingService *-- ZoneAnalyticsAggregator
    CabBookingService --> DriverMatchingStrategy : ranks with
    CabBookingService ..> SurgePricing : prices with

    Trip --> Rider
    Trip --> "1" Driver : owns status while active
    Trip --> TripStatus
    Trip --> Location : pickup, dropoff
    Driver --> CabStatus
    Driver --> CabType
    ZoneManager *-- "*" Zone
    GPSLocationStreamProcessor --> KafkaBroker : consumes gps.raw
    GPSLocationStreamProcessor --> GeoIndex : upserts
    GPSLocationStreamProcessor --> ZoneManager
    ZoneAnalyticsAggregator --> KafkaBroker : consumes gps.enriched
    ZoneAnalyticsAggregator --> ZoneManager : updates surge
```

---

## ⏱️ How to Run This in a 45–60 min Interview

| Time | Step | What you do | What to say out loud |
|------|------|-------------|----------------------|
| 0–7 | **Clarify** | Pin scope with the questions below. Write the agreed list in a comment. | "I'll treat matching, the trip lifecycle and pricing as core; GPS ingestion and surge as stretch." |
| 7–15 | **Entities & interfaces** | Enums, `Location`, `Driver`, `Trip`, `PricingStrategy`, `DriverMatchingStrategy`, the service facade. Draw the trip state machine. | "Driver status and trip status are separate state machines that move together. The trip owns the driver's status while it's active." |
| 15–35 | **Core code** | `request_ride` (search → rank → claim → price → create trip), `Trip` transitions table, `StandardPricing` + `SurgePricing`. A linear scan for "nearby" is fine first. | "I'm writing the linear scan first and hiding it behind `GeoIndex.search` so I can swap in geohash without touching matching." |
| 35–45 | **Concurrency** | `Driver.try_claim()` as a CAS; trip lock around transitions; one active trip per rider. | "The search result is stale by definition. The claim is the only authority, and losing a claim means try the next driver, not fail." |
| 45–55 | **Extension** | Whatever they add: decline/timeout, surge, cancellation fee, pool, ETA ranking. | "This fits in `rank()` / a new transition / the decorator chain. Here's the one place that changes." |
| 55–60 | **Wrap up** | Tests you'd write; how it maps to a service. | "In production the CAS becomes a conditional UPDATE or Redis `SET NX`, and the index is Redis GEO fed by Kafka." |

### Clarifying questions worth asking

1. **Matching rule:** nearest by straight line, by ETA, or by rating? Fixed radius or expanding? *(Drives the strategy interface.)*
2. **Offer model:** does the driver accept/decline, with a timeout, or is assignment automatic? *(Adds `REQUESTED` vs `ACCEPTED`.)*
3. **Cancellation:** who can cancel, until when, and is there a fee after the driver arrives? *(Transition table.)*
4. **Pricing:** upfront fare locked at request, or metered at the end? Surge per zone? *(Fare stored on trip vs computed at completion.)*
5. **Concurrency scope:** many riders requesting at once in the same area? *(Yes, always. Say you'll make the claim atomic.)*
6. **Can a rider have more than one active trip?** *(Usually no; enforce it.)*
7. **Scale for the follow-up:** drivers per city and GPS frequency. *(100K drivers / 3 s ≈ 33K writes/s, which is why the index is in memory.)*

---

## Phase 0: Requirements

Rider requests a cab of a type from A to B. The system finds a nearby available driver of that type, offers
the trip, and on acceptance the trip runs `ACCEPTED → DRIVER_ARRIVED → STARTED → COMPLETED`. Fare is quoted
up front (base + per km + per minute, times zone surge). Drivers stream GPS. A driver is never on two trips.

## Phase 1: Identify the Nouns

| Noun | Decision | Why |
|------|----------|-----|
| Rider | Class | Identity, minimal behaviour |
| Driver | Class with a lock | Status is contended state; changes via compare-and-set |
| Location | Frozen dataclass | Value object with haversine `distance_to` |
| GeoIndex | Class | "Who is near this point?" behind one method (`search`) |
| Trip | Dataclass with a lock | State machine; owns its driver's status while active |
| PricingStrategy | ABC | Base fare; surge decorates it |
| DriverMatchingStrategy | ABC | Ranking policy, pure function of candidates |
| Zone / ZoneManager | Classes | Surge per area |
| KafkaBroker | Class | Event pipeline simulation (stretch) |
| CabBookingService | Facade | Orchestrates matching, pricing, lifecycle |

## Phase 2: Enums First

```python
class CabStatus(Enum):  AVAILABLE, BOOKED, ON_TRIP, OFFLINE
class TripStatus(Enum): REQUESTED, ACCEPTED, DRIVER_ARRIVED, STARTED, COMPLETED, CANCELLED
class CabType(Enum):    MINI, SEDAN, SUV, PREMIUM, AUTO
```

Don't add enums you won't use (a `PaymentMethod` with no payment flow is noise in an interview).

## Phase 3: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Distance | `Location.distance_to()` | Pure value-object behaviour |
| Who is nearby | `GeoIndex.search()` | Spatial structure hidden behind one call |
| Order candidates | `DriverMatchingStrategy.rank()` | Policy, no side effects |
| Reserve a driver | `Driver.try_claim()` | The driver guards its own status |
| Fare | `PricingStrategy.calculate_fare()` | Strategy; surge is a decorator |
| Status transitions | `Trip.accept/arrive/start/complete/cancel` | Trip owns its lifecycle and validates against a table |
| Orchestration | `CabBookingService.request_ride()` | Search → rank → claim → price → create |

## Phase 4: The Concurrency Story (say this unprompted)

The classic bug is check-then-act: `if driver.is_available(): driver.status = BOOKED`. Two requests both see
AVAILABLE and both book. The fix is one atomic step:

```python
def try_claim(self) -> bool:
    with self._lock:
        if self._status is not CabStatus.AVAILABLE:
            return False
        self._status = CabStatus.BOOKED
        return True
```

and a matcher that treats a failed claim as "next candidate". Then lock the trip for every transition, so
cancel-vs-start can't both win. Lock order trip → driver, never the reverse.

## Phase 5: Two Strategy Patterns

```python
class PricingStrategy(ABC):
    def calculate_fare(self, distance_km, duration_min) -> Decimal

class StandardPricing(PricingStrategy)      # rate card per cab type
class SurgePricing(PricingStrategy)         # decorator: wraps any strategy, multiplies

class DriverMatchingStrategy(ABC):
    def rank(self, pickup, candidates: list[(Driver, km)]) -> list[Driver]

class NearestDriverMatching(...)            # distance asc
class HighestRatedDriverMatching(...)       # rating desc within radius, distance tiebreak
```

Radius expansion (2 → 5 → 10 km) lives in the service, not in each strategy, so every strategy gets it.

## Phase 6: GeoIndex

Start with a linear scan (O(N)), then say: "Redis GEO stores members in a sorted set keyed by a 52-bit
geohash. A radius query scans the centre cell and its 8 neighbours at a precision where a cell is at least
the radius wide, then filters by exact distance." Forgetting the neighbours is the common bug: a driver 50 m
away across a cell edge gets missed.

## Phase 7: Quick Checklist

✅ **Atomic claim:** no driver on two trips, losers fall through to the next candidate
✅ **State machine:** transitions in a table, illegal ones raise
✅ **Money:** `Decimal`, quoted at request
✅ **Strategy + Decorator:** matching and pricing swappable; surge composes
✅ **OCP:** new cab type = enum value + rate card
