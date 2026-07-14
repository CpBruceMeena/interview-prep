"""
Library Management System - Low Level Design
----------------------------------------------
Design Principles: SOLID, Strategy Pattern, Observer Pattern
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
import uuid


class BookStatus(Enum):
    AVAILABLE = "Available"
    BORROWED = "Borrowed"
    RESERVED = "Reserved"
    LOST = "Lost"
    DAMAGED = "Damaged"
    UNDER_MAINTENANCE = "Under Maintenance"


class MemberType(Enum):
    STUDENT = "Student"
    FACULTY = "Faculty"
    PUBLIC = "Public"
    PREMIUM = "Premium"


class FinePolicy(Enum):
    DAILY = "Daily"
    HOURLY = "Hourly"
    WEEKLY = "Weekly"


# --- Book (SRP) ---

class Book:
    """Single Responsibility: Represents a book's metadata"""

    def __init__(self, isbn: str, title: str, author: str,
                 publisher: str, year: int, category: str,
                 total_copies: int = 1):
        self._isbn = isbn
        self._title = title
        self._author = author
        self._publisher = publisher
        self._year = year
        self._category = category
        self._total_copies = total_copies
        self._available_copies = total_copies

    @property
    def isbn(self) -> str:
        return self._isbn

    @property
    def title(self) -> str:
        return self._title

    @property
    def author(self) -> str:
        return self._author

    @property
    def category(self) -> str:
        return self._category

    @property
    def available_copies(self) -> int:
        return self._available_copies

    def is_available(self) -> bool:
        return self._available_copies > 0

    def borrow_copy(self) -> bool:
        if self._available_copies <= 0:
            return False
        self._available_copies -= 1
        return True

    def return_copy(self) -> None:
        if self._available_copies < self._total_copies:
            self._available_copies += 1

    def __str__(self) -> str:
        return f"{self._title} by {self._author} ({self._available_copies}/{self._total_copies})"


# --- Book Item (Physical Copy) ---

class BookItem:
    """Represents a physical copy of a book"""

    def __init__(self, barcode: str, book: Book, rack_location: str):
        self._barcode = barcode
        self._book = book
        self._rack = rack_location
        self._status = BookStatus.AVAILABLE
        self._borrowed_by: Optional[str] = None
        self._due_date: Optional[datetime] = None

    @property
    def barcode(self) -> str:
        return self._barcode

    @property
    def book(self) -> Book:
        return self._book

    @property
    def status(self) -> BookStatus:
        return self._status

    @status.setter
    def status(self, value: BookStatus) -> None:
        self._status = value

    @property
    def due_date(self) -> Optional[datetime]:
        return self._due_date

    def borrow(self, member_id: str, days: int) -> None:
        self._status = BookStatus.BORROWED
        self._borrowed_by = member_id
        self._due_date = datetime.now() + timedelta(days=days)

    def return_book(self) -> None:
        self._status = BookStatus.AVAILABLE
        self._borrowed_by = None
        self._due_date = None

    def __str__(self) -> str:
        return f"[{self._barcode}] {self._book.title} - {self._status.value}"


# --- Member (SRP) ---

class Member:
    def __init__(self, member_id: str, name: str, email: str,
                 phone: str, member_type: MemberType = MemberType.PUBLIC):
        self._member_id = member_id
        self._name = name
        self._email = email
        self._phone = phone
        self._member_type = member_type
        self._borrowed_books: Dict[str, BookItem] = {}
        self._total_fine = 0.0

    @property
    def member_id(self) -> str:
        return self._member_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def member_type(self) -> MemberType:
        return self._member_type

    @property
    def borrowed_books(self) -> Dict[str, BookItem]:
        return dict(self._borrowed_books)

    @property
    def total_fine(self) -> float:
        return self._total_fine

    def add_fine(self, amount: float) -> None:
        self._total_fine += amount

    def pay_fine(self, amount: float) -> None:
        self._total_fine = max(0, self._total_fine - amount)

    def can_borrow(self) -> bool:
        max_books = {"STUDENT": 5, "FACULTY": 10, "PUBLIC": 3, "PREMIUM": 8}
        limit = max_books.get(self._member_type.value, 3)
        return len(self._borrowed_books) < limit and self._total_fine < 50.0

    def borrow_book(self, item: BookItem) -> None:
        self._borrowed_books[item.barcode] = item

    def return_book(self, barcode: str) -> Optional[BookItem]:
        return self._borrowed_books.pop(barcode, None)

    def __str__(self) -> str:
        return f"{self._name} ({self._member_type.value})"


# --- Fine Calculation (Strategy Pattern) ---

class FineCalculator(ABC):
    @abstractmethod
    def calculate_fine(self, days_overdue: int, member_type: MemberType) -> float:
        pass


class StandardFine(FineCalculator):
    _rates = {MemberType.STUDENT: 1.0, MemberType.FACULTY: 0.5,
              MemberType.PUBLIC: 2.0, MemberType.PREMIUM: 0.0}

    def calculate_fine(self, days_overdue: int, member_type: MemberType) -> float:
        rate = self._rates.get(member_type, 1.0)
        return rate * days_overdue


class ProgressiveFine(FineCalculator):
    def calculate_fine(self, days_overdue: int, member_type: MemberType) -> float:
        if member_type == MemberType.PREMIUM:
            return 0.0
        if days_overdue <= 7:
            return 1.0 * days_overdue
        elif days_overdue <= 30:
            return 7.0 + 2.0 * (days_overdue - 7)
        else:
            return 7.0 + 46.0 + 5.0 * (days_overdue - 30)


# --- Catalog / Search (SRP) ---

class Catalog:
    """Search books by various criteria"""

    def __init__(self):
        self._books: Dict[str, Book] = {}
        self._items: Dict[str, BookItem] = {}

    def add_book(self, book: Book) -> None:
        self._books[book.isbn] = book

    def add_item(self, item: BookItem) -> None:
        self._items[item.barcode] = item

    def search_by_title(self, title: str) -> List[Book]:
        return [b for b in self._books.values() if title.lower() in b.title.lower()]

    def search_by_author(self, author: str) -> List[Book]:
        return [b for b in self._books.values() if author.lower() in b.author.lower()]

    def search_by_isbn(self, isbn: str) -> Optional[Book]:
        return self._books.get(isbn)

    def search_by_category(self, category: str) -> List[Book]:
        return [b for b in self._books.values() if category.lower() in b.category.lower()]

    def get_available_items(self, isbn: str) -> List[BookItem]:
        return [i for i in self._items.values()
                if i.book.isbn == isbn and i.status == BookStatus.AVAILABLE]

    def get_item(self, barcode: str) -> Optional[BookItem]:
        return self._items.get(barcode)


# --- Lending Service (Facade / SRP) ---

class LendingService:
    def __init__(self, catalog: Catalog, fine_calculator: FineCalculator = None):
        self._catalog = catalog
        self._members: Dict[str, Member] = {}
        self._fine_calc = fine_calculator or StandardFine()
        self._max_loan_days = {MemberType.STUDENT: 14, MemberType.FACULTY: 30,
                                MemberType.PUBLIC: 7, MemberType.PREMIUM: 21}

    def register_member(self, name: str, email: str, phone: str,
                        member_type: MemberType = MemberType.PUBLIC) -> Member:
        member_id = f"M-{uuid.uuid4().hex[:6].upper()}"
        member = Member(member_id, name, email, phone, member_type)
        self._members[member_id] = member
        return member

    def get_member(self, member_id: str) -> Optional[Member]:
        return self._members.get(member_id)

    def borrow_book(self, member_id: str, isbn: str) -> Optional[BookItem]:
        member = self._members.get(member_id)
        if not member:
            print(f"  Member {member_id} not found")
            return None

        if not member.can_borrow():
            print(f"  {member.name} cannot borrow (limit/fine issue)")
            return None

        book = self._catalog.search_by_isbn(isbn)
        if not book or not book.is_available():
            print(f"  Book {isbn} not available")
            return None

        items = self._catalog.get_available_items(isbn)
        if not items:
            print(f"  No available copies of {book.title}")
            return None

        item = items[0]
        loan_days = self._max_loan_days.get(member.member_type, 14)
        item.borrow(member_id, loan_days)
        member.borrow_book(item)
        book.borrow_copy()

        print(f"  ✅ {member.name} borrowed '{book.title}' due {item.due_date:%d-%m-%Y}")
        return item

    def return_book(self, member_id: str, barcode: str) -> Optional[float]:
        member = self._members.get(member_id)
        if not member:
            print(f"  Member {member_id} not found")
            return None

        item = member.return_book(barcode)
        if not item:
            print(f"  Book item {barcode} not borrowed by {member.name}")
            return None

        # Calculate fine
        fine = 0.0
        if item.due_date and datetime.now() > item.due_date:
            days_overdue = (datetime.now() - item.due_date).days
            fine = self._fine_calc.calculate_fine(days_overdue, member.member_type)
            member.add_fine(fine)

        item.return_book()
        item.book.return_copy()

        print(f"  📚 {member.name} returned '{item.book.title}'", end="")
        if fine > 0:
            print(f" (Fine: ${fine:.2f})", end="")
        print()

        return fine

    def get_borrowed_books(self, member_id: str) -> List[BookItem]:
        member = self._members.get(member_id)
        if member:
            return list(member.borrowed_books.values())
        return []


# --- Demo ---

def demo():
    print("=== Library Management System ===")
    print("=" * 50)

    catalog = Catalog()
    service = LendingService(catalog, ProgressiveFine())

    # Add books
    book1 = Book("978-0-13-468599-1", "Clean Code", "Robert C. Martin",
                 "Prentice Hall", 2008, "Programming", 3)
    book2 = Book("978-0-201-63361-0", "Design Patterns", "Gang of Four",
                 "Addison-Wesley", 1994, "Programming", 2)
    book3 = Book("978-0-596-51774-8", "Head First Design Patterns",
                 "Eric Freeman", "O'Reilly", 2004, "Programming", 2)

    for book in [book1, book2, book3]:
        catalog.add_book(book)
        for i in range(book._total_copies):
            barcode = f"BC-{book.isbn[-6:]}-{i+1:02d}"
            item = BookItem(barcode, book, f"Section-A, Row-{i+1}")
            catalog.add_item(item)

    # Register members
    alice = service.register_member("Alice", "alice@lib.com", "1234567890", MemberType.STUDENT)
    bob = service.register_member("Bob", "bob@lib.com", "0987654321", MemberType.FACULTY)

    print(f"\nMembers: {alice}, {bob}")

    # Search and borrow
    print("\n--- Search Results ---")
    for title_search in ["Clean", "Design"]:
        books = catalog.search_by_title(title_search)
        print(f"  '{title_search}': {[str(b) for b in books]}")

    print("\n--- Borrowing ---")
    service.borrow_book(alice.member_id, "978-0-13-468599-1")
    service.borrow_book(alice.member_id, "978-0-201-63361-0")
    service.borrow_book(bob.member_id, "978-0-596-51774-8")

    # Return with fine simulation
    print("\n--- Returning (simulating overdue) ---")
    # Force overdue by modifying due date
    for item in alice.borrowed_books.values():
        item._due_date = datetime.now() - timedelta(days=5)

    service.return_book(alice.member_id,
                        list(alice.borrowed_books.keys())[0])

    # Check member fines
    print(f"\n--- Member Status ---")
    for member in [alice, bob]:
        print(f"  {member.name}: ${member.total_fine:.2f} fine, "
              f"{len(member.borrowed_books)} books borrowed")


if __name__ == "__main__":
    demo()
