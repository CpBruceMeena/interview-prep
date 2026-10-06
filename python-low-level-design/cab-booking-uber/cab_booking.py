"""
Cab Booking Service (Uber/Ola) - Low Level Design
-------------------------------------------------
Core flows : register riders/drivers, stream driver GPS, request a ride, match a
             nearby driver, run the trip state machine, price with zone surge.
Patterns   : Strategy (pricing, driver ranking), Decorator (surge on top of base
             fare), State machine (Trip), Facade (CabBookingService).
Concurrency: a driver is claimed with a compare-and-set under the driver's own
             lock, so two concurrent requests can never book the same driver.
             Trip transitions are validated under the trip's lock, so "rider
             cancels" racing "driver starts" has exactly one winner.
             Lock order is always trip -> driver (driver locks are leaves).
Infra sims : GeoIndex (Redis GEO), KafkaBroker (topics/partitions/offsets),
             geohash-cell zones for surge. Stdlib only, Python 3.10+.
"""

from __future__ import annotations

import bisect
import itertools
import math
import random
import threading
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

MONEY = Decimal("0.01")


def to_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


# ============================================================
# Enums, errors, value objects
# ============================================================

class CabStatus(Enum):
    AVAILABLE = "Available"   # online and matchable
    BOOKED = "Booked"         # claimed for a trip (offered or accepted), not yet driving it
    ON_TRIP = "On Trip"       # rider on board
    OFFLINE = "Offline"


class TripStatus(Enum):
    REQUESTED = "Requested"            # driver reserved, offer pending
    ACCEPTED = "Accepted"              # driver accepted, en route to pickup
    DRIVER_ARRIVED = "Driver Arrived"
    STARTED = "Started"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class CabType(Enum):
    MINI = "Mini"
    SEDAN = "Sedan"
    SUV = "SUV"
    PREMIUM = "Premium"
    AUTO = "Auto"


class BookingError(Exception):
    """Base class for domain errors."""


class NotFoundError(BookingError):
    pass


class NoDriverAvailableError(BookingError):
    pass


class RiderBusyError(BookingError):
    pass


class InvalidTransitionError(BookingError):
    pass


@dataclass(frozen=True)
class Location:
    lat: float
    lng: float

    def __post_init__(self) -> None:
        if not (-90 <= self.lat <= 90 and -180 <= self.lng <= 180):
            raise ValueError(f"invalid coordinates {self.lat}, {self.lng}")

    def distance_to(self, other: Location) -> float:
        """Great-circle (haversine) distance in km."""
        r = 6371.0
        d_lat = math.radians(other.lat - self.lat)
        d_lng = math.radians(other.lng - self.lng)
        a = (math.sin(d_lat / 2) ** 2
             + math.cos(math.radians(self.lat)) * math.cos(math.radians(other.lat))
             * math.sin(d_lng / 2) ** 2)
        return 2 * r * math.asin(math.sqrt(min(1.0, a)))

    def to_dict(self) -> dict:
        return {"lat": self.lat, "lng": self.lng}

    def __str__(self) -> str:
        return f"({self.lat:.4f}, {self.lng:.4f})"


# ============================================================
# Rider & Driver
# ============================================================

class Rider:
    def __init__(self, rider_id: str, name: str, phone: str):
        self.rider_id = rider_id
        self.name = name
        self.phone = phone

    def __str__(self) -> str:
        return f"{self.name} ({self.phone})"


class Driver:
    """Driver status changes only via compare-and-set under self._lock."""

    def __init__(self, driver_id: str, name: str, phone: str,
                 license_number: str, cab_type: CabType):
        self.driver_id = driver_id
        self.name = name
        self.phone = phone
        self.license_number = license_number
        self.cab_type = cab_type
        self._status = CabStatus.AVAILABLE
        self._rating = 5.0
        self._rated_trips = 0
        self._lock = threading.Lock()

    @property
    def status(self) -> CabStatus:
        return self._status

    @property
    def rating(self) -> float:
        return self._rating

    def is_available(self) -> bool:
        return self._status is CabStatus.AVAILABLE

    def compare_and_set(self, expected: CabStatus, new: CabStatus) -> bool:
        with self._lock:
            if self._status is not expected:
                return False
            self._status = new
            return True

    def try_claim(self) -> bool:
        """AVAILABLE -> BOOKED atomically. False means someone else got them first."""
        return self.compare_and_set(CabStatus.AVAILABLE, CabStatus.BOOKED)

    def _force_status(self, new: CabStatus) -> None:
        # Only called by Trip while it holds the trip lock and owns this driver.
        with self._lock:
            self._status = new

    def add_rating(self, stars: float) -> None:
        if not 1 <= stars <= 5:
            raise ValueError("rating must be between 1 and 5")
        with self._lock:
            self._rating = (self._rating * self._rated_trips + stars) / (self._rated_trips + 1)
            self._rated_trips += 1

    def __str__(self) -> str:
        return f"{self.name} ({self.cab_type.value})"


# ============================================================
# Pricing (Strategy + Decorator), money as Decimal
# ============================================================

class PricingStrategy(ABC):
    @abstractmethod
    def calculate_fare(self, distance_km: float, duration_min: float) -> Decimal:
        ...


@dataclass(frozen=True)
class RateCard:
    base: Decimal
    per_km: Decimal
    per_min: Decimal


RATE_CARDS: Dict[CabType, RateCard] = {
    CabType.AUTO: RateCard(Decimal("25"), Decimal("8"), Decimal("0.5")),
    CabType.MINI: RateCard(Decimal("50"), Decimal("10"), Decimal("1")),
    CabType.SEDAN: RateCard(Decimal("80"), Decimal("14"), Decimal("1.5")),
    CabType.SUV: RateCard(Decimal("120"), Decimal("18"), Decimal("2")),
    CabType.PREMIUM: RateCard(Decimal("150"), Decimal("22"), Decimal("2.5")),
}


class StandardPricing(PricingStrategy):
    def __init__(self, cab_type: CabType):
        self._card = RATE_CARDS[cab_type]

    def calculate_fare(self, distance_km: float, duration_min: float) -> Decimal:
        km = Decimal(str(round(distance_km, 3)))
        mins = Decimal(str(round(duration_min, 2)))
        return to_money(self._card.base + self._card.per_km * km + self._card.per_min * mins)


class SurgePricing(PricingStrategy):
    """Decorator: multiplies whatever the wrapped strategy charges."""

    def __init__(self, base: PricingStrategy, multiplier: Decimal):
        if multiplier < 1:
            raise ValueError("surge multiplier must be >= 1")
        self._base = base
        self._multiplier = multiplier

    def calculate_fare(self, distance_km: float, duration_min: float) -> Decimal:
        return to_money(self._base.calculate_fare(distance_km, duration_min) * self._multiplier)


# ============================================================
# Geohash + GeoIndex (in-memory stand-in for Redis GEO)
# ============================================================

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash_encode(lat: float, lng: float, precision: int) -> str:
    lat_rng, lng_rng = [-90.0, 90.0], [-180.0, 180.0]
    chars, ch, bit, even = [], 0, 0, True
    while len(chars) < precision:
        rng, val = (lng_rng, lng) if even else (lat_rng, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch |= 1 << (4 - bit)
            rng[0] = mid
        else:
            rng[1] = mid
        even = not even
        bit += 1
        if bit == 5:
            chars.append(_BASE32[ch])
            ch, bit = 0, 0
    return "".join(chars)


def geohash_bbox(gh: str) -> Tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lng, max_lng) of a geohash cell."""
    lat_rng, lng_rng = [-90.0, 90.0], [-180.0, 180.0]
    even = True
    for c in gh:
        v = _BASE32.index(c)
        for b in range(4, -1, -1):
            rng = lng_rng if even else lat_rng
            mid = (rng[0] + rng[1]) / 2
            if (v >> b) & 1:
                rng[0] = mid
            else:
                rng[1] = mid
            even = not even
    return lat_rng[0], lat_rng[1], lng_rng[0], lng_rng[1]


def geohash_cell_km(precision: int, at_lat: float) -> Tuple[float, float]:
    """(height_km, width_km) of a cell. Precision 5 ~ 4.9x4.9 km, 6 ~ 0.61x1.2 km, 7 ~ 153x153 m."""
    bits = 5 * precision
    lng_bits, lat_bits = (bits + 1) // 2, bits // 2
    height = 180 / (1 << lat_bits) * 111.32
    width = 360 / (1 << lng_bits) * 111.32 * math.cos(math.radians(at_lat))
    return height, width


def geohash_neighbourhood(gh: str) -> List[str]:
    """The cell itself plus its 8 neighbours (wraps at the antimeridian, clips at the poles)."""
    min_lat, max_lat, min_lng, max_lng = geohash_bbox(gh)
    h, w = max_lat - min_lat, max_lng - min_lng
    c_lat, c_lng = (min_lat + max_lat) / 2, (min_lng + max_lng) / 2
    cells = []
    for dy in (-1, 0, 1):
        lat = c_lat + dy * h
        if not -90 < lat < 90:
            continue
        for dx in (-1, 0, 1):
            lng = (c_lng + dx * w + 180) % 360 - 180
            cells.append(geohash_encode(lat, lng, len(gh)))
    return list(dict.fromkeys(cells))


class GeoIndex:
    """
    Mirrors how Redis GEO works: members live in ONE sorted structure ordered by
    geohash, and a radius query is a handful of range scans (the 3x3 cells at a
    precision whose cell is at least `radius` wide) followed by an exact
    haversine filter. Query cost is O(9 log N + M) for M points in those cells.
    (Redis uses a skiplist, so inserts are O(log N); this sorted list is O(N)
    per insert, which is fine for a simulation.)

    It stores driver ids only; availability and cab type are the caller's
    concern, just as with a Redis key. Updates carry a timestamp and older
    updates are ignored, so out-of-order or replayed GPS events are harmless.
    """

    PRECISION = 7

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sorted: List[Tuple[str, str]] = []                    # (geohash, driver_id)
        self._pos: Dict[str, Tuple[str, Location, float]] = {}      # driver_id -> (hash, loc, ts)

    def upsert(self, driver_id: str, location: Location, ts: float) -> bool:
        """Returns False (and changes nothing) if ts is older than the indexed position."""
        new_hash = geohash_encode(location.lat, location.lng, self.PRECISION)
        with self._lock:
            old = self._pos.get(driver_id)
            if old is not None:
                if ts < old[2]:
                    return False
                self._remove_entry(old[0], driver_id)
            bisect.insort(self._sorted, (new_hash, driver_id))
            self._pos[driver_id] = (new_hash, location, ts)
            return True

    def remove(self, driver_id: str) -> None:
        with self._lock:
            old = self._pos.pop(driver_id, None)
            if old is not None:
                self._remove_entry(old[0], driver_id)

    def location_of(self, driver_id: str) -> Optional[Location]:
        with self._lock:
            entry = self._pos.get(driver_id)
            return entry[1] if entry else None

    def search(self, center: Location, radius_km: float) -> List[Tuple[str, float]]:
        """All (driver_id, distance_km) within radius, nearest first."""
        precision = self._precision_for(radius_km, center.lat)
        cells = geohash_neighbourhood(geohash_encode(center.lat, center.lng, precision))
        hits: List[Tuple[str, float]] = []
        with self._lock:
            for prefix in cells:
                lo = bisect.bisect_left(self._sorted, (prefix, ""))
                hi = bisect.bisect_left(self._sorted, (prefix + "~", ""))  # '~' sorts after base32
                for _, driver_id in self._sorted[lo:hi]:
                    d = center.distance_to(self._pos[driver_id][1])
                    if d <= radius_km:
                        hits.append((driver_id, d))
        hits.sort(key=lambda h: (h[1], h[0]))
        return hits

    def __len__(self) -> int:
        return len(self._pos)

    def _remove_entry(self, gh: str, driver_id: str) -> None:
        i = bisect.bisect_left(self._sorted, (gh, driver_id))
        if i < len(self._sorted) and self._sorted[i] == (gh, driver_id):
            del self._sorted[i]

    def _precision_for(self, radius_km: float, lat: float) -> int:
        for p in range(self.PRECISION, 0, -1):
            h, w = geohash_cell_km(p, lat)
            if h >= radius_km and w >= radius_km:
                return p
        return 1


# ============================================================
# Kafka simulation: partitioned append-only logs + committed offsets
# ============================================================

@dataclass(frozen=True)
class KafkaMessage:
    topic: str
    partition: int
    offset: int
    key: str
    value: dict


class KafkaBroker:
    """
    Keyed messages go to partition crc32(key) % n, so one driver's events stay
    ordered. Consumers poll per (group, topic, partition) offset and commit
    AFTER processing (at-least-once): a crash between processing and commit
    replays the message, which is why consumers must be idempotent.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._topics: Dict[str, List[List[KafkaMessage]]] = {}
        self._committed: Dict[Tuple[str, str, int], int] = {}

    def create_topic(self, name: str, partitions: int = 3) -> None:
        with self._lock:
            self._topics.setdefault(name, [[] for _ in range(partitions)])

    def produce(self, topic: str, key: str, value: dict) -> KafkaMessage:
        with self._lock:
            parts = self._topics.get(topic)
            if parts is None:
                raise NotFoundError(f"topic {topic} does not exist")
            p = zlib.crc32(key.encode()) % len(parts)
            msg = KafkaMessage(topic, p, len(parts[p]), key, value)
            parts[p].append(msg)
            return msg

    def poll(self, topic: str, group: str, max_messages: int = 100) -> List[KafkaMessage]:
        with self._lock:
            out: List[KafkaMessage] = []
            for p, log in enumerate(self._topics.get(topic, [])):
                start = self._committed.get((group, topic, p), 0)
                out.extend(log[start:start + max_messages - len(out)])
                if len(out) >= max_messages:
                    break
            return out

    def commit(self, group: str, msg: KafkaMessage) -> None:
        with self._lock:
            key = (group, msg.topic, msg.partition)
            self._committed[key] = max(self._committed.get(key, 0), msg.offset + 1)

    def topic_size(self, topic: str) -> int:
        with self._lock:
            return sum(len(log) for log in self._topics.get(topic, []))


# ============================================================
# Zones & surge (geohash-6 cells stand in for H3 hexagons)
# ============================================================

def compute_surge(demand: int, supply: int) -> Decimal:
    """Step function on demand/supply. No demand -> no surge, whatever the supply."""
    if demand == 0:
        return Decimal("1.0")
    if supply == 0:
        return Decimal("2.5")
    ratio = demand / supply
    if ratio > 3.0:
        return Decimal("2.0")
    if ratio > 2.0:
        return Decimal("1.5")
    if ratio > 1.5:
        return Decimal("1.25")
    return Decimal("1.0")


@dataclass
class Zone:
    zone_id: str
    center: Location
    driver_count: int = 0
    ride_request_count: int = 0
    surge_multiplier: Decimal = Decimal("1.0")

    def update_supply_demand(self, driver_count: int, ride_requests: int) -> None:
        self.driver_count = driver_count
        self.ride_request_count = ride_requests
        self.surge_multiplier = compute_surge(ride_requests, driver_count)

    def __str__(self) -> str:
        return (f"Zone[{self.zone_id}]: {self.driver_count} drivers, "
                f"{self.ride_request_count} requests, surge={self.surge_multiplier}x")


class ZoneManager:
    """Point -> zone is O(1): the zone id IS the geohash cell. Zones are created lazily."""

    PRECISION = 6  # ~0.6 km x 1.2 km cells

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._zones: Dict[str, Zone] = {}

    def zone_for(self, location: Location) -> Zone:
        zone_id = geohash_encode(location.lat, location.lng, self.PRECISION)
        with self._lock:
            zone = self._zones.get(zone_id)
            if zone is None:
                min_lat, max_lat, min_lng, max_lng = geohash_bbox(zone_id)
                zone = Zone(zone_id, Location((min_lat + max_lat) / 2, (min_lng + max_lng) / 2))
                self._zones[zone_id] = zone
            return zone

    def get_zone(self, zone_id: str) -> Optional[Zone]:
        with self._lock:
            return self._zones.get(zone_id)

    @property
    def zones(self) -> List[Zone]:
        with self._lock:
            return sorted(self._zones.values(), key=lambda z: z.zone_id)


# ============================================================
# Stream processors (Kafka consumers)
# ============================================================

GPS_RAW = "gps.raw.updates"
GPS_ENRICHED = "gps.enriched.locations"
ZONE_COUNTS = "gps.zone.driver_counts"
GPS_DLQ = "gps.dlq"
TRIP_EVENTS = "trip.events"


class GPSLocationStreamProcessor:
    """gps.raw.updates -> validate -> GeoIndex upsert -> enrich with zone -> gps.enriched.locations."""

    GROUP = "gps-stream-processor"

    def __init__(self, broker: KafkaBroker, geo_index: GeoIndex, zones: ZoneManager):
        self._broker = broker
        self._geo = geo_index
        self._zones = zones
        self._lock = threading.Lock()  # one consumer instance processes its partitions serially
        self.total_processed = 0

    def poll(self, max_messages: int = 100) -> int:
        with self._lock:
            processed = 0
            for msg in self._broker.poll(GPS_RAW, self.GROUP, max_messages):
                try:
                    v = msg.value
                    location = Location(float(v["lat"]), float(v["lng"]))
                    if self._geo.upsert(v["driver_id"], location, float(v["ts"])):
                        zone = self._zones.zone_for(location)
                        self._broker.produce(GPS_ENRICHED, v["driver_id"], {
                            "driver_id": v["driver_id"], "location": location.to_dict(),
                            "zone_id": zone.zone_id, "speed_kmh": v.get("speed_kmh", 0),
                            "heading": v.get("heading", 0), "ts": v["ts"]})
                    processed += 1
                except (KeyError, TypeError, ValueError) as e:
                    self._broker.produce(GPS_DLQ, msg.key, {"error": repr(e), "original": msg.value})
                self._broker.commit(self.GROUP, msg)  # commit after handling: at-least-once
            self.total_processed += processed
            return processed


class ZoneAnalyticsAggregator:
    """
    Supply = AVAILABLE drivers whose latest position is in the zone (a driver
    who moves is counted once, in their current zone). Demand = ride requests
    in the current window. aggregate() closes the window (tumbling).
    """

    GROUP = "zone-analytics"

    def __init__(self, broker: KafkaBroker, zones: ZoneManager,
                 is_available: Callable[[str], bool]):
        self._broker = broker
        self._zones = zones
        self._is_available = is_available
        self._lock = threading.Lock()
        self._driver_zone: Dict[str, str] = {}
        self._requests: Dict[str, int] = {}

    def record_ride_request(self, pickup: Location) -> None:
        zone_id = self._zones.zone_for(pickup).zone_id
        with self._lock:
            self._requests[zone_id] = self._requests.get(zone_id, 0) + 1

    def aggregate(self) -> List[Zone]:
        with self._lock:
            for msg in self._broker.poll(GPS_ENRICHED, self.GROUP, max_messages=10_000):
                self._driver_zone[msg.value["driver_id"]] = msg.value["zone_id"]
                self._broker.commit(self.GROUP, msg)
            supply: Dict[str, int] = {}
            for driver_id, zone_id in self._driver_zone.items():
                if self._is_available(driver_id):
                    supply[zone_id] = supply.get(zone_id, 0) + 1
            for zone in self._zones.zones:
                zone.update_supply_demand(supply.get(zone.zone_id, 0),
                                          self._requests.get(zone.zone_id, 0))
                self._broker.produce(ZONE_COUNTS, zone.zone_id, {
                    "zone_id": zone.zone_id, "driver_count": zone.driver_count,
                    "ride_requests": zone.ride_request_count,
                    "surge_multiplier": str(zone.surge_multiplier)})
            self._requests.clear()
            return self._zones.zones


# ============================================================
# Driver matching: strategies RANK candidates; the service CLAIMS
# ============================================================

class DriverMatchingStrategy(ABC):
    """Pure ranking: given eligible (driver, distance_km) pairs, return them best first."""

    @abstractmethod
    def rank(self, pickup: Location, candidates: List[Tuple[Driver, float]]) -> List[Driver]:
        ...


class NearestDriverMatching(DriverMatchingStrategy):
    def rank(self, pickup: Location, candidates: List[Tuple[Driver, float]]) -> List[Driver]:
        return [d for d, _ in sorted(candidates, key=lambda c: (c[1], c[0].driver_id))]


class HighestRatedDriverMatching(DriverMatchingStrategy):
    """Best rating inside the search radius; distance breaks ties."""

    def rank(self, pickup: Location, candidates: List[Tuple[Driver, float]]) -> List[Driver]:
        return [d for d, _ in sorted(candidates, key=lambda c: (-c[0].rating, c[1]))]


# ============================================================
# Trip: the state machine. Owns its driver's status while active.
# ============================================================

_TRANSITIONS: Dict[TripStatus, Set[TripStatus]] = {
    TripStatus.REQUESTED: {TripStatus.ACCEPTED, TripStatus.CANCELLED},
    TripStatus.ACCEPTED: {TripStatus.DRIVER_ARRIVED, TripStatus.CANCELLED},
    TripStatus.DRIVER_ARRIVED: {TripStatus.STARTED, TripStatus.CANCELLED},
    TripStatus.STARTED: {TripStatus.COMPLETED},
    TripStatus.COMPLETED: set(),
    TripStatus.CANCELLED: set(),
}

TERMINAL = {TripStatus.COMPLETED, TripStatus.CANCELLED}


@dataclass
class Trip:
    trip_id: str
    rider: Rider
    driver: Driver
    pickup: Location
    dropoff: Location
    cab_type: CabType
    fare: Decimal
    surge_multiplier: Decimal
    status: TripStatus = TripStatus.REQUESTED
    cancel_reason: Optional[str] = None
    declined_by: Set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # Callers hold self.lock for every method below.
    def _move(self, target: TripStatus) -> None:
        if target not in _TRANSITIONS[self.status]:
            raise InvalidTransitionError(f"{self.trip_id}: {self.status.name} -> {target.name}")
        self.status = target

    def accept(self) -> None:
        self._move(TripStatus.ACCEPTED)

    def arrive(self) -> None:
        self._move(TripStatus.DRIVER_ARRIVED)

    def start(self) -> None:
        self._move(TripStatus.STARTED)
        self.driver._force_status(CabStatus.ON_TRIP)

    def complete(self) -> Decimal:
        self._move(TripStatus.COMPLETED)
        self.driver._force_status(CabStatus.AVAILABLE)
        return self.fare

    def cancel(self, reason: str) -> None:
        self._move(TripStatus.CANCELLED)
        self.cancel_reason = reason
        self.driver._force_status(CabStatus.AVAILABLE)

    def reassign(self, new_driver: Driver) -> None:
        """Offer declined: the old driver is freed, a freshly claimed one takes the offer."""
        if self.status is not TripStatus.REQUESTED:
            raise InvalidTransitionError(f"{self.trip_id}: can only reassign a pending offer")
        self.declined_by.add(self.driver.driver_id)
        self.driver._force_status(CabStatus.AVAILABLE)
        self.driver = new_driver

    def __str__(self) -> str:
        return f"Trip[{self.trip_id}] {self.rider.name} -> {self.driver.name} {self.status.name} ({self.fare})"


# ============================================================
# Facade
# ============================================================

class CabBookingService:
    SEARCH_RADII_KM = (2.0, 5.0, 10.0)   # progressive expansion
    AVG_SPEED_KMH = 30.0

    def __init__(self, matching: Optional[DriverMatchingStrategy] = None,
                 broker: Optional[KafkaBroker] = None):
        self._lock = threading.Lock()                # guards the registries below
        self._riders: Dict[str, Rider] = {}
        self._drivers: Dict[str, Driver] = {}
        self._trips: Dict[str, Trip] = {}
        self._active_trip_by_rider: Dict[str, Optional[str]] = {}
        self._ids = itertools.count(1)
        self._matching = matching or NearestDriverMatching()

        self.geo_index = GeoIndex()
        self.zone_manager = ZoneManager()
        self.broker = broker
        self._gps: Optional[GPSLocationStreamProcessor] = None
        self.zone_analytics: Optional[ZoneAnalyticsAggregator] = None
        if broker is not None:
            for topic, parts in ((GPS_RAW, 5), (GPS_ENRICHED, 5), (ZONE_COUNTS, 3),
                                 (GPS_DLQ, 1), (TRIP_EVENTS, 3)):
                broker.create_topic(topic, parts)
            self._gps = GPSLocationStreamProcessor(broker, self.geo_index, self.zone_manager)
            self.zone_analytics = ZoneAnalyticsAggregator(
                broker, self.zone_manager,
                lambda d_id: (d := self._drivers.get(d_id)) is not None and d.is_available())

    # ---- registration / lookup ----

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids):04d}"

    def register_rider(self, name: str, phone: str) -> Rider:
        with self._lock:
            rider = Rider(self._next_id("R"), name, phone)
            self._riders[rider.rider_id] = rider
            return rider

    def register_driver(self, name: str, phone: str, license_number: str,
                        cab_type: CabType) -> Driver:
        with self._lock:
            driver = Driver(self._next_id("D"), name, phone, license_number, cab_type)
            self._drivers[driver.driver_id] = driver
            return driver

    def get_trip(self, trip_id: str) -> Trip:
        trip = self._trips.get(trip_id)
        if trip is None:
            raise NotFoundError(f"trip {trip_id}")
        return trip

    def _get_driver(self, driver_id: str) -> Driver:
        driver = self._drivers.get(driver_id)
        if driver is None:
            raise NotFoundError(f"driver {driver_id}")
        return driver

    def set_matching_strategy(self, strategy: DriverMatchingStrategy) -> None:
        self._matching = strategy

    # ---- driver presence ----

    def update_driver_location(self, driver_id: str, location: Location, ts: float,
                               speed_kmh: float = 0.0, heading: int = 0) -> None:
        """With a broker: publish to Kafka and drain the consumer (synchronously, for the sim)."""
        self._get_driver(driver_id)
        if self.broker is None or self._gps is None:
            self.geo_index.upsert(driver_id, location, ts)
            return
        self.broker.produce(GPS_RAW, driver_id, {
            "driver_id": driver_id, "lat": location.lat, "lng": location.lng,
            "speed_kmh": speed_kmh, "heading": heading, "ts": ts})
        self._gps.poll()

    def go_offline(self, driver_id: str) -> bool:
        """Only an AVAILABLE driver can go offline; a booked driver must finish first."""
        return self._get_driver(driver_id).compare_and_set(CabStatus.AVAILABLE, CabStatus.OFFLINE)

    def go_online(self, driver_id: str) -> bool:
        return self._get_driver(driver_id).compare_and_set(CabStatus.OFFLINE, CabStatus.AVAILABLE)

    # ---- matching ----

    def _claim_driver(self, pickup: Location, cab_type: CabType,
                      exclude: Iterable[str] = ()) -> Optional[Driver]:
        """
        Search -> rank -> try_claim in rank order. The search result is a stale
        snapshot, so a candidate may have been taken by a concurrent request;
        try_claim is the only authority and a failed claim just means "next".
        """
        excluded, tried = set(exclude), set()
        for radius in self.SEARCH_RADII_KM:
            candidates = []
            for driver_id, dist in self.geo_index.search(pickup, radius):
                driver = self._drivers.get(driver_id)
                if (driver is None or driver_id in excluded or driver_id in tried
                        or driver.cab_type is not cab_type or not driver.is_available()):
                    continue
                candidates.append((driver, dist))
            for driver in self._matching.rank(pickup, candidates):
                tried.add(driver.driver_id)
                if driver.try_claim():
                    return driver
        return None

    # ---- ride lifecycle ----

    def request_ride(self, rider_id: str, pickup: Location, dropoff: Location,
                     cab_type: CabType = CabType.MINI) -> Trip:
        """Claims a driver and creates a REQUESTED trip (the offer). Raises if nothing claimable."""
        with self._lock:
            rider = self._riders.get(rider_id)
            if rider is None:
                raise NotFoundError(f"rider {rider_id}")
            if rider_id in self._active_trip_by_rider:
                raise RiderBusyError(f"{rider.name} already has an active trip")
            self._active_trip_by_rider[rider_id] = None   # reserve the rider before matching
        try:
            if self.zone_analytics:
                self.zone_analytics.record_ride_request(pickup)
            driver = self._claim_driver(pickup, cab_type)
            if driver is None:
                raise NoDriverAvailableError(f"no {cab_type.value} within {self.SEARCH_RADII_KM[-1]} km")

            surge = self.zone_manager.zone_for(pickup).surge_multiplier
            distance = pickup.distance_to(dropoff)
            fare = SurgePricing(StandardPricing(cab_type), surge).calculate_fare(
                distance, distance / self.AVG_SPEED_KMH * 60)
            with self._lock:
                trip = Trip(self._next_id("T"), rider, driver, pickup, dropoff, cab_type, fare, surge)
                self._trips[trip.trip_id] = trip
                self._active_trip_by_rider[rider_id] = trip.trip_id
        except BaseException:
            with self._lock:
                self._active_trip_by_rider.pop(rider_id, None)
            raise
        self._publish(trip)
        return trip

    def accept_trip(self, trip_id: str) -> Trip:
        return self._apply(trip_id, Trip.accept)

    def decline_trip(self, trip_id: str) -> Trip:
        """Driver declines (or the offer times out): re-match, never offering the same driver twice."""
        trip = self.get_trip(trip_id)
        with trip.lock:
            if trip.status is not TripStatus.REQUESTED:
                raise InvalidTransitionError(f"{trip_id}: no pending offer to decline")
            exclude = trip.declined_by | {trip.driver.driver_id}
            replacement = self._claim_driver(trip.pickup, trip.cab_type, exclude)
            if replacement is not None:
                trip.reassign(replacement)
            else:
                trip.cancel("no driver accepted")
                self._release_rider(trip)
        self._publish(trip)
        return trip

    def driver_arrived(self, trip_id: str) -> Trip:
        return self._apply(trip_id, Trip.arrive)

    def start_trip(self, trip_id: str) -> Trip:
        return self._apply(trip_id, Trip.start)

    def complete_trip(self, trip_id: str) -> Decimal:
        trip = self._apply(trip_id, Trip.complete)
        return trip.fare

    def cancel_trip(self, trip_id: str, reason: str = "rider cancelled") -> Trip:
        return self._apply(trip_id, lambda t: t.cancel(reason))

    def rate_driver(self, trip_id: str, stars: float) -> None:
        trip = self.get_trip(trip_id)
        if trip.status is not TripStatus.COMPLETED:
            raise InvalidTransitionError("can only rate a completed trip")
        trip.driver.add_rating(stars)

    def _apply(self, trip_id: str, action: Callable[[Trip], object]) -> Trip:
        trip = self.get_trip(trip_id)
        with trip.lock:
            action(trip)
            if trip.status in TERMINAL:
                self._release_rider(trip)
        self._publish(trip)
        return trip

    def _release_rider(self, trip: Trip) -> None:
        with self._lock:
            if self._active_trip_by_rider.get(trip.rider.rider_id) == trip.trip_id:
                del self._active_trip_by_rider[trip.rider.rider_id]

    def _publish(self, trip: Trip) -> None:
        if self.broker is not None:
            self.broker.produce(TRIP_EVENTS, trip.trip_id, {
                "trip_id": trip.trip_id, "status": trip.status.name,
                "rider_id": trip.rider.rider_id, "driver_id": trip.driver.driver_id,
                "fare": str(trip.fare), "surge_multiplier": str(trip.surge_multiplier)})


# ============================================================
# Demo (deterministic)
# ============================================================

def demo() -> None:
    rng = random.Random(42)
    center = Location(19.0760, 72.8777)   # Mumbai
    svc = CabBookingService(broker=KafkaBroker())

    print("=== Cab Booking Service ===")
    alice = svc.register_rider("Alice", "9876543210")
    cab_types = [CabType.MINI, CabType.SEDAN, CabType.SUV, CabType.PREMIUM]
    for i in range(20):
        d = svc.register_driver(f"Driver-{i + 1}", f"9999{i:02d}", f"LIC{i:04d}", cab_types[i % 4])
        loc = Location(center.lat + rng.uniform(-0.03, 0.03), center.lng + rng.uniform(-0.03, 0.03))
        svc.update_driver_location(d.driver_id, loc, ts=float(i), speed_kmh=rng.uniform(0, 60))
    print(f"Indexed drivers: {len(svc.geo_index)}, GPS events published: "
          f"{svc.broker.topic_size(GPS_RAW)}")

    # Happy path with the full state machine.
    pickup, dropoff = Location(19.0780, 72.8780), Location(19.1000, 72.9000)
    trip = svc.request_ride(alice.rider_id, pickup, dropoff, CabType.SEDAN)
    print(f"Requested: {trip}")
    svc.decline_trip(trip.trip_id)
    print(f"After first driver declined: {trip} (declined_by={sorted(trip.declined_by)})")
    for step in (svc.accept_trip, svc.driver_arrived, svc.start_trip):
        step(trip.trip_id)
    print(f"Completed, fare charged: {svc.complete_trip(trip.trip_id)}")
    svc.rate_driver(trip.trip_id, 4)

    # Invalid transition is rejected.
    try:
        svc.cancel_trip(trip.trip_id)
    except InvalidTransitionError as e:
        print(f"Rejected: {e}")

    # Surge: many requests in one zone, then aggregate the window.
    for i in range(6):
        r = svc.register_rider(f"Rider-{i}", f"8000{i}")
        try:
            t = svc.request_ride(r.rider_id, pickup, dropoff, CabType.SUV)
            svc.cancel_trip(t.trip_id)
        except NoDriverAvailableError:
            pass
    svc.zone_analytics.aggregate()
    zone = svc.zone_manager.zone_for(pickup)
    print(f"Pickup {zone}")
    surged = svc.request_ride(alice.rider_id, pickup, dropoff, CabType.MINI)
    print(f"Surged trip: {surged}")
    svc.cancel_trip(surged.trip_id)

    # Concurrency: 10 riders race for the only PREMIUM driver near a remote pickup.
    lone = svc.register_driver("Lone", "7000", "LIC-P", CabType.PREMIUM)
    remote = Location(28.6139, 77.2090)  # Delhi
    svc.update_driver_location(lone.driver_id, remote, ts=100.0)
    riders = [svc.register_rider(f"Racer-{i}", f"6000{i}") for i in range(10)]
    wins: List[Trip] = []
    barrier = threading.Barrier(len(riders))

    def race(r: Rider) -> None:
        barrier.wait()
        try:
            wins.append(svc.request_ride(r.rider_id, remote, dropoff, CabType.PREMIUM))
        except NoDriverAvailableError:
            pass

    threads = [threading.Thread(target=race, args=(r,)) for r in riders]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"Concurrent requests for 1 driver -> {len(wins)} trip(s) created")
    print(f"Kafka trip events: {svc.broker.topic_size(TRIP_EVENTS)}")


if __name__ == "__main__":
    demo()
