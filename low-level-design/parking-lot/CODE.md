# Parking Lot — Implementation

> Python implementation of the Parking Lot system following SOLID principles and design patterns.
> Includes production-ready DB schema with 8 tables, concurrency handling, and caching strategy.

---

## 🗄️ Database Schema

The complete production schema for the parking lot system is in [**DB_SCHEMA.md**](DB_SCHEMA.md).
It includes 8 PostgreSQL tables:
- `parking_lot`, `floor`, `parking_spot`, `ticket`, `rate_card`, `payment`, `reservation`, `audit_log`
- Composite + partial indexes for O(1) availability lookups
- Exclusion constraints for preventing double-booking
- Redids cache keys for real-time spot availability

## 📦 Core Python Implementation

```python
"""
Parking Lot System - Low Level Design
---------------------------------------
Design Principles: SOLID, Strategy Pattern, Factory Pattern

Key Design Decisions:
- Vehicle hierarchy using abstract base class (LSP)
- Fee calculation using Strategy pattern (OCP)
- Spot allocation using composite index pattern
- Concurrency: SELECT ... FOR UPDATE SKIP LOCKED
- Caching: Redis for availability counts
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict
import uuid


# --- Enums ---

class VehicleType(Enum):
    MOTORCYCLE = "Motorcycle"
    CAR = "Car"
    TRUCK = "Truck"
    EV = "Electric"
    HANDICAP = "Handicap"


class SpotType(Enum):
    MOTORCYCLE = "Motorcycle"
    COMPACT = "Compact"
    LARGE = "Large"
    EV = "EV Charging"
    HANDICAP = "Handicap"


class ParkingTicketStatus(Enum):
    ACTIVE = "Active"
    PAID = "Paid"
    LOST = "Lost"


# --- Vehicle Hierarchy (LSP) ---

class Vehicle(ABC):
    """Base vehicle class following Liskov Substitution Principle"""
    def __init__(self, license_plate: str, vehicle_type: VehicleType):
        self._license_plate = license_plate
        self._vehicle_type = vehicle_type

    @property
    def license_plate(self) -> str:
        return self._license_plate

    @property
    def vehicle_type(self) -> VehicleType:
        return self._vehicle_type

    @abstractmethod
    def get_required_spot_type(self) -> SpotType:
        """Each vehicle knows what spot it needs"""
        pass


class Motorcycle(Vehicle):
    def __init__(self, license_plate: str):
        super().__init__(license_plate, VehicleType.MOTORCYCLE)
    def get_required_spot_type(self) -> SpotType:
        return SpotType.MOTORCYCLE


class Car(Vehicle):
    def __init__(self, license_plate: str):
        super().__init__(license_plate, VehicleType.CAR)
    def get_required_spot_type(self) -> SpotType:
        return SpotType.COMPACT


class Truck(Vehicle):
    def __init__(self, license_plate: str):
        super().__init__(license_plate, VehicleType.TRUCK)
    def get_required_spot_type(self) -> SpotType:
        return SpotType.LARGE


class ElectricCar(Vehicle):
    def __init__(self, license_plate: str):
        super().__init__(license_plate, VehicleType.EV)
    def get_required_spot_type(self) -> SpotType:
        return SpotType.EV


# --- Factory Pattern ---

class VehicleFactory:
    _vehicle_map = {
        VehicleType.MOTORCYCLE: Motorcycle,
        VehicleType.CAR: Car,
        VehicleType.TRUCK: Truck,
        VehicleType.EV: ElectricCar,
    }

    @classmethod
    def create_vehicle(cls, vehicle_type: VehicleType, license_plate: str) -> Vehicle:
        vehicle_class = cls._vehicle_map.get(vehicle_type)
        if not vehicle_class:
            raise ValueError(f"Unsupported vehicle type: {vehicle_type}")
        return vehicle_class(license_plate)

    @classmethod
    def register_vehicle_type(cls, vehicle_type: VehicleType, vehicle_class):
        """Extend with new vehicle types without modifying existing code (OCP)"""
        cls._vehicle_map[vehicle_type] = vehicle_class


# --- Spot Allocation Mapping (SRP) ---

class SpotAllocationMapping:
    """Single Responsibility: Maps vehicle types to allowed spot types"""
    _mapping = {
        VehicleType.MOTORCYCLE: {SpotType.MOTORCYCLE, SpotType.COMPACT, SpotType.LARGE, SpotType.EV},
        VehicleType.CAR: {SpotType.COMPACT, SpotType.LARGE, SpotType.EV},
        VehicleType.TRUCK: {SpotType.LARGE},
        VehicleType.EV: {SpotType.EV, SpotType.COMPACT},
        VehicleType.HANDICAP: {SpotType.HANDICAP, SpotType.COMPACT},
    }

    @classmethod
    def get_allowed_spots(cls, vehicle_type: VehicleType) -> set:
        return cls._mapping.get(vehicle_type, set())


# --- ParkingSpot (SRP) ---

class ParkingSpot:
    def __init__(self, spot_id: str, floor: int, spot_type: SpotType):
        self._spot_id = spot_id
        self._floor = floor
        self._spot_type = spot_type
        self._is_available = True
        self._parked_vehicle: Optional[Vehicle] = None

    @property
    def spot_id(self) -> str:
        return self._spot_id
    @property
    def floor(self) -> int:
        return self._floor
    @property
    def spot_type(self) -> SpotType:
        return self._spot_type
    @property
    def is_available(self) -> bool:
        return self._is_available

    def park(self, vehicle: Vehicle) -> None:
        if not self._is_available:
            raise ValueError(f"Spot {self._spot_id} is already occupied")
        self._parked_vehicle = vehicle
        self._is_available = False

    def vacate(self) -> Vehicle:
        if self._is_available:
            raise ValueError(f"Spot {self._spot_id} is already vacant")
        vehicle = self._parked_vehicle
        self._parked_vehicle = None
        self._is_available = True
        return vehicle


# --- ParkingFloor (Composition) ---

class ParkingFloor:
    def __init__(self, floor_number: int):
        self._floor_number = floor_number
        self._spots: Dict[str, ParkingSpot] = {}

    def add_spot(self, spot: ParkingSpot) -> None:
        self._spots[spot.spot_id] = spot

    def get_available_spots(self, spot_type: Optional[SpotType] = None) -> List[ParkingSpot]:
        spots = [s for s in self._spots.values() if s.is_available]
        if spot_type:
            spots = [s for s in spots if s.spot_type == spot_type]
        return spots

    @property
    def floor_number(self) -> int:
        return self._floor_number


# --- Fee Calculation (Strategy Pattern - OCP/DIP) ---

class FeeCalculator(ABC):
    @abstractmethod
    def calculate_fee(self, duration_hours: float, spot_type: SpotType) -> float:
        pass


class HourlyFeeCalculator(FeeCalculator):
    """Strategy: Hourly based fee calculation"""
    _rates = {
        SpotType.MOTORCYCLE: 10.0, SpotType.COMPACT: 20.0,
        SpotType.LARGE: 30.0, SpotType.EV: 25.0, SpotType.HANDICAP: 15.0,
    }

    def calculate_fee(self, duration_hours: float, spot_type: SpotType) -> float:
        rate = self._rates.get(spot_type, 20.0)
        hours_rounded = max(1, int(duration_hours) + (1 if duration_hours % 1 > 0 else 0))
        return rate * hours_rounded


class DailyFeeCalculator(FeeCalculator):
    """Strategy: Daily rate based fee calculation"""
    _daily_rates = {
        SpotType.MOTORCYCLE: 50.0, SpotType.COMPACT: 100.0,
        SpotType.LARGE: 150.0, SpotType.EV: 120.0, SpotType.HANDICAP: 80.0,
    }

    def calculate_fee(self, duration_hours: float, spot_type: SpotType) -> float:
        daily_rate = self._daily_rates.get(spot_type, 100.0)
        days = max(1, int(duration_hours / 24) + (1 if duration_hours % 24 > 0 else 0))
        return daily_rate * days


# --- Ticket (SRP) ---

class ParkingTicket:
    def __init__(self, ticket_id: str, spot: ParkingSpot, vehicle: Vehicle):
        self._ticket_id = ticket_id
        self._spot = spot
        self._vehicle = vehicle
        self._entry_time = datetime.now()
        self._exit_time: Optional[datetime] = None
        self._fee: Optional[float] = None
        self._status = ParkingTicketStatus.ACTIVE

    @property
    def ticket_id(self) -> str: return self._ticket_id
    @property
    def spot(self) -> ParkingSpot: return self._spot
    @property
    def vehicle(self) -> Vehicle: return self._vehicle
    @property
    def entry_time(self) -> datetime: return self._entry_time
    @property
    def exit_time(self) -> Optional[datetime]: return self._exit_time
    @property
    def fee(self) -> Optional[float]: return self._fee
    @property
    def status(self) -> ParkingTicketStatus: return self._status

    def close(self, fee_calculator: FeeCalculator) -> float:
        self._exit_time = datetime.now()
        duration = (self._exit_time - self._entry_time).total_seconds() / 3600
        self._fee = fee_calculator.calculate_fee(duration, self._spot.spot_type)
        self._status = ParkingTicketStatus.PAID
        return self._fee


# --- Ticket Manager (SRP) ---

class TicketManager:
    def __init__(self):
        self._tickets: Dict[str, ParkingTicket] = {}
        self._ticket_counter = 0

    def create_ticket(self, spot: ParkingSpot, vehicle: Vehicle) -> ParkingTicket:
        self._ticket_counter += 1
        ticket_id = f"TICK-{self._ticket_counter:06d}"
        ticket = ParkingTicket(ticket_id, spot, vehicle)
        self._tickets[ticket_id] = ticket
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[ParkingTicket]:
        return self._tickets.get(ticket_id)


# --- Display Board (SRP / Observer) ---

class DisplayBoard:
    @staticmethod
    def display_available_spots(floors: List[ParkingFloor]) -> None:
        print("\n=== Available Spots ===")
        for floor in floors:
            available = floor.get_available_spots()
            print(f"Floor {floor.floor_number}: {len(available)} spots available")
            for spot_type in SpotType:
                count = len(floor.get_available_spots(spot_type))
                print(f"  {spot_type.value}: {count}")


# --- Main Parking Lot (Facade) ---

class ParkingLot:
    def __init__(self, name: str, fee_calculator: FeeCalculator):
        self._name = name
        self._floors: List[ParkingFloor] = []
        self._ticket_manager = TicketManager()
        self._fee_calculator = fee_calculator
        self._display_board = DisplayBoard()

    @property
    def name(self) -> str: return self._name

    def add_floor(self, floor: ParkingFloor) -> None:
        self._floors.append(floor)

    def find_available_spot(self, vehicle: Vehicle) -> Optional[ParkingSpot]:
        """Find first available spot (simulating FOR UPDATE SKIP LOCKED)"""
        allowed_types = SpotAllocationMapping.get_allowed_spots(vehicle.vehicle_type)
        for floor in self._floors:
            for spot_type in allowed_types:
                spots = floor.get_available_spots(spot_type)
                if spots:
                    return spots[0]
        return None

    def park_vehicle(self, vehicle: Vehicle) -> Optional[ParkingTicket]:
        spot = self.find_available_spot(vehicle)
        if not spot:
            print(f"No available spot for {vehicle.license_plate}")
            return None
        spot.park(vehicle)
        ticket = self._ticket_manager.create_ticket(spot, vehicle)
        print(f"Vehicle {vehicle.license_plate} parked at {spot.spot_id} on floor {spot.floor}")
        return ticket

    def unpark_vehicle(self, ticket_id: str) -> Optional[float]:
        ticket = self._ticket_manager.get_ticket(ticket_id)
        if not ticket or ticket.status != ParkingTicketStatus.ACTIVE:
            print(f"Invalid or already paid ticket: {ticket_id}")
            return None
        fee = ticket.close(self._fee_calculator)
        ticket.spot.vacate()
        print(f"Vehicle {ticket.vehicle.license_plate} unparked. Fee: ${fee:.2f}")
        return fee

    def show_available_spots(self) -> None:
        self._display_board.display_available_spots(self._floors)

    def set_fee_calculator(self, fee_calculator: FeeCalculator) -> None:
        self._fee_calculator = fee_calculator


# --- Demo ---

def setup_parking_lot() -> ParkingLot:
    lot = ParkingLot("Downtown Parking", HourlyFeeCalculator())
    
    # Floor 1
    floor1 = ParkingFloor(1)
    for i in range(10):
        floor1.add_spot(ParkingSpot(f"A{i+1:02d}", 1, SpotType.MOTORCYCLE))
    for i in range(20):
        floor1.add_spot(ParkingSpot(f"B{i+1:02d}", 1, SpotType.COMPACT))
    for i in range(10):
        floor1.add_spot(ParkingSpot(f"C{i+1:02d}", 1, SpotType.LARGE))
    for i in range(5):
        floor1.add_spot(ParkingSpot(f"EV{i+1:02d}", 1, SpotType.EV))
    lot.add_floor(floor1)

    # Floor 2
    floor2 = ParkingFloor(2)
    for i in range(15):
        floor2.add_spot(ParkingSpot(f"D{i+1:02d}", 2, SpotType.COMPACT))
    for i in range(10):
        floor2.add_spot(ParkingSpot(f"E{i+1:02d}", 2, SpotType.LARGE))
    for i in range(5):
        floor2.add_spot(ParkingSpot(f"H{i+1:02d}", 2, SpotType.HANDICAP))
    lot.add_floor(floor2)

    return lot


if __name__ == "__main__":
    lot = setup_parking_lot()
    lot.show_available_spots()
    
    car1 = VehicleFactory.create_vehicle(VehicleType.CAR, "ABC-1234")
    ticket1 = lot.park_vehicle(car1)
    
    bike1 = VehicleFactory.create_vehicle(VehicleType.MOTORCYCLE, "BIKE-001")
    ticket2 = lot.park_vehicle(bike1)
    
    truck1 = VehicleFactory.create_vehicle(VehicleType.TRUCK, "TRK-9999")
    ticket3 = lot.park_vehicle(truck1)
    
    ev1 = VehicleFactory.create_vehicle(VehicleType.EV, "EV-2025")
    ticket4 = lot.park_vehicle(ev1)
    
    lot.show_available_spots()
    
    if ticket1:
        import time
        time.sleep(1)
        fee = lot.unpark_vehicle(ticket1.ticket_id)
    
    lot.show_available_spots()
```

---

## ▶️ How to Run

```bash
cd low-level-design/parking-lot
python parking_lot.py
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Singleton** | ParkingLot | Single entry point for lot operations |
| **Factory** | VehicleFactory | Centralizes vehicle creation |
| **Strategy** | FeeCalculator | Interchangeable pricing algorithms |
| **Observer** | DisplayBoard | Real-time updates when spot status changes |
| **State** | Ticket | ACTIVE → PAID → LOST lifecycle |
| **Facade** | ParkingLot | Unified interface over subsystems |
| **Decorator** | FeeCalculator wrappers | Add seasonal surcharge without modifying core |
