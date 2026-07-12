# Cab Booking (Uber) — Implementation

> Python implementation of the Cab Booking (Uber) system following SOLID principles and design patterns.
> Includes: GeoRadius matching, Kafka event pipeline, Zone-based surge management, Production DB schema.

---

## 🗄️ Database Schema

The complete production schema for the cab booking system is in [**DB_SCHEMA.md**](DB_SCHEMA.md).
It includes 8 PostgreSQL + PostGIS tables:
- `riders`, `drivers`, `trips`, `zones`, `driver_location_history` (partitioned by month)
- `payments`, `rider_ratings`, `surge_pricing_log`
- Redis GEO keys for real-time matching
- PostGIS geo-radius query examples

---

## 📦 Core Implementation

```python
"""
Cab Booking Service (Uber/Ola) - Low Level Design
----------------------------------------------------
Design Principles: SOLID, Strategy Pattern, Observer Pattern

Infrastructure Additions:
  - GeoRadius-based driver matching (simulated Redis GEO)
  - Kafka event simulation for GPS location updates
  - Zone creation & driver counting per zone for surge
  - Proper DB schema for all entities
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Tuple, Set, Callable
from datetime import datetime, timedelta
import math
import uuid
import random
import json


class CabStatus(Enum):
    AVAILABLE = "Available"
    BOOKED = "Booked"
    ON_TRIP = "On Trip"
    OFFLINE = "Offline"
    MAINTENANCE = "Maintenance"


class TripStatus(Enum):
    REQUESTED = "Requested"
    ACCEPTED = "Accepted"
    STARTED = "Started"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class CabType(Enum):
    MINI = "Mini"
    SEDAN = "Sedan"
    SUV = "SUV"
    PREMIUM = "Premium"
    AUTO = "Auto"


class PaymentMethod(Enum):
    CASH = "Cash"
    CARD = "Card"
    WALLET = "Wallet"
    UPI = "UPI"


# --- Location (Value Object) ---

class Location:
    def __init__(self, lat: float, lng: float):
        self._lat = lat
        self._lng = lng

    @property
    def lat(self) -> float:
        return self._lat

    @property
    def lng(self) -> float:
        return self._lng

    def distance_to(self, other: 'Location') -> float:
        """Haversine formula for km distance"""
        R = 6371
        d_lat = math.radians(other._lat - self._lat)
        d_lng = math.radians(other._lng - self._lng)
        a = (math.sin(d_lat / 2) ** 2 +
             math.cos(math.radians(self._lat)) * math.cos(math.radians(other._lat)) *
             math.sin(d_lng / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def to_dict(self) -> dict:
        return {"lat": self._lat, "lng": self._lng}

    def __str__(self) -> str:
        return f"({self._lat:.4f}, {self._lng:.4f})"


# --- Rider & Driver (SRP) ---

class Rider:
    def __init__(self, rider_id: str, name: str, phone: str):
        self._rider_id = rider_id
        self._name = name
        self._phone = phone

    @property
    def rider_id(self) -> str:
        return self._rider_id

    @property
    def name(self) -> str:
        return self._name

    def __str__(self) -> str:
        return f"{self._name} ({self._phone})"


class Driver:
    def __init__(self, driver_id: str, name: str, phone: str,
                 license_number: str, cab_type: CabType):
        self._driver_id = driver_id
        self._name = name
        self._phone = phone
        self._license = license_number
        self._cab_type = cab_type
        self._status = CabStatus.AVAILABLE
        self._current_location: Optional[Location] = None
        self._rating = 5.0
        self._total_rides = 0

    @property
    def driver_id(self) -> str:
        return self._driver_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def cab_type(self) -> CabType:
        return self._cab_type

    @property
    def status(self) -> CabStatus:
        return self._status

    @status.setter
    def status(self, value: CabStatus) -> None:
        self._status = value

    @property
    def current_location(self) -> Optional[Location]:
        return self._current_location

    @current_location.setter
    def current_location(self, loc: Location) -> None:
        self._current_location = loc

    @property
    def rating(self) -> float:
        return self._rating

    def update_rating(self, new_rating: float) -> None:
        self._rating = ((self._rating * self._total_rides) + new_rating) / (self._total_rides + 1)
        self._total_rides += 1

    def is_available(self) -> bool:
        return self._status == CabStatus.AVAILABLE

    def __str__(self) -> str:
        return f"{self._name} ({self._cab_type.value})"


# --- Pricing Strategy (Strategy Pattern - OCP) ---

class PricingStrategy(ABC):
    @abstractmethod
    def calculate_fare(self, distance_km: float, duration_min: float) -> float:
        pass


class StandardPricing(PricingStrategy):
    _base_fare = {CabType.MINI: 50, CabType.SEDAN: 80, CabType.SUV: 120, CabType.PREMIUM: 150, CabType.AUTO: 25}
    _per_km = {CabType.MINI: 10, CabType.SEDAN: 14, CabType.SUV: 18, CabType.PREMIUM: 22, CabType.AUTO: 8}
    _per_min = {CabType.MINI: 1, CabType.SEDAN: 1.5, CabType.SUV: 2, CabType.PREMIUM: 2.5, CabType.AUTO: 0.5}

    def __init__(self, cab_type: CabType):
        self._cab_type = cab_type

    def calculate_fare(self, distance_km: float, duration_min: float) -> float:
        return (self._base_fare.get(self._cab_type, 50) +
                self._per_km.get(self._cab_type, 10) * distance_km +
                self._per_min.get(self._cab_type, 1) * duration_min)


class SurgePricing(PricingStrategy):
    def __init__(self, base_strategy: PricingStrategy, surge_multiplier: float = 1.5):
        self._base = base_strategy
        self._surge = surge_multiplier

    def calculate_fare(self, distance_km: float, duration_min: float) -> float:
        return self._base.calculate_fare(distance_km, duration_min) * self._surge


# --- Geo-Spatial Index (Simulated Redis GEO) ---

class GeoIndex:
    """
    Simulates Redis GEO sorted set using geohash encoding.
    
    In production, Redis GEO uses:
      GEOADD drivers:available <lng> <lat> <driver_id>
      GEORADIUS drivers:available <lng> <lat> <radius> km WITHCOORD WITHDIST ASC COUNT <limit>
    """

    GEOHASH_PRECISION = 7

    _BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

    def __init__(self):
        self._drivers: Dict[str, Driver] = {}
        self._geohash_buckets: Dict[str, Set[str]] = {}
        self._location_cache: Dict[str, Location] = {}

    @staticmethod
    def _encode_geohash(lat: float, lng: float, precision: int = GEOHASH_PRECISION) -> str:
        """Encode lat/lng into a geohash string."""
        lat_range = [-90.0, 90.0]
        lng_range = [-180.0, 180.0]
        hash_chars = []
        bit = 0
        ch = 0
        even = True

        while len(hash_chars) < precision:
            if even:
                mid = (lng_range[0] + lng_range[1]) / 2
                if lng > mid:
                    ch |= (1 << (4 - bit))
                    lng_range[0] = mid
                else:
                    lng_range[1] = mid
            else:
                mid = (lat_range[0] + lat_range[1]) / 2
                if lat > mid:
                    ch |= (1 << (4 - bit))
                    lat_range[0] = mid
                else:
                    lat_range[1] = mid

            even = not even
            if bit < 4:
                bit += 1
            else:
                hash_chars.append(GeoIndex._BASE32[ch])
                bit = 0
                ch = 0

        return ''.join(hash_chars)

    def add_driver(self, driver: Driver) -> None:
        self._drivers[driver.driver_id] = driver

    def update_location(self, driver_id: str, location: Location) -> None:
        """Update driver location — removes old geohash, adds new one."""
        old_loc = self._location_cache.get(driver_id)
        if old_loc:
            old_hash = self._encode_geohash(old_loc.lat, old_loc.lng)
            if driver_id in self._geohash_buckets.get(old_hash, set()):
                self._geohash_buckets[old_hash].discard(driver_id)

        new_hash = self._encode_geohash(location.lat, location.lng)
        self._geohash_buckets.setdefault(new_hash, set()).add(driver_id)
        self._location_cache[driver_id] = location
        if driver_id in self._drivers:
            self._drivers[driver_id].current_location = location

    def geo_radius_search(self, center: Location, radius_km: float,
                          cab_type: Optional[CabType] = None,
                          limit: int = 5) -> List[Tuple[Driver, float, Location]]:
        """
        GEORADIUS equivalent: find drivers within radius_km of center.
        Uses geohash prefix matching for efficient O(log N) search.
        """
        if radius_km <= 0.5:
            prefix_len = 7
        elif radius_km <= 2:
            prefix_len = 6
        elif radius_km <= 10:
            prefix_len = 5
        elif radius_km <= 50:
            prefix_len = 4
        else:
            prefix_len = 3

        center_hash = self._encode_geohash(center.lat, center.lng, prefix_len)
        candidates: List[Tuple[Driver, float, Location]] = []

        for geohash, driver_ids in self._geohash_buckets.items():
            if not geohash.startswith(center_hash):
                continue
            for driver_id in driver_ids:
                driver = self._drivers.get(driver_id)
                if not driver or not driver.is_available():
                    continue
                if cab_type and driver.cab_type != cab_type:
                    continue
                loc = self._location_cache.get(driver_id)
                if not loc:
                    continue
                dist = center.distance_to(loc)
                if dist <= radius_km:
                    candidates.append((driver, dist, loc))

        candidates.sort(key=lambda x: x[1])
        return candidates[:limit]

    def count_drivers_in_radius(self, center: Location, radius_km: float) -> int:
        return len(self.geo_radius_search(center, radius_km, limit=1000))


# --- Kafka Event Simulation ---

class KafkaMessage:
    def __init__(self, topic: str, key: str, value: dict,
                 partition: Optional[int] = None,
                 timestamp: Optional[datetime] = None):
        self.topic = topic
        self.key = key
        self.value = value
        self.partition = partition or 0
        self.timestamp = timestamp or datetime.now()
        self.offset: Optional[int] = None

    def __str__(self) -> str:
        return (f"KMsg[topic={self.topic}, key={self.key}, "
                f"partition={self.partition}, offset={self.offset}]")


class KafkaTopic:
    def __init__(self, name: str, partitions: int = 3, replication_factor: int = 3):
        self.name = name
        self.partitions = partitions
        self.replication_factor = replication_factor
        self._messages: List[KafkaMessage] = []

    def produce(self, message: KafkaMessage) -> None:
        message.offset = len(self._messages)
        message.partition = hash(message.key) % self.partitions
        self._messages.append(message)


class KafkaBroker:
    def __init__(self):
        self._topics: Dict[str, KafkaTopic] = {}

    def create_topic(self, name: str, partitions: int = 3,
                     replication_factor: int = 3) -> KafkaTopic:
        topic = KafkaTopic(name, partitions, replication_factor)
        self._topics[name] = topic
        return topic

    def produce(self, topic_name: str, key: str, value: dict) -> None:
        topic = self._topics.get(topic_name)
        if not topic:
            raise ValueError(f"Topic {topic_name} does not exist")
        msg = KafkaMessage(topic_name, key, value)
        topic.produce(msg)


# --- Zone Management ---

class Zone:
    def __init__(self, zone_id: str, center: Location, radius_km: float = 0.5):
        self.zone_id = zone_id
        self.center = center
        self.radius_km = radius_km
        self.driver_count: int = 0
        self.ride_request_count: int = 0
        self.surge_multiplier: float = 1.0
        self.last_updated: Optional[datetime] = None

    def update_supply_demand(self, driver_count: int, ride_requests: int) -> None:
        self.driver_count = driver_count
        self.ride_request_count = ride_requests
        self.last_updated = datetime.now()
        if driver_count == 0:
            self.surge_multiplier = 2.5
        else:
            ratio = ride_requests / driver_count
            if ratio > 3.0: self.surge_multiplier = 2.0
            elif ratio > 2.0: self.surge_multiplier = 1.5
            elif ratio > 1.5: self.surge_multiplier = 1.25
            else: self.surge_multiplier = 1.0


class ZoneManager:
    def __init__(self, city_center: Location, grid_radius_km: float = 10.0,
                 zone_radius_km: float = 0.5):
        self.city_center = city_center
        self.grid_radius_km = grid_radius_km
        self.zone_radius_km = zone_radius_km
        self._zones: Dict[str, Zone] = {}

    def create_hexagonal_grid(self) -> None:
        """Create hexagonal zones covering the city."""
        h_spacing = math.sqrt(3) * self.zone_radius_km
        v_spacing = 1.5 * self.zone_radius_km
        num_rings = max(1, int(self.grid_radius_km / self.zone_radius_km))
        zone_count = 0

        for ring in range(num_rings):
            hex_count = 6 * ring if ring > 0 else 1
            if ring == 0:
                zone = Zone(f"Z{zone_count:04d}", self.city_center, self.zone_radius_km)
                self._zones[zone.zone_id] = zone
                zone_count += 1
            else:
                for i in range(hex_count):
                    angle = (2 * math.pi * i) / hex_count
                    r = ring * h_spacing
                    lat = self.city_center.lat + (r * math.cos(angle)) / 111.0
                    lng = self.city_center.lng + (r * math.sin(angle)) / (111.0 * math.cos(math.radians(self.city_center.lat)))
                    zone = Zone(f"Z{zone_count:04d}", Location(lat, lng), self.zone_radius_km)
                    self._zones[zone.zone_id] = zone
                    zone_count += 1


# --- Driver Matching Strategies ---

class DriverMatchingStrategy(ABC):
    @abstractmethod
    def find_driver(self, pickup: Location, cab_type: CabType,
                    drivers: List[Driver],
                    geo_index: Optional[GeoIndex] = None) -> Optional[Driver]:
        pass


class NearestDriverMatching(DriverMatchingStrategy):
    def find_driver(self, pickup: Location, cab_type: CabType,
                    drivers: List[Driver],
                    geo_index: Optional[GeoIndex] = None) -> Optional[Driver]:
        if geo_index:
            results = geo_index.geo_radius_search(pickup, 5.0, cab_type, 1)
            return results[0][0] if results else None
        available = [d for d in drivers if d.is_available() and d.cab_type == cab_type and d.current_location]
        if not available:
            return None
        return min(available, key=lambda d: d.current_location.distance_to(pickup))


class GeoRadiusDriverMatching(DriverMatchingStrategy):
    """GeoRadius-based matching with progressive radius expansion."""
    def __init__(self, initial_radius_km: float = 3.0, max_radius_km: float = 10.0):
        self._initial_radius = initial_radius_km
        self._max_radius = max_radius_km

    def find_driver(self, pickup: Location, cab_type: CabType,
                    drivers: List[Driver],
                    geo_index: Optional[GeoIndex] = None) -> Optional[Driver]:
        if not geo_index:
            return None
        radius = self._initial_radius
        while radius <= self._max_radius:
            results = geo_index.geo_radius_search(pickup, radius, cab_type, 1)
            if results:
                return results[0][0]
            radius *= 1.5
        return None


# --- Trip (SRP) ---

class Trip:
    def __init__(self, trip_id: str, rider: Rider, driver: Driver,
                 pickup: Location, dropoff: Location, fare: float):
        self._trip_id = trip_id
        self._rider = rider
        self._driver = driver
        self._pickup = pickup
        self._dropoff = dropoff
        self._fare = fare
        self._status = TripStatus.REQUESTED
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None

    @property
    def trip_id(self) -> str:
        return self._trip_id
    @property
    def rider(self) -> Rider:
        return self._rider
    @property
    def driver(self) -> Driver:
        return self._driver
    @property
    def status(self) -> TripStatus:
        return self._status
    @status.setter
    def status(self, value: TripStatus) -> None:
        self._status = value

    def start(self) -> None:
        self._status = TripStatus.STARTED
        self._start_time = datetime.now()

    def complete(self) -> float:
        self._status = TripStatus.COMPLETED
        self._end_time = datetime.now()
        self._driver.status = CabStatus.AVAILABLE
        return self._fare

    def cancel(self) -> None:
        self._status = TripStatus.CANCELLED
        self._driver.status = CabStatus.AVAILABLE


# --- Cab Booking Service (Facade) ---

class CabBookingService:
    def __init__(self):
        self._riders: Dict[str, Rider] = {}
        self._drivers: Dict[str, Driver] = {}
        self._trips: Dict[str, Trip] = {}
        self._matching_strategy: DriverMatchingStrategy = NearestDriverMatching()
        self._geo_index = GeoIndex()
        self._kafka_broker: Optional[KafkaBroker] = None
        self._zone_manager: Optional[ZoneManager] = None

    def setup_geo_kafka_infrastructure(self, city_center: Location = Location(19.0760, 72.8777)) -> None:
        """Initialize Kafka broker, create topics, and set up zone manager."""
        self._kafka_broker = KafkaBroker()
        self._kafka_broker.create_topic("gps.raw.updates", partitions=5)
        self._kafka_broker.create_topic("gps.enriched.locations", partitions=5)
        self._kafka_broker.create_topic("gps.zone.driver_counts", partitions=3)
        self._kafka_broker.create_topic("gps.dlq", partitions=1)
        self._kafka_broker.create_topic("trip.events", partitions=3)
        self._zone_manager = ZoneManager(city_center, grid_radius_km=10.0, zone_radius_km=0.5)
        self._zone_manager.create_hexagonal_grid()

    def register_driver(self, name: str, phone: str, license_num: str, cab_type: CabType) -> Driver:
        driver_id = f"D-{uuid.uuid4().hex[:6].upper()}"
        driver = Driver(driver_id, name, phone, license_num, cab_type)
        self._drivers[driver_id] = driver
        self._geo_index.add_driver(driver)
        return driver

    def update_driver_location(self, driver_id: str, location: Location,
                                speed_kmh: float = 0, heading: int = 0) -> None:
        driver = self._drivers.get(driver_id)
        if not driver:
            return
        driver.current_location = location
        if self._kafka_broker:
            raw_event = {
                "driver_id": driver_id,
                "lat": location.lat, "lng": location.lng,
                "speed_kmh": speed_kmh, "heading": heading,
                "timestamp": datetime.now().isoformat()
            }
            self._kafka_broker.produce("gps.raw.updates", driver_id, raw_event)
        self._geo_index.update_location(driver_id, location)

    def request_ride(self, rider_id: str, pickup: Location, dropoff: Location,
                     cab_type: CabType = CabType.MINI) -> Optional[Trip]:
        rider = self._riders.get(rider_id)
        if not rider:
            return None
        driver = self._matching_strategy.find_driver(
            pickup, cab_type, list(self._drivers.values()), self._geo_index
        )
        if not driver:
            print(f"  No {cab_type.value} available nearby")
            return None

        distance = pickup.distance_to(dropoff)
        est_duration = distance / 30 * 60
        pricing = SurgePricing(StandardPricing(cab_type), 1.0)
        fare = pricing.calculate_fare(distance, est_duration)

        trip_id = f"T-{uuid.uuid4().hex[:8].upper()}"
        trip = Trip(trip_id, rider, driver, pickup, dropoff, fare)
        trip.status = TripStatus.ACCEPTED
        driver.status = CabStatus.BOOKED
        self._trips[trip_id] = trip

        if self._kafka_broker:
            self._kafka_broker.produce("trip.events", trip_id, {
                "trip_id": trip_id, "status": "ACCEPTED",
                "timestamp": datetime.now().isoformat()
            })

        print(f"  ✅ Trip created! {driver.name} ({cab_type.value}) - ${fare:.2f}")
        return trip

    # ... (start_trip, complete_trip, cancel_trip remain the same)
```



## 🏛️ Architecture: GeoRadius + Kafka Pipeline

### Location Update Flow

```
Driver App                    Kafka                          Stream Processor
    │                           │                                  │
    │── GPS (3s interval) ──────┤                                  │
    │   {driver_id, lat, lng,   │                                  │
    │    speed, heading, ts}    │                                  │
    │                           │── Topic: gps.raw.updates ────────┤
    │                           │                                  │
    │                           │                                  ├── GeoIndex.update_location()
    │                           │                                  ├── Zone lookup
    │                           │                                  └── Publish enriched event
    │                           │                                      │
    │                           │── Topic: gps.enriched.locations ──┤
    │                           │   {driver_id, location, zone_id,  │
    │                           │    speed, heading, timestamp}     │
    │                           │                                  │
    │                           │                          Zone Analytics Aggregator
    │                           │                                  │
    │                           │── Topic: gps.zone.driver_counts ──┤
    │                           │   {zone_id, driver_count,         │
    │                           │    surge_multiplier, timestamp}   │
```

### GeoRadius Driver Matching

```
Rider Requests Ride
    │
    ├── GeoIndex.geo_radius_search(center=pickup, radius=3km)
    │       │
    │       ├── Encode pickup as geohash prefix (e.g., "te7u1q")
    │       ├── Scan all buckets matching prefix
    │       ├── Filter: status=AVAILABLE, cab_type=MINI
    │       ├── Calculate exact haversine distance
    │       ├── Sort by distance ASC
    │       └── Return top 5 candidates
    │
    └── If no driver found → expand radius to 5km → 10km
```

<p align="center">
  <img src="../../../assets/videos/cab-booking-sequence.gif" alt="Animated Cab Booking Sequence Diagram" width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" />
  <br/>
  <em>🎬 Animated Cab Booking Sequence — Rider Request → Geo Matching → Driver Dispatch → Trip Creation → Kafka Event Pipeline. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## ▶️ How to Run

```bash
cd low-level-design/cab-booking-uber
python cab_booking.py
```

## 🧩 Design Patterns

See the [Interview Questions](INTERVIEW_QUESTIONS.md) for a detailed breakdown of design patterns and SOLID principles applied in this implementation.
