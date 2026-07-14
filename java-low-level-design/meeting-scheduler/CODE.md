# Meeting Scheduler — Java Implementation

> Java implementation of a Meeting Scheduler following SOLID principles and design patterns.

## 📦 Core Implementation

### Key Abstractions

| Interface/Class | Responsibility | Pattern |
|----------------|---------------|---------|
| `RoomBookingPolicy` | Validates room suitability | Strategy |
| `MeetingObserver` | Reacts to meeting lifecycle | Observer |
| `ConflictDetector` | Detects scheduling conflicts | Interval Tree |
| `MeetingScheduler` | Unified scheduling API | Facade |

### Conflict Detection with Interval Search

```java
class ConflictDetector {
    // Per-room calendar: sorted by start time
    private final Map<String, NavigableSet<TimeSlot>> roomCalendar;

    public Optional<TimeSlot> findConflict(String roomId, TimeSlot slot) {
        NavigableSet<TimeSlot> slots = roomCalendar.get(roomId);
        if (slots == null) return Optional.empty();

        // O(log n) search using NavigableSet
        TimeSlot floor = slots.floor(slot);   // Previous booking
        if (floor != null && floor.overlaps(slot)) return Optional.of(floor);

        TimeSlot ceil = slots.ceiling(slot);  // Next booking
        if (ceil != null && ceil.overlaps(slot)) return Optional.of(ceil);

        return Optional.empty();
    }
}
```

### Available Slot Finder

```java
public List<TimeSlot> findAvailableSlots(String roomId, LocalDate date, int durationMinutes) {
    List<TimeSlot> available = new ArrayList<>();
    LocalDateTime cursor = date.atStartOfDay().plusHours(9);  // 9 AM start
    LocalDateTime endOfDay = date.atTime(18, 0);              // 6 PM end

    while (cursor.plusMinutes(durationMinutes).isBefore(endOfDay)) {
        TimeSlot candidate = new TimeSlot(cursor, cursor.plusMinutes(durationMinutes));
        boolean hasConflict = booked.stream().anyMatch(b -> b.overlaps(candidate));
        if (!hasConflict) {
            available.add(candidate);
        }
        cursor = cursor.plusMinutes(15);  // 15-min granularity
    }
    return available;
}
```

## ▶️ How to Run

```bash
cd java-low-level-design/meeting-scheduler
javac MeetingSchedulerSystem.java
java MeetingSchedulerSystem
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | RoomBookingPolicy | Standard vs Executive booking rules |
| **Observer** | MeetingObserver | Calendar invites, reminders, analytics |
| **Facade** | MeetingScheduler | Unified interface over calendar, rooms, notifications |
| **Command** | Meeting | Lifecycle management with state transitions |
