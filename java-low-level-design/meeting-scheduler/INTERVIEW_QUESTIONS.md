# 📅 Meeting Scheduler — Interview Questions

## Q1: How do you handle recurring meetings?

**Answer:**
- Store recurrence pattern (DAILY/WEEKLY/MONTHLY) on the meeting
- On creation, expand up to X instances (e.g., 52 weeks)
- Exception model: modify/cancel single instance vs modify series
- Use iCalendar RRULE format for Outlook/Google Calendar sync

## Q2: How do you detect and resolve scheduling conflicts at scale?

**Answer:**
- In-memory NavigableSet per room for O(log n) lookups
- Participant availability index for multi-person conflict detection
- Denormalized Redis cache: `room:{id}:bookings` as sorted set by timestamp
- For 10K+ employees: shard by building/floor/region

## Q3: Design a "find first available slot" across multiple participants

**Answer:**
- Start with union of all participant busy slots
- Find gaps in the busy timeline within working hours
- For each gap, check room availability
- Return first gap that satisfies: duration, room capacity, participant availability

## Q4: How would you handle delegate/assistant booking?

**Answer:**
- Delegate mapping: manager → assistant(s)
- Assistant can book on behalf of manager (appears as "organized by")
- Permissions: assistant has WRITE access to manager's calendar
- Audit trail shows who actually created the meeting
