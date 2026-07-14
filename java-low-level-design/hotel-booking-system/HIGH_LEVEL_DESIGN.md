# 🏗️ Hotel Booking System — High-Level Design

> **Target Level:** Senior/Staff Engineer
> **Focus:** Inventory management, pricing strategies, booking lifecycle

---

## 1. SYSTEM OVERVIEW

**Purpose:** Online hotel reservation system with dynamic pricing and inventory management.

**Scale:** 500 rooms, 100K bookings/month, peak season 3x normal traffic.

---

## 2. SYSTEM ARCHITECTURE

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Guest App    │    │ Admin Panel  │    │ OTA Channel  │
│ (Web/Mobile) │    │ (Management) │    │ (Booking.com)│
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
              ┌────────────▼────────────┐
              │    API Gateway (REST)   │
              └────────────┬────────────┘
                           │
              ┌────────────┴────────────┐
              │  Hotel Booking Service  │
              │  (Java - Spring Boot)   │
              ├─────────────────────────┤
              │ Pricing | Inventory     │
              │ Booking | Notification  │
              └────────────┬────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
  │ PostgreSQL  │  │    Redis    │  │  Message Q  │
  │ (Bookings)  │  │ (Inventory) │  │ (RabbitMQ)  │
  └─────────────┘  └─────────────┘  └─────────────┘
```

## 3. BOOKING LIFECYCLE

```
SEARCH → AVAILABLE → RESERVE → CONFIRMED → CHECK_IN → CHECK_OUT
                           ↓                    ↓
                      WAITLIST           CANCELLED → REFUND
```

## 4. PRICING STRATEGY

| Strategy | Logic | Effect |
|----------|-------|--------|
| Base Rate | RoomType.baseRate × nights | Minimum revenue |
| Seasonal | 1.0-2.5× multiplier by month | Captures peak demand |
| Loyalty | 5-30% discount by tier | Repeat customer retention |
| Last Minute | 20% discount within 3 days | Fills unsold inventory |
| Extended Stay | 10% discount for 7+ nights | Increases occupancy |

## 5. CONCURRENCY & EDGE CASES

| Scenario | Approach |
|----------|----------|
| Double booking | Synchronized inventory methods + optimistic locking |
| Payment failure | Booking held 15 min pending, released after timeout |
| Overbooking tolerance | Allow 5% overbooking, VIP guests bumped last |
| Cancellation | Release inventory, process refund by policy |
| No-show | Auto-cancel after midnight check-in date |

## 6. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Inventory granularity | Date-range (not per-night) | Simpler, matches real booking patterns |
| Pricing calculation | At booking time, not check-out | Customer knows price upfront |
| Notifications | Async via observer | Non-blocking, extensible |
| Room assignment | At booking vs check-in | At booking guarantees specific room |
