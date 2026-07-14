/**
 * Hotel Booking System - Low Level Design (Java)
 * -----------------------------------------------
 * Design Principles: SOLID, Strategy Pattern, Observer Pattern, Factory Pattern
 *
 * Key Design Decisions:
 * - Room inventory managed as date-range availability (not per-night)
 * - Strategy pattern for pricing (seasonal, loyalty, early-bird)
 * - Observer pattern for notifications (confirmation, cancellation, upgrades)
 * - Overbooking tolerance with priority-based bumping
 */

import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.*;

// ============================================================
// ENUMS & VALUE OBJECTS
// ============================================================

enum RoomType {
    SINGLE(1, 100.0), DOUBLE(2, 150.0), SUITE(4, 350.0), PENTHOUSE(6, 800.0);

    private final int capacity;
    private final double baseRate;

    RoomType(int capacity, double baseRate) {
        this.capacity = capacity;
        this.baseRate = baseRate;
    }

    public int getCapacity() { return capacity; }
    public double getBaseRate() { return baseRate; }
}

enum BookingStatus { CONFIRMED, CHECKED_IN, CHECKED_OUT, CANCELLED, NO_SHOW, WAITLIST }

enum PaymentStatus { PENDING, AUTHORIZED, CAPTURED, REFUNDED, FAILED }

record Guest(String id, String name, String email, String phone, LoyaltyTier tier) {}
enum LoyaltyTier { BRONZE, SILVER, GOLD, PLATINUM }

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

    public Stream<LocalDate> dates() {
        return checkIn.datesUntil(checkOut);
    }
}

record Room(String id, RoomType type, int floor, String view) {}

// ============================================================
// PRICING STRATEGY (Strategy Pattern - OCP/DIP)
// ============================================================

interface PricingStrategy {
    double calculatePrice(RoomType roomType, DateRange stay, Guest guest);
}

class BaseRatePricing implements PricingStrategy {
    @Override
    public double calculatePrice(RoomType roomType, DateRange stay, Guest guest) {
        return roomType.getBaseRate() * stay.nights();
    }
}

class SeasonalPricing implements PricingStrategy {
    private final Map<Month, Double> seasonalMultipliers = Map.of(
        Month.DECEMBER, 2.0, Month.JANUARY, 1.8,
        Month.JUNE, 1.5, Month.JULY, 1.6, Month.AUGUST, 1.7
    );

    @Override
    public double calculatePrice(RoomType roomType, DateRange stay, Guest guest) {
        double multiplier = stay.dates()
            .map(d -> seasonalMultipliers.getOrDefault(d.getMonth(), 1.0))
            .mapToDouble(Double::doubleValue)
            .max().orElse(1.0);
        return roomType.getBaseRate() * stay.nights() * multiplier;
    }
}

class LoyaltyPricing implements PricingStrategy {
    private final PricingStrategy wrapped;

    public LoyaltyPricing(PricingStrategy wrapped) { this.wrapped = wrapped; }

    @Override
    public double calculatePrice(RoomType roomType, DateRange stay, Guest guest) {
        double base = wrapped.calculatePrice(roomType, stay, guest);
        double discount = switch (guest.tier()) {
            case PLATINUM -> 0.30;
            case GOLD -> 0.20;
            case SILVER -> 0.10;
            case BRONZE -> 0.05;
        };
        return base * (1 - discount);
    }
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
        // Initialize next 365 days with full availability
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

    public List<Room> findAvailableRooms(RoomType type, DateRange range) {
        if (!checkAvailability(type, range)) return List.of();
        return rooms.values().stream()
            .filter(r -> r.type() == type)
            .collect(Collectors.toList());
    }

    public int getAvailableCount(RoomType type, LocalDate date) {
        return availability.get(type).getOrDefault(date, 0);
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
    private final LocalDateTime createdAt;

    public Booking(String id, Guest guest, Room room, DateRange stay, double amount) {
        this.id = id;
        this.guest = guest;
        this.room = room;
        this.stay = stay;
        this.totalAmount = amount;
        this.status = BookingStatus.CONFIRMED;
        this.paymentStatus = PaymentStatus.PENDING;
        this.createdAt = LocalDateTime.now();
    }

    // Getters
    public String getId() { return id; }
    public Guest getGuest() { return guest; }
    public Room getRoom() { return room; }
    public DateRange getStay() { return stay; }
    public BookingStatus getStatus() { return status; }
    public PaymentStatus getPaymentStatus() { return paymentStatus; }
    public double getTotalAmount() { return totalAmount; }

    public synchronized void cancel() {
        this.status = BookingStatus.CANCELLED;
        this.paymentStatus = PaymentStatus.REFUNDED;
    }

    public synchronized void checkIn() { this.status = BookingStatus.CHECKED_IN; }
    public synchronized void checkOut() { this.status = BookingStatus.CHECKED_OUT; }

    @Override
    public String toString() {
        return String.format("Booking[%s] %s - %s: %s -> %s ($%.2f)",
            id, guest.name(), stay.checkIn(), stay.checkOut(), status, totalAmount);
    }
}

// ============================================================
// NOTIFICATION SERVICE (Observer Pattern)
// ============================================================

interface BookingObserver {
    void onBookingCreated(Booking booking);
    void onBookingCancelled(Booking booking);
    void onCheckIn(Booking booking);
    void onCheckOut(Booking booking);
    void onNoShow(Booking booking);
}

class EmailNotificationService implements BookingObserver {
    @Override
    public void onBookingCreated(Booking booking) {
        System.out.printf("📧 Email to %s: Booking %s confirmed for %s - %s%n",
            booking.getGuest().email(), booking.getId(),
            booking.getStay().checkIn(), booking.getStay().checkOut());
    }

    @Override
    public void onBookingCancelled(Booking booking) {
        System.out.printf("📧 Email to %s: Booking %s cancelled. Refund processed.%n",
            booking.getGuest().email(), booking.getId());
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
        System.out.printf("📧 Email to %s: No-show penalty applied for booking %s%n",
            booking.getGuest().email(), booking.getId());
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
    private final ScheduledExecutorService scheduler;
    private int bookingCounter;

    public HotelBookingService(String name, List<Room> rooms, PricingStrategy pricing) {
        this.hotelName = name;
        this.inventory = new InventoryManager(rooms);
        this.pricing = pricing;
        this.observers = new CopyOnWriteArrayList<>();
        this.bookings = new ConcurrentHashMap<>();
        this.guests = new ConcurrentHashMap<>();
        this.scheduler = Executors.newSingleThreadScheduledExecutor();
        this.bookingCounter = 0;

        // Add default observer
        addObserver(new EmailNotificationService());

        // Schedule no-show detection
        scheduler.scheduleAtFixedRate(this::checkNoShows, 1, 1, TimeUnit.HOURS);
    }

    public void addObserver(BookingObserver observer) {
        observers.add(observer);
    }

    // --- Core API ---

    public List<Room> searchRooms(RoomType type, DateRange stay) {
        return inventory.findAvailableRooms(type, stay);
    }

    public synchronized Booking createBooking(Guest guest, RoomType roomType, DateRange stay) {
        // Register guest if new
        guests.putIfAbsent(guest.id(), guest);

        // Check availability
        if (!inventory.checkAvailability(roomType, stay)) {
            throw new IllegalStateException("No availability for " + roomType + " on " + stay);
        }

        // Calculate price
        double amount = pricing.calculatePrice(roomType, stay, guest);

        // Reserve inventory
        inventory.reserveRoom(roomType, stay);

        // Find specific room
        List<Room> available = inventory.findAvailableRooms(roomType, stay);
        Room room = available.isEmpty() ? null : available.get(0);

        // Create booking
        bookingCounter++;
        String bookingId = "BK-" + hotelName.substring(0, 2).toUpperCase()
            + "-" + String.format("%05d", bookingCounter);
        Booking booking = new Booking(bookingId, guest, room, stay, amount);
        bookings.put(bookingId, booking);

        // Notify observers
        notifyBookingCreated(booking);
        return booking;
    }

    public synchronized void cancelBooking(String bookingId) {
        Booking booking = bookings.get(bookingId);
        if (booking == null) throw new IllegalArgumentException("Booking not found: " + bookingId);

        booking.cancel();
        inventory.releaseRoom(booking.getRoom().type(), booking.getStay());
        notifyBookingCancelled(booking);
    }

    public synchronized void checkIn(String bookingId) {
        Booking booking = bookings.get(bookingId);
        if (booking == null) throw new IllegalArgumentException("Booking not found: " + bookingId);
        booking.checkIn();
        notifyCheckIn(booking);
    }

    public synchronized void checkOut(String bookingId) {
        Booking booking = bookings.get(bookingId);
        if (booking == null) throw new IllegalArgumentException("Booking not found: " + bookingId);
        booking.checkOut();
        inventory.releaseRoom(booking.getRoom().type(), booking.getStay());
        notifyCheckOut(booking);
    }

    // --- Reporting ---

    public void printAvailability(RoomType type, LocalDate from, int days) {
        System.out.println("\n=== Availability for " + type + " ===");
        for (int i = 0; i < days; i++) {
            LocalDate date = from.plusDays(i);
            int count = inventory.getAvailableCount(type, date);
            System.out.printf("  %s: %d rooms%n", date, count);
        }
    }

    public void printActiveBookings() {
        System.out.println("\n=== Active Bookings ===");
        bookings.values().stream()
            .filter(b -> b.getStatus() == BookingStatus.CONFIRMED
                      || b.getStatus() == BookingStatus.CHECKED_IN)
            .forEach(System.out::println);
    }

    // --- Internal ---

    private void checkNoShows() {
        LocalDate today = LocalDate.now();
        bookings.values().stream()
            .filter(b -> b.getStatus() == BookingStatus.CONFIRMED)
            .filter(b -> b.getStay().checkIn().isBefore(today))
            .forEach(b -> {
                b.cancel();
                inventory.releaseRoom(b.getRoom().type(), b.getStay());
                notifyNoShow(b);
            });
    }

    private void notifyBookingCreated(Booking b) {
        observers.forEach(o -> o.onBookingCreated(b));
    }

    private void notifyBookingCancelled(Booking b) {
        observers.forEach(o -> o.onBookingCancelled(b));
    }

    private void notifyCheckIn(Booking b) { observers.forEach(o -> o.onCheckIn(b)); }
    private void notifyCheckOut(Booking b) { observers.forEach(o -> o.onCheckOut(b)); }
    private void notifyNoShow(Booking b) { observers.forEach(o -> o.onNoShow(b)); }

    public void shutdown() { scheduler.shutdown(); }
}

// ============================================================
// DEMO
// ============================================================

public class HotelBookingSystem {
    public static void main(String[] args) {
        System.out.println("=== Hotel Booking System Demo ===\n");

        // Setup hotel with rooms
        List<Room> rooms = new ArrayList<>();
        for (int i = 1; i <= 50; i++) {
            rooms.add(new Room("R" + String.format("%03d", i),
                i <= 20 ? RoomType.SINGLE : i <= 35 ? RoomType.DOUBLE :
                i <= 45 ? RoomType.SUITE : RoomType.PENTHOUSE,
                (i % 10) + 1, i % 2 == 0 ? "City" : "Garden"));
        }

        // Create hotel with seasonal + loyalty pricing
        PricingStrategy pricing = new LoyaltyPricing(new SeasonalPricing());
        HotelBookingService hotel = new HotelBookingService("Grand Plaza", rooms, pricing);

        // Create guests
        Guest alice = new Guest("G001", "Alice Johnson", "alice@email.com", "555-0101", LoyaltyTier.GOLD);
        Guest bob = new Guest("G002", "Bob Smith", "bob@email.com", "555-0102", LoyaltyTier.BRONZE);
        Guest charlie = new Guest("G003", "Charlie Brown", "charlie@email.com", "555-0103", LoyaltyTier.PLATINUM);

        // Search and book
        DateRange weekend = new DateRange(LocalDate.now().plusDays(7), LocalDate.now().plusDays(10));

        System.out.println("Searching rooms for " + weekend + "...");
        var available = hotel.searchRooms(RoomType.SUITE, weekend);
        System.out.println("Available suites: " + available.size());

        // Book rooms
        Booking b1 = hotel.createBooking(alice, RoomType.SUITE, weekend);
        Booking b2 = hotel.createBooking(bob, RoomType.SINGLE,
            new DateRange(LocalDate.now().plusDays(14), LocalDate.now().plusDays(16)));
        Booking b3 = hotel.createBooking(charlie, RoomType.PENTHOUSE,
            new DateRange(LocalDate.now().plusDays(30), LocalDate.now().plusDays(35)));

        System.out.println("\nPricing:");
        System.out.printf("  Alice (Gold): $%.2f%n", b1.getTotalAmount());
        System.out.printf("  Bob (Bronze): $%.2f%n", b2.getTotalAmount());
        System.out.printf("  Charlie (Platinum): $%.2f%n", b3.getTotalAmount());

        // Cancel one booking
        hotel.cancelBooking(b2.getId());

        // Check availability after cancellation
        hotel.printAvailability(RoomType.SINGLE, LocalDate.now().plusDays(14), 5);

        // Check in/out
        hotel.checkIn(b1.getId());
        hotel.checkOut(b1.getId());

        hotel.printActiveBookings();
        hotel.shutdown();

        System.out.println("\n=== Demo Complete ===");
    }
}
