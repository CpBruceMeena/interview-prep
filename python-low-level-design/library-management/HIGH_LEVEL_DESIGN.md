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
│  Conditional updates for copy status        │
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│              Redis Cache                      │
│  - Book availability (invalidate on borrow)  │
│  - Member session tokens                     │
│  - Search-page availability hints            │
└─────────────────────────────────────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/library-management-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Library Management Sequence — Search → Borrow → Return → Fine Calculation. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

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

**✅ Answer:** Keep the queue in Postgres, not Redis: it is low-volume, must survive restarts, and has to change in the same transaction as the copy's status.
```sql
-- join the queue (position = order of created_at, ties by id)
INSERT INTO reservations (isbn, member_id, created_at, status)
VALUES (:isbn, :member, now(), 'WAITING');

-- on return, inside the return transaction
WITH nxt AS (
  SELECT id, member_id FROM reservations
  WHERE isbn = :isbn AND status = 'WAITING'
  ORDER BY created_at, id LIMIT 1 FOR UPDATE      -- not SKIP LOCKED: that would break FIFO
)
UPDATE reservations r SET status = 'READY', barcode = :barcode,
       hold_expires_at = now() + interval '3 days'
FROM nxt WHERE r.id = nxt.id;
-- 1 row -> copy goes ON_HOLD for that member; 0 rows -> copy goes AVAILABLE
```
The queue is FCFS. When a copy comes back, only the head of the queue gets it; the copy stays `ON_HOLD` until they borrow it or the hold expires. Expiry is checked lazily (`hold_expires_at < now()` before any availability decision) and eagerly by a sweeper that re-runs the "next in queue" step and sends the notification. The lazy check means a late sweeper delays a notification but never hands a copy to the wrong person.

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
    id UUID PRIMARY KEY, name TEXT, email TEXT UNIQUE, phone TEXT,
    member_type TEXT, fine_due DECIMAL(8,2) NOT NULL DEFAULT 0
);
CREATE TABLE loans (
    id UUID PRIMARY KEY, book_item_barcode TEXT REFERENCES book_items(barcode),
    member_id UUID REFERENCES members(id),
    loan_date DATE, due_date DATE, renewals INT DEFAULT 0, return_date DATE,
    fine_amount DECIMAL(8,2)
);
-- at most one open loan per copy, enforced by the database
CREATE UNIQUE INDEX one_open_loan ON loans (book_item_barcode) WHERE return_date IS NULL;
CREATE TABLE reservations (
    id BIGSERIAL PRIMARY KEY, isbn TEXT, member_id UUID, created_at TIMESTAMPTZ,
    status TEXT,                       -- WAITING | READY | FULFILLED | EXPIRED | CANCELLED
    barcode TEXT, hold_expires_at TIMESTAMPTZ
);
CREATE INDEX ON reservations (isbn, status, created_at);
CREATE TABLE fine_payments (
    id UUID PRIMARY KEY, member_id UUID, amount DECIMAL(8,2),
    idempotency_key TEXT UNIQUE, created_at TIMESTAMPTZ
);
```

---

## 5. CONSISTENCY, CONCURRENCY & FAILURE MODES

| Concern | Choice |
|---------|--------|
| **Double issue of one copy** | `UPDATE book_items SET status='ON_LOAN' WHERE barcode=? AND status='AVAILABLE'` (0 rows = lost the race), plus the partial unique index on open loans. Choosing "any available copy" uses `FOR UPDATE SKIP LOCKED` so concurrent borrowers do not serialise on one row. |
| **Borrow is multi-row** | Copy status, loan insert and reservation update commit in one Postgres transaction. Lending data is small (see below), so one primary is enough; no distributed transaction needed. |
| **Availability cache in Redis** | Write-through after commit with a short TTL; it is only a hint for the search page. The borrow path always reads Postgres. |
| **Search index lag** | Catalog changes reach Elasticsearch via CDC/outbox in seconds. Availability is not indexed; the results page fetches it from the lending service. |
| **Kiosk offline / network retry** | Each checkout carries a client request id; a retried request returns the existing loan rather than failing or double-issuing. Fine payments carry an idempotency key. |
| **Sweeper or notifier down** | Holds expire lazily on the next read, so correctness does not depend on the job; only notification latency suffers. Notifications go through an outbox so a crash after commit cannot drop them. |
| **Clock skew across branches** | Due dates and hold expiry are computed by the database (`now()`), not by kiosks. |

**Capacity:** 10K transactions/day is about 0.1/s on average and maybe 5/s at opening time. 1M copies × ~200 bytes plus a few million loan rows per year is single-digit GB. This is a single Postgres primary with a replica; the interesting problems are correctness and search quality, not scale.

---

## 6. COST (Monthly)

| Component | Cost |
|-----------|------|
| Elasticsearch (3 nodes) | $1,500 |
| PostgreSQL (Primary + Replica) | $1,200 |
| API Services (3 pods) | $900 |
| Redis Cache | $300 |
| **Total** | **$3,900** |
