# 🪵 Logging Framework — Implementation

> **Python 3.10+, stdlib only.** Run the demo with `python3 logging_framework.py`; run the tests with `python3 -m unittest test_logging_framework` from this directory.

---

## Map of the file

| Section | Key types | What to look at |
|---|---|---|
| Levels | `Level(IntEnum)` | Integer comparison is the whole enable check |
| Context | `log_context()`, `current_context()` | `ContextVar` holding an immutable mapping; token reset on exit |
| Record | `LogRecord` (frozen) | Lazy `message`; context captured at creation |
| Formatters | `Formatter`, `TextFormatter`, `JsonFormatter` | JSON reserved keys written last; `template` kept for grouping |
| Filters | `Filter`, `NameFilter`, `RedactionFilter`, `SamplingFilter` | Return the record, a modified copy, or `None` |
| Handlers | `Handler`, `StreamHandler`, `ConsoleHandler`, `FileHandler`, `InMemoryHandler` | Template method `handle()`; `emit()` under the handler lock |
| Async | `AsyncHandler`, `OverflowPolicy` | Bounded queue, worker thread, drop counter, flush/close |
| Hierarchy | `Logger`, `LogManager` | `get_logger`, `effective_level` cache, propagation loop, `shutdown` ordering |

---

## Key design decisions

### 1. The fast path

```python
def log(self, level, msg, /, *args, exc_info=False, **extra):
    if not self.is_enabled_for(level):
        return
    record = LogRecord(...)
```

`is_enabled_for` reads a cached `(generation, level)` tuple. When the manager's generation matches, it costs one comparison; otherwise it walks to the nearest explicit level and re-caches. `set_level` anywhere bumps the generation under the manager lock. A reader that races with `set_level` may cache a value tagged with the old generation, which is simply recomputed on the next call. So the cache is never wrongly *kept*.

`msg % args` happens only in `LogRecord.message`, i.e. only if some handler formats it. `logger.debug("x=%s", expensive_obj)` never calls `str(expensive_obj)` when DEBUG is off (tested). `level` and `msg` are positional-only so `extra` fields may be called `level` or `msg` (a bug the tests caught).

### 2. Handler template method

```python
def handle(self, record):
    if record.level < self.level: return
    try:
        kept = self._apply_filters(record)      # drop or transform
        if kept is None: return
        text = self.formatter.format(kept)      # outside the lock
        with self._lock:
            if not self._closed:
                self.emit(text, kept)           # the only serialised part
    except Exception:
        self.handle_error(record)               # stderr, never raise
```

Subclasses implement only `emit` (and `flush`/`close` where they own a resource). A new sink (syslog, HTTP, Kafka) is one small class.

### 3. Propagation (Chain of Responsibility)

`Logger._dispatch` offers the record to each logger's handlers, walking parents until `propagate=False`. Ancestor **logger** levels are not consulted (the decision was made once at the originating logger); ancestor **handler** levels are. Tests pin both halves of that rule.

### 4. Copy-on-write handler lists

`add_handler`/`remove_handler` build a new tuple under the manager lock; `_dispatch` iterates whatever tuple it read. No lock on the hot path, and no "list changed size during iteration".

### 5. AsyncHandler

| Concern | Choice |
|---|---|
| What's queued | The immutable `LogRecord`, so formatting cost moves to the worker too |
| Where its own filters run | In the caller: drop early, don't spend queue slots on rejected records |
| Queue | `queue.Queue(maxsize=capacity)`: bounded by design |
| `DROP` | `put_nowait`; on `Full` increment `dropped` |
| `BLOCK` | `put(timeout=block_timeout)`; `None` = wait forever (true back-pressure) |
| `flush()` | `queue.join()` (waits for `task_done` on every item so far) then `target.flush()` |
| `close()` | Mark closed → blocking `put(_STOP)` → join worker → drain/count stragglers → `target.close()` |
| After close | Records are counted as dropped; nothing raises or hangs |

Why the stop marker uses a blocking put even under `DROP`: if it were dropped on a full queue, the worker would never exit and `close()` would wait for its timeout and lose the tail.

### 6. Context

`log_context(**fields)` merges into the current mapping and resets via the `ContextVar` token in `finally`. The record copies `dict(_context.get())` at creation, which is what makes `AsyncHandler` output carry the caller's correlation id. The tests run 8 threads and 5 interleaved asyncio tasks and check every record's id.

### 7. Filters that transform

- `RedactionFilter` scrubs the template, each non-numeric argument and string fields of `context`/`extra`, and blanks sensitive keys (`password`, `token`, ...). It scrubs args separately rather than the interpolated message, so `template` stays a stable grouping key and `%d`/`%.2f` still work.
- `SamplingFilter(rate, keep_at_or_above=WARNING)` keeps all warnings and errors and samples the rest by `crc32(correlation_id)`, so a request's lines are kept or dropped together (and consistently across services, since `crc32` is stable where Python's `hash()` is salted per process).

---

## Where to extend

| Requirement | Change |
|---|---|
| Rotating file by size/time | `RotatingFileHandler(FileHandler)`: in `emit`, check size and rename + reopen under the same lock |
| Never drop ERROR+ under `DROP` | In `AsyncHandler.handle`, use a blocking put when `record.level >= ERROR` |
| Network sink (Kafka/HTTP) | A handler that batches in `emit` and sends on size/time; always behind `AsyncHandler` |
| Config from a dict/YAML | `LogManager.configure(dict)` building handlers by name and calling `set_level`/`add_handler`; atomic swap by building the new tuples first |
| Rate-limit a noisy line | A `Filter` keyed by `(logger_name, msg)` template with a token bucket |
| Multiple processes writing one file | Don't. Use one file per process, or a queue to a single writer process / the local agent |

---

## Tests

`test_logging_framework.py` (25 tests, ~0.3 s): hierarchy construction and caching; level inheritance with cache invalidation and `set_level(None)`; lazy formatting; propagation with `propagate=False` and the logger-vs-handler level rule; text/JSON format including exceptions and reserved keys; bad format args; name filter dot-boundary; redaction of template, args, context and extra; request-consistent sampling; context isolation across **8 threads** and **5 asyncio tasks**; a failing formatter never raises; **8 threads × 300 lines to one file with no interleaving**; ring-buffer bound; AsyncHandler **DROP** (never blocks, exact drop count), **BLOCK** (caller held until space), **BLOCK+timeout** (drops after timeout), flush/shutdown draining 2000 records from 8 threads, logging after shutdown, context captured in the caller, and shutdown ordering with a shared target.

---

## Full source

<!-- source: logging_framework.py -->
```python
"""
Logging Framework — Low-Level Design
====================================

A small, thread-safe logging library in the shape of log4j / Python `logging`:

  * Levels: DEBUG < INFO < WARNING < ERROR < CRITICAL.
  * Logger hierarchy by dotted name ("app.db.pool" -> "app.db" -> "app" -> root),
    with level inheritance: a logger without its own level uses its nearest
    ancestor's.
  * Handlers (appenders) are Strategies for *where* records go: console, file,
    in-memory, and an async wrapper. Each handler has its own level, filters and
    formatter.
  * Propagation is a Chain of Responsibility up the hierarchy: a record is offered
    to the handlers of the logger, then its parent, ... until a logger has
    propagate=False or the root is reached.
  * Formatters: plain text and structured JSON.
  * Filters can drop or transform a record: name prefix, PII redaction, sampling.
  * Per-request context (correlation id, user id, ...) via `contextvars`, so it is
    correct for threads AND asyncio tasks.
  * AsyncHandler: bounded queue + background worker so callers never wait on I/O,
    with an explicit overflow policy (DROP or BLOCK with timeout), drop counters,
    and flush/close on shutdown.

Design rule: logging must never crash or deadlock the application. Formatting or
I/O errors are reported to stderr and swallowed.

Python 3.10+, stdlib only.
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import dataclasses
import json
import queue
import random
import re
import sys
import threading
import time
import traceback
import zlib
from decimal import Decimal
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional, TextIO


# ─── Levels ──────────────────────────────────────────────────────────────────

class Level(IntEnum):
    NOTSET = 0
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


# ─── Request context (correlation ids) ───────────────────────────────────────

_context: contextvars.ContextVar[Mapping[str, Any]] = contextvars.ContextVar(
    "log_context", default={})


@contextlib.contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Bind fields (e.g. correlation_id=...) to every record logged in this scope.

    ContextVar values are per thread and per asyncio task, so concurrent requests
    never see each other's fields. Nested scopes merge; leaving a scope restores
    the previous mapping exactly (token reset), even on exceptions.
    """
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> Mapping[str, Any]:
    return _context.get()


# ─── Record ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LogRecord:
    """Immutable, so it can be handed to another thread (AsyncHandler) safely.
    Context is captured at creation time, in the caller's thread/task."""
    logger_name: str
    level: Level
    msg: str
    args: tuple
    created: float
    thread_name: str
    context: Mapping[str, Any] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)
    exc_text: Optional[str] = None

    @property
    def message(self) -> str:
        """%-style interpolation done lazily, only if some handler formats the record.
        A bad format string must not raise into application code."""
        if not self.args:
            return self.msg
        try:
            return self.msg % self.args
        except (TypeError, ValueError):
            return f"{self.msg} {self.args!r}"

    @property
    def correlation_id(self) -> Optional[str]:
        return self.context.get("correlation_id")


# ─── Formatters ──────────────────────────────────────────────────────────────

def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")


class Formatter(ABC):
    @abstractmethod
    def format(self, record: LogRecord) -> str: ...


class TextFormatter(Formatter):
    """Pattern fields: time, level, name, thread, correlation_id, message."""

    DEFAULT = "{time} {level:<8} {name} [{correlation_id}] {message}"

    def __init__(self, pattern: str = DEFAULT) -> None:
        self.pattern = pattern

    def format(self, record: LogRecord) -> str:
        text = self.pattern.format(
            time=_iso(record.created), level=record.level.name, name=record.logger_name,
            thread=record.thread_name, correlation_id=record.correlation_id or "-",
            message=record.message)
        if record.extra:
            text += " " + " ".join(f"{k}={v}" for k, v in record.extra.items())
        if record.exc_text:
            text += "\n" + record.exc_text.rstrip("\n")
        return text


class JsonFormatter(Formatter):
    """One JSON object per line (NDJSON). Context and extra fields are flattened in;
    the reserved keys are written last so user fields can't spoof them."""

    def format(self, record: LogRecord) -> str:
        doc: dict[str, Any] = {**record.context, **record.extra}
        doc.update({
            "ts": _iso(record.created),
            "level": record.level.name,
            "logger": record.logger_name,
            "message": record.message,
            "template": record.msg,  # stable across args: good for grouping/alerting
            "thread": record.thread_name,
        })
        if record.exc_text:
            doc["exc"] = record.exc_text
        return json.dumps(doc, default=str, ensure_ascii=False, sort_keys=True)


# ─── Filters (drop or transform) ─────────────────────────────────────────────

class Filter(ABC):
    @abstractmethod
    def filter(self, record: LogRecord) -> Optional[LogRecord]:
        """Return the record (possibly a modified copy) to keep it, or None to drop it."""


class NameFilter(Filter):
    """Keep only records from a logger subtree, e.g. 'app.payments'."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def filter(self, record: LogRecord) -> Optional[LogRecord]:
        name = record.logger_name
        keep = name == self.prefix or name.startswith(self.prefix + ".")
        return record if keep else None


class RedactionFilter(Filter):
    """Masks PII in the message and in string fields, and blanks sensitive keys.
    Runs at the source: once a secret reaches the pipeline, it's in N systems."""

    DEFAULT_PATTERNS = (
        re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),        # email
        re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),           # card-like digit runs
    )
    SENSITIVE_KEYS = frozenset({"password", "token", "authorization", "secret", "ssn", "card"})

    def __init__(self, patterns: Iterable[re.Pattern[str]] = DEFAULT_PATTERNS,
                 sensitive_keys: Iterable[str] = SENSITIVE_KEYS, mask: str = "[REDACTED]") -> None:
        self.patterns = tuple(patterns)
        self.sensitive_keys = frozenset(k.lower() for k in sensitive_keys)
        self.mask = mask

    def _scrub(self, text: str) -> str:
        for pattern in self.patterns:
            text = pattern.sub(self.mask, text)
        return text

    def _scrub_fields(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        out = {}
        for k, v in fields.items():
            if k.lower() in self.sensitive_keys:
                out[k] = self.mask
            elif isinstance(v, str):
                out[k] = self._scrub(v)
            else:
                out[k] = v
        return out

    def _scrub_arg(self, arg: Any) -> Any:
        if isinstance(arg, (int, float, Decimal)):
            return arg  # keep %d / %.2f working; digits alone are caught in the template
        return self._scrub(arg if isinstance(arg, str) else str(arg))

    def filter(self, record: LogRecord) -> Optional[LogRecord]:
        # Scrub the template and each argument separately, so the template stays a
        # stable grouping key and PII passed as an argument is still caught.
        return dataclasses.replace(
            record, msg=self._scrub(record.msg),
            args=tuple(self._scrub_arg(a) for a in record.args),
            extra=self._scrub_fields(record.extra), context=self._scrub_fields(record.context))


class SamplingFilter(Filter):
    """Keep `rate` of records below `keep_at_or_above`. Sampling is by correlation id
    when present, so a request's logs are kept or dropped *together*."""

    def __init__(self, rate: float, keep_at_or_above: Level = Level.WARNING,
                 rng: Optional[random.Random] = None) -> None:
        if not 0.0 <= rate <= 1.0:
            raise ValueError("rate must be within [0, 1]")
        self.rate = rate
        self.keep_at_or_above = keep_at_or_above
        self._threshold = int(rate * 10_000)
        self._rng = rng or random.Random()
        self._rng_lock = threading.Lock()

    def filter(self, record: LogRecord) -> Optional[LogRecord]:
        if record.level >= self.keep_at_or_above:
            return record
        cid = record.correlation_id
        if cid is not None:
            bucket = zlib.crc32(cid.encode()) % 10_000  # stable across processes, unlike hash()
        else:
            with self._rng_lock:
                bucket = self._rng.randrange(10_000)
        return record if bucket < self._threshold else None


# ─── Handlers (Strategy for the sink) ────────────────────────────────────────

class Handler(ABC):
    """Template method: level check -> filters -> format -> emit (under lock).

    The lock serialises emit() so concurrent lines never interleave. Formatting
    happens outside the lock: formatters are stateless and can run in parallel.
    """

    def __init__(self, level: Level = Level.NOTSET, formatter: Optional[Formatter] = None,
                 filters: Iterable[Filter] = ()) -> None:
        self.level = level
        self.formatter: Formatter = formatter or TextFormatter()
        self.filters: list[Filter] = list(filters)
        self._lock = threading.RLock()
        self._closed = False

    def add_filter(self, f: Filter) -> None:
        self.filters.append(f)

    def handle(self, record: LogRecord) -> None:
        if record.level < self.level:
            return
        try:
            kept = self._apply_filters(record)
            if kept is None:
                return
            text = self.formatter.format(kept)
            with self._lock:
                if not self._closed:
                    self.emit(text, kept)
        except Exception:
            self.handle_error(record)

    def _apply_filters(self, record: LogRecord) -> Optional[LogRecord]:
        current: Optional[LogRecord] = record
        for f in self.filters:
            current = f.filter(current)
            if current is None:
                return None
        return current

    @abstractmethod
    def emit(self, text: str, record: LogRecord) -> None:
        """Write one formatted record. Called with self._lock held."""

    def flush(self) -> None:
        pass

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self.flush()
            self._closed = True

    def handle_error(self, record: LogRecord) -> None:
        """Never raise into the application. Report to stderr and carry on."""
        try:
            sys.stderr.write(f"--- logging error in {type(self).__name__} "
                             f"(logger={record.logger_name}) ---\n")
            traceback.print_exc(file=sys.stderr)
        except Exception:
            pass


class StreamHandler(Handler):
    def __init__(self, stream: Optional[TextIO] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.stream = stream if stream is not None else sys.stderr

    def emit(self, text: str, record: LogRecord) -> None:
        self.stream.write(text + "\n")

    def flush(self) -> None:
        with self._lock:
            if hasattr(self.stream, "flush"):
                self.stream.flush()


class ConsoleHandler(StreamHandler):
    """stderr by default: stdout is often the program's real output."""


class FileHandler(StreamHandler):
    """Appends to a file. `flush_every_record=True` trades throughput for durability
    of the last lines before a crash; put an AsyncHandler in front to hide the cost."""

    def __init__(self, path: str, flush_every_record: bool = False, **kwargs: Any) -> None:
        super().__init__(stream=open(path, "a", encoding="utf-8"), **kwargs)
        self.path = path
        self.flush_every_record = flush_every_record

    def emit(self, text: str, record: LogRecord) -> None:
        self.stream.write(text + "\n")
        if self.flush_every_record:
            self.stream.flush()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            super().close()
            self.stream.close()


class InMemoryHandler(Handler):
    """Bounded ring buffer: for tests, and for 'dump the last N lines on crash'."""

    def __init__(self, capacity: int = 10_000, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._lines: deque[str] = deque(maxlen=capacity)
        self._records: deque[LogRecord] = deque(maxlen=capacity)

    def emit(self, text: str, record: LogRecord) -> None:
        self._lines.append(text)
        self._records.append(record)

    @property
    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    @property
    def records(self) -> list[LogRecord]:
        with self._lock:
            return list(self._records)


class OverflowPolicy(Enum):
    DROP = "DROP"    # never block the caller; count and discard the new record
    BLOCK = "BLOCK"  # back-pressure the caller (optionally up to a timeout, then drop)


_STOP = object()


class AsyncHandler(Handler):
    """Decouples callers from slow sinks: handle() enqueues, a worker thread calls
    the target handler. Level and filters of THIS handler run in the caller (cheap
    rejection before enqueue); the target's formatter/filters run on the worker.

    Overflow when the queue is full:
      DROP  -> discard the incoming record, increment `dropped`.
      BLOCK -> wait for space; with `block_timeout`, give up and drop after it.

    Records are immutable and carry their context, so nothing is lost by
    formatting them on another thread.
    """

    def __init__(self, target: Handler, capacity: int = 10_000,
                 overflow: OverflowPolicy = OverflowPolicy.DROP,
                 block_timeout: Optional[float] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.target = target
        self.overflow = overflow
        self.block_timeout = block_timeout
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=capacity)
        self._counter_lock = threading.Lock()
        self._dropped = 0
        self._worker = threading.Thread(target=self._run, name=f"log-async-{id(self):x}",
                                        daemon=True)
        self._worker.start()

    @property
    def dropped(self) -> int:
        with self._counter_lock:
            return self._dropped

    def _count_drop(self) -> None:
        with self._counter_lock:
            self._dropped += 1

    def handle(self, record: LogRecord) -> None:
        if record.level < self.level:
            return
        if self._closed:
            self._count_drop()
            return
        try:
            kept = self._apply_filters(record)
        except Exception:
            self.handle_error(record)
            return
        if kept is None:
            return
        try:
            if self.overflow is OverflowPolicy.DROP:
                self._queue.put_nowait(kept)
            else:
                self._queue.put(kept, timeout=self.block_timeout)
        except queue.Full:
            self._count_drop()

    def emit(self, text: str, record: LogRecord) -> None:  # pragma: no cover - unused
        raise NotImplementedError("AsyncHandler enqueues records; see handle()")

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                self.target.handle(item)  # target swallows its own errors
            finally:
                self._queue.task_done()

    def flush(self) -> None:
        """Block until everything enqueued so far has been handed to the target."""
        if self._worker.is_alive():
            self._queue.join()
        self.target.flush()

    def close(self, timeout: Optional[float] = 5.0) -> None:
        """Stop accepting, drain the queue, stop the worker, close the target."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        # Blocking put: the stop marker must get in even under DROP policy.
        self._queue.put(_STOP)
        self._worker.join(timeout)
        # A producer that passed the _closed check just before we set it may have
        # enqueued behind _STOP; account for it rather than losing it silently.
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            self._queue.task_done()
            self._count_drop()
        self.target.close()


# ─── Loggers & hierarchy ─────────────────────────────────────────────────────

class Logger:
    """Create via LogManager.get_logger(); don't instantiate directly."""

    def __init__(self, name: str, parent: Optional[Logger], manager: LogManager) -> None:
        self.name = name
        self.parent = parent
        self.propagate = True
        self._manager = manager
        self._level: Optional[Level] = None  # None = inherit
        self._handlers: tuple[Handler, ...] = ()  # copy-on-write: lock-free reads
        self._cache: tuple[int, Level] = (-1, Level.NOTSET)

    # -- configuration -------------------------------------------------------
    @property
    def level(self) -> Optional[Level]:
        return self._level

    def set_level(self, level: Optional[Level]) -> None:
        self._manager._set_level(self, level)

    def add_handler(self, handler: Handler) -> None:
        with self._manager._lock:
            if handler not in self._handlers:
                self._handlers = self._handlers + (handler,)

    def remove_handler(self, handler: Handler) -> None:
        with self._manager._lock:
            self._handlers = tuple(h for h in self._handlers if h is not handler)

    @property
    def handlers(self) -> tuple[Handler, ...]:
        return self._handlers

    # -- level inheritance ---------------------------------------------------
    def effective_level(self) -> Level:
        """Nearest explicitly-set level walking up to root. Cached per config
        generation: any set_level anywhere bumps the generation, invalidating all."""
        gen = self._manager._generation
        cached_gen, cached = self._cache
        if cached_gen == gen:
            return cached
        node: Optional[Logger] = self
        level = Level.NOTSET
        while node is not None:
            if node._level is not None:
                level = node._level
                break
            node = node.parent
        self._cache = (gen, level)  # tuple assignment is atomic; a racing reader sees old or new
        return level

    def is_enabled_for(self, level: Level) -> bool:
        return level >= self.effective_level()

    # -- logging -------------------------------------------------------------
    def log(self, level: Level, msg: str, /, *args: Any, exc_info: bool = False,
            **extra: Any) -> None:
        """`level`/`msg` are positional-only so extra fields may use those names."""
        if not self.is_enabled_for(level):
            return  # fast path: no record, no formatting, no context copy
        exc_text = traceback.format_exc() if exc_info else None
        record = LogRecord(self.name, level, msg, args, self._manager.clock(),
                           threading.current_thread().name, dict(_context.get()),
                           extra, exc_text)
        self._dispatch(record)

    def _dispatch(self, record: LogRecord) -> None:
        """Chain of Responsibility: offer to each logger's handlers walking up the
        tree until propagate=False. Ancestor *logger* levels are NOT re-checked
        (same as log4j/Python); ancestor *handler* levels are."""
        node: Optional[Logger] = self
        while node is not None:
            for handler in node._handlers:
                handler.handle(record)
            if not node.propagate:
                break
            node = node.parent

    def debug(self, msg: str, /, *args: Any, **extra: Any) -> None:
        self.log(Level.DEBUG, msg, *args, **extra)

    def info(self, msg: str, /, *args: Any, **extra: Any) -> None:
        self.log(Level.INFO, msg, *args, **extra)

    def warning(self, msg: str, /, *args: Any, **extra: Any) -> None:
        self.log(Level.WARNING, msg, *args, **extra)

    def error(self, msg: str, /, *args: Any, **extra: Any) -> None:
        self.log(Level.ERROR, msg, *args, **extra)

    def critical(self, msg: str, /, *args: Any, **extra: Any) -> None:
        self.log(Level.CRITICAL, msg, *args, **extra)

    def exception(self, msg: str, /, *args: Any, **extra: Any) -> None:
        """Call from an except block: logs at ERROR with the traceback."""
        self.log(Level.ERROR, msg, *args, exc_info=True, **extra)

    def __repr__(self) -> str:
        return f"Logger({self.name!r}, level={self.effective_level().name})"


class LogManager:
    """Registry of loggers. get_logger('a.b.c') creates 'a' and 'a.b' too, so every
    logger's parent is always its real nearest ancestor (no placeholders)."""

    ROOT = "root"

    def __init__(self, clock: Callable[[], float] = time.time,
                 root_level: Level = Level.WARNING) -> None:
        self.clock = clock
        self._lock = threading.RLock()
        self._generation = 0
        self.root = Logger(self.ROOT, None, self)
        self.root._level = root_level
        self._loggers: dict[str, Logger] = {self.ROOT: self.root}
        self._shut_down = False

    def get_logger(self, name: str = ROOT) -> Logger:
        if not name or name == self.ROOT:
            return self.root
        existing = self._loggers.get(name)  # lock-free fast path; dict reads are atomic
        if existing is not None:
            return existing
        with self._lock:
            parent = self.root
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                prefix = ".".join(parts[:i])
                node = self._loggers.get(prefix)
                if node is None:
                    node = Logger(prefix, parent, self)
                    self._loggers[prefix] = node
                parent = node
            return parent

    def _set_level(self, logger: Logger, level: Optional[Level]) -> None:
        if logger is self.root and level is None:
            raise ValueError("root logger must have a level")
        with self._lock:
            logger._level = level
            self._generation += 1

    def all_handlers(self) -> list[Handler]:
        with self._lock:
            seen: dict[int, Handler] = {}
            for lg in self._loggers.values():
                for h in lg.handlers:
                    seen.setdefault(id(h), h)
            return list(seen.values())

    def shutdown(self) -> None:
        """Flush and close every handler once. Async handlers first, so they drain
        into targets that are still open."""
        with self._lock:
            if self._shut_down:
                return
            self._shut_down = True
            handlers = self.all_handlers()
        handlers.sort(key=lambda h: not isinstance(h, AsyncHandler))
        for h in handlers:
            try:
                h.close()
            except Exception:
                pass


# Process-wide default manager, closed at interpreter exit.
_default = LogManager()
atexit.register(_default.shutdown)


def get_logger(name: str = LogManager.ROOT) -> Logger:
    return _default.get_logger(name)


def shutdown() -> None:
    _default.shutdown()


# ─── Demo ────────────────────────────────────────────────────────────────────

def main() -> None:
    import asyncio

    ticks = iter(range(1_000_000))
    manager = LogManager(clock=lambda: 1_767_225_600 + next(ticks) / 1000,  # 2026-01-01Z
                         root_level=Level.INFO)
    root = manager.get_logger()
    console = ConsoleHandler(stream=sys.stdout, filters=[RedactionFilter()])
    root.add_handler(console)

    json_sink = InMemoryHandler(formatter=JsonFormatter())
    payments = manager.get_logger("app.payments")
    payments.add_handler(AsyncHandler(json_sink, capacity=100, filters=[RedactionFilter()]))

    db = manager.get_logger("app.db")
    print("== level inheritance ==")
    db.debug("not shown: app.db inherits INFO from root")
    manager.get_logger("app").set_level(Level.DEBUG)
    db.debug("shown: app is now DEBUG, so app.db is DEBUG too")

    print("\n== correlation ids across concurrent asyncio tasks ==")

    async def handle_request(cid: str, user: str) -> None:
        with log_context(correlation_id=cid, user=user):
            payments.info("charging %s for user %s", "499.00", user)
            await asyncio.sleep(0)  # interleave with the other request
            payments.info("charged; receipt sent to %s", f"{user}@example.com")

    async def serve() -> None:
        await asyncio.gather(handle_request("req-1", "asha"), handle_request("req-2", "ravi"))

    asyncio.run(serve())

    print("\n== exception ==")
    try:
        1 / 0
    except ZeroDivisionError:
        manager.get_logger("app.jobs").exception("nightly job failed", job="reindex")

    manager.shutdown()  # drains the async queue into json_sink
    print("\n== structured JSON from the async handler ==")
    for line in json_sink.lines:
        print(line)


if __name__ == "__main__":
    main()
```
<!-- /source -->
