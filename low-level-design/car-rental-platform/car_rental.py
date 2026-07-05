"""
Car Rental Platform - Low Level Design
-----------------------------------------
Design Principles: SOLID, Strategy Pattern, State Pattern

Core Focus:
  - Identifying when cars are free for booking (hourly/daily granularity)
  - 1-week lookahead availability calendar
  - Efficient search, display, and storage of availability data
  - Prevent double-booking with date-range exclusion constraints
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, date, time
from enum import Enum
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict
import uuid
import calendar


class VehicleType(Enum):
    HATCHBACK = "Hatchback"
    SEDAN = "Sedan"
    SUV = "SUV"
    LUXURY = "Luxury"
    VAN = "Van"
    TRUCK = "Truck"


class FuelType(Enum):
    PETROL = "Petrol"
    DIESEL = "Diesel"
    ELECTRIC = "Electric"
    HYBRID = "Hybrid"


class VehicleStatus(Enum):
    AVAILABLE = "Available"
    RESERVED = "Reserved"
    RENTED = "Rented"
    MAINTENANCE = "Maintenance"


class ReservationStatus(Enum):
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


# ============================================================
# TIME BLOCK: Core abstraction for availability tracking
# ============================================================

class TimeBlock:
    """
    Represents a block of time (default: 1 hour) for availability tracking.
    This is the fundamental unit of the availability calendar.
    """
    def __init__(self, start_time: datetime, end_time: datetime):
        assert start_time < end_time, "Start must be before end"
        self._start = start_time
        self._end = end_time

    @property
    def start(self) -> datetime:
        return self._start

    @property
    def end(self) -> datetime:
        return self._end

    @property
    def hours(self) -> float:
        return (self._end - self._start).total_seconds() / 3600

    def overlaps(self, other: 'TimeBlock') -> bool:
        """Check if this block overlaps with another."""
        return self._start < other._end and other._start < self._end

    def contains(self, dt: datetime) -> bool:
        return self._start <= dt < self._end

    def __str__(self) -> str:
        return f"{self._start.strftime('%a %H:%M')} - {self._end.strftime('%H:%M')}"

    def __repr__(self) -> str:
        return f"TimeBlock({self._start.isoformat()}, {self._end.isoformat()})"


# ============================================================
# AVAILABILITY CALENDAR: Core data structure
# ============================================================

class AvailabilityCalendar:
    """
    Tracks vehicle availability at hourly granularity for a configurable lookahead window.
    
    Key design decisions:
    1. Time-block based: Each day is divided into hourly slots
    2. Lookahead window: Default 7 days, configurable
    3. Reservation block: Each booking occupies contiguous time blocks
    4. Efficient search: Pre-computed availability bitmap for quick queries
    
    DB equivalents:
    - availability_slots table: (vehicle_id, slot_start, slot_end, is_booked)
    - Or computed on-the-fly from reservations table
    """

    def __init__(self, lookahead_days: int = 7):
        self._lookahead_days = lookahead_days
        # availability[vehicle_id] = set of (date, hour) tuples that are booked
        self._booked_slots: Dict[str, Set[Tuple[date, int]]] = defaultdict(set)

    def _generate_hourly_slots(self, start_date: date, end_date: date) -> List[Tuple[date, int]]:
        """Generate all hourly slots between start_date and end_date (inclusive)."""
        slots = []
        current = start_date
        while current <= end_date:
            for hour in range(24):  # 0 = midnight, 23 = 11pm
                slots.append((current, hour))
            current += timedelta(days=1)
        return slots

    def _get_dates_in_range(self, start_date: date, end_date: date) -> List[date]:
        """Get all dates between start and end (inclusive)."""
        dates = []
        current = start_date
        while current <= end_date:
            dates.append(current)
            current += timedelta(days=1)
        return dates

    def mark_booked(self, vehicle_id: str, pickup: datetime, dropoff: datetime) -> None:
        """
        Mark all hourly slots between pickup and dropoff as booked.
        
        In production, this is derived from the reservations table:
            INSERT INTO reservations (...) 
            WHERE NOT EXISTS (
                SELECT 1 FROM availability_slots 
                WHERE vehicle_id = ? AND slot_start >= ? AND slot_end <= ? AND is_booked = true
            )
        """
        pickup_date = pickup.date()
        dropoff_date = dropoff.date()

        current = pickup.replace(minute=0, second=0, microsecond=0)
        end = dropoff.replace(minute=0, second=0, microsecond=0)

        while current < end:
            slot_key = (current.date(), current.hour)
            self._booked_slots[vehicle_id].add(slot_key)
            current += timedelta(hours=1)

    def mark_available(self, vehicle_id: str, pickup: datetime, dropoff: datetime) -> None:
        """Mark slots as available (e.g., when a reservation is cancelled)."""
        current = pickup.replace(minute=0, second=0, microsecond=0)
        end = dropoff.replace(minute=0, second=0, microsecond=0)
        while current < end:
            slot_key = (current.date(), current.hour)
            self._booked_slots[vehicle_id].discard(slot_key)
            current += timedelta(hours=1)

    def is_available(self, vehicle_id: str, pickup: datetime, dropoff: datetime) -> bool:
        """Check if all hourly slots are available for this time range."""
        current = pickup.replace(minute=0, second=0, microsecond=0)
        end = dropoff.replace(minute=0, second=0, microsecond=0)

        while current < end:
            slot_key = (current.date(), current.hour)
            if slot_key in self._booked_slots.get(vehicle_id, set()):
                return False
            current += timedelta(hours=1)
        return True

    def get_available_vehicles(self, all_vehicle_ids: List[str],
                               pickup: datetime, dropoff: datetime) -> List[str]:
        """Return vehicle IDs available for the given time range."""
        available = []
        for vid in all_vehicle_ids:
            if self.is_available(vid, pickup, dropoff):
                available.append(vid)
        return available

    def get_availability_summary(self, vehicle_id: str,
                                 target_date: date) -> Dict[str, List[int]]:
        """
        Get hourly availability for a vehicle on a specific date.
        Returns dict: {'available': [hours], 'booked': [hours]}
        """
        available_hours = []
        booked_hours = []

        for hour in range(24):
            slot_key = (target_date, hour)
            if slot_key in self._booked_slots.get(vehicle_id, set()):
                booked_hours.append(hour)
            else:
                available_hours.append(hour)

        return {
            'available': available_hours,
            'booked': booked_hours,
            'date': target_date.isoformat(),
            'total_available_hours': len(available_hours),
            'total_booked_hours': len(booked_hours)
        }

    def get_weekly_availability(self, vehicle_id: str,
                                start_date: date) -> Dict[str, List[dict]]:
        """
        Get availability for next 7 days (or remaining lookahead).
        This is the primary UI-facing method.
        
        Returns:
        {
            'vehicle_id': str,
            'week_start': str,
            'days': [
                {'date': '2024-01-15', 'day_name': 'Mon',
                 'available_hours': [9,10,11,14,15,16],
                 'total_available': 6,
                 'is_fully_booked': False},
                ...
            ]
        }
        """
        days = []
        for day_offset in range(self._lookahead_days):
            current_date = start_date + timedelta(days=day_offset)
            summary = self.get_availability_summary(vehicle_id, current_date)
            days.append({
                'date': current_date.isoformat(),
                'day_name': current_date.strftime('%a'),
                'available_hours': summary['available'],
                'total_available': summary['total_available_hours'],
                'is_fully_booked': summary['total_available_hours'] == 0
            })

        return {
            'vehicle_id': vehicle_id,
            'week_start': start_date.isoformat(),
            'days': days
        }


# ============================================================
# VEHICLE: Availability-aware Fleet
# ============================================================

class Vehicle(ABC):
    def __init__(self, vehicle_id: str, make: str, model: str, year: int,
                 license_plate: str, fuel_type: FuelType,
                 hourly_rate: float, daily_rate: float, mileage: int = 0):
        self._vehicle_id = vehicle_id
        self._make = make
        self._model = model
        self._year = year
        self._license = license_plate
        self._fuel_type = fuel_type
        self._hourly_rate = hourly_rate
        self._daily_rate = daily_rate
        self._mileage = mileage
        self._status = VehicleStatus.AVAILABLE
        self._location: Optional[str] = None

    @property
    def vehicle_id(self) -> str: return self._vehicle_id
    @property
    def make(self) -> str: return self._make
    @property
    def model(self) -> str: return self._model
    @property
    def hourly_rate(self) -> float: return self._hourly_rate
    @property
    def daily_rate(self) -> float: return self._daily_rate
    @property
    def status(self) -> VehicleStatus: return self._status
    @status.setter
    def status(self, value: VehicleStatus) -> None: self._status = value
    @property
    def location(self) -> Optional[str]: return self._location
    @location.setter
    def location(self, loc: str) -> None: self._location = loc
    @property
    @abstractmethod
    def vehicle_type(self) -> VehicleType: pass
    @property
    @abstractmethod
    def seating_capacity(self) -> int: pass

    def __str__(self) -> str:
        return f"{self._year} {self._make} {self._model} ({self._license})"


class Hatchback(Vehicle):
    @property
    def vehicle_type(self) -> VehicleType: return VehicleType.HATCHBACK
    @property
    def seating_capacity(self) -> int: return 5

class Sedan(Vehicle):
    @property
    def vehicle_type(self) -> VehicleType: return VehicleType.SEDAN
    @property
    def seating_capacity(self) -> int: return 5

class SUV(Vehicle):
    @property
    def vehicle_type(self) -> VehicleType: return VehicleType.SUV
    @property
    def seating_capacity(self) -> int: return 7

class LuxuryCar(Vehicle):
    @property
    def vehicle_type(self) -> VehicleType: return VehicleType.LUXURY
    @property
    def seating_capacity(self) -> int: return 5

class Van(Vehicle):
    @property
    def vehicle_type(self) -> VehicleType: return VehicleType.VAN
    @property
    def seating_capacity(self) -> int: return 8


# --- Customer (SRP) ---

class Customer:
    def __init__(self, customer_id: str, name: str, email: str,
                 phone: str, license_number: str):
        self._customer_id = customer_id
        self._name = name
        self._email = email
        self._phone = phone
        self._license = license_number
        self._loyalty_points = 0

    @property
    def customer_id(self) -> str: return self._customer_id
    @property
    def name(self) -> str: return self._name
    @property
    def loyalty_points(self) -> int: return self._loyalty_points

    def add_points(self, points: int) -> None: self._loyalty_points += points

    def __str__(self) -> str: return self._name


# --- Pricing Strategy (Strategy Pattern) ---

class RentalPricing(ABC):
    @abstractmethod
    def calculate_cost(self, vehicle: Vehicle, hours: int,
                       days: int, customer: Customer) -> float:
        pass


class HourlyRentalPricing(RentalPricing):
    """Charge by the hour for short rentals (< 24 hours)."""
    def calculate_cost(self, vehicle: Vehicle, hours: int,
                       days: int, customer: Customer) -> float:
        if days >= 1:
            # For multi-day, charge daily rate + remaining hours
            daily_cost = vehicle.daily_rate * days
            remaining_hours = hours - (days * 24)
            hourly_cost = max(0, remaining_hours) * vehicle.hourly_rate
            return daily_cost + hourly_cost
        return max(vehicle.hourly_rate * hours, vehicle.daily_rate)


class DailyRentalPricing(RentalPricing):
    """Charge by the day with hourly fallback."""
    def calculate_cost(self, vehicle: Vehicle, hours: int,
                       days: int, customer: Customer) -> float:
        return max(
            vehicle.daily_rate * max(1, days),
            vehicle.hourly_rate * hours
        )


class WeeklyDiscountPricing(RentalPricing):
    """Strategy: Weekly discount applied on top of daily pricing."""
    def __init__(self, base: RentalPricing):
        self._base = base

    def calculate_cost(self, vehicle: Vehicle, hours: int,
                       days: int, customer: Customer) -> float:
        cost = self._base.calculate_cost(vehicle, hours, days, customer)
        if days >= 7:
            cost *= 0.9  # 10% weekly discount
        if days >= 30:
            cost *= 0.85  # Additional 15% monthly discount
        return cost


# --- Reservation (SRP) ---

class Reservation:
    def __init__(self, reservation_id: str, customer: Customer,
                 vehicle: Vehicle, pickup_datetime: datetime,
                 return_datetime: datetime,
                 pickup_location: str, dropoff_location: str,
                 pricing: RentalPricing):
        self._reservation_id = reservation_id
        self._customer = customer
        self._vehicle = vehicle
        self._pickup_datetime = pickup_datetime
        self._return_datetime = return_datetime
        self._pickup_location = pickup_location
        self._dropoff_location = dropoff_location
        self._pricing = pricing
        self._status = ReservationStatus.PENDING
        self._total_cost = 0.0
        self._additional_services: List[Tuple[str, float]] = []

    @property
    def reservation_id(self) -> str: return self._reservation_id
    @property
    def customer(self) -> Customer: return self._customer
    @property
    def vehicle(self) -> Vehicle: return self._vehicle
    @property
    def status(self) -> ReservationStatus: return self._status
    @status.setter
    def status(self, value: ReservationStatus) -> None: self._status = value
    @property
    def pickup_datetime(self) -> datetime: return self._pickup_datetime
    @property
    def return_datetime(self) -> datetime: return self._return_datetime
    @property
    def total_cost(self) -> float: return self._total_cost

    @property
    def duration_hours(self) -> int:
        """Get total duration in hours (rounded up)."""
        delta = self._return_datetime - self._pickup_datetime
        return max(1, int(delta.total_seconds() / 3600) + 
                   (1 if delta.total_seconds() % 3600 > 0 else 0))

    @property
    def duration_days(self) -> int:
        """Get total duration in days."""
        return self.duration_hours // 24

    def calculate_cost(self) -> float:
        hours = self.duration_hours
        days = self.duration_days
        self._total_cost = self._pricing.calculate_cost(
            self._vehicle, hours, days, self._customer
        )
        # Add additional services
        for _, cost in self._additional_services:
            self._total_cost += cost
        return self._total_cost

    def add_service(self, service_name: str, cost: float) -> None:
        self._additional_services.append((service_name, cost))

    def __str__(self) -> str:
        delta = self._return_datetime - self._pickup_datetime
        hours = int(delta.total_seconds() / 3600)
        return (f"Reservation[{self._reservation_id[:8]}]: "
                f"{self._customer.name} - {self._vehicle.make} {self._vehicle.model} "
                f"({hours}h)")


# --- Fleet Manager with Availability Calendar ---

class FleetManager:
    """Manages vehicles with availability tracking."""

    def __init__(self, availability_calendar: AvailabilityCalendar):
        self._vehicles: Dict[str, Vehicle] = {}
        self._calendar = availability_calendar

    def add_vehicle(self, vehicle: Vehicle) -> None:
        self._vehicles[vehicle.vehicle_id] = vehicle

    def get_vehicle(self, vehicle_id: str) -> Optional[Vehicle]:
        return self._vehicles.get(vehicle_id)

    @property
    def all_vehicle_ids(self) -> List[str]:
        return list(self._vehicles.keys())

    @property
    def all_vehicles(self) -> List[Vehicle]:
        return list(self._vehicles.values())

    def update_vehicle_status(self, vehicle_id: str, status: VehicleStatus) -> None:
        vehicle = self._vehicles.get(vehicle_id)
        if vehicle:
            vehicle.status = status


# --- Search Service ---

class SearchService:
    """
    Handles vehicle search with availability filtering.
    
    Key UX flows:
    1. Browse: Show all vehicles available for next 7 days
    2. Search: Filter by type, location, date range
    3. Quick view: Show hourly availability for a specific day
    """

    def __init__(self, fleet: FleetManager, calendar: AvailabilityCalendar):
        self._fleet = fleet
        self._calendar = calendar

    def search_available(self, pickup_datetime: datetime,
                         return_datetime: datetime,
                         vehicle_type: Optional[VehicleType] = None,
                         location: Optional[str] = None) -> List[Vehicle]:
        """
        Primary search: find vehicles available for given time range.
        Filters by type and location if specified.
        """
        available_ids = self._calendar.get_available_vehicles(
            self._fleet.all_vehicle_ids, pickup_datetime, return_datetime
        )

        results = []
        for vid in available_ids:
            vehicle = self._fleet.get_vehicle(vid)
            if not vehicle:
                continue
            if vehicle_type and vehicle.vehicle_type != vehicle_type:
                continue
            if location and vehicle.location != location:
                continue
            results.append(vehicle)

        return results

    def search_by_date(self, target_date: date,
                       vehicle_type: Optional[VehicleType] = None) -> Dict:
        """
        Browse: Show all vehicles with availability summary for a specific date.
        Used for the "what's available today/tomorrow" view.
        """
        results = []
        for vehicle in self._fleet.all_vehicles:
            if vehicle_type and vehicle.vehicle_type != vehicle_type:
                continue
            summary = self._calendar.get_availability_summary(
                vehicle.vehicle_id, target_date
            )
            results.append({
                'vehicle': vehicle,
                'availability': summary
            })

        results.sort(key=lambda r: r['availability']['total_available_hours'],
                     reverse=True)

        return {
            'date': target_date.isoformat(),
            'day_name': target_date.strftime('%A'),
            'results': results,
            'total_available': sum(
                1 for r in results if r['availability']['total_available_hours'] > 0
            )
        }

    def browse_weekly(self, vehicle_type: Optional[VehicleType] = None,
                      location: Optional[str] = None) -> Dict:
        """
        Browse: Show all vehicles with 7-day availability calendar.
        This is the primary fleet overview screen.
        """
        today = date.today()
        fleet_availability = []

        for vehicle in self._fleet.all_vehicles:
            if vehicle_type and vehicle.vehicle_type != vehicle_type:
                continue
            if location and vehicle.location != location:
                continue

            weekly = self._calendar.get_weekly_availability(
                vehicle.vehicle_id, today
            )
            # Compute total available hours across the week
            total_available = sum(
                day['total_available'] for day in weekly['days']
            )
            fleet_availability.append({
                'vehicle': vehicle,
                'weekly_availability': weekly,
                'total_weekly_available_hours': total_available,
                'fully_booked_days': sum(
                    1 for day in weekly['days'] if day['is_fully_booked']
                )
            })

        fleet_availability.sort(
            key=lambda r: r['total_weekly_available_hours'], reverse=True
        )

        return {
            'week_start': today.isoformat(),
            'week_end': (today + timedelta(days=6)).isoformat(),
            'fleet': fleet_availability,
            'total_vehicles': len(fleet_availability),
            'total_available_hours': sum(
                r['total_weekly_available_hours'] for r in fleet_availability
            )
        }


# --- Rental Service (Facade) ---

class CarRentalService:
    """Main facade for the car rental platform with availability-driven design."""

    def __init__(self, lookahead_days: int = 7):
        self._calendar = AvailabilityCalendar(lookahead_days)
        self._fleet = FleetManager(self._calendar)
        self._search = SearchService(self._fleet, self._calendar)
        self._customers: Dict[str, Customer] = {}
        self._reservations: Dict[str, Reservation] = {}

    @property
    def fleet(self) -> FleetManager:
        return self._fleet

    @property
    def search(self) -> SearchService:
        return self._search

    @property
    def calendar(self) -> AvailabilityCalendar:
        return self._calendar

    def register_customer(self, name: str, email: str, phone: str,
                          license_number: str) -> Customer:
        cid = f"C-{uuid.uuid4().hex[:6].upper()}"
        customer = Customer(cid, name, email, phone, license_number)
        self._customers[cid] = customer
        return customer

    def get_customer(self, customer_id: str) -> Optional[Customer]:
        return self._customers.get(customer_id)

    def create_reservation(self, customer_id: str, vehicle_id: str,
                           pickup_datetime: datetime, return_datetime: datetime,
                           pickup_location: str, dropoff_location: str,
                           pricing: Optional[RentalPricing] = None) -> Optional[Reservation]:
        """
        Create a reservation after verifying availability.
        The key business logic: validate all hourly slots are free before booking.
        """
        customer = self._customers.get(customer_id)
        vehicle = self._fleet.get_vehicle(vehicle_id)

        if not customer or not vehicle:
            print("  Customer or vehicle not found")
            return None

        if pickup_datetime >= return_datetime:
            print("  Pickup must be before return")
            return None

        if pickup_datetime < datetime.now():
            print("  Cannot book in the past")
            return None

        # Check availability for the ENTIRE requested time range
        if not self._calendar.is_available(vehicle_id, pickup_datetime, return_datetime):
            print(f"  ❌ Vehicle {vehicle.make} {vehicle.model} is NOT available "
                  f"for {pickup_datetime.strftime('%a %d %H:%M')} - "
                  f"{return_datetime.strftime('%a %d %H:%M')}")
            # Show alternative nearby availability
            suggested = self._find_nearest_available(vehicle_id, pickup_datetime, return_datetime)
            if suggested:
                print(f"  💡 Nearest availability: "
                      f"{suggested['pickup'].strftime('%a %d %H:%M')} - "
                      f"{suggested['return'].strftime('%a %d %H:%M')}")
            return None

        pricing = pricing or HourlyRentalPricing()
        rid = f"R-{uuid.uuid4().hex[:8].upper()}"
        reservation = Reservation(rid, customer, vehicle, pickup_datetime,
                                  return_datetime, pickup_location, dropoff_location, pricing)
        reservation.calculate_cost()
        reservation.status = ReservationStatus.CONFIRMED
        vehicle.status = VehicleStatus.RESERVED

        # Mark the time slots as booked in the calendar
        self._calendar.mark_booked(vehicle_id, pickup_datetime, return_datetime)

        self._reservations[rid] = reservation
        hours = reservation.duration_hours
        print(f"  ✅ {vehicle.make} {vehicle.model} booked for {hours}h: "
              f"{pickup_datetime.strftime('%a %d %H:%M')} → "
              f"{return_datetime.strftime('%a %d %H:%M')}")
        print(f"  💰 Total: ${reservation.total_cost:.2f}")
        return reservation

    def _find_nearest_available(self, vehicle_id: str,
                                 desired_pickup: datetime,
                                 desired_return: datetime) -> Optional[dict]:
        """Find the nearest available time slot if the desired one is booked."""
        # Brute-force search nearby slots (simplified)
        for offset_hours in range(1, 48):
            for direction in [1, -1]:
                test_pickup = desired_pickup + timedelta(hours=offset_hours * direction)
                test_return = test_pickup + (desired_return - desired_pickup)

                if test_pickup < datetime.now():
                    continue

                if self._calendar.is_available(vehicle_id, test_pickup, test_return):
                    return {'pickup': test_pickup, 'return': test_return}
        return None

    def start_rental(self, reservation_id: str) -> None:
        reservation = self._reservations.get(reservation_id)
        if reservation and reservation.status == ReservationStatus.CONFIRMED:
            reservation.status = ReservationStatus.IN_PROGRESS
            reservation.vehicle.status = VehicleStatus.RENTED
            print(f"  🚗 Rental started for {reservation.vehicle}")

    def complete_rental(self, reservation_id: str) -> Optional[float]:
        reservation = self._reservations.get(reservation_id)
        if reservation and reservation.status == ReservationStatus.IN_PROGRESS:
            reservation.status = ReservationStatus.COMPLETED
            reservation.vehicle.status = VehicleStatus.AVAILABLE

            # Re-calculate actual cost based on actual return time
            actual_hours = reservation.duration_hours
            points = int(actual_hours * 2)  # 2 points per hour
            reservation.customer.add_points(points)

            print(f"  ✅ Rental completed! Points earned: {points}")
            return reservation.total_cost
        return None

    def cancel_reservation(self, reservation_id: str) -> None:
        reservation = self._reservations.get(reservation_id)
        if reservation and reservation.status in (ReservationStatus.PENDING,
                                                  ReservationStatus.CONFIRMED):
            # Free up the time slots
            self._calendar.mark_available(
                reservation.vehicle.vehicle_id,
                reservation.pickup_datetime,
                reservation.return_datetime
            )
            reservation.status = ReservationStatus.CANCELLED
            reservation.vehicle.status = VehicleStatus.AVAILABLE
            print(f"  ❌ Reservation {reservation_id[:8]} cancelled")


# --- Demo ---

def demo():
    print("=== Car Rental Platform - Availability-Driven Design ===\n")
    print("=" * 60)

    service = CarRentalService(lookahead_days=7)

    # Add vehicles with hourly and daily rates
    vehicles = [
        SUV("V1", "Toyota", "Fortuner", 2024, "KA-01-AB-1234",
            FuelType.DIESEL, 12.0, 80.0),
        Sedan("V2", "Honda", "City", 2024, "KA-01-CD-5678",
              FuelType.PETROL, 8.0, 50.0),
        Hatchback("V3", "Maruti", "Swift", 2023, "KA-01-EF-9012",
                  FuelType.PETROL, 5.0, 35.0),
        LuxuryCar("V4", "Mercedes", "E-Class", 2024, "KA-01-GH-3456",
                  FuelType.DIESEL, 22.0, 150.0),
        SUV("V5", "Hyundai", "Creta", 2024, "KA-01-IJ-7890",
            FuelType.PETROL, 10.0, 65.0),
        Van("V6", "Toyota", "Innova", 2024, "KA-01-KL-0123",
            FuelType.DIESEL, 15.0, 90.0),
    ]
    for v in vehicles:
        v.location = "Bangalore Airport"
        service.fleet.add_vehicle(v)

    # Register customer
    alice = service.register_customer("Alice", "alice@email.com",
                                      "9876543210", "DL-12345678")
    bob = service.register_customer("Bob", "bob@email.com",
                                    "9876543211", "DL-87654321")
    print(f"\nRegistered customers: {alice.name}, {bob.name}")

    # --- DEMO 1: Browse weekly availability ---
    print("\n" + "=" * 60)
    print("📋 DEMO 1: Browse Weekly Fleet Availability")
    print("=" * 60)

    weekly = service.search.browse_weekly()
    print(f"\nTotal vehicles: {weekly['total_vehicles']}")
    print(f"Total available hours this week: {weekly['total_available_hours']}h\n")

    for entry in weekly['fleet'][:3]:  # Show top 3
        v = entry['vehicle']
        print(f"  {v.make} {v.model:10s} ({v.vehicle_type.value:8s}) "
              f"${v.hourly_rate:.0f}/hr · ${v.daily_rate:.0f}/day")

    # --- DEMO 2: Search by date ---
    print("\n" + "=" * 60)
    print("📋 DEMO 2: Check Today's Availability")
    print("=" * 60)

    today_summary = service.search.search_by_date(date.today())
    print(f"\n  📅 {today_summary['day_name']}, {today_summary['date']}")
    print(f"  🚗 Available vehicles: {today_summary['total_available']}/{len(vehicles)}")

    for entry in today_summary['results'][:3]:
        v = entry['vehicle']
        av = entry['availability']
        print(f"    {v.make} {v.model:10s} — {av['total_available_hours']}h available")

    # --- DEMO 3: Book a vehicle for specific hours ---
    print("\n" + "=" * 60)
    print("📋 DEMO 3: Book a Vehicle (Hourly)")
    print("=" * 60)

    today = date.today()
    pickup = datetime.combine(today, time(10, 0)) + timedelta(days=1)
    dropoff = pickup + timedelta(hours=6)  # 6-hour rental

    print(f"  🔍 Searching: {pickup.strftime('%a %d %H:%M')} → {dropoff.strftime('%a %d %H:%M')}")
    available = service.search.search_available(pickup, dropoff)
    print(f"  Found {len(available)} available vehicles:")

    for v in available[:3]:
        print(f"    {v.make} {v.model:10s} — {v.vehicle_type.value} "
              f"(${v.hourly_rate:.0f}/hr, ${v.daily_rate:.0f}/day)")

    if available:
        print("\n  Booking first available SUV...")
        res1 = service.create_reservation(
            alice.customer_id, available[0].vehicle_id,
            pickup, dropoff, "Bangalore Airport", "Bangalore City",
            HourlyRentalPricing()
        )

    # --- DEMO 4: Try double-booking prevention ---
    if available:
        print("\n" + "=" * 60)
        print("📋 DEMO 4: Double-Booking Prevention")
        print("=" * 60)
        print("  Trying to book same vehicle for overlapping time...")
        res2 = service.create_reservation(
            bob.customer_id, available[0].vehicle_id,
            pickup, dropoff, "Bangalore Airport", "MG Road",
            HourlyRentalPricing()
        )

    # --- DEMO 5: Multi-day booking ---
    print("\n" + "=" * 60)
    print("📋 DEMO 5: Multi-Day Booking with Discount")
    print("=" * 60)

    pickup2 = datetime.combine(today, time(10, 0)) + timedelta(days=2)
    dropoff2 = pickup2 + timedelta(days=5)  # 5-day rental

    available2 = service.search.search_available(pickup2, dropoff2, VehicleType.SUV)
    if available2:
        res3 = service.create_reservation(
            alice.customer_id, available2[0].vehicle_id,
            pickup2, dropoff2, "Bangalore Airport", "Mysore City",
            WeeklyDiscountPricing(DailyRentalPricing())
        )

    # --- DEMO 6: Weekly overview for a specific vehicle ---
    print("\n" + "=" * 60)
    print("📋 DEMO 6: Weekly Availability Calendar")
    print("=" * 60)

    weekly_cal = service.calendar.get_weekly_availability("V1", date.today())
    print(f"\n  Vehicle: {weekly_cal['vehicle_id']}")
    print(f"  Week: {weekly_cal['week_start']} onward\n")
    print(f"  {'Day':6s} | {'Date':10s} | {'Available Hours':20s} | {'Status'}")
    print(f"  {'-'*6} | {'-'*10} | {'-'*20} | {'-'*12}")

    for day in weekly_cal['days']:
        hours_str = ', '.join(f"{h:02d}:00" for h in day['available_hours'][:4])
        if len(day['available_hours']) > 4:
            hours_str += f" ...({day['total_available']}h total)"
        status = "FULL" if day['is_fully_booked'] else "OPEN"
        print(f"  {day['day_name']:6s} | {day['date']:10s} | {hours_str:20s} | {status}")


if __name__ == "__main__":
    demo()
