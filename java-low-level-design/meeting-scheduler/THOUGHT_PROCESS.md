# 🧠 Meeting Scheduler — Thought Process

## Problem Breakdown

### Step 1: Core Entities
- **Meeting:** Title, time slot, organizer, attendees, room, recurrence
- **Room:** Capacity, amenities, location
- **Participant:** Email, name, availability
- **TimeSlot:** Start/end with overlap detection

### Step 2: Conflict Detection
- Two meetings can't be in the same room at the same time
- Participants can't be in two meetings at the same time
- Need efficient interval overlap detection

### Step 3: Room Booking Policy
- Different rooms have different rules (capacity, amenities)
- Strategy pattern to make policies extensible

### Step 4: Notifications
- Calendar invites, reminders, changes
- Observer pattern for extensibility

### Step 5: Recurrence
- Daily, weekly, monthly patterns
- Exception handling for single-instance modifications

## Key Decisions

| Decision | Why |
|----------|-----|
| NavigableSet for calendar | O(log n) conflict detection |
| Observer for notifications | Easy to add email, SMS, push, calendar sync |
| 15-min granularity | Standard enterprise calendar, prevents fragmentation |
| Strategy for booking policy | Different rooms have different rules |
