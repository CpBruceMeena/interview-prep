# 💻 Claude Code/Editor — How It Interacts with LLMs

> **A detailed walkthrough of what happens when you use Claude Code (CLI) or Claude Editor — the full request/response cycle between the tool and the underlying model.**

---

## 1. WHAT IS CLAUDE CODE?

**Claude Code** (formerly Claude Code CLI) is Anthropic's official developer tool that brings Claude into the terminal. It connects to the Claude API and orchestrates complex coding tasks using tools and multi-turn conversations.

Similarly, **Claude Editor** is the in-editor version that works inside VS Code, JetBrains, and other IDEs.

```ascii
┌──────────────────────────────────────────────────────────────────┐
│                      CLAUDE CODE ARCHITECTURE                     │
│                                                                  │
│  ┌────────────┐     ┌────────────┐     ┌──────────────────┐    │
│  │   User     │────►│ Claude Code│────►│  Claude API       │    │
│  │ (Terminal) │     │   (CLI)    │     │  (Anthropic)      │    │
│  └────────────┘     │            │     └──────────────────┘    │
│                     │  ┌──────┐  │                              │
│                     │  │Tools │  │                              │
│                     │  │• Read│  │                              │
│                     │  │• Write│ │                              │
│                     │  │• Bash │  │                              │
│                     │  │• Search│ │                              │
│                     │  └──────┘  │                              │
│                     └────────────┘                              │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. THE FULL INTERACTION CYCLE

When you type a prompt in Claude Code, the following happens:

```ascii
┌─────────────────────────────────────────────────────────────────────┐
│                    COMPLETE INTERACTION CYCLE                        │
│                                                                     │
│  USER                                                               │
│  │ "Create a REST API for a todo app with FastAPI"                  │
│  ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    CLAUDE CODE (CLI)                          │   │
│  │                                                              │   │
│  │  STEP 1: Collect context                                     │   │
│  │  ├── Read files in current directory                         │   │
│  │  ├── Read relevant config files (pyproject.toml, etc.)       │   │
│  │  └── Check git status for existing changes                   │   │
│  │                                                              │   │
│  │  STEP 2: Build the prompt                                    │   │
│  │  ┌──────────────────────────────────────────────────────┐   │   │
│  │  │  System Prompt (pre-built, ~2000 tokens):             │   │   │
│  │  │  "You are Claude, an AI assistant created by...       │   │   │
│  │  │   You have access to tools: read_files, write_file,   │   │   │
│  │  │   edit_file, run_terminal_command, search_code...     │   │   │
│  │  │   Follow these rules:..."                             │   │   │
│  │  │                                                        │   │   │
│  │  │  + User's current message                             │   │   │
│  │  │  + Conversation history (previous turns)              │   │   │
│  │  │  + Tool results from previous calls                   │   │   │
│  │  │  + Context gathered (file contents, search results)   │   │   │
│  │  └──────────────────────────────────────────────────────┘   │   │
│  │                                                              │   │
│  │  STEP 3: Send to Claude API                                 │   │
│  │  ┌──────────────────────────────────────────────────────┐   │   │
│  │  │  POST https://api.anthropic.com/v1/messages           │   │   │
│  │  │  Headers:                                            │   │   │
│  │  │    x-api-key: sk-ant-...                             │   │   │
│  │  │    anthropic-version: 2025-01-01                     │   │   │
│  │  │    content-type: application/json                    │   │   │
│  │  │                                                        │   │   │
│  │  │  Body:                                                │   │   │
│  │  │  {                                                    │   │   │
│  │  │    "model": "claude-sonnet-4-20250514",               │   │   │
│  │  │    "max_tokens": 8192,                                │   │   │
│  │  │    "temperature": 0.0,                                │   │   │
│  │  │    "messages": [                                      │   │   │
│  │  │      {"role": "user", "content": "Create a REST..."} │   │   │
│  │  │    ],                                                 │   │   │
│  │  │    "system": "You are Claude, an AI assistant...",   │   │   │
│  │  │    "tools": [                                         │   │   │
│  │  │      {"name": "read_files", "description": "...",    │   │   │
│  │  │       "input_schema": {..."}},                       │   │   │
│  │  │      {"name": "write_file", ...},                    │   │   │
│  │  │      {"name": "run_terminal_command", ...}           │   │   │
│  │  │    ]                                                  │   │   │
│  │  │  }                                                    │   │   │
│  │  └──────────────────────────────────────────────────────┘   │   │
│  │                                                              │   │
│  │  STEP 4: Receive streaming response                          │   │
│  │  ┌──────────────────────────────────────────────────────┐   │   │
│  │  │  Event: message_start                                │   │   │
│  │  │  Event: content_block_start (text)                   │   │   │
│  │  │  Event: content_block_delta (text: "I'll create a")  │   │   │
│  │  │  Event: content_block_delta (text: " REST API for")  │   │   │
│  │  │  Event: content_block_stop                           │   │   │
│  │  │  Event: content_block_start (tool_use)               │   │   │
│  │  │  Event: message_delta (stop_reason: tool_use)        │   │   │
│  │  │  Event: message_stop                                 │   │   │
│  │  └──────────────────────────────────────────────────────┘   │   │
│  │                                                              │   │
│  │  STEP 5: Execute tools                                      │   │
│  │  ├── Claude wants to read the project structure              │   │
│  │  ├── Claude Code runs read_files on local machine            │   │
│  │  └── Results are added to conversation history               │   │
│  │                                                              │   │
│  │  STEP 6: Repeat Steps 3-5 until Claude is done               │   │
│  │  (Each tool call = one more API round-trip)                  │   │
│  │                                                              │   │
│  │  STEP 7: Display final response to user                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. WHAT DATA DO WE SEND TO THE LLM?

Every API call includes the following:

### 3.1 System Prompt (Pre-built by Claude Code)

The system prompt is a carefully crafted instruction set that defines Claude's behavior in the coding environment:

```
You are Claude, an AI assistant created by Anthropic to be helpful,
harmless, and honest. Your mission is to assist users with software
engineering tasks.

TOOLS:
You have access to the following tools:
- read_files: Read file contents from the project
- write_file: Create or overwrite a file
- str_replace: Make targeted edits to existing files
- run_terminal_command: Execute shell commands
- code_search: Search for patterns in the codebase
- list_directory: List files in a directory
- ... (more tools)

RULES:
1. Always read files before making changes to understand context
2. Make minimal, targeted changes — don't rewrite entire files
3. Run tests after making changes to verify correctness
4. Ask the user for clarification when requirements are ambiguous
5. Follow existing project conventions and patterns
6. Never expose API keys or secrets in responses
...
```

### 3.2 Messages Array

Contains the entire conversation history:

```json
[
  {
    "role": "user",
    "content": [
      {
        "type": "text",
        "text": "Create a REST API for a todo app with FastAPI"
      }
    ]
  },
  {
    "role": "assistant",
    "content": [
      {
        "type": "text",
        "text": "I'll create a FastAPI todo app. Let me first check the project structure..."
      },
      {
        "type": "tool_use",
        "id": "toolu_abc123",
        "name": "list_directory",
        "input": {"path": "."}
      }
    ]
  },
  {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_abc123",
        "content": "main.py\npyproject.toml\nREADME.md"
      }
    ]
  },
  // ... more turns
]
```

### 3.3 Tool Definitions

The schemas for all available tools:

```json
[
  {
    "name": "read_files",
    "description": "Read the contents of one or more files from the local filesystem.",
    "input_schema": {
      "type": "object",
      "properties": {
        "paths": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Array of file paths to read"
        }
      },
      "required": ["paths"]
    }
  },
  {
    "name": "str_replace",
    "description": "Make targeted edits to a file by finding and replacing strings.",
    "input_schema": {
      "type": "object",
      "properties": {
        "path": {"type": "string"},
        "old_string": {"type": "string", "description": "Exact string to find"},
        "new_string": {"type": "string", "description": "String to replace with"}
      },
      "required": ["path", "old_string", "new_string"]
    }
  }
]
```

### 3.4 Model Parameters

| Parameter | Value | Why |
|-----------|-------|-----|
| `model` | `claude-sonnet-4-20250514` | Best coding model |
| `max_tokens` | 8192 | Allow long responses |
| `temperature` | 0.0 | Deterministic, predictable |
| `system` | ~2000 token prompt | Defines behavior |
| `tools` | 15-20 tool schemas | Enable code editing |
| `stream` | true | Real-time display |

---

## 4. HOW DO WE GET RESPONSES BACK?

Responses come back as **server-sent events (SSE)** — a stream of structured events.

### 4.1 Streaming Events

```ascii
Time ──────────────────────────────────────────────────────────────►

Event 1: message_start
┌────────────────────────────────────────────────────────────────┐
│ {                                                              │
│   "type": "message_start",                                     │
│   "message": {                                                 │
│     "id": "msg_01ABCxyz",                                      │
│     "type": "message",                                         │
│     "role": "assistant",                                       │
│     "content": [],                                             │
│     "model": "claude-sonnet-4-20250514",                      │
│     "stop_reason": null,                                       │
│     "usage": {                                                 │
│       "input_tokens": 2850,                                    │
│       "output_tokens": 5                                       │
│     }                                                          │
│   }                                                            │
│ }                                                              │
└────────────────────────────────────────────────────────────────┘

Event 2: content_block_start (type: text)
┌────────────────────────────────────────────────────────────────┐
│ {                                                              │
│   "type": "content_block_start",                               │
│   "index": 0,                                                  │
│   "content_block": {                                           │
│     "type": "text",                                            │
│     "text": ""                                                 │
│   }                                                            │
│ }                                                              │
└────────────────────────────────────────────────────────────────┘

Events 3-N: content_block_delta (the actual response)
┌────────────────────────────────────────────────────────────────┐
│ { "type": "content_block_delta", "index": 0,                  │
│   "delta": { "type": "text_delta", "text": "I'll" } }        │
│ { "type": "content_block_delta", "index": 0,                  │
│   "delta": { "type": "text_delta", "text": " create" } }     │
│ { "type": "content_block_delta", "index": 0,                  │
│   "delta": { "type": "text_delta", "text": " a FastAPI" } }  │
│ { "type": "content_block_delta", "index": 0,                  │
│   "delta": { "type": "text_delta", "text": " todo app" } }   │
│ ...                                                            │
└────────────────────────────────────────────────────────────────┘

Event: content_block_stop
┌────────────────────────────────────────────────────────────────┐
│ { "type": "content_block_stop", "index": 0 }                  │
└────────────────────────────────────────────────────────────────┘

Event: content_block_start (type: tool_use)
┌────────────────────────────────────────────────────────────────┐
│ {                                                              │
│   "type": "content_block_start",                               │
│   "index": 1,                                                  │
│   "content_block": {                                           │
│     "type": "tool_use",                                        │
│     "id": "toolu_abc123",                                      │
│     "name": "read_files",                                      │
│     "input": {}                                                │
│   }                                                            │
│ }                                                              │
└────────────────────────────────────────────────────────────────┘

Event: message_delta
┌────────────────────────────────────────────────────────────────┐
│ {                                                              │
│   "type": "message_delta",                                     │
│   "delta": {                                                   │
│     "stop_reason": "tool_use",                                 │
│     "stop_sequence": null                                      │
│   },                                                           │
│   "usage": {                                                   │
│     "output_tokens": 450                                       │
│   }                                                            │
│ }                                                              │
└────────────────────────────────────────────────────────────────┘

Event: message_stop
┌────────────────────────────────────────────────────────────────┐
│ { "type": "message_stop" }                                    │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 Non-Streaming Response (Batch)

If streaming is disabled, the response comes as a single object:

```json
{
  "id": "msg_01ABCxyz",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "I'll create a FastAPI todo app. Let me first check the project structure..."
    },
    {
      "type": "tool_use",
      "id": "toolu_abc123",
      "name": "list_directory",
      "input": {"path": "."}
    }
  ],
  "model": "claude-sonnet-4-20250514",
  "stop_reason": "tool_use",
  "usage": {
    "input_tokens": 2850,
    "output_tokens": 450
  }
}
```

---

## 5. THE TOOL USE LOOP

This is the most important concept in Claude Code:

```ascii
                    THE TOOL USE LOOP
                    ────────────────

  User sends a prompt
         │
         ▼
  ┌─────────────────┐
  │  Send to Claude  │──────┐
  │  API             │      │
  └────────┬─────────┘      │
           │                │
           ▼                │
  ┌─────────────────┐      │
  │  Claude responds │      │  Repeat until
  │  with text +     │      │  Claude says
  │  optional tool   │      │  "text only"
  │  call             │      │  (stop_reason:
  └────────┬─────────┘      │   end_turn)
           │                │
           ▼                │
  ┌─────────────────┐      │
  │  Is stop_reason │ Yes  │
  │  = "tool_use"?  │──────┘
  └────────┬─────────┘
           │ No
           ▼
  ┌─────────────────┐
  │  Display final   │
  │  response to     │
  │  user            │
  └─────────────────┘
```

### How Many Round-Trips?

| Task Complexity | Typical Round-Trips |
|----------------|-------------------|
| **Simple question** | 1 (just text response) |
| **Quick edit** | 2-3 (read file → edit → verify) |
| **New feature** | 5-15 (multiple file reads/writes) |
| **Complex refactor** | 10-30+ (extensive context gathering) |
| **Debugging** | 5-20 (iterate on fix → test → fix) |

---

## 6. WHAT DATA IS INCLUDED IN EACH REQUEST?

As the conversation grows, so does the request payload:

```
Turn 1:  ~3,000  tokens  (user prompt + system + tools)
Turn 2:  ~5,000  tokens  (+ Claude's response + tool results)
Turn 5:  ~12,000 tokens  (+ conversation history)
Turn 10: ~25,000 tokens  (+ accumulated context)
Turn 20: ~50,000 tokens  (+ file contents, search results)
```

### Breakdown of a Typical Request Payload

```ascii
┌──────────────────────────────────────────────────────────────────┐
│                    REQUEST PAYLOAD BREAKDOWN                      │
│                                                                  │
│  Total: ~15,000 tokens (example: medium-complexity task)        │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  System Prompt:          2,000 tokens (13%)                │ │
│  │  ─ Includes persona, rules, tool descriptions              │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Conversation History:    5,000 tokens (33%)               │ │
│  │  ─ Previous user messages, Claude responses, tool results  │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  File Contents (context): 5,000 tokens (33%)               │ │
│  │  ─ Files Claude read to understand the codebase            │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Current User Message:      500 tokens (3%)                │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Tool Schemas:             2,500 tokens (17%)              │ │
│  │  ─ JSON schemas for all available tools                    │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 7. KEY DIFFERENCES: CLAUDE CODE vs CLAUDE EDITOR vs CLAUDE WEB

| Aspect | Claude Code (CLI) | Claude Editor (IDE) | Claude Web (Chat) |
|--------|-------------------|--------------------|--------------------|
| **Tools** | File system, shell, search | File system, IDE integration | Limited (thinking, artifacts) |
| **Context** | Full project | Current file + project | User-provided |
| **Use case** | Complex coding tasks | In-editor assistance | General chat |
| **Model** | Latest Sonnet/Opus | Latest Sonnet | Latest Sonnet/Opus |
| **System prompt** | Coding-focused | IDE integration | General assistant |
| **Streaming** | Yes (SSE) | Yes (SSE) | Yes (SSE) |

---

## 8. SUMMARY: THE COMPLETE DATA FLOW

```ascii
┌─────────────────────────────────────────────────────────────────────┐
│                  THE COMPLETE DATA FLOW                               │
│                                                                      │
│  YOU (User)                    CLAUDE CODE              CLAUDE API   │
│    │                               │                       │         │
│    │  "Create a todo app"          │                       │         │
│    │─────────────────────────────►│                       │         │
│    │                               │                       │         │
│    │                               │ 1. Read project files │         │
│    │                               │ 2. Build prompt       │         │
│    │                               │                       │         │
│    │                               │ 3. POST /messages     │         │
│    │                               │──────────────────────►│         │
│    │                               │   System: ~2000 tok   │         │
│    │                               │   Messages: ~500 tok  │         │
│    │                               │   Tools: 15 schemas   │         │
│    │                               │   Model: sonnet-4     │         │
│    │                               │                       │         │
│    │                               │ 4. SSE Stream ◄──────│         │
│    │                               │   text: "I'll create" │         │
│    │                               │   tool_use: read_file │         │
│    │                               │   stop_reason: tool   │         │
│    │                               │                       │         │
│    │                               │ 5. Execute tool       │         │
│    │                               │   (read main.py)      │         │
│    │                               │                       │         │
│    │                               │ 6. POST /messages     │         │
│    │                               │   (with tool result)  │         │
│    │                               │──────────────────────►│         │
│    │                               │   ...loop continues...│         │
│    │                               │                       │         │
│    │  "Here's your todo app..."    │                       │         │
│    │◄─────────────────────────────│                       │         │
│    │                               │                       │         │
└─────────────────────────────────────────────────────────────────────┘
```

---

> **Next:** [The Request/Response Cycle](03_REQUEST_RESPONSE_CYCLE.md) → Complete end-to-end flow
