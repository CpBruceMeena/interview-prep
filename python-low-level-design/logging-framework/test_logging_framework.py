import asyncio
import io
import json
import os
import random
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr

from logging_framework import (
    AsyncHandler, ConsoleHandler, FileHandler, Formatter, Handler, InMemoryHandler,
    JsonFormatter, Level, LogManager, NameFilter, OverflowPolicy, RedactionFilter,
    SamplingFilter, TextFormatter, current_context, log_context,
)


def manager(root_level=Level.DEBUG):
    return LogManager(clock=lambda: 0.0, root_level=root_level)


class GatedHandler(Handler):
    """Target whose emit blocks until `gate` is set; signals `started` on first emit."""

    def __init__(self):
        super().__init__(formatter=TextFormatter("{message}"))
        self.gate = threading.Event()
        self.started = threading.Event()
        self.lines = []

    def emit(self, text, record):
        self.started.set()
        self.gate.wait(5)
        self.lines.append(text)


class HierarchyTests(unittest.TestCase):
    def test_get_logger_builds_ancestors_and_is_cached(self):
        m = manager()
        c = m.get_logger("a.b.c")
        self.assertIs(c.parent, m.get_logger("a.b"))
        self.assertIs(c.parent.parent, m.get_logger("a"))
        self.assertIs(m.get_logger("a").parent, m.root)
        self.assertIs(m.get_logger("a.b.c"), c)

    def test_level_inheritance_and_cache_invalidation(self):
        m = manager(Level.WARNING)
        c = m.get_logger("a.b.c")
        self.assertEqual(c.effective_level(), Level.WARNING)
        m.get_logger("a").set_level(Level.DEBUG)
        self.assertEqual(c.effective_level(), Level.DEBUG)
        m.get_logger("a.b").set_level(Level.ERROR)
        self.assertEqual(c.effective_level(), Level.ERROR)
        m.get_logger("a.b").set_level(None)  # back to inheriting
        self.assertEqual(c.effective_level(), Level.DEBUG)
        with self.assertRaises(ValueError):
            m.root.set_level(None)

    def test_disabled_level_skips_formatting(self):
        m = manager(Level.INFO)
        calls = []

        class Spy:
            def __str__(self):
                calls.append(1)
                return "spy"

        sink = InMemoryHandler()
        m.root.add_handler(sink)
        m.get_logger("x").debug("value %s", Spy())
        self.assertEqual(calls, [])
        self.assertEqual(sink.lines, [])


class PropagationTests(unittest.TestCase):
    def test_record_reaches_every_ancestor_handler(self):
        m = manager()
        root_sink, app_sink, db_sink = InMemoryHandler(), InMemoryHandler(), InMemoryHandler()
        m.root.add_handler(root_sink)
        m.get_logger("app").add_handler(app_sink)
        m.get_logger("app.db").add_handler(db_sink)
        m.get_logger("app.db.pool").info("hi")
        self.assertEqual(len(root_sink.lines) + len(app_sink.lines) + len(db_sink.lines), 3)

    def test_propagate_false_stops_chain(self):
        m = manager()
        root_sink, app_sink = InMemoryHandler(), InMemoryHandler()
        m.root.add_handler(root_sink)
        app = m.get_logger("app")
        app.add_handler(app_sink)
        app.propagate = False
        m.get_logger("app.db").info("hi")
        self.assertEqual(len(app_sink.lines), 1)
        self.assertEqual(root_sink.lines, [])

    def test_ancestor_logger_level_not_rechecked_but_handler_level_is(self):
        m = manager(Level.ERROR)  # root logger at ERROR
        root_sink = InMemoryHandler()
        strict = InMemoryHandler(level=Level.WARNING)
        m.root.add_handler(root_sink)
        m.root.add_handler(strict)
        child = m.get_logger("svc")
        child.set_level(Level.DEBUG)
        child.info("info from child")
        self.assertEqual(len(root_sink.lines), 1)  # root's own level doesn't block
        self.assertEqual(strict.lines, [])         # but handler level does


class FormatterTests(unittest.TestCase):
    def test_text_format_includes_context_extra_and_exception(self):
        m = manager()
        sink = InMemoryHandler()
        m.root.add_handler(sink)
        try:
            raise KeyError("k")
        except KeyError:
            with log_context(correlation_id="c-1"):
                m.get_logger("app").exception("failed %d", 3, order="o-9")
        line = sink.lines[0]
        self.assertTrue(line.startswith("1970-01-01T00:00:00.000+00:00 ERROR    app [c-1] failed 3 order=o-9"))
        self.assertIn("KeyError", line)

    def test_json_is_valid_and_reserved_keys_win(self):
        m = manager()
        sink = InMemoryHandler(formatter=JsonFormatter())
        m.root.add_handler(sink)
        with log_context(correlation_id="c-2", tenant="t1"):
            m.get_logger("api").info("user %s", "u1", level="spoofed", latency_ms=12)
        doc = json.loads(sink.lines[0])
        self.assertEqual(doc["level"], "INFO")
        self.assertEqual(doc["message"], "user u1")
        self.assertEqual(doc["template"], "user %s")
        self.assertEqual(doc["correlation_id"], "c-2")
        self.assertEqual(doc["tenant"], "t1")
        self.assertEqual(doc["latency_ms"], 12)

    def test_bad_format_args_do_not_raise(self):
        m = manager()
        sink = InMemoryHandler()
        m.root.add_handler(sink)
        m.root.info("needs two %s %s", "only-one")
        self.assertIn("needs two %s %s ('only-one',)", sink.lines[0])


class FilterTests(unittest.TestCase):
    def test_name_filter(self):
        m = manager()
        sink = InMemoryHandler(filters=[NameFilter("app.pay")])
        m.root.add_handler(sink)
        m.get_logger("app.pay.card").info("a")
        m.get_logger("app.payroll").info("b")  # prefix match must respect dots
        m.get_logger("app.pay").info("c")
        self.assertEqual([r.msg for r in sink.records], ["a", "c"])

    def test_redaction_of_message_args_and_fields(self):
        m = manager()
        sink = InMemoryHandler(formatter=JsonFormatter(), filters=[RedactionFilter()])
        m.root.add_handler(sink)
        with log_context(correlation_id="c", email="a@b.com"):
            m.root.info("mail %s card 4111 1111 1111 1111 amount %.2f", "x.y@corp.io", 12.5,
                        password="hunter2", note="call bob@x.org")
        doc = json.loads(sink.lines[0])
        self.assertEqual(doc["message"], "mail [REDACTED] card [REDACTED] amount 12.50")
        self.assertEqual(doc["password"], "[REDACTED]")
        self.assertEqual(doc["note"], "call [REDACTED]")
        self.assertEqual(doc["email"], "[REDACTED]")
        self.assertNotIn("hunter2", sink.lines[0])

    def test_sampling_keeps_whole_requests_and_all_warnings(self):
        f = SamplingFilter(rate=0.3, rng=random.Random(7))
        m = manager()
        sink = InMemoryHandler(filters=[f])
        m.root.add_handler(sink)
        for i in range(200):
            with log_context(correlation_id=f"req-{i}"):
                m.root.info("a")
                m.root.info("b")
                m.root.warning("w")
        per_request = {}
        for r in sink.records:
            per_request.setdefault(r.correlation_id, []).append(r.msg)
        self.assertEqual(len(per_request), 200)  # every request kept its warning
        kept = [v for v in per_request.values() if v != ["w"]]
        for msgs in kept:
            self.assertEqual(msgs, ["a", "b", "w"])  # all-or-nothing per request
        self.assertTrue(30 <= len(kept) <= 90, len(kept))
        with self.assertRaises(ValueError):
            SamplingFilter(1.5)


class ContextTests(unittest.TestCase):
    def test_nested_scopes_restore(self):
        with log_context(correlation_id="outer", user="u"):
            with log_context(correlation_id="inner"):
                self.assertEqual(dict(current_context()), {"correlation_id": "inner", "user": "u"})
            self.assertEqual(current_context()["correlation_id"], "outer")
        self.assertEqual(dict(current_context()), {})

    def test_threads_do_not_share_context(self):
        m = manager()
        sink = InMemoryHandler()
        m.root.add_handler(sink)
        barrier = threading.Barrier(8)

        def request(i):
            with log_context(correlation_id=f"t{i}"):
                barrier.wait()
                for _ in range(50):
                    m.root.info("tick %d", i)

        threads = [threading.Thread(target=request, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(sink.records), 400)
        for r in sink.records:
            self.assertEqual(r.correlation_id, f"t{r.args[0]}")

    def test_asyncio_tasks_do_not_share_context(self):
        m = manager()
        sink = InMemoryHandler()
        m.root.add_handler(sink)

        async def request(cid):
            with log_context(correlation_id=cid):
                for _ in range(3):
                    m.root.info(cid)
                    await asyncio.sleep(0)

        async def run():
            await asyncio.gather(*(request(f"r{i}") for i in range(5)))

        asyncio.run(run())
        self.assertEqual(len(sink.records), 15)
        self.assertTrue(all(r.correlation_id == r.msg for r in sink.records))


class HandlerTests(unittest.TestCase):
    def test_console_handler_writes_to_stream(self):
        m = manager()
        buf = io.StringIO()
        m.root.add_handler(ConsoleHandler(stream=buf, formatter=TextFormatter("{level}:{message}")))
        m.root.warning("disk %d%%", 91)
        self.assertEqual(buf.getvalue(), "WARNING:disk 91%\n")

    def test_failing_formatter_never_raises_into_app(self):
        class Broken(Formatter):
            def format(self, record):
                raise RuntimeError("boom")

        m = manager()
        good = InMemoryHandler()
        m.root.add_handler(InMemoryHandler(formatter=Broken()))
        m.root.add_handler(good)
        err = io.StringIO()
        with redirect_stderr(err):
            m.root.error("still fine")
        self.assertEqual(len(good.lines), 1)
        self.assertIn("logging error", err.getvalue())

    def test_file_handler_concurrent_lines_never_interleave(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "app.log")
            m = manager()
            fh = FileHandler(path, formatter=TextFormatter("{thread}|{message}"))
            m.root.add_handler(fh)

            def worker(i):
                for j in range(300):
                    m.root.info("%s", f"w{i}-{j}-" + "x" * 200)

            threads = [threading.Thread(target=worker, args=(i,), name=f"T{i}") for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            m.shutdown()
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            self.assertEqual(len(lines), 2400)
            for line in lines:
                thread, msg = line.split("|")
                self.assertTrue(msg.startswith(f"w{thread[1:]}-"))
                self.assertTrue(msg.endswith("x" * 200))

    def test_in_memory_is_bounded(self):
        m = manager()
        sink = InMemoryHandler(capacity=3)
        m.root.add_handler(sink)
        for i in range(10):
            m.root.info("%d", i)
        self.assertEqual(sink.lines[-1].split()[-1], "9")
        self.assertEqual(len(sink.lines), 3)


class AsyncHandlerTests(unittest.TestCase):
    def _fill(self, target, handler, m, n_extra):
        m.root.add_handler(handler)
        m.root.info("first")          # taken by the worker, which then blocks in emit
        self.assertTrue(target.started.wait(2))
        for i in range(handler._queue.maxsize):
            m.root.info("q%d", i)     # fills the queue exactly
        for i in range(n_extra):
            m.root.info("x%d", i)

    def test_drop_policy_never_blocks_and_counts(self):
        m, target = manager(), GatedHandler()
        h = AsyncHandler(target, capacity=5, overflow=OverflowPolicy.DROP)
        start = time.monotonic()
        self._fill(target, h, m, n_extra=7)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertEqual(h.dropped, 7)
        target.gate.set()
        m.shutdown()
        self.assertEqual(target.lines, ["first"] + [f"q{i}" for i in range(5)])

    def test_block_policy_applies_back_pressure(self):
        m, target = manager(), GatedHandler()
        h = AsyncHandler(target, capacity=2, overflow=OverflowPolicy.BLOCK)
        self._fill(target, h, m, n_extra=0)
        done = threading.Event()

        def producer():
            m.root.info("blocked")
            done.set()

        t = threading.Thread(target=producer)
        t.start()
        self.assertFalse(done.wait(0.1))  # caller is held back by the full queue
        target.gate.set()
        self.assertTrue(done.wait(2))
        t.join()
        m.shutdown()
        self.assertEqual(h.dropped, 0)
        self.assertEqual(target.lines[-1], "blocked")

    def test_block_with_timeout_then_drops(self):
        m, target = manager(), GatedHandler()
        h = AsyncHandler(target, capacity=1, overflow=OverflowPolicy.BLOCK, block_timeout=0.05)
        start = time.monotonic()
        self._fill(target, h, m, n_extra=2)
        self.assertGreaterEqual(time.monotonic() - start, 0.09)
        self.assertEqual(h.dropped, 2)
        target.gate.set()
        m.shutdown()

    def test_flush_and_shutdown_drain_everything(self):
        m = manager()
        sink = InMemoryHandler()
        h = AsyncHandler(sink, capacity=10_000)
        m.root.add_handler(h)

        def worker(i):
            for j in range(250):
                m.root.info("%d-%d", i, j)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        h.flush()
        self.assertEqual(len(sink.records), 2000)
        m.root.info("last")
        m.shutdown()
        self.assertEqual(sink.records[-1].msg, "last")
        self.assertFalse(h._worker.is_alive())
        m.root.info("after shutdown")      # must not raise or hang
        self.assertEqual(h.dropped, 1)

    def test_context_is_captured_in_caller_not_worker(self):
        m = manager()
        sink = InMemoryHandler(formatter=JsonFormatter())
        m.root.add_handler(AsyncHandler(sink))
        with log_context(correlation_id="caller"):
            m.root.info("x")
        m.shutdown()
        self.assertEqual(json.loads(sink.lines[0])["correlation_id"], "caller")

    def test_shutdown_closes_async_before_shared_target(self):
        m = manager()
        sink = InMemoryHandler()
        m.root.add_handler(sink)                    # attached directly ...
        m.get_logger("a").add_handler(AsyncHandler(sink))  # ... and behind an async wrapper
        for _ in range(100):
            m.get_logger("a").info("x")
        m.shutdown()
        self.assertEqual(len(sink.lines), 200)      # nothing lost to a closed target


if __name__ == "__main__":
    unittest.main()
