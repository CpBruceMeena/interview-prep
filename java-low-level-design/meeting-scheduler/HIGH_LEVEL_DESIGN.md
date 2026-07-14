# 🏗️ Meeting Scheduler — High-Level Design

> **Target Level:** Senior/Staff Engineer
> **Focus:** Calendar management, conflict detection, room booking, notifications

---

## 1. SYSTEM OVERVIEW

**Purpose:** Enterprise meeting scheduling system with room booking, participant management, and calendar sync.

**Scale:** 10K employees, 100K meetings/month, thousands of rooms across buildings.

---

## 2. SYSTEM ARCHITECTURE

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Web App      │    │ Mobile App   │    │ Outlook/     │
│ (Calendar)   │    │ (Calendar)   │    │ Google Sync  │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
              ┌────────────▼────────────┐
              │     API Gateway         │
              └────────────┬────────────┘
                           │
              ┌────────────┴────────────┐
              │   Meeting Scheduler     │
              │   (Java - Spring Boot)  │
              ├─────────────────────────┤
              │  Conflict Detection     │
              │  Room Booking           │
              │  Notification           │
              └────────────┬────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
  │ PostgreSQL  │  │    Redis    │  │  Message Q  │
  │ (Meetings)  │  │ (Calendar)  │  │ (RabbitMQ)  │
  └─────────────┘  └─────────────┘  └─────────────┘
```

## 3. MEETING LIFECYCLE

```
SCHEDULED → ONGOING → COMPLETED
    │          │
    ▼          ▼
CANCELLED  RESCHEDULED → SCHEDULED
```

## 4. CONFLICT DETECTION

| Algorithm | Approach | Complexity |
|-----------|----------|------------|
| Interval Tree | NavigableSet floor/ceiling | O(log n) |
| Linear Scan | Check all bookings | O(n) |
| Database Query | SQL overlap condition | O(log n) with index |

## 5. RECURRENCE HANDLING

| Pattern | Implementation |
|---------|---------------|
| Daily | Create instances for each day |
| Weekly | Same day-of-week, time, room |
| Monthly | Same day-of-month |
| Exception | Cancel/modify single instance, leave series |

## 6. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Conflict detection | In-memory NavigableSet | Sub-millisecond, no DB round-trip |
| Calendar storage | Hybrid (Redis + PostgreSQL) | Redis for fast lookups, PG for durability |
| Notifications | Async via Observer pattern | Non-blocking, extensible |
| Granularity | 15-minute slots | Standard enterprise calendar |
