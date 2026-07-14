# 🧠 Hotel Booking System — Thought Process

## Problem Breakdown

### Step 1: Core Entities
- **Room:** Type, capacity, rate, amenities
- **Guest:** Profile, loyalty tier, preferences
- **Booking:** Date range, status lifecycle
- **Inventory:** Per-date availability per room type

### Step 2: Date Range Model
- Bookings span multiple nights → need date-range management
- Overlap detection for availability checking

### Step 3: Pricing Strategy
- Hotels use complex pricing (seasonal, loyalty, promotions)
- Strategy pattern to make pricing extensible
- Decorator pattern to compose multiple pricing strategies

### Step 4: Booking Lifecycle
- State machine: SEARCH → RESERVE → PAY → CONFIRM → CHECK_IN → CHECK_OUT
- Observer pattern for side effects (email, SMS, billing)

### Step 5: Concurrency
- Two guests can't book the same room for the same dates
- Use synchronized blocks + in-memory atomic operations

## Key Decisions

| Decision | Why |
|----------|-----|
| Date-range inventory (not per-night) | Matches real booking, simpler conflict detection |
| Synchronized inventory methods | Thread safety without database overhead |
| Pricing at booking time | Customer price certainty |
| Decorator for pricing | Compose multiple modifiers without class explosion |
