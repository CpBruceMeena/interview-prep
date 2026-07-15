# 🧠 Hotel Booking System — Thought Process

## 📊 Class Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/java-hotel-class-diagram.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Class Diagram — Hotel Booking System: SOLID + Strategy + Decorator + Observer Patterns — 50 rooms, 6 room types. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

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
