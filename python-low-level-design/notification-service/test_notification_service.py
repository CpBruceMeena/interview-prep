import random
import threading
import unittest
from datetime import datetime, time as dtime, timedelta, timezone

from notification_service import (
    Category, Channel, DeliveryStatus, FakeSender, Limit, ManualClock, NotificationRequest,
    NotificationService, PermanentSendError, Priority, QuietHours, RateLimiter, RetryPolicy,
    TemplateStore, TransientSendError, UserPreferences, ValidationError,
)

UTC = timezone.utc
T0 = datetime(2026, 1, 5, 12, 0, tzinfo=UTC).timestamp()     # noon UTC


def templates() -> TemplateStore:
    t = TemplateStore()
    for ch in Channel:
        t.register("hello", ch, "hi $name")
    t.register("otp", Channel.SMS, "code $code")
    return t


def req(key, channels=(Channel.EMAIL,), priority=Priority.NORMAL, user="u1", name="A",
        category=Category.TRANSACTIONAL, send_at=None, template="hello"):
    params = {"name": name} if template == "hello" else {"code": name}
    return NotificationRequest(key, user, template, params, tuple(channels), priority, category, send_at)


def make(limiter=None, retry=None, quiet=None, **prefs):
    clock = ManualClock(T0)
    senders = {ch: FakeSender(ch.value) for ch in Channel}
    svc = NotificationService(senders, templates(), rate_limiter=limiter,
                              retry=retry or RetryPolicy(max_attempts=3, base_s=1, rng=random.Random(1)),
                              clock=clock)
    contacts = {Channel.EMAIL: "a@x.com", Channel.SMS: "+1555", Channel.PUSH: "tok"}
    svc.upsert_user(UserPreferences("u1", contacts, quiet_hours=quiet, **prefs))
    return svc, senders, clock


class SubmitTest(unittest.TestCase):
    def test_fans_out_one_delivery_per_channel(self):
        svc, senders, _ = make()
        n = svc.submit(req("k", (Channel.EMAIL, Channel.SMS, Channel.EMAIL)))
        self.assertEqual([d.channel for d in n.deliveries], [Channel.EMAIL, Channel.SMS])
        svc.run_until_idle()
        self.assertEqual(senders[Channel.EMAIL].sent[0][1:], ("a@x.com", "hi A"))
        self.assertEqual(len(senders[Channel.SMS].sent), 1)

    def test_idempotency_key_returns_same_notification(self):
        svc, senders, _ = make()
        n1 = svc.submit(req("k"))
        self.assertIs(svc.submit(req("k")), n1)
        svc.run_until_idle()
        self.assertEqual(len(senders[Channel.EMAIL].sent), 1)

    def test_idempotency_key_expires(self):
        svc, _, clock = make()
        n1 = svc.submit(req("k"))
        clock.advance(24 * 3600 + 1)
        self.assertIsNot(svc.submit(req("k", name="B")), n1)

    def test_content_dedup_window(self):
        svc, senders, clock = make()
        svc.submit(req("k1"))
        dup = svc.submit(req("k2"))                       # same user/template/params, new key
        self.assertIs(dup.deliveries[0].status, DeliveryStatus.SUPPRESSED)
        clock.advance(601)
        fresh = svc.submit(req("k3"))
        self.assertIs(fresh.deliveries[0].status, DeliveryStatus.QUEUED)
        svc.run_until_idle()
        self.assertEqual(len(senders[Channel.EMAIL].sent), 2)

    def test_missing_template_param_fails_whole_request(self):
        svc, _, _ = make()
        bad = NotificationRequest("k", "u1", "hello", {}, (Channel.EMAIL,))
        with self.assertRaises(ValidationError):
            svc.submit(bad)
        svc.submit(req("k"))                              # key was not consumed by the failure

    def test_opt_outs_and_critical_override(self):
        svc, _, _ = make(opted_out_channels=frozenset({Channel.SMS}),
                         opted_out_categories=frozenset({Category.MARKETING}))
        n = svc.submit(req("k1", (Channel.SMS,)))
        self.assertIs(n.deliveries[0].status, DeliveryStatus.SUPPRESSED)
        m = svc.submit(req("k2", category=Category.MARKETING, name="B"))
        self.assertIs(m.deliveries[0].status, DeliveryStatus.SUPPRESSED)
        c = svc.submit(req("k3", (Channel.SMS,), Priority.CRITICAL, template="otp", name="1"))
        self.assertIs(c.deliveries[0].status, DeliveryStatus.QUEUED)


class PriorityAndSchedulingTest(unittest.TestCase):
    def test_ready_high_priority_goes_before_earlier_low(self):
        svc, senders, _ = make()
        svc.submit(req("low", priority=Priority.LOW, name="low"))
        svc.submit(req("norm", priority=Priority.NORMAL, name="normal"))
        svc.submit(req("crit", priority=Priority.CRITICAL, name="critical"))
        svc.run_until_idle()
        self.assertEqual([b for _, _, b in senders[Channel.EMAIL].sent],
                         ["hi critical", "hi normal", "hi low"])

    def test_scheduled_send(self):
        svc, senders, clock = make()
        svc.submit(req("k", send_at=T0 + 60))
        svc.run_until_idle()
        self.assertEqual(senders[Channel.EMAIL].sent, [])
        self.assertEqual(svc.next_wakeup(), T0 + 60)
        clock.advance(60)
        svc.run_until_idle()
        self.assertEqual(len(senders[Channel.EMAIL].sent), 1)


class QuietHoursTest(unittest.TestCase):
    ist = timezone(timedelta(hours=5, minutes=30))

    def at(self, h, m=0, day=5):
        return datetime(2026, 1, day, h, m, tzinfo=self.ist).timestamp()

    def test_window_wrapping_midnight(self):
        q = QuietHours(dtime(22, 0), dtime(7, 0), self.ist)
        self.assertEqual(q.next_allowed(self.at(21, 59)), self.at(21, 59))
        self.assertEqual(q.next_allowed(self.at(22, 0)), self.at(7, 0, day=6))
        self.assertEqual(q.next_allowed(self.at(3, 0)), self.at(7, 0))
        self.assertEqual(q.next_allowed(self.at(7, 0)), self.at(7, 0))      # end is exclusive

    def test_same_day_window(self):
        q = QuietHours(dtime(13, 0), dtime(14, 0), self.ist)
        self.assertEqual(q.next_allowed(self.at(13, 30)), self.at(14, 0))
        self.assertEqual(q.next_allowed(self.at(14, 30)), self.at(14, 30))

    def test_deferred_then_sent_and_critical_bypasses(self):
        q = QuietHours(dtime(22, 0), dtime(7, 0), self.ist)
        svc, senders, clock = make(quiet=q)
        clock.now = self.at(23, 0)
        n = svc.submit(req("k"))
        c = svc.submit(req("otp", (Channel.SMS,), Priority.CRITICAL, template="otp", name="9"))
        svc.run_until_idle()
        self.assertIs(n.deliveries[0].status, DeliveryStatus.QUEUED)
        self.assertEqual(n.deliveries[0].attempts, 0)
        self.assertIs(c.deliveries[0].status, DeliveryStatus.SENT)
        clock.now = self.at(7, 0, day=6)
        svc.run_until_idle()
        self.assertIs(n.deliveries[0].status, DeliveryStatus.SENT)


class RateLimitTest(unittest.TestCase):
    def test_per_user_channel_limit_defers_not_drops(self):
        limiter = RateLimiter(per_user={Channel.SMS: Limit(2, 60)}, per_channel={})
        svc, senders, clock = make(limiter=limiter)
        ns = [svc.submit(req(f"k{i}", (Channel.SMS,), template="otp", name=str(i))) for i in range(3)]
        svc.run_until_idle()
        self.assertEqual(len(senders[Channel.SMS].sent), 2)
        third = ns[2].deliveries[0]
        self.assertIs(third.status, DeliveryStatus.QUEUED)
        self.assertEqual(third.attempts, 0)
        self.assertAlmostEqual(third.ready_at - clock(), 30.0)          # one token per 30s
        clock.advance(30)
        svc.run_until_idle()
        self.assertEqual(len(senders[Channel.SMS].sent), 3)

    def test_limit_is_per_user_and_per_channel(self):
        limiter = RateLimiter(per_user={Channel.SMS: Limit(1, 60)}, per_channel={})
        svc, senders, _ = make(limiter=limiter)
        svc.upsert_user(UserPreferences("u2", {Channel.SMS: "+1666"}))
        svc.submit(req("a", (Channel.SMS,), template="otp", name="1"))
        svc.submit(req("b", (Channel.SMS,), template="otp", name="2", user="u2"))
        svc.submit(req("c", (Channel.EMAIL,)))                          # email not limited
        svc.run_until_idle()
        self.assertEqual(len(senders[Channel.SMS].sent), 2)
        self.assertEqual(len(senders[Channel.EMAIL].sent), 1)

    def test_global_channel_limit(self):
        limiter = RateLimiter(per_user={}, per_channel={Channel.EMAIL: Limit(2, 1)})
        svc, senders, _ = make(limiter=limiter)
        for i in range(5):
            svc.submit(req(f"k{i}", name=str(i)))
        svc.run_until_idle()
        self.assertEqual(len(senders[Channel.EMAIL].sent), 2)

    def test_user_bucket_map_is_bounded(self):
        limiter = RateLimiter(per_user={Channel.SMS: Limit(1, 60)}, per_channel={}, max_user_buckets=10)
        for i in range(100):
            limiter.acquire(f"user{i}", Channel.SMS, T0)
        self.assertLessEqual(len(limiter._user_buckets), 10)


class RetryTest(unittest.TestCase):
    def test_transient_then_success(self):
        svc, senders, clock = make()
        senders[Channel.EMAIL].fail_next(TransientSendError("503"))
        n = svc.submit(req("k"))
        svc.run_until_idle()
        d = n.deliveries[0]
        self.assertEqual(d.attempts, 1)
        self.assertGreater(d.ready_at, T0 - 1)
        clock.advance(10)
        svc.run_until_idle()
        self.assertIs(d.status, DeliveryStatus.SENT)
        self.assertEqual(d.attempts, 2)

    def test_retries_exhausted_go_to_dead_letters(self):
        svc, senders, clock = make()
        senders[Channel.EMAIL].fail_next(*[TransientSendError("503")] * 3)
        n = svc.submit(req("k"))
        for _ in range(5):
            svc.run_until_idle()
            clock.advance(10)
        d = n.deliveries[0]
        self.assertIs(d.status, DeliveryStatus.FAILED)
        self.assertEqual(d.attempts, 3)
        self.assertEqual(svc.dead_letters, [d])

    def test_permanent_error_not_retried(self):
        svc, senders, _ = make()
        senders[Channel.EMAIL].fail_next(PermanentSendError("550"))
        n = svc.submit(req("k"))
        svc.run_until_idle()
        self.assertIs(n.deliveries[0].status, DeliveryStatus.FAILED)
        self.assertEqual(n.deliveries[0].attempts, 1)

    def test_backoff_is_exponential_and_capped(self):
        class Max(random.Random):
            def uniform(self, a, b):
                return b
        policy = RetryPolicy(base_s=2, cap_s=10, rng=Max())
        self.assertEqual([policy.delay(n) for n in (1, 2, 3, 4)], [2, 4, 8, 10])


class ConcurrencyTest(unittest.TestCase):
    def test_workers_send_each_delivery_exactly_once(self):
        svc, senders, _ = make()
        for u in range(40):
            svc.upsert_user(UserPreferences(f"x{u}", {Channel.EMAIL: f"{u}@x", Channel.PUSH: f"t{u}"}))
        for u in range(40):
            for k in range(5):
                svc.submit(req(f"{u}-{k}", (Channel.EMAIL, Channel.PUSH), user=f"x{u}", name=str(k)))

        def worker():
            while svc.process_next() is not None:
                pass

        ts = [threading.Thread(target=worker) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        for ch in (Channel.EMAIL, Channel.PUSH):
            ids = [d for d, _, _ in senders[ch].sent]
            self.assertEqual(len(ids), 200)
            self.assertEqual(len(set(ids)), 200)

    def test_rate_limit_holds_under_concurrency(self):
        limiter = RateLimiter(per_user={Channel.SMS: Limit(5, 3600)}, per_channel={})
        svc, senders, _ = make(limiter=limiter)
        for i in range(50):
            svc.submit(req(f"k{i}", (Channel.SMS,), template="otp", name=str(i)))
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            while svc.process_next() is not None:     # deferred work leaves the ready queue
                pass

        ts = [threading.Thread(target=worker) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(senders[Channel.SMS].sent), 5)

    def test_concurrent_duplicate_submits_create_one_notification(self):
        svc, senders, _ = make()
        barrier, out = threading.Barrier(10), []

        def go():
            barrier.wait()
            out.append(svc.submit(req("same")).notification_id)

        ts = [threading.Thread(target=go) for _ in range(10)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(set(out)), 1)
        svc.run_until_idle()
        self.assertEqual(len(senders[Channel.EMAIL].sent), 1)


if __name__ == "__main__":
    unittest.main()
