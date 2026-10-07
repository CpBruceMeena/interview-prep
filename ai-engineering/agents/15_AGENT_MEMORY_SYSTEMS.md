# 🧠 Agent Memory Systems — Deep Dive

> **Category:** AI Engineering — Memory Architectures  
> **Target Level:** Staff/Principal Engineer  
> **Why this matters:** Without a deliberate memory design, agents lose track of long tasks, make users repeat themselves, and repeat their own mistakes. With a careless one, they leak data between users and faithfully remember injected instructions.  
> **Reviewed:** October 2026

!!! tip "30-second answer"
    LLMs are stateless; "memory" is whatever you choose to put back into the context window. Split it by lifetime: **in-context** (recent turns, compacted or summarized as the window fills), **working/task state** (structured, checkpointed per run, e.g. a LangGraph checkpointer per `thread_id`), and **long-term** (cross-session facts, preferences and past episodes in a store, retrieved on demand). The hard parts are not storage but **policy**: what to write (and who decides: the app, or the model via a memory tool), how to update or expire conflicting facts, how to retrieve only what's relevant within a token budget, and how to keep it scoped per user/tenant and safe from memory poisoning.

---

## Table of Contents

1. [Why Memory Matters](#1-why-memory-matters)
2. [The Four Memory Types](#2-the-four-memory-types)
3. [Short-Term (Working) Memory](#3-short-term-working-memory)
4. [Long-Term Memory — Storage Backends](#4-long-term-memory-storage-backends)
5. [Episodic Memory — Learning from Experience](#5-episodic-memory-learning-from-experience)
6. [Procedural Memory — Learned Behaviors](#6-procedural-memory-learned-behaviors)
7. [Memory Retrieval Strategies](#7-memory-retrieval-strategies)
8. [Hybrid Memory Architectures](#8-hybrid-memory-architectures)
9. [Memory in Multi-Agent Systems](#9-memory-in-multi-agent-systems)
10. [Memory Evaluation & Debugging](#10-memory-evaluation-debugging)
11. [Production Considerations](#11-production-considerations)
12. [Interview Questions](#12-interview-questions)

---

## 1. Why Memory Matters

### The Three Memory Failure Modes

```
Failure 1: Context Window Overflow
  "The agent had a 30-turn conversation. By turn 20, it forgot the user's
  original request. It started answering a different question."

Failure 2: No Cross-Session Learning
  "Every conversation starts fresh. The user tells the agent their preferences
  every single time. The agent never remembers past resolutions."

Failure 3: No Error Learning
  "The agent made the same mistake 50 times because it had no way to
  remember 'last time I tried approach X, it failed'."
```

### What Good Memory Enables

| Capability | Without Memory | With Memory |
|------------|----------------|-------------|
| Multi-turn conversation | Forgets after context limit | Maintains full context via summarization |
| User preferences | Ask every session | Recall from long-term store |
| Learning from mistakes | Repeats errors | Consults episodic memory |
| Multi-step tasks | Loses track of progress | Working memory tracks sub-task state |
| Personalization | One-size-fits-all | Tailored to user history |

---

## 2. The Four Memory Types

```
┌─────────────────────────────────────────────────────────────┐
│                    AGENT MEMORY SYSTEM                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  SHORT-TERM MEMORY (STM)                                │ │
│  │  ├─ Sliding window of recent turns                      │ │
│  │  ├─ Summarized context beyond window                    │ │
│  │  └─ Token budget: what fits in context                  │ │
│  └──────────────────────┬──────────────────────────────────┘ │
│                         │                                     │
│  ┌──────────────────────▼──────────────────────────────────┐ │
│  │  WORKING MEMORY (WM)                                    │ │
│  │  ├─ Current goal and sub-tasks                          │ │
│  │  ├─ Intermediate results                                │ │
│  │  ├─ Pending/blocked actions                             │ │
│  │  └─ Task progress tracker                               │ │
│  └──────────────────────┬──────────────────────────────────┘ │
│                         │                                     │
│  ┌──────────────────────▼──────────────────────────────────┐ │
│  │  LONG-TERM MEMORY (LTM)                                 │ │
│  │  ├─ User preferences & facts (key-value)                │ │
│  │  ├─ Conversation summaries (vector store)               │ │
│  │  ├─ Knowledge graph (structured facts)                  │ │
│  │  └─ TTL-based expiration                                │ │
│  └──────────────────────┬──────────────────────────────────┘ │
│                         │                                     │
│  ┌──────────────────────▼──────────────────────────────────┐ │
│  │  EPISODIC & PROCEDURAL MEMORY (EM/PM)                   │ │
│  │  ├─ Past resolution patterns                            │ │
│  │  ├─ Learned tool-use workflows                          │ │
│  │  ├─ Error patterns and avoidances                       │ │
│  │  └─ Outcome-based memory reinforcement                  │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 Where Memory Lives in 2026: Build vs Use What's There

| Need | Off-the-shelf options | Notes |
|------|----------------------|-------|
| Keep a long agent run inside the window | Server-side **compaction** and **context editing** (clearing old tool results) on the Anthropic API; summarization middleware in LangChain v1 | Cheaper and simpler than hand-rolled summarizers; keep raw history in your own store |
| Resume a conversation or run | **Checkpointers** (LangGraph Postgres/Redis savers), OpenAI **Conversations API** / `previous_response_id` | Thread-scoped state, not cross-session memory |
| Cross-session facts per user | LangGraph **Store** (namespaced key-value + semantic search), your own Postgres/pgvector table | Namespace by tenant and user |
| Model-managed notes | Anthropic **memory tool** (the model reads and writes files in a `/memories` directory your code backs), "notes file" patterns in coding agents | The model decides what is worth remembering; you control storage and access |
| Dedicated memory layers | Letta (MemGPT lineage: self-editing memory blocks), Mem0 (fact extraction and update), Zep/Graphiti (temporal knowledge graph) | Useful when memory is the product; another dependency otherwise |

The patterns in the rest of this page are what these tools implement; know them so you can choose and debug, not necessarily to rebuild them.

---

## 3. Short-Term (Working) Memory

### Sliding Window Strategy

```python
class SlidingWindowMemory:
    """Manages the in-context conversation window."""
    
    def __init__(self, max_tokens: int = 8000, reserve_tokens: int = 2000):
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens  # Reserved for tools, system prompt
        self.turns: List[Turn] = []
        self.summary: Optional[str] = None
    
    def add_turn(self, turn: Turn):
        self.turns.append(turn)
        self._maybe_trim()
    
    def _maybe_trim(self):
        """Trim conversation to fit within token budget."""
        total_tokens = count_tokens(self.turns)
        budget = self.max_tokens - self.reserve_tokens
        
        evicted = []
        while total_tokens > budget and len(self.turns) > 2:
            # Remove oldest turns (collect them; one summarization call per
            # trim, not one LLM call per evicted turn)
            evicted.append(self.turns.pop(0))
            total_tokens = count_tokens(self.turns)
        
        if evicted:
            text = "\n".join(str(t) for t in evicted)
            prior = f"Summary so far:\n{self.summary}\n\n" if self.summary else ""
            self.summary = self._summarize(prior + "New turns:\n" + text)
    
    def _summarize(self, content: str) -> str:
        """Use LLM to summarize old conversation turns."""
        return llm.call(f"Summarize this conversation concisely:\n{content}")
    
    def get_context(self) -> str:
        """Returns: summary (if exists) + recent turns."""
        parts = []
        if self.summary:
            parts.append(f"[Previous Conversation]: {self.summary}")
        parts.append(str(self.turns))
        return "\n\n".join(parts)
```

Trim on **turn boundaries** and never split a tool call from its result (providers reject a tool call without its matching result). Keep the full raw transcript in storage; only the *prompt* is summarized.

### Token Budget Allocation

Current frontier models have context windows from ~200K to ~1M tokens, but a budget still matters: you pay for every input token on every turn, latency grows with input size, and models get worse at using facts buried in very long contexts. An illustrative budget for a deliberately small working set:

```python
# Illustrative working-set budget of 32K tokens (even on a larger window):
CONTEXT_BUDGET = {
    "system_instructions": 1000,    # 3%
    "tools_and_schemas": 4000,     # 12.5%
    "long_term_memory": 2000,      # 6%
    "conversation_history": 15000,  # 47%
    "current_task": 1000,           # 3%
    "agent_scratchpad": 5000,       # 16%
    "reserve": 4000,                # 12.5%
}
# Total: 32,000 tokens
```

### Summarization Strategies

| Strategy | Approach | Pros | Cons |
|----------|----------|------|------|
| **Chunk-summarize** | Summarize oldest turns in batches | Simple, reliable | May lose important details |
| **Recursive summarize** | Re-summarize previous summary + new turns | Maintains coherent narrative | Summary drift over time |
| **Rolling window** | Keep last N turns, drop the rest | Zero cost | Loses all older context |
| **Importance-weighted** | Rate each turn for importance, drop lowest | Preserves critical info | Complex, needs LLM call per turn |
| **Hybrid** | Summarize old + keep recent raw | Best balance | Parameter tuning needed |

### Working Memory Structure

```python
@dataclass
class WorkingMemory:
    """Scoped to a single task or session."""
    
    # Task state
    goal: str                             # Original user goal
    sub_tasks: List[SubTask]              # Remaining sub-tasks
    completed_steps: List[str]            # What's been done
    
    # Execution state
    current_action: Optional[str]         # What's happening now
    last_tool_result: Optional[str]       # Most recent observation
    errors_encountered: List[Error]       # Failures this session
    
    # Ephemeral scratchpad
    notes: List[str]                      # Agent's own notes mid-task
    pending_decisions: List[str]          # Things to decide later
    
    def progress_summary(self) -> str:
        done = len(self.completed_steps)
        total = done + len(self.sub_tasks)
        return f"Progress: {done}/{total} steps. Current: {self.current_action}"
```

---

## 4. Long-Term Memory — Storage Backends

### Storage Backend Comparison

Latencies are typical orders of magnitude within one region, not benchmarks.

| Backend | Best For | Read Speed | Write Speed | Query Type | Persistence |
|---------|----------|------------|-------------|------------|-------------|
| **Redis** | KV facts, session state | <1ms | <1ms | Exact key lookup | Optional (RDB/AOF) |
| **PostgreSQL** | Structured user data, preferences | 1-5ms | 1-5ms | SQL queries | Durable |
| **Vector DB (Pinecone, Weaviate, Qdrant) or pgvector** | Semantic search over memories | 5-20ms | 10-50ms | Similarity search (+ metadata filters) | Durable |
| **SQLite** | Local/embedded, on-premise | <1ms | <1ms | SQL | File-based |
| **S3/GCS** | Large blobs, conversation archives | 50-200ms | 50-200ms | Metadata + content | Durable |

### Redis — Fast KV Memory

```python
class RedisMemory:
    """Fast key-value memory for user preferences and session state.

    One HASH per user: recall_all is a single HGETALL instead of a KEYS scan
    (KEYS is O(N) over the whole keyspace and blocks Redis).
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.default_ttl = 86400 * 30  # 30 days
    
    def _key(self, user_id: str) -> str:
        return f"memory:{user_id}"
    
    async def remember(self, user_id: str, key: str, value: Any, ttl: int = None):
        """Store a fact about a user."""
        await self.redis.hset(self._key(user_id), key, json.dumps(value))
        # Per-field TTL needs Redis 7.4+ (HEXPIRE); otherwise the TTL applies
        # to the user's whole hash.
        await self.redis.hexpire(self._key(user_id), ttl or self.default_ttl, key)
    
    async def recall(self, user_id: str, key: str) -> Optional[Any]:
        """Retrieve a stored fact."""
        data = await self.redis.hget(self._key(user_id), key)
        return json.loads(data) if data else None
    
    async def recall_all(self, user_id: str) -> Dict[str, Any]:
        """Get all memories for a user."""
        raw = await self.redis.hgetall(self._key(user_id))
        return {k: json.loads(v) for k, v in raw.items()}
    
    async def forget(self, user_id: str, key: str):
        """Explicitly remove a memory."""
        await self.redis.hdel(self._key(user_id), key)
```

### Vector Store — Semantic Memory

```python
class VectorMemory:
    """Semantic search over past conversations, facts, and resolutions."""
    
    def __init__(self, collection_name: str = "agent_memories"):
        self.client = WeaviateClient()  # Or Pinecone, Qdrant, Chroma
        self.collection = collection_name
        self.embedder = EmbeddingModel()
    
    async def store(
        self,
        user_id: str,
        content: str,
        metadata: Dict[str, Any],
        memory_type: str = "conversation"
    ):
        """Store a memory with semantic embedding."""
        embedding = await self.embedder.embed(content)
        
        await self.client.insert(
            collection=self.collection,
            vector=embedding,
            properties={
                "user_id": user_id,
                "content": content,
                "type": memory_type,  # conversation, fact, resolution, preference
                "timestamp": time.time(),
                **metadata
            }
        )
    
    async def search(
        self,
        query: str,
        user_id: str,                 # required: never search across users by default
        memory_type: str = None,
        top_k: int = 5,
        score_threshold: float = 0.7
    ) -> List[Memory]:
        """Search memories by semantic similarity."""
        query_embedding = await self.embedder.embed(query)
        
        # Build filter (tenant/user scoping is a security control, not an
        # optimization: an unfiltered search can return another user's memories)
        filters = {"user_id": user_id}
        if memory_type:
            filters["type"] = memory_type
        
        results = await self.client.search(
            collection=self.collection,
            vector=query_embedding,
            filters=filters,
            top_k=top_k,
            threshold=score_threshold
        )
        
        return [
            Memory(
                content=r.properties["content"],
                score=r.score,
                metadata=r.properties
            )
            for r in results
        ]
```

### PostgreSQL — Structured Memory

```sql
-- Schema for structured long-term memory (PostgreSQL + pgvector)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE agent_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    memory_type VARCHAR(50) NOT NULL,  -- 'preference', 'fact', 'resolution', 'conversation'
    key VARCHAR(255),
    value JSONB NOT NULL,
    embedding VECTOR(1536),            -- dimension is fixed by your embedding model
    source VARCHAR(64),                -- who wrote it: 'user_stated', 'extracted', 'agent'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    importance_score REAL DEFAULT 0.5
);

-- A partial unique constraint must be a unique INDEX (a table constraint
-- can't have a WHERE clause)
CREATE UNIQUE INDEX uq_memories_user_key
    ON agent_memories (tenant_id, user_id, key) WHERE key IS NOT NULL;
CREATE INDEX idx_memories_user ON agent_memories (tenant_id, user_id, memory_type);
CREATE INDEX idx_memories_expires ON agent_memories (expires_at) WHERE expires_at IS NOT NULL;
-- HNSW (pgvector 0.5+) is the usual default: better recall/latency than
-- IVFFlat and no need to build after loading data. Filter by user first.
CREATE INDEX idx_memories_embedding ON agent_memories USING hnsw (embedding vector_cosine_ops);
```

---

## 5. Episodic Memory — Learning from Experience

### What is Episodic Memory?

Episodic memory stores **past experiences** — what the agent did, what the outcome was, and what could be learned. This is different from long-term memory (which stores facts) because it stores **sequences of events**.

```python
@dataclass
class Episode:
    """A complete past resolution that can be referenced."""
    episode_id: str
    problem_summary: str          # What the user asked
    steps_taken: List[Step]       # What the agent did
    outcome: str                  # success, partial, failed
    user_feedback: Optional[float]  # Rating if available
    tags: List[str]               # For categorization
    embedding: List[float]        # For similarity search
    timestamp: float

class EpisodicMemory:
    """Store and retrieve past resolution patterns."""
    
    async def store_episode(self, task: Task, result: Result, feedback: float = None):
        """Save a completed task as an episode."""
        episode = Episode(
            episode_id=str(uuid.uuid4()),
            problem_summary=task.summary(),
            steps_taken=task.steps,
            outcome=result.status,
            user_feedback=feedback,
            tags=self._extract_tags(task, result),
            embedding=await self._embed(task.summary()),
            timestamp=time.time()
        )
        await self._save(episode)
    
    async def find_similar_episode(
        self, problem: str, min_score: float = 0.8
    ) -> Optional[Episode]:
        """Find a past resolution similar to the current problem."""
        embedding = await self._embed(problem)
        results = await self.vector_db.search(
            collection="episodes",
            vector=embedding,
            top_k=1,
            threshold=min_score
        )
        if results:
            return self._hydrate(results[0])
        return None
    
    async def get_lessons_for_tag(self, tag: str) -> List[str]:
        """Get lessons learned from episodes with a specific tag."""
        episodes = await self._find_by_tag(tag)
        lessons = []
        for ep in episodes:
            # A lesson is about the APPROACH, in the context of the problem;
            # "avoid <problem>" teaches nothing.
            approach = " → ".join(s.tool_name for s in ep.steps_taken)
            if ep.outcome == "failed" and ep.failure_reason != "transient":
                lessons.append(f"For '{ep.problem_summary}', {approach} failed: {ep.failure_reason}")
            elif ep.outcome == "success" and ep.user_feedback and ep.user_feedback >= 4:
                lessons.append(f"For '{ep.problem_summary}', {approach} worked")
        return lessons
    
    def _extract_tags(self, task: Task, result: Result) -> List[str]:
        """Auto-tag based on tools used and domain."""
        tags = set()
        for step in task.steps:
            tags.add(f"tool:{step.tool_name}")
            tags.add(f"domain:{task.domain}")
        if result.status == "failed":
            tags.add("avoid")
        return list(tags)
```

### Episodic Memory in the Agent Loop

```python
class MemoryAwareAgent:
    """Agent that consults episodic memory before acting."""
    
    async def run(self, task: str) -> str:
        # Step 0: Check episodic memory for similar problems
        similar = await self.episodic_memory.find_similar_episode(task)
        
        if similar and similar.outcome == "success":
            # Bootstrap from past success
            context = (
                f"[Previous Resolution]: A similar problem was solved before.\n"
                f"Problem: {similar.problem_summary}\n"
                f"Approach: {similar.steps_taken}\n"
                f"Outcome: {similar.outcome}\n"
                f"Consider this approach, but adapt to the current situation."
            )
        elif similar and similar.outcome == "failed":
            # Avoid past mistakes
            context = (
                f"[Previous Attempt]: A similar problem was attempted before.\n"
                f"Problem: {similar.problem_summary}\n"
                f"Attempted: {similar.steps_taken}\n"
                f"Outcome: FAILED\n"
                f"Try a DIFFERENT approach."
            )
        else:
            context = ""
        
        # Normal ReAct loop with memory context
        result = await self.react_loop(task, episodic_context=context)
        
        # Store this episode
        await self.episodic_memory.store_episode(task, result)
        
        return result
```

Caveats: a past *failure* may have been a transient outage, not a bad approach, so record the failure reason and don't steer away on timeouts. Past episodes can be stale (the API changed) or poisoned, so present them as hints, not instructions. And measure: episodic memory helps only if eval runs show higher task success with it than without.

---

## 6. Procedural Memory — Learned Behaviors

Procedural memory stores **how to do things** — learned workflows, tool-use patterns, and optimized sequences.

### Tool-Use Patterns

```python
class ProceduralMemory:
    """Learned tool-use patterns and workflows."""
    
    def __init__(self):
        # Stored patterns: sequence of tool calls for common tasks
        self.patterns: Dict[str, ToolPattern] = {}
    
    def learn_pattern(self, task_type: str, tool_sequence: List[str], success: bool):
        """Learn a tool-use pattern from experience."""
        if task_type not in self.patterns:
            self.patterns[task_type] = ToolPattern(task_type)
        
        pattern = self.patterns[task_type]
        if success:
            pattern.reinforce(tool_sequence)
        else:
            pattern.weaken(tool_sequence)
    
    def suggest_pattern(self, task_type: str) -> Optional[List[str]]:
        """Suggest the best tool sequence for this task type."""
        pattern = self.patterns.get(task_type)
        if pattern and pattern.confidence > 0.7:
            return pattern.best_sequence
        return None

@dataclass
class ToolPattern:
    task_type: str
    sequences: Dict[str, PatternStats] = field(default_factory=dict)
    
    def reinforce(self, sequence: List[str]):
        key = "→".join(sequence)
        if key in self.sequences:
            self.sequences[key].success_count += 1
        else:
            self.sequences[key] = PatternStats(success_count=1)
    
    def weaken(self, sequence: List[str]):
        key = "→".join(sequence)
        if key in self.sequences:
            self.sequences[key].failure_count += 1
    
    @property
    def confidence(self) -> float:
        if not self.sequences:
            return 0.0
        best = max(self.sequences.values(), key=lambda s: s.success_rate)
        return best.success_rate
    
    @property
    def best_sequence(self) -> Optional[List[str]]:
        if not self.sequences:
            return None
        best_key = max(self.sequences, key=lambda k: self.sequences[k].success_rate)
        return best_key.split("→")
```

---

## 7. Memory Retrieval Strategies

### Retrieval Approaches

```
1. EXACT MATCH — Key-value lookup
   "What is the user's name?" → Direct Redis get
   
2. SEMANTIC SEARCH — Vector similarity
   "What did we discuss about deployment?" → Vector DB query
   
3. HYBRID SEARCH — Combined exact + semantic
   "User preferences for email" → Exact on 'preferences' tag + semantic
   
4. MULTI-HOP RETRIEVAL — Chain queries
   "Find the author who wrote about memory" → Find paper → Find author
   
5. TEMPORAL RETRIEVAL — Time-based
   "What happened in the last session?" → Recent timestamp filter
```

### The RAPID Retrieval Framework

```python
class MemoryRetrieval:
    """
    RAPID: Retrieve, Augment, Prioritize, Inject, Decide
    """
    
    async def get_relevant_memory(self, query: str, user_id: str) -> MemoryContext:
        memories = []
        
        # R — Retrieve from all sources in parallel
        kv_memories = await self.redis.recall_all(user_id)
        semantic_memories = await self.vector_memory.search(query, user_id)
        episodic = await self.episodic_memory.find_similar_episode(query)
        
        # A — Augment with computed relevance
        for mem_type, content in kv_memories.items():
            relevance = self._compute_relevance(query, mem_type)
            memories.append(MemoryItem(content, relevance, "kv"))
        
        for mem in semantic_memories:
            memories.append(MemoryItem(mem.content, mem.score, "semantic"))
        
        # P — Prioritize by relevance score (descending)
        memories.sort(key=lambda m: m.relevance, reverse=True)
        
        # I — Inject top K into context (token budget aware)
        budget = 2000  # tokens for memory
        injected = []
        for mem in memories:
            tokens = count_tokens(mem.content)
            if tokens <= budget:
                injected.append(mem)
                budget -= tokens
        
        # D — Decide if episodic memory suggests a different approach
        if episodic and episodic.score > 0.85:
            injected.insert(0, MemoryItem(
                f"Past resolution: {episodic.content}\nConsider this approach.",
                episodic.score,
                "episodic"
            ))
        
        return MemoryContext(memories=injected)
```

### Context Assembly

```python
def assemble_context(
    memory_context: MemoryContext,
    conversation: str,
    working_memory: WorkingMemory,
    system_instructions: str
) -> str:
    """Assemble the full context for an LLM call."""
    
    sections = []
    
    # System
    sections.append(f"[System Instructions]\n{system_instructions}\n")
    
    # Long-term memory
    if memory_context.memories:
        memory_str = "\n".join(
            f"[{m.memory_type}] {m.content}"
            for m in memory_context.memories
        )
        sections.append(f"[Relevant Memories]\n{memory_str}\n")
    
    # Working memory
    sections.append(f"[Current Task]\n{working_memory.goal}\n")
    sections.append(f"[Progress]\n{working_memory.progress_summary()}\n")
    if working_memory.errors_encountered:
        sections.append(f"[Errors This Session]\n{working_memory.errors_encountered}\n")
    
    # Recent conversation
    sections.append(f"[Conversation]\n{conversation}\n")
    
    return "\n\n---\n\n".join(sections)
```

---

## 8. Hybrid Memory Architectures

### Architecture 1: Two-Tier (Fast + Deep)

```python
class TwoTierMemory:
    """
    Tier 1 (Fast): Redis KV for frequent, simple lookups
    Tier 2 (Deep): Vector DB for semantic search when Tier 1 misses
    """
    
    async def get(self, user_id: str, query: str) -> Optional[str]:
        # Tier 1: Check exact KV match first
        exact = await self.redis.recall_all(user_id)
        if exact and query in exact:
            return exact[query]
        
        # Tier 2: Semantic search
        results = await self.vector_memory.search(query, user_id, top_k=1)
        if results and results[0].score > 0.9:
            return results[0].content
        
        return None
```

### Architecture 2: Three-Tier (Working + Episodic + Semantic)

```python
class ThreeTierMemory:
    """
    Tier 1: Working memory (current session, ephemeral)
    Tier 2: Episodic memory (past sessions, experience-based)
    Tier 3: Semantic memory (knowledge, facts, patterns)
    """
    
    async def get_context(self, user_id: str, query: str, session_id: str) -> str:
        context_parts = []
        
        # Tier 1: Session state (fastest)
        session = await self.session_store.get(session_id)
        if session:
            context_parts.append(f"[Current Session]\n{session.state_summary()}")
        
        # Tier 2: Episodic (similar past experiences)
        episodes = await self.episodic.find_similar(query)
        if episodes:
            context_parts.append(
                f"[Past Experiences]\n" +
                "\n".join(f"- {e.problem_summary} → {e.outcome}" for e in episodes[:3])
            )
        
        # Tier 3: Semantic (broad knowledge)
        semantic = await self.vector_memory.search(query, user_id, top_k=5)
        if semantic:
            context_parts.append(
                f"[Knowledge]\n" +
                "\n".join(f"- {s.content}" for s in semantic)
            )
        
        return "\n\n---\n\n".join(context_parts)
```

### Architecture 3: Importance-Weighted Memory

```python
class ImportanceWeightedMemory:
    """
    Each memory has an importance score (0.0 to 1.0).
    High-importance memories survive context trimming.
    Low-importance memories are dropped first.
    """
    
    async def store(self, content: str, importance: float = None):
        if importance is None:
            importance = await self._estimate_importance(content)
        await self.db.insert({
            "content": content,
            "importance": importance,
            "timestamp": time.time(),
            "access_count": 0
        })
    
    async def get_top_k(self, user_id: str, k: int = 10) -> List[str]:
        """Get the K most important memories FOR THIS USER."""
        return await self.db.query(
            """SELECT content FROM memories
               WHERE user_id = $1
               ORDER BY importance DESC, access_count DESC LIMIT $2""",
            [user_id, k]
        )
    
    async def _estimate_importance(self, content: str) -> float:
        """Use an LLM (structured output) to estimate importance."""
        result = await llm.structured(
            prompt=("Rate how useful this information will be in future "
                    f"conversations with this user:\n{content}"),
            schema={"type": "object",
                    "properties": {"importance": {"type": "number", "minimum": 0, "maximum": 1}},
                    "required": ["importance"]},
        )
        # float(free_text) breaks on "Importance: 0.8 because..."
        return result["importance"]
```

---

## 9. Memory in Multi-Agent Systems

### Shared Memory Pool

```python
class SharedMemoryPool:
    """Memory that multiple agents can read/write."""
    
    def __init__(self, backend: str = "redis"):
        self.backend = self._init_backend(backend)
    
    async def broadcast(self, event: MemoryEvent):
        """Share a memory event across all agents in the system.

        Redis Pub/Sub is fire-and-forget: an agent that is down or slow misses
        events. Use Redis Streams (XADD + consumer groups) or Kafka when
        agents must not lose updates.
        """
        await self.backend.publish("memory_events", event)
    
    async def subscribe(self, agent_id: str, topics: List[str]):
        """Subscribe to memory events relevant to this agent."""
        async for event in self.backend.subscribe("memory_events"):
            if event.topic in topics or event.target_agent == agent_id:
                await self._integrate(event, agent_id)
    
    async def _integrate(self, event: MemoryEvent, agent_id: str):
        """Integrate a memory event into an agent's local memory."""
        if event.type == "episode":
            await self.local_episodic.store(event.data)
        elif event.type == "pattern":
            await self.local_procedural.learn_pattern(
                event.data.task_type,
                event.data.tool_sequence,
                event.data.success
            )
```

### Agent-Specific Memory Isolation

```python
class IsolatedMemory:
    """Each agent gets its own memory namespace."""
    
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.namespace = f"agent:{agent_id}:memory"
    
    async def store(self, key: str, value: Any):
        await redis.hset(self.namespace, key, json.dumps(value))
    
    async def recall(self, key: str) -> Optional[Any]:
        data = await redis.hget(self.namespace, key)
        return json.loads(data) if data else None
```

---

## 10. Memory Evaluation & Debugging

### Memory Metrics

```python
MEMORY_METRICS = {
    "memory_hit_rate": "fraction of memory queries returning relevant results",
    "memory_latency_p95": "p95 latency for memory retrieval (ms)",
    "context_utilization": "fraction of context window actually useful",
    "memory_staleness": "average age of memories retrieved",
    "forgetting_rate": "how quickly low-importance memories are dropped",
}
```

### Debugging Memory Issues

```python
class MemoryDebugger:
    """Debug tool for inspecting agent memory state."""
    
    async def inspect_session(self, session_id: str):
        session = await self.session_store.load(session_id)
        
        print(f"Session: {session_id}")
        print(f"Working Memory: {session.working}")
        print(f"Recent Turns: {len(session.short_term.turns)}")
        print(f"Summary: {session.short_term.summary[:200]}...")
        
        # Check memory usage
        total_tokens = count_tokens(session.working) + count_tokens(session.short_term)
        print(f"Total Memory Tokens: {total_tokens}/{session.max_tokens}")
        
        # Check if important info was trimmed
        if session.short_term.trimmed_count > 0:
            print(f"⚠️ {session.short_term.trimmed_count} turns were summarized")
    
    async def memory_audit(self, user_id: str):
        """Audit all memories for a user."""
        # List by metadata filter, not by searching with an empty query
        memories = await self.memory_store.list(user_id=user_id)
        
        # Check for duplicates
        contents = [m.content for m in memories]
        duplicates = find_near_duplicates(contents, threshold=0.95)
        if duplicates:
            print(f"Found {len(duplicates)} near-duplicate memories")
        
        # Check for stale memories
        stale = [m for m in memories if m.age_days > 90]
        print(f"Stale memories (>90 days): {len(stale)}")
        
        # Check importance distribution
        importances = [m.importance for m in memories]
        print(f"Importance distribution:")
        print(f"  High (>0.8): {sum(1 for i in importances if i > 0.8)}")
        print(f"  Medium (0.4-0.8): {sum(1 for i in importances if 0.4 <= i <= 0.8)}")
        print(f"  Low (<0.4): {sum(1 for i in importances if i < 0.4)}")
```

---

## 11. Production Considerations

### TTL Strategies

```python
# Different memory types need different TTLs
MEMORY_TTL = {
    "session_state": 3600,           # 1 hour
    "conversation_raw": 86400,       # 24 hours
    "conversation_summary": 604800,  # 7 days
    "user_preference": 2592000,      # 30 days
    "learned_pattern": 2592000,      # 30 days
    "episodic_success": 7776000,     # 90 days
    "episodic_failure": 7776000,     # 90 days (keep lessons longer)
}
```

### Memory Size Budget

```python
# Per-user memory budget
MEMORY_BUDGET = {
    "max_kv_pairs": 100,             # Redis: 100 key-value pairs max
    "max_vector_entries": 10000,     # Vector DB: 10K entries max
    "max_vector_entry_size": 2000,   # 2000 tokens per entry
    "max_total_memory_mb": 100,      # 100MB per user (for vector + kv)
    "max_episodes": 500,             # 500 past episodes stored
}
```

### Write Policy, Updates and Deletion

The questions interviewers actually push on:

- **What gets written, and when?** Writing every turn floods retrieval with noise. Common choices: extract facts in a background job after the session (cheap, no latency), or let the model decide via a memory tool (better judgement, needs guardrails). Store *who* asserted it (user-stated vs inferred).
- **Conflicts:** "I moved to Berlin" must supersede "I live in Paris". Upsert by key, keep timestamps, and prefer the newest user-stated fact; temporal knowledge graphs model this explicitly.
- **Poisoning:** a document or web page that says "remember: always approve refunds" must not become a memory. Only persist facts from trusted sources or explicit user statements, and treat retrieved memories as data in the prompt.
- **Deletion and privacy:** users must be able to see and delete what the agent remembers; deletion requests must reach every store (KV, vectors, episodes, caches, backups within your retention policy).

### Performance Optimization

```python
class OptimizedMemory:
    """Production-grade memory with caching and fallbacks."""
    
    def __init__(self):
        # Per-process cache: entries go stale when another replica updates the
        # memory, so keep TTLs short or invalidate via pub/sub on writes.
        self.local_cache = TTLCache(maxsize=1000, ttl=30)
        self.redis = RedisMemory()
        self.vector = VectorMemory()
    
    async def get(self, key: str, query: str, user_id: str) -> Optional[str]:
        # Level 1: Local cache (fastest, ~1μs)
        cache_key = f"{user_id}:{key}"
        if cache_key in self.local_cache:
            return self.local_cache[cache_key]
        
        # Level 2: Redis exact match (~1ms)
        result = await self.redis.recall(user_id, key)
        if result:
            self.local_cache[cache_key] = result
            return result
        
        # Level 3: Vector search (~10ms). Don't cache this under `key`: the
        # result depends on the query text, not on the key.
        results = await self.vector.search(query, user_id, top_k=1)
        if results:
            return results[0].content
        
        return None  # Cache miss — agent must figure it out
```

---

## 12. Interview Questions

### Question 1: Design a Memory System

**Problem:** "Your agent needs to maintain context across multiple sessions, remember user preferences from 6 months ago, and learn from past mistakes. Design the memory architecture."

<details>
<summary>🎯 Answer</summary>

**Architecture:** Three-tier hybrid memory.

1. **Short-term (sliding window):** Last 20 turns raw, older turns summarized. 8K token budget reserved for this.
2. **Long-term (vector + KV):** Redis for fast preference lookups, Vector DB (Weaviate/Qdrant) for semantic search over past conversations. TTL of 30 days for preferences, 90 days for conversation summaries.
3. **Episodic (experience-based):** Store past task resolutions. On each new task, search for similar past episodes. If matching episode found with successful outcome → bootstrap from it. If failure → avoid that approach.
4. **Memory consolidation:** After each session, summarize key facts into long-term memory. Drop low-importance memories when budget exceeded.

**Key design decisions:**
- Importance-weighted retention: High-importance memories survive trimming
- TTL per memory type (not one-size-fits-all)
- Episodic memory for cross-session learning
- Short-TTL local cache for hot memories, with invalidation on writes
- Per-user scoping on every read, and a user-visible "what I remember" view with delete
- Evaluate it: task success and user-repeat rate with memory on vs off
</details>

### Question 2: Context Window Management

**Problem:** "A conversation has 50 turns with 5 tool calls each and the context is filling up (cost and latency are climbing too). How do you manage this?"

<details>
<summary>🎯 Answer</summary>

**Strategy:** Structured context management with token budgeting.

```python
# Illustrative budget for a 32K working set
CONTEXT_BUDGET = {
    "system_and_tools": 5000,      # 16%
    "working_memory": 2000,        # 6%
    "recent_conversation": 12000,  # 37%
    "summarized_history": 6000,    # 19%
    "long_term_memory": 3000,      # 9%
    "agent_scratchpad": 4000,      # 13%
}
```

**When budget is exceeded:**
1. First: Clear or truncate old **tool results** (usually the bulk of an agent transcript and the least needed later)
2. Then: Trim oldest conversation turns → summarize in batches (or use server-side compaction)
3. Then: Compress summaries (recursive summarization)
4. Then: Drop lowest-importance long-term memories
5. Never: Drop system instructions or tool definitions, and never split a tool call from its result

**Key insights:** Keep the stable prefix (system + tools) byte-identical so **prompt caching** keeps working; editing the system prompt every turn (e.g. to insert a "context remaining" counter) invalidates the cache, so put such notes in a message at the end instead. Some newer models are trained to track their remaining context themselves.
</details>

### Question 3: Memory Retrieval Optimization

**Problem:** "Your vector memory search returns 10 results but only 2 are relevant. The agent wastes context on irrelevant memories. How do you fix this?"

<details>
<summary>🎯 Answer</summary>

**Multi-stage retrieval pipeline:**

1. **Pre-filtering:** Apply metadata filters before vector search (user_id, memory_type, recency)
2. **Hybrid search:** Combine semantic + keyword (BM25) for better relevance
3. **Re-ranking:** After initial search, use a cross-encoder or LLM to re-rank results
4. **Threshold filtering:** Drop results below a similarity score tuned for your embedding model (0.7 below is illustrative; score scales differ between models)
5. **Deduplication:** Remove near-duplicate memories before adding to context
6. **Importance gating:** Only include high-importance memories by default, low-importance only if there's budget

```python
async def search_memories(query, user_id, top_k=5):
    # Stage 1: Hybrid search
    semantic = await vector_search(query, filters={"user_id": user_id})
    keyword = await bm25_search(query, filters={"user_id": user_id})
    
    # Stage 2: Merge and deduplicate
    merged = merge_results(semantic, keyword, weights=[0.7, 0.3])
    
    # Stage 3: Re-rank (cross-encoder)
    reranked = await cross_encoder_rerank(query, merged)
    
    # Stage 4: Filter by threshold and budget
    return [r for r in reranked if r.score > 0.7][:top_k]
```
</details>

### Question 4: Memory in Multi-Tenant Systems

**Problem:** "Design a memory system for a multi-tenant SaaS agent. Each customer has their own data, but the agent should also learn general patterns across customers."

<details>
<summary>🎯 Answer</summary>

**Two-tier memory:**

```
Tier 1: Per-tenant memory (isolated)
  ├── KV: User preferences, session state
  ├── Vector: Tenant-specific conversations, knowledge
  └── Episodic: Past resolutions for this tenant
  
Tier 2: Global memory (shared patterns)
  ├── Patterns: Common workflows across tenants (anonymized)
  ├── Failures: Mistakes to avoid (no PII)
  └── Optimizations: Learned efficiency improvements
```

**Privacy guarantees:**
- Tenant data NEVER leaks across boundaries
- Global memory stores only anonymized patterns
- No PII in global memory
- TTL-based purging per tenant contract

**Isolation implementation:**
```python
# Each query is scoped to the tenant
await memory.search(query, tenant_id=tenant_id, user_id=user_id)
# Cross-tenant patterns have tenant_id = "__global__"
```
</details>

---

## Summary

| Memory Type | Storage | Retrieval | TTL | Use Case |
|-------------|---------|-----------|-----|----------|
| **Short-term** | In-context | Sliding window | Session | Recent conversation |
| **Working** | In-context | Structured fields | Task | Current goal, progress |
| **Long-term (KV)** | Redis | Exact key lookup | 30 days | User preferences |
| **Long-term (Vector)** | Vector DB | Semantic search | 90 days | Past conversations |
| **Episodic** | Vector DB | Similarity match | 90 days | Learning from experience |
| **Procedural** | Config/DB | Pattern match | 30 days | Learned workflows |
