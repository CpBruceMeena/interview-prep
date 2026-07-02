# Parking Lot System

## Problem Statement
Design a parking lot system that manages multiple floors, different spot sizes, ticket generation, and fee calculation.

## Requirements
- Multiple floors with configurable spots per floor
- Different spot types: Motorcycle, Compact, Large
- Vehicle types: Motorcycle, Car, Truck
- Spot assignment based on vehicle type
- Ticket generation with entry time
- Fee calculation based on duration and spot type
- Display available spots per floor

## SOLID Principles Applied
- **Single Responsibility**: Each class has one reason to change (ParkingSpot manages spot state, TicketManager handles ticketing)
- **Open/Closed**: New vehicle/spot types can be added without modifying existing code
- **Liskov Substitution**: Vehicle subclasses are substitutable for Vehicle base
- **Interface Segregation**: FeeCalculator interface is specific to fee calculation
- **Dependency Inversion**: High-level modules depend on abstractions (FeeCalculator interface)

## Design Patterns
- **Strategy Pattern**: Fee calculation strategies (HourlyFeeCalculator, DailyFeeCalculator)
- **Factory Pattern**: Vehicle creation
- **Singleton Pattern**: ParkingLot instance management
