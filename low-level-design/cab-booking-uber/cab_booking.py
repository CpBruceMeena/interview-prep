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


# ============================================================
# GEO-SPATIAL INDEX: Simulated Redis GEO (Sorted Set)
# ============================================================

class GeoIndex:
    """
    Simulates Redis GEO sorted set using geohash encoding.
    
    In production, Redis GEO uses:
      GEOADD drivers:available <lng> <lat> <driver_id>
      GEORADIUS drivers:available <lng> <lat> <radius> km WITHCOORD WITHDIST ASC COUNT <limit>
    
    Here we maintain an in-memory spatial index using
    geohash-prefix bucketing for O(log N) lookup.
    """

    GEOHASH_PRECISION = 7  # ~76m × 76m precision

    # Base32 character set for geohash
    _BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

    def __init__(self):
        self._drivers: Dict[str, Driver] = {}        # driver_id -> Driver
        self._geohash_buckets: Dict[str, Set[str]] = {}  # geohash -> {driver_ids}
        self._location_cache: Dict[str, Location] = {}   # driver_id -> last Location

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
        """Register driver in geo index."""
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

        # Also update the driver object
        if driver_id in self._drivers:
            self._drivers[driver_id].current_location = location

    def geo_radius_search(self, center: Location, radius_km: float,
                          cab_type: Optional[CabType] = None,
                          limit: int = 5) -> List[Tuple[Driver, float, Location]]:
        """
        GEORADIUS equivalent: find drivers within radius_km of center.
        Returns list of (Driver, distance_km, Location) sorted by distance ASC.
        Uses geohash prefix matching for efficient search.
        """
        # Determine geohash prefix length based on radius
        # Larger radius -> shorter prefix (broader search)
        if radius_km <= 0.5:
            prefix_len = 7  # ~76m precision
        elif radius_km <= 2:
            prefix_len = 6  # ~610m
        elif radius_km <= 10:
            prefix_len = 5  # ~4.9km
        elif radius_km <= 50:
            prefix_len = 4  # ~39km
        else:
            prefix_len = 3  # ~312km

        center_hash = self._encode_geohash(center.lat, center.lng, prefix_len)

        candidates: List[Tuple[Driver, float, Location]] = []

        # Search all buckets matching the prefix
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

        # Sort by distance ASC and limit
        candidates.sort(key=lambda x: x[1])
        return candidates[:limit]

    def count_drivers_in_radius(self, center: Location, radius_km: float) -> int:
        """Count available drivers within radius (for surge calculation)."""
        return len(self.geo_radius_search(center, radius_km, limit=1000))


# ============================================================
# KAFKA SIMULATION: Event Bus for GPS Location Updates
# ============================================================

class KafkaMessage:
    """Represents a message in the Kafka event bus."""

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


class KafkaConsumerGroup:
    """Simulates a Kafka consumer group with partition assignment."""

    def __init__(self, group_id: str, topics: List[str]):
        self.group_id = group_id
        self.topics = topics
        self._offset: Dict[str, int] = {}  # topic_partition -> offset

    def commit(self, topic: str, partition: int, offset: int) -> None:
        key = f"{topic}:{partition}"
        self._offset[key] = offset

    def get_offset(self, topic: str, partition: int) -> int:
        return self._offset.get(f"{topic}:{partition}", 0)


class KafkaTopic:
    """Simulates a Kafka topic with multiple partitions."""

    def __init__(self, name: str, partitions: int = 3, replication_factor: int = 3):
        self.name = name
        self.partitions = partitions
        self.replication_factor = replication_factor
        self._messages: List[KafkaMessage] = []

    def produce(self, message: KafkaMessage) -> None:
        """Produce a message and assign offset."""
        message.offset = len(self._messages)
        message.partition = hash(message.key) % self.partitions
        self._messages.append(message)

    def consume(self, group: KafkaConsumerGroup, batch_size: int = 10,
                auto_commit: bool = True) -> List[KafkaMessage]:
        """Consume messages from the topic for a consumer group."""
        offset = group.get_offset(self.name, 0)
        if offset >= len(self._messages):
            return []

        batch = self._messages[offset:offset + batch_size]

        if auto_commit:
            group.commit(self.name, 0, offset + len(batch))

        return batch


class KafkaBroker:
    """Simulates a Kafka broker managing multiple topics."""

    def __init__(self):
        self._topics: Dict[str, KafkaTopic] = {}

    def create_topic(self, name: str, partitions: int = 3,
                     replication_factor: int = 3) -> KafkaTopic:
        topic = KafkaTopic(name, partitions, replication_factor)
        self._topics[name] = topic
        return topic

    def get_topic(self, name: str) -> Optional[KafkaTopic]:
        return self._topics.get(name)

    def produce(self, topic_name: str, key: str, value: dict) -> None:
        topic = self._topics.get(topic_name)
        if not topic:
            raise ValueError(f"Topic {topic_name} does not exist")
        msg = KafkaMessage(topic_name, key, value)
        topic.produce(msg)

    def consume(self, topic_name: str, group: KafkaConsumerGroup,
                batch_size: int = 10) -> List[KafkaMessage]:
        topic = self._topics.get(topic_name)
        if not topic:
            return []
        return topic.consume(group, batch_size)


# ============================================================
# ZONE MANAGEMENT: City Partitioning for Surge & Analytics
# ============================================================

class Zone:
    """
    Represents a hexagonal zone within a city.
    Each zone has a center, radius, and maintains supply/demand counts.
    """

    def __init__(self, zone_id: str, center: Location, radius_km: float = 0.5):
        self.zone_id = zone_id
        self.center = center
        self.radius_km = radius_km
        self.driver_count: int = 0
        self.ride_request_count: int = 0
        self.surge_multiplier: float = 1.0
        self.last_updated: Optional[datetime] = None

    def update_supply_demand(self, driver_count: int, ride_requests: int) -> None:
        """Update supply/demand and recalculate surge multiplier."""
        self.driver_count = driver_count
        self.ride_request_count = ride_requests
        self.last_updated = datetime.now()

        # Surge calculation
        if driver_count == 0:
            self.surge_multiplier = 2.5
        else:
            ratio = ride_requests / driver_count
            if ratio > 3.0:
                self.surge_multiplier = 2.0
            elif ratio > 2.0:
                self.surge_multiplier = 1.5
            elif ratio > 1.5:
                self.surge_multiplier = 1.25
            else:
                self.surge_multiplier = 1.0

    def __str__(self) -> str:
        return (f"Zone[{self.zone_id}]: {self.driver_count} drivers, "
                f"{self.ride_request_count} requests, surge={self.surge_multiplier:.2f}x")


class ZoneManager:
    """
    Manages zones within a city. Supports creation from a grid pattern
    and assignment of locations to zones.
    """

    def __init__(self, city_center: Location, grid_radius_km: float = 10.0,
                 zone_radius_km: float = 0.5):
        self.city_center = city_center
        self.grid_radius_km = grid_radius_km
        self.zone_radius_km = zone_radius_km
        self._zones: Dict[str, Zone] = {}
        self._location_to_zone_cache: Dict[str, str] = {}  # "lat,lng" -> zone_id

    def create_hexagonal_grid(self) -> None:
        """
        Create a hexagonal grid of zones covering the city.
        
        Hexagonal packing is preferred over square grids because:
        1. All neighbors are equidistant
        2. Better approximation of circular radius searches
        3. Minimizes edge effects in zone transitions
        """
        # Hexagonal grid parameters
        # Each hexagon has radius = zone_radius_km
        # Horizontal spacing = sqrt(3) * radius
        # Vertical spacing = 1.5 * radius (offset rows)
        h_spacing = math.sqrt(3) * self.zone_radius_km
        v_spacing = 1.5 * self.zone_radius_km

        # Number of rings from center
        num_rings = max(1, int(self.grid_radius_km / self.zone_radius_km))

        zone_count = 0
        for ring in range(num_rings):
            # Number of hexagons in this ring
            hex_count = 6 * ring if ring > 0 else 1

            if ring == 0:
                # Center zone
                zone_id = f"Z{zone_count:04d}"
                zone = Zone(zone_id, self.city_center, self.zone_radius_km)
                self._zones[zone_id] = zone
                zone_count += 1
            else:
                for i in range(hex_count):
                    angle = (2 * math.pi * i) / hex_count
                    # Radial distance from center for this ring
                    r = ring * h_spacing
                    lat = self.city_center.lat + (r * math.cos(angle)) / 111.0
                    lng = self.city_center.lng + (r * math.sin(angle)) / (111.0 * math.cos(math.radians(self.city_center.lat)))

                    zone_id = f"Z{zone_count:04d}"
                    zone = Zone(zone_id, Location(lat, lng), self.zone_radius_km)
                    self._zones[zone_id] = zone
                    zone_count += 1

        print(f"  🗺️ Created {len(self._zones)} hexagonal zones covering {self.grid_radius_km}km grid")

    def get_zone_for_location(self, location: Location) -> Optional[Zone]:
        """Find the zone containing this location (by proximity to zone center)."""
        cache_key = f"{location.lat:.4f},{location.lng:.4f}"

        if cache_key in self._location_to_zone_cache:
            zone_id = self._location_to_zone_cache[cache_key]
            return self._zones.get(zone_id)

        # Find closest zone center
        closest_zone = min(
            self._zones.values(),
            key=lambda z: z.center.distance_to(location)
        )

        if closest_zone.center.distance_to(location) <= self.zone_radius_km:
            self._location_to_zone_cache[cache_key] = closest_zone.zone_id
            return closest_zone

        return None

    def update_driver_counts(self, geo_index: GeoIndex) -> None:
        """Update driver counts for all zones using the geo index."""
        for zone in self._zones.values():
            count = geo_index.count_drivers_in_radius(zone.center, zone.radius_km)
            zone.driver_count = count

    def get_zone(self, zone_id: str) -> Optional[Zone]:
        return self._zones.get(zone_id)

    @property
    def zones(self) -> List[Zone]:
        return list(self._zones.values())


# ============================================================
# GPS LOCATION STREAM PROCESSOR (Kafka Consumer)
# ============================================================

class GPSLocationStreamProcessor:
    """
    Processes GPS location updates from the Kafka stream.
    
    Kafka Topics:
      - gps.raw.updates: Raw GPS pings from driver apps
      - gps.enriched.locations: Enriched with zone info, speed, heading
      - gps.zone.driver_counts: Aggregated driver counts per zone
    """

    def __init__(self, broker: KafkaBroker, geo_index: GeoIndex,
                 zone_manager: ZoneManager):
        self.broker = broker
        self.geo_index = geo_index
        self.zone_manager = zone_manager
        self._consumer_group = KafkaConsumerGroup("gps-stream-processor",
                                                  ["gps.raw.updates"])
        self._total_processed = 0

    def process_batch(self, batch_size: int = 10) -> int:
        """Process a batch of raw GPS messages."""
        messages = self.broker.consume("gps.raw.updates",
                                       self._consumer_group,
                                       batch_size)

        processed = 0
        for msg in messages:
            try:
                value = msg.value
                driver_id = value.get("driver_id")
                lat = value.get("lat")
                lng = value.get("lng")
                speed = value.get("speed_kmh", 0)
                heading = value.get("heading", 0)

                if not all([driver_id, lat is not None, lng is not None]):
                    continue

                location = Location(lat, lng)

                # 1. Update geo index
                self.geo_index.update_location(driver_id, location)

                # 2. Determine zone
                zone = self.zone_manager.get_zone_for_location(location)
                zone_id = zone.zone_id if zone else "unknown"

                # 3. Publish enriched event
                enriched = {
                    "driver_id": driver_id,
                    "location": location.to_dict(),
                    "speed_kmh": speed,
                    "heading": heading,
                    "zone_id": zone_id,
                    "timestamp": datetime.now().isoformat(),
                    "processed_at": datetime.now().isoformat()
                }
                self.broker.produce("gps.enriched.locations",
                                    driver_id, enriched)

                processed += 1
            except Exception as e:
                # Publish to dead letter topic
                self.broker.produce("gps.dlq",
                                    msg.key,
                                    {"error": str(e), "original": msg.value})

        self._total_processed += processed
        return processed

    @property
    def total_processed(self) -> int:
        return self._total_processed


# ============================================================
# ZONE ANALYTICS AGGREGATOR (Kafka Consumer)
# ============================================================

class ZoneAnalyticsAggregator:
    """
    Consumes enriched GPS events to calculate driver counts per zone.
    Publishes zone stats every aggregation window.
    """

    def __init__(self, broker: KafkaBroker, zone_manager: ZoneManager,
                 window_seconds: int = 30):
        self.broker = broker
        self.zone_manager = zone_manager
        self.window_seconds = window_seconds
        self._consumer_group = KafkaConsumerGroup("zone-analytics",
                                                  ["gps.enriched.locations"])
        self._zone_drivers: Dict[str, Set[str]] = {}
        self._ride_requests: Dict[str, int] = {}
        self._last_aggregation: Optional[datetime] = None

    def record_ride_request(self, pickup: Location) -> None:
        """Record a ride request for surge calculation."""
        zone = self.zone_manager.get_zone_for_location(pickup)
        if zone:
            self._ride_requests[zone.zone_id] = self._ride_requests.get(zone.zone_id, 0) + 1

    def aggregate(self, batch_size: int = 50) -> List[Zone]:
        """Process enriched events and compute zone stats."""
        messages = self.broker.consume("gps.enriched.locations",
                                       self._consumer_group,
                                       batch_size)

        for msg in messages:
            value = msg.value
            driver_id = value.get("driver_id")
            zone_id = value.get("zone_id", "unknown")

            if zone_id != "unknown":
                self._zone_drivers.setdefault(zone_id, set()).add(driver_id)

        # Update zone driver counts
        for zone_id, drivers in self._zone_drivers.items():
            zone = self.zone_manager.get_zone(zone_id)
            if zone:
                requests = self._ride_requests.get(zone_id, 0)
                zone.update_supply_demand(len(drivers), requests)

        self._last_aggregation = datetime.now()

        # Publish aggregated zone stats
        zone_stats = []
        for zone in self.zone_manager.zones:
            stats = {
                "zone_id": zone.zone_id,
                "driver_count": zone.driver_count,
                "ride_requests": zone.ride_request_count,
                "surge_multiplier": zone.surge_multiplier,
                "timestamp": datetime.now().isoformat()
            }
            zone_stats.append(stats)
            self.broker.produce("gps.zone.driver_counts",
                                zone.zone_id, stats)

        return self.zone_manager.zones

    def reset_window(self) -> None:
        """Reset zone driver sets for next aggregation window."""
        self._zone_drivers.clear()
        self._ride_requests.clear()


# ============================================================
# DB SCHEMA (SQL DDL for reference)
# ============================================================

DB_SCHEMA_SQL = """
-- ============================================================
-- Cab Booking Service - Production Database Schema
-- Database: PostgreSQL 16 with PostGIS extension
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- -----------------------------------------------------------
-- 1. RIDERS
-- -----------------------------------------------------------
CREATE TABLE riders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    rating DECIMAL(2,1) DEFAULT 5.0 CHECK (rating >= 1.0 AND rating <= 5.0),
    total_rides INT DEFAULT 0,
    payment_methods JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_riders_email ON riders(email);
CREATE INDEX idx_riders_phone ON riders(phone);

-- -----------------------------------------------------------
-- 2. DRIVERS
-- -----------------------------------------------------------
CREATE TABLE drivers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    license_number VARCHAR(50) UNIQUE NOT NULL,
    cab_type VARCHAR(20) NOT NULL CHECK (cab_type IN ('MINI','SEDAN','SUV','PREMIUM','AUTO')),
    cab_registration VARCHAR(50) UNIQUE NOT NULL,
    rating DECIMAL(2,1) DEFAULT 5.0 CHECK (rating >= 1.0 AND rating <= 5.0),
    total_rides INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'AVAILABLE'
        CHECK (status IN ('AVAILABLE','BOOKED','ON_TRIP','OFFLINE','MAINTENANCE')),
    current_location GEOGRAPHY(Point, 4326),
    last_location_update TIMESTAMPTZ,
    is_verified BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_drivers_status ON drivers(status) WHERE status = 'AVAILABLE';
CREATE INDEX idx_drivers_location ON drivers USING GIST (current_location);
CREATE INDEX idx_drivers_cab_type ON drivers(cab_type);

-- -----------------------------------------------------------
-- 3. TRIPS
-- -----------------------------------------------------------
CREATE TABLE trips (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rider_id UUID NOT NULL REFERENCES riders(id),
    driver_id UUID REFERENCES drivers(id),
    pickup_location GEOGRAPHY(Point, 4326) NOT NULL,
    dropoff_location GEOGRAPHY(Point, 4326) NOT NULL,
    pickup_address TEXT,
    dropoff_address TEXT,
    status VARCHAR(20) DEFAULT 'REQUESTED'
        CHECK (status IN ('REQUESTED','ACCEPTED','DRIVER_ARRIVED',
                          'STARTED','COMPLETED','CANCELLED')),
    fare_estimate DECIMAL(10,2),
    final_fare DECIMAL(10,2),
    surge_multiplier DECIMAL(3,2) DEFAULT 1.0,
    distance_km DECIMAL(8,2),
    duration_min INT,
    waiting_minutes INT DEFAULT 0,
    payment_method VARCHAR(20) DEFAULT 'CASH',
    payment_status VARCHAR(20) DEFAULT 'PENDING'
        CHECK (payment_status IN ('PENDING','AUTHORIZED','CAPTURED','REFUNDED','FAILED')),
    idempotency_key VARCHAR(64) UNIQUE,
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    accepted_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    cancellation_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_trips_rider ON trips(rider_id);
CREATE INDEX idx_trips_driver ON trips(driver_id);
CREATE INDEX idx_trips_status ON trips(status);
CREATE INDEX idx_trips_requested ON trips(requested_at);

-- -----------------------------------------------------------
-- 4. ZONES (City Partitioning)
-- -----------------------------------------------------------
CREATE TABLE zones (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    city_id UUID NOT NULL,
    zone_code VARCHAR(10) NOT NULL,
    center GEOGRAPHY(Point, 4326) NOT NULL,
    radius_meters DECIMAL(10,2) NOT NULL DEFAULT 500,
    surge_multiplier DECIMAL(3,2) DEFAULT 1.0,
    driver_count INT DEFAULT 0,
    ride_request_count INT DEFAULT 0,
    last_calculated TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_zones_city ON zones(city_id);
CREATE INDEX idx_zones_center ON zones USING GIST (center);

-- -----------------------------------------------------------
-- 5. GPS LOCATION HISTORY
-- -----------------------------------------------------------
CREATE TABLE driver_location_history (
    id BIGSERIAL,
    driver_id UUID NOT NULL REFERENCES drivers(id),
    location GEOGRAPHY(Point, 4326) NOT NULL,
    speed_kmh DECIMAL(5,1),
    heading INT,
    accuracy_meters DECIMAL(5,1),
    zone_id UUID REFERENCES zones(id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (driver_id, recorded_at)
) PARTITION BY RANGE (recorded_at);

-- Monthly partitions
CREATE TABLE driver_location_history_202401 PARTITION OF driver_location_history
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE driver_location_history_202402 PARTITION OF driver_location_history
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

CREATE INDEX idx_loc_history_recorded ON driver_location_history(recorded_at DESC);

-- -----------------------------------------------------------
-- 6. PAYMENTS
-- -----------------------------------------------------------
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trip_id UUID NOT NULL REFERENCES trips(id),
    amount DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    method VARCHAR(20) NOT NULL CHECK (method IN ('CASH','CARD','WALLET','UPI')),
    status VARCHAR(20) DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','AUTHORIZED','CAPTURED','REFUNDED','FAILED')),
    gateway_transaction_id VARCHAR(255),
    gateway_response JSONB,
    idempotency_key VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_payments_trip ON payments(trip_id);
CREATE INDEX idx_payments_idempotency ON payments(idempotency_key);

-- -----------------------------------------------------------
-- 7. RIDER_RATINGS
-- -----------------------------------------------------------
CREATE TABLE rider_ratings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trip_id UUID NOT NULL REFERENCES trips(id),
    rider_id UUID NOT NULL REFERENCES riders(id),
    driver_id UUID NOT NULL REFERENCES drivers(id),
    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
    review TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(trip_id, rider_id, driver_id)
);

-- -----------------------------------------------------------
-- 8. SURGE PRICING LOG
-- -----------------------------------------------------------
CREATE TABLE surge_pricing_log (
    id BIGSERIAL,
    zone_id UUID NOT NULL REFERENCES zones(id),
    surge_multiplier DECIMAL(3,2) NOT NULL,
    driver_count INT NOT NULL,
    demand_count INT NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (zone_id, calculated_at)
);
CREATE INDEX idx_surge_log_calculated ON surge_pricing_log(calculated_at DESC);

-- -----------------------------------------------------------
-- 9. GEO-RADIUS QUERY EXAMPLE (PostGIS)
-- -----------------------------------------------------------
-- -- Find nearest available drivers within 3km
-- SELECT d.id, d.name, d.cab_type, d.rating,
--        ST_Distance(d.current_location, ST_MakePoint(-73.9857, 40.7484)::geography) / 1000 AS distance_km
-- FROM drivers d
-- WHERE d.status = 'AVAILABLE'
--   AND ST_DWithin(
--       d.current_location,
--       ST_MakePoint(-73.9857, 40.7484)::geography,
--       3000  -- 3km in meters
--   )
-- ORDER BY distance_km ASC
-- LIMIT 5;
"""


# ============================================================
# UPDATED DRIVER MATCHING STRATEGIES
# ============================================================

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
            # Use geo-radius search (O(log N))
            results = geo_index.geo_radius_search(pickup, 5.0, cab_type, 1)
            return results[0][0] if results else None

        # Fallback to linear scan (O(N))
        available = [d for d in drivers if d.is_available() and d.cab_type == cab_type and d.current_location]
        if not available:
            return None
        return min(available, key=lambda d: d.current_location.distance_to(pickup))


class HighestRatedDriverMatching(DriverMatchingStrategy):
    def find_driver(self, pickup: Location, cab_type: CabType,
                    drivers: List[Driver],
                    geo_index: Optional[GeoIndex] = None) -> Optional[Driver]:
        available = [d for d in drivers if d.is_available() and d.cab_type == cab_type]
        if not available:
            return None
        return max(available, key=lambda d: d.rating)


class GeoRadiusDriverMatching(DriverMatchingStrategy):
    """
    GeoRadius-based matching using spatial index.
    Finds nearest drivers within a specified radius using the GeoIndex.
    Supports:
      - Radius expansion: Start with 3km, expand to 5km, 10km if none found
      - Cab type filtering
      - Distance-based sorting
    """

    def __init__(self, initial_radius_km: float = 3.0,
                 max_radius_km: float = 10.0):
        self._initial_radius = initial_radius_km
        self._max_radius = max_radius_km

    def find_driver(self, pickup: Location, cab_type: CabType,
                    drivers: List[Driver],
                    geo_index: Optional[GeoIndex] = None) -> Optional[Driver]:
        if not geo_index:
            return None

        # Progressive radius expansion
        radius = self._initial_radius
        while radius <= self._max_radius:
            results = geo_index.geo_radius_search(pickup, radius, cab_type, 1)
            if results:
                driver, distance, _ = results[0]
                print(f"    📍 Found {driver.name} at {distance:.2f}km "
                      f"(radius={radius}km)")
                return driver
            radius *= 1.5  # Expand search radius

        return None


class BatchedGeoRadiusMatching(DriverMatchingStrategy):
    """
    Batched matching: collects ride requests for a short window
    and runs global optimization for optimal assignments.
    Used in high-density areas for fleet efficiency.
    """

    def __init__(self, batch_window_ms: int = 2000):
        self._batch_window_ms = batch_window_ms
        self._pending_requests: List[Tuple[Location, CabType, Callable]] = []

    def find_driver(self, pickup: Location, cab_type: CabType,
                    drivers: List[Driver],
                    geo_index: Optional[GeoIndex] = None) -> Optional[Driver]:
        if not geo_index:
            return None

        # For batched matching, find top 3 candidates
        results = geo_index.geo_radius_search(pickup, 5.0, cab_type, 3)
        if not results:
            return None

        # Pick the closest (simplified; real impl would optimize globally)
        return results[0][0]


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

    def __str__(self) -> str:
        return f"Trip[{self._trip_id[:8]}]: {self._rider.name} -> {self._driver.name} (${self._fare:.2f})"


# --- Cab Booking Service (Facade with Geo/Kafka Integration) ---

class CabBookingService:
    def __init__(self):
        self._riders: Dict[str, Rider] = {}
        self._drivers: Dict[str, Driver] = {}
        self._trips: Dict[str, Trip] = {}
        self._matching_strategy: DriverMatchingStrategy = NearestDriverMatching()

        # Geo-spatial infrastructure
        self._geo_index = GeoIndex()
        self._kafka_broker: Optional[KafkaBroker] = None
        self._zone_manager: Optional[ZoneManager] = None
        self._gps_processor: Optional[GPSLocationStreamProcessor] = None
        self._zone_analytics: Optional[ZoneAnalyticsAggregator] = None

    # ---- Infrastructure Setup ----

    def setup_geo_kafka_infrastructure(self, city_center: Location = Location(19.0760, 72.8777)) -> None:
        """Initialize GeoIndex, Kafka broker, Zone manager, and stream processors."""
        # Kafka
        self._kafka_broker = KafkaBroker()
        self._kafka_broker.create_topic("gps.raw.updates", partitions=5)
        self._kafka_broker.create_topic("gps.enriched.locations", partitions=5)
        self._kafka_broker.create_topic("gps.zone.driver_counts", partitions=3)
        self._kafka_broker.create_topic("gps.dlq", partitions=1)
        self._kafka_broker.create_topic("trip.events", partitions=3)

        # Zone management
        self._zone_manager = ZoneManager(city_center, grid_radius_km=10.0, zone_radius_km=0.5)
        self._zone_manager.create_hexagonal_grid()

        # Stream processors
        self._gps_processor = GPSLocationStreamProcessor(
            self._kafka_broker, self._geo_index, self._zone_manager
        )
        self._zone_analytics = ZoneAnalyticsAggregator(
            self._kafka_broker, self._zone_manager
        )

    @property
    def geo_index(self) -> Optional[GeoIndex]:
        return self._geo_index

    @property
    def kafka_broker(self) -> Optional[KafkaBroker]:
        return self._kafka_broker

    @property
    def zone_manager(self) -> Optional[ZoneManager]:
        return self._zone_manager

    # ---- Rider/Driver Registration ----

    def register_rider(self, name: str, phone: str) -> Rider:
        rider_id = f"R-{uuid.uuid4().hex[:6].upper()}"
        rider = Rider(rider_id, name, phone)
        self._riders[rider_id] = rider
        return rider

    def register_driver(self, name: str, phone: str, license_num: str, cab_type: CabType) -> Driver:
        driver_id = f"D-{uuid.uuid4().hex[:6].upper()}"
        driver = Driver(driver_id, name, phone, license_num, cab_type)
        self._drivers[driver_id] = driver

        # Register in geo index
        self._geo_index.add_driver(driver)

        return driver

    # ---- Location Update via Kafka ----

    def update_driver_location(self, driver_id: str, location: Location,
                                speed_kmh: float = 0, heading: int = 0) -> None:
        """
        Simulate driver location update flowing through Kafka.
        In production, this would be:
          1. Driver app sends GPS via WebSocket
          2. WebSocket gateway publishes to Kafka topic 'gps.raw.updates'
          3. Stream processor (this service) consumes and enriches
          4. Enriched data goes to Redis Geo for queries
        """
        # Update in-memory driver
        driver = self._drivers.get(driver_id)
        if not driver:
            return
        driver.current_location = location

        # If Kafka infrastructure is set up, simulate the pipeline
        if self._kafka_broker:
            # 1. Produce raw GPS event to Kafka
            raw_event = {
                "driver_id": driver_id,
                "lat": location.lat,
                "lng": location.lng,
                "speed_kmh": speed_kmh,
                "heading": heading,
                "timestamp": datetime.now().isoformat()
            }
            self._kafka_broker.produce("gps.raw.updates", driver_id, raw_event)

            # 2. Process batch (simulate stream processor consuming)
            if self._gps_processor:
                self._gps_processor.process_batch(10)
        else:
            # Direct update to geo index
            self._geo_index.update_location(driver_id, location)

    # ---- Matching Strategy ----

    def set_matching_strategy(self, strategy: DriverMatchingStrategy) -> None:
        self._matching_strategy = strategy

    # ---- Ride Request ----

    def request_ride(self, rider_id: str, pickup: Location, dropoff: Location,
                     cab_type: CabType = CabType.MINI) -> Optional[Trip]:
        rider = self._riders.get(rider_id)
        if not rider:
            print(f"  Rider {rider_id} not found")
            return None

        # Record ride request for zone analytics
        if self._zone_analytics:
            self._zone_analytics.record_ride_request(pickup)

        # Find driver using geo-indexed strategy
        driver = self._matching_strategy.find_driver(
            pickup, cab_type,
            list(self._drivers.values()),
            self._geo_index
        )
        if not driver:
            print(f"  No {cab_type.value} available nearby")
            return None

        # Calculate fare
        distance = pickup.distance_to(dropoff)
        est_duration = distance / 30 * 60  # Assume 30 km/h average

        # Check zone surge multiplier
        surge = 1.0
        if self._zone_manager:
            zone = self._zone_manager.get_zone_for_location(pickup)
            if zone:
                surge = zone.surge_multiplier
                print(f"  ⚡ Zone surge: {surge:.2f}x")

        pricing = SurgePricing(StandardPricing(cab_type), surge)
        fare = pricing.calculate_fare(distance, est_duration)

        trip_id = f"T-{uuid.uuid4().hex[:8].upper()}"
        trip = Trip(trip_id, rider, driver, pickup, dropoff, fare)
        trip.status = TripStatus.ACCEPTED
        driver.status = CabStatus.BOOKED

        self._trips[trip_id] = trip

        # Publish trip event to Kafka
        if self._kafka_broker:
            trip_event = {
                "trip_id": trip_id,
                "rider_id": rider_id,
                "driver_id": driver.driver_id,
                "pickup": pickup.to_dict(),
                "dropoff": dropoff.to_dict(),
                "fare": fare,
                "surge_multiplier": surge,
                "status": "ACCEPTED",
                "timestamp": datetime.now().isoformat()
            }
            self._kafka_broker.produce("trip.events", trip_id, trip_event)

        print(f"  ✅ Trip created! {driver.name} ({cab_type.value}) arriving in ~{pickup.distance_to(driver.current_location) / 30 * 60:.0f} min")
        print(f"  💰 Estimated fare: ${fare:.2f}")
        return trip

    def start_trip(self, trip_id: str) -> None:
        trip = self._trips.get(trip_id)
        if trip and trip.status == TripStatus.ACCEPTED:
            trip.start()
            trip.driver.status = CabStatus.ON_TRIP
            print(f"  🚗 Trip {trip_id[:8]} started!")

    def complete_trip(self, trip_id: str) -> Optional[float]:
        trip = self._trips.get(trip_id)
        if trip and trip.status == TripStatus.STARTED:
            fare = trip.complete()
            print(f"  ✅ Trip completed! Fare: ${fare:.2f}")
            return fare
        return None

    def cancel_trip(self, trip_id: str) -> None:
        trip = self._trips.get(trip_id)
        if trip:
            trip.cancel()
            print(f"  ❌ Trip {trip_id[:8]} cancelled")


# --- Demo ---

def demo():
    print("=== Cab Booking Service (Uber) ===")
    print("=" * 50)

    cab = CabBookingService()

    # Register riders and drivers
    rider = cab.register_rider("Alice", "9876543210")
    print(f"\nRider: {rider}")

    drivers_data = [
        ("Bob", "Driver", "LIC001", CabType.MINI, Location(19.0760, 72.8777)),
        ("Charlie", "Driver", "LIC002", CabType.SEDAN, Location(19.0800, 72.8800)),
        ("Diana", "Driver", "LIC003", CabType.SUV, Location(19.0700, 72.8700)),
    ]

    for name, _, lic, cab_type, loc in drivers_data:
        driver = cab.register_driver(name, f"{len(cab._drivers)}-{random.randint(100,999)}", lic, cab_type)
        cab.update_driver_location(driver.driver_id, loc)
        print(f"  Driver: {driver} at {loc}")

    # Request a ride
    print("\n--- Requesting Ride ---")
    pickup = Location(19.0780, 72.8780)
    dropoff = Location(19.1000, 72.9000)

    trip = cab.request_ride(rider.rider_id, pickup, dropoff, CabType.MINI)

    if trip:
        cab.start_trip(trip.trip_id)
        cab.complete_trip(trip.trip_id)

    # Request with surge pricing
    print("\n--- Request with Surge Pricing ---")
    cab.set_matching_strategy(HighestRatedDriverMatching())
    trip2 = cab.request_ride(rider.rider_id, pickup, dropoff, CabType.SUV)

    # --- Demo: GeoRadius + Kafka + Zone Infrastructure ---
    print("\n" + "=" * 50)
    print("=== GeoRadius + Kafka + Zone Management Demo ===")
    print("=" * 50)

    # Initialize full infrastructure
    cab2 = CabBookingService()
    mumbai_center = Location(19.0760, 72.8777)
    cab2.setup_geo_kafka_infrastructure(mumbai_center)

    # Register riders and drivers
    rider2 = cab2.register_rider("Bob", "9876543211")
    print(f"\nRider: {rider2}")

    # Register 20 drivers spread across the city
    print("\n--- Registering 20 Drivers Across City ---")
    for i in range(20):
        # Spread drivers in a grid around the center
        lat = mumbai_center.lat + random.uniform(-0.05, 0.05)
        lng = mumbai_center.lng + random.uniform(-0.05, 0.05)
        cab_types = [CabType.MINI, CabType.SEDAN, CabType.SUV, CabType.PREMIUM]
        cab_type = cab_types[i % 4]

        driver = cab2.register_driver(
            f"Driver-{i+1}", f"9999{i:02d}", f"LIC{i:04d}", cab_type
        )
        loc = Location(lat, lng)

        # Update location through Kafka pipeline
        cab2.update_driver_location(driver.driver_id, loc,
                                     speed_kmh=random.uniform(0, 60),
                                     heading=random.randint(0, 359))

    # Update zone driver counts
    if cab2._zone_analytics and cab2._gps_processor:
        cab2._zone_analytics.aggregate(50)

    # Show zone stats
    print("\n--- Zone Statistics ---")
    if cab2.zone_manager:
        for zone in cab2.zone_manager.zones[:5]:  # Show first 5 zones
            print(f"  {zone}")
        print(f"  ... and {len(cab2.zone_manager.zones) - 5} more zones")

    # Use GeoRadius matching
    print("\n--- GeoRadius Driver Matching ---")
    cab2.set_matching_strategy(GeoRadiusDriverMatching(initial_radius_km=2.0))
    pickup2 = Location(19.0780, 72.8780)
    dropoff2 = Location(19.1000, 72.9000)

    trip3 = cab2.request_ride(rider2.rider_id, pickup2, dropoff2, CabType.SEDAN)
    if trip3:
        print(f"  📋 Matched with: {trip3.driver.name} (${trip3._fare:.2f})")

    # Show Kafka broker stats
    print("\n--- Kafka Event Stats ---")
    if cab2._gps_processor:
        print(f"  📊 GPS events processed: {cab2._gps_processor.total_processed}")
    if cab2.kafka_broker:
        raw_topic = cab2.kafka_broker.get_topic("gps.raw.updates")
        enriched_topic = cab2.kafka_broker.get_topic("gps.enriched.locations")
        if raw_topic:
            print(f"  📨 Raw GPS events: {len(raw_topic._messages)}")
        if enriched_topic:
            print(f"  📨 Enriched events: {len(enriched_topic._messages)}")


if __name__ == "__main__":
    demo()
