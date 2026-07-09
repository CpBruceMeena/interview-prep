# 🧠 Notification Service LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

## Phase 0: Requirements Gathering

What channels? (Email, SMS, Push, Webhook.) Templates? Scheduling? Batching? Rate limits? Idempotency? Cost tracking?

## Phase 1: Identify the Nouns

> *"A notification service accepts requests with recipients and channels, renders templates, queues messages, and delivers via providers."*

| Noun | Decision | Why |
|------|----------|-----|
| NotificationRequest | @dataclass | Incoming request with recipients + channels |
| NotificationMessage | @dataclass | Individual message to one recipient via one channel |
| Recipient | @dataclass | Contact info (email, phone, push_token) |
| NotificationStore | Regular | In-memory store (replace with DB) |
| TemplateRenderer | Regular | Renders templates with variables |
| Provider | ABC | Strategy pattern for delivery |
| MessageWorker | Regular | Processes message queue per channel |
| NotificationOrchestrator | Facade | Main entry point |
| TokenBucket | Regular | Rate limiter for async delivery |
| NotificationChannel | Enum | EMAIL, SMS, PUSH, WEBHOOK |
| MessageStatus | Enum | PENDING → QUEUED → SENDING → SENT → DELIVERED/FAILED |

## Phase 2: Enums First

```python
class NotificationChannel(Enum):  EMAIL, SMS, PUSH, WEBHOOK
class NotificationPriority(Enum): LOW=0, NORMAL=1, HIGH=2, URGENT=3
class MessageStatus(Enum):        PENDING, QUEUED, SENDING, SENT, DELIVERED, FAILED, BOUNCED
```

## Phase 3: dataclass vs `__init__`

- **`NotificationRequest`**: `@dataclass` — incoming data with auto-generated fields
- **`NotificationMessage`**: `@dataclass` — message data with auto-generated ID
- **`Recipient`**: `@dataclass` — pure data container
- **`Provider`**: ABC — each channel has a different provider
- **`MessageWorker`**: Regular — async queue processing
- **`TokenBucket`**: Regular — rate limiter with refill algorithm

**These dataclasses are great examples** — complex defaults (`field(default_factory=...)`).

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Accept request | `NotificationOrchestrator.submit()` | Entry point, handles idempotency |
| Render template | `TemplateRenderer.render()` | SRP: template logic separate |
| Generate messages | Orchestrator._generate_messages() | Creates individual messages per channel |
| Send via provider | `Provider.send()` | Each provider has its own API |
| Process queue | `MessageWorker.run()` | Batches + rate limits + sends |
| Rate limit | `TokenBucket.acquire()` | Generic rate limiter |
| Store data | `NotificationStore` | SRP: storage separate |
| Check scheduled | `scheduler_loop()` | Background task |

## Phase 5: Provider Strategy Pattern

```python
class Provider(ABC):
    async def send(self, message) -> bool
    def cost_per_unit(self) -> float

class SESEmailProvider(Provider):   # $0.0001/email
class SNSSMSProvider(Provider):     # $0.00645/SMS
class FCMProvider(Provider):        # Free up to 1M/month
```

Each provider has a different cost per unit — useful for cost estimation.

## Phase 6: The Message Flow

```
NotificationRequest
    ↓
Orchestrator.submit()
    ├── Idempotency check (dedup_cache)
    ├── Schedule check (if scheduled, store for later)
    └── _generate_messages()
        └── For each recipient × channel:
            → NotificationMessage
            → Store
            → Worker.queue.put(message)
                └── Worker loop:
                    ├── Collect batch
                    ├── Rate limit (TokenBucket)
                    ├── Provider.send()
                    └── Update status
```

## Phase 7: Token Bucket Rate Limiter (Async)

```python
class TokenBucket:
    async def acquire(self, tokens=1):
        while True:
            elapsed = time.monotonic() - self.last_refill
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            if self.tokens >= tokens:
                self.tokens -= tokens
                return
            await asyncio.sleep(...)
```

This is the same TokenBucket concept from rate-limiter, applied in an async context.

## Phase 8: Quick Checklist

✅ **Strategy Pattern:** Providers are swappable per channel
✅ **SRP:** Store, Template, Worker, Provider each own their concern
✅ **Async:** Message processing is non-blocking with asyncio
✅ **Rate Limiting:** TokenBucket prevents provider overload
✅ **Idempotency:** Prevents duplicate notifications
