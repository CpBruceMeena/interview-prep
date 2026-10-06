# Meeting Scheduler — Java Implementation

> Interval calendars per room and per person, all-or-nothing booking with ordered multi-lock acquisition, best-fit room allocation, and a sweep-line search for common free slots across time zones.

## 📦 Core Implementation

### Key Abstractions

| Type | Responsibility | Pattern |
|------|----------------|---------|
| `TimeSlot` (record) | Half-open `[start, end)` over `Instant`; `overlaps`, `clip` | Value object |
| `Participant` (record) | Id, `ZoneId`, local working hours; `offHours(window)` | Value object |
| `IntervalCalendar` | Non-overlapping entries of ONE room or person, keyed by start; own `ReentrantLock` | Interval set |
| `Meeting` | Organizer, attendees, room, slot, status | Entity |
| `RoomAllocationStrategy` / `BestFitRoomStrategy` | Rank rooms that fit headcount and features | Strategy |
| `MeetingScheduler` | `schedule`, `cancel`, `reschedule`, `findFreeSlots`, `proposeEarliest`, `agenda` | Facade |

### 1. Interval conflicts

`TimeSlot.overlaps` is half-open: `start < o.end && o.start < end`. So 9:00–10:00 and 10:00–11:00 are back-to-back, not a conflict. (A closed-interval check here blocks every back-to-back meeting.)

Each calendar stores entries in a `TreeMap<Instant, CalendarEntry>` keyed by start. Because entries never overlap, a new slot can only collide with:

- `floorEntry(start)`: the last meeting starting at or before it (catches a long earlier meeting such as 8:00–12:00 against 11:00–11:30), and
- `higherEntry(start)`: the first meeting starting after it (collides if it starts before the new slot ends).

That makes `conflict()` O(log n). `entries(window)` uses `floorKey` + `subMap` for an agenda query in O(log n + k).

### 2. All-or-nothing booking across the room and every attendee

```java
List<IntervalCalendar> involved = calendarsFor(req.attendeeIds(), room.id());
Meeting booked = withLocks(involved, () -> {
    for (String pid : req.attendeeIds())                      // any busy person: fail the whole request
        calendar(personKey(pid)).conflict(req.slot()).ifPresent(c -> { throw new ConflictException(...); });
    if (calendar(roomKey(room.id())).conflict(req.slot()).isPresent()) return null;   // try next room
    involved.forEach(c -> c.add(id, req.slot()));             // insert everywhere
    ...
});
```

`withLocks` sorts the calendars by key (`"person:alice"`, `"room:Board"`, …) and locks them in that order. Every booking acquires locks in the same global order, so two bookings that share people can never deadlock (no cycle in the wait-for graph). Because every involved lock is held from the first check to the last insert, check-then-insert is atomic: a conflict anywhere means **nothing** is written. Meetings with disjoint people and rooms proceed in parallel; there is no global lock.

`reschedule` takes the same locks, removes the meeting's own entries (so it does not conflict with itself), checks the new slot everywhere, and either inserts the new entries or puts the old ones back. Other threads never see the intermediate state because the locks are held throughout. `cancel` removes the entries from **every** calendar, the organizer's included.

### 3. Room allocation

`BestFitRoomStrategy` filters rooms that seat everyone and have the required features, then orders them by capacity, then by number of features, then id. The scheduler tries them in that order under the locks and takes the first that is free. Best fit keeps big rooms available for big meetings; it is a Strategy so a building can swap in "closest to the organizer's desk" or "same floor as most attendees".

### 4. Common free slots across attendees

```text
busy = for each attendee: offHours(window) in their own zone + their meetings in the window
sort busy by start                                  O(N log N)
cursor = window.start
for b in busy: if b.start > cursor → gap [cursor, b.start);  cursor = max(cursor, b.end)
tail gap [cursor, window.end)
emit grid-aligned (15 min) slots of the requested length inside each gap
```

Working hours are computed per participant with `LocalDate.atStartOfDay(zone)` and `atTime(...).atZone(zone)`, which handles DST transitions correctly. In the self-check, Alice (New York, 14:00–22:00 UTC in January) and Bob (London, 09:00–17:00 UTC) overlap only 14:00–17:00 UTC; with their meetings removed the 60-minute answer is exactly 16:00–17:00 UTC.

`proposeEarliest` walks those candidate slots in time order and returns the first one where a best-fit room is also free. It is **advisory**: the caller books it with `schedule()`, which re-checks everything under locks.

## 🔧 Where to extend

| Requirement | Change |
|-------------|--------|
| RSVP (accept/decline) | Per-attendee status on `Meeting`; decide whether *tentative* blocks the calendar (Google: yes, shown as busy) |
| Optional attendees | Compute gaps for required attendees only, then rank slots by how many optional attendees are free |
| Recurring meetings | Store the series (RRULE) and expand into instances over a horizon; book each instance through the same all-or-nothing path; exceptions override single instances |
| Buffer between meetings | Inflate each busy interval by the buffer before the sweep |
| Room hold expiry / no-show release | Release the room if nobody checks in within 10 minutes |
| Different working hours / holidays | Already per `Participant`; add a holiday calendar to `offHours` |

## ▶️ How to Run

```bash
cd java-low-level-design/meeting-scheduler
java MeetingSchedulerSystem.java      # JDK 17+; runs the self-checks, exits non-zero on failure
```

`MeetingDemo.run()` covers half-open intervals and neighbour checks, best-fit allocation, atomic booking with no partial writes, cancel/reschedule rollback, cross-time-zone free slots, room-aware proposals, and a 12-thread random booking storm followed by invariant checks (no person or room double-booked, calendars consistent, no deadlock).

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | `RoomAllocationStrategy` | Swap best-fit for proximity or floor-based allocation |
| **Facade** | `MeetingScheduler` | One API over calendars, rooms and people |
| **Value objects** | `TimeSlot`, `Participant`, `MeetingRequest`, `Proposal` records | Immutable, validated at construction, trivially testable |
| **Ordered locking** | `withLocks` | Deadlock-free atomic updates over several aggregates |

## 📄 Full Source

<!-- source: MeetingSchedulerSystem.java -->
```java
/**
 * Meeting Scheduler - Low Level Design (Java 17+)
 * ------------------------------------------------
 * Run:  java MeetingSchedulerSystem.java   (single-file source launcher; main self-checks and
 *                                            throws AssertionError if any behaviour breaks)
 *
 * Scope: rooms and participants each own a calendar. Schedule a meeting (explicit room or
 * auto-allocated), cancel, reschedule, find common free slots across attendees in different
 * time zones, and propose the earliest slot that also has a suitable room.
 *
 * Key design decisions:
 *   - Time is an Instant; a TimeSlot is HALF-OPEN [start, end), so 9:00-10:00 and 10:00-11:00
 *     do not conflict. Working hours are evaluated in each participant's own ZoneId.
 *   - IntervalCalendar = TreeMap of non-overlapping entries keyed by start. Only the floor and
 *     higher neighbours of a new start can overlap it, so the conflict check is O(log n).
 *   - Booking is all-or-nothing across the room and every attendee. The scheduler locks all the
 *     involved calendars in one canonical order (sorted by key), checks every one, then inserts
 *     into every one. Ordered acquisition makes deadlock impossible; holding all the locks makes
 *     check-then-insert atomic. No global lock: meetings with disjoint people and rooms run in
 *     parallel.
 *   - Free-slot search: collect busy intervals of all attendees (meetings + outside working
 *     hours), sort, sweep once to find gaps. O(N log N) in the number of busy intervals.
 *   - Room choice is a Strategy (best fit: smallest room that seats everyone and has the
 *     required features), so a big room is not wasted on a 1:1.
 */

import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/** Entry point. Must be the first top-level class: `java File.java` runs the first class it finds. */
public class MeetingSchedulerSystem {
    public static void main(String[] args) throws Exception {
        MeetingDemo.run();
    }
}

// ============================================================
// VALUE TYPES
// ============================================================

/** Half-open [start, end). */
record TimeSlot(Instant start, Instant end) {
    TimeSlot {
        Objects.requireNonNull(start);
        Objects.requireNonNull(end);
        if (!end.isAfter(start)) throw new IllegalArgumentException("end must be after start");
    }

    static TimeSlot of(Instant start, Duration d) { return new TimeSlot(start, start.plus(d)); }

    Duration duration() { return Duration.between(start, end); }

    boolean overlaps(TimeSlot o) { return start.isBefore(o.end) && o.start.isBefore(end); }

    /** Intersection with another slot, if non-empty. */
    Optional<TimeSlot> clip(TimeSlot o) {
        Instant s = start.isAfter(o.start) ? start : o.start;
        Instant e = end.isBefore(o.end) ? end : o.end;
        return e.isAfter(s) ? Optional.of(new TimeSlot(s, e)) : Optional.empty();
    }
}

enum Feature { VIDEO_CONF, WHITEBOARD, PROJECTOR }

record Room(String id, int capacity, Set<Feature> features) {
    Room { features = Set.copyOf(features); }
    boolean fits(int headcount, Set<Feature> required) { return capacity >= headcount && features.containsAll(required); }
}

/** Working hours are local to the participant's zone, Monday to Friday. */
record Participant(String id, ZoneId zone, LocalTime workStart, LocalTime workEnd) {
    Participant(String id, ZoneId zone) { this(id, zone, LocalTime.of(9, 0), LocalTime.of(17, 0)); }

    /** Intervals inside the window when this person is NOT working (nights, weekends). */
    List<TimeSlot> offHours(TimeSlot window) {
        List<TimeSlot> out = new ArrayList<>();
        LocalDate day = window.start().atZone(zone).toLocalDate().minusDays(1);
        LocalDate last = window.end().atZone(zone).toLocalDate().plusDays(1);
        for (; !day.isAfter(last); day = day.plusDays(1)) {
            Instant dayStart = day.atStartOfDay(zone).toInstant();          // DST-safe
            Instant dayEnd = day.plusDays(1).atStartOfDay(zone).toInstant();
            DayOfWeek dow = day.getDayOfWeek();
            if (dow == DayOfWeek.SATURDAY || dow == DayOfWeek.SUNDAY) {
                new TimeSlot(dayStart, dayEnd).clip(window).ifPresent(out::add);
            } else {
                Instant ws = day.atTime(workStart).atZone(zone).toInstant();
                Instant we = day.atTime(workEnd).atZone(zone).toInstant();
                new TimeSlot(dayStart, ws).clip(window).ifPresent(out::add);
                new TimeSlot(we, dayEnd).clip(window).ifPresent(out::add);
            }
        }
        return out;
    }
}

enum MeetingStatus { SCHEDULED, CANCELLED }

/** What the caller asks for. roomId == null means "pick a room for me". */
record MeetingRequest(String title, String organizerId, Set<String> attendeeIds, TimeSlot slot,
                      Set<Feature> requiredFeatures, String roomId) {
    MeetingRequest {
        Set<String> all = new TreeSet<>(attendeeIds);
        all.add(organizerId);                                  // organizer always attends
        attendeeIds = Collections.unmodifiableSet(all);
        requiredFeatures = Set.copyOf(requiredFeatures);
    }
}

record Proposal(TimeSlot slot, Room room) {}

class ConflictException extends RuntimeException {
    private static final long serialVersionUID = 1L;
    ConflictException(String msg) { super(msg); }
}

// ============================================================
// MEETING
// ============================================================

final class Meeting {
    private final String id;
    private final String title;
    private final String organizerId;
    private final Set<String> attendeeIds;
    private final String roomId;
    // Mutated only while the scheduler holds the locks of ALL this meeting's calendars.
    private volatile TimeSlot slot;
    private volatile MeetingStatus status = MeetingStatus.SCHEDULED;

    Meeting(String id, String title, String organizerId, Set<String> attendeeIds, String roomId, TimeSlot slot) {
        this.id = id;
        this.title = title;
        this.organizerId = organizerId;
        this.attendeeIds = Set.copyOf(attendeeIds);
        this.roomId = roomId;
        this.slot = slot;
    }

    String id() { return id; }
    String title() { return title; }
    String organizerId() { return organizerId; }
    Set<String> attendeeIds() { return attendeeIds; }
    String roomId() { return roomId; }
    TimeSlot slot() { return slot; }
    MeetingStatus status() { return status; }
    void moveTo(TimeSlot s) { slot = s; }
    void markCancelled() { status = MeetingStatus.CANCELLED; }

    @Override public String toString() { return "%s '%s' %s %s [%s]".formatted(id, title, roomId, slot, status); }
}

// ============================================================
// INTERVAL CALENDAR (one per room and per participant)
// ============================================================

record CalendarEntry(String meetingId, TimeSlot slot) {}

final class IntervalCalendar {
    private final String key;                                   // "person:alice", "room:R1" - defines lock order
    final ReentrantLock lock = new ReentrantLock();
    private final TreeMap<Instant, CalendarEntry> byStart = new TreeMap<>();   // guarded by lock

    IntervalCalendar(String key) { this.key = key; }
    String key() { return key; }

    /** The entry that overlaps the slot, if any. O(log n): only two neighbours can overlap. */
    Optional<CalendarEntry> conflict(TimeSlot s) {
        lock.lock();
        try {
            Map.Entry<Instant, CalendarEntry> before = byStart.floorEntry(s.start());
            if (before != null && before.getValue().slot().overlaps(s)) return Optional.of(before.getValue());
            Map.Entry<Instant, CalendarEntry> after = byStart.higherEntry(s.start());
            if (after != null && after.getKey().isBefore(s.end())) return Optional.of(after.getValue());
            return Optional.empty();
        } finally {
            lock.unlock();
        }
    }

    /** Caller must already have checked conflict() under the same lock hold. */
    void add(String meetingId, TimeSlot s) {
        lock.lock();
        try {
            byStart.put(s.start(), new CalendarEntry(meetingId, s));
        } finally {
            lock.unlock();
        }
    }

    void remove(String meetingId, TimeSlot s) {
        lock.lock();
        try {
            CalendarEntry e = byStart.get(s.start());
            if (e != null && e.meetingId().equals(meetingId)) byStart.remove(s.start());
        } finally {
            lock.unlock();
        }
    }

    /** Entries overlapping the window, in start order. */
    List<CalendarEntry> entries(TimeSlot window) {
        lock.lock();
        try {
            Instant from = Optional.ofNullable(byStart.floorKey(window.start())).orElse(window.start());
            return byStart.subMap(from, true, window.end(), false).values().stream()
                    .filter(e -> e.slot().overlaps(window)).collect(Collectors.toList());
        } finally {
            lock.unlock();
        }
    }
}

// ============================================================
// ROOM ALLOCATION (Strategy)
// ============================================================

interface RoomAllocationStrategy {
    /** Rooms that satisfy the request, best first. */
    List<Room> rank(Collection<Room> rooms, int headcount, Set<Feature> required);
}

/** Smallest room that fits, then fewest unneeded features, then id (deterministic). */
final class BestFitRoomStrategy implements RoomAllocationStrategy {
    @Override
    public List<Room> rank(Collection<Room> rooms, int headcount, Set<Feature> required) {
        return rooms.stream()
                .filter(r -> r.fits(headcount, required))
                .sorted(Comparator.comparingInt(Room::capacity)
                        .thenComparingInt((Room r) -> r.features().size())
                        .thenComparing(Room::id))
                .collect(Collectors.toList());
    }
}

// ============================================================
// SCHEDULER (Facade)
// ============================================================

final class MeetingScheduler {
    static final Duration GRID = Duration.ofMinutes(15);

    private final Map<String, Room> rooms;
    private final Map<String, Participant> people;
    private final Map<String, IntervalCalendar> calendars;     // fixed after construction
    private final Map<String, Meeting> meetings = new ConcurrentHashMap<>();
    private final RoomAllocationStrategy allocation;
    private final AtomicLong ids = new AtomicLong();

    MeetingScheduler(List<Room> rooms, List<Participant> people, RoomAllocationStrategy allocation) {
        this.rooms = rooms.stream().collect(Collectors.toUnmodifiableMap(Room::id, r -> r));
        this.people = people.stream().collect(Collectors.toUnmodifiableMap(Participant::id, p -> p));
        Map<String, IntervalCalendar> cals = new HashMap<>();
        rooms.forEach(r -> cals.put(roomKey(r.id()), new IntervalCalendar(roomKey(r.id()))));
        people.forEach(p -> cals.put(personKey(p.id()), new IntervalCalendar(personKey(p.id()))));
        this.calendars = Map.copyOf(cals);
        this.allocation = allocation;
    }

    /** Book atomically across the room and every attendee, or throw ConflictException and change nothing. */
    Meeting schedule(MeetingRequest req) {
        req.attendeeIds().forEach(this::person);
        int headcount = req.attendeeIds().size();
        List<Room> candidates;
        if (req.roomId() != null) {
            Room r = room(req.roomId());
            if (!r.fits(headcount, req.requiredFeatures())) {
                throw new IllegalArgumentException(r.id() + " does not fit " + headcount + " with " + req.requiredFeatures());
            }
            candidates = List.of(r);
        } else {
            candidates = allocation.rank(rooms.values(), headcount, req.requiredFeatures());
            if (candidates.isEmpty()) throw new IllegalArgumentException("no room fits " + headcount + " with " + req.requiredFeatures());
        }
        String id = "M-" + ids.incrementAndGet();
        for (Room room : candidates) {
            List<IntervalCalendar> involved = calendarsFor(req.attendeeIds(), room.id());
            Meeting booked = withLocks(involved, () -> {
                for (String pid : req.attendeeIds()) {
                    calendar(personKey(pid)).conflict(req.slot()).ifPresent(c -> {
                        throw new ConflictException(pid + " is busy (" + c.meetingId() + ")");
                    });
                }
                if (calendar(roomKey(room.id())).conflict(req.slot()).isPresent()) return null;   // try next room
                Meeting m = new Meeting(id, req.title(), req.organizerId(), req.attendeeIds(), room.id(), req.slot());
                involved.forEach(c -> c.add(id, req.slot()));
                meetings.put(id, m);
                return m;
            });
            if (booked != null) return booked;
        }
        throw new ConflictException("no suitable room free for " + req.slot());
    }

    void cancel(String meetingId) {
        Meeting m = meeting(meetingId);
        withLocks(calendarsFor(m.attendeeIds(), m.roomId()), () -> {
            if (m.status() == MeetingStatus.CANCELLED) throw new IllegalStateException(meetingId + " already cancelled");
            calendarsFor(m.attendeeIds(), m.roomId()).forEach(c -> c.remove(m.id(), m.slot()));
            m.markCancelled();
            return null;
        });
    }

    /** Move to a new slot in the same room. Atomic: on conflict the meeting stays where it was. */
    void reschedule(String meetingId, TimeSlot newSlot) {
        Meeting m = meeting(meetingId);
        List<IntervalCalendar> involved = calendarsFor(m.attendeeIds(), m.roomId());
        withLocks(involved, () -> {
            if (m.status() == MeetingStatus.CANCELLED) throw new IllegalStateException(meetingId + " is cancelled");
            TimeSlot old = m.slot();
            involved.forEach(c -> c.remove(m.id(), old));       // so the meeting doesn't conflict with itself
            for (IntervalCalendar c : involved) {
                Optional<CalendarEntry> clash = c.conflict(newSlot);
                if (clash.isPresent()) {
                    involved.forEach(x -> x.add(m.id(), old));  // roll back; nobody saw the gap (locks held)
                    throw new ConflictException(c.key() + " is busy (" + clash.get().meetingId() + ")");
                }
            }
            involved.forEach(c -> c.add(m.id(), newSlot));
            m.moveTo(newSlot);
            return null;
        });
    }

    /**
     * Grid-aligned slots of the given length inside the window when EVERY attendee is free and
     * within their working hours. Sweep over the merged busy intervals: O(N log N).
     */
    List<TimeSlot> findFreeSlots(Set<String> attendeeIds, Duration length, TimeSlot window, int limit) {
        List<TimeSlot> out = new ArrayList<>();
        for (TimeSlot gap : commonGaps(attendeeIds, window)) {
            for (Instant s = alignUp(gap.start()); !s.plus(length).isAfter(gap.end()) && out.size() < limit; s = s.plus(GRID)) {
                out.add(TimeSlot.of(s, length));
            }
            if (out.size() >= limit) break;
        }
        return out;
    }

    /** Earliest slot where all attendees are free AND a suitable room is free. Advisory: book with schedule(). */
    Optional<Proposal> proposeEarliest(Set<String> attendeeIds, Duration length, TimeSlot window, Set<Feature> required) {
        List<Room> fitting = allocation.rank(rooms.values(), attendeeIds.size(), required);
        for (TimeSlot gap : commonGaps(attendeeIds, window)) {
            for (Instant s = alignUp(gap.start()); !s.plus(length).isAfter(gap.end()); s = s.plus(GRID)) {
                TimeSlot slot = TimeSlot.of(s, length);
                for (Room r : fitting) {
                    if (calendar(roomKey(r.id())).conflict(slot).isEmpty()) return Optional.of(new Proposal(slot, r));
                }
            }
        }
        return Optional.empty();
    }

    List<Meeting> agenda(String personId, TimeSlot window) {
        person(personId);
        return calendar(personKey(personId)).entries(window).stream()
                .map(e -> meetings.get(e.meetingId())).collect(Collectors.toList());
    }

    Meeting meeting(String id) {
        Meeting m = meetings.get(id);
        if (m == null) throw new NoSuchElementException("no meeting " + id);
        return m;
    }

    Collection<Meeting> allMeetings() { return List.copyOf(meetings.values()); }

    // ---- internals ----

    /** Merge busy time of all attendees (meetings + off-hours) and return the gaps inside the window. */
    private List<TimeSlot> commonGaps(Set<String> attendeeIds, TimeSlot window) {
        List<TimeSlot> busy = new ArrayList<>();
        for (String pid : attendeeIds) {
            busy.addAll(person(pid).offHours(window));
            calendar(personKey(pid)).entries(window).forEach(e -> busy.add(e.slot()));
        }
        busy.sort(Comparator.comparing(TimeSlot::start));
        List<TimeSlot> gaps = new ArrayList<>();
        Instant cursor = window.start();
        for (TimeSlot b : busy) {
            if (b.start().isAfter(cursor)) gaps.add(new TimeSlot(cursor, b.start()));
            if (b.end().isAfter(cursor)) cursor = b.end();
        }
        if (window.end().isAfter(cursor)) gaps.add(new TimeSlot(cursor, window.end()));
        return gaps;
    }

    private static Instant alignUp(Instant t) {
        long grid = GRID.getSeconds();
        long secs = t.getEpochSecond() + (t.getNano() > 0 ? 1 : 0);
        return Instant.ofEpochSecond(Math.floorDiv(secs + grid - 1, grid) * grid);
    }

    /** Lock every calendar in key order (deadlock-free), run, unlock in reverse. */
    private static <T> T withLocks(List<IntervalCalendar> cals, Supplier<T> action) {
        List<IntervalCalendar> ordered = cals.stream().distinct()
                .sorted(Comparator.comparing(IntervalCalendar::key)).collect(Collectors.toList());
        int locked = 0;
        try {
            for (IntervalCalendar c : ordered) { c.lock.lock(); locked++; }
            return action.get();
        } finally {
            for (int i = locked - 1; i >= 0; i--) ordered.get(i).lock.unlock();
        }
    }

    private List<IntervalCalendar> calendarsFor(Set<String> personIds, String roomId) {
        List<IntervalCalendar> l = new ArrayList<>();
        personIds.forEach(p -> l.add(calendar(personKey(p))));
        l.add(calendar(roomKey(roomId)));
        return l;
    }

    private IntervalCalendar calendar(String key) { return calendars.get(key); }
    private static String roomKey(String id) { return "room:" + id; }
    private static String personKey(String id) { return "person:" + id; }

    private Room room(String id) {
        Room r = rooms.get(id);
        if (r == null) throw new IllegalArgumentException("unknown room " + id);
        return r;
    }

    private Participant person(String id) {
        Participant p = people.get(id);
        if (p == null) throw new IllegalArgumentException("unknown participant " + id);
        return p;
    }
}

// ============================================================
// DEMO + SELF-CHECKS
// ============================================================

final class MeetingDemo {
    // Monday 11 Jan 2027: no DST in either zone. London = UTC+0, New York = UTC-5.
    static final LocalDate MONDAY = LocalDate.of(2027, 1, 11);
    static final ZoneId LONDON = ZoneId.of("Europe/London"), NEW_YORK = ZoneId.of("America/New_York");

    static Instant utc(int h, int m) { return MONDAY.atTime(h, m).toInstant(ZoneOffset.UTC); }
    static TimeSlot slot(int h1, int m1, int h2, int m2) { return new TimeSlot(utc(h1, m1), utc(h2, m2)); }

    static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError("FAILED: " + what);
        System.out.println("  ok  " + what);
    }

    static MeetingScheduler scheduler() {
        List<Room> rooms = List.of(
                new Room("Huddle", 4, Set.of(Feature.WHITEBOARD)),
                new Room("Focus", 6, Set.of(Feature.VIDEO_CONF)),
                new Room("Board", 12, Set.of(Feature.VIDEO_CONF, Feature.PROJECTOR, Feature.WHITEBOARD)));
        List<Participant> people = List.of(
                new Participant("alice", NEW_YORK), new Participant("bob", LONDON),
                new Participant("carol", LONDON), new Participant("dan", LONDON),
                new Participant("erin", LONDON));
        return new MeetingScheduler(rooms, people, new BestFitRoomStrategy());
    }

    static MeetingRequest req(String title, String organizer, Set<String> attendees, TimeSlot s, Set<Feature> f, String room) {
        return new MeetingRequest(title, organizer, attendees, s, f, room);
    }

    static void run() throws Exception {
        System.out.println("== 1. Half-open intervals and O(log n) calendar ==");
        {
            check(!slot(9, 0, 10, 0).overlaps(slot(10, 0, 11, 0)), "9-10 and 10-11 do not overlap");
            IntervalCalendar cal = new IntervalCalendar("room:test");
            cal.add("long", slot(8, 0, 12, 0));
            check(cal.conflict(slot(11, 0, 11, 30)).map(CalendarEntry::meetingId).equals(Optional.of("long")),
                  "floor neighbour 8-12 detected for 11:00-11:30");
            check(cal.conflict(slot(7, 0, 8, 0)).isEmpty() && cal.conflict(slot(12, 0, 13, 0)).isEmpty(),
                  "touching slots before and after are free");
            check(cal.conflict(slot(7, 30, 8, 15)).isPresent(), "higher neighbour detected for 7:30-8:15");
        }

        System.out.println("== 2. Room allocation: best fit ==");
        {
            MeetingScheduler s = scheduler();
            Meeting a = s.schedule(req("1:1", "bob", Set.of("carol"), slot(10, 0, 11, 0), Set.of(), null));
            check(a.roomId().equals("Huddle"), "2 people, no features -> smallest room (Huddle)");
            Meeting b = s.schedule(req("Sync", "dan", Set.of("erin"), slot(10, 0, 11, 0), Set.of(), null));
            check(b.roomId().equals("Focus"), "Huddle busy -> next best fit (Focus)");
            Meeting c = s.schedule(req("Demo", "alice", Set.of(), slot(15, 0, 16, 0), Set.of(Feature.PROJECTOR), null));
            check(c.roomId().equals("Board"), "projector required -> Board");
            check(throwsIAE(() -> s.schedule(req("All hands", "bob", Set.of("alice", "carol", "dan", "erin"),
                    slot(12, 0, 13, 0), Set.of(), "Huddle"))),
                  "5 people do not fit the 4-seat Huddle");
        }

        System.out.println("== 3. Atomic booking: a busy attendee blocks the whole meeting ==");
        {
            MeetingScheduler s = scheduler();
            s.schedule(req("Bob busy", "bob", Set.of(), slot(14, 0, 15, 0), Set.of(), "Focus"));
            check(throwsConflict(() -> s.schedule(req("Team", "carol", Set.of("bob", "dan"), slot(14, 30, 15, 30), Set.of(), "Board"))),
                  "bob double-booked -> ConflictException");
            check(s.agenda("carol", slot(0, 0, 23, 59)).isEmpty() && s.agenda("dan", slot(0, 0, 23, 59)).isEmpty(),
                  "no partial writes: carol and dan calendars untouched");
            Meeting ok = s.schedule(req("Team", "carol", Set.of("bob", "dan"), slot(15, 0, 16, 0), Set.of(), "Board"));
            check(ok.status() == MeetingStatus.SCHEDULED, "back-to-back with bob's 14-15 is fine");
        }

        System.out.println("== 4. Cancel and reschedule ==");
        {
            MeetingScheduler s = scheduler();
            Meeting m = s.schedule(req("Plan", "bob", Set.of("carol"), slot(10, 0, 11, 0), Set.of(), "Focus"));
            s.cancel(m.id());
            check(s.agenda("bob", slot(0, 0, 23, 0)).isEmpty(), "cancel frees the ORGANIZER's calendar too");
            check(throwsISE(() -> s.cancel(m.id())), "double cancel rejected");
            Meeting again = s.schedule(req("Plan", "bob", Set.of("carol"), slot(10, 0, 11, 0), Set.of(), "Focus"));
            Meeting blocker = s.schedule(req("Carol 1:1", "carol", Set.of("dan"), slot(13, 0, 14, 0), Set.of(), "Huddle"));
            check(throwsConflict(() -> s.reschedule(again.id(), slot(13, 30, 14, 30))), "reschedule into carol's 1:1 fails");
            check(again.slot().equals(slot(10, 0, 11, 0)) && s.agenda("bob", slot(10, 0, 11, 0)).size() == 1,
                  "failed reschedule leaves the meeting where it was");
            s.reschedule(again.id(), slot(10, 30, 11, 30));
            check(again.slot().equals(slot(10, 30, 11, 30)), "reschedule overlapping its own old slot works");
            check(blocker.status() == MeetingStatus.SCHEDULED, "other meetings untouched");
        }

        System.out.println("== 5. Free slots across time zones ==");
        {
            MeetingScheduler s = scheduler();
            // Working-hours overlap: London 09-17 UTC, New York 14-22 UTC -> 14:00-17:00 UTC.
            s.schedule(req("Alice busy", "alice", Set.of(), slot(14, 0, 15, 0), Set.of(), "Huddle"));
            s.schedule(req("Bob busy", "bob", Set.of(), slot(15, 30, 16, 0), Set.of(), "Focus"));
            TimeSlot day = new TimeSlot(utc(0, 0), utc(0, 0).plus(Duration.ofDays(1)));
            List<TimeSlot> halfHours = s.findFreeSlots(Set.of("alice", "bob"), Duration.ofMinutes(30), day, 10);
            check(halfHours.equals(List.of(slot(15, 0, 15, 30), slot(16, 0, 16, 30), slot(16, 15, 16, 45), slot(16, 30, 17, 0))),
                  "30-min slots: 15:00, then 16:00/16:15/16:30 on the 15-min grid");
            List<TimeSlot> hour = s.findFreeSlots(Set.of("alice", "bob"), Duration.ofHours(1), day, 10);
            check(hour.equals(List.of(slot(16, 0, 17, 0))), "only one 60-min slot: 16:00-17:00 UTC");
            TimeSlot saturday = new TimeSlot(utc(0, 0).plus(Duration.ofDays(5)), utc(0, 0).plus(Duration.ofDays(6)));
            check(s.findFreeSlots(Set.of("bob"), Duration.ofMinutes(30), saturday, 5).isEmpty(), "nobody works on Saturday");

            // With a room requirement: the only VIDEO_CONF rooms are Focus (busy 15:30-16:00) and Board.
            s.schedule(req("Board taken", "carol", Set.of(), slot(15, 0, 15, 30), Set.of(), "Board"));
            s.schedule(req("Focus taken", "dan", Set.of(), slot(15, 0, 15, 30), Set.of(), "Focus"));
            Optional<Proposal> p = s.proposeEarliest(Set.of("alice", "bob"), Duration.ofMinutes(30), day, Set.of(Feature.VIDEO_CONF));
            check(p.isPresent() && p.get().slot().equals(slot(16, 0, 16, 30)) && p.get().room().id().equals("Focus"),
                  "earliest with VIDEO_CONF skips 15:00 (both video rooms busy) -> 16:00 in Focus");
            Meeting booked = s.schedule(req("Booked", "alice", Set.of("bob"), p.get().slot(), Set.of(Feature.VIDEO_CONF), null));
            check(booked.roomId().equals("Focus"), "booking the proposal succeeds");
        }

        System.out.println("== 6. Concurrency: random bookings from 12 threads ==");
        {
            MeetingScheduler s = scheduler();
            List<String> ids = List.of("alice", "bob", "carol", "dan", "erin");
            ExecutorService pool = Executors.newFixedThreadPool(12);
            CountDownLatch go = new CountDownLatch(1);
            List<Future<int[]>> fs = new ArrayList<>();
            for (int t = 0; t < 12; t++) {
                final int seed = t;
                fs.add(pool.submit(() -> {
                    Random rnd = new Random(seed);
                    go.await();
                    int ok = 0, conflicts = 0;
                    for (int i = 0; i < 400; i++) {
                        Set<String> who = new HashSet<>();
                        for (int k = 0; k < 1 + rnd.nextInt(3); k++) who.add(ids.get(rnd.nextInt(ids.size())));
                        String org = who.iterator().next();
                        int startQ = rnd.nextInt(40);            // quarter-hours from 08:00 UTC
                        TimeSlot sl = TimeSlot.of(utc(8, 0).plus(quarters(startQ)), quarters(1 + rnd.nextInt(4)));
                        try {
                            Meeting m = s.schedule(req("r", org, who, sl, Set.of(), null));
                            ok++;
                            if (rnd.nextInt(4) == 0) s.cancel(m.id());
                            else if (rnd.nextInt(4) == 0) {
                                try { s.reschedule(m.id(), TimeSlot.of(sl.start().plus(quarters(1)), sl.duration())); }
                                catch (ConflictException ignored) { }
                            }
                        } catch (ConflictException e) {
                            conflicts++;
                        }
                    }
                    return new int[] {ok, conflicts};
                }));
            }
            go.countDown();
            int ok = 0;
            for (Future<int[]> f : fs) ok += f.get(20, TimeUnit.SECONDS)[0];   // timeout would mean deadlock
            pool.shutdown();
            List<Meeting> live = s.allMeetings().stream().filter(m -> m.status() == MeetingStatus.SCHEDULED).collect(Collectors.toList());
            check(ok > 0 && noOverlaps(live, m -> m.attendeeIds()) && noOverlaps(live, m -> Set.of("room:" + m.roomId())),
                  ok + " bookings across 12 threads, no person or room ever double-booked, no deadlock");
            boolean calendarsAgree = ids.stream().allMatch(p ->
                    s.agenda(p, new TimeSlot(utc(0, 0), utc(23, 0))).stream().allMatch(m -> m.status() == MeetingStatus.SCHEDULED
                            && m.attendeeIds().contains(p))
                    && s.agenda(p, new TimeSlot(utc(0, 0), utc(23, 0))).size()
                       == live.stream().filter(m -> m.attendeeIds().contains(p)).count());
            check(calendarsAgree, "every person's calendar matches the live meetings exactly");
        }

        System.out.println("\nAll meeting scheduler checks passed.");
    }

    static Duration quarters(int n) { return MeetingScheduler.GRID.multipliedBy(n); }

    static boolean noOverlaps(List<Meeting> live, java.util.function.Function<Meeting, Set<String>> owners) {
        Map<String, List<TimeSlot>> byOwner = new HashMap<>();
        for (Meeting m : live) for (String o : owners.apply(m)) byOwner.computeIfAbsent(o, k -> new ArrayList<>()).add(m.slot());
        for (List<TimeSlot> l : byOwner.values()) {
            l.sort(Comparator.comparing(TimeSlot::start));
            for (int i = 1; i < l.size(); i++) if (l.get(i - 1).overlaps(l.get(i))) return false;
        }
        return true;
    }

    static boolean throwsIAE(Runnable r) { try { r.run(); return false; } catch (IllegalArgumentException e) { return true; } }
    static boolean throwsISE(Runnable r) { try { r.run(); return false; } catch (IllegalStateException e) { return true; } }
    static boolean throwsConflict(Runnable r) { try { r.run(); return false; } catch (ConflictException e) { return true; } }
}
```
<!-- /source -->
