# 🧠 Cab Booking (Uber) LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

## Phase 0: Requirements Gathering

How are riders matched to drivers? (Nearest, GeoRadius?) What cab types? Pricing model (base + per km)? Surge pricing? Location tracking?

## Phase 1: Identify the Nouns

> *"Riders request cabs. Nearby drivers are matched. Fare is calculated based on distance and duration."*

| Noun | Decision | Why |
|------|----------|-----|
| Rider | Regular Class | Identity, minimal behavior |
| Driver | Regular Class | Status, location, rating, cab type |
| Location | Regular Class | Value object with Haversine distance |
| GeoIndex | Regular Class | Simulates Redis GEO for spatial search |
| Trip | Regular Class | State machine: REQUESTED → COMPLETED |
| PricingStrategy | ABC | Strategy for fare calculation |
| DriverMatchingStrategy | ABC | Strategy for finding drivers |
| Zone / ZoneManager | Regular | Surge pricing zones |
| KafkaBroker / KafkaTopic | Regular | Event simulation |
| CabBookingService | Facade | Main entry point |
| CabStatus / TripStatus / CabType / PaymentMethod | Enum | System vocabularies |

## Phase 2: Enums First

```python
class CabStatus(Enum):  AVAILABLE, BOOKED, ON_TRIP, OFFLINE, MAINTENANCE
class TripStatus(Enum): REQUESTED, ACCEPTED, STARTED, COMPLETED, CANCELLED
class CabType(Enum):    MINI, SEDAN, SUV, PREMIUM, AUTO
class PaymentMethod(Enum): CASH, CARD, WALLET, UPI
```

## Phase 3: dataclass vs `__init__`

- **`Location`**: Regular — has behavior (`distance_to` with Haversine formula, `to_dict`)
- **`Rider`**: Regular — identity class
- **`Driver`**: Regular — complex state (status, rating, location updates)
- **`Trip`**: Regular — lifecycle management (start, complete, cancel)
- **`GeoIndex`**: Regular — geohash encoding + spatial search
- **`KafkaMessage`/`KafkaTopic`**: Regular — event simulation

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Calculate distance | `Location.distance_to()` | Location is a value object with behavior |
| Update driver location | `GeoIndex.update_location()` | GeoIndex manages spatial indices |
| Search nearby drivers | `GeoIndex.geo_radius_search()` | Simulates Redis GEORADIUS |
| Calculate fare | `PricingStrategy.calculate_fare()` | Strategy pattern |
| Find best driver | `DriverMatchingStrategy.find_driver()` | Strategy pattern |
| Start/complete trip | `Trip.start()`/`Trip.complete()` | Trip owns its lifecycle |
| Request ride | `CabBookingService.request_ride()` | Orchestrates matching + pricing + trip |

## Phase 5: Location Value Object

```python
class Location:
    def __init__(self, lat: float, lng: float):
        self._lat = lat
        self._lng = lng
    
    def distance_to(self, other: 'Location') -> float:
        """Haversine formula for km distance"""
        # Pure calculation, no side effects
    
    def to_dict(self) -> dict:
        return {"lat": self._lat, "lng": self._lng}
```

**Value objects** are immutable-ish, have behavior, and are compared by value.

## Phase 6: Two Strategy Patterns

**Pricing:**
```python
class PricingStrategy(ABC):
    def calculate_fare(self, distance_km, duration_min) -> float

class StandardPricing(PricingStrategy):  # Base + per km + per min
class SurgePricing(PricingStrategy):     # Multiplier on base
```

**Driver Matching:**
```python
class DriverMatchingStrategy(ABC):
    def find_driver(self, pickup, cab_type, drivers, geo_index)

class NearestDriverMatching(DriverMatchingStrategy):  # Closest first
class GeoRadiusDriverMatching(DriverMatchingStrategy):  # Progressive expansion
```

## Phase 7: GeoIndex (Simulated Redis GEO)

The GeoIndex uses geohash encoding for O(log N) spatial search:
```
In production: Redis GEOADD + GEORADIUS
Simulated: geohash prefix matching → distance filter → sort
```

## Phase 8: Quick Checklist

✅ **Value Object:** Location encapsulates coordinates + distance calculation
✅ **Strategy:** Both pricing and driver matching are swappable
✅ **SRP:** Rider, Driver, Trip, GeoIndex each own their data
✅ **OCP:** New cab type → add enum + rate, no pricing class changes
