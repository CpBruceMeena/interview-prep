"""
Order Matching Engine (stock exchange order book) - Low Level Design
--------------------------------------------------------------------
- Limit and market orders, price-time priority, partial fills, cancels.
- Time-in-force: GTC (rest the remainder), IOC (cancel the remainder),
  FOK (fill completely or do nothing).
- Prices are integer ticks inside the engine. The API boundary accepts
  Decimal and rejects anything that is not an exact multiple of the tick size.
  Floats are refused outright.
- One OrderBook per symbol. Each side keeps a dict price -> PriceLevel plus a
  heap of prices for O(1) best-price lookup. A PriceLevel is an OrderedDict
  (FIFO by arrival, O(1) cancel by id).
- Concurrency: the OrderBook is deliberately NOT thread-safe. Each symbol has
  exactly one writer, a SymbolSequencer thread, that stamps every command with
  a sequence number, journals it, applies it and publishes the events. Same
  journal in -> same trades out, so state can be rebuilt by replay().

Run:  python3 order_matching_engine.py
"""

from __future__ import annotations

import heapq
import itertools
import queue
import threading
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Callable, Iterable, Iterator, Optional, Union


# --------------------------------------------------------------------------- #
# Enums and value objects
# --------------------------------------------------------------------------- #

class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(Enum):
    GTC = "GTC"  # good-till-cancel: remainder rests on the book
    IOC = "IOC"  # immediate-or-cancel: fill what you can, cancel the rest
    FOK = "FOK"  # fill-or-kill: fill everything now or nothing at all


class OrderStatus(Enum):
    NEW = "NEW"                        # resting, nothing filled yet
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"            # may have partial fills before cancel
    REJECTED = "REJECTED"


class OrderError(ValueError):
    """Raised synchronously at the API boundary for malformed input."""


@dataclass(frozen=True)
class Instrument:
    symbol: str
    tick_size: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        if not isinstance(self.tick_size, Decimal) or self.tick_size <= 0:
            raise OrderError("tick_size must be a positive Decimal")

    def to_ticks(self, price: Decimal) -> int:
        if not isinstance(price, Decimal):
            # float(0.1) is 0.1000000000000000055...; never let it near a price.
            raise TypeError(f"price must be Decimal, got {type(price).__name__}")
        ticks = price / self.tick_size
        if ticks != ticks.to_integral_value():
            raise OrderError(f"{price} is not a multiple of tick size {self.tick_size}")
        if ticks <= 0:
            raise OrderError("price must be positive")
        return int(ticks)

    def to_price(self, ticks: int) -> Decimal:
        return self.tick_size * ticks


# --------------------------------------------------------------------------- #
# Commands (inputs) - these are what gets journaled and replayed
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class NewOrder:
    client_id: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.LIMIT
    price: Optional[int] = None        # ticks; None for market orders
    tif: TimeInForce = TimeInForce.GTC


@dataclass(frozen=True)
class CancelOrder:
    order_id: int


Command = Union[NewOrder, CancelOrder]


# --------------------------------------------------------------------------- #
# Events (outputs) - what downstream consumers (market data, clearing) see
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class OrderAccepted:
    seq: int
    order_id: int


@dataclass(frozen=True)
class Trade:
    seq: int
    trade_id: int
    price: int                 # ticks; always the resting (maker) order's price
    quantity: int
    maker_order_id: int
    taker_order_id: int
    taker_side: Side

    @property
    def buy_order_id(self) -> int:
        return self.taker_order_id if self.taker_side is Side.BUY else self.maker_order_id

    @property
    def sell_order_id(self) -> int:
        return self.maker_order_id if self.taker_side is Side.BUY else self.taker_order_id


@dataclass(frozen=True)
class OrderRested:
    seq: int
    order_id: int
    side: Side
    price: int
    quantity: int


@dataclass(frozen=True)
class OrderCancelled:
    seq: int
    order_id: int
    cancelled_quantity: int
    reason: str


@dataclass(frozen=True)
class OrderRejected:
    seq: int
    order_id: Optional[int]
    reason: str


Event = Union[OrderAccepted, Trade, OrderRested, OrderCancelled, OrderRejected]
EventListener = Callable[[str, Event], None]   # (symbol, event)


@dataclass(frozen=True)
class ExecutionReport:
    """Result of one command. Values are copied, so the report never changes
    after it is returned even though the live Order keeps getting filled."""
    seq: int
    order_id: Optional[int]
    status: OrderStatus
    filled_quantity: int
    remaining_quantity: int
    events: tuple[Event, ...]

    @property
    def trades(self) -> list[Trade]:
        return [e for e in self.events if isinstance(e, Trade)]


# --------------------------------------------------------------------------- #
# Order, PriceLevel, BookSide
# --------------------------------------------------------------------------- #

@dataclass(eq=False)
class Order:
    order_id: int              # = sequence number of the NewOrder command
    client_id: str
    side: Side
    order_type: OrderType
    tif: TimeInForce
    quantity: int
    price: Optional[int]
    remaining: int = field(init=False)
    status: OrderStatus = field(init=False, default=OrderStatus.NEW)

    def __post_init__(self) -> None:
        self.remaining = self.quantity

    @property
    def filled(self) -> int:
        return self.quantity - self.remaining

    def fill(self, qty: int) -> None:
        assert 0 < qty <= self.remaining
        self.remaining -= qty
        self.status = OrderStatus.FILLED if self.remaining == 0 else OrderStatus.PARTIALLY_FILLED


class PriceLevel:
    """All resting orders at one price. OrderedDict = FIFO queue with O(1)
    removal by id (a deque would make cancel O(n))."""

    __slots__ = ("price", "_orders", "total_quantity")

    def __init__(self, price: int) -> None:
        self.price = price
        self._orders: OrderedDict[int, Order] = OrderedDict()
        self.total_quantity = 0

    def append(self, order: Order) -> None:
        self._orders[order.order_id] = order
        self.total_quantity += order.remaining

    def head(self) -> Order:
        return next(iter(self._orders.values()))

    def fill_head(self, qty: int) -> Order:
        order = self.head()
        order.fill(qty)
        self.total_quantity -= qty
        if order.remaining == 0:
            self._orders.popitem(last=False)
        return order

    def remove(self, order_id: int) -> Order:
        order = self._orders.pop(order_id)
        self.total_quantity -= order.remaining
        return order

    def __len__(self) -> int:
        return len(self._orders)

    def __iter__(self) -> Iterator[Order]:
        return iter(self._orders.values())


class BookSide:
    """One side of the book. Price levels live in a dict; a heap of prices
    gives the best level. Empty levels are deleted from the dict immediately
    and from the heap lazily (when they surface at the top)."""

    def __init__(self, side: Side) -> None:
        self.side = side
        self._levels: dict[int, PriceLevel] = {}
        self._heap: list[int] = []         # min-heap of priority keys
        self._in_heap: set[int] = set()    # prices with a heap entry (keeps entries unique)

    def _key(self, price: int) -> int:
        return -price if self.side is Side.BUY else price   # bids: highest first

    def best_level(self) -> Optional[PriceLevel]:
        while self._heap:
            price = abs(self._heap[0])
            level = self._levels.get(price)
            if level is not None:
                return level
            heapq.heappop(self._heap)          # stale: level was emptied earlier
            self._in_heap.discard(price)
        return None

    def best_price(self) -> Optional[int]:
        level = self.best_level()
        return level.price if level else None

    def add(self, order: Order) -> None:
        assert order.price is not None
        level = self._levels.get(order.price)
        if level is None:
            level = self._levels[order.price] = PriceLevel(order.price)
            if order.price not in self._in_heap:
                heapq.heappush(self._heap, self._key(order.price))
                self._in_heap.add(order.price)
        level.append(order)

    def remove(self, order: Order) -> None:
        assert order.price is not None
        level = self._levels[order.price]
        level.remove(order.order_id)
        if not level:
            del self._levels[order.price]

    def drop_level_if_empty(self, level: PriceLevel) -> None:
        if not level:
            del self._levels[level.price]

    def levels(self) -> Iterator[PriceLevel]:
        """Levels best-first. O(L log L): used by FOK pre-check and snapshots,
        never on the hot path of an ordinary match."""
        for price in sorted(self._levels, key=self._key):
            yield self._levels[price]

    def depth(self) -> list[tuple[int, int]]:
        return [(lvl.price, lvl.total_quantity) for lvl in self.levels()]


# --------------------------------------------------------------------------- #
# OrderBook - pure, deterministic, single-threaded state machine
# --------------------------------------------------------------------------- #

class OrderBook:
    """Matching logic for one symbol. Not thread-safe by design: exactly one
    writer (the sequencer) calls apply(). Output depends only on the ordered
    command stream - no clocks, no randomness - which is what makes replay work.
    """

    def __init__(self, instrument: Instrument) -> None:
        self.instrument = instrument
        self.bids = BookSide(Side.BUY)
        self.asks = BookSide(Side.SELL)
        self._live: dict[int, Order] = {}          # resting orders by id, for cancel
        self._trade_ids = itertools.count(1)

    # ---- public API -------------------------------------------------------

    def apply(self, seq: int, command: Command) -> ExecutionReport:
        if isinstance(command, NewOrder):
            return self._new_order(seq, command)
        if isinstance(command, CancelOrder):
            return self._cancel(seq, command)
        raise TypeError(f"unknown command {command!r}")

    def best_bid(self) -> Optional[int]:
        return self.bids.best_price()

    def best_ask(self) -> Optional[int]:
        return self.asks.best_price()

    def get_order(self, order_id: int) -> Optional[Order]:
        return self._live.get(order_id)

    def snapshot(self) -> dict[str, list[tuple[int, int]]]:
        """Aggregated depth (price ticks, quantity), best first."""
        return {"bids": self.bids.depth(), "asks": self.asks.depth()}

    # ---- new order ----------------------------------------------------------

    def _new_order(self, seq: int, cmd: NewOrder) -> ExecutionReport:
        reason = self._validate(cmd)
        if reason:
            event = OrderRejected(seq, seq, reason)
            return ExecutionReport(seq, seq, OrderStatus.REJECTED, 0, cmd.quantity, (event,))

        order = Order(seq, cmd.client_id, cmd.side, cmd.order_type, cmd.tif,
                      cmd.quantity, cmd.price)
        events: list[Event] = [OrderAccepted(seq, order.order_id)]

        if order.tif is TimeInForce.FOK and not self._can_fill_completely(order):
            order.status = OrderStatus.CANCELLED
            events.append(OrderCancelled(seq, order.order_id, order.remaining,
                                         "FOK: insufficient liquidity"))
            return self._report(seq, order, events)

        self._match(seq, order, events)

        if order.remaining > 0:
            if order.order_type is OrderType.LIMIT and order.tif is TimeInForce.GTC:
                self._own_side(order.side).add(order)
                self._live[order.order_id] = order
                events.append(OrderRested(seq, order.order_id, order.side,
                                          order.price, order.remaining))  # type: ignore[arg-type]
            else:
                # Market orders and IOC never rest. FOK can't get here with a remainder.
                events.append(OrderCancelled(seq, order.order_id, order.remaining,
                                             "unfilled remainder of IOC/market order"))
                order.status = OrderStatus.CANCELLED
        return self._report(seq, order, events)

    @staticmethod
    def _validate(cmd: NewOrder) -> Optional[str]:
        if cmd.quantity <= 0:
            return "quantity must be positive"
        if cmd.order_type is OrderType.LIMIT and (cmd.price is None or cmd.price <= 0):
            return "limit order needs a positive price"
        if cmd.order_type is OrderType.MARKET:
            if cmd.price is not None:
                return "market order must not carry a price"
            if cmd.tif is TimeInForce.GTC:
                return "market order cannot be GTC (it would rest with no price)"
        return None

    def _match(self, seq: int, taker: Order, events: list[Event]) -> None:
        contra = self._own_side(taker.side.opposite)
        while taker.remaining > 0:
            level = contra.best_level()
            if level is None or not self._crosses(taker, level.price):
                break
            # Price priority: best level first. Time priority: FIFO inside it.
            while taker.remaining > 0 and level:
                qty = min(taker.remaining, level.head().remaining)
                maker = level.fill_head(qty)
                taker.fill(qty)
                if maker.remaining == 0:
                    del self._live[maker.order_id]
                events.append(Trade(seq, next(self._trade_ids), level.price, qty,
                                    maker.order_id, taker.order_id, taker.side))
            contra.drop_level_if_empty(level)

    @staticmethod
    def _crosses(taker: Order, contra_price: int) -> bool:
        if taker.order_type is OrderType.MARKET:
            return True
        assert taker.price is not None
        return contra_price <= taker.price if taker.side is Side.BUY else contra_price >= taker.price

    def _can_fill_completely(self, taker: Order) -> bool:
        available = 0
        for level in self._own_side(taker.side.opposite).levels():
            if not self._crosses(taker, level.price):
                return False
            available += level.total_quantity
            if available >= taker.quantity:
                return True
        return False

    # ---- cancel ---------------------------------------------------------------

    def _cancel(self, seq: int, cmd: CancelOrder) -> ExecutionReport:
        order = self._live.pop(cmd.order_id, None)
        if order is None:
            # Unknown, already filled or already cancelled: a normal race, not an error.
            event = OrderRejected(seq, cmd.order_id, "cancel rejected: order not live")
            return ExecutionReport(seq, cmd.order_id, OrderStatus.REJECTED, 0, 0, (event,))
        self._own_side(order.side).remove(order)
        order.status = OrderStatus.CANCELLED
        event = OrderCancelled(seq, order.order_id, order.remaining, "cancelled by client")
        return self._report(seq, order, [event])

    # ---- helpers ----------------------------------------------------------------

    def _own_side(self, side: Side) -> BookSide:
        return self.bids if side is Side.BUY else self.asks

    @staticmethod
    def _report(seq: int, order: Order, events: list[Event]) -> ExecutionReport:
        return ExecutionReport(seq, order.order_id, order.status, order.filled,
                               order.remaining, tuple(events))


# --------------------------------------------------------------------------- #
# Journal + sequencer (single writer per symbol) + replay
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class JournalEntry:
    seq: int
    command: Command


class Journal:
    """Append-only command log. In production: an fsync'd / replicated log
    (Raft, Aeron cluster, Kafka with acks=all) written BEFORE the ack."""

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []
        self._lock = threading.Lock()   # readers may be on other threads

    def append(self, entry: JournalEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def entries(self) -> list[JournalEntry]:
        with self._lock:
            return list(self._entries)


def replay(instrument: Instrument, entries: Iterable[JournalEntry]) -> tuple[OrderBook, list[ExecutionReport]]:
    """Rebuild a book from its journal. Deterministic: same entries -> same book
    and byte-identical reports. Recovery = latest snapshot + replay of the tail."""
    book = OrderBook(instrument)
    reports = [book.apply(e.seq, e.command) for e in entries]
    return book, reports


_STOP = object()


class SymbolSequencer:
    """The only thread that touches one symbol's OrderBook.

    Many client threads call submit(); the queue imposes a single total order.
    The worker assigns seq, journals, applies, publishes, then completes the
    future. No locks around matching: one writer means nothing to contend on.
    """

    def __init__(self, instrument: Instrument, listeners: Iterable[EventListener] = ()) -> None:
        self.instrument = instrument
        self.book = OrderBook(instrument)
        self.journal = Journal()
        self._listeners = tuple(listeners)
        self._queue: "queue.Queue[object]" = queue.Queue()
        self._seq = 0                       # touched only by the worker thread
        self._closed = False
        self._close_lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, name=f"seq-{instrument.symbol}",
                                        daemon=True)
        self._worker.start()

    def submit(self, command: Command) -> "Future[ExecutionReport]":
        future: "Future[ExecutionReport]" = Future()
        with self._close_lock:              # no submit can slip in after the stop marker
            if self._closed:
                raise RuntimeError(f"sequencer for {self.instrument.symbol} is closed")
            self._queue.put((command, future))
        return future

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(_STOP)
        self._worker.join()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            command, future = item  # type: ignore[misc]
            self._seq += 1
            self.journal.append(JournalEntry(self._seq, command))   # write-ahead
            try:
                report = self.book.apply(self._seq, command)
            except Exception as exc:     # a bug, not a business reject; keep the symbol alive
                future.set_exception(exc)
                continue
            for event in report.events:
                for listener in self._listeners:
                    try:
                        listener(self.instrument.symbol, event)
                    except Exception:
                        pass   # a slow/broken consumer must never stall matching
            future.set_result(report)


class MatchingEngine:
    """Facade: routes each command to its symbol's sequencer. Symbols are
    independent, so they match in parallel; within a symbol, strictly serial."""

    def __init__(self, instruments: Iterable[Instrument],
                 listeners: Iterable[EventListener] = ()) -> None:
        listeners = tuple(listeners)
        self._sequencers = {i.symbol: SymbolSequencer(i, listeners) for i in instruments}

    def submit(self, symbol: str, command: Command) -> "Future[ExecutionReport]":
        return self._sequencer(symbol).submit(command)

    # Blocking conveniences: convert Decimal -> ticks at the boundary.
    def limit(self, symbol: str, client_id: str, side: Side, quantity: int, price: Decimal,
              tif: TimeInForce = TimeInForce.GTC) -> ExecutionReport:
        ticks = self._sequencer(symbol).instrument.to_ticks(price)
        return self.submit(symbol, NewOrder(client_id, side, quantity, OrderType.LIMIT,
                                            ticks, tif)).result()

    def market(self, symbol: str, client_id: str, side: Side, quantity: int,
               tif: TimeInForce = TimeInForce.IOC) -> ExecutionReport:
        return self.submit(symbol, NewOrder(client_id, side, quantity, OrderType.MARKET,
                                            None, tif)).result()

    def cancel(self, symbol: str, order_id: int) -> ExecutionReport:
        return self.submit(symbol, CancelOrder(order_id)).result()

    def book(self, symbol: str) -> OrderBook:
        """Read access for tests/demo. Only safe to read once close() has run
        (or from a listener); live readers should consume events instead."""
        return self._sequencer(symbol).book

    def journal(self, symbol: str) -> Journal:
        return self._sequencer(symbol).journal

    def close(self) -> None:
        for seq in self._sequencers.values():
            seq.close()

    def __enter__(self) -> "MatchingEngine":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _sequencer(self, symbol: str) -> SymbolSequencer:
        try:
            return self._sequencers[symbol]
        except KeyError:
            raise OrderError(f"unknown symbol {symbol}") from None


# --------------------------------------------------------------------------- #
# Demo
# --------------------------------------------------------------------------- #

def main() -> None:
    aapl = Instrument("AAPL", Decimal("0.01"))
    tape: list[str] = []

    def on_event(symbol: str, event: Event) -> None:
        if isinstance(event, Trade):
            tape.append(f"{symbol} trade #{event.trade_id}: {event.quantity} @ "
                        f"{aapl.to_price(event.price)} (maker {event.maker_order_id}, "
                        f"taker {event.taker_order_id} {event.taker_side.value})")

    with MatchingEngine([aapl], listeners=[on_event]) as engine:
        print("== Build the book ==")
        s1 = engine.limit("AAPL", "alice", Side.SELL, 100, Decimal("101.00"))
        s2 = engine.limit("AAPL", "bob", Side.SELL, 50, Decimal("101.00"))   # behind alice
        s3 = engine.limit("AAPL", "carol", Side.SELL, 200, Decimal("102.50"))
        b1 = engine.limit("AAPL", "dave", Side.BUY, 80, Decimal("100.00"))
        print(f"asks rested: {s1.order_id}, {s2.order_id}, {s3.order_id}; bid rested: {b1.order_id}")

        print("\n== Aggressive buy 120 @ 101.00: crosses, alice first (time priority) ==")
        r = engine.limit("AAPL", "erin", Side.BUY, 120, Decimal("101.00"))
        print(f"status={r.status.value} filled={r.filled_quantity} "
              f"fills={[(t.maker_order_id, t.quantity) for t in r.trades]}")

        print("\n== FOK buy 300 @ 102.50: only 230 available -> killed, book untouched ==")
        r = engine.limit("AAPL", "frank", Side.BUY, 300, Decimal("102.50"), TimeInForce.FOK)
        print(f"status={r.status.value} filled={r.filled_quantity}")

        print("\n== IOC sell 100 @ 99.00: hits dave's 80, remaining 20 cancelled ==")
        r = engine.limit("AAPL", "grace", Side.SELL, 100, Decimal("99.00"), TimeInForce.IOC)
        print(f"status={r.status.value} filled={r.filled_quantity} cancelled={r.remaining_quantity}")

        print("\n== Market buy 50: sweeps bob's last 30, then 20 from carol at 102.50 ==")
        r = engine.market("AAPL", "heidi", Side.BUY, 50)
        print(f"status={r.status.value} fills={[(aapl.to_price(t.price), t.quantity) for t in r.trades]}")

        print("\n== Cancel carol's remainder, then cancel it again (race-safe reject) ==")
        print(engine.cancel("AAPL", s3.order_id).status.value,
              engine.cancel("AAPL", s3.order_id).status.value)

        engine.limit("AAPL", "judy", Side.BUY, 40, Decimal("100.50"))
        engine.limit("AAPL", "ken", Side.SELL, 25, Decimal("100.75"))

        try:
            engine.limit("AAPL", "ivan", Side.BUY, 10, Decimal("100.005"))
        except OrderError as exc:
            print(f"\nrejected at boundary: {exc}")

    print("\n== Tape ==")
    print("\n".join(tape))

    book = engine.book("AAPL")
    rebuilt, _ = replay(aapl, engine.journal("AAPL").entries())
    print(f"\nlive book    {book.snapshot()}")
    print(f"replayed book {rebuilt.snapshot()}  identical={rebuilt.snapshot() == book.snapshot()}")


if __name__ == "__main__":
    main()
