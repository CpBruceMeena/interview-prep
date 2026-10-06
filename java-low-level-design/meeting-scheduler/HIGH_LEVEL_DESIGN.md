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
| Sorted map of non-overlapping intervals | `TreeMap` floor/higher neighbours (what the LLD uses) | O(log n) per check |
| Interval tree | Needed only when stored intervals may overlap (e.g. a person's tentative + accepted invites) | O(log n + k) |
| Linear scan | Check all bookings | O(n) |
| Database query | `start_at < :end AND end_at > :start` on index `(room_id, start_at)` | O(log n + k) |
| Database constraint | Postgres `EXCLUDE USING gist (room_id WITH =, tstzrange(start_at, end_at) WITH &&)` | Enforced on commit; the only check that is safe across many app instances |

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
| Conflict detection | DB exclusion constraint is authoritative; in-memory/cached calendars only for suggestions | With several service instances, an in-memory check alone cannot prevent two instances booking the same room |
| Calendar storage | PostgreSQL source of truth + Redis free/busy cache | Cache is invalidated on every write to the person's or room's calendar; stale cache only affects suggestions |
| Notifications | Async via Observer pattern | Non-blocking, extensible |
| Granularity | 15-minute slots | Standard enterprise calendar |

## 7. CONSISTENCY, IDEMPOTENCY & FAILURE MODES

**Write path:** a booking inserts one row per attendee calendar plus the room row in a single transaction. The room exclusion constraint makes double-booking a room impossible; for people, a conflict is usually allowed with a warning (people double-book themselves on purpose), so it is a check, not a constraint. Partition by tenant (company): every booking is single-tenant, so transactions stay on one shard.

**Read path (free/busy):** the expensive query is "when are these 8 people free this week". Precompute per person per day a busy bitmap at 15-minute resolution (96 bits/day), cache it, and AND the bitmaps of all attendees. Invalidate on any write to that person's calendar.

| Failure | Response |
|---------|----------|
| Client retries a create after a timeout | Idempotency key on create (`UNIQUE(tenant_id, idempotency_key)`), so the retry returns the existing meeting |
| Two instances book the same room concurrently | Exclusion constraint: one commit fails with a constraint violation, which maps to `409 Conflict` |
| Invite email / push fails | Notifications go through an outbox table written in the booking transaction and are delivered by a worker with retries; the booking is never rolled back because email failed |
| External calendar sync (Google/Exchange) diverges | Treat sync as eventually consistent: store external ids and etags, sync incrementally (watch channels / sync tokens), resolve conflicts by last-writer-wins on non-time fields and by re-validating time changes against room constraints |
| Stale free/busy cache | Suggestions may be wrong for a few seconds; the booking transaction re-validates, so correctness is unaffected |

**Capacity:** 10K employees × ~5 meetings/day ≈ 50K meeting rows/day and ~250K attendee rows/day: small. Free/busy lookups dominate (every scheduling UI open triggers one for each attendee); with bitmaps one person-week is 7 × 12 bytes, so a full company-week of free/busy fits in about 1 MB of cache.

