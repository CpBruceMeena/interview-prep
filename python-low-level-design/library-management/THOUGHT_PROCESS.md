# 🧠 Library Management LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![](library-management-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

How many books can a member borrow? What are the fine rules? How long is the loan period? Different member types? Search capabilities?

## Phase 1: Identify the Nouns

> *"A library has books with multiple copies. Members borrow and return books. Fines accrue for overdue returns."*

| Noun | Decision | Why |
|------|----------|-----|
| Book | Regular Class | Metadata (ISBN, title, author) + tracks available copies |
| BookItem | Regular Class | A physical copy of a book with barcode and status |
| Member | Regular Class | ID, name, type, borrowed books, fines |
| FineCalculator | ABC | Strategy for fine calculation |
| Catalog | Regular Class | Search/retrieval of books |
| LendingService | Facade | Borrow/return orchestration |
| BookStatus | Enum | AVAILABLE, BORROWED, LOST, etc. |
| MemberType | Enum | STUDENT, FACULTY, PUBLIC, PREMIUM |

**Key Insight:** `Book` vs `BookItem` is the distinction between *title* and *physical copy*. A library has 3 copies of "Clean Code" — that's 1 Book, 3 BookItems. This is a critical modeling decision.

## Phase 2: Enums First

```python
class BookStatus(Enum):    AVAILABLE, BORROWED, RESERVED, LOST, DAMAGED
class MemberType(Enum):    STUDENT, FACULTY, PUBLIC, PREMIUM
class FinePolicy(Enum):    DAILY, HOURLY, WEEKLY
```

## Phase 3: dataclass vs `__init__`

- **`Book`**: Regular — has `borrow_copy()`/`return_copy()` behavior
- **`BookItem`**: Regular — has state changes (borrow/return) and due date tracking
- **`Member`**: Regular — complex behavior (can_borrow, add_fine, borrow_book)
- **`FineCalculator`**: ABC — abstract strategy
- **`Catalog`**: Regular — search logic

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Track available copies | `Book` | Book knows its total copies |
| Track physical copy status | `BookItem` | Each copy has its own status |
| Check if member can borrow | `Member.can_borrow()` | Member knows limits + fines |
| Calculate fine | `FineCalculator.calculate_fine()` | SRP: fine logic is separate |
| Search books | `Catalog.search_by_*()` | Catalog owns search indexes |
| Borrow a book | `LendingService.borrow_book()` | Orchestrates: Member → Book → BookItem |

## Phase 5: The Borrow Flow

```
borrow_book(member_id, isbn):
  1. Check member exists & can borrow (Member.can_borrow)
  2. Check book exists & has available copies (Book.is_available)
  3. Find an available BookItem (Catalog.get_available_items)
  4. Mark BookItem as borrowed (BookItem.borrow)
  5. Add BookItem to Member's borrowed list (Member.borrow_book)
  6. Decrement Book's available copies (Book.borrow_copy)
```

Each step delegates to the class that owns that data.

## Phase 6: Strategy Pattern for Fines

```python
class FineCalculator(ABC):
    def calculate_fine(self, days_overdue, member_type) -> float

class StandardFine(FineCalculator):      # Simple daily rate
class ProgressiveFine(FineCalculator):   # Escalating: 1→2→5 per day
```

Different libraries can use different fine policies.

## Phase 7: Member Type Configuration

Each member type has different limits — stored as dictionaries, not if-else chains:

```python
max_books = {"STUDENT": 5, "FACULTY": 10, "PUBLIC": 3, "PREMIUM": 8}
max_loan_days = {MemberType.STUDENT: 14, MemberType.FACULTY: 30, ...}
```

## Phase 8: Quick Checklist

✅ **Book vs BookItem:** Clear separation between title and physical copy
✅ **SRP:** Catalog searches, LendingService orchestrates, FineCalculator computes
✅ **Strategy:** Fine policies are interchangeable
✅ **OCP:** New member type → add to dictionary, no conditionals changed
