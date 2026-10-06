import threading
import time
import unittest

from pub_sub_system import (
    CallbackSubscriber,
    DeadLetterReason,
    DedupingSubscriber,
    MessageBroker,
    MessagePriority,
    RetryPolicy,
    TopicNotFound,
)


class Recorder:
    """Subscriber callback that records payloads and detects concurrent calls."""

    def __init__(self, fail_times=0, delay=0.0):
        self.payloads = []
        self.fail_times = fail_times
        self.calls = 0
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def __call__(self, message):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls += 1
            fail = self.calls <= self.fail_times
        try:
            if self.delay:
                time.sleep(self.delay)
            if fail:
                raise RuntimeError("boom")
            with self._lock:
                self.payloads.append(message.payload)
        finally:
            with self._lock:
                self.active -= 1


def sync_broker(**kw):
    sleeps = []
    broker = MessageBroker(sleep=sleeps.append, **kw)
    broker.create_topic("t")
    return broker, sleeps


class SynchronousModeTests(unittest.TestCase):
    def test_fan_out_to_every_subscriber(self):
        broker, _ = sync_broker()
        a, b = Recorder(), Recorder()
        broker.subscribe("t", CallbackSubscriber("a", a))
        broker.subscribe("t", CallbackSubscriber("b", b))
        broker.publish("t", 1)
        broker.publish("t", 2)
        self.assertEqual(broker.run_until_idle(), 4)
        self.assertEqual(a.payloads, [1, 2])
        self.assertEqual(b.payloads, [1, 2])

    def test_priority_first_then_fifo(self):
        broker, _ = sync_broker()
        r = Recorder()
        broker.subscribe("t", CallbackSubscriber("r", r))
        broker.publish("t", "n1")
        broker.publish("t", "low", MessagePriority.LOW)
        broker.publish("t", "h1", MessagePriority.HIGH)
        broker.publish("t", "n2")
        broker.publish("t", "h2", MessagePriority.HIGH)
        broker.publish("t", "crit", MessagePriority.CRITICAL)
        broker.run_until_idle()
        self.assertEqual(r.payloads, ["crit", "h1", "h2", "n1", "n2", "low"])

    def test_predicate_filters_per_subscription(self):
        broker, _ = sync_broker()
        r = Recorder()
        broker.subscribe("t", CallbackSubscriber("r", r), predicate=lambda m: m.payload % 2 == 0)
        for i in range(6):
            broker.publish("t", i)
        broker.run_until_idle()
        self.assertEqual(r.payloads, [0, 2, 4])

    def test_retry_with_exponential_backoff_then_success(self):
        broker, sleeps = sync_broker()
        r = Recorder(fail_times=2)
        broker.subscribe("t", CallbackSubscriber("r", r),
                         retry=RetryPolicy(max_attempts=3, base_delay=0.1, multiplier=2))
        broker.publish("t", "x")
        broker.run_until_idle()
        self.assertEqual(r.payloads, ["x"])
        self.assertEqual(sleeps, [0.1, 0.2])
        self.assertEqual(broker.dead_letters(), [])

    def test_retries_exhausted_goes_to_dlq_and_later_messages_still_flow(self):
        broker, _ = sync_broker()
        r = Recorder(fail_times=2)
        broker.subscribe("t", CallbackSubscriber("r", r), retry=RetryPolicy(max_attempts=2))
        broker.publish("t", "poison")
        broker.publish("t", "ok")
        broker.run_until_idle()
        self.assertEqual(r.payloads, ["ok"])
        [dl] = broker.dead_letters()
        self.assertEqual(dl.reason, DeadLetterReason.RETRIES_EXHAUSTED)
        self.assertEqual(dl.message.payload, "poison")
        self.assertEqual(dl.subscription_id, "t/r")

    def test_full_queue_dead_letters_instead_of_blocking(self):
        broker, _ = sync_broker(max_queue=2)
        r = Recorder()
        broker.subscribe("t", CallbackSubscriber("r", r))
        for i in range(4):
            broker.publish("t", i)
        broker.run_until_idle()
        self.assertEqual(r.payloads, [0, 1])
        self.assertEqual([d.message.payload for d in broker.dead_letters()], [2, 3])
        self.assertTrue(all(d.reason is DeadLetterReason.OVERFLOW for d in broker.dead_letters()))

    def test_unknown_topic_and_duplicate_subscription_are_errors(self):
        broker, _ = sync_broker()
        with self.assertRaises(TopicNotFound):
            broker.publish("nope", 1)
        with self.assertRaises(TopicNotFound):
            broker.subscribe("nope", CallbackSubscriber("a", Recorder()))
        broker.subscribe("t", CallbackSubscriber("a", Recorder()))
        with self.assertRaises(ValueError):
            broker.subscribe("t", CallbackSubscriber("a", Recorder()))

    def test_unsubscribe_discards_pending_and_stops_delivery(self):
        broker, _ = sync_broker()
        r = Recorder()
        broker.subscribe("t", CallbackSubscriber("r", r))
        broker.publish("t", 1)
        broker.unsubscribe("t", "r")
        broker.publish("t", 2)
        broker.run_until_idle()
        self.assertEqual(r.payloads, [])

    def test_message_is_immutable(self):
        broker, _ = sync_broker()
        m = broker.publish("t", 1, headers={"k": "v"})
        with self.assertRaises(Exception):
            m.topic = "other"
        with self.assertRaises(TypeError):
            m.headers["k"] = "changed"

    def test_deduping_subscriber_processes_redelivery_once(self):
        broker, _ = sync_broker()
        r = Recorder()
        sub = broker.subscribe("t", DedupingSubscriber(CallbackSubscriber("r", r)))
        m = broker.publish("t", "x")
        sub.offer(m)                      # redelivery of the same message id
        broker.run_until_idle()
        self.assertEqual(r.payloads, ["x"])

    def test_deduping_subscriber_does_not_mark_failed_attempts_as_seen(self):
        broker, _ = sync_broker()
        r = Recorder(fail_times=1)
        broker.subscribe("t", DedupingSubscriber(CallbackSubscriber("r", r)),
                         retry=RetryPolicy(max_attempts=2))
        broker.publish("t", "x")
        broker.run_until_idle()
        self.assertEqual(r.payloads, ["x"])


class ThreadedModeTests(unittest.TestCase):
    def setUp(self):
        self.broker = MessageBroker(default_retry=RetryPolicy(max_attempts=3, base_delay=0.001))
        self.broker.create_topic("t")

    def tearDown(self):
        self.broker.close()

    def test_slow_subscriber_does_not_delay_others(self):
        gate = threading.Event()
        fast = Recorder()
        self.broker.subscribe("t", CallbackSubscriber("slow", lambda m: gate.wait(5)))
        self.broker.subscribe("t", CallbackSubscriber("fast", fast))
        self.broker.start()
        for i in range(20):
            self.broker.publish("t", i)
        deadline = time.monotonic() + 2
        while len(fast.payloads) < 20 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(fast.payloads, list(range(20)))
        gate.set()

    def test_concurrent_publishers_each_subscriber_in_order_never_concurrent(self):
        recs = [Recorder() for _ in range(3)]
        for i, r in enumerate(recs):
            self.broker.subscribe("t", CallbackSubscriber(f"s{i}", r))
        self.broker.start()
        barrier = threading.Barrier(4)

        def producer(pid):
            barrier.wait()
            for n in range(200):
                self.broker.publish("t", (pid, n))

        threads = [threading.Thread(target=producer, args=(p,)) for p in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(self.broker.wait_idle(5))
        for r in recs:
            self.assertEqual(len(r.payloads), 800)
            self.assertEqual(r.max_active, 1)            # one dispatcher per subscription
            for pid in range(4):                         # per-producer order preserved
                seq = [n for p, n in r.payloads if p == pid]
                self.assertEqual(seq, list(range(200)))

    def test_subscribe_unsubscribe_while_publishing(self):
        self.broker.start()
        stop = threading.Event()
        errors = []

        def churn():
            i = 0
            while not stop.is_set():
                try:
                    self.broker.subscribe("t", CallbackSubscriber(f"c{i}", Recorder()))
                    self.broker.unsubscribe("t", f"c{i}")
                except Exception as e:   # pragma: no cover - surfaced below
                    errors.append(e)
                i += 1

        t = threading.Thread(target=churn)
        t.start()
        try:
            for n in range(500):
                self.broker.publish("t", n)
        finally:
            stop.set()
            t.join()
        self.assertEqual(errors, [])

    def test_subscriber_can_unsubscribe_itself_without_deadlock(self):
        done = threading.Event()

        def cb(m):
            self.broker.unsubscribe("t", "self")
            done.set()

        self.broker.subscribe("t", CallbackSubscriber("self", cb))
        self.broker.start()
        self.broker.publish("t", 1)
        self.assertTrue(done.wait(2))

    def test_close_interrupts_backoff(self):
        broker = MessageBroker(default_retry=RetryPolicy(max_attempts=5, base_delay=10))
        broker.create_topic("t")
        started = threading.Event()

        def always_fail(m):
            started.set()
            raise RuntimeError

        broker.subscribe("t", CallbackSubscriber("f", always_fail))
        broker.start()
        broker.publish("t", 1)
        started.wait(2)
        t0 = time.monotonic()
        broker.close()
        self.assertLess(time.monotonic() - t0, 1.0)


if __name__ == "__main__":
    unittest.main()
