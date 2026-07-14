# 🏨 Hotel Booking System — Interview Questions

## Q1: How do you handle overbooking?

**Answer:**
- Allow configurable overbooking tolerance (e.g., 5% of capacity)
- Maintain VIP priority list: Platinum → Gold → Silver → Bronze
- If overbooked: bump lowest-priority reservation, offer compensation
- Real-time inventory sync with OTAs to minimize overbooking risk

## Q2: How would you implement a "waitlist" feature?

**Answer:**
- When all rooms are booked, add guest to waitlist queue
- When cancellation occurs, notify first waitlisted guest (time-limited hold)
- If they don't respond within 15 min, move to next in queue
- Priority in waitlist: loyalty tier first, then timestamp

## Q3: Design a "best available rate" guarantee system

**Answer:**
- Track competitor prices via periodic scraping
- If lower rate found: match or undercut by 5%
- Rate parity clause in OTA contracts
- Price matching for direct bookings only (to encourage direct channel)

## Q4: How do you handle group bookings (10+ rooms)?

**Answer:**
- Group booking = master booking with sub-bookings
- Different cancellation policy (24-72 hours vs 24 hours)
- Block allocation: hold N rooms for group until T-30 days
- Partial payment schedule: 25% at booking, 75% at T-7 days
