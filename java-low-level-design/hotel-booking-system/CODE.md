# Hotel Booking System — Java Implementation

> Java implementation of a Hotel Booking System following SOLID principles and design patterns.

## 📦 Core Implementation

### Key Abstractions

| Interface/Class | Responsibility | Pattern |
|----------------|---------------|---------|
| `PricingStrategy` | Calculates room pricing | Strategy + Decorator |
| `BookingObserver` | Reacts to booking lifecycle events | Observer |
| `InventoryManager` | Manages room availability by date | Singleton |
| `HotelBookingService` | Unified booking API | Facade |

### Pricing with Decorator Pattern

```java
// Nested strategies via Decorator pattern
PricingStrategy pricing = new LoyaltyPricing(
    new SeasonalPricing()
);

// Base price for Suite, 3 nights:
// BaseRate = 350.0 * 3 = 1050.0
// Seasonal (December) = 1050.0 * 2.0 = 2100.0
// Gold Loyalty = 2100.0 * 0.8 = 1680.0
```

### Inventory Management

```java
class InventoryManager {
    // Per-date, per-room-type availability
    private final Map<RoomType, NavigableMap<LocalDate, Integer>> availability;

    public synchronized boolean checkAvailability(RoomType type, DateRange range) {
        return range.dates().allMatch(d ->
            availability.get(type).getOrDefault(d, 0) > 0
        );
    }

    public synchronized boolean reserveRoom(RoomType type, DateRange range) {
        if (!checkAvailability(type, range)) return false;
        range.dates().forEach(d -> availability.get(type).merge(d, -1, Integer::sum));
        return true;
    }
}
```

## ▶️ How to Run

```bash
cd java-low-level-design/hotel-booking-system
javac HotelBookingSystem.java
java HotelBookingSystem
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | PricingStrategy | Base / Seasonal / Loyalty pricing algorithms |
| **Decorator** | LoyaltyPricing wraps SeasonalPricing | Compose pricing modifiers |
| **Observer** | BookingObserver | Email, SMS, analytics on booking events |
| **Facade** | HotelBookingService | Unified interface over inventory, pricing, notifications |
| **Command** | Booking | Immutable lifecycle object |
