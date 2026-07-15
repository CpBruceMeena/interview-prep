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
 * - Recurring meeting expansion with exception handling
 * - Room recommendation based on attendee count and amenities
 * - Meeting analytics for usage tracking
 */

import java.time.*;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.time.temporal.TemporalAdjusters;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.*;

// ============================================================
// ENUMS & VALUE OBJECTS
// ============================================================

enum MeetingStatus { SCHEDULED, ONGOING, COMPLETED, CANCELLED, RESCHEDULED }

enum ParticipantStatus { PENDING, ACCEPTED, DECLINED, TENTATIVE }

enum RecurrencePattern { NONE, DAILY, WEEKLY, BIWEEKLY, MONTHLY, YEARLY }

enum RoomFeature {
    PROJECTOR, WHITEBOARD, VIDEO_CONF, CATERING, PHONE,
    STANDING_DESK, STAGE, SOUND_SYSTEM, LARGE_SCREEN
}

record TimeSlot(LocalDateTime start, LocalDateTime end) {
    public TimeSlot {
        if (!end.isAfter(start)) {
            throw new IllegalArgumentException("End must be after start");
        }
    }

    public Duration duration() { return Duration.between(start, end); }

    public long durationMinutes() { return ChronoUnit.MINUTES.between(start, end); }

    public boolean overlaps(TimeSlot other) {
        return !start.isAfter(other.end) && !other.start.isAfter(end);
    }

    public boolean contains(LocalDateTime point) {
        return !point.isBefore(start) && point.isBefore(end);
    }

    public boolean isWithinWorkingHours() {
        int startHour = start.getHour();
        int endHour = end.getHour();
        return startHour >= 9 && endHour <= 18 && start.getDayOfWeek() != DayOfWeek.SATURDAY
            && start.getDayOfWeek() != DayOfWeek.SUNDAY;
    }

    public TimeSlot shift(Duration offset) {
        return new TimeSlot(start.plus(offset), end.plus(offset));
    }
}

record Participant(String id, String name, String email, String department,
                   String timezone, boolean isAssistant) {
    public Participant(String id, String name, String email) {
        this(id, name, email, "General", "UTC", false);
    }
}

record Room(String id, String name, int capacity, String building, int floor,
            List<RoomFeature> features) {
    public Room(String id, String name, int capacity, List<String> featureNames) {
        this(id, name, capacity, "Building A", 1,
            featureNames.stream()
                .map(n -> {
                    try { return RoomFeature.valueOf(n); }
                    catch (IllegalArgumentException e) { return null; }
                })
                .filter(Objects::nonNull)
                .collect(Collectors.toList()));
    }

    public boolean hasAllFeatures(List<RoomFeature> required) {
        return features.containsAll(required);
    }

    public boolean canAccommodate(int attendeeCount) {
        return capacity >= attendeeCount;
    }

    public int scoreForMeeting(int attendeeCount, List<RoomFeature> required) {
        int score = 0;
        // Capacity match (closer to attendee count = better, but not under)
        if (capacity < attendeeCount) return -1;
        score += 10 - (capacity - attendeeCount) / 5; // Prefer right-sized rooms

        // Feature match
        for (RoomFeature f : required) {
            if (features.contains(f)) score += 5;
        }
        return score;
    }
}

// ============================================================
// MEETING SERIES (Recurring Meeting Support)
// ============================================================

class MeetingSeries {
    private final String seriesId;
    private final String title;
    private final String description;
    private final TimeSlot templateSlot;  // The original time slot
    private final RecurrencePattern pattern;
    private final List<Participant> attendees;
    private final Participant organizer;
    private final Room preferredRoom;
    private final LocalDate seriesStart;
    private final LocalDate seriesEnd;
    private final Set<LocalDate> exceptionDates; // Dates where meeting is cancelled
    private final Map<LocalDate, TimeSlot> modifiedSlots; // Date -> modified time
    private final int maxInstances;

    public MeetingSeries(String seriesId, String title, String description,
                         TimeSlot templateSlot, RecurrencePattern pattern,
                         List<Participant> attendees, Participant organizer,
                         Room preferredRoom, LocalDate seriesStart, LocalDate seriesEnd) {
        this.seriesId = seriesId;
        this.title = title;
        this.description = description;
        this.templateSlot = templateSlot;
        this.pattern = pattern;
        this.attendees = new CopyOnWriteArrayList<>(attendees);
        this.organizer = organizer;
        this.preferredRoom = preferredRoom;
        this.seriesStart = seriesStart;
        this.seriesEnd = seriesEnd;
        this.exceptionDates = ConcurrentHashMap.newKeySet();
        this.modifiedSlots = new ConcurrentHashMap<>();
        this.maxInstances = 52; // Default: 1 year of weekly meetings
    }

    public List<MeetingInstance> expand(LocalDate fromDate, LocalDate toDate) {
        List<MeetingInstance> instances = new ArrayList<>();
        LocalDate current = fromDate.isAfter(seriesStart) ? fromDate : seriesStart;

        int count = 0;
        while (!current.isAfter(toDate) && !current.isAfter(seriesEnd) && count < maxInstances) {
            boolean shouldSchedule = switch (pattern) {
                case NONE -> false;
                case DAILY -> true;
                case WEEKLY -> current.getDayOfWeek() == templateSlot.start().getDayOfWeek();
                case BIWEEKLY -> current.getDayOfWeek() == templateSlot.start().getDayOfWeek()
                    && (ChronoUnit.WEEKS.between(seriesStart, current) % 2 == 0);
                case MONTHLY -> current.getDayOfMonth() == templateSlot.start().getDayOfMonth();
                case YEARLY -> current.getDayOfYear() == templateSlot.start().getDayOfYear();
            };

            if (shouldSchedule && !exceptionDates.contains(current)) {
                LocalTime startTime = templateSlot.start().toLocalTime();
                LocalTime endTime = templateSlot.end().toLocalTime();

                // Check for modified time on this date
                TimeSlot slot = modifiedSlots.getOrDefault(current,
                    new TimeSlot(LocalDateTime.of(current, startTime),
                                 LocalDateTime.of(current, endTime)));

                if (slot.start().getDayOfWeek() != DayOfWeek.SATURDAY
                    && slot.start().getDayOfWeek() != DayOfWeek.SUNDAY) {
                    instances.add(new MeetingInstance(
                        seriesId + "-" + count,
                        title, description, slot, organizer,
                        attendees, preferredRoom, seriesId, current));
                    count++;
                }
            }

            current = current.plusDays(1);
        }

        return instances;
    }

    public void cancelInstance(LocalDate date) {
        exceptionDates.add(date);
    }

    public void modifyInstance(LocalDate date, TimeSlot newSlot) {
        if (!exceptionDates.contains(date)) {
            modifiedSlots.put(date, newSlot);
        }
    }

    public String getSeriesId() { return seriesId; }
    public RecurrencePattern getPattern() { return pattern; }
}

record MeetingInstance(String id, String title, String description,
                       TimeSlot slot, Participant organizer,
                       List<Participant> attendees, Room room,
                       String seriesId, LocalDate date) {
    public boolean isRecurring() { return seriesId != null; }
}

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
    private final String seriesId;
    private final LocalDateTime createdAt;
    private LocalDateTime lastModifiedAt;
    private final List<String> notes;
    private String cancellationReason;

    public Meeting(String id, String title, String description, TimeSlot slot,
                   Participant organizer, List<Participant> attendees,
                   Room room, RecurrencePattern recurrence, String seriesId) {
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
        this.seriesId = seriesId;
        this.createdAt = LocalDateTime.now();
        this.lastModifiedAt = LocalDateTime.now();
        this.notes = new CopyOnWriteArrayList<>();

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
    public String getSeriesId() { return seriesId; }
    public boolean isRecurring() { return seriesId != null; }
    public String getCancellationReason() { return cancellationReason; }

    public Map<String, ParticipantStatus> getResponses() { return Map.copyOf(responses); }

    public synchronized void reschedule(TimeSlot newSlot) {
        this.slot = newSlot;
        this.status = MeetingStatus.RESCHEDULED;
        this.lastModifiedAt = LocalDateTime.now();
        // Reset attendee statuses
        attendees.forEach(a -> responses.put(a.email(), ParticipantStatus.PENDING));
    }

    public synchronized void cancel(String reason) {
        this.status = MeetingStatus.CANCELLED;
        this.cancellationReason = reason;
        this.lastModifiedAt = LocalDateTime.now();
    }

    public synchronized void respond(String email, ParticipantStatus status) {
        responses.put(email, status);
    }

    public synchronized void start() { this.status = MeetingStatus.ONGOING; }
    public synchronized void complete() { this.status = MeetingStatus.COMPLETED; }

    public synchronized void addNote(String note) { notes.add(note); }
    public List<String> getNotes() { return List.copyOf(notes); }

    public boolean allAccepted() {
        return attendees.stream()
            .allMatch(a -> responses.getOrDefault(a.email(), ParticipantStatus.PENDING)
                          == ParticipantStatus.ACCEPTED);
    }

    public boolean hasAcceptedCount() {
        return attendees.stream()
            .filter(a -> responses.getOrDefault(a.email(), ParticipantStatus.PENDING)
                      == ParticipantStatus.ACCEPTED)
            .count();
    }

    @Override
    public String toString() {
        return String.format("Meeting[%s] '%s' %s-%s (%s) Room=%s Status=%s",
            id, title, slot.start().toLocalTime(), slot.end().toLocalTime(),
            slot.start().toLocalDate(), room.name(), status);
    }

    public String toDetailedString() {
        StringBuilder sb = new StringBuilder();
        sb.append(String.format("╔══════════════════════════════════╗%n"));
        sb.append(String.format("║ %-32s ║%n", title));
        sb.append(String.format("╠══════════════════════════════════╣%n"));
        sb.append(String.format("║ ID:     %-24s ║%n", id));
        sb.append(String.format("║ Date:   %-24s ║%n", slot.start().toLocalDate()));
        sb.append(String.format("║ Time:   %s - %s        ║%n",
            slot.start().toLocalTime(), slot.end().toLocalTime()));
        sb.append(String.format("║ Room:   %-24s ║%n", room.name()));
        sb.append(String.format("║ Status: %-24s ║%n", status));
        sb.append(String.format("║ Organizer: %-20s ║%n", organizer.name()));
        sb.append(String.format("║ Attendees: %d/%-18d ║%n",
            hasAcceptedCount(), attendees.size()));
        if (isRecurring()) {
            sb.append(String.format("║ Series: %-22s ║%n", seriesId));
            sb.append(String.format("║ Pattern: %-22s ║%n", recurrence));
        }
        sb.append(String.format("╚══════════════════════════════════╝"));
        return sb.toString();
    }
}

// ============================================================
// ROOM BOOKING POLICY (Strategy Pattern)
// ============================================================

interface RoomBookingPolicy {
    boolean canBook(Room room, TimeSlot slot, int attendeeCount, List<RoomFeature> requiredFeatures);
    String rejectionReason();
}

class StandardBookingPolicy implements RoomBookingPolicy {
    @Override
    public boolean canBook(Room room, TimeSlot slot, int attendeeCount, List<RoomFeature> requiredFeatures) {
        return room.capacity() >= attendeeCount
            && slot.durationMinutes() >= 15
            && slot.durationMinutes() <= 480  // Max 8 hours
            && room.hasAllFeatures(requiredFeatures);
    }

    @Override
    public String rejectionReason() { return "Room does not meet standard booking criteria"; }
}

class ExecutiveBookingPolicy implements RoomBookingPolicy {
    @Override
    public boolean canBook(Room room, TimeSlot slot, int attendeeCount, List<RoomFeature> requiredFeatures) {
        return room.capacity() >= attendeeCount
            && room.hasAllFeatures(requiredFeatures)
            && (room.features().contains(RoomFeature.VIDEO_CONF)
                || room.features().contains(RoomFeature.PROJECTOR));
    }

    @Override
    public String rejectionReason() { return "Room lacks executive features (projector/video conf)"; }
}

class CompositingBookingPolicy implements RoomBookingPolicy {
    private final List<RoomBookingPolicy> policies;

    public CompositingBookingPolicy(RoomBookingPolicy... policies) {
        this.policies = Arrays.asList(policies);
    }

    @Override
    public boolean canBook(Room room, TimeSlot slot, int attendeeCount, List<RoomFeature> requiredFeatures) {
        return policies.stream().allMatch(p -> p.canBook(room, slot, attendeeCount, requiredFeatures));
    }

    @Override
    public String rejectionReason() {
        return policies.stream()
            .map(RoomBookingPolicy::rejectionReason)
            .collect(Collectors.joining("; "));
    }
}

// ============================================================
// CONFLICT DETECTOR (Interval Tree Based)
// ============================================================

class ConflictDetector {
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

        // Check nearby slots for overlap (O(log n))
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

    public Map<String, List<TimeSlot>> findAllParticipantConflicts(List<String> emails, TimeSlot slot) {
        return emails.stream()
            .collect(Collectors.toMap(
                email -> email,
                email -> findParticipantConflicts(email, slot)
            ))
            .entrySet().stream()
            .filter(e -> !e.getValue().isEmpty())
            .collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue));
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

            if (candidate.isWithinWorkingHours()) {
                boolean hasConflict = booked.stream().anyMatch(b -> b.overlaps(candidate));
                if (!hasConflict) {
                    available.add(candidate);
                }
            }
            cursor = cursor.plusMinutes(15); // 15-min granularity
        }

        return available;
    }

    public List<TimeSlot> findMutualAvailableSlots(List<String> roomIds, List<String> participantEmails,
                                                    LocalDate date, int durationMinutes) {
        // Check all rooms for availability
        List<TimeSlot> candidates = new ArrayList<>();
        for (String roomId : roomIds) {
            candidates.addAll(findAvailableSlots(roomId, date, durationMinutes));
        }

        // Filter out slots where participants are busy
        return candidates.stream()
            .filter(slot -> {
                for (String email : participantEmails) {
                    if (!findParticipantConflicts(email, slot).isEmpty()) {
                        return false;
                    }
                }
                return true;
            })
            .collect(Collectors.toList());
    }
}

// ============================================================
// ROOM RECOMMENDER
// ============================================================

class RoomRecommender {
    private final List<Room> rooms;

    public RoomRecommender(List<Room> rooms) {
        this.rooms = rooms;
    }

    public List<Room> recommendRooms(int attendeeCount, List<RoomFeature> requiredFeatures) {
        return rooms.stream()
            .map(r -> Map.entry(r, r.scoreForMeeting(attendeeCount, requiredFeatures)))
            .filter(e -> e.getValue() >= 0)
            .sorted(Map.Entry.<Room, Integer>comparingByValue().reversed())
            .map(Map.Entry::getKey)
            .collect(Collectors.toList());
    }

    public Optional<Room> findBestRoom(int attendeeCount, List<RoomFeature> requiredFeatures) {
        return recommendRooms(attendeeCount, requiredFeatures).stream().findFirst();
    }
}

// ============================================================
// NOTIFICATION SERVICE (Observer Pattern)
// ============================================================

interface MeetingObserver {
    void onMeetingCreated(Meeting meeting);
    void onMeetingCancelled(Meeting meeting, String reason);
    void onMeetingRescheduled(Meeting meeting, TimeSlot oldSlot, TimeSlot newSlot);
    void onResponseReceived(Meeting meeting, Participant participant, ParticipantStatus status);
    void onMeetingReminder(Meeting meeting);
    void onMeetingStarted(Meeting meeting);
    void onMeetingCompleted(Meeting meeting);
    void onSeriesInstanceCreated(Meeting meeting, String seriesId);
}

class CalendarInviteService implements MeetingObserver {
    @Override
    public void onMeetingCreated(Meeting meeting) {
        System.out.printf("📅 Calendar invite sent for '%s' to %d attendees%n",
            meeting.getTitle(), meeting.getAttendees().size());
        if (meeting.isRecurring()) {
            System.out.printf("  ↪ Recurring series: %s%n", meeting.getSeriesId());
        }
    }

    @Override
    public void onMeetingCancelled(Meeting meeting, String reason) {
        System.out.printf("📅 Calendar cancellation for '%s': %s%n",
            meeting.getTitle(), reason != null ? reason : "No reason");
    }

    @Override
    public void onMeetingRescheduled(Meeting meeting, TimeSlot oldSlot, TimeSlot newSlot) {
        System.out.printf("📅 Calendar update for '%s' - %s → %s%n",
            meeting.getTitle(), oldSlot.start(), newSlot.start());
    }

    @Override
    public void onResponseReceived(Meeting meeting, Participant participant, ParticipantStatus status) {
        System.out.printf("📧 %s %s for '%s'%n", participant.name(), status, meeting.getTitle());
    }

    @Override
    public void onMeetingReminder(Meeting meeting) {
        System.out.printf("⏰ Reminder: '%s' starts in 15 min in %s%n",
            meeting.getTitle(), meeting.getRoom().name());
    }

    @Override
    public void onMeetingStarted(Meeting meeting) {
        System.out.printf("▶️ Meeting '%s' has started with %d participants%n",
            meeting.getTitle(), meeting.hasAcceptedCount());
    }

    @Override
    public void onMeetingCompleted(Meeting meeting) {
        System.out.printf("✅ Meeting '%s' completed. Duration: %d min%n",
            meeting.getTitle(), meeting.getSlot().durationMinutes());
    }

    @Override
    public void onSeriesInstanceCreated(Meeting meeting, String seriesId) {
        System.out.printf("🔄 Recurring instance created: '%s' (%s)%n",
            meeting.getTitle(), meeting.getSlot().start().toLocalDate());
    }
}

// ============================================================
// MEETING ANALYTICS
// ============================================================

class MeetingAnalytics {
    private final Map<String, Integer> meetingsByRoom = new ConcurrentHashMap<>();
    private final Map<String, Integer> meetingsByOrganizer = new ConcurrentHashMap<>();
    private final Map<DayOfWeek, Integer> meetingsByDay = new ConcurrentHashMap<>();
    private final AtomicLong totalMeetings = new AtomicLong(0);
    private final AtomicLong totalDuration = new AtomicLong(0);
    private final AtomicLong cancelledMeetings = new AtomicLong(0);

    public void recordMeeting(Meeting meeting) {
        totalMeetings.incrementAndGet();
        totalDuration.addAndGet(meeting.getSlot().durationMinutes());
        meetingsByRoom.merge(meeting.getRoom().name(), 1, Integer::sum);
        meetingsByOrganizer.merge(meeting.getOrganizer().email(), 1, Integer::sum);
        meetingsByDay.merge(meeting.getSlot().start().getDayOfWeek(), 1, Integer::sum);
    }

    public void recordCancellation() { cancelledMeetings.incrementAndGet(); }

    public void printReport() {
        System.out.println("\n" + "=".repeat(55));
        System.out.println("           MEETING ANALYTICS");
        System.out.println("=".repeat(55));
        System.out.printf("Total meetings:     %d%n", totalMeetings.get());
        System.out.printf("Total duration:     %d hours%n", totalDuration.get() / 60);
        System.out.printf("Cancelled:          %d (%.1f%%)%n",
            cancelledMeetings.get(),
            totalMeetings.get() > 0 ? (double) cancelledMeetings.get() / totalMeetings.get() * 100 : 0);

        System.out.println("\n📊 By Day of Week:");
        for (DayOfWeek day : DayOfWeek.values()) {
            if (day != DayOfWeek.SATURDAY && day != DayOfWeek.SUNDAY) {
                int count = meetingsByDay.getOrDefault(day, 0);
                System.out.printf("  %-10s: %d%n", day, count);
            }
        }

        System.out.println("\n🏠 Top Rooms:");
        meetingsByRoom.entrySet().stream()
            .sorted(Map.Entry.<String, Integer>comparingByValue().reversed())
            .limit(5)
            .forEach(e -> System.out.printf("  %-20s: %d meetings%n", e.getKey(), e.getValue()));

        System.out.println("=".repeat(55));
    }
}

// ============================================================
// MEETING SCHEDULER (Facade)
// ============================================================

class MeetingScheduler {
    private final ConflictDetector conflictDetector;
    private final RoomBookingPolicy bookingPolicy;
    private final RoomRecommender roomRecommender;
    private final List<MeetingObserver> observers;
    private final Map<String, Meeting> meetings;
    private final Map<String, List<Meeting>> participantMeetings;
    private final Map<String, MeetingSeries> meetingSeries;
    private final ScheduledExecutorService scheduler;
    private final MeetingAnalytics analytics;
    private int meetingCounter;

    public MeetingScheduler(RoomBookingPolicy policy, List<Room> rooms) {
        this.conflictDetector = new ConflictDetector();
        this.bookingPolicy = policy;
        this.roomRecommender = new RoomRecommender(rooms);
        this.observers = new CopyOnWriteArrayList<>();
        this.meetings = new ConcurrentHashMap<>();
        this.participantMeetings = new ConcurrentHashMap<>();
        this.meetingSeries = new ConcurrentHashMap<>();
        this.scheduler = Executors.newSingleThreadScheduledExecutor();
        this.analytics = new MeetingAnalytics();
        this.meetingCounter = 0;

        // Add default observer
        addObserver(new CalendarInviteService());

        // Schedule reminders
        scheduler.scheduleAtFixedRate(this::sendReminders, 1, 5, TimeUnit.MINUTES);
    }

    public void addObserver(MeetingObserver observer) { observers.add(observer); }
    public MeetingAnalytics getAnalytics() { return analytics; }

    // --- Room Recommendations ---

    public List<Room> recommendRooms(int attendeeCount, List<RoomFeature> requiredFeatures) {
        return roomRecommender.recommendRooms(attendeeCount, requiredFeatures);
    }

    // --- Slot Discovery ---

    public List<TimeSlot> findAvailableSlots(Room room, LocalDate date, int durationMinutes) {
        return conflictDetector.findAvailableSlots(room.id(), date, durationMinutes);
    }

    public List<TimeSlot> findMutualSlots(List<Room> rooms, List<Participant> participants,
                                           LocalDate date, int durationMinutes) {
        return conflictDetector.findMutualAvailableSlots(
            rooms.stream().map(Room::id).collect(Collectors.toList()),
            participants.stream().map(Participant::email).collect(Collectors.toList()),
            date, durationMinutes);
    }

    // --- Meeting Scheduling ---

    public synchronized Meeting scheduleMeeting(String title, String description,
                                                  TimeSlot slot, Participant organizer,
                                                  List<Participant> attendees, Room room,
                                                  RecurrencePattern recurrence) {
        // Validate booking policy
        if (!bookingPolicy.canBook(room, slot, attendees.size(), List.of())) {
            throw new IllegalArgumentException("Room " + room.name()
                + " cannot accommodate this meeting: " + bookingPolicy.rejectionReason());
        }

        // Check room conflicts
        Optional<TimeSlot> conflict = conflictDetector.findConflict(room.id(), slot);
        if (conflict.isPresent()) {
            throw new IllegalStateException("Room " + room.name()
                + " is already booked for " + conflict.get());
        }

        // Check participant conflicts
        List<String> allEmails = new ArrayList<>();
        allEmails.add(organizer.email());
        allEmails.addAll(attendees.stream().map(Participant::email).collect(Collectors.toList()));

        Map<String, List<TimeSlot>> allConflicts = conflictDetector.findAllParticipantConflicts(allEmails, slot);
        if (!allConflicts.isEmpty()) {
            String firstConflict = allConflicts.entrySet().iterator().next().getKey();
            throw new IllegalStateException(firstConflict + " has a scheduling conflict");
        }

        // Create meeting
        meetingCounter++;
        String meetingId = "MTG-" + String.format("%05d", meetingCounter);
        Meeting meeting = new Meeting(meetingId, title, description, slot,
            organizer, attendees, room, recurrence, null);

        registerMeeting(meeting);
        return meeting;
    }

    public synchronized Meeting scheduleRecurringInstance(MeetingSeries series, LocalDate date) {
        List<MeetingInstance> instances = series.expand(date, date);
        if (instances.isEmpty()) {
            throw new IllegalArgumentException("No instance to schedule on " + date);
        }

        MeetingInstance instance = instances.get(0);
        meetingCounter++;
        String meetingId = "MTG-" + String.format("%05d", meetingCounter);

        Meeting meeting = new Meeting(meetingId, instance.title(), instance.description(),
            instance.slot(), instance.organizer(), instance.attendees(),
            instance.room(), series.getPattern(), series.getSeriesId());

        registerMeeting(meeting);
        notifySeriesInstance(meeting, series.getSeriesId());
        return meeting;
    }

    public synchronized MeetingSeries createMeetingSeries(String seriesId, String title,
                                                           String description, TimeSlot templateSlot,
                                                           RecurrencePattern pattern,
                                                           List<Participant> attendees,
                                                           Participant organizer, Room preferredRoom,
                                                           LocalDate seriesStart, LocalDate seriesEnd) {
        MeetingSeries series = new MeetingSeries(seriesId, title, description,
            templateSlot, pattern, attendees, organizer,
            preferredRoom, seriesStart, seriesEnd);

        meetingSeries.put(seriesId, series);

        // Expand and schedule first batch of instances
        LocalDate expandUntil = seriesStart.plusWeeks(4); // Schedule 4 weeks ahead
        for (MeetingInstance instance : series.expand(seriesStart, expandUntil)) {
            try {
                boolean roomAvailable = conflictDetector.findConflict(
                    preferredRoom.id(), instance.slot()).isEmpty();
                if (roomAvailable) {
                    scheduleRecurringInstance(series, instance.date());
                }
            } catch (IllegalStateException e) {
                System.out.printf("  ⚠️ Skipping %s: %s%n", instance.date(), e.getMessage());
            }
        }

        return series;
    }

    private void registerMeeting(Meeting meeting) {
        meetings.put(meeting.getId(), meeting);
        conflictDetector.addEntry(meeting.getRoom().id(), meeting.getSlot());
        conflictDetector.addParticipantEntry(meeting.getOrganizer().email(), meeting.getSlot());
        meeting.getAttendees().forEach(a ->
            conflictDetector.addParticipantEntry(a.email(), meeting.getSlot()));

        // Register in participant calendars
        participantMeetings.computeIfAbsent(meeting.getOrganizer().email(),
            k -> new CopyOnWriteArrayList<>()).add(meeting);
        meeting.getAttendees().forEach(a ->
            participantMeetings.computeIfAbsent(a.email(),
                k -> new CopyOnWriteArrayList<>()).add(meeting));

        analytics.recordMeeting(meeting);
        notifyCreated(meeting);
    }

    // --- Meeting Lifecycle ---

    public synchronized void cancelMeeting(String meetingId, String reason) {
        Meeting meeting = meetings.get(meetingId);
        if (meeting == null) throw new IllegalArgumentException("Meeting not found: " + meetingId);

        meeting.cancel(reason);
        conflictDetector.removeEntry(meeting.getRoom().id(), meeting.getSlot());
        meeting.getAttendees().forEach(a ->
            conflictDetector.removeParticipantEntry(a.email(), meeting.getSlot()));

        analytics.recordCancellation();
        notifyCancelled(meeting, reason);
    }

    public synchronized void cancelSeriesInstance(String seriesId, LocalDate date) {
        MeetingSeries series = meetingSeries.get(seriesId);
        if (series == null) throw new IllegalArgumentException("Series not found: " + seriesId);

        series.cancelInstance(date);
        System.out.printf("🗑️ Cancelled instance of '%s' on %s%n", seriesId, date);
    }

    public synchronized void respondToMeeting(String meetingId, Participant participant,
                                                ParticipantStatus status) {
        Meeting meeting = meetings.get(meetingId);
        if (meeting == null) throw new IllegalArgumentException("Meeting not found: " + meetingId);

        meeting.respond(participant.email(), status);
        notifyResponse(meeting, participant, status);
    }

    public synchronized void startMeeting(String meetingId) {
        Meeting meeting = meetings.get(meetingId);
        if (meeting == null) throw new IllegalArgumentException("Meeting not found: " + meetingId);
        meeting.start();
        notifyStarted(meeting);
    }

    public synchronized void completeMeeting(String meetingId) {
        Meeting meeting = meetings.get(meetingId);
        if (meeting == null) throw new IllegalArgumentException("Meeting not found: " + meetingId);
        meeting.complete();
        notifyCompleted(meeting);
    }

    // --- Queries ---

    public List<Meeting> getMeetingsForUser(String email, LocalDate date) {
        return participantMeetings.getOrDefault(email, List.of()).stream()
            .filter(m -> m.getSlot().start().toLocalDate().equals(date))
            .filter(m -> m.getStatus() != MeetingStatus.CANCELLED)
            .sorted(Comparator.comparing(m -> m.getSlot().start()))
            .collect(Collectors.toList());
    }

    public List<Meeting> getUpcomingMeetings(String email, int limit) {
        LocalDateTime now = LocalDateTime.now();
        return participantMeetings.getOrDefault(email, List.of()).stream()
            .filter(m -> m.getSlot().start().isAfter(now))
            .filter(m -> m.getStatus() != MeetingStatus.CANCELLED)
            .sorted(Comparator.comparing(m -> m.getSlot().start()))
            .limit(limit)
            .collect(Collectors.toList());
    }

    public DailyAgenda getDailyAgenda(String email, LocalDate date) {
        List<Meeting> meetings = getMeetingsForUser(email, date);
        return new DailyAgenda(email, date, meetings);
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
    private void notifyCancelled(Meeting m, String reason) {
        observers.forEach(o -> o.onMeetingCancelled(m, reason));
    }
    private void notifyRescheduled(Meeting m, TimeSlot old, TimeSlot now) {
        observers.forEach(o -> o.onMeetingRescheduled(m, old, now));
    }
    private void notifyResponse(Meeting m, Participant p, ParticipantStatus s) {
        observers.forEach(o -> o.onResponseReceived(m, p, s));
    }
    private void notifyReminder(Meeting m) { observers.forEach(o -> o.onMeetingReminder(m)); }
    private void notifyStarted(Meeting m) { observers.forEach(o -> o.onMeetingStarted(m)); }
    private void notifyCompleted(Meeting m) { observers.forEach(o -> o.onMeetingCompleted(m)); }
    private void notifySeriesInstance(Meeting m, String seriesId) {
        observers.forEach(o -> o.onSeriesInstanceCreated(m, seriesId));
    }

    public void shutdown() { scheduler.shutdown(); }
}

// ============================================================
// DAILY AGENDA
// ============================================================

record DailyAgenda(String email, LocalDate date, List<Meeting> meetings) {
    public void print() {
        System.out.println("\n" + "=".repeat(55));
        System.out.printf("  📋 AGENDA for %s on %s%n", email, date);
        System.out.println("=".repeat(55));

        if (meetings.isEmpty()) {
            System.out.println("  🎉 No meetings scheduled — Enjoy your day!");
            System.out.println("=".repeat(55));
            return;
        }

        for (int i = 0; i < meetings.size(); i++) {
            Meeting m = meetings.get(i);
            System.out.printf("  %d. %s - %s | %s | %s%n",
                i + 1,
                m.getSlot().start().toLocalTime(),
                m.getSlot().end().toLocalTime(),
                m.getTitle(),
                m.getRoom().name());
            System.out.printf("     ▸ %d attendees | %s%n",
                m.getAttendees().size(),
                m.getStatus());
            if (m.isRecurring()) {
                System.out.printf("     ↪ Recurring: %s%n", m.getRecurrence());
            }
        }

        System.out.printf("  📊 Total: %d meetings, %d minutes%n",
            meetings.size(),
            meetings.stream().mapToLong(m -> m.getSlot().durationMinutes()).sum());
        System.out.println("=".repeat(55));
    }
}

// ============================================================
// DEMO
// ============================================================

public class MeetingSchedulerSystem {
    public static void main(String[] args) {
        System.out.println("╔══════════════════════════════════╗");
        System.out.println("║    MEETING SCHEDULER DEMO       ║");
        System.out.println("╚══════════════════════════════════╝\n");

        System.out.println("🏢 Enterprise: Acme Corp — 3 buildings, 8 rooms\n");

        // Setup rooms with features
        List<Room> rooms = Arrays.asList(
            new Room("R001", "Conference A", 10,
                List.of("PROJECTOR", "WHITEBOARD", "VIDEO_CONF")),
            new Room("R002", "Meeting Room B", 6,
                List.of("WHITEBOARD")),
            new Room("R003", "Board Room", 20,
                List.of("PROJECTOR", "VIDEO_CONF", "CATERING", "SOUND_SYSTEM")),
            new Room("R004", "Phone Booth", 2,
                List.of("PHONE")),
            new Room("R005", "Innovation Lab", 15,
                List.of("PROJECTOR", "WHITEBOARD", "VIDEO_CONF", "STANDING_DESK", "LARGE_SCREEN")),
            new Room("R006", "Training Room", 30,
                List.of("PROJECTOR", "SOUND_SYSTEM", "STAGE")),
            new Room("R007", "Quiet Room", 4,
                List.of("WHITEBOARD")),
            new Room("R008", "Executive Suite", 8,
                List.of("PROJECTOR", "VIDEO_CONF", "CATERING"))
        );

        // Setup participants with departments
        Participant alice = new Participant("P001", "Alice", "alice@acme.com",
            "Engineering", "America/New_York", false);
        Participant bob = new Participant("P002", "Bob", "bob@acme.com",
            "Engineering", "America/New_York", false);
        Participant charlie = new Participant("P003", "Charlie", "charlie@acme.com",
            "Design", "America/Chicago", false);
        Participant diana = new Participant("P004", "Diana", "diana@acme.com",
            "Product", "America/New_York", false);
        Participant eve = new Participant("P005", "Eve", "eve@acme.com",
            "Engineering", "America/New_York", true);

        // Create scheduler with compositing policy
        RoomBookingPolicy policy = new CompositingBookingPolicy(
            new StandardBookingPolicy(),
            new ExecutiveBookingPolicy()
        );
        MeetingScheduler scheduler = new MeetingScheduler(policy, rooms);
        LocalDate tomorrow = LocalDate.now().plusDays(1);

        // ---- ROOM RECOMMENDATION ----
        System.out.println("--- ROOM RECOMMENDATION ---");
        System.out.println("Finding best room for 8 people with video conf + projector:");
        var recommended = scheduler.recommendRooms(8, List.of(RoomFeature.VIDEO_CONF, RoomFeature.PROJECTOR));
        recommended.forEach(r -> System.out.println("  ✅ " + r.name() + " (capacity: " + r.capacity() + ")"));

        // ---- SLOT DISCOVERY ----
        System.out.println("\n--- AVAILABLE SLOTS ---");
        var slots = scheduler.findAvailableSlots(rooms.get(0), tomorrow, 60);
        System.out.println("Available 1-hour slots in Conference A:");
        slots.stream().limit(5).forEach(s ->
            System.out.println("  " + s.start().toLocalTime() + " - " + s.end().toLocalTime()));

        // ---- SCHEDULE MEETINGS ----
        System.out.println("\n--- SCHEDULING MEETINGS ---");
        TimeSlot slot1 = slots.get(0);
        Meeting m1 = scheduler.scheduleMeeting(
            "Sprint Planning", "Plan next sprint goals and tasks",
            slot1, alice, List.of(bob, charlie, diana), rooms.get(0),
            RecurrencePattern.WEEKLY);
        System.out.println("Scheduled: " + m1.toDetailedString());

        // Try to schedule conflicting meeting
        try {
            scheduler.scheduleMeeting(
                "Conflict Test", "Should fail",
                slot1, bob, List.of(charlie), rooms.get(0),
                RecurrencePattern.NONE);
        } catch (IllegalStateException e) {
            System.out.println("✅ Conflict detection: " + e.getMessage());
        }

        // ---- RECURRING MEETINGS ----
        System.out.println("\n--- RECURRING MEETINGS ---");
        MeetingSeries standupSeries = scheduler.createMeetingSeries(
            "SERIES-001", "Daily Standup", "Daily engineering standup",
            new TimeSlot(tomorrow.atTime(9, 30), tomorrow.atTime(9, 45)),
            RecurrencePattern.DAILY,
            List.of(bob, charlie, diana, eve),
            alice, rooms.get(1),
            tomorrow, tomorrow.plusWeeks(4));
        System.out.println("Created daily standup series: SERIES-001");

        // Cancel one instance
        scheduler.cancelSeriesInstance("SERIES-001", tomorrow.plusDays(2));
        System.out.println("Cancelled Friday's standup");

        // ---- RESPONSES ----
        System.out.println("\n--- PARTICIPANT RESPONSES ---");
        scheduler.respondToMeeting(m1.getId(), bob, ParticipantStatus.ACCEPTED);
        scheduler.respondToMeeting(m1.getId(), charlie, ParticipantStatus.TENTATIVE);
        scheduler.respondToMeeting(m1.getId(), diana, ParticipantStatus.ACCEPTED);

        // ---- DAILY AGENDA ----
        System.out.println("\n--- DAILY AGENDA ---");
        DailyAgenda agenda = scheduler.getDailyAgenda(alice.email(), tomorrow);
        agenda.print();

        // ---- UPCOMING MEETINGS ----
        System.out.println("\n--- UPCOMING MEETINGS ---");
        var upcoming = scheduler.getUpcomingMeetings(alice.email(), 5);
        System.out.println("Upcoming meetings for Alice:");
        upcoming.forEach(m -> System.out.println("  📅 " + m.getSlot().start() + " - " + m.getTitle()));

        // ---- MEETING LIFECYCLE ----
        System.out.println("\n--- MEETING LIFECYCLE ---");
        scheduler.startMeeting(m1.getId());
        scheduler.completeMeeting(m1.getId());

        // ---- CANCELLATION ----
        System.out.println("\n--- BOOKING A SECOND MEETING & CANCELLING ---");
        TimeSlot slot2 = slots.get(2);
        Meeting m2 = scheduler.scheduleMeeting(
            "Product Review", "Review Q4 product roadmap",
            slot2, diana, List.of(alice, bob), rooms.get(4),
            RecurrencePattern.NONE);
        System.out.println("Scheduled: " + m2);

        scheduler.cancelMeeting(m2.getId(), "Postponed to next quarter");
        System.out.println("Cancelled: " + m2.getTitle());

        // ---- ANALYTICS ----
        scheduler.getAnalytics().printReport();

        // ---- MUTUAL AVAILABILITY ----
        System.out.println("\n--- MUTUAL AVAILABILITY ---");
        var mutualSlots = scheduler.findMutualSlots(
            List.of(rooms.get(0), rooms.get(4), rooms.get(7)),
            List.of(alice, bob, charlie, diana),
            tomorrow.plusDays(2), 30);
        System.out.println("Mutually available 30-min slots:");
        mutualSlots.stream().limit(3).forEach(s ->
            System.out.println("  ✅ " + s.start().toLocalTime() + " - " + s.end().toLocalTime()));

        scheduler.shutdown();
        System.out.println("\n╔══════════════════════════════════╗");
        System.out.println("║       DEMO COMPLETE             ║");
        System.out.println("╚══════════════════════════════════╝");
    }
}
