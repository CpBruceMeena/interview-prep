"""
Car Rental Platform - Low Level Design
-----------------------------------------
Design Principles: SOLID, Strategy Pattern, State Pattern
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, date
from enum import Enum
from typing import Dict, List, Optional, Tuple
import uuid


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
    RETURNED = "Returned"


class ReservationStatus(Enum):
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


# --- Vehicle Hierarchy (LSP / OCP) ---

class Vehicle(ABC):
    def __init__(self, vehicle_id: str, make: str, model: str, year: int,
                 license_plate: str, fuel_type: FuelType,
                 daily_rate: float, mileage: int = 0):
        self._vehicle_id = vehicle_id
        self._make = make
        self._model = model
        self._year = year
        self._license = license_plate
        self._fuel_type = fuel_type
        self._daily_rate = daily_rate
        self._mileage = mileage
        self._status = VehicleStatus.AVAILABLE
        self._location: Optional[str] = None

    @property
    def vehicle_id(self) -> str:
        return self._vehicle_id

    @property
    def make(self) -> str:
        return self._make

    @property
    def model(self) -> str:
        return self._model

    @property
    def daily_rate(self) -> float:
        return self._daily_rate

    @property
    def status(self) -> VehicleStatus:
        return self._status

    @status.setter
    def status(self, value: VehicleStatus) -> None:
        self._status = value

    @property
    @abstractmethod
    def vehicle_type(self) -> VehicleType:
        pass

    @property
    @abstractmethod
    def seating_capacity(self) -> int:
        pass

    def __str__(self) -> str:
        return f"{self._year} {self._make} {self._model} ({self._license})"


class Hatchback(Vehicle):
    @property
    def vehicle_type(self) -> VehicleType:
        return VehicleType.HATCHBACK

    @property
    def seating_capacity(self) -> int:
        return 5


class Sedan(Vehicle):
    @property
    def vehicle_type(self) -> VehicleType:
        return VehicleType.SEDAN

    @property
    def seating_capacity(self) -> int:
        return 5


class SUV(Vehicle):
    @property
    def vehicle_type(self) -> VehicleType:
        return VehicleType.SUV

    @property
    def seating_capacity(self) -> int:
        return 7


class LuxuryCar(Vehicle):
    @property
    def vehicle_type(self) -> VehicleType:
        return VehicleType.LUXURY

    @property
    def seating_capacity(self) -> int:
        return 5


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
    def customer_id(self) -> str:
        return self._customer_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def loyalty_points(self) -> int:
        return self._loyalty_points

    def add_points(self, points: int) -> None:
        self._loyalty_points += points

    def redeem_points(self, points: int) -> bool:
        if points <= self._loyalty_points:
            self._loyalty_points -= points
            return True
        return False

    def __str__(self) -> str:
        return self._name


# --- Pricing Strategy (Strategy Pattern) ---

class RentalPricing(ABC):
    @abstractmethod
    def calculate_cost(self, vehicle: Vehicle, days: int,
                       customer: Customer) -> float:
        pass


class StandardRentalPricing(RentalPricing):
    def calculate_cost(self, vehicle: Vehicle, days: int,
                       customer: Customer) -> float:
        return vehicle.daily_rate * days


class WeeklyDiscountPricing(RentalPricing):
    def calculate_cost(self, vehicle: Vehicle, days: int,
                       customer: Customer) -> float:
        base = vehicle.daily_rate * days
        if days >= 7:
            base *= 0.9  # 10% weekly discount
        if days >= 30:
            base *= 0.85  # Additional 15% monthly discount
        return base


class LoyaltyPricing(RentalPricing):
    def __init__(self, base: RentalPricing):
        self._base = base

    def calculate_cost(self, vehicle: Vehicle, days: int,
                       customer: Customer) -> float:
        cost = self._base.calculate_cost(vehicle, days, customer)
        discount = min(0.2, customer.loyalty_points / 1000 * 0.01)
        return cost * (1 - discount)


# --- Reservation (SRP) ---

class Reservation:
    def __init__(self, reservation_id: str, customer: Customer,
                 vehicle: Vehicle, pickup_date: date, return_date: date,
                 pickup_location: str, dropoff_location: str,
                 pricing: RentalPricing):
        self._reservation_id = reservation_id
        self._customer = customer
        self._vehicle = vehicle
        self._pickup_date = pickup_date
        self._return_date = return_date
        self._pickup_location = pickup_location
        self._dropoff_location = dropoff_location
        self._pricing = pricing
        self._status = ReservationStatus.PENDING
        self._total_cost = 0.0
        self._insurance_included = False
        self._additional_services: List[Tuple[str, float]] = []

    @property
    def reservation_id(self) -> str:
        return self._reservation_id

    @property
    def customer(self) -> Customer:
        return self._customer

    @property
    def vehicle(self) -> Vehicle:
        return self._vehicle

    @property
    def status(self) -> ReservationStatus:
        return self._status

    @status.setter
    def status(self, value: ReservationStatus) -> None:
        self._status = value

    @property
    def total_cost(self) -> float:
        return self._total_cost

    def calculate_cost(self) -> float:
        days = (self._return_date - self._pickup_date).days
        self._total_cost = self._pricing.calculate_cost(
            self._vehicle, days, self._customer
        )
        # Add insurance
        if self._insurance_included:
            self._total_cost += 15.0 * days
        # Add additional services
        for _, cost in self._additional_services:
            self._total_cost += cost
        return self._total_cost

    def add_insurance(self) -> None:
        self._insurance_included = True

    def add_service(self, service_name: str, cost: float) -> None:
        self._additional_services.append((service_name, cost))

    def __str__(self) -> str:
        return (f"Reservation[{self._reservation_id[:8]}]: "
                f"{self._customer.name} - {self._vehicle.make} {self._vehicle.model}")


# --- Fleet Management (SRP) ---

class FleetManager:
    """Manages the vehicle fleet"""

    def __init__(self):
        self._vehicles: Dict[str, Vehicle] = {}

    def add_vehicle(self, vehicle: Vehicle) -> None:
        self._vehicles[vehicle.vehicle_id] = vehicle

    def get_vehicle(self, vehicle_id: str) -> Optional[Vehicle]:
        return self._vehicles.get(vehicle_id)

    def get_available_vehicles(self, vehicle_type: Optional[VehicleType] = None,
                               pickup_date: Optional[date] = None,
                               return_date: Optional[date] = None) -> List[Vehicle]:
        vehicles = [v for v in self._vehicles.values()
                    if v.status == VehicleStatus.AVAILABLE]
        if vehicle_type:
            vehicles = [v for v in vehicles if v.vehicle_type == vehicle_type]
        return vehicles

    def update_vehicle_status(self, vehicle_id: str, status: VehicleStatus) -> None:
        vehicle = self._vehicles.get(vehicle_id)
        if vehicle:
            vehicle.status = status


# --- Rental Service (Facade) ---

class CarRentalService:
    def __init__(self):
        self._fleet = FleetManager()
        self._customers: Dict[str, Customer] = {}
        self._reservations: Dict[str, Reservation] = {}

    @property
    def fleet(self) -> FleetManager:
        return self._fleet

    def register_customer(self, name: str, email: str, phone: str,
                          license_number: str) -> Customer:
        cid = f"C-{uuid.uuid4().hex[:6].upper()}"
        customer = Customer(cid, name, email, phone, license_number)
        self._customers[cid] = customer
        return customer

    def get_customer(self, customer_id: str) -> Optional[Customer]:
        return self._customers.get(customer_id)

    def search_vehicles(self, vehicle_type: Optional[VehicleType] = None,
                        pickup_date: Optional[date] = None,
                        return_date: Optional[date] = None) -> List[Vehicle]:
        return self._fleet.get_available_vehicles(vehicle_type, pickup_date, return_date)

    def create_reservation(self, customer_id: str, vehicle_id: str,
                           pickup_date: date, return_date: date,
                           pickup_location: str, dropoff_location: str,
                           pricing: Optional[RentalPricing] = None) -> Optional[Reservation]:
        customer = self._customers.get(customer_id)
        vehicle = self._fleet.get_vehicle(vehicle_id)

        if not customer or not vehicle:
            print("  Customer or vehicle not found")
            return None

        if vehicle.status != VehicleStatus.AVAILABLE:
            print(f"  Vehicle {vehicle.make} {vehicle.model} is not available")
            return None

        pricing = pricing or StandardRentalPricing()
        rid = f"R-{uuid.uuid4().hex[:8].upper()}"
        reservation = Reservation(rid, customer, vehicle, pickup_date,
                                  return_date, pickup_location, dropoff_location, pricing)
        reservation.calculate_cost()
        reservation.status = ReservationStatus.CONFIRMED
        vehicle.status = VehicleStatus.RESERVED

        self._reservations[rid] = reservation
        print(f"  ✅ Reservation created: {reservation}")
        print(f"  💰 Total: ${reservation.total_cost:.2f}")
        return reservation

    def start_rental(self, reservation_id: str) -> None:
        reservation = self._reservations.get(reservation_id)
        if reservation and reservation.status == ReservationStatus.CONFIRMED:
            reservation.status = ReservationStatus.IN_PROGRESS
            reservation.vehicle.status = VehicleStatus.RENTED
            print(f"  🚗 Rental started for {reservation.vehicle.make} {reservation.vehicle.model}")

    def complete_rental(self, reservation_id: str) -> Optional[float]:
        reservation = self._reservations.get(reservation_id)
        if reservation and reservation.status == ReservationStatus.IN_PROGRESS:
            reservation.status = ReservationStatus.COMPLETED
            reservation.vehicle.status = VehicleStatus.AVAILABLE

            # Add loyalty points
            points = int(reservation.total_cost / 10)
            reservation.customer.add_points(points)

            print(f"  ✅ Rental completed! Loyalty points earned: {points}")
            return reservation.total_cost
        return None

    def cancel_reservation(self, reservation_id: str) -> None:
        reservation = self._reservations.get(reservation_id)
        if reservation and reservation.status in (ReservationStatus.PENDING,
                                                  ReservationStatus.CONFIRMED):
            reservation.status = ReservationStatus.CANCELLED
            reservation.vehicle.status = VehicleStatus.AVAILABLE
            print(f"  ❌ Reservation {reservation_id[:8]} cancelled")


# --- Demo ---

def demo():
    print("=== Car Rental Platform ===")
    print("=" * 50)

    service = CarRentalService()

    # Add vehicles
    vehicles = [
        SUV("V1", "Toyota", "Fortuner", 2024, "KA-01-AB-1234", FuelType.DIESEL, 80.0),
        Sedan("V2", "Honda", "City", 2024, "KA-01-CD-5678", FuelType.PETROL, 50.0),
        Hatchback("V3", "Maruti", "Swift", 2023, "KA-01-EF-9012", FuelType.PETROL, 35.0),
        LuxuryCar("V4", "Mercedes", "E-Class", 2024, "KA-01-GH-3456", FuelType.DIESEL, 150.0),
        SUV("V5", "Hyundai", "Creta", 2024, "KA-01-IJ-7890", FuelType.PETROL, 65.0),
    ]
    for v in vehicles:
        service.fleet.add_vehicle(v)

    # Register customer
    alice = service.register_customer("Alice", "alice@email.com", "9876543210", "DL-12345678")
    print(f"\nCustomer: {alice}")

    # Search available
    print("\n--- Available SUVs ---")
    for v in service.search_vehicles(VehicleType.SUV):
        print(f"  {v} - ${v.daily_rate}/day")

    # Create reservation
    print("\n--- Creating Reservation ---")
    today = date.today()
    pickup = today + timedelta(days=2)
    ret = pickup + timedelta(days=5)

    # Use weekly discount
    pricing = WeeklyDiscountPricing()
    res = service.create_reservation(alice.customer_id, "V1",
                                      pickup, ret,
                                      "Bangalore Airport", "Mysore City",
                                      pricing)

    if res:
        res.add_insurance()
        res.add_service("GPS Navigation", 5.0)
        print(f"  Final cost with add-ons: ${res.calculate_cost():.2f}")

        service.start_rental(res.reservation_id)
        service.complete_rental(res.reservation_id)
        print(f"  Loyalty points: {alice.loyalty_points}")


if __name__ == "__main__":
    demo()
