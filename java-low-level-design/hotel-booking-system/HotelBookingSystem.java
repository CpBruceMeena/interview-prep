/**
 * Hotel Booking System - Low Level Design (Java 17+)
 * ---------------------------------------------------
 * Run:  java HotelBookingSystem.java   (single-file source launcher; main self-checks and
 *                                        throws AssertionError if any behaviour breaks)
 *
 * Scope: search availability by room type and dates, hold -> pay -> confirm, cancel with a
 * refund policy, check in / check out, multi-room (group) bookings, hold expiry.
 *
 * Key design decisions:
 *   - Stays are HALF-OPEN date ranges [checkIn, checkOut): a guest leaving on the 10th and one
 *     arriving on the 10th do not conflict.
 *   - Every booking is assigned specific rooms at hold time. Each room owns a RoomCalendar:
 *     a TreeMap of non-overlapping reservations keyed by check-in date. Because existing
 *     reservations never overlap, a new range can only collide with its floor and higher
 *     neighbours, so the conflict check is O(log n).
 *   - Double-booking prevention = check-and-insert under the ROOM's lock (tryReserve). No
 *     global lock: bookings for different rooms never contend. This is the in-memory twin of
 *     a DB exclusion constraint / unique index per (room, night).
 *   - Two-phase booking: HELD (rooms reserved, price locked, expires after a TTL) ->
 *     CONFIRMED after payment. Exactly one thread wins each state transition, and only that
 *     thread releases the rooms, so rooms are never released twice.
 *   - Money is BigDecimal (scale 2, HALF_EVEN). Time comes from an injected Clock so pricing,
 *     refunds and expiry are deterministic in tests.
 *   - Holds are idempotent per client key: retrying the same request returns the same booking.
 */

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.Collectors;

/** Entry point. Must be the first top-level class: `java File.java` runs the first class it finds. */
public class HotelBookingSystem {
    public static void main(String[] args) throws Exception {
        HotelDemo.run();
    }
}

// ============================================================
// VALUE TYPES
// ============================================================

enum RoomType {
    SINGLE("100.00"), DOUBLE("150.00"), SUITE("350.00");

    final BigDecimal nightlyRate;
    RoomType(String rate) { this.nightlyRate = new BigDecimal(rate); }
}

enum LoyaltyTier {
    NONE("0.00"), SILVER("0.05"), GOLD("0.10"), PLATINUM("0.15");

    final BigDecimal discount;
    LoyaltyTier(String d) { this.discount = new BigDecimal(d); }
}

record Guest(String id, String name, LoyaltyTier tier) {}

record Room(String id, RoomType type, int floor) {}

/** Half-open [checkIn, checkOut). checkOut is the departure morning, not a night stayed. */
record DateRange(LocalDate checkIn, LocalDate checkOut) {
    DateRange {
        Objects.requireNonNull(checkIn);
        Objects.requireNonNull(checkOut);
        if (!checkOut.isAfter(checkIn)) throw new IllegalArgumentException("checkOut must be after checkIn");
    }

    long nights() { return ChronoUnit.DAYS.between(checkIn, checkOut); }

    boolean overlaps(DateRange o) {
        return checkIn.isBefore(o.checkOut) && o.checkIn.isBefore(checkOut);
    }
}

final class Money {
    private Money() {}
    static BigDecimal of(BigDecimal v) { return v.setScale(2, RoundingMode.HALF_EVEN); }
}

// ============================================================
// PRICING (Strategy + Decorator)
// ============================================================

interface PricingStrategy {
    /** Price for ONE room for the whole stay. */
    BigDecimal price(RoomType type, DateRange stay, Guest guest);
}

/** Nightly rate, plus a surcharge for Friday and Saturday nights. */
final class NightlyRatePricing implements PricingStrategy {
    private final BigDecimal weekendSurcharge;
    NightlyRatePricing(BigDecimal weekendSurcharge) { this.weekendSurcharge = weekendSurcharge; }

    @Override
    public BigDecimal price(RoomType type, DateRange stay, Guest guest) {
        BigDecimal total = BigDecimal.ZERO;
        for (LocalDate night = stay.checkIn(); night.isBefore(stay.checkOut()); night = night.plusDays(1)) {
            DayOfWeek d = night.getDayOfWeek();
            boolean weekend = d == DayOfWeek.FRIDAY || d == DayOfWeek.SATURDAY;
            total = total.add(type.nightlyRate).add(weekend ? weekendSurcharge : BigDecimal.ZERO);
        }
        return Money.of(total);
    }
}

/** Decorator: applies the guest's loyalty discount on top of whatever it wraps. */
final class LoyaltyDiscountPricing implements PricingStrategy {
    private final PricingStrategy inner;
    LoyaltyDiscountPricing(PricingStrategy inner) { this.inner = inner; }

    @Override
    public BigDecimal price(RoomType type, DateRange stay, Guest guest) {
        BigDecimal base = inner.price(type, stay, guest);
        return Money.of(base.multiply(BigDecimal.ONE.subtract(guest.tier().discount)));
    }
}

// ============================================================
// CANCELLATION POLICY
// ============================================================

enum CancellationPolicy {
    /** Full refund up to 48h before check-in time, otherwise the first night is charged. */
    FLEXIBLE(48),
    /** Full refund up to 7 days before, otherwise the first night is charged. */
    MODERATE(168),
    NON_REFUNDABLE(-1);

    private final int freeCancelHours;
    CancellationPolicy(int h) { this.freeCancelHours = h; }

    BigDecimal refund(BigDecimal total, BigDecimal firstNight, Duration beforeCheckIn) {
        if (this == NON_REFUNDABLE) return Money.of(BigDecimal.ZERO);
        if (beforeCheckIn.toHours() >= freeCancelHours) return total;
        return Money.of(total.subtract(firstNight).max(BigDecimal.ZERO));
    }
}

// ============================================================
// BOOKING (lifecycle state machine)
// ============================================================

enum BookingStatus {
    HELD, CONFIRMED, CHECKED_IN, CHECKED_OUT, CANCELLED, EXPIRED;

    boolean canMoveTo(BookingStatus next) {
        return switch (this) {
            case HELD -> next == CONFIRMED || next == CANCELLED || next == EXPIRED;
            case CONFIRMED -> next == CHECKED_IN || next == CANCELLED;
            case CHECKED_IN -> next == CHECKED_OUT;
            case CHECKED_OUT, CANCELLED, EXPIRED -> false;
        };
    }
}

final class Booking {
    private final String id;
    private final Guest guest;
    private final RoomType roomType;
    private final List<String> roomIds;
    private final DateRange stay;
    private final BigDecimal total;           // price locked at hold time
    private final BigDecimal firstNight;      // basis for late-cancellation penalty
    private final CancellationPolicy policy;
    private final Instant holdExpiresAt;
    private BookingStatus status = BookingStatus.HELD;   // guarded by this

    Booking(String id, Guest guest, RoomType roomType, List<String> roomIds, DateRange stay,
            BigDecimal total, BigDecimal firstNight, CancellationPolicy policy, Instant holdExpiresAt) {
        this.id = id;
        this.guest = guest;
        this.roomType = roomType;
        this.roomIds = List.copyOf(roomIds);
        this.stay = stay;
        this.total = total;
        this.firstNight = firstNight;
        this.policy = policy;
        this.holdExpiresAt = holdExpiresAt;
    }

    String id() { return id; }
    Guest guest() { return guest; }
    RoomType roomType() { return roomType; }
    List<String> roomIds() { return roomIds; }
    DateRange stay() { return stay; }
    BigDecimal total() { return total; }
    BigDecimal firstNight() { return firstNight; }
    CancellationPolicy policy() { return policy; }
    Instant holdExpiresAt() { return holdExpiresAt; }
    synchronized BookingStatus status() { return status; }

    /** Atomic compare-and-set on the status. Returns false if another thread got there first. */
    synchronized boolean transition(BookingStatus expected, BookingStatus next) {
        if (status != expected) return false;
        if (!status.canMoveTo(next)) throw new IllegalStateException(status + " -> " + next + " not allowed");
        status = next;
        return true;
    }

    /** Transition from whatever the current state is, or throw if that move is illegal. */
    synchronized BookingStatus moveTo(BookingStatus next) {
        if (!status.canMoveTo(next)) {
            throw new IllegalStateException("booking " + id + ": " + status + " -> " + next + " not allowed");
        }
        BookingStatus prev = status;
        status = next;
        return prev;
    }

    boolean sameRequest(Guest g, RoomType t, DateRange s, int count) {
        return guest.id().equals(g.id()) && roomType == t && stay.equals(s) && roomIds.size() == count;
    }

    @Override
    public String toString() {
        return "%s %s %s x%d %s..%s %s [%s]".formatted(id, guest.name(), roomType, roomIds.size(),
                stay.checkIn(), stay.checkOut(), total, status());
    }
}

class NoAvailabilityException extends RuntimeException {
    private static final long serialVersionUID = 1L;
    NoAvailabilityException(String msg) { super(msg); }
}

// ============================================================
// PER-ROOM CALENDAR (interval set, O(log n) conflict check)
// ============================================================

record Reservation(String bookingId, DateRange range) {}

final class RoomCalendar {
    private final Room room;
    private final TreeMap<LocalDate, Reservation> byCheckIn = new TreeMap<>();   // guarded by this

    RoomCalendar(Room room) { this.room = room; }

    Room room() { return room; }

    synchronized boolean isFree(DateRange r) {
        // Existing reservations never overlap each other, so only the reservation starting at or
        // before r.checkIn and the first one starting after it can possibly overlap r.
        Map.Entry<LocalDate, Reservation> before = byCheckIn.floorEntry(r.checkIn());
        if (before != null && before.getValue().range().overlaps(r)) return false;
        Map.Entry<LocalDate, Reservation> after = byCheckIn.higherEntry(r.checkIn());
        return after == null || !after.getKey().isBefore(r.checkOut());
    }

    /** Check-and-insert as one atomic step: the heart of double-booking prevention. */
    synchronized boolean tryReserve(String bookingId, DateRange r) {
        if (!isFree(r)) return false;
        byCheckIn.put(r.checkIn(), new Reservation(bookingId, r));
        return true;
    }

    synchronized void release(String bookingId, DateRange r) {
        Reservation existing = byCheckIn.get(r.checkIn());
        if (existing != null && existing.bookingId().equals(bookingId)) byCheckIn.remove(r.checkIn());
    }

    synchronized List<Reservation> reservations() { return List.copyOf(byCheckIn.values()); }
}

// ============================================================
// HOTEL BOOKING SERVICE (Facade)
// ============================================================

final class HotelBookingService {
    private static final LocalTime CHECK_IN_TIME = LocalTime.of(15, 0);

    private final Map<RoomType, List<RoomCalendar>> calendarsByType;      // immutable after construction
    private final Map<String, RoomCalendar> calendarsById;
    private final PricingStrategy pricing;
    private final Clock clock;
    private final Duration holdTtl;
    private final Map<String, Booking> bookings = new ConcurrentHashMap<>();
    private final Map<String, Booking> byIdempotencyKey = new ConcurrentHashMap<>();
    private final AtomicLong ids = new AtomicLong();

    HotelBookingService(List<Room> rooms, PricingStrategy pricing, Clock clock, Duration holdTtl) {
        Map<RoomType, List<RoomCalendar>> byType = new EnumMap<>(RoomType.class);
        Map<String, RoomCalendar> byId = new HashMap<>();
        for (Room r : rooms) {
            RoomCalendar cal = new RoomCalendar(r);
            if (byId.put(r.id(), cal) != null) throw new IllegalArgumentException("duplicate room " + r.id());
            byType.computeIfAbsent(r.type(), t -> new ArrayList<>()).add(cal);
        }
        byType.replaceAll((t, list) -> List.copyOf(list));
        this.calendarsByType = Collections.unmodifiableMap(byType);
        this.calendarsById = Map.copyOf(byId);
        this.pricing = pricing;
        this.clock = clock;
        this.holdTtl = holdTtl;
    }

    /** Rooms free right now. Advisory only: hold() re-checks under each room's lock. */
    List<Room> searchAvailable(RoomType type, DateRange stay) {
        return calendarsByType.getOrDefault(type, List.of()).stream()
                .filter(c -> c.isFree(stay)).map(RoomCalendar::room).collect(Collectors.toList());
    }

    /**
     * Reserve {@code roomCount} rooms of a type, all-or-nothing, and lock the price.
     * Idempotent: the same key returns the original booking (and rejects a different request).
     */
    Booking hold(String idempotencyKey, Guest guest, RoomType type, DateRange stay,
                 int roomCount, CancellationPolicy policy) {
        if (roomCount < 1) throw new IllegalArgumentException("roomCount must be >= 1");
        if (stay.checkIn().isBefore(LocalDate.now(clock))) throw new IllegalArgumentException("check-in is in the past");
        Booking b = byIdempotencyKey.computeIfAbsent(idempotencyKey,
                k -> doHold(guest, type, stay, roomCount, policy));
        if (!b.sameRequest(guest, type, stay, roomCount)) {
            throw new IllegalArgumentException("idempotency key " + idempotencyKey + " reused for a different request");
        }
        return b;
    }

    private Booking doHold(Guest guest, RoomType type, DateRange stay, int roomCount, CancellationPolicy policy) {
        String id = "BK-" + ids.incrementAndGet();
        List<RoomCalendar> taken = new ArrayList<>();
        for (RoomCalendar cal : calendarsByType.getOrDefault(type, List.of())) {
            if (taken.size() == roomCount) break;
            if (cal.tryReserve(id, stay)) taken.add(cal);
        }
        if (taken.size() < roomCount) {
            taken.forEach(c -> c.release(id, stay));      // compensate: all-or-nothing
            throw new NoAvailabilityException("only " + taken.size() + " of " + roomCount + " " + type + " free for " + stay);
        }
        BigDecimal perRoom = pricing.price(type, stay, guest);
        BigDecimal firstNight = pricing.price(type, new DateRange(stay.checkIn(), stay.checkIn().plusDays(1)), guest);
        Booking b = new Booking(id, guest, type,
                taken.stream().map(c -> c.room().id()).collect(Collectors.toList()), stay,
                Money.of(perRoom.multiply(BigDecimal.valueOf(roomCount))),
                Money.of(firstNight.multiply(BigDecimal.valueOf(roomCount))),
                policy, clock.instant().plus(holdTtl));
        bookings.put(id, b);
        return b;
    }

    /** Called after payment succeeds. Fails if the hold already expired (rooms were released). */
    Booking confirm(String bookingId) {
        Booking b = get(bookingId);
        if (!clock.instant().isBefore(b.holdExpiresAt())) {
            if (b.transition(BookingStatus.HELD, BookingStatus.EXPIRED)) releaseRooms(b);
            throw new IllegalStateException("hold " + bookingId + " expired; payment must be voided");
        }
        if (!b.transition(BookingStatus.HELD, BookingStatus.CONFIRMED)) {
            throw new IllegalStateException("booking " + bookingId + " is " + b.status() + ", cannot confirm");
        }
        return b;
    }

    /** Cancels a HELD or CONFIRMED booking. Returns the refund (zero for an unpaid hold). */
    BigDecimal cancel(String bookingId) {
        Booking b = get(bookingId);
        BookingStatus prev = b.moveTo(BookingStatus.CANCELLED);   // throws if not cancellable
        releaseRooms(b);
        if (prev == BookingStatus.HELD) return Money.of(BigDecimal.ZERO);
        ZonedDateTime checkInAt = b.stay().checkIn().atTime(CHECK_IN_TIME).atZone(clock.getZone());
        Duration before = Duration.between(clock.instant(), checkInAt.toInstant());
        return b.policy().refund(b.total(), b.firstNight(), before);
    }

    void checkIn(String bookingId) {
        Booking b = get(bookingId);
        if (LocalDate.now(clock).isBefore(b.stay().checkIn())) throw new IllegalStateException("too early to check in");
        b.moveTo(BookingStatus.CHECKED_IN);
    }

    /** Checkout keeps the reservation on the calendar: those nights were sold. */
    void checkOut(String bookingId) { get(bookingId).moveTo(BookingStatus.CHECKED_OUT); }

    /** Sweeper: expire unpaid holds. Safe to run concurrently with confirm(): one transition wins. */
    int expireHolds() {
        Instant now = clock.instant();
        int n = 0;
        for (Booking b : bookings.values()) {
            if (!now.isBefore(b.holdExpiresAt()) && b.transition(BookingStatus.HELD, BookingStatus.EXPIRED)) {
                releaseRooms(b);
                n++;
            }
        }
        return n;
    }

    Booking get(String bookingId) {
        Booking b = bookings.get(bookingId);
        if (b == null) throw new NoSuchElementException("no booking " + bookingId);
        return b;
    }

    /** For invariant checks: every reservation on every room. */
    Map<String, List<Reservation>> reservationsByRoom() {
        Map<String, List<Reservation>> m = new TreeMap<>();
        calendarsById.forEach((id, cal) -> m.put(id, cal.reservations()));
        return m;
    }

    private void releaseRooms(Booking b) {
        b.roomIds().forEach(id -> calendarsById.get(id).release(b.id(), b.stay()));
    }
}

// ============================================================
// DEMO + SELF-CHECKS
// ============================================================

/** A clock tests can move forward. */
final class MutableClock extends Clock {
    private volatile Instant now;
    private final ZoneId zone;
    MutableClock(Instant start, ZoneId zone) { this.now = start; this.zone = zone; }
    void advance(Duration d) { now = now.plus(d); }
    @Override public ZoneId getZone() { return zone; }
    @Override public Clock withZone(ZoneId z) { return new MutableClock(now, z); }
    @Override public Instant instant() { return now; }
}

final class HotelDemo {
    static final ZoneId ZONE = ZoneId.of("UTC");
    static final LocalDate TODAY = LocalDate.of(2026, 11, 2);   // a Monday

    static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError("FAILED: " + what);
        System.out.println("  ok  " + what);
    }

    static DateRange stay(int fromDay, int toDay) {
        return new DateRange(TODAY.withDayOfMonth(fromDay), TODAY.withDayOfMonth(toDay));
    }

    static HotelBookingService hotel(MutableClock clock, int singles, int suites) {
        List<Room> rooms = new ArrayList<>();
        for (int i = 1; i <= singles; i++) rooms.add(new Room("S" + i, RoomType.SINGLE, 1));
        for (int i = 1; i <= suites; i++) rooms.add(new Room("X" + i, RoomType.SUITE, 9));
        PricingStrategy pricing = new LoyaltyDiscountPricing(new NightlyRatePricing(new BigDecimal("30.00")));
        return new HotelBookingService(rooms, pricing, clock, Duration.ofMinutes(15));
    }

    static MutableClock clock() { return new MutableClock(TODAY.atTime(9, 0).atZone(ZONE).toInstant(), ZONE); }

    static void run() throws Exception {
        Guest alice = new Guest("G1", "Alice", LoyaltyTier.GOLD);
        Guest bob = new Guest("G2", "Bob", LoyaltyTier.NONE);

        System.out.println("== 1. Half-open date ranges ==");
        check(!stay(5, 8).overlaps(stay(8, 10)), "checkout 8th and check-in 8th do not overlap");
        check(stay(5, 8).overlaps(stay(7, 9)) && stay(5, 10).overlaps(stay(6, 7)), "partial and nested stays overlap");
        check(throwsIAE(() -> stay(8, 8)), "zero-night stay rejected");

        System.out.println("== 2. Pricing is exact (BigDecimal) ==");
        {
            HotelBookingService h = hotel(clock(), 2, 1);
            // Thu 5th, Fri 6th, Sat 7th = 3 nights, 2 weekend: 3*350 + 2*30 = 1110, GOLD -10% = 999.00
            Booking b = h.hold("k-price", alice, RoomType.SUITE, stay(5, 8), 1, CancellationPolicy.FLEXIBLE);
            check(b.total().equals(new BigDecimal("999.00")), "suite Thu-Sun for GOLD costs 999.00: " + b.total());
            check(b.status() == BookingStatus.HELD && b.roomIds().equals(List.of("X1")), "hold reserves room X1");
        }

        System.out.println("== 3. No double booking; back-to-back stays allowed ==");
        {
            HotelBookingService h = hotel(clock(), 2, 0);
            Booking b1 = h.hold("a", alice, RoomType.SINGLE, stay(5, 8), 1, CancellationPolicy.FLEXIBLE);
            Booking b2 = h.hold("b", bob, RoomType.SINGLE, stay(6, 9), 1, CancellationPolicy.FLEXIBLE);
            check(!b1.roomIds().equals(b2.roomIds()), "overlapping stays get different rooms");
            check(throwsNoAvail(() -> h.hold("c", bob, RoomType.SINGLE, stay(7, 8), 1, CancellationPolicy.FLEXIBLE)),
                  "third overlapping stay rejected when both rooms are taken");
            Booking b4 = h.hold("d", bob, RoomType.SINGLE, stay(8, 10), 1, CancellationPolicy.FLEXIBLE);
            check(b4.roomIds().equals(b1.roomIds()), "stay starting on b1's checkout day reuses b1's room");
            check(h.searchAvailable(RoomType.SINGLE, stay(9, 11)).size() == 1, "search: one single free for 9th-11th");
        }

        System.out.println("== 4. Hold, confirm, expiry ==");
        {
            MutableClock clk = clock();
            HotelBookingService h = hotel(clk, 1, 0);
            Booking paid = h.hold("p", alice, RoomType.SINGLE, stay(5, 6), 1, CancellationPolicy.FLEXIBLE);
            h.confirm(paid.id());
            check(paid.status() == BookingStatus.CONFIRMED, "confirm within TTL succeeds");
            Booking unpaid = h.hold("u", bob, RoomType.SINGLE, stay(10, 12), 1, CancellationPolicy.FLEXIBLE);
            clk.advance(Duration.ofMinutes(16));
            check(throwsISE(() -> h.confirm(unpaid.id())), "confirm after TTL fails");
            check(unpaid.status() == BookingStatus.EXPIRED, "late confirm expires the hold");
            check(h.searchAvailable(RoomType.SINGLE, stay(10, 12)).size() == 1, "expired hold released its room");
            Booking again = h.hold("u2", bob, RoomType.SINGLE, stay(10, 12), 1, CancellationPolicy.FLEXIBLE);
            clk.advance(Duration.ofMinutes(16));
            check(h.expireHolds() == 1 && again.status() == BookingStatus.EXPIRED, "sweeper expires one stale hold");
            check(h.expireHolds() == 0, "sweeper is idempotent");
            check(paid.status() == BookingStatus.CONFIRMED, "sweeper leaves confirmed bookings alone");
        }

        System.out.println("== 5. Lifecycle rules and refunds ==");
        {
            MutableClock clk = clock();
            HotelBookingService h = hotel(clk, 3, 0);
            Booking early = h.hold("e", bob, RoomType.SINGLE, stay(10, 12), 1, CancellationPolicy.FLEXIBLE);
            h.confirm(early.id());
            check(h.cancel(early.id()).equals(new BigDecimal("200.00")), "cancel 8 days out on FLEXIBLE: full refund 200.00");
            check(throwsISE(() -> h.cancel(early.id())), "cancelling twice is rejected (rooms released once)");

            Booking late = h.hold("l", bob, RoomType.SINGLE, stay(3, 5), 1, CancellationPolicy.FLEXIBLE);
            h.confirm(late.id());
            check(h.cancel(late.id()).equals(new BigDecimal("100.00")), "cancel 30h before check-in: first night (100) kept");

            Booking nr = h.hold("n", bob, RoomType.SINGLE, stay(20, 21), 1, CancellationPolicy.NON_REFUNDABLE);
            h.confirm(nr.id());
            check(h.cancel(nr.id()).signum() == 0, "non-refundable: zero refund");

            Booking stayB = h.hold("s", alice, RoomType.SINGLE, stay(2, 4), 1, CancellationPolicy.FLEXIBLE);
            check(throwsISE(() -> h.checkIn(stayB.id())), "cannot check in an unconfirmed hold");
            h.confirm(stayB.id());
            h.checkIn(stayB.id());
            check(throwsISE(() -> h.cancel(stayB.id())), "cannot cancel after check-in");
            h.checkOut(stayB.id());
            check(stayB.status() == BookingStatus.CHECKED_OUT, "check-out completes the stay");
            check(h.searchAvailable(RoomType.SINGLE, stay(2, 4)).size() == 2, "checked-out nights stay sold");
        }

        System.out.println("== 6. Idempotent hold and all-or-nothing group booking ==");
        {
            HotelBookingService h = hotel(clock(), 2, 0);
            Booking first = h.hold("retry-1", alice, RoomType.SINGLE, stay(5, 7), 1, CancellationPolicy.FLEXIBLE);
            Booking retry = h.hold("retry-1", alice, RoomType.SINGLE, stay(5, 7), 1, CancellationPolicy.FLEXIBLE);
            check(first == retry && h.searchAvailable(RoomType.SINGLE, stay(5, 7)).size() == 1,
                  "client retry with the same key returns the same booking, consumes no extra room");
            check(throwsIAE(() -> h.hold("retry-1", alice, RoomType.SINGLE, stay(9, 10), 1, CancellationPolicy.FLEXIBLE)),
                  "same key with a different request is rejected");
            check(throwsNoAvail(() -> h.hold("grp", bob, RoomType.SINGLE, stay(5, 7), 2, CancellationPolicy.MODERATE)),
                  "group of 2 fails when only 1 room is free");
            check(h.searchAvailable(RoomType.SINGLE, stay(5, 7)).size() == 1, "failed group hold rolled back its partial room");
            Booking grp = h.hold("grp2", bob, RoomType.SINGLE, stay(8, 9), 2, CancellationPolicy.MODERATE);
            check(grp.roomIds().size() == 2 && grp.total().equals(new BigDecimal("200.00")), "group of 2 for one night: 200.00");
        }

        System.out.println("== 7. Concurrency: no room is ever double-booked ==");
        {
            HotelBookingService h = hotel(clock(), 5, 0);
            int threads = 16;
            ExecutorService pool = Executors.newFixedThreadPool(threads);
            CountDownLatch go = new CountDownLatch(1);
            AtomicInteger won = new AtomicInteger(), lost = new AtomicInteger();
            List<Future<?>> fs = new ArrayList<>();
            for (int t = 0; t < threads; t++) {
                final int tid = t;
                fs.add(pool.submit(() -> {
                    go.await();
                    // Everyone fights for the same 5 rooms on the same nights...
                    try {
                        h.hold("same-" + tid, bob, RoomType.SINGLE, stay(12, 15), 1, CancellationPolicy.FLEXIBLE);
                        won.incrementAndGet();
                    } catch (NoAvailabilityException e) {
                        lost.incrementAndGet();
                    }
                    // ...then books random overlapping stays across the month.
                    Random rnd = new Random(tid);
                    for (int i = 0; i < 300; i++) {
                        int from = 16 + rnd.nextInt(10);
                        try {
                            Booking b = h.hold("r-" + tid + "-" + i, bob, RoomType.SINGLE,
                                    stay(from, from + 1 + rnd.nextInt(4)), 1 + rnd.nextInt(2), CancellationPolicy.FLEXIBLE);
                            if (rnd.nextInt(3) == 0) h.cancel(b.id());
                        } catch (NoAvailabilityException ignored) { }
                    }
                    return null;
                }));
            }
            go.countDown();
            for (Future<?> f : fs) f.get(20, TimeUnit.SECONDS);
            pool.shutdown();
            check(won.get() == 5 && lost.get() == threads - 5, "16 racers for 5 rooms: exactly 5 holds succeed");
            boolean noOverlap = h.reservationsByRoom().values().stream().allMatch(HotelDemo::pairwiseDisjoint);
            check(noOverlap, "after ~4800 concurrent holds/cancels every room calendar is overlap-free");
        }

        System.out.println("\nAll hotel booking checks passed.");
    }

    static boolean pairwiseDisjoint(List<Reservation> rs) {
        for (int i = 0; i < rs.size(); i++)
            for (int j = i + 1; j < rs.size(); j++)
                if (rs.get(i).range().overlaps(rs.get(j).range())) return false;
        return true;
    }

    static boolean throwsIAE(Runnable r) { try { r.run(); return false; } catch (IllegalArgumentException e) { return true; } }
    static boolean throwsISE(Runnable r) { try { r.run(); return false; } catch (IllegalStateException e) { return true; } }
    static boolean throwsNoAvail(Runnable r) { try { r.run(); return false; } catch (NoAvailabilityException e) { return true; } }
}
