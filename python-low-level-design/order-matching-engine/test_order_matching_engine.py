"""Run: python3 -m unittest test_order_matching_engine  (from this directory)"""

import random
import threading
import unittest
from collections import defaultdict
from decimal import Decimal

from order_matching_engine import (
    CancelOrder, Instrument, MatchingEngine, NewOrder, OrderBook, OrderCancelled,
    OrderError, OrderRejected, OrderStatus, OrderType, Side, TimeInForce, Trade, replay,
)

INST = Instrument("TEST", Decimal("0.01"))


class BookHarness:
    """Drives an OrderBook directly with an incrementing seq (no threads)."""

    def __init__(self) -> None:
        self.book = OrderBook(INST)
        self.seq = 0

    def send(self, cmd):
        self.seq += 1
        return self.book.apply(self.seq, cmd)

    def limit(self, side, qty, price, tif=TimeInForce.GTC, client="c"):
        return self.send(NewOrder(client, side, qty, OrderType.LIMIT, price, tif))

    def market(self, side, qty, tif=TimeInForce.IOC):
        return self.send(NewOrder("c", side, qty, OrderType.MARKET, None, tif))

    def cancel(self, order_id):
        return self.send(CancelOrder(order_id))


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.h = BookHarness()

    def test_non_crossing_orders_rest(self):
        self.h.limit(Side.BUY, 10, 100)
        self.h.limit(Side.SELL, 10, 101)
        self.assertEqual(self.h.book.best_bid(), 100)
        self.assertEqual(self.h.book.best_ask(), 101)

    def test_price_priority_best_price_first(self):
        self.h.limit(Side.SELL, 10, 105)
        cheap = self.h.limit(Side.SELL, 10, 101)
        r = self.h.limit(Side.BUY, 10, 110)
        self.assertEqual([(t.maker_order_id, t.price) for t in r.trades], [(cheap.order_id, 101)])

    def test_time_priority_fifo_within_level(self):
        first = self.h.limit(Side.SELL, 10, 100)
        second = self.h.limit(Side.SELL, 10, 100)
        r = self.h.limit(Side.BUY, 15, 100)
        self.assertEqual([(t.maker_order_id, t.quantity) for t in r.trades],
                         [(first.order_id, 10), (second.order_id, 5)])
        self.assertEqual(self.h.book.get_order(second.order_id).status, OrderStatus.PARTIALLY_FILLED)

    def test_trade_executes_at_maker_price(self):
        self.h.limit(Side.SELL, 10, 100)
        r = self.h.limit(Side.BUY, 10, 105)
        self.assertEqual(r.trades[0].price, 100)
        self.assertEqual(r.trades[0].buy_order_id, r.order_id)

    def test_partial_fill_remainder_rests(self):
        self.h.limit(Side.SELL, 4, 100)
        r = self.h.limit(Side.BUY, 10, 100)
        self.assertEqual((r.status, r.filled_quantity, r.remaining_quantity),
                         (OrderStatus.PARTIALLY_FILLED, 4, 6))
        self.assertEqual(self.h.book.snapshot(), {"bids": [(100, 6)], "asks": []})

    def test_sweeps_multiple_levels(self):
        for price in (100, 101, 102):
            self.h.limit(Side.SELL, 5, price)
        r = self.h.limit(Side.BUY, 12, 101)
        self.assertEqual([(t.price, t.quantity) for t in r.trades], [(100, 5), (101, 5)])
        self.assertEqual(self.h.book.snapshot(), {"bids": [(101, 2)], "asks": [(102, 5)]})

    def test_market_order_never_rests(self):
        self.h.limit(Side.BUY, 5, 99)
        r = self.h.market(Side.SELL, 8)
        self.assertEqual((r.status, r.filled_quantity, r.remaining_quantity),
                         (OrderStatus.CANCELLED, 5, 3))
        self.assertEqual(self.h.book.snapshot(), {"bids": [], "asks": []})

    def test_market_order_on_empty_book(self):
        r = self.h.market(Side.BUY, 5)
        self.assertEqual((r.status, r.filled_quantity), (OrderStatus.CANCELLED, 0))

    def test_ioc_cancels_remainder(self):
        self.h.limit(Side.SELL, 3, 100)
        r = self.h.limit(Side.BUY, 10, 100, TimeInForce.IOC)
        self.assertEqual((r.filled_quantity, r.remaining_quantity), (3, 7))
        self.assertIsNone(self.h.book.best_bid())

    def test_fok_insufficient_liquidity_leaves_book_untouched(self):
        self.h.limit(Side.SELL, 5, 100)
        self.h.limit(Side.SELL, 5, 103)          # beyond the limit, must not count
        before = self.h.book.snapshot()
        r = self.h.limit(Side.BUY, 8, 101, TimeInForce.FOK)
        self.assertEqual((r.status, r.filled_quantity), (OrderStatus.CANCELLED, 0))
        self.assertFalse(r.trades)
        self.assertEqual(self.h.book.snapshot(), before)

    def test_fok_exact_liquidity_fills(self):
        self.h.limit(Side.SELL, 5, 100)
        self.h.limit(Side.SELL, 5, 101)
        r = self.h.limit(Side.BUY, 10, 101, TimeInForce.FOK)
        self.assertEqual(r.status, OrderStatus.FILLED)

    def test_cancel_resting_order_and_double_cancel(self):
        a = self.h.limit(Side.BUY, 10, 100)
        b = self.h.limit(Side.BUY, 10, 100)
        r = self.h.cancel(a.order_id)
        self.assertEqual((r.status, r.remaining_quantity), (OrderStatus.CANCELLED, 10))
        self.assertEqual(self.h.book.snapshot()["bids"], [(100, 10)])
        again = self.h.cancel(a.order_id)
        self.assertEqual(again.status, OrderStatus.REJECTED)
        # b is now first in line
        t = self.h.limit(Side.SELL, 1, 100).trades[0]
        self.assertEqual(t.maker_order_id, b.order_id)

    def test_cancel_filled_order_is_rejected(self):
        a = self.h.limit(Side.BUY, 10, 100)
        self.h.limit(Side.SELL, 10, 100)
        self.assertIsInstance(self.h.cancel(a.order_id).events[0], OrderRejected)

    def test_level_reused_after_emptied(self):
        a = self.h.limit(Side.SELL, 5, 100)
        self.h.limit(Side.SELL, 5, 101)
        self.h.cancel(a.order_id)                # 100 level gone, heap entry stale
        self.assertEqual(self.h.book.best_ask(), 101)
        self.h.limit(Side.SELL, 7, 100)          # level re-created
        self.assertEqual(self.h.book.best_ask(), 100)
        self.assertEqual(self.h.book.asks._heap.count(100), 1)   # no duplicate heap entries

    def test_validation_rejects(self):
        cases = [
            NewOrder("c", Side.BUY, 0, OrderType.LIMIT, 100),
            NewOrder("c", Side.BUY, 5, OrderType.LIMIT, None),
            NewOrder("c", Side.BUY, 5, OrderType.MARKET, 100, TimeInForce.IOC),
            NewOrder("c", Side.BUY, 5, OrderType.MARKET, None, TimeInForce.GTC),
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.h.send(cmd).status, OrderStatus.REJECTED)
        self.assertEqual(self.h.book.snapshot(), {"bids": [], "asks": []})


class TestPrices(unittest.TestCase):
    def test_decimal_to_ticks(self):
        self.assertEqual(INST.to_ticks(Decimal("101.25")), 10125)
        self.assertEqual(INST.to_price(10125), Decimal("101.25"))

    def test_off_tick_and_float_rejected(self):
        with self.assertRaises(OrderError):
            INST.to_ticks(Decimal("1.005"))
        with self.assertRaises(TypeError):
            INST.to_ticks(1.01)
        with self.assertRaises(OrderError):
            INST.to_ticks(Decimal("0"))


class TestEngineAndReplay(unittest.TestCase):
    def test_events_published_in_sequence_order(self):
        seen = []
        with MatchingEngine([INST], listeners=[lambda s, e: seen.append(e.seq)]) as engine:
            engine.limit("TEST", "a", Side.SELL, 10, Decimal("1.00"))
            engine.limit("TEST", "b", Side.BUY, 4, Decimal("1.00"))
            engine.cancel("TEST", 1)
        self.assertEqual(seen, sorted(seen))

    def test_unknown_symbol_and_closed_engine(self):
        engine = MatchingEngine([INST])
        with self.assertRaises(OrderError):
            engine.market("NOPE", "a", Side.BUY, 1)
        engine.close()
        with self.assertRaises(RuntimeError):
            engine.market("TEST", "a", Side.BUY, 1)

    def test_concurrent_submitters_single_writer_invariants_and_replay(self):
        other = Instrument("OTHER", Decimal("0.05"))
        trades_by_symbol = defaultdict(list)
        listener_lock = threading.Lock()

        def on_event(symbol, event):
            if isinstance(event, Trade):
                with listener_lock:
                    trades_by_symbol[symbol].append(event)

        engine = MatchingEngine([INST, other], listeners=[on_event])
        reports = []
        reports_lock = threading.Lock()
        start = threading.Barrier(8)

        def client(n: int) -> None:
            rng = random.Random(n)
            start.wait()
            futures = []
            for _ in range(250):
                symbol = "TEST" if rng.random() < 0.7 else "OTHER"
                roll = rng.random()
                if roll < 0.1:
                    cmd = CancelOrder(rng.randint(1, 400))
                elif roll < 0.2:
                    cmd = NewOrder(f"c{n}", rng.choice(list(Side)), rng.randint(1, 20),
                                   OrderType.MARKET, None, TimeInForce.IOC)
                else:
                    tif = rng.choice([TimeInForce.GTC, TimeInForce.GTC, TimeInForce.IOC, TimeInForce.FOK])
                    cmd = NewOrder(f"c{n}", rng.choice(list(Side)), rng.randint(1, 20),
                                   OrderType.LIMIT, rng.randint(95, 105), tif)
                futures.append((symbol, cmd, engine.submit(symbol, cmd)))
            with reports_lock:
                reports.extend((s, c, f.result(timeout=5)) for s, c, f in futures)

        threads = [threading.Thread(target=client, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        engine.close()

        self.assertEqual(len(reports), 8 * 250)
        for symbol, inst in (("TEST", INST), ("OTHER", other)):
            book = engine.book(symbol)
            bid, ask = book.best_bid(), book.best_ask()
            if bid is not None and ask is not None:
                self.assertLess(bid, ask, "book must never be left crossed")

            # Quantity conservation per order: filled via trades + resting + cancelled == qty.
            filled = defaultdict(int)
            for t in trades_by_symbol[symbol]:
                filled[t.maker_order_id] += t.quantity
                filled[t.taker_order_id] += t.quantity
            entries = engine.journal(symbol).entries()
            self.assertEqual([e.seq for e in entries], list(range(1, len(entries) + 1)))
            by_seq = {r.seq: r for s, _, r in reports if s == symbol}
            cancelled = defaultdict(int)
            for r in by_seq.values():
                for e in r.events:
                    if isinstance(e, OrderCancelled):
                        cancelled[e.order_id] += e.cancelled_quantity
            checked = 0
            for e in entries:
                if not isinstance(e.command, NewOrder) or by_seq[e.seq].status is OrderStatus.REJECTED:
                    continue
                live = book.get_order(e.seq)
                resting = live.remaining if live else 0
                self.assertEqual(filled[e.seq] + resting + cancelled[e.seq], e.command.quantity)
                checked += 1
            self.assertGreater(checked, 100)
            self.assertTrue(trades_by_symbol[symbol], "expected some trades")

            # Replay of the journal reproduces the exact trades and book.
            rebuilt, replay_reports = replay(inst, entries)
            self.assertEqual(rebuilt.snapshot(), book.snapshot())
            replay_trades = [t for r in replay_reports for t in r.trades]
            self.assertEqual(replay_trades, sorted(trades_by_symbol[symbol], key=lambda t: t.trade_id))


if __name__ == "__main__":
    unittest.main()
