import threading
import unittest
from datetime import date
from decimal import Decimal

from library_management import (
    Book, BookItem, BorrowingBlockedError, Catalog, FakeClock, ItemStatus,
    LibraryError, LibraryService, MemberType, NotAvailableError, NotFoundError,
    ProgressiveFine, StandardFine,
)

D = Decimal
ISBN = "111"
OTHER = "222"


class FineTest(unittest.TestCase):
    def test_progressive_tiers(self):
        f = ProgressiveFine()
        cases = {0: "0", 1: "1", 7: "7", 8: "9", 30: "53", 31: "58", 40: "103"}
        for days, expected in cases.items():
            self.assertEqual(f.calculate_fine(days, MemberType.STUDENT), D(expected), days)

    def test_progressive_cap_and_premium(self):
        self.assertEqual(ProgressiveFine(cap=D("40")).calculate_fine(100, MemberType.PUBLIC), D("40"))
        self.assertEqual(ProgressiveFine().calculate_fine(100, MemberType.PREMIUM), D("0"))

    def test_standard_rate_by_type(self):
        self.assertEqual(StandardFine().calculate_fine(4, MemberType.FACULTY), D("2.00"))


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(date(2025, 1, 1))
        self.catalog = Catalog()
        self.catalog.add_book(Book(ISBN, "Clean Code", "Martin", "Programming", 2008))
        self.catalog.add_book(Book(OTHER, "SICP", "Abelson", "Programming", 1985))
        self.catalog.add_item(BookItem("c1", ISBN, "A1"))
        for n in range(1, 11):
            self.catalog.add_item(BookItem(f"s{n}", OTHER, "B1"))
        self.lib = LibraryService(self.catalog, StandardFine(), self.clock)
        self.alice = self.lib.register_member("Alice", MemberType.STUDENT).member_id
        self.bob = self.lib.register_member("Bob", MemberType.PUBLIC).member_id
        self.carol = self.lib.register_member("Carol", MemberType.FACULTY).member_id

    def test_borrow_and_return_on_time(self):
        loan = self.lib.borrow(self.alice, ISBN)
        self.assertEqual(loan.due_on, date(2025, 1, 15))   # student: 14 days
        self.assertEqual(self.catalog.item("c1").status, ItemStatus.ON_LOAN)
        self.assertEqual(self.lib.available_copies(ISBN), 0)
        self.clock.advance(14)
        returned = self.lib.return_item("c1")
        self.assertEqual(returned.fine, D("0"))
        self.assertEqual(self.lib.available_copies(ISBN), 1)

    def test_member_type_limits_apply(self):
        # The original code looked limits up by "STUDENT" against "Student" and always got 3.
        for _ in range(5):
            self.lib.borrow(self.alice, OTHER)
        with self.assertRaises(BorrowingBlockedError):
            self.lib.borrow(self.alice, OTHER)
        for _ in range(3):
            self.lib.borrow(self.bob, OTHER)
        with self.assertRaises(BorrowingBlockedError):
            self.lib.borrow(self.bob, OTHER)

    def test_late_return_fines_and_blocks(self):
        self.lib.borrow(self.bob, ISBN)              # public: 7 days, 2.00/day
        self.clock.advance(7 + 6)
        loan = self.lib.return_item("c1")
        self.assertEqual(loan.fine, D("12.00"))
        with self.assertRaises(BorrowingBlockedError):
            self.lib.borrow(self.bob, OTHER)
        self.assertEqual(self.lib.pay_fine(self.bob, D("12.00")), D("0.00"))
        self.lib.borrow(self.bob, OTHER)
        with self.assertRaises(LibraryError):
            self.lib.pay_fine(self.bob, D("1.00"))

    def test_overdue_book_blocks_new_borrow(self):
        self.lib.borrow(self.alice, ISBN)
        self.clock.advance(15)
        with self.assertRaises(BorrowingBlockedError):
            self.lib.borrow(self.alice, OTHER)

    def test_reservation_queue_and_hold(self):
        self.lib.borrow(self.alice, ISBN)
        with self.assertRaises(NotAvailableError):
            self.lib.borrow(self.bob, ISBN)
        self.assertEqual(self.lib.reserve(self.bob, ISBN), 1)
        self.assertEqual(self.lib.reserve(self.carol, ISBN), 2)
        with self.assertRaises(LibraryError):
            self.lib.reserve(self.bob, ISBN)

        self.lib.return_item("c1")
        self.assertEqual(self.catalog.item("c1").status, ItemStatus.ON_HOLD)
        with self.assertRaises(NotAvailableError):
            self.lib.borrow(self.carol, ISBN)         # held for Bob, not Carol
        self.assertEqual(self.lib.borrow(self.bob, ISBN).barcode, "c1")

    def test_expired_hold_passes_to_next(self):
        self.lib.borrow(self.alice, ISBN)
        self.lib.reserve(self.bob, ISBN)
        self.lib.reserve(self.carol, ISBN)
        self.lib.return_item("c1")
        self.clock.advance(LibraryService.HOLD_DAYS)
        self.assertIsNotNone(self.lib.hold_for(self.bob, ISBN))   # last day still valid
        self.clock.advance(1)
        self.assertIsNone(self.lib.hold_for(self.bob, ISBN))
        self.assertIsNotNone(self.lib.hold_for(self.carol, ISBN))
        self.clock.advance(LibraryService.HOLD_DAYS + 1)
        self.assertEqual(self.lib.available_copies(ISBN), 1)       # queue empty: back on shelf

    def test_cancel_hold_releases_copy(self):
        self.lib.borrow(self.alice, ISBN)
        self.lib.reserve(self.bob, ISBN)
        self.lib.return_item("c1")
        self.lib.cancel_reservation(self.bob, ISBN)
        self.assertEqual(self.catalog.item("c1").status, ItemStatus.AVAILABLE)

    def test_cannot_reserve_when_on_shelf(self):
        with self.assertRaises(LibraryError):
            self.lib.reserve(self.bob, ISBN)

    def test_renew_rules(self):
        loan = self.lib.borrow(self.alice, ISBN)
        self.clock.advance(10)
        self.assertEqual(self.lib.renew("c1").due_on, date(2025, 1, 25))
        self.lib.renew("c1")
        with self.assertRaises(BorrowingBlockedError):
            self.lib.renew("c1")                      # max 2 renewals
        self.assertEqual(loan.renewals, 2)

    def test_renew_blocked_by_waitlist(self):
        self.lib.borrow(self.alice, ISBN)
        self.lib.reserve(self.bob, ISBN)
        with self.assertRaises(BorrowingBlockedError):
            self.lib.renew("c1")

    def test_report_lost(self):
        self.lib.borrow(self.alice, ISBN)
        self.lib.report_lost("c1", D("35.00"))
        self.assertEqual(self.lib.member(self.alice).fine_due, D("35.00"))
        self.assertEqual(self.catalog.item("c1").status, ItemStatus.LOST)
        with self.assertRaises(LibraryError):
            self.lib.return_item("c1")

    def test_unknown_ids(self):
        with self.assertRaises(NotFoundError):
            self.lib.borrow("nobody", ISBN)
        with self.assertRaises(NotFoundError):
            self.lib.borrow(self.alice, "999")
        with self.assertRaises(NotFoundError):
            self.lib.return_item("zzz")

    def test_search(self):
        self.assertEqual([b.isbn for b in self.catalog.search(title="clean")], [ISBN])
        self.assertEqual(len(self.catalog.search(category="programming")), 2)
        self.assertEqual(self.catalog.search(title="clean", author="abelson"), [])

    def test_concurrent_borrow_never_double_issues(self):
        members = [self.lib.register_member(f"m{i}", MemberType.FACULTY).member_id
                   for i in range(30)]
        wins, barrier = [], threading.Barrier(len(members))

        def attempt(mid):
            barrier.wait()
            try:
                wins.append(self.lib.borrow(mid, OTHER).barcode)
            except NotAvailableError:
                pass

        threads = [threading.Thread(target=attempt, args=(m,)) for m in members]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(wins), 10)               # exactly the 10 copies
        self.assertEqual(len(set(wins)), 10)          # each copy issued once


if __name__ == "__main__":
    unittest.main()
