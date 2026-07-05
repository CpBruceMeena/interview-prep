"""
Cab Booking Service (Uber/Ola) - Low Level Design
----------------------------------------------------
Design Principles: SOLID, Strategy Pattern, Observer Pattern
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import math
import uuid
import random


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


# --- Driver Matching Strategy ---

class DriverMatchingStrategy(ABC):
    @abstractmethod
    def find_driver(self, pickup: Location, cab_type: CabType,
                    drivers: List[Driver]) -> Optional[Driver]:
        pass


class NearestDriverMatching(DriverMatchingStrategy):
    def find_driver(self, pickup: Location, cab_type: CabType,
                    drivers: List[Driver]) -> Optional[Driver]:
        available = [d for d in drivers if d.is_available() and d.cab_type == cab_type and d.current_location]
        if not available:
            return None
        return min(available, key=lambda d: d.current_location.distance_to(pickup))


class HighestRatedDriverMatching(DriverMatchingStrategy):
    def find_driver(self, pickup: Location, cab_type: CabType,
                    drivers: List[Driver]) -> Optional[Driver]:
        available = [d for d in drivers if d.is_available() and d.cab_type == cab_type]
        if not available:
            return None
        return max(available, key=lambda d: d.rating)


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


# --- Cab Booking Service (Facade) ---

class CabBookingService:
    def __init__(self):
        self._riders: Dict[str, Rider] = {}
        self._drivers: Dict[str, Driver] = {}
        self._trips: Dict[str, Trip] = {}
        self._matching_strategy: DriverMatchingStrategy = NearestDriverMatching()

    def register_rider(self, name: str, phone: str) -> Rider:
        rider_id = f"R-{uuid.uuid4().hex[:6].upper()}"
        rider = Rider(rider_id, name, phone)
        self._riders[rider_id] = rider
        return rider

    def register_driver(self, name: str, phone: str, license_num: str, cab_type: CabType) -> Driver:
        driver_id = f"D-{uuid.uuid4().hex[:6].upper()}"
        driver = Driver(driver_id, name, phone, license_num, cab_type)
        self._drivers[driver_id] = driver
        return driver

    def update_driver_location(self, driver_id: str, location: Location) -> None:
        driver = self._drivers.get(driver_id)
        if driver:
            driver.current_location = location

    def set_matching_strategy(self, strategy: DriverMatchingStrategy) -> None:
        self._matching_strategy = strategy

    def request_ride(self, rider_id: str, pickup: Location, dropoff: Location,
                     cab_type: CabType = CabType.MINI) -> Optional[Trip]:
        rider = self._riders.get(rider_id)
        if not rider:
            print(f"  Rider {rider_id} not found")
            return None

        driver = self._matching_strategy.find_driver(pickup, cab_type, list(self._drivers.values()))
        if not driver:
            print(f"  No {cab_type.value} available nearby")
            return None

        # Calculate fare
        distance = pickup.distance_to(dropoff)
        est_duration = distance / 30 * 60  # Assume 30 km/h average
        pricing = StandardPricing(cab_type)
        fare = pricing.calculate_fare(distance, est_duration)

        trip_id = f"T-{uuid.uuid4().hex[:8].upper()}"
        trip = Trip(trip_id, rider, driver, pickup, dropoff, fare)
        trip.status = TripStatus.ACCEPTED
        driver.status = CabStatus.BOOKED

        self._trips[trip_id] = trip
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


if __name__ == "__main__":
    demo()
