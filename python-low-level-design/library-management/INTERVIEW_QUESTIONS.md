# Library Management System - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Search systems, fine calculation, reservation queues, inventory

---

## Question 1: Core Design
**Interviewer:** *"Design a library management system — books, members, borrowing, returns, and fines."*

### 🎯 Expected Answer

**Domain Model:**
```python
# Book = metadata, BookItem = physical copy
class Book:  # ISBN, Title, Author, TotalCopies, AvailableCopies
class BookItem:  # Barcode, Status (AVAILABLE/BORROWED/RESERVED/LOST)
class Member:  # ID, Type (STUDENT/FACULTY/PUBLIC), BorrowedBooks, TotalFine
```

**Why separate Book from BookItem?** Because the same book (1984 by Orwell) can have 3 physical copies. The catalog should show "1984: 3 copies" without listing each copy. **SRP** — `Book` tracks metadata, `BookItem` tracks physical state.

---

## Question 2: Fine Calculation
**Interviewer:** *"Design a flexible fine calculation system."*

### 🎯 Answer

**Strategy Pattern for fines:**
```python
class FineCalculator(ABC):
    @abstractmethod
    def calculate_fine(self, days_overdue, member_type): pass

class ProgressiveFine(FineCalculator):
    def calculate_fine(self, days_overdue, member_type):
        if member_type == MemberType.PREMIUM:
            return 0.0  # No fine for premium
        if days_overdue <= 7:
            return 1.0 * days_overdue
        elif days_overdue <= 30:
            return 7.0 + 2.0 * (days_overdue - 7)
        else:
            return 7.0 + 46.0 + 5.0 * (days_overdue - 30)
```

**Why progressive?** Flat fines ($1/day) incentivize returning after 7 days if you've lost the book. Progressive fines create urgency to return sooner.

---

## Question 3: Search & Catalog
**Interviewer:** *"Design the search system."*

### 🎯 Answer

**For a library catalog (not Google-scale):**
```python
class Catalog:
    def search_by_title(self, query):
        return [b for b in self._books.values() if query.lower() in b.title.lower()]
    
    def search_by_author(self, query):
        return [b for b in self._books.values() if query.lower() in b.author.lower()]
```

**Production: Use Elasticsearch.**
```json
PUT /books
{
  "mappings": {
    "properties": {
      "title": {"type": "text", "analyzer": "english"},
      "author": {"type": "text"},
      "category": {"type": "keyword"},
      "isbn": {"type": "keyword"}
    }
  }
}
```

**Fuzzy matching for misspellings:**
```http
GET /books/_search
{
  "query": {
    "fuzzy": {
      "title": {
        "value": "harrey potter",
        "fuzziness": "AUTO"
      }
    }
  }
}
```

---

## Question 4: Circulation & Queue Management

**Reservation queue for popular books:**
```python
class ReservationQueue:
    def __init__(self):
        self._queue: Dict[str, deque] = {}  # book_isbn -> deque of member_ids
    
    def reserve(self, book_isbn, member_id):
        self._queue.setdefault(book_isbn, deque()).append(member_id)
    
    def notify_next(self, book_isbn):
        if self._queue.get(book_isbn):
            next_member = self._queue[book_isbn].popleft()
            NotificationService.send(next_member, f"'{book.title}' is now available!")
            # Hold expires in 48 hours
            schedule_job(f"release_hold:{next_member}:{book_isbn}", delay=48h)
```

---

## Question 5: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | FineCalculator | Progressive, flat, or waived fines |
| **Observer** | Notifications | Due-date reminders, hold available |
| **Facade** | LendingService | Unified borrowing/return interface |
| **Iterator** | Catalog browsing | Paginate results without exposing internals |
| **Decorator** | Book wrapping | Add gift wrapping, priority processing |
