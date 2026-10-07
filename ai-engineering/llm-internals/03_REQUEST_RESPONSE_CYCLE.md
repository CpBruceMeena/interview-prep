# 🔄 The Request/Response Cycle — Complete End-to-End Flow

> **What goes into a Messages API request, what happens to it on the server, how the response streams back, and how tokens (and money) accumulate across an agent loop.**

**30-second answer:** A request is `model` + `max_tokens` + `messages` (plus optional `system`, `tools`, caching markers, thinking/effort settings). The server renders it into the model's prompt format, tokenizes it, runs **prefill** over all input tokens (reusing cached prefix state if there's a cache hit), then **decodes** one token at a time until the model ends its turn, asks for a tool, or hits `max_tokens`. The response is a list of content blocks plus a `stop_reason` and `usage`. In an agent loop every tool call means another full request, so input tokens grow every turn and caching is what keeps that affordable.

---

## 1. THE PROMPT ASSEMBLY

Everything the model sees is decided client-side, before the request is sent.

### 1.1 The Complete Prompt Structure

The API renders a request in a fixed order: **`tools` → `system` → `messages`**. That order matters for prompt caching, which matches on an exact prefix.

```ascii
┌────────────────────────────────────────────────────────────────────┐
│  TOOL DEFINITIONS          name, description, input_schema (JSON)  │
│  (+ a tool-use system prompt the API adds automatically)          │
├────────────────────────────────────────────────────────────────────┤
│  SYSTEM PROMPT             role, rules, context, output format     │
├──────────── cache breakpoint: everything above is stable ──────────┤
│  MESSAGES                                                          │
│   user:      "Create a todo API..."                                │
│   assistant: [text, tool_use{id, name, input}]                     │
│   user:      [tool_result{tool_use_id, content}]                   │
│   ... repeated per tool round-trip ...                             │
│   user:      current message                                       │
└────────────────────────────────────────────────────────────────────┘
                  ▼ model generates here (output, ≤ max_tokens)
```

When you pass `tools`, Anthropic documents that the API also injects a tool-use system prompt (a few hundred tokens, model-dependent), billed as input. Tool *schemas* themselves are input tokens too, which is why large tool sets get expensive and why tool search / deferred loading exists.

### 1.2 Token Count Breakdown (illustrative agent request)

| Component | Tokens | Share of input | Changes per call? |
|-----------|--------|---------------|-------------------|
| Tool definitions (+ tool-use prompt) | ~2,500 | 14% | No (cacheable) |
| System prompt | ~2,000 | 11% | No (cacheable) |
| Conversation history (text turns) | ~5,000 | 28% | Grows |
| Tool results (file contents, command output) | ~8,000 | 44% | Grows, usually the largest part |
| Current user message | ~500 | 3% | Yes |
| **Total input** | **~18,000** | **100%** | |
| Output (`max_tokens` cap, not pre-charged) | up to e.g. 16,000 | n/a | You pay only for tokens actually generated |

`max_tokens` reserves room in the context window (input + output must fit), but you're billed only for generated tokens.

---

## 2. THE API REQUEST

### 2.1 HTTP Request Structure

```http
POST https://api.anthropic.com/v1/messages
x-api-key: sk-ant-...
anthropic-version: 2023-06-01
content-type: application/json

{
  "model": "claude-opus-5-5",
  "max_tokens": 16000,
  "stream": true,
  "output_config": {"effort": "medium"},
  "system": [
    {
      "type": "text",
      "text": "You are a coding agent working in a FastAPI repo...",
      "cache_control": {"type": "ephemeral"}
    }
  ],
  "tools": [
    {
      "name": "read_file",
      "description": "Read a UTF-8 file from the repository. Use before editing.",
      "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"]
      }
    }
  ],
  "messages": [
    {"role": "user", "content": "Create a REST API for a todo app with FastAPI"}
  ]
}
```

Corrections to common mistakes:

- Auth is the **`x-api-key`** header (OAuth bearer tokens are a separate login path). `anthropic-version` is **`2023-06-01`**, the current API version; new features arrive via `anthropic-beta` headers, not new version dates.
- Don't send `stop_sequences: ["\n\nHuman:"]`. That's a leftover from the retired Text Completions API; the Messages API handles turns structurally.
- Don't set `temperature`/`top_p`/`top_k` on current models: models released after Opus 4.6 reject non-default values. Use `effort`.

### 2.2 Request Fields Explained

| Field | Required | Purpose |
|-------|----------|---------|
| `model` | ✅ | Model ID, e.g. `claude-opus-5-5` (IDs from the 4.6 generation on are dateless pinned snapshots) |
| `max_tokens` | ✅ | Cap on generated tokens (thinking included) |
| `messages` | ✅ | Conversation; must start with a `user` turn |
| `system` | ❌ | System prompt (string or list of text blocks, cacheable) |
| `tools`, `tool_choice` | ❌ | Tool definitions; `auto` / `none` / force a tool. Forcing (`any`/`tool`) is rejected on the newest models, so use `auto` + `strict: true` tools or structured outputs |
| `thinking` | ❌ | `{"type": "adaptive"}` on current models (older models: `enabled` + `budget_tokens`) |
| `output_config` | ❌ | `effort` (low…max) and structured-output `format` (JSON schema) |
| `cache_control` | ❌ | Top-level automatic caching, or per-block breakpoints (max 4) |
| `stream` | ❌ | SSE streaming; recommended for long outputs to avoid HTTP timeouts |
| `stop_sequences` | ❌ | Custom stop strings |
| `metadata` | ❌ | `user_id` (an opaque ID for abuse detection) |
| `temperature`, `top_p`, `top_k` | ❌ | Deprecated; only older models accept non-default values |

---

## 3. WHAT HAPPENS INSIDE THE LLM

Anthropic doesn't document its serving stack or tokenizer internals. The pipeline below is general LLM background, true of any transformer server.

```ascii
┌──────────────────────────────────────────────────────────────────────┐
│ 1. RENDER + TOKENIZE                                                 │
│    JSON request → model's internal prompt format (role markers,      │
│    tool schemas, special tokens; not public) → token IDs             │
│    Subword tokenizer (BPE-style); Claude's vocabulary isn't public   │
├──────────────────────────────────────────────────────────────────────┤
│ 2. PREFILL (parallel over all input tokens)                          │
│    • Cache hit? Reuse stored state for the cached prefix, compute    │
│      only the rest. That's why cached input is cheaper and faster    │
│    • Each layer: causal self-attention + feed-forward                │
│    • Writes K/V for every position into the KV cache                 │
│    • Produces logits for the first output token                      │
├──────────────────────────────────────────────────────────────────────┤
│ 3. DECODE LOOP (one token per step)                                  │
│    • Sample a token from the logits                                  │
│    • Run one forward pass for that token, attending over the KV      │
│      cache; append its K/V                                           │
│    • Stream the token's text (or tool-input JSON) to the client      │
├──────────────────────────────────────────────────────────────────────┤
│ 4. STOP CONDITION → stop_reason                                      │
│    end_turn            model finished its turn                       │
│    tool_use            model emitted tool_use block(s), wants results│
│    max_tokens          hit your cap (output truncated)               │
│    stop_sequence       hit one of your stop strings                  │
│    pause_turn          long server-tool turn paused; resend to resume│
│    refusal             safety classifier stopped the response        │
│    model_context_window_exceeded  ran out of context window          │
└──────────────────────────────────────────────────────────────────────┘
```

`tool_use` isn't decided "after" generation: the model generates the tool call as tokens like any other output, and the server parses them into a structured `tool_use` block.

---

## 4. THE STREAMING RESPONSE

### Why Stream?

| Reason | Impact |
|--------|--------|
| **Perceived latency** | Text appears as soon as the first token is decoded (time-to-first-token is dominated by prefill, so it grows with prompt size) |
| **Long outputs** | Non-streaming requests with very large `max_tokens` can hit HTTP timeouts; the SDKs push you to stream |
| **Early tool dispatch** | The client sees a complete tool call at `content_block_stop`, before the message ends |
| **Cancellation** | Close the connection to stop paying for further output |

### Streaming Event Types

| Event | Data |
|-------|------|
| `message_start` | Message ID, model, input-side `usage` (incl. cache read/write tokens) |
| `content_block_start` | Block index and type (`text`, `thinking`, `tool_use`, server-tool blocks) |
| `content_block_delta` | `text_delta`, `input_json_delta` (partial tool JSON), `thinking_delta`, `signature_delta` |
| `content_block_stop` | Block complete |
| `message_delta` | `stop_reason`, cumulative output `usage` |
| `message_stop` | Stream ends |
| `ping` / `error` | Keep-alive / mid-stream error such as `overloaded_error` |

---

## 5. TOOL CALL HANDLING

```ascii
┌─────────────────────────────────────────────────────────────────────┐
│ Response:                                                           │
│  content: [ {type: "text", text: "Let me check main.py"},           │
│             {type: "tool_use", id: "toolu_01A", name: "read_file",  │
│              input: {"path": "main.py"}} ]                          │
│  stop_reason: "tool_use"                                            │
│                                                                     │
│ Client:                                                             │
│  1. Append the WHOLE assistant content (text, thinking, tool_use)   │
│  2. Validate tool name + input (schema, path allow-list)            │
│  3. Check permissions / ask the user for risky actions              │
│  4. Execute; truncate huge outputs                                  │
│  5. Append ONE user message with ALL tool_result blocks:            │
│     {type: "tool_result", tool_use_id: "toolu_01A",                 │
│      content: "from fastapi import FastAPI\n...",                   │
│      is_error: false}                                               │
│  6. Resend the complete conversation                                │
│  7. Model either calls more tools or ends its turn                  │
└─────────────────────────────────────────────────────────────────────┘
```

Rules that bite in practice:

- Every `tool_use` needs a matching `tool_result` in the very next user message; otherwise you get a 400.
- Failed tools return `is_error: true` with the error text so the model can recover. Don't drop them.
- If thinking is on, pass thinking blocks back **unmodified** with the tool results (they're signed).
- Parse tool `input` as JSON; don't string-match it. Escaping can differ between models.

### Token Consumption Across Tool Calls

Each call re-sends all previous context:

```
Call 1 (user prompt):        5,000 input  +  500 output
Call 2 (after tool result):  6,000 input  +  300 output
Call 3 (after tool result):  7,000 input  +  400 output
Call 4 (final answer):       8,000 input  +  800 output
                             ──────────────────────────
Total:                      26,000 input  + 2,000 output
```

Three tool calls cost 28,000 tokens, versus ~5,500 if the same answer came in one call. In general, with a fixed prefix P and ~Δ new tokens per turn, cumulative input after N calls is about N·P + Δ·N²/2: **linear per call, quadratic in total.** With prompt caching, most of each call's input is billed as cache reads (~10% of the input rate, less on some models), which flattens that curve dramatically.

---

## 6. RESPONSE POST-PROCESSING (CLIENT SIDE)

What a well-built client does with the response:

| Step | Why |
|------|-----|
| Branch on `stop_reason` *before* reading content | `max_tokens` means truncated (maybe mid tool-JSON); `refusal` means no usable answer; `pause_turn` means resend to continue |
| Iterate content blocks by `type` | `content[0]` may be a `thinking` block, not text |
| Validate tool inputs against your schema | Or set `strict: true` on tools to get schema-valid inputs |
| Render text, show tool activity | UX; Claude Code shows each tool call as it runs |
| Record `usage` | Cost tracking, cache hit-rate monitoring (`cache_read_input_tokens`) |

---

## 7. COMPLETE END-TO-END EXAMPLE

"Add a health check endpoint to the FastAPI app", in a loop with no caching (illustrative counts):

```
CALL 1
  input:  tools 2,500 + system 2,000 + history 3,200 + message 8   = 5,708
  output: text + tool_use(read_file main.py)                        =    85

  client reads main.py → tool_result                                =   340

CALL 2
  input:  5,708 + 85 (assistant turn) + 340 (tool result)          = 6,133
  output: tool_use(edit main.py)                                    =    62

  client applies edit → tool_result "edit applied"                  =    62

CALL 3
  input:  6,133 + 62 + 62                                           = 6,257
  output: "Added GET /health ..."  stop_reason: end_turn            =   150

TOTAL  input 18,098   output 297
```

At example rates of $3 / $15 per million input/output tokens: 18,098 × $3/M + 297 × $15/M ≈ $0.054 + $0.004 = **$0.059**. With the 4,500-token tools+system prefix cached (written once at 1.25× in call 1, read at 0.1× in calls 2 and 3), billed input drops by roughly 40% for this short loop; caching the growing history too, and running more turns, pushes the saving much higher.

---

## 8. KEY TAKEAWAYS

| Concept | Why It Matters |
|---------|---------------|
| **The API is stateless** | Every call resends everything; the client owns conversation state |
| **Cost per call grows linearly; per session, quadratically** | Cache the prefix, compact or reset long sessions |
| **Order is tools → system → messages** | Put stable content first so caching works |
| **Output is priced at 5× input** (current Claude lineup) | Control verbosity and `effort`; thinking tokens bill as output |
| **`stop_reason` drives the loop** | `tool_use` → run tools and continue; `end_turn` → done; handle the rest explicitly |
| **TTFT comes from prefill** | Long prompts start slower; caching cuts TTFT on repeated prefixes |

---

> **Next:** [Tokenization & Token Calculation](04_TOKENIZATION_AND_COST.md) → How tokens are counted, priced, and optimized
