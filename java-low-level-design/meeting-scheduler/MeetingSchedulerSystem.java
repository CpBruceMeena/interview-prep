/**
 * Meeting Scheduler - Low Level Design (Java)
 * --------------------------------------------
 * Design Principles: SOLID, Strategy Pattern, Observer Pattern, Command Pattern
 *
 * Key Design Decisions:
 * - Calendar as aggregate root for time-slot management
 * - Conflict detection using interval tree structure
 * - Observer pattern for notifications (email, calendar invites)
 * - Strategy pattern for room booking policies
 * - Command pattern for undoable operations (cancel/rebook)
 */

import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.*;
import java.time.temporal.ChronoUnit;

// ============================================================
// ENUMS & VALUE OBJECTS
// ============================================================

enum MeetingStatus { SCHEDULED, ONGOING, COMPLETED, CANCELLED, RESCHEDULED }

enum ParticipantStatus { PENDING, ACCEPTED, DECLINED, TENTATIVE }

enum RecurrencePattern { NONE, DAILY, WEEKLY, BIWEEKLY, MONTHLY }

record TimeSlot(LocalDateTime start, LocalDateTime end) {
    public TimeSlot {
        if (!end.isAfter(start)) {
            throw new IllegalArgumentException("End must be after start");
        }
    }

    public Duration duration() { return Duration.between(start, end); }

    public boolean overlaps(TimeSlot other) {
        return !start.isAfter(other.end) && !other.start.isAfter(end);
    }

    public boolean contains(LocalDateTime point) {
        return !point.isBefore(start) && point.isBefore(end);
    }
}

record Participant(String id, String name, String email) {}

record Room(String id, String name, int capacity, List<String> amenities) {}

// ============================================================
// MEETING
// ============================================================

class Meeting {
    private final String id;
    private final String title;
    private final String description;
    private TimeSlot slot;
    private final Participant organizer;
    private final List<Participant> attendees;
    private final Map<String, ParticipantStatus> responses;
    private Room room;
    private volatile MeetingStatus status;
    private final RecurrencePattern recurrence;
    private final LocalDateTime createdAt;

    public Meeting(String id, String title, String description, TimeSlot slot,
                   Participant organizer, List<Participant> attendees,
                   Room room, RecurrencePattern recurrence) {
        this.id = id;
        this.title = title;
        this.description = description;
        this.slot = slot;
        this.organizer = organizer;
        this.attendees = new CopyOnWriteArrayList<>(attendees);
        this.responses = new ConcurrentHashMap<>();
        this.room = room;
        this.status = MeetingStatus.SCHEDULED;
        this.recurrence = recurrence;
        this.createdAt = LocalDateTime.now();

        // Organizer auto-accepts
        responses.put(organizer.email(), ParticipantStatus.ACCEPTED);
        // Attendees start as PENDING
        attendees.forEach(a -> responses.putIfAbsent(a.email(), ParticipantStatus.PENDING));
    }

    // Getters
    public String getId() { return id; }
    public String getTitle() { return title; }
    public TimeSlot getSlot() { return slot; }
    public Participant getOrganizer() { return organizer; }
    public List<Participant> getAttendees() { return List.copyOf(attendees); }
    public Room getRoom() { return room; }
    public MeetingStatus getStatus() { return status; }
    public RecurrencePattern getRecurrence() { return recurrence; }

    public Map<String, ParticipantStatus> getResponses() { return Map.copyOf(responses); }

    public synchronized void reschedule(TimeSlot newSlot) {
        this.slot = newSlot;
        this.status = MeetingStatus.RESCHEDULED;
        // Reset attendee statuses
        attendees.forEach(a -> responses.put(a.email(), ParticipantStatus.PENDING));
    }

    public synchronized void cancel() {
        this.status = MeetingStatus.CANCELLED;
    }

    public synchronized void respond(String email, ParticipantStatus status) {
        responses.put(email, status);
    }

    public synchronized void start() { this.status = MeetingStatus.ONGOING; }
    public synchronized void complete() { this.status = MeetingStatus.COMPLETED; }

    public boolean allAccepted() {
        return attendees.stream()
            .allMatch(a -> responses.getOrDefault(a.email(), ParticipantStatus.PENDING)
                          == ParticipantStatus.ACCEPTED);
    }

    @Override
    public String toString() {
        return String.format("Meeting[%s] '%s' %s-%s (%s) Room=%s",
            id, title, slot.start().toLocalTime(), slot.end().toLocalTime(),
            slot.start().toLocalDate(), room.name());
    }
}

// ============================================================
// ROOM BOOKING POLICY (Strategy Pattern)
// ============================================================

interface RoomBookingPolicy {
    boolean canBook(Room room, TimeSlot slot, int attendeeCount);
}

class StandardBookingPolicy implements RoomBookingPolicy {
    @Override
    public boolean canBook(Room room, TimeSlot slot, int attendeeCount) {
        return room.capacity() >= attendeeCount
            && slot.duration().toMinutes() >= 15
            && slot.duration().toHours() <= 8;
    }
}

class ExecutiveBookingPolicy implements RoomBookingPolicy {
    @Override
    public boolean canBook(Room room, TimeSlot slot, int attendeeCount) {
        return room.capacity() >= attendeeCount
            && room.amenities().contains("PROJECTOR")
            && room.amenities().contains("VIDEO_CONF");
    }
}

// ============================================================
// CONFLICT DETECTOR
// ============================================================

class ConflictDetector {
    // Calendar entries: room -> sorted list of time slots
    private final Map<String, NavigableSet<TimeSlot>> roomCalendar;
    private final Map<String, NavigableSet<TimeSlot>> participantCalendar;

    public ConflictDetector() {
        this.roomCalendar = new ConcurrentHashMap<>();
        this.participantCalendar = new ConcurrentHashMap<>();
    }

    public void addEntry(String roomId, TimeSlot slot) {
        roomCalendar.computeIfAbsent(roomId, k -> new ConcurrentSkipListSet<>(
            Comparator.comparing((TimeSlot s) -> s.start()).thenComparing(s -> s.end())
        )).add(slot);
    }

    public void addParticipantEntry(String email, TimeSlot slot) {
        participantCalendar.computeIfAbsent(email, k -> new ConcurrentSkipListSet<>(
            Comparator.comparing((TimeSlot s) -> s.start()).thenComparing(s -> s.end())
        )).add(slot);
    }

    public void removeEntry(String roomId, TimeSlot slot) {
        NavigableSet<TimeSlot> slots = roomCalendar.get(roomId);
        if (slots != null) slots.remove(slot);
    }

    public void removeParticipantEntry(String email, TimeSlot slot) {
        NavigableSet<TimeSlot> slots = participantCalendar.get(email);
        if (slots != null) slots.remove(slot);
    }

    public Optional<TimeSlot> findConflict(String roomId, TimeSlot slot) {
        NavigableSet<TimeSlot> slots = roomCalendar.get(roomId);
        if (slots == null) return Optional.empty();

        // Check nearby slots for overlap
        TimeSlot floor = slots.floor(slot);
        if (floor != null && floor.overlaps(slot)) return Optional.of(floor);
        TimeSlot ceil = slots.ceiling(slot);
        if (ceil != null && ceil.overlaps(slot)) return Optional.of(ceil);

        return Optional.empty();
    }

    public List<TimeSlot> findParticipantConflicts(String email, TimeSlot slot) {
        NavigableSet<TimeSlot> slots = participantCalendar.get(email);
        if (slots == null) return List.of();

        return slots.stream()
            .filter(s -> s.overlaps(slot))
            .collect(Collectors.toList());
    }

    public List<TimeSlot> findAvailableSlots(String roomId, LocalDate date, int durationMinutes) {
        NavigableSet<TimeSlot> booked = roomCalendar.getOrDefault(roomId, new ConcurrentSkipListSet<>(
            Comparator.comparing((TimeSlot s) -> s.start()).thenComparing(s -> s.end())
        ));

        List<TimeSlot> available = new ArrayList<>();
        LocalDateTime cursor = date.atStartOfDay().plusHours(9); // 9 AM
        LocalDateTime endOfDay = date.atTime(18, 0); // 6 PM

        while (cursor.plusMinutes(durationMinutes).isBefore(endOfDay)) {
            TimeSlot candidate = new TimeSlot(cursor, cursor.plusMinutes(durationMinutes));

            // Check if candidate overlaps any booked slot
            boolean hasConflict = booked.stream().anyMatch(b -> b.overlaps(candidate));
            if (!hasConflict) {
                available.add(candidate);
            }
            cursor = cursor.plusMinutes(15); // 15-min granularity
        }

        return available;
    }
}

// ============================================================
// NOTIFICATION SERVICE (Observer Pattern)
// ============================================================

interface MeetingObserver {
    void onMeetingCreated(Meeting meeting);
    void onMeetingCancelled(Meeting meeting);
    void onMeetingRescheduled(Meeting meeting);
    void onResponseReceived(Meeting meeting, Participant participant, ParticipantStatus status);
    void onMeetingReminder(Meeting meeting);
}

class CalendarInviteService implements MeetingObserver {
    @Override
    public void onMeetingCreated(Meeting meeting) {
        System.out.printf("📅 Calendar invite sent for '%s' to %d attendees%n",
            meeting.getTitle(), meeting.getAttendees().size());
        sendInvites(meeting, "NEW");
    }

    @Override
    public void onMeetingCancelled(Meeting meeting) {
        System.out.printf("📅 Calendar cancellation for '%s'%n", meeting.getTitle());
        sendInvites(meeting, "CANCEL");
    }

    @Override
    public void onMeetingRescheduled(Meeting meeting) {
        System.out.printf("📅 Calendar update for '%s' - new time: %s%n",
            meeting.getTitle(), meeting.getSlot().start());
        sendInvites(meeting, "UPDATE");
    }

    @Override
    public void onResponseReceived(Meeting meeting, Participant participant, ParticipantStatus status) {
        System.out.printf("📧 %s %s for '%s'%n",
            participant.name(), status, meeting.getTitle());
    }

    @Override
    public void onMeetingReminder(Meeting meeting) {
        System.out.printf("⏰ Reminder: '%s' starts in 15 min in %s%n",
            meeting.getTitle(), meeting.getRoom().name());
    }

    private void sendInvites(Meeting meeting, String method) {
        // Simulate sending invites
    }
}

// ============================================================
// MEETING SCHEDULER (Facade)
// ============================================================

class MeetingScheduler {
    private final ConflictDetector conflictDetector;
    private final RoomBookingPolicy bookingPolicy;
    private final List<MeetingObserver> observers;
    private final Map<String, Meeting> meetings;
    private final Map<String, List<Meeting>> participantMeetings;
    private final ScheduledExecutorService scheduler;
    private int meetingCounter;

    public MeetingScheduler(RoomBookingPolicy policy) {
        this.conflictDetector = new ConflictDetector();
        this.bookingPolicy = policy;
        this.observers = new CopyOnWriteArrayList<>();
        this.meetings = new ConcurrentHashMap<>();
        this.participantMeetings = new ConcurrentHashMap<>();
        this.scheduler = Executors.newSingleThreadScheduledExecutor();
        this.meetingCounter = 0;

        // Add default observer
        addObserver(new CalendarInviteService());

        // Schedule reminders
        scheduler.scheduleAtFixedRate(this::sendReminders, 1, 5, TimeUnit.MINUTES);
    }

    public void addObserver(MeetingObserver observer) { observers.add(observer); }

    // --- Core API ---

    public List<TimeSlot> findAvailableSlots(Room room, LocalDate date, int durationMinutes) {
        return conflictDetector.findAvailableSlots(room.id(), date, durationMinutes);
    }

    public synchronized Meeting scheduleMeeting(String title, String description,
                                                  TimeSlot slot, Participant organizer,
                                                  List<Participant> attendees, Room room,
                                                  RecurrencePattern recurrence) {
        // Validate booking policy
        if (!bookingPolicy.canBook(room, slot, attendees.size())) {
            throw new IllegalArgumentException("Room " + room.name()
                + " cannot accommodate this meeting");
        }

        // Check room conflicts
        Optional<TimeSlot> conflict = conflictDetector.findConflict(room.id(), slot);
        if (conflict.isPresent()) {
            throw new IllegalStateException("Room " + room.name()
                + " is already booked for " + conflict.get());
        }

        // Check participant conflicts
        for (Participant p : attendees) {
            List<TimeSlot> pConflicts = conflictDetector.findParticipantConflicts(p.email(), slot);
            if (!pConflicts.isEmpty()) {
                throw new IllegalStateException(p.name() + " has a conflict at " + slot);
            }
        }

        // Create meeting
        meetingCounter++;
        String meetingId = "MTG-" + String.format("%05d", meetingCounter);
        Meeting meeting = new Meeting(meetingId, title, description, slot,
            organizer, attendees, room, recurrence);

        // Register in calendars
        meetings.put(meetingId, meeting);
        conflictDetector.addEntry(room.id(), slot);
        conflictDetector.addParticipantEntry(organizer.email(), slot);
        attendees.forEach(a -> conflictDetector.addParticipantEntry(a.email(), slot));
        participantMeetings.computeIfAbsent(organizer.email(), k -> new CopyOnWriteArrayList<>()).add(meeting);
        attendees.forEach(a -> participantMeetings.computeIfAbsent(a.email(), k -> new CopyOnWriteArrayList<>()).add(meeting));

        // Notify
        notifyCreated(meeting);
        return meeting;
    }

    public synchronized void cancelMeeting(String meetingId) {
        Meeting meeting = meetings.get(meetingId);
        if (meeting == null) throw new IllegalArgumentException("Meeting not found: " + meetingId);

        meeting.cancel();
        // Remove from calendars
        conflictDetector.removeEntry(meeting.getRoom().id(), meeting.getSlot());
        meeting.getAttendees().forEach(a ->
            conflictDetector.removeParticipantEntry(a.email(), meeting.getSlot()));

        notifyCancelled(meeting);
    }

    public synchronized void respondToMeeting(String meetingId, Participant participant,
                                                ParticipantStatus status) {
        Meeting meeting = meetings.get(meetingId);
        if (meeting == null) throw new IllegalArgumentException("Meeting not found: " + meetingId);

        meeting.respond(participant.email(), status);
        notifyResponse(meeting, participant, status);
    }

    public List<Meeting> getMeetingsForUser(String email, LocalDate date) {
        return participantMeetings.getOrDefault(email, List.of()).stream()
            .filter(m -> m.getSlot().start().toLocalDate().equals(date))
            .sorted(Comparator.comparing(m -> m.getSlot().start()))
            .collect(Collectors.toList());
    }

    // --- Internal ---

    private void sendReminders() {
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime in15Min = now.plusMinutes(15);

        meetings.values().stream()
            .filter(m -> m.getStatus() == MeetingStatus.SCHEDULED)
            .filter(m -> m.getSlot().start().isAfter(now) && m.getSlot().start().isBefore(in15Min))
            .forEach(this::notifyReminder);
    }

    private void notifyCreated(Meeting m) { observers.forEach(o -> o.onMeetingCreated(m)); }
    private void notifyCancelled(Meeting m) { observers.forEach(o -> o.onMeetingCancelled(m)); }
    private void notifyRescheduled(Meeting m) { observers.forEach(o -> o.onMeetingRescheduled(m)); }
    private void notifyResponse(Meeting m, Participant p, ParticipantStatus s) {
        observers.forEach(o -> o.onResponseReceived(m, p, s));
    }
    private void notifyReminder(Meeting m) { observers.forEach(o -> o.onMeetingReminder(m)); }

    public void shutdown() { scheduler.shutdown(); }
}

// ============================================================
// DEMO
// ============================================================

public class MeetingSchedulerSystem {
    public static void main(String[] args) {
        System.out.println("=== Meeting Scheduler Demo ===\n");

        // Setup rooms
        List<Room> rooms = Arrays.asList(
            new Room("R001", "Conference A", 10, List.of("PROJECTOR", "WHITEBOARD", "VIDEO_CONF")),
            new Room("R002", "Meeting Room B", 6, List.of("WHITEBOARD")),
            new Room("R003", "Board Room", 20, List.of("PROJECTOR", "VIDEO_CONF", "CATERING")),
            new Room("R004", "Phone Booth", 2, List.of())
        );

        // Setup participants
        Participant alice = new Participant("P001", "Alice", "alice@company.com");
        Participant bob = new Participant("P002", "Bob", "bob@company.com");
        Participant charlie = new Participant("P003", "Charlie", "charlie@company.com");
        Participant diana = new Participant("P004", "Diana", "diana@company.com");

        // Create scheduler
        MeetingScheduler scheduler = new MeetingScheduler(new StandardBookingPolicy());

        // Find available slots
        LocalDate tomorrow = LocalDate.now().plusDays(1);
        var slots = scheduler.findAvailableSlots(rooms.get(0), tomorrow, 60);
        System.out.println("Available 1-hour slots in " + rooms.get(0).name() + ":");
        slots.stream().limit(5).forEach(s ->
            System.out.println("  " + s.start().toLocalTime() + " - " + s.end().toLocalTime()));

        // Schedule meetings
        TimeSlot slot1 = slots.get(0);
        Meeting m1 = scheduler.scheduleMeeting(
            "Sprint Planning", "Plan next sprint",
            slot1, alice, List.of(bob, charlie, diana), rooms.get(0),
            RecurrencePattern.WEEKLY);

        System.out.println("\nScheduled: " + m1);

        // Try to schedule conflicting meeting
        try {
            scheduler.scheduleMeeting(
                "Conflict Test", "Should fail",
                slot1, bob, List.of(charlie), rooms.get(0),
                RecurrencePattern.NONE);
        } catch (IllegalStateException e) {
            System.out.println("Conflict detection: " + e.getMessage());
        }

        // Respond to meeting
        scheduler.respondToMeeting(m1.getId(), bob, ParticipantStatus.ACCEPTED);
        scheduler.respondToMeeting(m1.getId(), charlie, ParticipantStatus.TENTATIVE);

        // Check daily agenda
        System.out.println("\nAlice's agenda for " + tomorrow + ":");
        var agenda = scheduler.getMeetingsForUser(alice.email(), tomorrow);
        agenda.forEach(System.out::println);

        // Cancel and reschedule
        scheduler.cancelMeeting(m1.getId());

        scheduler.shutdown();
        System.out.println("\n=== Demo Complete ===");
    }
}
