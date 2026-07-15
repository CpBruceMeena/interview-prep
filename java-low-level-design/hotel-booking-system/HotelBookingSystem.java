/**
 * Hotel Booking System - Low Level Design (Java)
 * -----------------------------------------------
 * Design Principles: SOLID, Strategy Pattern, Observer Pattern, Factory Pattern,
 *                    Decorator Pattern, State Pattern
 *
 * Key Design Decisions:
 * - Room inventory managed as date-range availability (not per-night)
 * - Strategy pattern for pricing (seasonal, loyalty, early-bird)
 * - Decorator pattern for composable pricing modifiers
 * - Observer pattern for notifications (confirmation, cancellation, upgrades)
 * - Waitlist management with priority queue and time-limited holds
 * - Group booking with room blocks and staggered cancellation policies
 * - Loyalty points tracking with points-earning and redemption
 * - Room upgrades based on availability and loyalty tier
 * - Cancellation policies with tiered refunds
 */

import java.time.*;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.*;

// ============================================================
// ENUMS & VALUE OBJECTS
// ============================================================

enum RoomType {
    SINGLE(1, 100.0), DOUBLE(2, 150.0), SUITE(4, 350.0),
    PENTHOUSE(6, 800.0), DELUXE(2, 250.0), PRESIDENTIAL(8, 2000.0);

    private final int capacity;
    private final double baseRate;

    RoomType(int capacity, double baseRate) {
        this.capacity = capacity;
        this.baseRate = baseRate;
    }

    public int getCapacity() { return capacity; }
    public double getBaseRate() { return baseRate; }

    public RoomType upgrade() {
        return switch (this) {
            case SINGLE -> DOUBLE;
            case DOUBLE -> DELUXE;
            case DELUXE -> SUITE;
            case SUITE -> PENTHOUSE;
            case PENTHOUSE -> PRESIDENTIAL;
            case PRESIDENTIAL -> PRESIDENTIAL;
        };
    }
}

enum BookingStatus { CONFIRMED, CHECKED_IN, CHECKED_OUT, CANCELLED, NO_SHOW, WAITLIST, EXPIRED }

enum PaymentStatus { PENDING, AUTHORIZED, CAPTURED, REFUNDED, FAILED, PARTIALLY_REFUNDED }

enum LoyaltyTier { BRONZE(0, 0.05), SILVER(10, 0.10), GOLD(50, 0.15),
                   PLATINUM(150, 0.25), DIAMOND(500, 0.35);

    private final int pointsPerDollar;
    private final double discountRate;

    LoyaltyTier(int pointsPerDollar, double discountRate) {
        this.pointsPerDollar = pointsPerDollar;
        this.discountRate = discountRate;
    }

    public int getPointsPerDollar() { return pointsPerDollar; }
    public double getDiscountRate() { return discountRate; }

    public LoyaltyTier promote() {
        return switch (this) {
            case BRONZE -> SILVER;
            case SILVER -> GOLD;
            case GOLD -> PLATINUM;
            case PLATINUM -> DIAMOND;
            case DIAMOND -> DIAMOND;
        };
    }

    public static LoyaltyTier fromPoints(int points) {
        if (points >= 500) return DIAMOND;
        if (points >= 150) return PLATINUM;
        if (points >= 50) return GOLD;
        if (points >= 10) return SILVER;
        return BRONZE;
    }
}

enum CancellationPolicy { FLEXIBLE(48, 100.0, 0), MODERATE(72, 50.0, 0),
                          STRICT(168, 0.0, 100.0), NON_REFUNDABLE(0, 0.0, 100.0);

    private final int hoursBeforeCheckIn;
    private final double refundPercentage;
    private final double penaltyPercentage;

    CancellationPolicy(int hoursBeforeCheckIn, double refundPercentage, double penaltyPercentage) {
        this.hoursBeforeCheckIn = hoursBeforeCheckIn;
        this.refundPercentage = refundPercentage;
        this.penaltyPercentage = penaltyPercentage;
    }

    public boolean isEligibleForRefund(LocalDateTime now, LocalDateTime checkIn) {
        return ChronoUnit.HOURS.between(now, checkIn) >= hoursBeforeCheckIn;
    }

    public double getRefundPercentage(LocalDateTime now, LocalDateTime checkIn) {
        return isEligibleForRefund(now, checkIn) ? refundPercentage : penaltyPercentage;
    }

    public double calculateRefund(double totalAmount) {
        return totalAmount * refundPercentage / 100.0;
    }
}

record Guest(String id, String name, String email, String phone,
             LoyaltyTier tier, int loyaltyPoints, LocalDate memberSince) {
    public Guest(String id, String name, String email, String phone, LoyaltyTier tier) {
        this(id, name, email, phone, tier, 0, LocalDate.now());
    }

    public Guest withPoints(int newPoints) {
        return new Guest(id, name, email, phone,
            LoyaltyTier.fromPoints(newPoints), newPoints, memberSince);
    }
}

record DateRange(LocalDate checkIn, LocalDate checkOut) {
    public DateRange {
        if (!checkOut.isAfter(checkIn)) {
            throw new IllegalArgumentException("Check-out must be after check-in");
        }
    }

    public long nights() { return ChronoUnit.DAYS.between(checkIn, checkOut); }

    public boolean overlaps(DateRange other) {
        return !checkIn.isAfter(other.checkOut) && !other.checkIn.isAfter(checkOut);
    }

    public boolean contains(LocalDate date) {
        return !date.isBefore(checkIn) && date.isBefore(checkOut);
    }

    public Stream<LocalDate> dates() {
        return checkIn.datesUntil(checkOut);
    }
}

record Room(String id, RoomType type, int floor, String view, String building, List<String> amenities) {
    public Room(String id, RoomType type, int floor, String view) {
        this(id, type, floor, view, "Main", List.of());
    }

    public boolean hasAmenity(String amenity) {
        return amenities.contains(amenity);
    }
}

// ============================================================
// PRICING STRATEGY (Strategy Pattern + Decorator Pattern)
// ============================================================

interface PricingStrategy {
    double calculatePrice(RoomType roomType, DateRange stay, Guest guest);
    String description();
}

class BaseRatePricing implements PricingStrategy {
    @Override
    public double calculatePrice(RoomType roomType, DateRange stay, Guest guest) {
        return roomType.getBaseRate() * stay.nights();
    }

    @Override
    public String description() { return "Base rate"; }
}

class SeasonalPricing implements PricingStrategy {
    private final PricingStrategy wrapped;
    private final Map<Month, Double> seasonalMultipliers = Map.of(
        Month.DECEMBER, 2.0, Month.JANUARY, 1.8,
        Month.JUNE, 1.5, Month.JULY, 1.6, Month.AUGUST, 1.7,
        Month.FEBRUARY, 1.3, Month.MARCH, 1.2
    );

    public SeasonalPricing(PricingStrategy wrapped) {
        this.wrapped = wrapped;
    }

    @Override
    public double calculatePrice(RoomType roomType, DateRange stay, Guest guest) {
        double base = wrapped.calculatePrice(roomType, stay, guest);
        double multiplier = stay.dates()
            .map(d -> seasonalMultipliers.getOrDefault(d.getMonth(), 1.0))
            .mapToDouble(Double::doubleValue)
            .max().orElse(1.0);
        return base * multiplier;
    }

    @Override
    public String description() { return wrapped.description() + " → Seasonal adjustment"; }
}

class LoyaltyPricing implements PricingStrategy {
    private final PricingStrategy wrapped;

    public LoyaltyPricing(PricingStrategy wrapped) {
        this.wrapped = wrapped;
    }

    @Override
    public double calculatePrice(RoomType roomType, DateRange stay, Guest guest) {
        double base = wrapped.calculatePrice(roomType, stay, guest);
        return base * (1 - guest.tier().getDiscountRate());
    }

    @Override
    public String description() { return wrapped.description() + " → Loyalty discount (" + description() + ")"; }
}

class EarlyBirdPricing implements PricingStrategy {
    private final PricingStrategy wrapped;
    private static final long EARLY_BIRD_DAYS = 30;

    public EarlyBirdPricing(PricingStrategy wrapped) {
        this.wrapped = wrapped;
    }

    @Override
    public double calculatePrice(RoomType roomType, DateRange stay, Guest guest) {
        double base = wrapped.calculatePrice(roomType, stay, guest);
        long daysUntilCheckIn = ChronoUnit.DAYS.between(LocalDate.now(), stay.checkIn());
        if (daysUntilCheckIn >= EARLY_BIRD_DAYS) {
            return base * 0.85; // 15% discount for early booking
        }
        return base;
    }

    @Override
    public String description() { return wrapped.description() + " → Early bird"; }
}

class LastMinutePricing implements PricingStrategy {
    private final PricingStrategy wrapped;
    private static final long LAST_MINUTE_DAYS = 3;

    public LastMinutePricing(PricingStrategy wrapped) {
        this.wrapped = wrapped;
    }

    @Override
    public double calculatePrice(RoomType roomType, DateRange stay, Guest guest) {
        double base = wrapped.calculatePrice(roomType, stay, guest);
        long daysUntilCheckIn = ChronoUnit.DAYS.between(LocalDate.now(), stay.checkIn());
        if (daysUntilCheckIn <= LAST_MINUTE_DAYS) {
            return base * 0.75; // 25% discount for last-minute booking
        }
        return base;
    }

    @Override
    public String description() { return wrapped.description() + " → Last minute"; }
}

class WeekendSurchargePricing implements PricingStrategy {
    private final PricingStrategy wrapped;

    public WeekendSurchargePricing(PricingStrategy wrapped) {
        this.wrapped = wrapped;
    }

    @Override
    public double calculatePrice(RoomType roomType, DateRange stay, Guest guest) {
        double base = wrapped.calculatePrice(roomType, stay, guest);
        long weekendNights = stay.dates()
            .filter(d -> d.getDayOfWeek() == DayOfWeek.FRIDAY
                       || d.getDayOfWeek() == DayOfWeek.SATURDAY)
            .count();
        return base + (weekendNights * 30.0); // $30 surcharge per weekend night
    }

    @Override
    public String description() { return wrapped.description() + " → Weekend surcharge"; }
}

class LongStayDiscountPricing implements PricingStrategy {
    private final PricingStrategy wrapped;

    public LongStayDiscountPricing(PricingStrategy wrapped) {
        this.wrapped = wrapped;
    }

    @Override
    public double calculatePrice(RoomType roomType, DateRange stay, Guest guest) {
        double base = wrapped.calculatePrice(roomType, stay, guest);
        long nights = stay.nights();
        if (nights >= 30) return base * 0.60;  // 40% off for monthly
        if (nights >= 14) return base * 0.75;  // 25% off for 2 weeks
        if (nights >= 7) return base * 0.85;   // 15% off for weekly
        return base;
    }

    @Override
    public String description() { return wrapped.description() + " → Long stay discount"; }
}

// ============================================================
// GROUP BOOKING
// ============================================================

class GroupBooking {
    private final String groupId;
    private final String groupName;
    private final String contactEmail;
    private final Map<String, Booking> bookings;
    private final int minRooms, maxRooms;
    private final CancellationPolicy groupPolicy;
    private final LocalDateTime blockExpiry;
    private final List<String> notes;

    public GroupBooking(String groupId, String groupName, String contactEmail,
                        int minRooms, int maxRooms, CancellationPolicy groupPolicy,
                        LocalDateTime blockExpiry) {
        this.groupId = groupId;
        this.groupName = groupName;
        this.contactEmail = contactEmail;
        this.bookings = new ConcurrentHashMap<>();
        this.minRooms = minRooms;
        this.maxRooms = maxRooms;
        this.groupPolicy = groupPolicy;
        this.blockExpiry = blockExpiry;
        this.notes = new CopyOnWriteArrayList<>();
    }

    public synchronized boolean addBooking(Booking booking) {
        if (bookings.size() >= maxRooms) {
            return false; // Block is full
        }
        bookings.put(booking.getId(), booking);
        return true;
    }

    public synchronized boolean canRelease() {
        return bookings.size() >= minRooms;
    }

    public synchronized void releaseUnused() {
        // Release block if minimum not met by expiry
        if (LocalDateTime.now().isAfter(blockExpiry) && bookings.size() < minRooms) {
            bookings.clear();
            System.out.printf("  🗑️ Group block %s expired - releasing %d rooms%n",
                groupId, maxRooms);
        }
    }

    public String getGroupId() { return groupId; }
    public int getCurrentRooms() { return bookings.size(); }
    public int getMaxRooms() { return maxRooms; }
    public int getMinRooms() { return minRooms; }
    public CancellationPolicy getGroupPolicy() { return groupPolicy; }
    public void addNote(String note) { notes.add(note); }
}

// ============================================================
// WAITLIST
// ============================================================

class WaitlistEntry implements Comparable<WaitlistEntry> {
    private final String id;
    private final Guest guest;
    private final RoomType roomType;
    private final DateRange stay;
    private final LocalDateTime createdAt;
    private final LoyaltyTier priorityTier;

    public WaitlistEntry(String id, Guest guest, RoomType roomType, DateRange stay) {
        this.id = id;
        this.guest = guest;
        this.roomType = roomType;
        this.stay = stay;
        this.createdAt = LocalDateTime.now();
        this.priorityTier = guest.tier();
    }

    @Override
    public int compareTo(WaitlistEntry other) {
        // Higher loyalty tier first, then earlier creation
        if (this.priorityTier.ordinal() != other.priorityTier.ordinal()) {
            return other.priorityTier.ordinal() - this.priorityTier.ordinal();
        }
        return this.createdAt.compareTo(other.createdAt);
    }

    public String getId() { return id; }
    public Guest getGuest() { return guest; }
    public RoomType getRoomType() { return roomType; }
    public DateRange getStay() { return stay; }
}

class WaitlistManager {
    private final Map<String, PriorityQueue<WaitlistEntry>> waitlists; // roomType -> queue
    private static final Duration HOLD_DURATION = Duration.ofHours(24);
    private final ScheduledExecutorService scheduler;

    public WaitlistManager() {
        this.waitlists = new ConcurrentHashMap<>();
        this.scheduler = Executors.newSingleThreadScheduledExecutor();

        // Initialize queues for each room type
        for (RoomType type : RoomType.values()) {
            waitlists.put(type.name(), new PriorityQueue<>());
        }

        // Periodic cleanup
        scheduler.scheduleAtFixedRate(this::expireOldEntries, 1, 1, TimeUnit.HOURS);
    }

    public void addToWaitlist(WaitlistEntry entry) {
        PriorityQueue<WaitlistEntry> queue = waitlists.get(entry.getRoomType().name());
        synchronized (queue) {
            queue.offer(entry);
        }
        System.out.printf("  ⏳ Added %s to waitlist for %s (tier: %s)%n",
            entry.getGuest().name(), entry.getRoomType(), entry.getGuest().tier());
    }

    public Optional<WaitlistEntry> getNextAvailable(RoomType type) {
        PriorityQueue<WaitlistEntry> queue = waitlists.get(type.name());
        synchronized (queue) {
            WaitlistEntry entry = queue.poll();
            return Optional.ofNullable(entry);
        }
    }

    public void removeFromWaitlist(String entryId) {
        for (PriorityQueue<WaitlistEntry> queue : waitlists.values()) {
            synchronized (queue) {
                queue.removeIf(e -> e.getId().equals(entryId));
            }
        }
    }

    public int getWaitlistCount(RoomType type) {
        return waitlists.get(type.name()).size();
    }

    private void expireOldEntries() {
        for (PriorityQueue<WaitlistEntry> queue : waitlists.values()) {
            synchronized (queue) {
                queue.removeIf(e ->
                    ChronoUnit.HOURS.between(e.getStay().checkIn(), LocalDateTime.now()) > 0);
            }
        }
    }

    public void shutdown() { scheduler.shutdown(); }
}

// ============================================================
// INVENTORY MANAGER
// ============================================================

class InventoryManager {
    private final Map<RoomType, NavigableMap<LocalDate, Integer>> availability;
    private final Map<String, Room> rooms;

    public InventoryManager(List<Room> rooms) {
        this.rooms = rooms.stream().collect(Collectors.toMap(Room::id, r -> r));
        this.availability = new ConcurrentHashMap<>();
        for (RoomType type : RoomType.values()) {
            availability.put(type, new ConcurrentSkipListMap<>());
        }
        initializeInventory();
    }

    private void initializeInventory() {
        long countByType = rooms.stream()
            .collect(Collectors.groupingBy(Room::type, Collectors.counting()));
        LocalDate today = LocalDate.now();
        for (RoomType type : RoomType.values()) {
            NavigableMap<LocalDate, Integer> map = availability.get(type);
            for (int i = 0; i < 365; i++) {
                map.put(today.plusDays(i), countByType.getOrDefault(type, 0L).intValue());
            }
        }
    }

    public synchronized boolean checkAvailability(RoomType type, DateRange range) {
        NavigableMap<LocalDate, Integer> inv = availability.get(type);
        return range.dates().allMatch(d ->
            inv.getOrDefault(d, 0) > 0
        );
    }

    public synchronized boolean reserveRoom(RoomType type, DateRange range) {
        if (!checkAvailability(type, range)) return false;
        NavigableMap<LocalDate, Integer> inv = availability.get(type);
        range.dates().forEach(d -> inv.merge(d, -1, Integer::sum));
        return true;
    }

    public synchronized void releaseRoom(RoomType type, DateRange range) {
        NavigableMap<LocalDate, Integer> inv = availability.get(type);
        range.dates().forEach(d -> inv.merge(d, 1, Integer::sum));
    }

    // Block reservation for group bookings
    public synchronized boolean reserveBlock(RoomType type, DateRange range, int roomCount) {
        NavigableMap<LocalDate, Integer> inv = availability.get(type);
        boolean allAvailable = range.dates().allMatch(d ->
            inv.getOrDefault(d, 0) >= roomCount
        );
        if (!allAvailable) return false;

        range.dates().forEach(d -> inv.merge(d, -roomCount, Integer::sum));
        return true;
    }

    public synchronized void releaseBlock(RoomType type, DateRange range, int roomCount) {
        NavigableMap<LocalDate, Integer> inv = availability.get(type);
        range.dates().forEach(d -> inv.merge(d, roomCount, Integer::sum));
    }

    public List<Room> findAvailableRooms(RoomType type, DateRange range) {
        if (!checkAvailability(type, range)) return List.of();
        return rooms.values().stream()
            .filter(r -> r.type() == type)
            .collect(Collectors.toList());
    }

    public int getAvailableCount(RoomType type, LocalDate date) {
        return availability.get(type).getOrDefault(date, 0);
    }

    public RoomType suggestUpgrade(RoomType requested, DateRange range) {
        // Check if a higher room type is available
        RoomType current = requested;
        for (int i = 0; i < 3; i++) {
            RoomType upgraded = current.upgrade();
            if (checkAvailability(upgraded, range)) {
                return upgraded;
            }
            current = upgraded;
        }
        return requested; // No upgrade available
    }
}

// ============================================================
// BOOKING
// ============================================================

class Booking {
    private final String id;
    private final Guest guest;
    private final Room room;
    private final DateRange stay;
    private volatile BookingStatus status;
    private volatile PaymentStatus paymentStatus;
    private final double totalAmount;
    private final double baseAmount;
    private final double taxes;
    private final CancellationPolicy cancellationPolicy;
    private final LocalDateTime createdAt;
    private final Map<String, Object> metadata;

    public Booking(String id, Guest guest, Room room, DateRange stay,
                   double amount, double taxes, CancellationPolicy policy) {
        this.id = id;
        this.guest = guest;
        this.room = room;
        this.stay = stay;
        this.totalAmount = amount;
        this.baseAmount = amount - taxes;
        this.taxes = taxes;
        this.cancellationPolicy = policy;
        this.status = BookingStatus.CONFIRMED;
        this.paymentStatus = PaymentStatus.PENDING;
        this.createdAt = LocalDateTime.now();
        this.metadata = new ConcurrentHashMap<>();
    }

    // Getters
    public String getId() { return id; }
    public Guest getGuest() { return guest; }
    public Room getRoom() { return room; }
    public DateRange getStay() { return stay; }
    public BookingStatus getStatus() { return status; }
    public PaymentStatus getPaymentStatus() { return paymentStatus; }
    public double getTotalAmount() { return totalAmount; }
    public double getBaseAmount() { return baseAmount; }
    public double getTaxes() { return taxes; }
    public CancellationPolicy getCancellationPolicy() { return cancellationPolicy; }
    public LocalDateTime getCreatedAt() { return createdAt; }

    public void putMetadata(String key, Object value) { metadata.put(key, value); }
    public Object getMetadata(String key) { return metadata.get(key); }

    public synchronized double cancel() {
        double refund = cancellationPolicy.calculateRefund(totalAmount);
        this.status = BookingStatus.CANCELLED;
        if (refund > 0) {
            this.paymentStatus = refund >= totalAmount ?
                PaymentStatus.REFUNDED : PaymentStatus.PARTIALLY_REFUNDED;
        } else {
            this.paymentStatus = PaymentStatus.CAPTURED;
        }
        return refund;
    }

    public synchronized void checkIn() { this.status = BookingStatus.CHECKED_IN; }
    public synchronized void checkOut() { this.status = BookingStatus.CHECKED_OUT; }
    public synchronized void markNoShow() { this.status = BookingStatus.NO_SHOW; }

    public long nightsStayed() {
        if (status == BookingStatus.CHECKED_OUT) {
            return stay.nights();
        }
        if (status == BookingStatus.CHECKED_IN) {
            return ChronoUnit.DAYS.between(stay.checkIn(), LocalDate.now());
        }
        return 0;
    }

    @Override
    public String toString() {
        return String.format("Booking[%s] %s - %s: %s → %s ($%.2f) [%s]",
            id, guest.name(), stay.checkIn(), stay.checkOut(),
            status, totalAmount, room.type());
    }
}

// ============================================================
// LOYALTY POINTS TRACKER
// ============================================================

class LoyaltyPointsTracker {
    private final Map<String, Guest> guests;
    private static final int POINTS_EXPIRY_DAYS = 365;

    public LoyaltyPointsTracker() {
        this.guests = new ConcurrentHashMap<>();
    }

    public void registerGuest(Guest guest) {
        guests.put(guest.id(), guest);
    }

    public int earnPoints(Guest guest, double amount) {
        int points = (int)(amount * guest.tier().getPointsPerDollar());
        Guest updated = guest.withPoints(guest.loyaltyPoints() + points);
        guests.put(guest.id(), updated);

        // Check for tier promotion
        if (updated.tier() != guest.tier()) {
            System.out.printf("  🏆 %s promoted to %s tier! (Points: %d)%n",
                guest.name(), updated.tier(), updated.loyaltyPoints());
        }

        return points;
    }

    public boolean redeemPoints(Guest guest, int points, double amount) {
        if (guest.loyaltyPoints() < points) return false;

        // 100 points = $1 redemption value
        double discount = points / 100.0;
        if (discount > amount) discount = amount;

        Guest updated = guest.withPoints(guest.loyaltyPoints() - (int)(discount * 100));
        guests.put(guest.id(), updated);
        return true;
    }

    public int getPoints(String guestId) {
        Guest guest = guests.get(guestId);
        return guest != null ? guest.loyaltyPoints() : 0;
    }

    public Guest getGuest(String guestId) {
        return guests.get(guestId);
    }

    public LoyaltyTier getTier(String guestId) {
        Guest guest = guests.get(guestId);
        return guest != null ? guest.tier() : LoyaltyTier.BRONZE;
    }
}

// ============================================================
// REVENUE MANAGER
// ============================================================

class RevenueManager {
    private final Map<RoomType, Map<LocalDate, Double>> dailyRevenue;
    private final Map<RoomType, AtomicLong> totalBookings;

    public RevenueManager() {
        this.dailyRevenue = new ConcurrentHashMap<>();
        this.totalBookings = new ConcurrentHashMap<>();
        for (RoomType type : RoomType.values()) {
            dailyRevenue.put(type, new ConcurrentHashMap<>());
            totalBookings.put(type, new AtomicLong(0));
        }
    }

    public void recordRevenue(RoomType type, LocalDate date, double amount) {
        dailyRevenue.get(type).merge(date, amount, Double::sum);
        totalBookings.get(type).incrementAndGet();
    }

    public double getDailyRevenue(RoomType type, LocalDate date) {
        return dailyRevenue.get(type).getOrDefault(date, 0.0);
    }

    public double getTotalRevenue(RoomType type) {
        return dailyRevenue.get(type).values().stream().mapToDouble(Double::doubleValue).sum();
    }

    public double getTotalRevenueAll() {
        return dailyRevenue.values().stream()
            .flatMap(m -> m.values().stream())
            .mapToDouble(Double::doubleValue)
            .sum();
    }

    public void printRevenueReport() {
        System.out.println("\n" + "=".repeat(55));
        System.out.println("           REVENUE REPORT");
        System.out.println("=".repeat(55));
        double grandTotal = 0;
        for (RoomType type : RoomType.values()) {
            double rev = getTotalRevenue(type);
            long bookings = totalBookings.get(type).get();
            if (bookings > 0) {
                System.out.printf("  %-15s: $%.2f (%d bookings, avg $%.2f)%n",
                    type, rev, bookings, rev / bookings);
            }
            grandTotal += rev;
        }
        System.out.printf("  %-15s: $%.2f%n", "TOTAL", grandTotal);
        System.out.println("=".repeat(55));
    }
}

// ============================================================
// NOTIFICATION SERVICE (Observer Pattern)
// ============================================================

interface BookingObserver {
    void onBookingCreated(Booking booking);
    void onBookingCancelled(Booking booking, double refund);
    void onCheckIn(Booking booking);
    void onCheckOut(Booking booking);
    void onNoShow(Booking booking);
    void onUpgradeOffered(Booking booking, RoomType newType);
    void onWaitlistNotified(WaitlistEntry entry);
    void onLoyaltyPointsEarned(Guest guest, int points);
    void onGroupBookingCreated(GroupBooking group);
}

class EmailNotificationService implements BookingObserver {
    @Override
    public void onBookingCreated(Booking booking) {
        System.out.printf("📧 Email to %s: Booking %s confirmed for %s - %s ($%.2f)%n",
            booking.getGuest().email(), booking.getId(),
            booking.getStay().checkIn(), booking.getStay().checkOut(),
            booking.getTotalAmount());
    }

    @Override
    public void onBookingCancelled(Booking booking, double refund) {
        System.out.printf("📧 Email to %s: Booking %s cancelled. Refund: $%.2f%n",
            booking.getGuest().email(), booking.getId(), refund);
    }

    @Override
    public void onCheckIn(Booking booking) {
        System.out.printf("📧 Welcome email to %s: Enjoy your stay in %s!%n",
            booking.getGuest().email(), booking.getRoom().id());
    }

    @Override
    public void onCheckOut(Booking booking) {
        System.out.printf("📧 Thank you email to %s: We hope you enjoyed your stay!%n",
            booking.getGuest().email());
    }

    @Override
    public void onNoShow(Booking booking) {
        System.out.printf("📧 Email to %s: No-show penalty applied for booking %s ($%.2f)%n",
            booking.getGuest().email(), booking.getId(), booking.getTotalAmount());
    }

    @Override
    public void onUpgradeOffered(Booking booking, RoomType newType) {
        System.out.printf("⭐ Upgrade available for %s: %s → %s (complimentary!)%n",
            booking.getGuest().name(), booking.getRoom().type(), newType);
    }

    @Override
    public void onWaitlistNotified(WaitlistEntry entry) {
        System.out.printf("📧 Waitlist notification to %s: %s available for %s!%n",
            entry.getGuest().email(), entry.getRoomType(),
            entry.getStay().checkIn());
    }

    @Override
    public void onLoyaltyPointsEarned(Guest guest, int points) {
        System.out.printf("💎 %s earned %d loyalty points (Total: %d, Tier: %s)%n",
            guest.name(), points, guest.loyaltyPoints(), guest.tier());
    }

    @Override
    public void onGroupBookingCreated(GroupBooking group) {
        System.out.printf("📧 Group booking created: %s (%d rooms, contact: %s)%n",
            group.getGroupId(), group.getMaxRooms(), group.getGroupId());
    }
}

// ============================================================
// HOTEL BOOKING SERVICE (Facade)
// ============================================================

class HotelBookingService {
    private final String hotelName;
    private final InventoryManager inventory;
    private final PricingStrategy pricing;
    private final List<BookingObserver> observers;
    private final Map<String, Booking> bookings;
    private final Map<String, Guest> guests;
    private final WaitlistManager waitlist;
    private final LoyaltyPointsTracker loyalty;
    private final RevenueManager revenue;
    private final Map<String, GroupBooking> groupBookings;
    private final ScheduledExecutorService scheduler;
    private int bookingCounter;
    private static final double TAX_RATE = 0.12;

    public HotelBookingService(String name, List<Room> rooms, PricingStrategy pricing) {
        this.hotelName = name;
        this.inventory = new InventoryManager(rooms);
        this.pricing = pricing;
        this.observers = new CopyOnWriteArrayList<>();
        this.bookings = new ConcurrentHashMap<>();
        this.guests = new ConcurrentHashMap<>();
        this.waitlist = new WaitlistManager();
        this.loyalty = new LoyaltyPointsTracker();
        this.revenue = new RevenueManager();
        this.groupBookings = new ConcurrentHashMap<>();
        this.scheduler = Executors.newSingleThreadScheduledExecutor();
        this.bookingCounter = 0;

        // Add default observer
        addObserver(new EmailNotificationService());

        // Schedule no-show detection and waitlist processing
        scheduler.scheduleAtFixedRate(this::checkNoShows, 1, 1, TimeUnit.HOURS);
        scheduler.scheduleAtFixedRate(this::processWaitlist, 1, 5, TimeUnit.MINUTES);
    }

    public void addObserver(BookingObserver observer) { observers.add(observer); }
    public RevenueManager getRevenue() { return revenue; }

    // --- Core API ---

    public List<Room> searchRooms(RoomType type, DateRange stay) {
        return inventory.findAvailableRooms(type, stay);
    }

    public synchronized Booking createBooking(Guest guest, RoomType roomType, DateRange stay) {
        // Register guest if new
        guests.putIfAbsent(guest.id(), guest);
        loyalty.registerGuest(guest);

        // Check availability
        if (!inventory.checkAvailability(roomType, stay)) {
            // Add to waitlist
            WaitlistEntry waitlistEntry = new WaitlistEntry(
                "WL-" + UUID.randomUUID().toString().substring(0, 8),
                guest, roomType, stay);
            waitlist.addToWaitlist(waitlistEntry);
            throw new IllegalStateException("No availability for " + roomType
                + " on " + stay.checkIn() + " to " + stay.checkOut()
                + " — added to waitlist");
        }

        // Calculate price with all modifiers
        double amount = pricing.calculatePrice(roomType, stay, guest);
        double taxes = amount * TAX_RATE;
        double total = amount + taxes;

        // Reserve inventory
        inventory.reserveRoom(roomType, stay);

        // Find specific room
        List<Room> available = inventory.findAvailableRooms(roomType, stay);
        Room room = available.isEmpty() ? null : available.get(0);

        // Check for upgrade
        RoomType upgradedType = inventory.suggestUpgrade(roomType, stay);
        if (upgradedType != roomType) {
            notifyUpgradeOffered(new Booking("", guest, room, stay, total, taxes,
                CancellationPolicy.FLEXIBLE), upgradedType);
        }

        // Create booking
        bookingCounter++;
        String bookingId = generateBookingId();
        CancellationPolicy cancelPolicy = determineCancellationPolicy(guest, stay);
        Booking booking = new Booking(bookingId, guest, room, stay, total, taxes, cancelPolicy);
        bookings.put(bookingId, booking);
        booking.putMetadata("created", LocalDateTime.now().toString());

        // Track revenue and points
        revenue.recordRevenue(roomType, stay.checkIn(), total);
        int points = loyalty.earnPoints(guest, amount);
        notifyLoyaltyPointsEarned(guest, points);

        // Notify observers
        notifyBookingCreated(booking);
        return booking;
    }

    // --- Group Booking ---

    public synchronized GroupBooking createGroupBooking(String groupId, String groupName,
                                                         String contactEmail, RoomType roomType,
                                                         DateRange stay, int minRooms, int maxRooms) {
        // Reserve block of rooms
        if (!inventory.reserveBlock(roomType, stay, maxRooms)) {
            throw new IllegalStateException("Cannot reserve " + maxRooms
                + " rooms of type " + roomType + " for " + stay);
        }

        GroupBooking group = new GroupBooking(groupId, groupName, contactEmail,
            minRooms, maxRooms, CancellationPolicy.MODERATE,
            LocalDateTime.now().plusDays(14));
        groupBookings.put(groupId, group);

        notifyGroupBookingCreated(group);
        return group;
    }

    public synchronized Booking addToGroupBooking(String groupId, Guest guest, RoomType roomType,
                                                    DateRange stay) {
        GroupBooking group = groupBookings.get(groupId);
        if (group == null) throw new IllegalArgumentException("Group not found: " + groupId);

        // Calculate price
        double amount = pricing.calculatePrice(roomType, stay, guest);
        double taxes = amount * TAX_RATE;
        double total = amount + taxes;

        Room room = inventory.findAvailableRooms(roomType, stay).stream().findFirst().orElse(null);

        bookingCounter++;
        String bookingId = generateBookingId();
        Booking booking = new Booking(bookingId, guest, room, stay, total, taxes,
            CancellationPolicy.MODERATE);
        bookings.put(bookingId, booking);

        // Track revenue and points
        revenue.recordRevenue(roomType, stay.checkIn(), total);
        loyalty.earnPoints(guest, amount);

        group.addBooking(booking);
        notifyBookingCreated(booking);
        return booking;
    }

    // --- Cancellation ---

    public synchronized double cancelBooking(String bookingId) {
        Booking booking = bookings.get(bookingId);
        if (booking == null) throw new IllegalArgumentException("Booking not found: " + bookingId);

        double refund = booking.cancel();
        inventory.releaseRoom(booking.getRoom().type(), booking.getStay());

        // If refund is partial, some revenue is retained
        revenue.recordRevenue(booking.getRoom().type(), booking.getStay().checkIn(),
            -(refund));

        notifyBookingCancelled(booking, refund);

        // Notify waitlist
        processWaitlistForRoomType(booking.getRoom().type());
        return refund;
    }

    // --- Check-in / Check-out ---

    public synchronized void checkIn(String bookingId) {
        Booking booking = bookings.get(bookingId);
        if (booking == null) throw new IllegalArgumentException("Booking not found: " + bookingId);
        booking.checkIn();
        booking.getGuest();
        notifyCheckIn(booking);
    }

    public synchronized void checkOut(String bookingId) {
        Booking booking = bookings.get(bookingId);
        if (booking == null) throw new IllegalArgumentException("Booking not found: " + bookingId);
        booking.checkOut();
        inventory.releaseRoom(booking.getRoom().type(), booking.getStay());
        notifyCheckOut(booking);
    }

    // --- Waitlist ---

    public void addToWaitlist(Guest guest, RoomType roomType, DateRange stay) {
        WaitlistEntry entry = new WaitlistEntry(
            "WL-" + UUID.randomUUID().toString().substring(0, 8),
            guest, roomType, stay);
        waitlist.addToWaitlist(entry);
    }

    // --- Reporting ---

    public void printAvailability(RoomType type, LocalDate from, int days) {
        System.out.println("\n📊 AVAILABILITY for " + type + " (" + hotelName + ")");
        System.out.println("-".repeat(50));
        for (int i = 0; i < days; i++) {
            LocalDate date = from.plusDays(i);
            int count = inventory.getAvailableCount(type, date);
            int waitlisted = waitlist.getWaitlistCount(type);
            String bar = "█".repeat(Math.min(count, 20));
            System.out.printf("  %s: %s %d rooms (waitlist: %d)%n", date, bar, count, waitlisted);
        }
    }

    public void printActiveBookings() {
        System.out.println("\n📋 ACTIVE BOOKINGS");
        System.out.println("=".repeat(60));
        bookings.values().stream()
            .filter(b -> b.getStatus() == BookingStatus.CONFIRMED
                      || b.getStatus() == BookingStatus.CHECKED_IN)
            .forEach(System.out::println);
        System.out.println("=".repeat(60));
    }

    public void printGuestHistory(String guestId) {
        Guest guest = loyalty.getGuest(guestId);
        if (guest == null) {
            System.out.println("Guest not found: " + guestId);
            return;
        }
        System.out.printf("""
            ╔══════════════════════════════════╗
            ║         GUEST PROFILE            ║
            ╠══════════════════════════════════╣
            ║ Name:   %-24s ║%n
            ║ Tier:   %-24s ║%n
            ║ Points: %-24d ║%n
            ║ Member: %-24s ║%n
            ╚══════════════════════════════════╝%n""",
            guest.name(), guest.tier(), guest.loyaltyPoints(), guest.memberSince());

        var guestBookings = bookings.values().stream()
            .filter(b -> b.getGuest().id().equals(guestId))
            .collect(Collectors.toList());
        System.out.println("Recent bookings: " + guestBookings.size());
        guestBookings.stream().limit(5).forEach(b ->
            System.out.printf("  • %s: %s → %s ($%.2f, %s)%n",
                b.getRoom().type(), b.getStay().checkIn(), b.getStay().checkOut(),
                b.getTotalAmount(), b.getStatus()));
    }

    // --- Internal ---

    private String generateBookingId() {
        return "BK-" + hotelName.substring(0, 2).toUpperCase()
            + "-" + String.format("%05d", bookingCounter);
    }

    private CancellationPolicy determineCancellationPolicy(Guest guest, DateRange stay) {
        long nights = stay.nights();
        if (nights >= 30) return CancellationPolicy.STRICT;
        if (guest.tier() == LoyaltyTier.DIAMOND || guest.tier() == LoyaltyTier.PLATINUM) {
            return CancellationPolicy.FLEXIBLE;
        }
        return CancellationPolicy.MODERATE;
    }

    private void checkNoShows() {
        LocalDate today = LocalDate.now();
        bookings.values().stream()
            .filter(b -> b.getStatus() == BookingStatus.CONFIRMED)
            .filter(b -> b.getStay().checkIn().isBefore(today))
            .forEach(b -> {
                b.markNoShow();
                inventory.releaseRoom(b.getRoom().type(), b.getStay());
                notifyNoShow(b);
            });
    }

    private void processWaitlist() {
        for (RoomType type : RoomType.values()) {
            processWaitlistForRoomType(type);
        }
    }

    private void processWaitlistForRoomType(RoomType type) {
        while (true) {
            Optional<WaitlistEntry> next = waitlist.getNextAvailable(type);
            if (next.isEmpty()) break;

            WaitlistEntry entry = next.get();
            DateRange stay = entry.getStay();
            if (inventory.checkAvailability(type, stay)) {
                try {
                    createBooking(entry.getGuest(), type, stay);
                    notifyWaitlistNotified(entry);
                } catch (IllegalStateException e) {
                    // Still not available, re-add to waitlist
                    waitlist.addToWaitlist(entry);
                    break;
                }
            } else {
                // Not available yet, re-add
                waitlist.addToWaitlist(entry);
                break;
            }
        }
    }

    // --- Notifications ---

    private void notifyBookingCreated(Booking b) { observers.forEach(o -> o.onBookingCreated(b)); }
    private void notifyBookingCancelled(Booking b, double refund) {
        observers.forEach(o -> o.onBookingCancelled(b, refund));
    }
    private void notifyCheckIn(Booking b) { observers.forEach(o -> o.onCheckIn(b)); }
    private void notifyCheckOut(Booking b) { observers.forEach(o -> o.onCheckOut(b)); }
    private void notifyNoShow(Booking b) { observers.forEach(o -> o.onNoShow(b)); }
    private void notifyUpgradeOffered(Booking b, RoomType t) {
        observers.forEach(o -> o.onUpgradeOffered(b, t));
    }
    private void notifyWaitlistNotified(WaitlistEntry e) {
        observers.forEach(o -> o.onWaitlistNotified(e));
    }
    private void notifyLoyaltyPointsEarned(Guest g, int p) {
        observers.forEach(o -> o.onLoyaltyPointsEarned(g, p));
    }
    private void notifyGroupBookingCreated(GroupBooking g) {
        observers.forEach(o -> o.onGroupBookingCreated(g));
    }

    public void shutdown() {
        scheduler.shutdown();
        waitlist.shutdown();
    }
}

// ============================================================
// DEMO
// ============================================================

public class HotelBookingSystem {
    public static void main(String[] args) {
        System.out.println("╔══════════════════════════════════╗");
        System.out.println("║    HOTEL BOOKING SYSTEM DEMO    ║");
        System.out.println("╚══════════════════════════════════╝\n");

        System.out.println("🏨 Hotel: Grand Plaza — 50 rooms, 6 types, 5 floors\n");

        // Setup hotel with 50 rooms of various types
        List<Room> rooms = new ArrayList<>();
        int roomNum = 1;
        // 15 SINGLE rooms
        for (int i = 0; i < 15; i++) {
            rooms.add(new Room("R" + String.format("%03d", roomNum++),
                RoomType.SINGLE, (roomNum % 5) + 1,
                roomNum % 2 == 0 ? "City" : "Garden", "Main",
                List.of("WiFi", "TV"));
        }
        // 10 DOUBLE rooms
        for (int i = 0; i < 10; i++) {
            rooms.add(new Room("R" + String.format("%03d", roomNum++),
                RoomType.DOUBLE, (roomNum % 5) + 1,
                roomNum % 2 == 0 ? "City" : "Garden", "Main",
                List.of("WiFi", "TV", "MiniBar"));
        }
        // 10 DELUXE rooms
        for (int i = 0; i < 10; i++) {
            rooms.add(new Room("R" + String.format("%03d", roomNum++),
                RoomType.DELUXE, (roomNum % 5) + 1,
                roomNum % 2 == 0 ? "Ocean" : "City", "Tower",
                List.of("WiFi", "TV", "MiniBar", "RoomService", "Balcony")));
        }
        // 8 SUITE rooms
        for (int i = 0; i < 8; i++) {
            rooms.add(new Room("R" + String.format("%03d", roomNum++),
                RoomType.SUITE, (roomNum % 5) + 1,
                "Ocean", "Tower",
                List.of("WiFi", "TV", "MiniBar", "RoomService", "Balcony", "Jacuzzi")));
        }
        // 5 PENTHOUSE rooms
        for (int i = 0; i < 5; i++) {
            rooms.add(new Room("R" + String.format("%03d", roomNum++),
                RoomType.PENTHOUSE, 5,
                "Panoramic", "Tower",
                List.of("WiFi", "TV", "MiniBar", "RoomService", "Balcony",
                        "Jacuzzi", "Butler", "PrivateElevator")));
        }
        // 2 PRESIDENTIAL rooms
        for (int i = 0; i < 2; i++) {
            rooms.add(new Room("R" + String.format("%03d", roomNum++),
                RoomType.PRESIDENTIAL, 5,
                "Panoramic", "Tower",
                List.of("WiFi", "TV", "MiniBar", "RoomService", "Balcony",
                        "Jacuzzi", "Butler", "PrivateElevator", "Sauna", "Kitchen")));
        }

        // Create hotel with composable pricing strategy
        PricingStrategy pricing = new WeekendSurchargePricing(
            new LongStayDiscountPricing(
            new EarlyBirdPricing(
            new LastMinutePricing(
            new LoyaltyPricing(
            new SeasonalPricing(
            new BaseRatePricing()))))));

        HotelBookingService hotel = new HotelBookingService("Grand Plaza", rooms, pricing);

        // Create guests — various tiers
        Guest alice = new Guest("G001", "Alice Johnson", "alice@email.com",
            "555-0101", LoyaltyTier.GOLD, 150, LocalDate.now().minusMonths(6));
        Guest bob = new Guest("G002", "Bob Smith", "bob@email.com",
            "555-0102", LoyaltyTier.BRONZE, 5, LocalDate.now().minusDays(1));
        Guest charlie = new Guest("G003", "Charlie Brown", "charlie@email.com",
            "555-0103", LoyaltyTier.PLATINUM, 500, LocalDate.now().minusYears(2));
        Guest diana = new Guest("G004", "Diana Prince", "diana@email.com",
            "555-0104", LoyaltyTier.DIAMOND, 1200, LocalDate.now().minusYears(3));

        // ---- BASIC BOOKING ----
        System.out.println("--- BASIC BOOKINGS ---");
        DateRange weekend = new DateRange(LocalDate.now().plusDays(7), LocalDate.now().plusDays(10));

        System.out.println("Searching rooms for " + weekend + "...");
        var available = hotel.searchRooms(RoomType.SUITE, weekend);
        System.out.println("Available suites: " + available.size());

        // Book rooms — compare pricing by tier
        Booking b1 = hotel.createBooking(alice, RoomType.SUITE, weekend);
        Booking b2 = hotel.createBooking(bob, RoomType.SINGLE,
            new DateRange(LocalDate.now().plusDays(14), LocalDate.now().plusDays(16)));

        System.out.println("\n💰 Pricing Comparison:");
        System.out.printf("  Alice (Gold — 15%% off): $%.2f%n", b1.getTotalAmount());
        System.out.printf("  Bob (Bronze — 5%% off): $%.2f%n", b2.getTotalAmount());

        // ---- BOOKING WITH SPECIAL PRICING ----
        System.out.println("\n--- SPECIAL PRICING ---");

        // Early bird booking (30+ days ahead)
        DateRange earlyBird = new DateRange(LocalDate.now().plusDays(45), LocalDate.now().plusDays(50));
        Booking b3 = hotel.createBooking(charlie, RoomType.PENTHOUSE, earlyBird);
        System.out.printf("  Charlie (Platinum, early bird): $%.2f%n", b3.getTotalAmount());

        // Long stay (weekly discount)
        DateRange longStay = new DateRange(LocalDate.now().plusDays(20), LocalDate.now().plusDays(27));
        Booking b4 = hotel.createBooking(diana, RoomType.DELUXE, longStay);
        System.out.printf("  Diana (Diamond, weekly stay): $%.2f%n", b4.getTotalAmount());

        // ---- GROUP BOOKING ----
        System.out.println("\n--- GROUP BOOKING ---");
        DateRange conference = new DateRange(LocalDate.now().plusDays(60), LocalDate.now().plusDays(63));
        GroupBooking group = hotel.createGroupBooking(
            "GRP-001", "TechConf 2026", "organizer@techconf.com",
            RoomType.DELUXE, conference, 5, 10);
        System.out.printf("Group block created: %s (%d rooms held, min %d)%n",
            group.getGroupId(), group.getMaxRooms(), group.getMinRooms());

        // Add attendees to group
        Booking groupB1 = hotel.addToGroupBooking("GRP-001", bob, RoomType.DELUXE, conference);
        Booking groupB2 = hotel.addToGroupBooking("GRP-001", alice, RoomType.DELUXE, conference);
        System.out.printf("Group bookings: %s, %s%n", groupB1.getId(), groupB2.getId());

        // ---- CANCELLATION WITH REFUND ----
        System.out.println("\n--- CANCELLATION ---");
        double refund = hotel.cancelBooking(b2.getId());
        System.out.printf("  Bob's booking cancelled — refund: $%.2f%n", refund);

        // Check availability after cancellation
        hotel.printAvailability(RoomType.SINGLE, LocalDate.now().plusDays(14), 5);

        // ---- WAITLIST ----
        System.out.println("\n--- WAITLIST ---");
        // Book all single rooms for a date
        DateRange popularDate = new DateRange(LocalDate.now().plusDays(3), LocalDate.now().plusDays(5));
        for (int i = 0; i < 15; i++) {
            try {
                hotel.createBooking(bob, RoomType.SINGLE, popularDate);
            } catch (IllegalStateException e) {
                System.out.println("  All single rooms booked — " + e.getMessage());
                break;
            }
        }

        // This should trigger waitlist
        try {
            hotel.createBooking(diana, RoomType.SINGLE, popularDate);
        } catch (IllegalStateException e) {
            System.out.println("  ✅ " + e.getMessage());
        }

        // ---- CHECK IN / CHECK OUT ----
        System.out.println("\n--- CHECK-IN / CHECK-OUT ---");
        hotel.checkIn(b1.getId());
        System.out.printf("  %s checked in to %s%n", b1.getGuest().name(), b1.getRoom().id());
        hotel.checkOut(b1.getId());
        System.out.printf("  %s checked out from %s%n", b1.getGuest().name(), b1.getRoom().id());

        // ---- GUEST PROFILE ----
        System.out.println("\n--- GUEST PROFILES ---");
        hotel.printGuestHistory("G001"); // Alice
        hotel.printGuestHistory("G004"); // Diana

        // ---- REVENUE REPORT ----
        hotel.getRevenue().printRevenueReport();

        // ---- FINAL STATUS ----
        hotel.printActiveBookings();
        hotel.printAvailability(RoomType.PENTHOUSE, LocalDate.now(), 7);

        hotel.shutdown();
        System.out.println("\n╔══════════════════════════════════╗");
        System.out.println("║       DEMO COMPLETE             ║");
        System.out.println("╚══════════════════════════════════╝");
    }
}
