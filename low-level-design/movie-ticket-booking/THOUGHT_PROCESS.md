# 🧠 Movie Ticket Booking LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![Class Diagram](movie-ticket-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

What movies, shows, seats? Booking process? Payment integration? Cancellation policy? Concurrency (two users booking same seat)?

## Phase 1: Identify the Nouns

> *"A cinema has multiple movies playing at different times. Users book seats for a show. Payment is collected and tickets are issued."*

| Noun | Decision | Why |
|------|----------|-----|
| Movie | Regular Class | Metadata (title, duration, genre) |
| Show | Regular Class | Movie + Screen + Time |
| Screen | Regular Class | Physical screen with seats layout |
| Seat | Regular Class | Row, number, type (standard, VIP, recliner) |
| Booking | Regular Class | Links user + show + seats + payment |
| User | Regular Class | Identity and booking history |
| Payment | Regular Class | Amount, method, status |
| BookingService | Facade | Main entry point |
| SeatStatus | Enum | AVAILABLE, BOOKED, BLOCKED |
| BookingStatus | Enum | PENDING, CONFIRMED, CANCELLED |

## Phase 2: Enums First

```python
class SeatStatus(Enum):   AVAILABLE, BOOKED, BLOCKED
class BookingStatus(Enum): PENDING, CONFIRMED, CANCELLED, REFUNDED
```

## Phase 3: dataclass vs `__init__`

- **`Movie`**: Regular — metadata with no state changes
- **`Show`**: Regular — links Movie + Screen + Time
- **`Seat`**: Regular — has status that changes (booked/available)
- **`Screen`**: Regular — contains seats
- **`Booking`**: Regular — lifecycle management
- **`Payment`**: Regular — status transitions

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Check seat availability | `Show` or `BookingService` | Show knows its screen's seats |
| Select seats | `BookingService.select_seats()` | Needs to lock seats temporarily |
| Calculate price | `BookingService` or pricing strategy | Could vary by seat type, show time |
| Create booking | `BookingService.create_booking()` | Orchestrates seat locking → payment → confirmation |
| Process payment | `PaymentService` | Separate concern |
| Release expired holds | Background job | Seats should be unlocked if payment times out |

## Phase 5: The Seat Locking Problem

**This is the hardest part of the design.** Two users might try to book the same seat simultaneously.

**Approach in code:** Use a `locked_until` timeout on seats:
```python
class Seat:
    def __init__(self):
        self._status = SeatStatus.AVAILABLE
        self._locked_until: Optional[datetime] = None
    
    def is_available(self) -> bool:
        if self._status == SeatStatus.BLOCKED:
            return False
        if self._locked_until and datetime.now() < self._locked_until:
            return False
        return True
    
    def lock(self, duration_minutes=10):
        self._locked_until = datetime.now() + timedelta(minutes=duration_minutes)
```

**Production:** Use `SELECT ... FOR UPDATE` or Redis locks.

## Phase 6: Show → Screen → Seats (Composition)

```python
Screen HAS-A List[Seat]
Show HAS-A Screen, HAS-A Movie
Booking HAS-A Show, HAS-A List[Seat], HAS-A User
```

## Phase 7: Booking Flow

```
1. User searches movies → selects movie + show
2. Show seats for selected show → Display seat map
3. User selects seats → Seats get locked (10-min hold)
4. User pays → Payment processed
5. Booking confirmed → Seats marked BOOKED
6. If payment fails → Seats unlocked (AVAILABLE)
```

## Phase 8: Quick Checklist

✅ **Concurrency:** Seat locking prevents double-booking
✅ **Composition:** Show → Screen → Seats is a clear hierarchy
✅ **SRP:** Movie, Show, Seat, Booking each own their data
✅ **Flow:** Lock → Pay → Confirm pattern prevents race conditions
✅ **Encapsulation:** Seat status is only changed through methods
