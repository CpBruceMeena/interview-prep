# 💰 Tokenization & Token Calculation — Complete Guide

> **What tokens are, how BPE builds them, how to count them for Claude, how input, output, cache and batch tokens are priced, and how to estimate the cost of an agent session.**

**30-second answer:** LLMs read and write *tokens*, subword pieces produced by a learned tokenizer (byte-level BPE or similar). English averages roughly 4 characters or 0.75 words per token; code, JSON, numbers and non-Latin scripts are less efficient. Claude's tokenizer isn't public, and it changed with Opus 4.7 (roughly 1.0–1.35× the tokens for the same text), so **count with the API, don't guess**. You pay per token: output costs 5× input on the current Claude lineup, cache reads cost a small fraction of input, cache writes a premium, and the Batch API halves everything.

!!! info "Prices on this page"
    Rates quoted were checked against the [Claude pricing page](https://platform.claude.com/docs/en/about-claude/pricing) on **7 Oct 2026**. They change; re-check before quoting them. Worked examples use round **example rates of $3 input / $15 output per million tokens** so the arithmetic stays readable; plug in current rates for real estimates.

---

## 1. WHAT ARE TOKENS?

A **token** is the unit the model reads and predicts: often a whole common word (with its leading space), sometimes a word fragment, punctuation, whitespace run, or a single byte.

```ascii
Illustrative split (not Claude's actual tokenizer):

"I love programming in Python"
 [I] [ love] [ programming] [ in] [ Python]      → ~5 tokens

"unbelievably tokenizable"
 [un] [bel] [iev] [ably] [ token] [izable]       → ~6 tokens
```

Leading spaces are usually part of the token (`" love"`, not `"love"`), which is why the same word can tokenize differently at the start of a line.

### Rules of Thumb

| Content | Rough ratio | Why |
|---------|-------------|-----|
| English prose | ~4 chars ≈ 1 token; ~0.75 words ≈ 1 token | Anthropic's own FAQ figure; frequent words are single tokens |
| Code | Somewhat fewer chars per token than prose | Identifiers, symbols, indentation |
| JSON / YAML | Noticeably fewer chars per token | Quotes, braces, repeated keys |
| Numbers | Often split into 1–3 digit chunks | Long numbers cost several tokens |
| Chinese / Japanese / Korean | Often ~1 token per 1–2 characters | Less training-data compression per character |
| Emoji / rare Unicode | Can be several tokens each | Byte-level fallback |

Treat these as estimates for capacity planning. Two documented anchors: on the tokenizer introduced with Opus 4.7, **1M tokens ≈ 555K English words**; on older models, about 750K words.

---

## 2. HOW TOKENS ARE COUNTED

### 2.1 Byte-Pair Encoding (BPE), General Background

BPE-family tokenizers are used by most modern LLMs. Training the tokenizer is a separate, one-off step before model training:

```ascii
TRAINING THE TOKENIZER (once, on a large corpus)
  1. Start with a base vocabulary of bytes (256 symbols) → nothing is ever
     "out of vocabulary"
  2. Count every adjacent pair of symbols across the corpus
  3. Merge the most frequent pair into a new symbol; record the merge rule
  4. Repeat until the vocabulary reaches the target size (tens of
     thousands to a few hundred thousand entries)

Toy example (corpus: "low lower lowest", "newest widest"):
  start:      l o w   l o w e r   l o w e s t   n e w e s t ...
  merge 1:    (l,o) → lo      lo w   lo w e r   lo w e s t
  merge 2:    (lo,w) → low    low    low e r    low e s t
  merge 3:    (e,s) → es      ...    n e w es t   w i d es t
  merge 4:    (es,t) → est    low est   n e w est   w i d est
  ...

ENCODING NEW TEXT
  Split into bytes, then apply the learned merges in the order learned.
  Common words collapse to 1 token; rare words stay as several pieces.
```

Variants you might be asked about: **WordPiece** (BERT; merges by likelihood gain), **Unigram / SentencePiece** (starts big and prunes; treats the space as a symbol). Anthropic hasn't published which algorithm or vocabulary Claude uses.

### 2.2 Why Tokenization Matters in Practice

| Effect | Example |
|--------|---------|
| **Cost & limits** | Everything (context window, rate limits, price) is measured in tokens, not characters |
| **Model swaps change counts** | Moving from Sonnet 4.6 to Opus 4.7+ can raise token counts ~1.0–1.35× for the same text, so a cheaper per-token price isn't automatically a cheaper bill |
| **Character-level tasks are hard** | Counting letters or reversing strings: the model sees tokens, not characters |
| **Numbers** | Arithmetic on long numbers suffers when digits are chunked unevenly; use a tool |
| **Whitespace** | Deeply indented code or minified vs pretty JSON tokenizes very differently |

---

## 3. INPUT TOKENS vs OUTPUT TOKENS

### 3.1 Claude API Rates (per million tokens, checked 7 Oct 2026)

| Model | Input | Output | 5-min cache write | 1-h cache write | Cache read |
|-------|-------|--------|------------------|-----------------|-----------|
| Claude Fable 5.1 | $10 | $50 | $12.50 | $20 | $0.25 (0.025×) |
| Claude Opus 5.5 | $4 | $20 | $5 | $8 | $0.20 (0.05×) |
| Claude Sonnet 5.5 | $2 | $10 | $2.50 | $4 | $0.20 (0.1×) |
| Claude Haiku 4.5 | $1 | $5 | $1.25 | $2 | $0.10 (0.1×) |

Other pricing facts (same source):

- **Batch API:** 50% off input and output, for asynchronous jobs (results within 24 hours).
- **Long context:** on Claude 4.6 and later, the full 1M window is billed at the standard rate (no long-context premium).
- **US-only inference** (`inference_geo: "us"`): 1.1× on all token categories.
- **Thinking tokens** are billed as output.
- **Server tools** add usage charges: web search is $10 per 1,000 searches plus the tokens of the results; web fetch costs only tokens.
- Bedrock and Vertex AI set their own prices.

### 3.2 Why Output Costs More

```ascii
Input (prefill):   all prompt tokens go through the model in ONE parallel pass.
                   Big matrix multiplies, GPU compute fully used.

Output (decode):   one token per forward pass per sequence. Each step must
                   read the model weights and the whole KV cache from GPU
                   memory to produce a single token → memory-bandwidth bound,
                   and the request holds KV-cache memory the whole time.
```

That asymmetry (general serving economics, not a published Anthropic cost model) is why every current Claude model prices output at **5× input**.

### 3.3 Cost Comparison (example rates $3 / $15)

| Scenario | Input tokens | Output tokens | Cost |
|----------|-------------|--------------|------|
| **Simple Q&A** | 1,000 | 200 | $0.006 |
| **Code review** | 5,000 | 1,000 | $0.030 |
| **Feature, 10 turns** | 50,000 | 5,000 | $0.225 |
| **Agent session, 50 turns** | 500,000 | 25,000 | $1.875 |
| **Heavy agent use, 500 turns** | 5,000,000 | 250,000 | $18.75 |

These are uncached. In an agent loop most input is a repeated prefix, so with caching the input part typically falls by well over half.

---

## 4. PROMPT CACHING

Prompt caching stores the processed state of a **prompt prefix** on Anthropic's side so later requests that start with the *byte-identical* prefix skip re-processing it.

### How It Works

| Property | Detail |
|----------|--------|
| **Match rule** | Exact prefix in render order **tools → system → messages**. Any change invalidates everything after it |
| **Marking** | Top-level `cache_control: {"type": "ephemeral"}` (automatic, moves forward as the conversation grows) or explicit `cache_control` on up to 4 blocks |
| **Lifetime (TTL)** | 5 minutes by default, refreshed free on every hit; or `"ttl": "1h"` |
| **Minimum size** | Model-dependent, from 512 to 4,096 tokens. Shorter prefixes silently don't cache |
| **Price** | Write: 1.25× input (5 min) or 2× (1 h). Read: 0.1× input on most models (0.05× Opus 5.5, 0.025× Fable 5.1) |
| **Verify** | `usage.cache_creation_input_tokens` and `usage.cache_read_input_tokens` in every response |
| **Scope** | Per model, and never shared across organizations; switching model means a cold cache |

### A Correct Walkthrough

Example rates: input $3/M, 5-min write $3.75/M, read $0.30/M. System + tools = 5,000 tokens (above the minimum), each turn adds 1,000 new tokens, top-level automatic caching on.

```ascii
Without caching                      With automatic caching
Turn 1: 6,000 × $3      = $0.0180    write 6,000 × $3.75           = $0.0225
Turn 2: 7,000 × $3      = $0.0210    read 6,000 × $0.30 + write 1,000 × $3.75 = $0.0056
Turn 3: 8,000 × $3      = $0.0240    read 7,000 × $0.30 + write 1,000 × $3.75 = $0.0059
Turn 4: 9,000 × $3      = $0.0270    read 8,000 × $0.30 + write 1,000 × $3.75 = $0.0062
                          ───────                                    ───────
Input total:              $0.0900                                    $0.0401  (-55%)
```

Turn 1 costs *more* (the 25% write premium); every later turn is far cheaper; the gap widens with each turn. With the 5-minute TTL, a single cache hit already pays for the write.

### What to Cache

| Component | Cache? | Why |
|-----------|--------|-----|
| **Tool definitions, system prompt** | ✅ Always | Identical on every request; keep them byte-stable (no timestamps, sorted JSON) |
| **Large shared documents** | ✅ Yes | Put them early, before the variable question |
| **Conversation history** | ✅ Yes, in multi-turn and agent loops | Automatic caching moves the breakpoint forward each turn |
| **Tool results** | ✅ Once they're in history | Today's tool result is tomorrow's cached prefix |
| **The newest user message** | ❌ | It's the part that changes; it goes after the last breakpoint |

### Silent Cache Killers

- A timestamp, request ID or random ordering in the system prompt.
- Non-deterministic JSON serialization of tool schemas (unsorted keys).
- Adding, removing or reordering tools mid-session.
- Switching models, or changing settings that alter the rendered prompt (e.g. thinking or effort configuration).
- Gaps longer than the TTL between requests.

---

## 5. TOKEN BUDGET PLANNING

### 5.1 Context Window Allocation (200K example)

```ascii
Context window:          200,000 tokens  (1M on current Opus/Sonnet/Fable)
Reserve for output:       16,000         ← max_tokens (includes thinking)
Available for input:     184,000

  ├── Tool definitions:     2,500
  ├── System prompt:        2,000
  ├── CLAUDE.md / memory:   2,000
  ├── Conversation:        ~80,000   ← grows; compact or summarise
  ├── Tool results/files:  ~90,000   ← grows fastest; truncate, paginate
  └── Headroom:            ~7,500
```

### 5.2 Cost Optimization Strategies

| Strategy | Typical effect | How |
|----------|---------|-----|
| **Prompt caching** | Input cost on the cached prefix falls to ~10% or less | Stable prefix first; automatic caching |
| **Batch API** | 50% off | For anything that can wait (evals, backfills, bulk classification) |
| **Right-size the model and effort** | Large | Cheapest model/effort that passes your evals |
| **Trim tool output** | Large in agent loops | Return the relevant lines, paginate, cap size |
| **Compact or reset long sessions** | Large | Summarise old turns; start fresh for unrelated work |
| **Fewer, richer tool calls** | Moderate | Parallel calls; tools that return exactly what's needed |
| **Shorter tool descriptions / names** | Small | Only matters with many tools; clarity beats brevity |

---

## 6. TOKEN ESTIMATION

### 6.1 Quick Estimation Rules

```ascii
English prose:   chars / 4      or  words / 0.75
Code:            chars / 3.5    (rough)
JSON:            chars / 3      (rough; whitespace and quotes add up)
Newer Claude tokenizer (Opus 4.7+): 1.0–1.35× the tokens of older models (budget up to ~35% more)

Common sizes (very rough):
  Page of prose (~500 words):        ~650–700 tokens
  200-line Python file (~6 KB):      ~1,500–2,000 tokens
  Average web page (10 KB):          ~2,500 tokens   (Anthropic's figure)
```

### 6.2 Counting Tokens Exactly

Use the token-counting endpoint. It takes the same shape as a Messages request (so it includes system prompt, tools, images and PDFs), is free to call, and is subject to its own rate limits. Use the model you'll actually call, because tokenizers differ between models.

```python
import anthropic

client = anthropic.Anthropic()

count = client.messages.count_tokens(
    model="claude-opus-5-5",
    system="You are a code reviewer.",
    messages=[{"role": "user", "content": "Review this function: ..."}],
)
print(count.input_tokens)   # exact input tokens for that request shape


def estimate_tokens(text: str) -> int:
    """Offline rough estimate for capacity planning only (~4 chars/token)."""
    return max(1, len(text) // 4)
```

Don't use OpenAI's `tiktoken` to count Claude tokens: different tokenizer, wrong numbers. And the response's `usage` field is the ground truth for billing.

### 6.3 Common File Token Estimates (chars / 4)

| File Type | Typical Size | Tokens |
|-----------|-------------|--------|
| **README.md** | 500–2,000 chars | 125–500 |
| **Small Python file** (50 lines) | ~1,500 chars | ~375 |
| **Medium Python file** (200 lines) | ~6,000 chars | ~1,500 |
| **Large Python file** (500 lines) | ~15,000 chars | ~3,750 |
| **TypeScript file** (200 lines) | ~8,000 chars | ~2,000 |
| **Config file** (pyproject.toml) | ~500 chars | ~125 |
| **JSON API response** | ~2,000 chars | ~500–700 |

Add up to ~35% (1.0–1.35×) for models on the newer tokenizer.

---

## 7. REAL-WORLD TOKEN USAGE EXAMPLES (example rates $3 / $15)

### 7.1 Simple Q&A

```ascii
System prompt: 2,000 tokens   User: "What is the capital of France?" ~8 tokens
Input:  2,008 × $3/M  = $0.0060
Output: "The capital of France is Paris." ~8 tokens × $15/M = $0.0001
Total ≈ $0.006   (the system prompt is 99% of the cost → cache it)
```

### 7.2 Code Generation (3 turns, no caching)

```ascii
Turn 1: system 2K + tools 2.5K + user 50                = 4,550 in → 500 out
Turn 2: previous 5,050 + tool result 200 + prompt 20    = 5,270 in → 300 out
Turn 3: previous 5,570 + tool result 500                = 6,070 in → 800 out

Total: 15,890 in × $3/M + 1,600 out × $15/M = $0.048 + $0.024 ≈ $0.072
```

### 7.3 Complex Refactoring (10 turns with file reads, no caching)

```ascii
Turn 1:  4,550 in →  500 out   (plan)            Turn 6:   9,500 in → 200 out
Turn 2:  5,200 in →  200 out   (read files)      Turn 7:  10,200 in → 500 out
Turn 3:  6,500 in →  300 out   (read more)       Turn 8:  11,200 in → 200 out
Turn 4:  8,000 in →  400 out   (first edit)      Turn 9:  12,000 in → 300 out
Turn 5:  8,800 in →  300 out   (second edit)     Turn 10: 13,000 in → 500 out

Total: 88,950 in × $3/M + 3,400 out × $15/M = $0.267 + $0.051 ≈ $0.318
With the growing prefix cached, input would cost roughly a quarter of that.
```

---

## 8. KEY TAKEAWAYS

| Takeaway | Impact |
|----------|--------|
| **Count with `count_tokens`, not heuristics** | Tokenizers differ by model; Opus 4.7+ uses roughly 1.0–1.35× the tokens for the same text |
| **Output costs 5× input** (current Claude lineup) | Control verbosity and effort; thinking bills as output |
| **Caching is prefix-exact and TTL-based** | It invalidates automatically on any prefix change or after the TTL; nothing to "manually" expire |
| **Cache writes cost extra, reads are cheap** | Pays off from the first hit at the 5-minute TTL |
| **Agent loops resend everything** | Cumulative input grows ~quadratically with turns without caching/compaction |
| **Batch API = 50% off** | Default for non-interactive workloads |

### What Interviewers Probe Next

- *"Why can't the model count the r's in 'strawberry'?"* It sees tokens, not letters.
- *"We switched to a cheaper-per-token model and the bill went up. Why?"* Different tokenizer (more tokens), more thinking/output, or lost cache hits.
- *"Your cache hit rate is 0%. How do you debug it?"* Check the prefix is above the model's minimum, byte-stable (timestamps, key order, tool order), within TTL, and on the same model; read `cache_read_input_tokens`.

---

> **Next:** [System Prompt Engineering](05_SYSTEM_PROMPT_ENGINEERING.md) → Crafting effective system prompts
