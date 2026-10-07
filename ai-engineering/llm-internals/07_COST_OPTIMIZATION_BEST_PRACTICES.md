# 💸 LLM Cost Optimization — Practical Guide

> **How to cut LLM spend without cutting quality: the levers in order of payoff (caching, batching, context hygiene, output control, model and effort choice), how to measure, and Claude Code–specific habits.**

**30-second answer:** Measure first (`usage` per request, cost per *completed task*). Then take the free wins: prompt caching for any repeated prefix, the Batch API (50% off) for anything that can wait, and keeping context small (trim tool output, compact or reset long sessions). Then trade-offs: lower `effort` or a cheaper model where evals show quality holds, and shorter outputs (output is 5× the input price on Claude). Optimise per route, verify with evals, and remember a cheaper request that needs more retries isn't cheaper.

!!! info "Prices on this page"
    Claude API rates were checked on the [pricing page](https://platform.claude.com/docs/en/about-claude/pricing) on **7 Oct 2026**. Prices and model names change every few months. Re-check before quoting, and compare other providers using their own pricing pages. Worked examples use round example rates ($3 input / $15 output per million tokens) so the arithmetic is easy to follow.

---

## 1. THE COST LANDSCAPE

### Claude API Pricing (per million tokens, 7 Oct 2026)

| Model | Input | Output | Cache read | Batch (in / out) | Typical use |
|-------|-------|--------|-----------|------------------|-------------|
| **Claude Fable 5.1** | $10 | $50 | $0.25 | $5 / $25 | Hardest reasoning, long-horizon agents |
| **Claude Opus 5.5** | $4 | $20 | $0.20 | $2 / $10 | Anthropic's default recommendation; agentic coding |
| **Claude Sonnet 5.5** | $2 | $10 | $0.20 | $1 / $5 | High-volume production, everyday coding |
| **Claude Haiku 4.5** | $1 | $5 | $0.10 | $0.50 / $2.50 | Classification, extraction, cheap sub-agents |

The structure is what lasts:

- **Output is 5× input** on every current Claude model, and **thinking tokens bill as output**.
- **Cache writes** cost 1.25× input (5-minute TTL) or 2× (1-hour); **cache reads** 0.1× on most models (less on Opus 5.5 and Fable 5.1).
- **Batch API**: 50% off input and output; stacks with caching.
- **Long context**: no premium on Claude 4.6+ models (1M window at the standard rate).
- **Newer tokenizer** (Opus 4.7 and later): roughly 1.0–1.35× the tokens for the same text, so compare *cost per task*, not price per token.
- Other providers (OpenAI, Google, DeepSeek, open-weight hosts) price differently and change often; benchmark them on your own eval set.

---

## 2. MODEL AND EFFORT SELECTION

Choosing the model is a big lever, but on current Claude models **effort** is often the first one to try: `output_config.effort` (`low` → `max`) trades thoroughness against tokens *within* a model.

### The Tiered Strategy

```
  Task                                   Start with
  ─────────────────────────────────────────────────────────────────────
  Classification, extraction, routing    Haiku, or Sonnet at low effort
  Chat, summarisation, simple edits      Sonnet at low/medium effort
  Everyday coding, tool-using agents     Sonnet or Opus at medium/high
  Hard debugging, architecture, research Opus at high, or Fable
```

### How to Choose in Practice

1. Build an eval set from real traffic for the route.
2. Run the most capable model you'd consider at a lower effort, and a cheaper model at its default. Often the newest large model at low effort matches an older one at high effort.
3. Pick the cheapest configuration that clears your quality bar, measured as **cost per successfully completed task**.
4. Route per task type, not globally. A multi-model cascade adds complexity and splits prompt caches (caches are per model); measure the single-model option first.

```python
# Per-route configuration, chosen from eval results rather than intuition.
ROUTES = {
    "classify_ticket": {"model": "claude-haiku-4-5", "effort": None},   # Haiku doesn't support effort
    "summarise_doc":   {"model": "claude-sonnet-5-5", "effort": "low"},
    "code_review":     {"model": "claude-opus-5-5", "effort": "medium"},
    "incident_rca":    {"model": "claude-opus-5-5", "effort": "high"},
}

def request_params(route: str) -> dict:
    cfg = ROUTES[route]
    params = {"model": cfg["model"]}
    if cfg["effort"]:
        params["output_config"] = {"effort": cfg["effort"]}
    return params
```

---

## 3. PROMPT CACHING — USUALLY THE BIGGEST SAVER

Any request that repeats a prefix (system prompt, tool definitions, a shared document, an agent's growing history) should cache it.

### How the Math Works (example rates: input $3, write $3.75, read $0.30 per M)

```
Prefix (system + tools) = 4,500 tokens, question = 500 tokens, 3 requests within 5 minutes

Without caching:
  3 × 5,000 × $3/M                                    = $0.0450

With caching:
  Request 1: 4,500 × $3.75/M (write) + 500 × $3/M     = $0.0184
  Request 2: 4,500 × $0.30/M (read)  + 500 × $3/M     = $0.0029
  Request 3: same as request 2                        = $0.0029
                                                        ───────
                                                        $0.0241  (-46%)

At 100 requests: $1.50 uncached vs ~$0.30 cached (-80%)
```

The first request costs more; each hit is far cheaper. With the 5-minute TTL a single hit pays back the write.

### Doing It Right

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-sonnet-5-5",
    max_tokens=4000,
    cache_control={"type": "ephemeral"},     # automatic: caches up to the last cacheable block
    tools=TOOLS,                             # rendered first: keep the list and order stable
    system=[
        {
            "type": "text",
            "text": LONG_SYSTEM_PROMPT + PROJECT_CONVENTIONS,   # stable content only
            "cache_control": {"type": "ephemeral"},            # explicit breakpoint on the static prefix
        }
    ],
    messages=history + [{"role": "user", "content": question}],  # dynamic content last
)
u = response.usage
print(u.cache_creation_input_tokens, u.cache_read_input_tokens, u.input_tokens)
```

Note that `system` is a top-level parameter, not a message with `role: "system"` at the start of `messages`.

| ✅ Cache | ❌ Keep after the last breakpoint |
|----------|----------------------------------|
| Tool definitions, system prompt | The newest user message |
| Project conventions, reference docs | Per-request IDs, timestamps |
| Conversation history and earlier tool results (agent loops) | Anything that differs between otherwise-identical requests |

### Cache Rules That Trip People Up

- **Prefix-exact, in order tools → system → messages.** Change one byte early and everything after it misses.
- **TTL:** 5 minutes (refreshed by every hit) or 1 hour (2× write cost). Pick by the gap between requests.
- **Minimum length:** 512–4,096 tokens depending on the model; shorter prefixes silently don't cache.
- **Up to 4 explicit breakpoints** per request.
- **Verify:** if `cache_read_input_tokens` stays 0, look for timestamps, unsorted JSON, changing tool lists, or a model switch.

---

## 4. CONTEXT MANAGEMENT

In agents, the biggest cost driver is a conversation that grows without bound: every call resends it.

### The Cost of Conversation Growth (example rate $3/M input, uncached)

```
Call 1:    5,000 tokens  →  $0.015
Call 10:  30,000 tokens  →  $0.090
Call 50: 150,000 tokens  →  $0.450  per call, 30× the first

With caching, most of each call is billed at the cache-read rate,
so call 50 costs about $0.06 (145K cached reads + 5K new tokens written). Still: smaller context is
cheaper, faster, and more accurate (context rot).
```

### Strategies

**Compact, don't just accumulate.** Summarise old turns when the context passes a threshold. The Claude API offers server-side compaction (beta) and context editing that clears old tool results; Claude Code auto-compacts and supports `/compact <focus>`.

```python
# Client-side version of the idea (server-side compaction does this for you).
if count_tokens(messages) > COMPACT_AT:
    summary = summarise(messages[:-KEEP_RECENT])          # one cheap model call
    messages = [{"role": "user", "content": f"<summary>{summary}</summary>"}] + messages[-KEEP_RECENT:]
    # Keep tool_use/tool_result pairs together when choosing the cut point.
```

**Reset for unrelated work.** Starting a new conversation (Claude Code: `/clear`) costs nothing; carrying 100K tokens of irrelevant history into every call does.

**Trim tool results at the source.** Return the matching lines, not the file; paginate; cap command output; summarise logs in a sub-agent.

**Offload noisy work.** A sub-agent with its own context reads the 10,000-line log and returns ten lines.

---

## 5. OUTPUT LENGTH CONTROL

Output costs 5× input, and long outputs are slow (decode is sequential).

### The Cost of Verbosity (example rate $15/M output)

```
Concise (50 tokens):      $0.00075   (0.075 cents)
Verbose (500 tokens):     $0.0075    (0.75 cents)
Very verbose (2,000):     $0.030     (3 cents, 40× concise)

× 1,000 requests/day:     $0.75   vs   $7.50   vs   $30.00 per day
```

### Levers

| Lever | Notes |
|-------|-------|
| **Lower `effort`** | Fewer thinking tokens, fewer and more consolidated tool calls, terser answers |
| **Instructions** | "Answer in at most three sentences", "Return only the code block" |
| **Structured outputs** | `output_config.format` with a JSON schema returns exactly the fields you need |
| **`max_tokens`** | A safety cap, not a style control: hitting it truncates mid-answer (`stop_reason: "max_tokens"`) and you pay for a retry |
| **Show, don't tell** | An example of the desired terse format beats "be concise" |

---

## 6. TOOL CALL OPTIMIZATION

Each tool call is another round-trip carrying the full context.

### The Hidden Cost (example rate $3/M input, uncached)

```
Sequential (8 calls)                     Batched (4 calls)
  1. Initial request    5,000  $0.015      1. Initial request        5,000  $0.015
  2. Read main.py       6,000  $0.018      2. Read 3 files at once   7,000  $0.021
  3. Read models.py     7,000  $0.021      3. Edit main + models     9,000  $0.027
  4. Read schemas.py    8,000  $0.024      4. Run tests + respond   11,000  $0.033
  5. Edit main.py       9,000  $0.027                                ──────────────
  6. Edit models.py    10,000  $0.030                                       $0.096
  7. Run tests         11,000  $0.033
  8. Final response    12,000  $0.036
                              ──────
                              $0.204                                  (-53%)
```

How to get there:

- **Parallel tool calls:** the model can request several tools in one turn; return all results in one user message (splitting them across messages discourages parallel calls).
- **Tools that return exactly what's needed:** `search_code("class User")` beats reading a 500-line file; a `get_failing_tests` tool beats dumping the full test log.
- **Fewer, well-described tools:** every tool definition is input tokens on every call; for large tool sets use tool search / deferred loading so only names are sent until needed.
- **Programmatic tool calling** (Claude API): the model writes code that calls your tools in a loop inside code execution, so intermediate results don't flow through the context.

---

## 7. BATCH PROCESSING

Two different ideas share the word "batch":

### 7.1 The Message Batches API (asynchronous, 50% off)

For work that doesn't need an answer now (evals, backfills, nightly classification, document processing), submit up to tens of thousands of requests in one batch; results arrive asynchronously (most within an hour, at most 24 hours) at **half price**, and caching discounts still apply.

```python
batch = client.messages.batches.create(
    requests=[
        {
            "custom_id": f"ticket-{t.id}",
            "params": {
                "model": "claude-haiku-4-5",
                "max_tokens": 256,
                "system": CLASSIFIER_PROMPT,          # identical across requests → cacheable
                "messages": [{"role": "user", "content": t.text}],
            },
        }
        for t in tickets
    ]
)
# Poll client.messages.batches.retrieve(batch.id) until processing_status == "ended",
# then stream client.messages.batches.results(batch.id). Results can arrive in any
# order: match them by custom_id, never by position.
```

### 7.2 Packing Several Items into One Prompt

Putting 20 short items in one request saves the repeated system prompt and per-request overhead, but:

| Pack items together? | When |
|---------------------|------|
| ✅ Yes | Many tiny, independent, same-instruction items (translate phrases, tag short texts) |
| ❌ No | Items that need careful individual attention, long items, anything where one bad item shouldn't spoil the rest |

Quality tends to drop as packs grow (items get skipped or blended), so measure accuracy per pack size, and prefer the Batch API plus caching when each item deserves its own request.

---

## 8. PRACTICAL BUDGET CONTROL

### Measure from `usage`, Not Estimates

```python
from dataclasses import dataclass


def alert(msg: str) -> None:
    print(msg)  # wire to your paging/alerting system


PRICES = {  # USD per million tokens; load from config and keep in sync with the pricing page
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_write_5m": 2.50, "cache_read": 0.20},
}

@dataclass
class CostTracker:
    daily_budget_usd: float
    spent_today: float = 0.0

    def record(self, model: str, usage) -> float:
        p = PRICES[model]
        cost = (
            usage.input_tokens * p["in"]
            + (usage.cache_creation_input_tokens or 0) * p["cache_write_5m"]
            + (usage.cache_read_input_tokens or 0) * p["cache_read"]
            + usage.output_tokens * p["out"]
        ) / 1_000_000
        self.spent_today += cost
        if self.spent_today > 0.8 * self.daily_budget_usd:
            alert(f"LLM spend at {self.spent_today / self.daily_budget_usd:.0%} of daily budget")
        return cost
```

(`input_tokens` excludes cached tokens; the three input fields add up to the total input.) In production also: tag requests by route/customer, use workspace spend limits in the Claude Console, and track cost per completed task, cache hit rate, and retry rate on a dashboard.

### Reference Points

- Anthropic's Claude Code cost docs (checked Oct 2026): across enterprise deployments the average is **about $13 per developer per active day** and **$150–250 per developer per month**, with 90% of users under $30 per active day. Your numbers depend on model, codebase and habits; pilot and measure.
- Per-request costs scale with context: at example rates, a 2K-token Q&A is under a cent, a 50K-input agent task is tens of cents, a long multi-hour agent session can be dollars.

---

## 9. LOCAL AND OPEN-WEIGHT MODELS

Open-weight models (Llama, Qwen, Gemma, Mistral, DeepSeek families and others) can run locally or on your own GPUs. They're "free" per token but not free: hardware, ops, and usually lower capability than frontier APIs.

| Good fit | Poor fit |
|----------|----------|
| Prototyping, offline dev, unit tests of plumbing | Hard reasoning and long agentic tasks |
| High-volume simple classification/extraction after evals prove quality | Workloads needing frontier coding ability |
| Data that can't leave your network | Teams without capacity to run inference infra |

Sizing rule of thumb for weights: parameters × bytes per parameter. An 8B model is ~16 GB at FP16 or ~4–5 GB at 4-bit, plus KV-cache memory that grows with context length and concurrency.

---

## 10. CLAUDE CODE SPECIFIC TIPS

All from the official [Claude Code cost guide](https://code.claude.com/docs/en/costs) unless noted.

### Before Starting

- [ ] **Be specific:** "add input validation to `login()` in auth.ts" lets Claude go straight there; "improve this codebase" triggers broad scanning.
- [ ] **Give a verification target:** a test command, expected output, or screenshot, so it doesn't iterate blindly.
- [ ] **Use plan mode** (`Shift+Tab`) for complex work, so you approve the approach before tokens go into implementation.
- [ ] **Keep CLAUDE.md lean** (the docs suggest under ~200 lines); move specialised workflows into skills, which load only when used.

### During a Session

- [ ] **Watch usage:** `/usage` shows session tokens and estimated cost (meaningful for API billing), `/context` shows what fills the window; the status line can show it continuously.
- [ ] **`/clear` between unrelated tasks** (free); `/compact <focus>` when you need continuity.
- [ ] **Pick the model and effort for the job:** `/model`, `/effort`. Sonnet handles most coding; reserve Opus for harder reasoning; use Haiku for simple sub-agents.
- [ ] **Course-correct early:** `Esc` to stop, `Esc Esc` or `/rewind` to roll back, rather than letting a wrong approach run.
- [ ] **Delegate verbose work to sub-agents:** test runs, log reading and doc fetching stay out of your main context.
- [ ] **Prefer CLIs to MCP servers where both exist** (`gh`, `aws`), and disable unused MCP servers (`/mcp`).
- [ ] **Filter output with hooks:** e.g. a `PreToolUse` hook that rewrites test commands to show only failures.
- [ ] **Mind idle-time costs:** after a break longer than the cache TTL, the next message re-processes the full context; scheduled tasks and agent teams keep spending while you're away.

### Cost-Effective Prompts

```
❌ "Make this better"
   → broad exploration, many reads, many suggestions

✅ "In src/main.py, change the /health endpoint to return {'status': 'ok'}
    instead of {'health': 'good'}, and update its test."
   → one search, one read, two edits, one test run
```

---

## 11. SUMMARY — THE LEVERS IN ORDER

```
┌──────────────────────────────────────────────────────────────────────┐
│  FREE WINS (no quality trade-off)                                    │
│  1. Measure: usage per request, cost per completed task, cache hits  │
│  2. Prompt caching on every repeated prefix                          │
│  3. Batch API (-50%) for anything that can wait                      │
│  4. Context hygiene: trim tool output, compact, reset, sub-agents    │
│  5. Output hygiene: no preamble, structured outputs, sane max_tokens │
│                                                                      │
│  TRADE-OFFS (verify with evals)                                      │
│  6. Lower effort per route                                           │
│  7. Cheaper model per route                                          │
│  8. Pack small items / route simple work to open-weight models       │
│                                                                      │
│  GUARDRAILS                                                          │
│  9. Budgets and alerts per route/customer; spend limits              │
│ 10. Re-check pricing and re-run evals when models change             │
└──────────────────────────────────────────────────────────────────────┘
```

### What Interviewers Probe Next

- *"Your LLM bill doubled last month. How do you investigate?"* Break down by route/model/customer; look at tokens per request (context growth? tokenizer change?), output and thinking tokens, cache hit rate, retry/loop rates, and traffic volume.
- *"Would you route to a cheaper model?"* Only per route and with evals; compare cost per completed task, including retries and escalations, and account for losing cache reuse across models.
- *"How do you stop a runaway agent from burning money?"* Per-task token/turn budgets, loop detection, max tool calls, spend limits, and alerting on per-session cost.

---

> **Related:** [Tokenization & Cost](04_TOKENIZATION_AND_COST.md) → How tokens work and are priced
> **Related:** [Multi-LLM Architecture](../agents/08_MULTI_LLM_ARCHITECTURE.md) → Production routing and cost management
