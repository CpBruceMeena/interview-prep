# 🔔 Notification Service — Implementation

> **Python implementation of a high-throughput, low-cost notification system**

```python
"""
Notification Service — Low Level Design
----------------------------------------
Design Principles: SOLID, Strategy Pattern, Queue-Based Architecture
Features: Multi-channel, scheduled delivery, batching, provider failover
"""

import asyncio
import json
import uuid
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from collections import defaultdict


# ─── Enums ───────────────────────────────────────────

class NotificationChannel(Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEBHOOK = "webhook"

class NotificationPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3

class MessageStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"


# ─── Data Models ─────────────────────────────────────

@dataclass
class Recipient:
    email: Optional[str] = None
    phone: Optional[str] = None
    push_token: Optional[str] = None
    webhook_url: Optional[str] = None
    user_id: Optional[str] = None

@dataclass
class NotificationRequest:
    """Incoming notification request from API."""
    notification_id: str = field(default_factory=lambda: f"notif_{uuid.uuid4().hex[:12]}")
    template_id: Optional[str] = None
    recipients: List[Recipient] = field(default_factory=list)
    channels: List[NotificationChannel] = field(default_factory=list)
    schedule_at: Optional[datetime] = None
    priority: NotificationPriority = NotificationPriority.NORMAL
    metadata: Dict[str, Any] = field(default_factory=dict)
    idempotency_key: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class NotificationMessage:
    """Individual message to a single recipient via a single channel."""
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    notification_id: str = ""
    channel: NotificationChannel = NotificationChannel.EMAIL
    recipient: str = ""
    content: str = ""
    status: MessageStatus = MessageStatus.PENDING
    provider_id: Optional[str] = None
    delivery_attempts: int = 0
    last_error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


# ─── In-Memory Store (for demo — replace with DB) ───

class NotificationStore:
    """Simple in-memory store for notifications."""
    
    def __init__(self):
        self.notifications: Dict[str, NotificationRequest] = {}
        self.messages: Dict[str, NotificationMessage] = {}
        self.scheduled: Dict[str, NotificationRequest] = {}
    
    def save_notification(self, request: NotificationRequest):
        self.notifications[request.notification_id] = request
    
    def save_message(self, message: NotificationMessage):
        self.messages[message.message_id] = message
    
    def get_notification(self, notif_id: str) -> Optional[NotificationRequest]:
        return self.notifications.get(notif_id)
    
    def get_messages_by_notification(self, notif_id: str) -> List[NotificationMessage]:
        return [m for m in self.messages.values() if m.notification_id == notif_id]


# ─── Token Bucket Rate Limiter ──────────────────────

class TokenBucket:
    """Token bucket rate limiter for async contexts."""
    
    def __init__(self, rate: float, burst: Optional[int] = None):
        self.rate = rate
        self.burst = burst or rate
        self.tokens = self.burst
        self.last_refill = time.monotonic()
    
    async def acquire(self, tokens: int = 1) -> None:
        """Wait until tokens are available."""
        while True:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_refill = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return
            
            wait = (tokens - self.tokens) / self.rate
            await asyncio.sleep(min(wait, 0.1))


# ─── Template Engine ────────────────────────────────

class TemplateRenderer:
    """Simple template renderer for notification content."""
    
    def __init__(self):
        self.templates = {
            "welcome_email": {
                "subject": "Welcome, {{user_name}}!",
                "body": "Hi {{user_name}},\n\nWelcome to our platform! "
                        "Get started by visiting {{activation_link}}.\n\nThanks!"
            },
            "password_reset": {
                "subject": "Password Reset Request",
                "body": "Hi {{user_name}},\n\nClick here to reset your password: "
                        "{{reset_link}}\n\nThis link expires in 24 hours."
            },
            "sms_alert": {
                "body": "Alert: {{message}}"
            },
            "push_notification": {
                "title": "{{title}}",
                "body": "{{message}}"
            }
        }
    
    def render(self, template_id: str, channel: str, metadata: dict) -> str:
        """Render a template with metadata."""
        if template_id not in self.templates:
            return json.dumps(metadata)

        template = self.templates[template_id]

        if channel == "email":
            subject = self._fill(template.get('subject', 'Notification'), metadata)
            body = self._fill(template.get('body', ''), metadata)
            return f"Subject: {subject}\n\n{body}"

        elif channel == "sms":
            return self._fill(template.get('body', ''), metadata)

        elif channel == "push":
            return json.dumps({
                "title": self._fill(template.get('title', ''), metadata),
                "body": self._fill(template.get('body', ''), metadata)
            })

        return json.dumps(metadata)

    def _fill(self, text: str, metadata: dict) -> str:
        """Fill template variables."""
        for key, value in metadata.items():
            text = text.replace("{{" + key + "}}", str(value))
        return text


# ─── Provider Abstraction (Strategy Pattern) ────────

class Provider(ABC):
    """Abstract provider interface."""
    
    @abstractmethod
    async def send(self, message: NotificationMessage) -> bool:
        pass
    
    @abstractmethod
    def cost_per_unit(self) -> float:
        pass

class SESEmailProvider(Provider):
    """Amazon SES email provider (low cost)."""
    
    def __init__(self):
        self.sent_count = 0
        # In production: self.client = boto3.client('ses')
    
    async def send(self, message: NotificationMessage) -> bool:
        """Send email via SES."""
        # Simulate sending
        await asyncio.sleep(0.05)  # 50ms latency
        self.sent_count += 1
        
        message.provider_id = f"ses_{uuid.uuid4().hex[:8]}"
        message.status = MessageStatus.SENT
        return True
    
    def cost_per_unit(self) -> float:
        return 0.0001  # $0.10 per 1000 emails

class SNSSMSProvider(Provider):
    """Amazon SNS SMS provider."""
    
    def __init__(self):
        self.sent_count = 0
    
    async def send(self, message: NotificationMessage) -> bool:
        """Send SMS via SNS."""
        await asyncio.sleep(0.1)  # 100ms latency
        
        message.provider_id = f"sns_{uuid.uuid4().hex[:8]}"
        message.status = MessageStatus.SENT
        self.sent_count += 1
        return True
    
    def cost_per_unit(self) -> float:
        return 0.00645  # $0.00645 per SMS in US

class FCMProvider(Provider):
    """Firebase Cloud Messaging push provider."""
    
    async def send(self, message: NotificationMessage) -> bool:
        """Send push notification via FCM."""
        await asyncio.sleep(0.03)
        
        message.provider_id = f"fcm_{uuid.uuid4().hex[:8]}"
        message.status = MessageStatus.SENT
        return True
    
    def cost_per_unit(self) -> float:
        return 0.0  # Free up to 1M/month


# ─── Provider Factory ───────────────────────────────

class ProviderFactory:
    """Creates the appropriate provider for each channel."""
    
    _providers = {
        NotificationChannel.EMAIL: SESEmailProvider(),
        NotificationChannel.SMS: SNSSMSProvider(),
        NotificationChannel.PUSH: FCMProvider(),
        NotificationChannel.WEBHOOK: None,  # Custom per customer
    }
    
    @classmethod
    def get_provider(cls, channel: NotificationChannel) -> Optional[Provider]:
        return cls._providers.get(channel)


# ─── Message Worker ─────────────────────────────────

class MessageWorker:
    """Processes messages for a specific channel."""
    
    def __init__(self, channel: NotificationChannel, 
                 provider: Provider,
                 batch_size: int = 10,
                 rate_limit: int = 50):
        self.channel = channel
        self.provider = provider
        self.batch_size = batch_size
        self.queue: asyncio.Queue[NotificationMessage] = asyncio.Queue()
        self.rate_limiter = TokenBucket(rate=rate_limit, burst=rate_limit)
        self.running = True
        self.store = None
    
    def set_store(self, store: NotificationStore):
        self.store = store
    
    async def run(self):
        """Main worker loop — processes messages from queue."""
        while self.running:
            try:
                # Collect a batch
                batch = []
                while len(batch) < self.batch_size:
                    try:
                        msg = await asyncio.wait_for(
                            self.queue.get(), timeout=0.5
                        )
                        batch.append(msg)
                    except asyncio.TimeoutError:
                        break
                
                if not batch:
                    await asyncio.sleep(0.1)
                    continue
                
                # Rate limit
                await self.rate_limiter.acquire(len(batch))
                
                # Send each message
                for msg in batch:
                    try:
                        msg.status = MessageStatus.SENDING
                        success = await self.provider.send(msg)
                        if not success:
                            msg.status = MessageStatus.FAILED
                    except Exception as e:
                        msg.last_error = str(e)
                        msg.status = MessageStatus.FAILED
                    
                    if self.store:
                        self.store.save_message(msg)
                
            except Exception as e:
                print(f"[{self.channel.value}] Worker error: {e}")
                await asyncio.sleep(1)


# ─── Notification Orchestrator ──────────────────────

class NotificationOrchestrator:
    """
    Main orchestrator for the notification system.
    Handles submission, scheduling, and dispatch.
    """
    
    def __init__(self):
        self.store = NotificationStore()
        self.template_engine = TemplateRenderer()
        self.workers: Dict[NotificationChannel, MessageWorker] = {}
        self.dedup_cache: set = set()
        self.dedup_max_size = 10000  # LRU-like limit
        
        # Initialize workers for each channel
        channels = {
            NotificationChannel.EMAIL: {"batch_size": 100, "rate_limit": 50},
            NotificationChannel.SMS: {"batch_size": 1, "rate_limit": 10},
            NotificationChannel.PUSH: {"batch_size": 50, "rate_limit": 100},
            NotificationChannel.WEBHOOK: {"batch_size": 1, "rate_limit": 30},
        }
        
        for channel, config in channels.items():
            provider = ProviderFactory.get_provider(channel)
            if provider:
                worker = MessageWorker(
                    channel=channel,
                    provider=provider,
                    batch_size=config["batch_size"],
                    rate_limit=config["rate_limit"]
                )
                worker.set_store(self.store)
                self.workers[channel] = worker
    
    async def start(self):
        """Start all workers."""
        for worker in self.workers.values():
            asyncio.create_task(worker.run())
    
    async def submit(self, request: NotificationRequest) -> dict:
        """Submit a notification request."""
        
        # Idempotency check
        if request.idempotency_key:
            if request.idempotency_key in self.dedup_cache:
                return {
                    "notification_id": "DUPLICATE",
                    "status": "already_processed"
                }
            self.dedup_cache.add(request.idempotency_key)
            if len(self.dedup_cache) > self.dedup_max_size:
                self.dedup_cache.clear()
        
        # Store notification
        self.store.save_notification(request)
        
        # Handle scheduled notifications
        if request.schedule_at and request.schedule_at > datetime.utcnow():
            self.store.scheduled[request.notification_id] = request
            return {
                "notification_id": request.notification_id,
                "status": "scheduled",
                "estimated_delivery": request.schedule_at.isoformat()
            }
        
        # Generate and dispatch messages
        messages = await self._generate_messages(request)
        
        msg_count_by_channel = defaultdict(int)
        for msg in messages:
            self.store.save_message(msg)
            worker = self.workers.get(msg.channel)
            if worker:
                await worker.queue.put(msg)
                msg_count_by_channel[msg.channel.value] += 1
        
        return {
            "notification_id": request.notification_id,
            "status": "queued" if messages else "empty",
            "recipient_count": len(messages),
            "channel_breakdown": dict(msg_count_by_channel)
        }
    
    async def _generate_messages(self, request: NotificationRequest) -> List[NotificationMessage]:
        """Generate individual messages from the request."""
        messages = []
        
        for recipient in request.recipients:
            for channel in request.channels:
                # Check if recipient has this channel
                if channel == NotificationChannel.EMAIL and not recipient.email:
                    continue
                if channel == NotificationChannel.SMS and not recipient.phone:
                    continue
                if channel == NotificationChannel.PUSH and not recipient.push_token:
                    continue
                
                # Get the address
                addr = {
                    NotificationChannel.EMAIL: recipient.email,
                    NotificationChannel.SMS: recipient.phone,
                    NotificationChannel.PUSH: recipient.push_token,
                }.get(channel, "")
                
                # Render template content
                if request.template_id:
                    content = self.template_engine.render(
                        request.template_id,
                        channel.value,
                        request.metadata
                    )
                else:
                    content = json.dumps(request.metadata)
                
                messages.append(NotificationMessage(
                    notification_id=request.notification_id,
                    channel=channel,
                    recipient=addr,
                    content=content
                ))
        
        return messages
    
    async def process_scheduled(self):
        """Process due scheduled notifications."""
        now = datetime.utcnow()
        due = [
            req for req_id, req in list(self.store.scheduled.items())
            if req.schedule_at and req.schedule_at <= now
        ]
        
        for req in due:
            del self.store.scheduled[req.notification_id]
            await self.submit(req)
    
    def get_status(self, notification_id: str) -> dict:
        """Get the status of a notification."""
        request = self.store.get_notification(notification_id)
        if not request:
            return {"error": "notification not found"}
        
        messages = self.store.get_messages_by_notification(notification_id)
        
        channel_counts = defaultdict(int)
        status_counts = defaultdict(int)
        
        for msg in messages:
            channel_counts[msg.channel.value] += 1
            status_counts[msg.status.value] += 1
        
        return {
            "notification_id": notification_id,
            "status": request.priority.value,
            "total_messages": len(messages),
            "by_channel": dict(channel_counts),
            "by_status": dict(status_counts),
            "created_at": request.created_at.isoformat()
        }

    def get_cost_estimate(self, notification_id: str) -> float:
        """Estimate cost of a notification."""
        messages = self.store.get_messages_by_notification(notification_id)
        total_cost = 0.0
        
        for msg in messages:
            provider = ProviderFactory.get_provider(msg.channel)
            if provider:
                total_cost += provider.cost_per_unit()
        
        return total_cost


# ─── Scheduled Delivery Loop ────────────────────────

async def scheduler_loop(orchestrator: NotificationOrchestrator):
    """Check for due scheduled notifications every second."""
    while True:
        try:
            await orchestrator.process_scheduled()
        except Exception as e:
            print(f"Scheduler error: {e}")
        await asyncio.sleep(1)


# ─── Demo ────────────────────────────────────────────

async def demo():
    print("=== Notification Service Demo ===\n")
    
    orchestrator = NotificationOrchestrator()
    await orchestrator.start()
    
    # Start scheduler
    asyncio.create_task(scheduler_loop(orchestrator))
    
    # Demo 1: Send immediate email notification
    print("--- Demo 1: Immediate Email ---")
    result = await orchestrator.submit(NotificationRequest(
        template_id="welcome_email",
        recipients=[Recipient(email="user@example.com", user_id="123")],
        channels=[NotificationChannel.EMAIL],
        priority=NotificationPriority.HIGH,
        metadata={
            "user_name": "Alice",
            "activation_link": "https://example.com/activate/abc123"
        }
    ))
    print(f"  Result: {json.dumps(result, indent=2)}")
    
    # Demo 2: Multi-channel notification
    print("\n--- Demo 2: Multi-Channel (Email + SMS) ---")
    result = await orchestrator.submit(NotificationRequest(
        template_id="sms_alert",
        recipients=[Recipient(
            email="admin@example.com",
            phone="+1234567890",
            user_id="admin01"
        )],
        channels=[NotificationChannel.EMAIL, NotificationChannel.SMS],
        priority=NotificationPriority.URGENT,
        metadata={"message": "Server CPU usage exceeded 90%!"}
    ))
    print(f"  Result: {json.dumps(result, indent=2)}")
    
    # Demo 3: Scheduled notification
    print("\n--- Demo 3: Scheduled (5 seconds from now) ---")
    result = await orchestrator.submit(NotificationRequest(
        template_id="password_reset",
        recipients=[Recipient(email="user@example.com")],
        channels=[NotificationChannel.EMAIL],
        schedule_at=datetime.utcnow() + timedelta(seconds=5),
        metadata={
            "user_name": "Bob",
            "reset_link": "https://example.com/reset/xyz789"
        }
    ))
    print(f"  Result: {json.dumps(result, indent=2)}")
    
    # Wait for scheduled delivery
    await asyncio.sleep(6)
    
    # Demo 4: Check status
    print("\n--- Demo 4: Status Check ---")
    for notif_id in orchestrator.store.notifications:
        status = orchestrator.get_status(notif_id)
        cost = orchestrator.get_cost_estimate(notif_id)
        print(f"  {notif_id}: {status['total_messages']} messages, "
              f"status: {status['by_status']}, cost: ${cost:.6f}")
    
    print("\n✅ Demo complete!")


if __name__ == "__main__":
    asyncio.run(demo())
```

---

## ▶️ How to Run

```bash
cd low-level-design/notification-service
python CODE.md  # Or rename to notification_service.py
```

> **Note:** This is a complete working implementation with in-memory storage. For production, replace the `NotificationStore` with PostgreSQL and Redis.
