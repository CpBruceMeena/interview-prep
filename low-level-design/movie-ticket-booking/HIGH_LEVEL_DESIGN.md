# 🏗️ Movie Ticket Booking System — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Concurrency, flash sales, payment, seat allocation

---

## 1. SYSTEM OVERVIEW

**Purpose:** Online movie ticket platform handling bookings, seat selection, payments, and discovery (like BookMyShow).

**Scale:** 10M MAU, 100K concurrent during flash sales (Avengers release), 50K simultaneous bookings

**Users:** Moviegoers, Theatre admins, Platform operators

**Use Cases:** Browse movies/theatres, Select seats, Book tickets, Cancel/refund, Search by city/date/genre

**Constraints:** No double-booking, <2s booking response, 99.95% uptime, payment idempotency

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌────────────────────────────────────────────┐
│           CDN (CloudFront/Akamai)           │
│  - Movie listings, theatre pages (static)   │
└───────────────────┬────────────────────────┘
                    │
┌───────────────────▼────────────────────────┐
│           API Gateway / Load Balancer       │
│  - Rate limit: 5 req/s per user during rush │
│  - WAF: Block DDoS / SQL injection          │
└──────┬────────────────────────────────┬────┘
       │                                │
┌──────▼──────┐                 ┌───────▼──────┐
│  Search     │                 │  Booking       │
│  Service    │                 │  Service       │
│  (Read)     │                 │  (Write)       │
│  - Elastic  │                 │  - Mutex per   │
│    search   │                 │    show        │
│  - Redis    │                 │  - Queue for   │
│    cache    │                 │    flash sales │
└──────┬──────┘                 └───────┬───────┘
       │                                │
┌──────▼──────────┐           ┌─────────▼──────┐
│  Read Replicas  │           │  Primary        │
│  (PostgreSQL)   │           │  Database       │
└─────────────────┘           └─────────┬───────┘
                                        │
                                ┌───────▼───────┐
                                │  Payment       │
                                │  Service       │
                                │  (Stripe/      │
                                │   Razorpay)    │
                                └───────────────┘
```

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Booking Service (Go/Python)
- Seat selection with 10-minute hold
- Distributed lock per show
- Queue-based request processing for flash sales

**🔴 Interview Question:** *"How do you prevent double-booking during a flash sale?"*

**✅ Answer:** Multi-layered approach:
1. **Redis distributed lock:** `SET show:123:lock user_456 NX EX 10` — per-show mutex
2. **Database transaction with SELECT FOR UPDATE:** Within transaction, lock all requested rows
3. **Seat state machine:** AVAILABLE → HELD (10 min TTL) → BOOKED
4. **Queue layer:** During flash sales, requests enter SQS queue → processed sequentially by workers
5. **Client-side:** Immediate "seat held" confirmation with countdown timer

---

### Search Service (Elasticsearch + Redis)
- Movie/theatre/shows indexed in Elasticsearch
- Popular searches cached in Redis (TTL: 1 minute)
- Geo-filtering by city and proximity

**🔴 Interview Question:** *"How do you handle the thundering herd problem when a popular movie releases?"*

**✅ Answer:**
1. **CDN for static pages:** Movie listing pages cached at edge (10 min TTL)
2. **Stale cache while revalidate:** Serve stale cached results while async refetch happens in background
3. **Redis cache for seat availability:** `GET show:123:available_seats` — updates every 10 seconds, not on every booking
4. **Request coalescing:** If 100 requests arrive for same query simultaneously, only 1 hits the backend; others wait on the first result
5. **Rate limiting per user:** 5 requests/second max during flash sales

---

### Payment Service
- Idempotency key on every payment
- Gateway fallback chain: Stripe → Razorpay → manual

---

## 4. SCALABILITY FOR FLASH SALES

| Strategy | Implementation |
|----------|---------------|
| **Queue excess** | Requests beyond capacity go to SQS; user gets estimated wait time |
| **Rate limit per user** | 1 booking attempt per 5 seconds |
| **Separate read/write paths** | Movie listing reads from replicas/cache; bookings go to write master |
| **Auto-scaling** | Booking workers auto-scale based on queue depth |
| **A/B capacity testing** | Regular load testing to know breaking point |

---

## 5. COST (Monthly)

| Component | Cost |
|-----------|------|
| Compute (booking + search) | $4,000 |
| PostgreSQL (Primary + Replicas) | $2,500 |
| Elasticsearch cluster | $1,500 |
| Redis Cache | $800 |
| CDN + Bandwidth | $1,000 |
| **Total** | **$9,800** |
