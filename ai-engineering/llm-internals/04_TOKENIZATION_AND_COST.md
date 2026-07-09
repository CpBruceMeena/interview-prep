# 💰 Tokenization & Token Calculation — Complete Guide

> **How tokens are counted, how pricing works, and strategies to optimize token usage.**

---

## 1. WHAT ARE TOKENS?

**Tokens** are the fundamental units that LLMs process. Think of them as "sub-words" — pieces of text that the model can understand and generate.

```ascii
Example: "I love programming in Python"
         │    │     │          │  │     │
Tokens: [I] [love] [program] [ming] [in] [Python]
         1     2       3        4     5      6

So: "I love programming in Python" = 6 tokens
```

### Token Size Ranges

| Content Type | Tokens per Character | Example |
|-------------|---------------------|---------|
| **English text** | ~0.25 tokens/char | "Hello, world!" = 4 tokens |
| **Code (Python)** | ~0.20 tokens/char | `def foo(): return 1` = 6 tokens |
| **Code (Go)** | ~0.30 tokens/char | `func foo() int { return 1 }` = 9 tokens |
| **Markdown** | ~0.30 tokens/char | "# Title" = 3 tokens |
| **JSON** | ~0.40 tokens/char | `{"key": "value"}` = 8 tokens |
| **Special chars** | Variable | "🔥" = 1 token (rare), "→" = 1 token |

### Average Token Counts for Common Items

| Item | Approximate Tokens |
|------|-------------------|
| **1 English word** | 1.3 tokens |
| **1 page of text** | ~400 tokens |
| **1 page of code** | ~500 tokens |
| **10 lines of Python** | ~60 tokens |
| **This sentence** | ~10 tokens |
| **One email** | 50-200 tokens |
| **README.md** | 500-2000 tokens |

---

## 2. HOW TOKENS ARE COUNTED

### 2.1 Byte-Pair Encoding (BPE)

Claude (and most modern LLMs) uses **Byte-Pair Encoding** tokenization:

```ascii
Step 1: Split text into individual characters
"unbelievable" → [u] [n] [b] [e] [l] [i] [e] [v] [a] [b] [l] [e]

Step 2: Merge most frequent pairs
[un] [b] [e] [l] [ie] [v] [a] [b] [l] [e]

Step 3: Continue merging
[un] [be] [lie] [va] [ble]

Step 4: Final tokens
[un] [belie] [vable]
```

The merge rules are learned from training data. Common words become single tokens, while rare words are split into multiple tokens.

### 2.2 Tokenizer Behavior Examples

```ascii
Common words (often 1 token):
  "the"        → 1 token
  "because"    → 1 token
  "def"        → 1 token
  "return"     → 1 token
  "class"      → 1 token

Rare words (split into multiple tokens):
  "unbelievable"     → 2-3 tokens
  "anthropomorphism" → 3-4 tokens
  "xylophone"        → 2 tokens

Code patterns:
  "print"             → 1 token
  "self"              → 1 token
  "__init__"          → 1 token (Claude knows Python!)
  "fastapi"           → 2 tokens
  "asyncio"           → 2 tokens

Numbers:
  "42"                → 1 token
  "100"               → 1 token
  "1000000"           → 2 tokens (common pattern)
  "3.14159"           → 3 tokens

Whitespace:
  "  " (2 spaces)     → 1 token (often merged)
  "\n"                → 1 token
  "\n\n"             → 1 token (common pattern)
  "\\t"               → 1 token
```

---

## 3. INPUT TOKENS vs OUTPUT TOKENS

These are priced differently!

```ascii
┌────────────────────────────────────────────────────────────────────┐
│                    TOKEN PRICING (Illustrative)                     │
│                                                                    │
│  Claude Sonnet 4:                                                  │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Input tokens:   $3.00 / million tokens  (cheaper)          │   │
│  │  Output tokens:  $15.00 / million tokens (5x more!)        │   │
│  │  Cache hit:      $0.30 / million tokens  (10x cheaper!)    │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                    │
│  Why the difference?                                               │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Input tokens: processed in parallel (FP8, batch), fast    │   │
│  │  Output tokens: generated one at a time (auto-regressive)  │   │
│  │  → Output is 50-100x more computationally expensive!       │   │
│  └────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
```

### Cost Comparison

| Scenario | Input Tokens | Output Tokens | Cost |
|----------|-------------|--------------|------|
| **Simple Q&A** | 1,000 | 200 | $0.006 |
| **Code review** | 5,000 | 1,000 | $0.030 |
| **Complex feature** (10 turns) | 50,000 | 5,000 | $0.225 |
| **Agent session** (50 turns) | 500,000 | 25,000 | $1.875 |
| **Heavy agent usage** (500 turns) | 5,000,000 | 250,000 | $18.75 |

---

## 4. PROMPT CACHING

One of the most important cost optimization features:

### How It Works

```ascii
Traditional (no caching):
  Turn 1: System(2K) + User(1K) = 3K input tokens → Charged for 3K
  Turn 2: System(2K) + History(1K) + User(1K) = 4K → Charged for 4K
  Turn 3: System(2K) + History(2K) + User(1K) = 5K → Charged for 5K
  Total: 12K tokens charged

With prompt caching:
  Turn 1: System(2K, cached) + User(1K) → 2K cache write, 1K charged
  Turn 2: System(2K, cached) + History(1K) + User(1K) → 2K cache hit, 2K charged
  Turn 3: System(2K, cached) + History(2K) + User(1K) → 2K cache hit, 3K charged
  Total: 2K cache write + 6K charged = HUGE savings!
```

### Cache Pricing

| Component | Normal Price | Cached Price | Savings |
|-----------|-------------|--------------|---------|
| **System prompt** | $3.00/M | $0.30/M | **90%** |
| **Tool schemas** | $3.00/M | $0.30/M | **90%** |
| **Conversation prefix** | $3.00/M | $0.30/M | **90%** |

### What to Cache

| Component | Cache? | Why |
|-----------|--------|-----|
| **System prompt** | ✅ Always | Same every request |
| **Tool definitions** | ✅ Always | Same every request |
| **Conversation startup** | ✅ Yes | Multi-turn conversations |
| **File contents** | ⚠️ Maybe | If read multiple times |
| **User messages** | ❌ No | Changes each turn |
| **Tool results** | ❌ No | Changes each turn |

---

## 5. TOKEN BUDGET PLANNING

### 5.1 Context Window Allocation

```ascii
Total Context Window: 200,000 tokens
                               
Reserved for Output:    8,000  (4%)   ← max_tokens setting
Available for Input:  192,000  (96%)

Input Budget: 192,000 tokens
  ├── System Prompt:     2,000  (1%)
  ├── Tool Schemas:      2,500  (1.3%)
  ├── Conversation:    100,000  (52%)
  ├── File Contents:    85,000  (44.3%)
  └── Misc Overhead:     2,500  (1.3%)
```

### 5.2 Cost Optimization Strategies

| Strategy | Savings | How |
|----------|---------|-----|
| **Prompt caching** | 50-90% on system/tools | Cache system prompt and tool definitions |
| **Limit conversation history** | 30-50% on long sessions | Summarize vs. keep full history |
| **Chunk large files** | 70-90% on file reads | Read relevant sections, not entire files |
| **Use shorter tool names** | 1-5% | `read_file` vs `read_file_contents_from_disk` |
| **Compress JSON** | 20-30% | Remove whitespace, use shorter keys |
| **Batch tool calls** | 30-50% on tool-heavy tasks | Combine multiple operations in one tool |
| **Cache frequent queries** | 50-90% on repeated queries | Don't re-ask the same question |

---

## 6. TOKEN ESTIMATION GUIDE

### 6.1 Quick Estimation Rules

```ascii
English text:   ~4 characters  = 1 token
               ~0.75 words    = 1 token
Code:           ~5 characters  = 1 token
JSON:           ~2.5 characters = 1 token
Chinese/Japanese: ~1 character  = 1 token

Common references:
  A4 page of text:     ~400-500 tokens
  A4 page of code:     ~500-700 tokens
  Average email:       ~100-200 tokens
  Average paragraph:   ~50-100 tokens
  This section:        ~150 tokens
```

### 6.2 Token Counter Tool

```python
def estimate_tokens(text: str) -> int:
    """Quick token estimation for Claude."""
    # Rough estimate: ~4 chars per token for English
    char_count = len(text)
    token_estimate = char_count // 4
    
    # Adjust for code (more compact)
    # Adjust for whitespace (tokens include whitespace)
    return max(1, token_estimate)

# More accurate: use anthropic's tokenizer
# pip install anthropic
from anthropic import Anthropic

client = Anthropic()
tokens = client.count_tokens("Your text here")
print(f"Exact token count: {tokens}")
```

### 6.3 Common File Token Estimates

| File Type | Typical Size | Tokens |
|-----------|-------------|--------|
| **README.md** | 500-2000 chars | 125-500 |
| **Small Python file** (50 lines) | ~1500 chars | ~375 |
| **Medium Python file** (200 lines) | ~6000 chars | ~1500 |
| **Large Python file** (500 lines) | ~15000 chars | ~3750 |
| **TypeScript file** (200 lines) | ~8000 chars | ~2000 |
| **Config file** (pyproject.toml) | ~500 chars | ~125 |
| **JSON response** (API) | ~2000 chars | ~500 |
| **Markdown doc** (200 lines) | ~10000 chars | ~2500 |

---

## 7. REAL-WORLD TOKEN USAGE EXAMPLES

### 7.1 Simple Q&A

```ascii
User: "What is the capital of France?"
       └── 8 tokens

System: 2,000 tokens
Input:  8 tokens
────────────────
Total:  2,008 input tokens

Response: "The capital of France is Paris."
         └── 8 tokens

Total cost: 2,008 input + 8 output = ~$0.006
```

### 7.2 Code Generation (3-turns)

```ascii
Turn 1: System(2K) + Tools(2.5K) + User(50) = 4,550 input → 500 output
Turn 2: Prev(5,050) + ToolResult(200) + Prompt(20) = 5,270 input → 300 output
Turn 3: Prev(5,570) + ToolResult(500) = 6,070 input → 800 output

Total: 15,890 input + 1,600 output = ~$0.072
```

### 7.3 Complex Refactoring (10 turns with file reads)

```ascii
Turn 1:  4,550 input  →  500 output  (initial plan)
Turn 2:  5,200 input  →  200 output  (read_files)
Turn 3:  6,500 input  →  300 output  (read more files)
Turn 4:  8,000 input  →  400 output  (first edit)
Turn 5:  8,800 input  →  300 output  (second edit)
Turn 6:  9,500 input  →  200 output  (dependency update)
Turn 7:  10,200 input →  500 output  (test file)
Turn 8:  11,200 input →  200 output  (run tests)
Turn 9:  12,000 input →  300 output  (fix issues)
Turn 10: 13,000 input →  500 output  (final summary)

Total: 88,950 input + 3,400 output = ~$0.318
```

---

## 8. KEY TAKEAWAYS

| Takeaway | Impact |
|----------|--------|
| **Output tokens cost 5x more** | Minimize generation length where possible |
| **Prompt caching saves 90% on system/tools** | Structure prompts to maximize cache hits |
| **Conversation history grows fast** | Summarize or trim old turns in long sessions |
| **Tool calls multiply cost** | Each tool call = new API request with full context |
| **Token count ≠ character count** | Use a tokenizer to estimate accurately |
| **Cache invalidation is manual** | Break cache at logical boundaries (e.g., after major topic shifts) |

---

> **Next:** [System Prompt Engineering](05_SYSTEM_PROMPT_ENGINEERING.md) → Crafting effective system prompts
