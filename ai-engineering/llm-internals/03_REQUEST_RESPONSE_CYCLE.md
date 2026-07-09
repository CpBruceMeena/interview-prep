# 🔄 The Request/Response Cycle — Complete End-to-End Flow

> **What data goes to the LLM, how it's processed, and how responses come back — with detailed token breakdowns.**

---

## 1. THE PROMPT ASSEMBLY

Before anything is sent to the API, the prompt must be assembled. This is the most important step because **everything the LLM sees is determined here**.

### 1.1 The Complete Prompt Structure

```ascii
┌────────────────────────────────────────────────────────────────────┐
│                    THE COMPLETE PROMPT                              │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  SYSTEM PROMPT (~2,000 tokens)                             │   │
│  │  ───────────────────────────                               │   │
│  │  "You are Claude, an AI assistant created by Anthropic...  │   │
│  │   Your capabilities:                                       │   │
│  │   - You can read, write, and edit files                    │   │
│  │   - You can run terminal commands                          │   │
│  │   - You can search code                                    │   │
│  │   Rules:                                                   │   │
│  │   - Always read files before editing                      │   │
│  │   - Make minimal changes                                   │   │
│  │   - Follow project conventions..."                         │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  TOOL DEFINITIONS (~2,500 tokens)                          │   │
│  │  ────────────────────────────                              │   │
│  │  Each tool has: name, description, input_schema (JSON)     │   │
│  │  [                                                         │   │
│  │    {name: "read_files", input_schema: {...}},              │   │
│  │    {name: "write_file", input_schema: {...}},              │   │
│  │    {name: "str_replace", input_schema: {...}},             │   │
│  │    {name: "run_terminal_command", input_schema: {...}},    │   │
│  │    ...                                                     │   │
│  │  ]                                                         │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  CONVERSATION HISTORY (~5,000+ tokens)                     │   │
│  │  ────────────────────────────────────                      │   │
│  │  [                                                         │   │
│  │    {"role": "user", "content": "..."},                    │   │
│  │    {"role": "assistant", "content": [                      │   │
│  │      {"type": "text", "text": "..."},                     │   │
│  │      {"type": "tool_use", ...}                             │   │
│  │    ]},                                                     │   │
│  │    {"role": "user", "content": [                           │   │
│  │      {"type": "tool_result", ...}                          │   │
│  │    ]},                                                     │   │
│  │    ... (repeated for each turn)                            │   │
│  │  ]                                                         │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  CURRENT USER MESSAGE (~200-2,000 tokens)                  │   │
│  │  ──────────────────────────────────────                    │   │
│  │  {"role": "user", "content": "Create a todo app..."}       │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### 1.2 Token Count Breakdown

| Component | Tokens | Percentage | Notes |
|-----------|--------|------------|-------|
| System prompt | ~2,000 | 10% | Fixed per session |
| Tool definitions | ~2,500 | 12.5% | Fixed per session |
| Conversation history | ~5,000 | 25% | Grows with each turn |
| File contents (context) | ~5,000 | 25% | From read_files results |
| Tool results | ~3,000 | 15% | From tool executions |
| Current user message | ~500 | 2.5% | The actual prompt |
| Reserved for output | ~2,000 | 10% | Token budget for response |
| **Total** | **~20,000** | **100%** | |

---

## 2. THE API REQUEST

### 2.1 HTTP Request Structure

```http
POST https://api.anthropic.com/v1/messages
Authorization: Bearer sk-ant-xxxxxxxxxxxxx
anthropic-version: 2025-01-01
content-type: application/json

{
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 8192,
  "temperature": 0.0,
  "top_p": 0.9,
  "top_k": 50,
  "stream": true,
  "stop_sequences": ["\n\nHuman:", "\n\nAssistant:"],
  "system": [
    {
      "type": "text",
      "text": "You are Claude, an AI assistant...",
      "cache_control": {"type": "ephemeral"}
    }
  ],
  "tools": [
    {
      "name": "read_files",
      "description": "Read the contents of one or more files...",
      "input_schema": {
        "type": "object",
        "properties": {
          "paths": {
            "type": "array",
            "items": {"type": "string"}
          }
        },
        "required": ["paths"]
      }
    }
  ],
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "Create a REST API for a todo app with FastAPI"
        }
      ]
    }
  ]
}
```

### 2.2 Request Fields Explained

| Field | Required | Purpose |
|-------|----------|---------|
| `model` | ✅ | Which Claude model to use |
| `max_tokens` | ✅ | Maximum tokens in the response |
| `messages` | ✅ | The conversation messages |
| `system` | ❌ | System prompt (optional, recommended) |
| `tools` | ❌ | Tool definitions for function calling |
| `temperature` | ❌ | Sampling temperature (default: 0.7) |
| `top_p` | ❌ | Nucleus sampling parameter |
| `top_k` | ❌ | Top-K sampling parameter |
| `stream` | ❌ | Whether to stream the response |
| `stop_sequences` | ❌ | Custom stop sequences |
| `metadata` | ❌ | User ID, tags for tracking |
| `tool_choice` | ❌ | Force a specific tool or allow any |

---

## 3. WHAT HAPPENS INSIDE THE LLM

Once the request reaches the API, here's what happens:

```ascii
┌──────────────────────────────────────────────────────────────────────┐
│                    LLM INFERENCE PIPELINE                             │
│                                                                      │
│  INPUT: Raw JSON request                                             │
│         │                                                             │
│         ▼                                                             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 1. TOKENIZATION                                                │   │
│  │    ┌───────────────────────────────────────────────────────┐  │   │
│  │    │ "Create a REST API" → [BOS] [1456] [892] [331] ...   │  │   │
│  │    │                                                        │  │   │
│  │    │ Claude uses a custom byte-pair encoding (BPE) tokenizer│  │   │
│  │    │ • 100,000+ vocabulary size                             │  │   │
│  │    │ • BPE tokens average ~3.5 characters                  │  │   │
│  │    │ • Special tokens: [BOS], [EOS], [PAD], [SEP]          │  │   │
│  │    └───────────────────────────────────────────────────────┘  │   │
│  │                                                               │   │
│  │         ▼                                                     │   │
│  │  ┌────────────────────────────────────────────────────────┐   │   │
│  │  │ 2. EMBEDDING LOOKUP                                     │   │   │
│  │  │    Each token ID → embedding vector (e.g., 5120 dims)   │   │   │
│  │  │    • Token embeddings: learned representations          │   │   │
│  │  │    • Positional embeddings: token position info         │   │   │
│  │  │    • Combined: embedding + position → transformer input │   │   │
│  │  └────────────────────────────────────────────────────────┘   │   │
│  │                                                               │   │
│  │         ▼                                                     │   │
│  │  ┌────────────────────────────────────────────────────────┐   │   │
│  │  │ 3. TRANSFORMER LAYERS (×N)                              │   │   │
│  │  │    For each layer (repeated N times):                   │   │   │
│  │  │                                                          │   │   │
│  │  │    a. Multi-Head Self-Attention                         │   │   │
│  │  │       • Each token "attends" to all previous tokens     │   │   │
│  │  │       • Causal masking: can't see future tokens         │   │   │
│  │  │       • QKV projections: Query, Key, Value vectors      │   │   │
│  │  │       • Scaled dot-product: Q·K^T / sqrt(d) → weights  │   │   │
│  │  │       • Weighted sum of values                          │   │   │
│  │  │                                                          │   │   │
│  │  │    b. Feed-Forward Network                              │   │   │
│  │  │       • Linear → SwiGLU → Linear                        │   │   │
│  │  │       • Expands hidden dim by ~4x then contracts        │   │   │
│  │  │                                                          │   │   │
│  │  │    c. Residual Connection + LayerNorm                   │   │   │
│  │  │       • output = LayerNorm(input + sublayer(input))      │   │   │
│  │  │                                                          │   │   │
│  │  │    d. Next Layer → ... → Final Layer                   │   │   │
│  │  └────────────────────────────────────────────────────────┘   │   │
│  │                                                               │   │
│  │         ▼                                                     │   │
│  │  ┌────────────────────────────────────────────────────────┐   │   │
│  │  │ 4. OUTPUT PROJECTION                                    │   │   │
│  │  │    • Final hidden state → linear projection             │   │   │
│  │  │    • Softmax → probability distribution over vocab      │   │   │
│  │  │    • Returns: logits (raw scores) for each token        │   │   │
│  │  │    • Token "def" has probability 0.45                   │   │   │
│  │  └────────────────────────────────────────────────────────┘   │   │
│  │                                                               │   │
│  │         ▼                                                     │   │
│  │  ┌────────────────────────────────────────────────────────┐   │   │
│  │  │ 5. SAMPLING                                              │   │   │
│  │  │    • Apply temperature scaling: logits / temperature    │   │   │
│  │  │    • Apply top_p filtering: keep tokens with cum prob   │   │   │
│  │  │    • Apply top_k filtering: keep top K tokens           │   │   │
│  │  │    • Sample from the filtered distribution              │   │   │
│  │  │    • Pick one token                                     │   │   │
│  │  │    • Append to sequence, go back to Step 3 for next tok│   │   │
│  │  └────────────────────────────────────────────────────────┘   │   │
│  │                                                               │   │
│  │         ▼                                                     │   │
│  │  ┌────────────────────────────────────────────────────────┐   │   │
│  │  │ 6. STOP CONDITION                                       │   │   │
│  │  │    Generation stops when ONE of these is met:           │   │   │
│  │  │    • max_tokens reached                                 │   │   │
│  │  │    • Stop sequence encountered                          │   │   │
│  │  │    • EOS token generated                                │   │   │
│  │  │    • Model decides tool_use (next response has tool)    │   │   │
│  │  └────────────────────────────────────────────────────────┘   │   │
│  │                                                               │   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  OUTPUT: Token IDs → Detokenize → Response text                     │
│          [1456] [892] [331] → "Create a"                             │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. THE STREAMING RESPONSE

Claude Code uses **streaming** to display responses in real-time.

### Why Streaming?

| Reason | Impact |
|--------|--------|
| **User experience** | User sees response immediately, not after full generation |
| **Perceived latency** | First token in ~500ms vs waiting 5-10s for full response |
| **Tool calls** | Can execute tools as soon as Claude decides — no wait |
| **Cancellation** | User can stop mid-generation if Claude goes wrong |

### Streaming Event Types

| Event | When | Data |
|-------|------|------|
| `message_start` | Stream begins | Message metadata, initial token counts |
| `content_block_start` | New content block (text or tool_use) | Block index and type |
| `content_block_delta` | New tokens in a block | Text delta or tool input JSON |
| `content_block_stop` | Block completed | None |
| `message_delta` | Message state change | Stop reason, updated token count |
| `message_stop` | Stream ends | None |

---

## 5. TOOL CALL HANDLING

When Claude decides to use a tool, the flow changes:

```ascii
┌─────────────────────────────────────────────────────────────────────┐
│                    TOOL CALL FLOW                                    │
│                                                                     │
│  Claude's response contains:                                        │
│  {                                                                 │
│    "content": [                                                    │
│      {"type": "text", "text": "Let me check your project..."},    │
│      {                                                             │
│        "type": "tool_use",                                         │
│        "id": "toolu_abc123",                                       │
│        "name": "read_files",                                       │
│        "input": {"paths": ["main.py"]}                             │
│      }                                                             │
│    ],                                                              │
│    "stop_reason": "tool_use"                                       │
│  }                                                                 │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Claude Code receives the response                          │   │
│  │                                                             │   │
│  │  1. Detects stop_reason = "tool_use"                        │   │
│  │  2. Extracts the tool_use block                             │   │
│  │  3. Validates tool name and arguments                       │   │
│  │  4. Executes the tool (e.g., reads main.py)                │   │
│  │  5. Appends tool result to conversation history             │   │
│  │                                                             │   │
│  │  Added to messages:                                         │   │
│  │  {                                                          │   │
│  │    "role": "user",                                          │   │
│  │    "content": [                                             │   │
│  │      {                                                      │   │
│  │        "type": "tool_result",                               │   │
│  │        "tool_use_id": "toolu_abc123",                      │   │
│  │        "content": "from fastapi import FastAPI\\n..."       │   │
│  │      }                                                      │   │
│  │    ]                                                        │   │
│  │  }                                                          │   │
│  │                                                             │   │
│  │  6. Sends the COMPLETE conversation back to Claude          │   │
│  │     (all previous messages + the new tool result)           │   │
│  │  7. Claude decides: more tools or final response            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Credit Consumption for Tool Calls

Each tool call = one additional API call with ALL previous context:

```
Turn 1 (user prompt):                5,000 input tokens  +  500 output tokens
Turn 2 (tool call + result):         6,000 input tokens  +  300 output tokens
Turn 3 (another tool):               7,000 input tokens  +  400 output tokens
Turn 4 (final response):             8,000 input tokens  +  800 output tokens
                                                     ──────────────
Total:                               26,000 input       +  2,000 output
```

That's **28,000 tokens** consumed for one interaction with 3 tool calls!

---

## 6. RESPONSE POST-PROCESSING

After the LLM response is received, Claude Code post-processes it:

```ascii
┌─────────────────────────────────────────────────────────────────────┐
│                    RESPONSE POST-PROCESSING                          │
│                                                                     │
│  RAW RESPONSE                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ I'll create this file for you:                              │   │
│  │                                                             │   │
│  │ Let me also check if there's an existing pyproject.toml     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ STEP 1: Validate response                                    │   │
│  │ • Check for valid JSON (if tool_use expected)                │   │
│  │ • Validate tool call arguments against schema                │   │
│  │ • Check for hallucinated file paths                          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ STEP 2: Display to user                                      │   │
│  │ • Stream text as it arrives (via SSE)                       │   │
│  │ • Show tool calls as they happen (e.g., "[Reading file...]") │   │
│  │ • Format code blocks with syntax highlighting                │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ STEP 3: Execute tools (if any)                               │   │
│  │ • Run the tool locally                                       │   │
│  │ • Capture tool output                                        │   │
│  │ • If tool fails, decide whether to retry or report error     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 7. COMPLETE END-TO-END EXAMPLE

Here's a real example with token counts:

```
USER: "Add a health check endpoint to the FastAPI app"
       └── 8 tokens

CLAUDE CODE assembles prompt:
  System prompt:                   2,000 tokens
  Tool schemas:                    2,500 tokens
  Conversation history:            3,200 tokens
  Current message:                    8 tokens
  ─────────────────────────────────────────
  Total input:                     5,708 tokens

CLAUDE API response (Turn 1):
  Stop reason: "tool_use"
  Tool: read_files (main.py)
  Output:                            85 tokens
  ─────────────────────────────────────────
  Total output:                        85 tokens

CLAUDE CODE executes read_files:
  Gets main.py content: 340 tokens
  Appends tool_result to history

CLAUDE API call (Turn 2):
  Total input:                     6,133 tokens  (5,708 + 85 + 340)
  
  Stop reason: "tool_use"
  Tool: str_replace (edit main.py)
  Output:                            62 tokens
  ─────────────────────────────────────────
  Total output:                        62 tokens

CLAUDE CODE executes str_replace:
  Adds health check endpoint
  Appends tool_result

CLAUDE API call (Turn 3):
  Total input:                     6,257 tokens
  
  Stop reason: "end_turn"
  Content: "Done! Added /health endpoint..."
  Output:                           150 tokens
  ─────────────────────────────────────────
  Total output:                       150 tokens

TOTAL for this interaction:
  Input:   5,708 + 6,133 + 6,257 = 18,098 tokens
  Output:    85 +    62 +   150 =    297 tokens
  ─────────────────────────────────────────────
  Total:                    18,395 tokens
```

---

## 8. KEY TAKEAWAYS

| Concept | Why It Matters |
|---------|---------------|
| **Each turn resends ALL context** | Token costs grow linearly with conversation length |
| **Tool calls double the cost** | Each tool call = one more API request with full context |
| **Streaming reduces perceived latency** | First token in ~500ms, even for long responses |
| **System prompt is per-session** | Same 2,000 tokens every request — use prompt caching |
| **Output tokens cost more** | Typically 3-4x more expensive than input tokens |
| **Stop_reason determines next action** | `tool_use` = execute tool and continue; `end_turn` = done |

---

> **Next:** [Tokenization & Token Calculation](04_TOKENIZATION_AND_COST.md) → How tokens are counted, priced, and optimized
