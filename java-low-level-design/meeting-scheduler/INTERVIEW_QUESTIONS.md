# 📅 Meeting Scheduler — Interview Questions

## Q1: How do you check whether a new meeting conflicts with a room's existing bookings?

**Answer:**
- Store each calendar's entries in a `TreeMap<Instant, Entry>` keyed by start. The entries never overlap.
- For a new `[s, e)`, only two entries can overlap: `floorEntry(s)` (overlaps if it ends after `s`) and `higherEntry(s)` (overlaps if it starts before `e`). O(log n).
- Checking only the *ceiling* neighbour, or comparing starts only, misses a long earlier meeting (8:00–12:00 vs 11:00).
- Database equivalent: `WHERE room_id = ? AND start_at < :e AND end_at > :s` with an index on `(room_id, start_at)`, or let Postgres enforce it with `EXCLUDE USING gist (room_id WITH =, tstzrange(start_at, end_at) WITH &&)`.

## Q2: Find the earliest 1-hour slot when 6 people, in 3 time zones, are all free.

**Answer:**
- For each person collect busy intervals in the search window: their meetings plus their off-hours, computed in their own `ZoneId` (nights, weekends, holidays).
- Sort all intervals by start (O(N log N)), sweep with a cursor: whenever the next busy interval starts after the cursor, `[cursor, next.start)` is a common gap. Advance `cursor = max(cursor, b.end)`.
- In each gap emit grid-aligned candidates (15-minute grid) of length 1 hour; the first is the answer.
- Equivalent framing: merge-intervals (LeetCode 56) followed by "employee free time" (LeetCode 759). With k sorted per-person lists you can also do a k-way merge with a heap in O(N log k).

## Q3: Two organizers book overlapping meetings that both include Bob, at the same instant. What happens?

**Answer:**
- Each `schedule` call locks the calendars of the room and all attendees, **sorted by key**, then checks all of them, then inserts into all of them.
- Both need `person:bob`. Whoever gets it first completes; the other blocks, then sees Bob's new entry and throws `ConflictException` without writing anything.
- Sorted acquisition is what prevents deadlock: if one booking locked `alice → bob` and the other `bob → alice`, each could hold one lock and wait forever.
- Alternative: one global lock. Correct and simple, but it serialises every booking in the company; mention it as the fallback.

## Q4: Why not check availability first and then book?

**Answer:**
- Classic check-then-act race. Between "Bob is free" and "insert into Bob's calendar" another thread can book Bob. The check and the insert must be in the same critical section (or the same DB transaction with a constraint).
- That is why `findFreeSlots` and `proposeEarliest` are advisory and `schedule` re-checks everything under locks.

## Q5: Now add recurring meetings ("every Tuesday at 10:00 for 6 months").

**Answer:**
- Store the series once (an iCalendar RRULE: `FREQ=WEEKLY;BYDAY=TU`) plus exceptions (`EXDATE` for cancelled occurrences, overridden instances for moved ones).
- **Expand on read** for display; **materialise** instances over a rolling horizon (e.g. 3–6 months) for conflict checking, because conflicts must be checked against concrete intervals.
- Booking the series: either all-or-nothing for the horizon, or book what's free and report the conflicting dates (what Outlook does). Say which you chose.
- Recurrence must be expanded in the **organizer's zone**: "10:00 every Tuesday in New York" shifts in UTC across DST.

## Q6: How do you allocate rooms well?

**Answer:**
- Filter by capacity and features, then best fit: smallest room that works, fewest unneeded features. This keeps the 12-seat board room for 12-person meetings.
- Other policies as strategies: nearest to most attendees, same floor, avoid cross-building walks back to back.
- For a whole day's requests at once, assigning rooms to minimise the number used is interval partitioning (sort by start, min-heap of room end times), and the minimum number of rooms equals the maximum overlap (LeetCode 253).

## Q7: Should declined or tentative invites block a person's time?

**Answer:**
- Declined: no. Remove the entry from their calendar (the meeting still exists).
- Tentative/unanswered: most products show them as busy for free/busy lookups but allow overbooking with a warning. Make it a policy flag rather than hard-coding it.
- Rooms are different: a room is hard-blocked regardless of RSVPs.

## Q8: How do you test this?

**Answer:**
- Unit tests on `TimeSlot.overlaps` (touching, nested, partial) and `IntervalCalendar.conflict` (floor and higher neighbours).
- Free-slot tests with fixed dates in a non-DST week and people in different zones, asserting exact UTC slots. Add a DST-transition week as a separate case.
- Concurrency: many threads booking random meetings with overlapping attendees and auto-allocated rooms, with a timeout on each worker (a timeout means deadlock). Afterwards check the **invariants**: no person or room has overlapping live meetings, and each calendar matches the set of live meetings exactly.

---

## ⚠️ Common mistakes

- Closed-interval overlap, so back-to-back meetings conflict.
- Checking only the room, not the attendees (or vice versa).
- Cancel that frees attendees but forgets the organizer's calendar.
- Locking calendars in request order instead of a canonical order (deadlock).
- `LocalDateTime` everywhere; working hours computed in the server's zone.
- Free-slot search that tests every 15-minute candidate against every booking (O(candidates × bookings)) instead of one merge.
- A demo that schedules for `LocalDate.now().plusDays(1)` and breaks when tomorrow is Saturday.

## 🎯 Senior vs Staff signal

- **Senior:** half-open intervals, O(log n) conflict check, atomic booking across room and attendees with an argued locking scheme, a correct sweep for common free time, deterministic tests.
- **Staff:** treats time zones and DST as first-class, explains why suggestions are advisory and where the real invariant lives (DB exclusion constraint), designs recurrence as rule + exceptions + bounded materialisation, and discusses how free/busy is served at scale (precomputed busy bitmaps per person per day, cached and invalidated on writes) and how external calendar sync (Google/Exchange) introduces eventual consistency and conflict resolution.
