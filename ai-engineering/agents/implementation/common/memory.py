"""
Memory systems for AI agents — short-term, working, and long-term memory.
"""

import time
import json
from typing import List, Dict, Optional, Any
from collections import deque
from dataclasses import dataclass, field


@dataclass
class MemoryEntry:
    """A single memory entry."""
    role: str  # user, assistant, observation, system
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class ShortTermMemory:
    """Sliding window of recent conversation turns."""

    def __init__(self, max_turns: int = 20):
        self.entries: deque = deque(maxlen=max_turns)

    def add(self, role: str, content: str, metadata: Optional[dict] = None):
        self.entries.append(MemoryEntry(
            role=role,
            content=content,
            metadata=metadata or {}
        ))

    def get_recent(self, n: Optional[int] = None) -> str:
        """Get recent entries as formatted text."""
        entries = list(self.entries)
        if n:
            entries = entries[-n:]
        return "\n".join(
            f"[{e.role}]: {e.content[:500]}"
            for e in entries
        )

    def get_token_count(self) -> int:
        """Estimate token count of all entries."""
        return sum(len(e.content.split()) for e in self.entries)

    def clear(self):
        self.entries.clear()


@dataclass
class WorkingMemory:
    """Current task context — goal, progress, intermediate results."""

    current_goal: str = ""
    completed_steps: List[str] = field(default_factory=list)
    remaining_steps: List[str] = field(default_factory=list)
    intermediate_results: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def progress_summary(self) -> str:
        """Summarize current progress."""
        parts = [f"Goal: {self.current_goal}"]
        if self.completed_steps:
            parts.append(f"Completed: {len(self.completed_steps)} steps")
        if self.remaining_steps:
            parts.append(f"Remaining: {len(self.remaining_steps)} steps")
        if self.errors:
            parts.append(f"Errors: {len(self.errors)}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "current_goal": self.current_goal,
            "completed_steps": self.completed_steps,
            "remaining_steps": self.remaining_steps,
            "intermediate_results": self.intermediate_results,
            "errors": self.errors,
        }


class LongTermMemory:
    """Persistent memory stored across sessions."""

    def __init__(self, backend: str = "memory"):
        self.backend = backend
        self.store: Dict[str, dict] = {}

    def remember(self, key: str, value: Any, ttl: Optional[int] = None):
        """Store a fact with optional TTL (seconds)."""
        self.store[key] = {
            "value": value,
            "expires": time.time() + ttl if ttl else None,
            "created": time.time(),
        }

    def recall(self, key: str) -> Optional[Any]:
        """Retrieve a stored fact if not expired."""
        entry = self.store.get(key)
        if entry is None:
            return None
        if entry["expires"] and time.time() > entry["expires"]:
            del self.store[key]
            return None
        return entry["value"]

    def forget(self, key: str):
        self.store.pop(key, None)

    def clear(self):
        self.store.clear()

    def get_all(self) -> dict:
        """Get all non-expired entries."""
        now = time.time()
        return {
            k: v["value"]
            for k, v in self.store.items()
            if v["expires"] is None or now < v["expires"]
        }


class AgentMemory:
    """Combined memory system for an agent."""

    def __init__(self, user_id: str = "default"):
        self.short_term = ShortTermMemory()
        self.working = WorkingMemory()
        self.long_term = LongTermMemory()

    def get_context(self) -> str:
        """Assemble full context for the LLM."""
        parts = []

        # Long-term memory
        facts = self.long_term.get_all()
        if facts:
            parts.append("[Known Facts]:")
            for k, v in facts.items():
                parts.append(f"  {k}: {v}")

        # Working memory
        if self.working.current_goal:
            parts.append(f"[Current Task]: {self.working.current_goal}")
            parts.append(f"[Progress]: {self.working.progress_summary()}")

        # Conversation history
        conversation = self.short_term.get_recent()
        parts.append(f"[Conversation]:\n{conversation}")

        return "\n\n".join(parts)

    def add_conversation_turn(self, role: str, content: str):
        self.short_term.add(role, content)
