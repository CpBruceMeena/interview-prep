# 💸 LLM Cost Optimization — Practical Guide for Daily Usage

> **Actionable strategies to get the most out of LLMs while keeping costs under control — from prompt design to model selection, conversation management, and production monitoring.**

---

## 1. THE COST LANDSCAPE (Updated July 2026)

Understanding current pricing is the first step to controlling costs:

### Model Pricing (per million tokens)

| Model | Input | Output | Best For |
|-------|-------|--------|----------|
| **Claude 4 Sonnet** | $3.00 | $15.00 | Daily coding, analysis, reasoning |
| **Claude 4 Haiku** | $0.80 | $4.00 | Quick Q&A, simple edits, classification |
| **Claude 4 Opus** | $15.00 | $75.00 | Complex research, deep reasoning |
| **GPT-4o** | $2.50 | $10.00 | General purpose, creative work |
| **GPT-4o-mini** | $0.15 | $0.60 | Simple tasks, high volume, cheap |
| **DeepSeek Coder V3** | $0.90 | $3.60 | Code generation, technical tasks |
| **DeepSeek V4 Flash** | $0.40 | $1.60 | Fast inference, prototyping |

> **Key insight:** Output tokens cost **3-5x more** than input tokens for most models. Every word the model generates has a disproportionate cost impact.

---

## 2. MODEL SELECTION STRATEGY

The single biggest cost lever is **choosing the right model for the right task**.

### The Tiered Model Strategy

```
                    TIERED MODEL SELECTION
                    ─────────────────────

  Task Complexity          Model Choice          Cost/Task
  ──────────────────────────────────────────────────────────
  Simple Q&A               GPT-4o-mini /         $0.001-0.005
  (What is X?)             Claude 4 Haiku
  
  Simple edit              Claude 4 Haiku        $0.005-0.02
  (Fix one typo)
  
  Daily coding             Claude 4 Sonnet       $0.02-0.10
  (Feature implementation)
  
  Complex refactoring      Claude 4 Sonnet       $0.10-0.50
  (Multi-file changes)
  
  Deep research            Claude 4 Opus         $0.50-5.00
  (Architecture design)

  Percentage of tasks:
  ┌────────────────────────────────────────────────────────────┐
  │  60% Simple (cheap model)                                  │
  │  30% Moderate (balanced model)                             │
  │  10% Complex (best model when needed)                      │
  └────────────────────────────────────────────────────────────┘
```

### Rule of Thumb

| If your task is... | Use... | Savings vs Opus |
|-------------------|--------|-----------------|
| A simple question you'd Google | GPT-4o-mini or Claude 4 Haiku | **97%** |
| Writing a short email or message | GPT-4o-mini | **99%** |
| Reviewing a small PR | Claude 4 Sonnet | **80%** |
| Brainstorming ideas | GPT-4o | **83%** |
| Complex debugging | Claude 4 Sonnet | **80%** |
| Only the hardest problems | Claude 4 Opus | — |

### How to Choose in Practice

```python
# Decision framework for model selection
def pick_model(task: str, context: dict) -> str:
    """Pick the most cost-effective model for a task."""
    
    # 1. High-volume, repetitive tasks → cheapest
    if context.get("volume", 0) > 1000:
        return "gpt-4o-mini"  # $0.15/M input
    
    # 2. Real-time, user-facing → fast + cheap
    if context.get("latency_sensitive"):
        return "claude-4-haiku"  # Fastest Claude model
    
    # 3. Code generation → coding-specialized
    if task in ("code_gen", "code_review", "debug"):
        return "deepseek-coder-v3"  # $0.90/M input
    
    # 4. Complex reasoning → best model
    if context.get("complexity", "low") == "high":
        return "claude-4-sonnet"  # Best reasoning/price ratio
    
    # 5. Everything else → balanced
    return "claude-4-sonnet"  # Default for daily use
```

---

## 3. PROMPT CACHING — YOUR BIGGEST COST SAVER

Prompt caching can reduce input costs by **90%** for repeated prompt components.

### How Caching Works

```
Without Caching (every request pays full price):
  Request 1: System(2K) + Tools(2.5K) + User(0.5K) = 5.0K charged
  Request 2: System(2K) + Tools(2.5K) + User(0.5K) = 5.0K charged
  Request 3: System(2K) + Tools(2.5K) + User(0.5K) = 5.0K charged
  ──────────────────────────────────────────────────────────
  Total: 15.0K tokens charged at full price

With Caching:
  Request 1: System(2K, write) + Tools(2.5K, write) + User(0.5K) = 5.0K (cache write)
  Request 2: System(2K, hit)  + Tools(2.5K, hit)  + User(0.5K) = 0.5K (cache hit!)
  Request 3: System(2K, hit)  + Tools(2.5K, hit)  + User(0.5K) = 0.5K (cache hit!)
  ──────────────────────────────────────────────────────────
  Total: 6.0K tokens charged (60% savings!)
```

### Cache Pricing

| Component | Normal Price | Cached Price | Savings |
|-----------|-------------|--------------|---------|
| **System prompt** | $3.00/M | $0.30/M | **90%** |
| **Tool schemas** | $3.00/M | $0.30/M | **90%** |
| **Large context prefix** | $3.00/M | $0.30/M | **90%** |

### Best Practices for Prompt Caching

```python
# ✅ GOOD: Cache-friendly prompt structure
SYSTEM_PROMPT = [
    {
        "type": "text",
        "text": "You are a senior software engineer...",
        "cache_control": {"type": "ephemeral"}  # ← Mark for caching
    }
]

# ✅ GOOD: Group static content together
messages = [
    # Put ALL cached content at the beginning
    {
        "role": "system",
        "content": LONG_SYSTEM_PROMPT,  # Marked with cache_control
    },
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": STATIC_CONTEXT,  # Project info, conventions
                "cache_control": {"type": "ephemeral"}
            },
            {
                "type": "text",
                "text": DYNAMIC_QUERY  # The actual question
            }
        ]
    }
]
```

### What to Cache vs What Not to Cache

| ✅ Cache This | ❌ Don't Cache This |
|--------------|-------------------|
| System prompt (persona, rules) | User messages (change every turn) |
| Tool definitions and schemas | Tool results (different every time) |
| Project conventions and context | File contents (variable per request) |
| Static knowledge base snippets | Error messages |
| Template explanations | Session-specific data |

### Cache Invalidation Strategy

The cache is **ephemeral** — it lasts ~5 minutes of inactivity. Design for this:

```python
# Strategy: Organize prompts to maximize cache hits

# 1. Place static content FIRST (most likely to be cached)
# 2. Place dynamic content LAST (always new)
# 3. Keep cacheable content contiguous (no interleaving)

BAD:  [System] [UserMsg1] [Tools] [UserMsg2]  ← Cache broken
GOOD: [System] [Tools] [StaticContext] [Dynamic]  ← Max cache hits
```

---

## 4. CONVERSATION MANAGEMENT

The #1 cost killer in agent tools: **conversation history that grows unbounded**.

### The Cost of Conversation Growth

```
Turn 1:   5,000 tokens  →  $0.015
Turn 5:  15,000 tokens  →  $0.045
Turn 10: 30,000 tokens  →  $0.090
Turn 20: 60,000 tokens  →  $0.180
Turn 50: 150,000 tokens →  $0.450

After 50 turns: You're spending $0.45 per message — 30x the first message!
```

### Strategies to Control History Growth

#### Strategy 1: Summarize, Don't Accumulate

```python
# ❌ BAD: Keep everything
messages.append(user_message)
messages.append(assistant_response)  # Grows forever

# ✅ GOOD: Summarize periodically
if len(messages) > MAX_HISTORY_TURNS:
    summary = summarize_conversation(messages[:-2])  # Condense history
    messages = [summary_message(summary)] + messages[-2:]  # Keep only last turn
```

#### Strategy 2: Know When to Fork

```python
# When to start a NEW conversation (fork) vs. continue:
#
# CONTINUE if: Same task, incremental progress
#   "Fix this bug" → "Now fix the related bug in utils.py"
#
# FORK if: New task, unrelated topic
#   "Fix this bug" → "Now design a new API from scratch"
#
# FORK if: Conversation > 20 turns
#   Starting fresh saves costs even if you lose some context
```

#### Strategy 3: Trim Tool Results

```python
# Tool results (file contents, search results) are the biggest cost driver.
# Trim them before sending back to the LLM.

# ❌ BAD: Send full file contents every time
tool_result = read_entire_file("large_file.py")  # 2000+ tokens

# ✅ GOOD: Send only what's relevant
tool_result = extract_relevant_section("large_file.py", line_range=(10, 50))
```

### The Fresh Start Rule

```
┌──────────────────────────────────────────────────────────────────────┐
│                          FRESH START RULE                             │
│                                                                       │
│  If your task is COMPLETELY DIFFERENT from the current conversation:  │
│                                                                       │
│  ❌ Don't: "Now let's also redesign the database schema"              │
│     (After 30 turns of frontend work — $0.30/msg)                    │
│                                                                       │
│  ✅ Do: Start a new conversation with a concise summary:              │
│     "We have a FastAPI app with user auth. Design a DB schema."      │
│     (Fresh start: $0.02/msg — 15x cheaper!)                         │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 5. OUTPUT LENGTH CONTROL

Output tokens cost **3-5x more** than input tokens. Every unnecessary word burns budget.

### The Cost of Verbosity

```
Concise response (50 tokens):   $0.00075  (75/100 of a cent)
Verbose response (500 tokens):  $0.00750  (7.5 cents)
Very verbose (2000 tokens):     $0.03000  (3 cents — 40x more!)

Over 1000 conversations/day:
  Concise:   $0.75/day
  Verbose:   $7.50/day
  Very verbose: $30.00/day
```

### Controlling Output Length

```python
# Method 1: Set max_tokens aggressively
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=500,  # ← Be specific about how much you need
)

# Method 2: Instruct conciseness in system prompt
"You are a concise assistant. Keep responses under 3 sentences.
 Never add unnecessary commentary. Answer directly."

# Method 3: Use structured output format
"Respond with ONLY the code. No explanations. No markdown.
 Just the raw code block."

# Method 4: Set response format explicitly
"Format your response as:
 - One-line summary
 - Bullet points only (max 5)
 - No prose, no greetings, no sign-offs"
```

### When Verbosity Is Actually Wasteful

| ❌ Unnecessary | ✅ Better |
|--------------|----------|
| "Certainly! I'd be happy to help you with that. Here's my analysis..." | Direct answer, no preamble |
| "Let me first understand your requirements..." (and then asks a question you already answered) | Read the existing context before responding |
| "In conclusion, to summarize the key points we've discussed..." (at the end of every turn) | Only summarize when starting a new task |
| "I hope this helps! Let me know if you have any questions." (on every response) | Skip sign-offs in a conversation |

---

## 6. TOOL CALL OPTIMIZATION

In agent frameworks (Claude Code, Cursor, etc.), each tool call costs an additional API round-trip.

### The Hidden Cost of Tool Calls

```
Example: Implementing a feature
    
    Step                     Tokens (Input)  Cost
    ─────────────────────────────────────────────────
    1. Initial request         5,000         $0.015
    2. Read main.py            6,000         $0.018
    3. Read models.py          7,000         $0.021
    4. Read schemas.py         8,000         $0.024
    5. Edit main.py            9,000         $0.027
    6. Edit models.py         10,000         $0.030
    7. Run tests              11,000         $0.033
    8. Final response         12,000         $0.036
    ─────────────────────────────────────────────────
    Total                     —             $0.204

WITH optimization:
    Step                     Tokens (Input)  Cost
    ─────────────────────────────────────────────────
    1. Initial request         5,000         $0.015
    2. Read ALL files at once  7,000         $0.021
    3. Edit main.py + models   9,000         $0.027
    4. Run tests + respond    11,000         $0.033
    ─────────────────────────────────────────────────
    Total                      —            $0.096  (53% savings!)
```

### Tool Call Best Practices

```python
# ✅ GOOD: Batch reads together
read_files(["main.py", "models.py", "schemas.py"])  # One call

# ❌ BAD: Read one file at a time
read_files(["main.py"])     # Call 1
read_files(["models.py"])   # Call 2  
read_files(["schemas.py"])  # Call 3

# ✅ GOOD: Read only what you need
read_file("src/main.py")  # Read the file you're editing
# Don't read irrelevant files just to be thorough

# ✅ GOOD: Use targeted search instead of full file reads
search_code("class User")  # Find only the relevant section
# vs. read entire 500-line file

# ✅ GOOD: Combine multiple small edits into one str_replace
str_replace(
    old="line1\nline2\nline3",
    new="new_line1\nnew_line2\nnew_line3"
)
# vs. three separate str_replace calls
```

### The "Read Once" Rule

```
┌──────────────────────────────────────────────────────────────────────┐
│                          READ ONCE RULE                              │
│                                                                      │
│  Before you ask Claude to read a file, ask yourself:                 │
│                                                                      │
│  ❌ "Can I give Claude enough context in my prompt instead?"         │
│  ✅ Copy the key function/section into your prompt                   │
│                                                                      │
│  ❌ "Do I need the entire file or just a function?"                  │
│  ✅ Target specific functions, classes, or line ranges              │
│                                                                      │
│  ❌ "Can I find it with a search instead?"                          │
│  ✅ Use targeted search for patterns, not full file reads           │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 7. BATCH PROCESSING

When processing multiple independent items, **batch them** instead of making separate requests.

### Batching vs. Individual Requests

```python
# ❌ BAD: 10 separate requests (10x overhead)
for item in items:
    response = llm.generate(f"Translate to French: {item}")
    # Each call pays the full system prompt + tools cost again

# ✅ GOOD: One batched request
response = llm.generate(f"""
Translate each of the following to French.
Return as a JSON array preserving the order.

Items:
{json.dumps(items, indent=2)}

Response format: {{"translations": [...], "indices": [...]}}
""")
# One call, one system prompt, one set of tools
```

### When to Batch vs. Not

| Scenario | Batch? | Why |
|----------|--------|-----|
| Translate 100 sentences | ✅ Batch | Same task, same context |
| Review 10 small files | ✅ Batch | Same reviewer persona |
| Classify 1000 items | ✅ Batch | Same classification criteria |
| Debug a specific error | ❌ Don't batch | Needs iteration and context |
| Brainstorming ideas | ❌ Don't batch | Benefits from back-and-forth |
| Complex multi-step task | ❌ Don't batch | Needs sequential reasoning |

### Batch Size Guidelines

```
Optimal batch size depends on context window:

  Small model (8K context):  3-5 items per batch
  Medium model (32K context): 5-10 items per batch
  Large model (128K+ context): 10-50 items per batch

Note: Larger batches can reduce quality. Start small and increase.
```

---

## 8. PRACTICAL BUDGET CONTROL

### Setting Up Cost Alerts

```python
class CostMonitor:
    """Simple cost monitoring for daily usage."""
    
    def __init__(self, daily_budget: float = 5.0, monthly_budget: float = 100.0):
        self.daily_budget = daily_budget
        self.monthly_budget = monthly_budget
        self.daily_usage = 0.0
        self.monthly_usage = 0.0
    
    def track_call(self, model: str, input_tokens: int, output_tokens: int):
        cost = calculate_cost(model, input_tokens, output_tokens)
        self.daily_usage += cost
        self.monthly_usage += cost
        
        if self.daily_usage > self.daily_budget * 0.8:
            print(f"⚠️ Warning: Daily usage at 80% (${self.daily_usage:.2f}/${self.daily_budget:.2f})")
        
        if self.monthly_usage > self.monthly_budget:
            print(f"🚨 Monthly budget exceeded!")
    
    def get_report(self) -> str:
        return f"""
Cost Report:
  Today:  ${self.daily_usage:.2f} / ${self.daily_budget:.2f}
  Month:  ${self.monthly_usage:.2f} / ${self.monthly_budget:.2f}
        """
```

### Quick Cost Estimation Cheat Sheet

```
ESTIMATE YOUR COSTS QUICKLY
────────────────────────────

Per API call (average):
  Simple Q&A:            ~$0.002  (2,000 input + 200 output tokens)
  Code generation:       ~$0.02   (5,000 input + 500 output tokens)
  Complex task (10 turns): ~$0.25  (50,000 input + 5,000 output total)

For heavy daily usage (Claude Code, Cursor, etc.):
  Light day:   ~$1-3/day    (~30-90 simple tasks)
  Medium day:  ~$3-10/day   (~10-30 coding tasks)
  Heavy day:   ~$10-30/day  (~5-10 complex tasks)
  Very heavy:  ~$30-100/day (agent sessions, bulk processing)

Monthly projections:
  Light usage:   ~$30-90/month
  Medium usage:  ~$90-300/month
  Heavy usage:   ~$300-900/month
  Power usage:   ~$900-3000+/month
```

---

## 9. FREE/OPEN-SOURCE ALTERNATIVES

When costs become a concern, consider local/open-source models for certain tasks:

| When to Use Local | Recommended Model | Hardware Needed |
|-------------------|-------------------|-----------------|
| Prototype / testing | Gemma 4B, Llama 3.2 3B | 8GB RAM (any Mac) |
| Simple classification | Phi-3 Mini | 4GB RAM |
| Code completion | DeepSeek Coder (local) | 16GB RAM, GPU recommended |
| Batch processing | Mistral 7B | 16GB RAM |
| Last resort | Llama 3 70B (via API) | Requires API or heavy GPU |

### Hybrid Strategy for Maximum Savings

```python
# Hybrid approach: local for simple, API for complex
def get_response(prompt: str, complexity: str):
    if complexity == "simple":
        return local_model.generate(prompt)    # Free!
    elif complexity == "medium":
        return cheap_api.generate(prompt)      # $0.001
    else:
        return best_api.generate(prompt)       # $0.02-0.10
```

---

## 10. CLAUDE CODE / EDITOR SPECIFIC TIPS

If you're using Claude Code (CLI) or Claude Editor:

### Before Starting a Session

- [ ] **Define the scope clearly**: Vague requests lead to more back-and-forth
- [ ] **Include relevant context in your prompt**: Saves file reads
- [ ] **Check for existing solutions**: Don't ask Claude to write what already exists
- [ ] **Use a focused task description**: "Add search to the user list" vs "Make the app better"

### During a Session

- [ ] **Monitor the cost indicator** (Claude Code shows token usage)
- [ ] **Restart for new tasks**: `/clear` or start a new conversation
- [ ] **Give complete requirements in one message**: Avoid multiple rounds of clarification
- [ ] **Use precise file paths**: "Read src/main.py:42-60" vs "Read the main file"
- [ ] **Explicitly say when Claude is done**: Don't let it continue analyzing after task is complete

### Cost-Effective Prompt Templates

```
❌ EXPENSIVE: "Make this better" → Claude reads all files, analyzes everything, suggests many changes
   Cost: ~$0.30-0.50

✅ CHEAP: "In src/main.py, change the /health endpoint to return {'status': 'ok'} instead of {'health': 'good'}"
   Cost: ~$0.01-0.02

❌ EXPENSIVE: "Review this code for issues" → Claude might do a deep analysis
   Cost: ~$0.15-0.30

✅ CHEAP: "Check this function for SQL injection vulnerabilities: [paste function]"
   Cost: ~$0.01-0.02
```

### End-of-Session Checklist

- [ ] Did I complete the task within this session?
- [ ] If not, should I save a summary for next time vs. continuing?
- [ ] Did I learn anything I should document for future reference?
- [ ] Is there a way to write shorter prompts next time for similar tasks?

---

## 11. SUMMARY — THE TOP 10 COST-SAVING RULES

```
┌──────────────────────────────────────────────────────────────────────┐
│                   TOP 10 COST-SAVING RULES                            │
│                                                                       │
│  1.  Pick the cheapest model that can do the job                     │
│      (Haiku for simple, Sonnet for daily, Opus for emergencies)      │
│                                                                       │
│  2.  Enable prompt caching on system prompts and tool schemas        │
│      (90% savings on cached content)                                 │
│                                                                       │
│  3.  Start fresh conversations for new tasks                         │
│      (Don't let history grow beyond 20 turns)                        │
│                                                                       │
│  4.  Be specific in your prompts                                     │
│      (Vague prompts → more round-trips → more cost)                 │
│                                                                       │
│  5.  Ask for concise responses                                       │
│      (Output costs 5x more than input)                               │
│                                                                       │
│  6.  Batch independent tasks into one request                        │
│      (Avoid paying system prompt overhead N times)                  │
│                                                                       │
│  7.  Read files once and target specific sections                    │
│      (Each tool call multiplies the cost)                            │
│                                                                       │
│  8.  Use local models for prototyping and simple tasks               │
│      (Free inference for development work)                           │
│                                                                       │
│  9.  Set budget alerts and monitor usage                             │
│      (Catch cost spikes before they become problems)                 │
│                                                                       │
│  10. Document effective prompts for reuse                            │
│      (Don't reinvent the wheel — save and iterate)                  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 12. QUICK REFERENCE CARD

```
┌────────────────────────────────────────────────────────────────────┐
│                    QUICK COST REFERENCE                              │
│                                                                      │
│  MODEL          INPUT      OUTPUT    BEST FOR                       │
│  ───────────────────────────────────────────────────────────        │
│  GPT-4o-mini    $0.15/M    $0.60/M   Simple Q&A, classification    │
│  Claude Haiku   $0.80/M    $4.00/M   Fast tasks, simple edits      │
│  DeepSeek Coder $0.90/M    $3.60/M   Code gen & review            │
│  GPT-4o         $2.50/M   $10.00/M   General purpose              │
│  Claude Sonnet  $3.00/M   $15.00/M   Daily coding & reasoning     │
│  Claude Opus    $15.00/M  $75.00/M   Complex research only         │
│                                                                      │
│  SAVINGS TIPS                                                        │
│  ────────────────────────────────────                               │
│  Prompt caching:           Up to 90% on system/tools               │
│  Concise instructions:     Up to 80% on output                      │
│  Fresh conversations:      Up to 70% on long sessions              │
│  Batch processing:         Up to 60% on high-volume tasks          │
│  Local models:             100% (free) on prototyping              │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘
```

---

> **Related:** [Tokenization & Cost](04_TOKENIZATION_AND_COST.md) → How tokens work and are priced
> **Related:** [Multi-LLM Architecture](../agents/08_MULTI_LLM_ARCHITECTURE.md) → Production routing and cost management
