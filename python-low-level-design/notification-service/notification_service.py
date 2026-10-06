"""
Notification Service - Low Level Design
=======================================

One request ("notify user U with template T") fans out into one Delivery per
channel. Each Delivery then goes through, at send time:

    preferences (opt-outs)  ->  quiet hours  ->  rate limits  ->  send  ->  retry / DLQ

Design points:

* Idempotency on submit: the same idempotency_key within its TTL returns the
  original notification instead of sending again. Separately, a content dedup
  window suppresses the same (user, template, params) sent twice in quick
  succession under different keys (e.g. a double-fired event).
* Priority: CRITICAL > HIGH > NORMAL > LOW among deliveries that are *ready*.
  Delayed work (scheduled, backing off, rate-limited, quiet hours) waits in a
  separate heap ordered by time, so a ready HIGH never queues behind a LOW that
  merely became ready a moment earlier.
* Rate limits: a token bucket per (user, channel) protects users from spam and
  a token bucket per channel protects the provider quota. Rate-limited
  deliveries are deferred, not dropped, and do not consume a retry attempt.
* Quiet hours in the user's timezone, possibly wrapping midnight. CRITICAL
  bypasses quiet hours and channel opt-outs, but never rate limits (OTP floods
  are an abuse vector).
* Retries: transient errors back off exponentially with full jitter; permanent
  errors and exhausted retries go to a dead-letter list.
* Thread-safe: one lock guards queues and records, never held while calling a
  provider. Any number of worker threads may call `process_next()`.

Stdlib only, Python 3.10+. Time is an injectable clock (epoch seconds).
"""

from __future__ import annotations

import heapq
import itertools
import random
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta, timezone, tzinfo
from enum import Enum
from string import Template
from typing import Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

Clock = Callable[[], float]


# ---------------------------------------------------------------- errors

class NotificationError(Exception):
    pass


class ValidationError(NotificationError):
    pass


class TransientSendError(Exception):
    """Provider timeout, 5xx, throttling: worth retrying."""


class PermanentSendError(Exception):
    """Invalid address, unsubscribed token, 4xx: retrying will not help."""


# ---------------------------------------------------------------- enums & value objects

class Channel(Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class Priority(Enum):
    CRITICAL = 0     # OTP, security alerts: bypass quiet hours and opt-outs
    HIGH = 1         # order shipped, payment failed
    NORMAL = 2
    LOW = 3          # digests, marketing


class Category(Enum):
    TRANSACTIONAL = "transactional"
    MARKETING = "marketing"


class DeliveryStatus(Enum):
    QUEUED = "queued"            # waiting (scheduled, backing off, deferred) or ready
    SENDING = "sending"          # claimed by a worker
    SENT = "sent"
    FAILED = "failed"            # permanent error or retries exhausted -> dead letters
    SUPPRESSED = "suppressed"    # opted out, no address, or content duplicate


@dataclass(frozen=True)
class QuietHours:
    """Local-time window [start, end). May wrap midnight, e.g. 22:00-07:00."""
    start: dtime
    end: dtime
    tz: tzinfo                    # a zoneinfo.ZoneInfo in production (handles DST)

    def next_allowed(self, now: float) -> float:
        """`now` if outside the window, else the epoch time at which the window ends."""
        local = datetime.fromtimestamp(now, self.tz)
        t = local.time()
        if self.start <= self.end:
            inside = self.start <= t < self.end
        else:
            inside = t >= self.start or t < self.end
        if not inside:
            return now
        end = local.replace(hour=self.end.hour, minute=self.end.minute, second=0, microsecond=0)
        if end <= local:
            end += timedelta(days=1)
        return end.timestamp()


@dataclass
class UserPreferences:
    user_id: str
    contacts: Dict[Channel, str]                       # email address, phone, push token
    opted_out_channels: FrozenSet[Channel] = frozenset()
    opted_out_categories: FrozenSet[Category] = frozenset()
    quiet_hours: Optional[QuietHours] = None


@dataclass(frozen=True)
class NotificationRequest:
    idempotency_key: str
    user_id: str
    template_id: str
    params: Mapping[str, str]
    channels: Tuple[Channel, ...]
    priority: Priority = Priority.NORMAL
    category: Category = Category.TRANSACTIONAL
    send_at: Optional[float] = None                   # None = now


@dataclass
class Delivery:
    delivery_id: str
    notification_id: str
    user_id: str
    channel: Channel
    address: str
    body: str
    priority: Priority
    category: Category
    status: DeliveryStatus = DeliveryStatus.QUEUED
    attempts: int = 0
    ready_at: float = 0.0
    last_error: Optional[str] = None
    provider_message_id: Optional[str] = None


@dataclass
class Notification:
    notification_id: str
    request: NotificationRequest
    deliveries: List[Delivery] = field(default_factory=list)


# ---------------------------------------------------------------- templates

class TemplateStore:
    """Templates per (template_id, channel). `$name` placeholders; a missing param is an error,
    so we never send 'Hi $name'."""

    def __init__(self) -> None:
        self._templates: Dict[Tuple[str, Channel], Template] = {}

    def register(self, template_id: str, channel: Channel, text: str) -> None:
        self._templates[(template_id, channel)] = Template(text)

    def render(self, template_id: str, channel: Channel, params: Mapping[str, str]) -> str:
        tpl = self._templates.get((template_id, channel))
        if tpl is None:
            raise ValidationError(f"no template {template_id!r} for {channel.value}")
        try:
            return tpl.substitute(params)
        except KeyError as e:
            raise ValidationError(f"template {template_id!r} missing param {e}") from None


# ---------------------------------------------------------------- senders

class ChannelSender(ABC):
    """Adapter over SES / Twilio / FCM. Returns the provider's message id."""

    @abstractmethod
    def send(self, delivery_id: str, address: str, body: str) -> str: ...


class FakeSender(ChannelSender):
    """Records sends; scripted failures are consumed one per call."""

    def __init__(self, name: str):
        self.name = name
        self.sent: List[Tuple[str, str, str]] = []      # (delivery_id, address, body)
        self._failures: List[Exception] = []
        self._lock = threading.Lock()

    def fail_next(self, *errors: Exception) -> None:
        with self._lock:
            self._failures.extend(errors)

    def send(self, delivery_id: str, address: str, body: str) -> str:
        with self._lock:
            if self._failures:
                raise self._failures.pop(0)
            self.sent.append((delivery_id, address, body))
            return f"{self.name}-{len(self.sent)}"


# ---------------------------------------------------------------- rate limiting

class TokenBucket:
    """Not thread-safe on its own; RateLimiter serialises access."""

    def __init__(self, capacity: float, refill_per_s: float, now: float):
        self.capacity, self.rate = capacity, refill_per_s
        self.tokens, self.updated = capacity, now

    def try_take(self, now: float) -> float:
        """Take one token. Returns 0.0 on success, else seconds until one is available."""
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / self.rate

    def peek_wait(self, now: float) -> float:
        tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        return 0.0 if tokens >= 1 else (1 - tokens) / self.rate


@dataclass(frozen=True)
class Limit:
    capacity: int          # burst
    per_seconds: float     # capacity tokens refill over this many seconds

    @property
    def rate(self) -> float:
        return self.capacity / self.per_seconds


class RateLimiter:
    """Per-(user, channel) and per-channel token buckets, checked together atomically:
    a token is only taken from either bucket if both have one."""

    def __init__(self, per_user: Mapping[Channel, Limit], per_channel: Mapping[Channel, Limit],
                 max_user_buckets: int = 100_000):
        self._per_user, self._per_channel = dict(per_user), dict(per_channel)
        self._user_buckets: "OrderedDict[Tuple[str, Channel], TokenBucket]" = OrderedDict()
        self._channel_buckets: Dict[Channel, TokenBucket] = {}
        self._max = max_user_buckets
        self._lock = threading.Lock()

    def acquire(self, user_id: str, channel: Channel, now: float) -> float:
        """0.0 if allowed (tokens taken), else seconds to wait before trying again."""
        with self._lock:
            buckets = []
            if channel in self._per_user:
                buckets.append(self._user_bucket(user_id, channel, now))
            if channel in self._per_channel:
                lim = self._per_channel[channel]
                buckets.append(self._channel_buckets.setdefault(
                    channel, TokenBucket(lim.capacity, lim.rate, now)))
            wait = max((b.peek_wait(now) for b in buckets), default=0.0)
            if wait > 0:
                return wait
            for b in buckets:
                b.try_take(now)
            return 0.0

    def _user_bucket(self, user_id: str, channel: Channel, now: float) -> TokenBucket:
        key = (user_id, channel)
        bucket = self._user_buckets.get(key)
        if bucket is None:
            lim = self._per_user[channel]
            bucket = self._user_buckets[key] = TokenBucket(lim.capacity, lim.rate, now)
            if len(self._user_buckets) > self._max:
                # Evict least-recently-used. Slightly lenient for that user; bounded memory.
                self._user_buckets.popitem(last=False)
        self._user_buckets.move_to_end(key)
        return bucket


# ---------------------------------------------------------------- retry policy

class RetryPolicy:
    """Exponential backoff with full jitter: delay ~ U(0, min(cap, base * 2^(attempt-1)))."""

    def __init__(self, max_attempts: int = 4, base_s: float = 2.0, cap_s: float = 300.0,
                 rng: Optional[random.Random] = None):
        self.max_attempts, self._base, self._cap = max_attempts, base_s, cap_s
        self._rng = rng or random.Random()

    def delay(self, attempt: int) -> float:
        return self._rng.uniform(0, min(self._cap, self._base * 2 ** (attempt - 1)))


# ---------------------------------------------------------------- service

class NotificationService:
    def __init__(self, senders: Mapping[Channel, ChannelSender], templates: TemplateStore,
                 rate_limiter: Optional[RateLimiter] = None, retry: Optional[RetryPolicy] = None,
                 idempotency_ttl_s: float = 24 * 3600, dedup_window_s: float = 600,
                 clock: Clock = time.time):
        self._senders = dict(senders)
        self._templates = templates
        self._limiter = rate_limiter or RateLimiter({}, {})
        self._retry = retry or RetryPolicy()
        self._idem_ttl, self._dedup_window = idempotency_ttl_s, dedup_window_s
        self._clock = clock

        self._lock = threading.Lock()
        self._users: Dict[str, UserPreferences] = {}
        self._notifications: Dict[str, Notification] = {}
        self._deliveries: Dict[str, Delivery] = {}
        # Both ordered by insertion; with a constant TTL that is also expiry order,
        # so expired entries are popped from the front in O(1) each.
        self._idempotency: "OrderedDict[str, Tuple[str, float]]" = OrderedDict()
        self._recent_content: "OrderedDict[Tuple, float]" = OrderedDict()
        self._delayed: List[Tuple[float, int, str]] = []          # (ready_at, seq, delivery_id)
        self._ready: List[Tuple[int, int, str]] = []              # (priority, seq, delivery_id)
        self._seq = itertools.count()
        self._notification_ids = itertools.count(1)
        self._delivery_ids = itertools.count(1)
        self.dead_letters: List[Delivery] = []

    # ---- setup ----------------------------------------------------------------

    def upsert_user(self, prefs: UserPreferences) -> None:
        with self._lock:
            self._users[prefs.user_id] = prefs

    # ---- submit ---------------------------------------------------------------

    def submit(self, request: NotificationRequest) -> Notification:
        """Validate, render, and enqueue one Delivery per channel. Idempotent on the key."""
        if not request.channels:
            raise ValidationError("at least one channel is required")
        now = self._clock()
        with self._lock:
            self._expire(now)
            hit = self._idempotency.get(request.idempotency_key)
            if hit is not None:
                return self._notifications[hit[0]]

            prefs = self._users.get(request.user_id)
            if prefs is None:
                raise ValidationError(f"unknown user {request.user_id}")
            # Render everything before recording anything: a bad template fails the whole request.
            bodies = {ch: self._templates.render(request.template_id, ch, request.params)
                      for ch in dict.fromkeys(request.channels)}

            notification = Notification(f"n_{next(self._notification_ids)}", request)
            content_key = (request.user_id, request.template_id, tuple(sorted(request.params.items())))
            duplicate = content_key in self._recent_content
            self._recent_content[content_key] = now
            self._recent_content.move_to_end(content_key)

            for channel, body in bodies.items():
                d = Delivery(f"d_{next(self._delivery_ids)}", notification.notification_id, request.user_id,
                             channel, prefs.contacts.get(channel, ""), body, request.priority,
                             request.category, ready_at=max(now, request.send_at or now))
                reason = "duplicate content within dedup window" if duplicate else self._suppression(prefs, d)
                if reason:
                    d.status, d.last_error = DeliveryStatus.SUPPRESSED, reason
                else:
                    self._enqueue(d, d.ready_at, now)
                notification.deliveries.append(d)
                self._deliveries[d.delivery_id] = d

            self._notifications[notification.notification_id] = notification
            self._idempotency[request.idempotency_key] = (notification.notification_id, now)
            return notification

    def _suppression(self, prefs: UserPreferences, d: Delivery) -> Optional[str]:
        if not d.address:
            return f"no {d.channel.value} contact"
        if d.channel not in self._senders:
            return f"no sender for {d.channel.value}"
        if d.priority is Priority.CRITICAL:
            return None
        if d.category in prefs.opted_out_categories:
            return f"opted out of {d.category.value}"
        if d.channel in prefs.opted_out_channels:
            return f"opted out of {d.channel.value}"
        return None

    # ---- workers --------------------------------------------------------------

    def process_next(self) -> Optional[Delivery]:
        """Claim the highest-priority ready delivery and try to send it once.
        Returns the delivery it worked on, or None if nothing is ready. Safe from many threads."""
        now = self._clock()
        with self._lock:
            self._promote(now)
            if not self._ready:
                return None
            _, _, delivery_id = heapq.heappop(self._ready)
            d = self._deliveries[delivery_id]
            prefs = self._users[d.user_id]

            # Quiet hours are checked at send time: a retry or a scheduled send can land in them.
            if d.priority is not Priority.CRITICAL and prefs.quiet_hours:
                allowed = prefs.quiet_hours.next_allowed(now)
                if allowed > now:
                    self._enqueue(d, allowed, now)
                    return d
            wait = self._limiter.acquire(d.user_id, d.channel, now)
            if wait > 0:
                self._enqueue(d, now + wait, now)          # deferred, not an attempt
                return d
            d.status = DeliveryStatus.SENDING
            d.attempts += 1

        # Provider I/O outside the lock. delivery_id doubles as the provider idempotency key
        # where the provider supports one; otherwise delivery is at-least-once.
        try:
            provider_id = self._senders[d.channel].send(d.delivery_id, d.address, d.body)
        except TransientSendError as e:
            self._after_failure(d, str(e), retryable=True)
        except PermanentSendError as e:
            self._after_failure(d, str(e), retryable=False)
        else:
            with self._lock:
                d.status, d.provider_message_id = DeliveryStatus.SENT, provider_id
        return d

    def run_until_idle(self, max_steps: int = 10_000) -> int:
        """Process everything that is ready *now*. Deterministic single-threaded driver."""
        steps = 0
        while steps < max_steps:
            if not self._has_ready():
                break
            self.process_next()
            steps += 1
        return steps

    def _after_failure(self, d: Delivery, error: str, retryable: bool) -> None:
        now = self._clock()
        with self._lock:
            d.last_error = error
            if retryable and d.attempts < self._retry.max_attempts:
                self._enqueue(d, now + self._retry.delay(d.attempts), now)
            else:
                d.status = DeliveryStatus.FAILED
                self.dead_letters.append(d)

    # ---- queries --------------------------------------------------------------

    def get(self, notification_id: str) -> Notification:
        with self._lock:
            return self._notifications[notification_id]

    def next_wakeup(self) -> Optional[float]:
        """When the earliest delayed delivery becomes ready (for a worker's sleep)."""
        with self._lock:
            if self._ready:
                return self._clock()
            return self._delayed[0][0] if self._delayed else None

    # ---- internals (caller holds self._lock) ------------------------------------

    def _enqueue(self, d: Delivery, ready_at: float, now: float) -> None:
        d.status, d.ready_at = DeliveryStatus.QUEUED, ready_at
        if ready_at <= now:
            heapq.heappush(self._ready, (d.priority.value, next(self._seq), d.delivery_id))
        else:
            heapq.heappush(self._delayed, (ready_at, next(self._seq), d.delivery_id))

    def _promote(self, now: float) -> None:
        while self._delayed and self._delayed[0][0] <= now:
            _, _, delivery_id = heapq.heappop(self._delayed)
            d = self._deliveries[delivery_id]
            heapq.heappush(self._ready, (d.priority.value, next(self._seq), delivery_id))

    def _has_ready(self) -> bool:
        with self._lock:
            self._promote(self._clock())
            return bool(self._ready)

    def _expire(self, now: float) -> None:
        while self._idempotency and next(iter(self._idempotency.values()))[1] <= now - self._idem_ttl:
            self._idempotency.popitem(last=False)
        while self._recent_content and next(iter(self._recent_content.values())) <= now - self._dedup_window:
            self._recent_content.popitem(last=False)


class ManualClock:
    def __init__(self, start: float):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------- demo

def demo() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    clock = ManualClock(datetime(2026, 3, 2, 21, 0, tzinfo=ist).timestamp())   # 21:00 IST
    email, sms = FakeSender("ses"), FakeSender("sns")
    templates = TemplateStore()
    templates.register("otp", Channel.SMS, "Your code is $code")
    templates.register("shipped", Channel.EMAIL, "Hi $name, order $order shipped")
    templates.register("shipped", Channel.SMS, "Order $order shipped")
    templates.register("digest", Channel.EMAIL, "Hi $name, your weekly digest")
    templates.register("promo", Channel.EMAIL, "Hi $name, 20% off today")

    svc = NotificationService(
        {Channel.EMAIL: email, Channel.SMS: sms}, templates,
        rate_limiter=RateLimiter(per_user={Channel.SMS: Limit(3, 3600)},
                                 per_channel={Channel.EMAIL: Limit(100, 1)}),
        retry=RetryPolicy(max_attempts=3, base_s=2, rng=random.Random(7)),
        clock=clock,
    )
    svc.upsert_user(UserPreferences(
        "u1", {Channel.EMAIL: "asha@example.com", Channel.SMS: "+911234567890"},
        opted_out_categories=frozenset({Category.MARKETING}),
        quiet_hours=QuietHours(dtime(22, 0), dtime(7, 0), ist)))
    ship = lambda key, order, chans=(Channel.EMAIL, Channel.SMS), prio=Priority.HIGH: NotificationRequest(
        key, "u1", "shipped", {"name": "Asha", "order": order}, chans, prio)

    # 1. Priority: the LOW digest was submitted first but the HIGH update is sent first.
    #    Marketing is suppressed by the user's opt-out.
    digest = svc.submit(NotificationRequest("k-digest", "u1", "digest", {"name": "Asha"},
                                            (Channel.EMAIL,), Priority.LOW))
    promo = svc.submit(NotificationRequest("k-promo", "u1", "promo", {"name": "Asha"}, (Channel.EMAIL,),
                                           Priority.LOW, Category.MARKETING))
    n = svc.submit(ship("k-ship", "A-17"))
    svc.run_until_idle()
    print("1. email order:", [body for _, _, body in email.sent], "| promo:", promo.deliveries[0].status.value)

    # 2. A transient provider error is retried after backoff.
    n2 = svc.submit(ship("k-ship2", "A-18", (Channel.EMAIL,)))
    email.fail_next(TransientSendError("SES 503"))
    svc.run_until_idle()
    first = n2.deliveries[0].status.value
    clock.advance(5)
    svc.run_until_idle()
    print(f"2. A-18 email: {first} after 1 attempt -> {n2.deliveries[0].status.value} "
          f"after {n2.deliveries[0].attempts}")

    # 3. Same idempotency key -> same notification, nothing new sent.
    again = svc.submit(ship("k-ship", "A-17"))
    print(f"3. retry returned {again.notification_id}, same notification: {again is n}")

    # 4. Quiet hours (22:00-07:00 IST): NORMAL is deferred to 07:00, CRITICAL OTP goes now.
    clock.now = datetime(2026, 3, 2, 23, 0, tzinfo=ist).timestamp()
    late = svc.submit(ship("k-late", "B-2", (Channel.EMAIL,), Priority.NORMAL))
    otp = svc.submit(NotificationRequest("k-otp1", "u1", "otp", {"code": "111"}, (Channel.SMS,),
                                         Priority.CRITICAL))
    svc.run_until_idle()
    until = datetime.fromtimestamp(late.deliveries[0].ready_at, ist).strftime("%H:%M")
    print(f"4. late email {late.deliveries[0].status.value} until {until}; otp {otp.deliveries[0].status.value}")

    # 5. Per-user SMS limit is 3/hour. otp1 used one token; otp2 and otp3 use the rest;
    #    otp4 is deferred until a token refills (20 min at 3/hour), not dropped.
    otps = [svc.submit(NotificationRequest(f"k-otp{i}", "u1", "otp", {"code": str(i) * 3}, (Channel.SMS,),
                                           Priority.CRITICAL)) for i in (2, 3, 4)]
    svc.run_until_idle()
    otp4 = otps[-1].deliveries[0]
    print("5.", [o.deliveries[0].status.value for o in otps], f"otp4 retries in {otp4.ready_at - clock():.0f}s")

    # 6. At 07:00 the deferred email is attempted; a permanent bounce goes to dead letters.
    clock.now = datetime(2026, 3, 3, 7, 0, tzinfo=ist).timestamp()
    email.fail_next(PermanentSendError("550 mailbox does not exist"))
    svc.run_until_idle()
    print("6. dead letters:", [(d.delivery_id, d.last_error) for d in svc.dead_letters],
          "| digest:", digest.deliveries[0].status.value)


if __name__ == "__main__":
    demo()
