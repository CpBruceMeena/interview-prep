# Movie Ticket Booking System - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Concurrency, race conditions, dynamic pricing, scalability

---

## Question 1: Core Design
**Interviewer:** *"Design a ticket booking system like BookMyShow."*

### 🎯 Expected Answer

**Domain Model:**
```
Movie ──→ Show ──→ Screen ──→ Seat
  │               │
  └─── Genre      └─── Theatre ──→ City
```

**Key Design Decision: Seat Availability as a State Machine**
```python
class Seat:
    # States: AVAILABLE → BLOCKED → BOOKED
    #                     ↘        ↗ (on timeout/cancel)
    def __init__(self):
        self._status = SeatStatus.AVAILABLE
    
    def block(self):     # Reserve for 10 minutes
        if self._status != SeatStatus.AVAILABLE:
            raise SeatNotAvailableError()
        self._status = SeatStatus.BLOCKED
    
    def confirm(self):   # Payment successful
        if self._status != SeatStatus.BLOCKED:
            raise InvalidSeatStateError()
        self._status = SeatStatus.BOOKED
    
    def release(self):   # Timeout or cancellation
        self._status = SeatStatus.AVAILABLE
```

**Why an explicit BLOCKED state?** Without it, the race condition window between seat selection and payment confirmation is exposed. BLOCKED acts as a temporary lock with TTL — prevents double-booking during payment processing.

---

## Question 2: Concurrency & Double-Booking Prevention
**Interviewer:** *"How do you prevent two users from booking the same seat?"*

### 🎯 Multi-layered approach:

**Layer 1 — Application Lock:**
```python
booking_lock = threading.Lock()

def create_booking(show_id, seat_ids, user_id):
    with booking_lock:  # Per-show lock
        seats = [get_seat(s) for s in seat_ids]
        if any(s.status != AVAILABLE for s in seats):
            raise SeatNotAvailableError()
        for seat in seats:
            seat.block()  # OCCUPIED
```

**Layer 2 — Database (Pessimistic):**
```sql
BEGIN;
SELECT * FROM seats 
WHERE show_id = ? AND seat_id IN (?) AND status = 'AVAILABLE'
FOR UPDATE;  -- Row-level lock
UPDATE seats SET status = 'BLOCKED' WHERE seat_id IN (?);
COMMIT;
```

**Layer 3 — Redis (Distributed Lock):**
```python
lock_key = f"show:{show_id}:seat:{seat_id}"
acquired = redis.setnx(lock_key, user_id, ttl=600)  # 10 min hold
if not acquired:
    return "Seat held by another user"
```

**Hold timeout strategy:** Seats are auto-released if payment isn't confirmed within 10 minutes. Show users a countdown timer.

---

## Question 3: Dynamic Pricing
**Interviewer:** *"How would you implement surge pricing for popular shows?"*

### 🎯 Answer

**Strategy Pattern with composable strategies:**
```python
class PricingStrategy(ABC):
    @abstractmethod
    def calculate_price(self, base_price, show, category): pass

class PeakPricing(PricingStrategy):
    """1.5x surcharge for evening/weekend shows"""
    def calculate_price(self, base, show, category):
        if show.start_time.hour in (18, 19, 20, 21) or \
           show.start_time.weekday() >= 5:
            return base * 1.5
        return base

class DemandPricing(PricingStrategy):
    """Dynamic pricing based on remaining seats"""
    def calculate_price(self, base, show, category):
        fill_rate = 1 - (show.available_seats / show.total_seats)
        if fill_rate > 0.8: return base * 2.0
        if fill_rate > 0.5: return base * 1.25
        return base
```

**Real-world approach:** Airlines use continuous revenue management, not simple tiers. They optimize price = f(remaining_capacity, time_to_show, historical_demand, competitor_prices).

---

## Question 4: Search & Discovery

**Elasticsearch-like approach:**
```python
class SearchService:
    def search(self, query, city, date, genre=None):
        filters = [
            {"term": {"city": city}},
            {"range": {"show_date": {"gte": date, "lte": date}}},
        ]
        if genre:
            filters.append({"term": {"genre": genre}})
        
        results = self._es.search(
            index="shows",
            query={"bool": {"must": [
                {"match": {"title": query}},
                {"filter": filters}
            ]}}
        )
        return [hit["_source"] for hit in results["hits"]]
```

---

## Question 5: Cancellation & Refund

```python
CANCELLATION_POLICY = {
    "> 48 hours": 0.0,    # Full refund
    "24-48 hours": 0.25,  # 25% fee
    "6-24 hours": 0.50,   # 50% fee
    "2-6 hours": 0.75,    # 75% fee
    "< 2 hours": 1.0,     # No refund
}

def cancel_booking(booking_id):
    booking = get_booking(booking_id)
    hours_until = (booking.show.start_time - datetime.now()).total_seconds() / 3600
    
    fee_percent = next(v for k, v in CANCELLATION_POLICY.items() 
                       if hours_until > parse_time(k))
    refund_amount = booking.total_amount * (1 - fee_percent)
    
    booking.cancel()
    refund_to_payment_method(booking.payment_id, refund_amount)
    release_seats(booking.seats)
```

---

## Question 6: Scalability for Flash Sales

**Architecture for 100K+ concurrent users:**
```
          ┌──────────────┐
Users ──▶ │   API GW      │──▶ Rate Limiter (per user: 5 req/sec)
          │  (CDN cached) │──▶ Request Queue (SQS/Kafka)
          └──────────────┘          │
                              ┌─────▼──────┐
                              │  Booking    │
                              │  Workers    │──▶ DB (Read replicas for search)
                              │  (Auto-scaled)│──▶ DB (Primary for bookings)
                              └────────────┘
```

**Key strategies:**
- **Queue it**: Don't process bookings synchronously during flash sales. Return a "ticket pending" status.
- **Rate limit per user**: 1 booking request per 5 seconds
- **CDN**: Cache movie listings, showtimes — only booking flows hit origin
- **Separate read/write paths**: CQRS pattern — writes go to queue, reads from cache/replicas

---

## Question 7: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | PricingStrategy | Interchangeable pricing (peak, weekend, demand) |
| **Singleton** | BookingManager | Single source of seat allocation truth |
| **Observer** | Notifications | Email/SMS on booking confirmation |
| **Factory** | Seat/Show creation | Config-driven setup |
| **Facade** | MovieSearchService | Unified search interface |
| **Decorator** | Booking add-ons | Food combos, insurance wrapping |
| **State** | Seat/Booking status | Lifecycle management with timeouts |
