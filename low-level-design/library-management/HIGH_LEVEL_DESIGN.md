# 🏗️ Library Management System — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Search, inventory, reservations, fine calculation

---

## 1. SYSTEM OVERVIEW

**Purpose:** Digital library management system handling catalog, borrowing, returns, fines, and member management for a multi-branch library chain.

**Scale:** 500K members, 1M books (100K unique titles), 50 branches, 10K transactions/day

**Users:** Members (borrowers), Librarians (staff), Branch managers, System admins

**Use Cases:** Search catalog, Borrow books, Return books, Pay fines, Reserve books, Renew loans

**Constraints:** No double-issue, fine accuracy to the cent, reservation queue fairness, 99.9% uptime

---

## 2. HIGH-LEVEL ARCHITECTURE

```
Web App / Mobile App / Self-service Kiosk
      │
┌─────▼──────┐
│ API Gateway │── Auth (OAuth2 for members, LDAP for staff)
└─────┬──────┘
      │
┌─────▼──────┐  ┌─────▼──────┐  ┌─────▼──────┐
│ Catalog    │  │ Lending    │  │ Fine       │
│ Service    │  │ Service    │  │ Service    │
│ (Elastic)  │  │ (Python)   │  │ (Python)   │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      │               │               │
┌─────▼───────────────▼───────────────▼──────┐
│              PostgreSQL                      │
│  Books, Members, Loans, Fines              │
│  Optimistic locking for concurrent access   │
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│              Redis Cache                      │
│  - Book availability (invalidate on borrow)  │
│  - Member session tokens                     │
│  - Reservation queue (sorted set)            │
└─────────────────────────────────────────────┘
```

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Catalog Service (Elasticsearch)
- Full-text search (title, author, subject)
- Faceted search (category, year, publisher)
- Fuzzy matching for misspellings

**🔴 Interview Question:** *"How does your search handle misspellings like 'Harry Poter'?"*

**✅ Answer:** Elasticsearch's built-in fuzzy query:
```json
{
  "query": {
    "match": {
      "title": {
        "query": "harry poter",
        "fuzziness": "AUTO"
      }
    }
  }
}
```
`fuzziness: AUTO` dynamically sets Levenshtein distance based on term length (0 for <3 chars, 1 for 3-5 chars, 2 for >5 chars). Combined with n-gram tokenizer for prefix matching.

---

### Lending Service (Python)
- Borrow/return with loan period enforcement
- Reservation queue management
- Hold expiration (48 hours)

**🔴 Interview Question:** *"How do you handle the reservation queue for popular books?"*

**✅ Answer:**
```python
class ReservationQueue:
    def __init__(self, redis):
        self._redis = redis
    
    def reserve(self, member_id, book_isbn):
        # Add to sorted set: score = timestamp for FCFS ordering
        key = f"reservation_queue:{book_isbn}"
        self._redis.zadd(key, {member_id: time.time()})
    
    def next_available(self, book_isbn):
        key = f"reservation_queue:{book_isbn}"
        next_member = self._redis.zpopmin(key)  # Earliest first
        if next_member:
            member_id, _ = next_member[0]
            return member_id
        return None
    
    def expire_hold(self, member_id, book_isbn):
        """Auto-release hold after 48 hours"""
        key = f"hold:{book_isbn}:{member_id}"
        self._redis.setex(key, 48*3600, member_id)
```
Reservation queue is FCFS. When a copy is returned, the front of queue is notified. They have 48 hours to pick up before the hold expires.

---

### Fine Service (Python)
- Progressive fine calculation
- Payment tracking
- Fine waivers (admin override)

---

## 4. DATA MODEL

```sql
CREATE TABLE books (
    isbn TEXT PRIMARY KEY, title TEXT, author TEXT,
    publisher TEXT, year INT, category TEXT
);
CREATE TABLE book_items (
    barcode TEXT PRIMARY KEY, isbn TEXT REFERENCES books(isbn),
    branch_id UUID, status TEXT, rack_location TEXT
);
CREATE TABLE members (
    id UUID, name TEXT, email TEXT UNIQUE, phone TEXT,
    member_type TEXT, total_fine DECIMAL(8,2) DEFAULT 0
);
CREATE TABLE loans (
    id UUID, book_item_barcode TEXT, member_id UUID,
    loan_date DATE, due_date DATE, return_date DATE,
    fine_amount DECIMAL(8,2)
);
```

---

## 5. COST (Monthly)

| Component | Cost |
|-----------|------|
| Elasticsearch (3 nodes) | $1,500 |
| PostgreSQL (Primary + Replica) | $1,200 |
| API Services (3 pods) | $900 |
| Redis Cache | $300 |
| **Total** | **$3,900** |
