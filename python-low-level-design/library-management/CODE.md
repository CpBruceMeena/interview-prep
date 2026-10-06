# Library Management — Implementation

> Single-file Python implementation (stdlib only, 3.10+): catalog, loans, renewals, a FIFO reservation queue with expiring holds, Decimal fines, and a thread-safe service.

---

## ▶️ How to Run

```bash
cd python-low-level-design/library-management
python3 library_management.py                     # deterministic demo (fake clock)
python3 -m unittest test_library_management       # 17 tests, < 1 s
```

---

## 🗺️ Map of the Code

| Piece | Role | Why it is shaped this way |
|-------|------|---------------------------|
| `Book` (frozen) | A title, keyed by ISBN | Metadata only; no copy counter |
| `BookItem` | A physical copy, keyed by barcode | Its `ItemStatus` is the single source of truth for availability |
| `ItemStatus` | `AVAILABLE`, `ON_LOAN`, `ON_HOLD`, `LOST` | Only the states the code actually uses |
| `Loan` | One borrowing of one copy | Due date, renewals, return date and fine live here, so history is kept |
| `Hold` | A copy set aside for one member until `expires_on` | Created when a reserved title comes back |
| `Member` | Type, active loans, `fine_due` | Limits come from `POLICIES[member_type]` |
| `MembershipPolicy` / `POLICIES` | Max books, loan days, max renewals per type | A table, not if/else |
| `FineCalculator` → `StandardFine`, `ProgressiveFine` | Fine rules | Strategy; returns `Decimal` |
| `Catalog` | Books, items, `items_by_isbn` index, `search()` | Lookup by ISBN is O(copies), not O(all items) |
| `LibraryService` | Facade: borrow, return, renew, reserve, holds, fines | One `RLock`; clock injected |

---

## 🔑 Key Design Decisions

### 1. Availability is derived, not counted

The earlier version kept `Book._available_copies` *and* a status on each `BookItem`. Two sources of truth drift: marking a copy lost or damaged never touched the counter. Now availability is `count(items where status == AVAILABLE)`, computed from the per-ISBN index.

### 2. Loans are records

`borrow()` creates a `Loan`; `return_item()` closes it with `returned_on` and `fine`. Renewal updates `due_on` and bumps `renewals`. Because the loan outlives the return, you get borrowing history and an audit trail for disputed fines.

### 3. Reservations: FIFO queue + expiring holds

```
reserve(member, isbn)           only when no copy is on the shelf
return_item(barcode)            -> _release(item)
    waitlist non-empty?  item ON_HOLD for head of queue, expires today + HOLD_DAYS
    else                 item AVAILABLE
borrow(member, isbn)            held copy for this member first, else any AVAILABLE copy
_expire_holds(isbn)             lazy: runs before every availability decision;
                                an expired hold is re-released (next in queue or shelf)
```

A held copy is invisible to everyone except the member it is held for, so the queue cannot be skipped. Renewal is refused while anyone is waiting.

### 4. Borrowing rules

`_check_can_borrow` blocks when the member is at their type's limit, owes at least `fine_block_threshold` (default 10.00), or holds any overdue book. The last rule matters: fines are only assessed on return, so without it a member could keep a book forever and keep borrowing.

The original code looked limits up with `"STUDENT"` against an enum whose value is `"Student"`, so every member silently got the default limit of 3. The policy table is now keyed by the enum itself.

### 5. Time and money

- `clock: Callable[[], date]` is injected. Tests and the demo use `FakeClock` and `advance(days)` rather than editing a private `_due_date`.
- Overdue days are calendar days: `max(0, (today - due_on).days)`.
- Fines are `Decimal`. `ProgressiveFine` takes an optional cap (typically the replacement cost).

### 6. Thread-safety

Every public `LibraryService` method takes one `RLock`, so "find an available copy → mark it on loan" is atomic. `test_concurrent_borrow_never_double_issues` starts 30 threads behind a barrier against 10 copies and asserts exactly 10 distinct barcodes were issued. In a database the same guarantee comes from a conditional update (see the HLD).

---

## 🧩 Where to Extend

| Requirement | Change |
|-------------|--------|
| New fine rule (weekend grace, per-category rates) | New `FineCalculator`; pass it to `LibraryService` |
| New member type | Add a `MemberType` and a `POLICIES` row |
| Damaged copies / maintenance | Add an `ItemStatus`; `_first_available` already ignores everything that is not `AVAILABLE` |
| Notifications ("your hold is ready", "due tomorrow") | Emit an event from `_release` and from a daily due-date sweep, outside the lock |
| Multi-branch | `BookItem.branch_id`; holds pick a copy at the member's pickup branch, or create a transfer |
| Eager hold expiry | A scheduled job calling `_expire_holds` for ISBNs with holds; lazy expiry stays as the safety net |

---

## 📄 Full Source

<!-- source: library_management.py -->
```python
"""
Library Management System - Low Level Design
----------------------------------------------
Patterns: Strategy (fine rules), Facade (LibraryService), policy table per
member type instead of if/else.

Modelling decisions worth saying out loud:
  * Book (a title, keyed by ISBN) vs BookItem (a physical copy, keyed by
    barcode). Availability is derived from item statuses; there is no separate
    "available copies" counter to drift out of sync.
  * A Loan is its own record, so history, renewals and fines hang off it.
  * Reservations are a FIFO queue per ISBN. A returned copy goes ON_HOLD for
    the first member in the queue for HOLD_DAYS instead of back on the shelf.
  * Money (fines) is Decimal. Time comes from an injected clock, so overdue
    behaviour is testable without sleeping or poking private fields.
  * LibraryService holds one lock around every operation, so two members can
    never be issued the same copy.
"""

from __future__ import annotations

import itertools
import threading
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Callable, Deque, Dict, List, Optional

ZERO = Decimal("0.00")


class ItemStatus(Enum):
    AVAILABLE = "Available"
    ON_LOAN = "On loan"
    ON_HOLD = "On hold"        # set aside for the member at the head of the queue
    LOST = "Lost"


class MemberType(Enum):
    STUDENT = "Student"
    FACULTY = "Faculty"
    PUBLIC = "Public"
    PREMIUM = "Premium"


@dataclass(frozen=True)
class MembershipPolicy:
    max_books: int
    loan_days: int
    max_renewals: int = 2


POLICIES: Dict[MemberType, MembershipPolicy] = {
    MemberType.STUDENT: MembershipPolicy(max_books=5, loan_days=14),
    MemberType.FACULTY: MembershipPolicy(max_books=10, loan_days=30),
    MemberType.PUBLIC: MembershipPolicy(max_books=3, loan_days=7),
    MemberType.PREMIUM: MembershipPolicy(max_books=8, loan_days=21),
}


class LibraryError(Exception):
    pass


class NotFoundError(LibraryError):
    pass


class NotAvailableError(LibraryError):
    pass


class BorrowingBlockedError(LibraryError):
    """Limit reached, unpaid fines, or an overdue book."""


# --- Catalog entities ---

@dataclass(frozen=True)
class Book:
    isbn: str
    title: str
    author: str
    category: str
    year: int

    def __str__(self) -> str:
        return f"{self.title} by {self.author}"


@dataclass
class BookItem:
    barcode: str
    isbn: str
    rack: str
    status: ItemStatus = ItemStatus.AVAILABLE


@dataclass
class Loan:
    loan_id: str
    barcode: str
    isbn: str
    member_id: str
    borrowed_on: date
    due_on: date
    renewals: int = 0
    returned_on: Optional[date] = None
    fine: Decimal = ZERO

    def days_overdue(self, on: date) -> int:
        return max(0, (on - self.due_on).days)


@dataclass
class Hold:
    """A copy set aside for one member until expires_on (inclusive)."""
    member_id: str
    barcode: str
    expires_on: date


@dataclass
class Member:
    member_id: str
    name: str
    member_type: MemberType
    active_loans: Dict[str, Loan] = field(default_factory=dict)   # barcode -> loan
    fine_due: Decimal = ZERO

    @property
    def policy(self) -> MembershipPolicy:
        return POLICIES[self.member_type]

    def __str__(self) -> str:
        return f"{self.name} ({self.member_type.value})"


# --- Fine strategies ---

class FineCalculator(ABC):
    @abstractmethod
    def calculate_fine(self, days_overdue: int, member_type: MemberType) -> Decimal:
        ...


class StandardFine(FineCalculator):
    """Flat daily rate by member type."""

    _rates = {MemberType.STUDENT: Decimal("1.00"), MemberType.FACULTY: Decimal("0.50"),
              MemberType.PUBLIC: Decimal("2.00"), MemberType.PREMIUM: ZERO}

    def calculate_fine(self, days_overdue: int, member_type: MemberType) -> Decimal:
        return self._rates[member_type] * days_overdue


class ProgressiveFine(FineCalculator):
    """1/day for the first week, 2/day up to day 30, 5/day after. Optional cap
    (e.g. the replacement cost), because an uncapped fine stops being an
    incentive to return the book and becomes a reason never to come back."""

    def __init__(self, cap: Optional[Decimal] = None) -> None:
        self._cap = cap

    def calculate_fine(self, days_overdue: int, member_type: MemberType) -> Decimal:
        if member_type is MemberType.PREMIUM or days_overdue <= 0:
            return ZERO
        fine, prev = ZERO, 0
        for upto, rate in ((7, Decimal(1)), (30, Decimal(2)), (None, Decimal(5))):
            end = days_overdue if upto is None else min(days_overdue, upto)
            fine += rate * (end - prev)
            if upto is None or days_overdue <= upto:
                break
            prev = upto
        return min(fine, self._cap) if self._cap is not None else fine


# --- Catalog (search) ---

class Catalog:
    """Books and their copies. Substring search is fine at LLD scale; a real
    catalog uses an inverted index (see HIGH_LEVEL_DESIGN.md)."""

    def __init__(self) -> None:
        self._books: Dict[str, Book] = {}
        self._items: Dict[str, BookItem] = {}
        self._items_by_isbn: Dict[str, List[BookItem]] = {}

    def add_book(self, book: Book) -> None:
        self._books[book.isbn] = book
        self._items_by_isbn.setdefault(book.isbn, [])

    def add_item(self, item: BookItem) -> None:
        if item.isbn not in self._books:
            raise NotFoundError(f"unknown ISBN {item.isbn}")
        if item.barcode in self._items:
            raise LibraryError(f"duplicate barcode {item.barcode}")
        self._items[item.barcode] = item
        self._items_by_isbn[item.isbn].append(item)

    def book(self, isbn: str) -> Book:
        try:
            return self._books[isbn]
        except KeyError:
            raise NotFoundError(f"unknown ISBN {isbn}") from None

    def item(self, barcode: str) -> BookItem:
        try:
            return self._items[barcode]
        except KeyError:
            raise NotFoundError(f"unknown barcode {barcode}") from None

    def items_for(self, isbn: str) -> List[BookItem]:
        self.book(isbn)
        return list(self._items_by_isbn[isbn])

    def search(self, *, title: str = "", author: str = "", category: str = "") -> List[Book]:
        def match(field_value: str, query: str) -> bool:
            return query.lower() in field_value.lower()
        return [b for b in self._books.values()
                if match(b.title, title) and match(b.author, author) and match(b.category, category)]


# --- Facade ---

class LibraryService:
    HOLD_DAYS = 3

    def __init__(self, catalog: Catalog, fine_calculator: Optional[FineCalculator] = None,
                 clock: Callable[[], date] = date.today,
                 fine_block_threshold: Decimal = Decimal("10.00")) -> None:
        self._catalog = catalog
        self._fines = fine_calculator or StandardFine()
        self._clock = clock
        self._fine_block = fine_block_threshold
        self._lock = threading.RLock()
        self._ids = itertools.count(1)
        self._members: Dict[str, Member] = {}
        self._loans: Dict[str, Loan] = {}                      # loan_id -> loan (history)
        self._active: Dict[str, Loan] = {}                     # barcode -> open loan
        self._waitlist: Dict[str, Deque[str]] = {}            # isbn -> member ids, FIFO
        self._holds: Dict[str, Hold] = {}                      # barcode -> hold

    # members

    def register_member(self, name: str, member_type: MemberType = MemberType.PUBLIC) -> Member:
        with self._lock:
            member = Member(f"M{next(self._ids)}", name, member_type)
            self._members[member.member_id] = member
            return member

    def member(self, member_id: str) -> Member:
        with self._lock:
            return self._member(member_id)

    # availability

    def available_copies(self, isbn: str) -> int:
        with self._lock:
            self._expire_holds(isbn)
            return sum(i.status is ItemStatus.AVAILABLE for i in self._catalog.items_for(isbn))

    # borrow / return / renew

    def borrow(self, member_id: str, isbn: str) -> Loan:
        with self._lock:
            member = self._member(member_id)
            self._check_can_borrow(member)
            self._expire_holds(isbn)
            item = self._held_item_for(member_id, isbn) or self._first_available(isbn)
            if item is None:
                raise NotAvailableError(f"no copy of {isbn} available; reserve it instead")

            self._holds.pop(item.barcode, None)
            waiting = self._waitlist.get(isbn)
            if waiting and member_id in waiting:
                waiting.remove(member_id)
            today = self._clock()
            loan = Loan(f"L{next(self._ids)}", item.barcode, isbn, member_id, today,
                        today + timedelta(days=member.policy.loan_days))
            item.status = ItemStatus.ON_LOAN
            member.active_loans[item.barcode] = loan
            self._active[item.barcode] = loan
            self._loans[loan.loan_id] = loan
            return loan

    def return_item(self, barcode: str) -> Loan:
        """Check a copy back in (the desk scans the barcode, not the member card)."""
        with self._lock:
            item = self._catalog.item(barcode)
            loan = self._active_loan(barcode)
            member = self._members[loan.member_id]
            today = self._clock()

            loan.returned_on = today
            loan.fine = self._fines.calculate_fine(loan.days_overdue(today), member.member_type)
            member.fine_due += loan.fine
            del member.active_loans[barcode]
            del self._active[barcode]

            self._expire_holds(item.isbn)
            self._release(item)
            return loan

    def renew(self, barcode: str) -> Loan:
        with self._lock:
            loan = self._active_loan(barcode)
            member = self._members[loan.member_id]
            today = self._clock()
            if loan.days_overdue(today) > 0:
                raise BorrowingBlockedError("overdue loans must be returned, not renewed")
            if loan.renewals >= member.policy.max_renewals:
                raise BorrowingBlockedError("renewal limit reached")
            if self._waitlist.get(loan.isbn):
                raise BorrowingBlockedError("other members are waiting for this book")
            loan.renewals += 1
            loan.due_on = today + timedelta(days=member.policy.loan_days)
            return loan

    def report_lost(self, barcode: str, replacement_cost: Decimal) -> Loan:
        with self._lock:
            loan = self._active_loan(barcode)
            member = self._members[loan.member_id]
            loan.returned_on = self._clock()
            loan.fine = replacement_cost
            member.fine_due += replacement_cost
            del member.active_loans[barcode]
            del self._active[barcode]
            self._catalog.item(barcode).status = ItemStatus.LOST
            return loan

    # reservations

    def reserve(self, member_id: str, isbn: str) -> int:
        """Join the FIFO waitlist for a title. Returns the 1-based position."""
        with self._lock:
            member = self._member(member_id)
            self._expire_holds(isbn)
            if any(i.status is ItemStatus.AVAILABLE for i in self._catalog.items_for(isbn)):
                raise LibraryError("a copy is on the shelf; borrow it instead")
            queue = self._waitlist.setdefault(isbn, deque())
            if member_id in queue or self._held_item_for(member_id, isbn):
                raise LibraryError("already reserved")
            if any(loan.isbn == isbn for loan in member.active_loans.values()):
                raise LibraryError("member already has this book")
            queue.append(member_id)
            return len(queue)

    def cancel_reservation(self, member_id: str, isbn: str) -> None:
        with self._lock:
            queue = self._waitlist.get(isbn, deque())
            if member_id in queue:
                queue.remove(member_id)
                return
            item = self._held_item_for(member_id, isbn)
            if item is None:
                raise NotFoundError("no reservation to cancel")
            del self._holds[item.barcode]
            self._release(item)

    def hold_for(self, member_id: str, isbn: str) -> Optional[Hold]:
        with self._lock:
            self._expire_holds(isbn)
            item = self._held_item_for(member_id, isbn)
            return self._holds[item.barcode] if item else None

    # fines

    def pay_fine(self, member_id: str, amount: Decimal) -> Decimal:
        with self._lock:
            member = self._member(member_id)
            if amount <= 0 or amount > member.fine_due:
                raise LibraryError(f"payment must be between 0.01 and {member.fine_due}")
            member.fine_due -= amount
            return member.fine_due

    # helpers (lock held)

    def _member(self, member_id: str) -> Member:
        try:
            return self._members[member_id]
        except KeyError:
            raise NotFoundError(f"unknown member {member_id}") from None

    def _active_loan(self, barcode: str) -> Loan:
        self._catalog.item(barcode)
        loan = self._active.get(barcode)
        if loan is None:
            raise LibraryError(f"{barcode} is not on loan")
        return loan

    def _check_can_borrow(self, member: Member) -> None:
        if len(member.active_loans) >= member.policy.max_books:
            raise BorrowingBlockedError(f"limit of {member.policy.max_books} books reached")
        if member.fine_due >= self._fine_block:
            raise BorrowingBlockedError(f"unpaid fines of {member.fine_due}")
        today = self._clock()
        if any(loan.days_overdue(today) for loan in member.active_loans.values()):
            raise BorrowingBlockedError("has an overdue book")

    def _first_available(self, isbn: str) -> Optional[BookItem]:
        return next((i for i in self._catalog.items_for(isbn)
                     if i.status is ItemStatus.AVAILABLE), None)

    def _held_item_for(self, member_id: str, isbn: str) -> Optional[BookItem]:
        for barcode, hold in self._holds.items():
            item = self._catalog.item(barcode)
            if hold.member_id == member_id and item.isbn == isbn:
                return item
        return None

    def _release(self, item: BookItem) -> None:
        """A copy came free: hold it for the next waiting member, else shelve it."""
        queue = self._waitlist.get(item.isbn)
        if queue:
            member_id = queue.popleft()
            item.status = ItemStatus.ON_HOLD
            self._holds[item.barcode] = Hold(member_id, item.barcode,
                                             self._clock() + timedelta(days=self.HOLD_DAYS))
        else:
            item.status = ItemStatus.AVAILABLE

    def _expire_holds(self, isbn: str) -> None:
        """Lazy expiry: run before any decision that depends on availability.
        A production system would also run it from a scheduled sweep."""
        today = self._clock()
        for barcode, hold in list(self._holds.items()):
            item = self._catalog.item(barcode)
            if item.isbn == isbn and today > hold.expires_on:
                del self._holds[barcode]
                self._release(item)


# --- Demo ---

class FakeClock:
    def __init__(self, today: date) -> None:
        self.today = today

    def __call__(self) -> date:
        return self.today

    def advance(self, days: int) -> None:
        self.today += timedelta(days=days)


def demo() -> None:
    print("=== Library Management System ===")
    clock = FakeClock(date(2025, 1, 1))
    catalog = Catalog()
    lib = LibraryService(catalog, ProgressiveFine(cap=Decimal("40.00")), clock)

    books = [
        Book("978-0132350884", "Clean Code", "Robert C. Martin", "Programming", 2008),
        Book("978-0201633610", "Design Patterns", "Gamma, Helm, Johnson, Vlissides", "Programming", 1994),
    ]
    for book, copies in zip(books, (2, 1)):
        catalog.add_book(book)
        for n in range(1, copies + 1):
            catalog.add_item(BookItem(f"{book.isbn[-4:]}-{n}", book.isbn, f"A-{n}"))
    clean, gof = (b.isbn for b in books)

    alice = lib.register_member("Alice", MemberType.STUDENT)
    bob = lib.register_member("Bob", MemberType.FACULTY)
    carol = lib.register_member("Carol", MemberType.PUBLIC)
    print(f"Members: {alice}, {bob}, {carol}")
    print(f"Search 'design': {[str(b) for b in catalog.search(title='design')]}")

    print("\n--- Borrowing ---")
    loan_a = lib.borrow(alice.member_id, gof)
    print(f"  Alice borrowed {loan_a.barcode}, due {loan_a.due_on}")
    try:
        lib.borrow(bob.member_id, gof)
    except NotAvailableError as e:
        print(f"  Bob: {e}")
    print(f"  Bob reserves Design Patterns, position {lib.reserve(bob.member_id, gof)}")
    print(f"  Carol reserves Design Patterns, position {lib.reserve(carol.member_id, gof)}")
    try:
        lib.renew(loan_a.barcode)
    except BorrowingBlockedError as e:
        print(f"  Alice cannot renew: {e}")

    print("\n--- Alice returns 20 days late ---")
    clock.advance(14 + 20)
    loan = lib.return_item(loan_a.barcode)
    print(f"  fine {loan.fine} (7 x 1 + 13 x 2), Alice owes {lib.member(alice.member_id).fine_due}")
    hold = lib.hold_for(bob.member_id, gof)
    print(f"  copy {hold.barcode} on hold for Bob until {hold.expires_on}")
    try:
        lib.borrow(alice.member_id, clean)
    except BorrowingBlockedError as e:
        print(f"  Alice blocked: {e}")
    lib.pay_fine(alice.member_id, Decimal("30.00"))
    print(f"  Alice pays 30.00 (owes 3.00, under the 10.00 block); borrows {lib.borrow(alice.member_id, clean).barcode}")

    print("\n--- Bob never collects; hold passes to Carol ---")
    clock.advance(LibraryService.HOLD_DAYS + 1)
    print(f"  Bob's hold: {lib.hold_for(bob.member_id, gof)}")
    loan_c = lib.borrow(carol.member_id, gof)
    print(f"  Carol borrowed {loan_c.barcode}, due {loan_c.due_on}")
    print(f"  Clean Code copies on shelf: {lib.available_copies(clean)}")


if __name__ == "__main__":
    demo()
```
<!-- /source -->
