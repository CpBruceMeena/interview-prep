# Library Management System - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Modelling (title vs copy), reservation queues, concurrency on scarce copies, fines

---

## Question 1: Core Design
**Interviewer:** *"Design a library management system — books, members, borrowing, returns, and fines."*

### 🎯 Expected Answer

```python
@dataclass(frozen=True)
class Book:      isbn, title, author, category, year          # a title
@dataclass
class BookItem:  barcode, isbn, rack, status: ItemStatus       # a physical copy
@dataclass
class Loan:      loan_id, barcode, member_id, borrowed_on, due_on, renewals, returned_on, fine
@dataclass
class Member:    member_id, name, member_type, active_loans, fine_due
```

**Why separate Book from BookItem?** The catalog shows one entry for "1984" with three copies; the desk scans one specific copy. Status, rack and loan history belong to the copy.

**Why no `available_copies` counter on Book?** It duplicates the item statuses and drifts the first time a copy is marked lost without touching the counter. Derive it.

**Why is Loan its own class?** Renewals, fines and borrowing history need somewhere to live after the book comes back.

---

## Question 2: Fine Calculation
**Interviewer:** *"Design a flexible fine calculation system."*

### 🎯 Answer

```python
class FineCalculator(ABC):
    @abstractmethod
    def calculate_fine(self, days_overdue: int, member_type: MemberType) -> Decimal: ...

class ProgressiveFine(FineCalculator):
    """1/day for days 1-7, 2/day for days 8-30, 5/day after; optional cap."""
```

- Strategy, injected into the service, so a branch can change policy without touching lending code.
- `Decimal`, not `float`.
- **Cap it** (often at replacement cost). Past some amount, a fine stops being an incentive to return the book and becomes a reason to never come back.
- Days overdue are calendar days computed from an injected clock, so tests can set "today".
- Fines are assessed on return, which is why the borrow check must also refuse anyone currently holding an overdue book.

---

## Question 3: Reservations
**Interviewer:** *"All copies of a popular book are out. How do reservations work?"*

### 🎯 Answer

- A FIFO waitlist per ISBN. Reserving is only allowed when no copy is on the shelf.
- On return, `_release` gives the copy an `ON_HOLD` status for the head of the queue, with an expiry (3 days here). Only that member can borrow it.
- Expiry is lazy: `_expire_holds(isbn)` runs before every decision that depends on availability. An expired hold is released again, so it passes to the next member or back to the shelf. Production adds a scheduled sweep so the next member is notified promptly, but the lazy check is what keeps correctness independent of the scheduler.
- Renewal is refused while anyone is waiting.

**Follow-up: "Why not just notify everyone in the queue?"** Then the fastest person wins and the queue is meaningless.

---

## Question 4: Concurrency
**Interviewer:** *"Two kiosks try to check out the last copy at the same moment."*

### 🎯 Answer

The race is check-then-act: both see `AVAILABLE`, both mark `ON_LOAN`. In process, one `RLock` around the whole borrow makes it atomic (the test starts 30 threads against 10 copies and checks exactly 10 distinct copies are issued).

In a database, make the state change itself the check:

```sql
UPDATE book_items SET status = 'ON_LOAN'
WHERE barcode = :b AND status = 'AVAILABLE';     -- 0 rows -> someone else won
```

Or pick a copy with `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1` so concurrent borrowers take different copies instead of queueing on the same row. Add a partial unique index `UNIQUE (barcode) WHERE returned_on IS NULL` on `loans` as the last line of defence against two open loans on one copy.

---

## Question 5: "Now add X" Extensions

| Interviewer adds | Answer |
|------------------|--------|
| **Renewals** | Allowed if not overdue, under `max_renewals`, and nobody is waiting. New due date from today. |
| **Lost book** | Close the loan, charge replacement cost, mark the copy `LOST`. If the book turns up, refund and move it back to `AVAILABLE` through `_release` so the queue is honoured. |
| **Multi-branch** | `branch_id` on `BookItem`; a hold chooses a copy at the member's pickup branch or triggers a transfer. Queue stays per ISBN (or per ISBN + branch, a product decision). |
| **Notifications** | Events from `_release` ("hold ready") and from a daily sweep ("due tomorrow", "overdue"). Publish after the state change commits. |
| **E-books with N licences** | Same model: a licence is a `BookItem` with no rack; loans auto-return at expiry. |
| **Search by misspelled title** | Out of the LLD; an inverted index with fuzzy matching (see the HLD). |

---

## Question 6: Search & Catalog
**Interviewer:** *"Design the search system."*

### 🎯 Answer

In the LLD, `Catalog.search(title=, author=, category=)` is a linear scan with substring matching; at 100K titles that is still milliseconds and fine for an interview. In production, use an inverted index (Elasticsearch/OpenSearch): `text` fields with an English analyser for title and author, `keyword` fields for ISBN and category (facets), and `fuzziness: AUTO` for typos. The index is a read model fed from the catalog database; availability is not indexed (it changes too often) but fetched from the lending service for the page of results shown.

---

## Question 7: Testing Strategy

- **Fine tiers** at the boundaries (0, 7, 8, 30, 31 days), the cap, and premium members.
- **Policy per type:** a student can borrow 5, a public member 3 (this is the test that would have caught the original lookup bug).
- **Blocking:** unpaid fine above threshold, overdue book held.
- **Reservations:** queue order, hold valid on its last day and gone the day after, hold passes to the next member, cancellation releases the copy.
- **Concurrency:** many threads against fewer copies; each copy issued exactly once.
- All time-dependent tests use `FakeClock`; nothing sleeps.

---

## Question 8: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | `FineCalculator` | Flat, progressive, capped, waived |
| **Facade** | `LibraryService` | One entry point that owns locking and the clock |
| **Table-driven policy** | `POLICIES` | Per-type limits without conditionals |
| **Observer** (extension) | Hold-ready / due-date notifications | Decouple lending from messaging |

---

## ⚠️ Common Mistakes

- Modelling only `Book` with a copy count, so you cannot say *which* copy is overdue or lost.
- Keeping a counter *and* per-copy statuses, which drift apart.
- Check-then-act on availability without a lock or conditional update.
- Notifying the whole waitlist when a copy returns, or putting the copy back on the shelf while people are waiting.
- Holds that never expire, so one absent member blocks a title forever.
- Calling `datetime.now()` inside domain logic, then hacking private fields in tests.
- Fines as floats; fines with no cap.
- Printing errors and returning `None` instead of raising typed exceptions.

---

## 🎚️ Senior vs Staff Signal

- **Senior:** Book/BookItem split, Loan as a record, a fine strategy, limits from a table, a working reservation queue, a lock around borrow, tests with a fake clock.
- **Staff:** argues for derived availability over counters; designs hold expiry so correctness does not depend on a scheduler; moves the concurrency guarantee into the database (conditional update, `SKIP LOCKED`, partial unique index); separates the search read model from the transactional store; raises product questions (fine caps, queue per branch, what "lost then found" does to the queue).
