# 🤖 LLM Internals — Claude, Model Interaction, Tokenization & the Complete Request/Response Cycle

> **A deep-dive into how LLMs like Claude work under the hood — from prompt assembly to token calculation, model inference, and response generation.**

---

## 📦 Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [How Claude Works](01_HOW_CLAUDE_WORKS.md) | Model architecture, training, context window, safety |
| 2 | [Claude Code/Editor — Interaction Flow](02_CLAUDE_CODE_INTERACTION.md) | How Claude Code/Edition interacts with models, tools, and the file system |
| 3 | [The Request/Response Cycle](03_REQUEST_RESPONSE_CYCLE.md) | Complete end-to-end flow: what data is sent, how the LLM processes it, how responses come back |
| 4 | [Tokenization & Token Calculation](04_TOKENIZATION_AND_COST.md) | How tokens work — input, output, pricing, and optimization |
| 5 | [System Prompt Engineering](05_SYSTEM_PROMPT_ENGINEERING.md) | Crafting effective system prompts, role design, constraints |
| 6 | [How Claude Makes Code Changes](06_HOW_CLAUDE_MAKES_CODE_CHANGES.md) | Step-by-step flow of code changes, debugging, and user input decisions |

---

## 🎯 Why This Matters

Understanding LLM internals is critical for:

| Reason | Impact |
|--------|--------|
| **Cost optimization** | Token-aware design reduces API costs by 30-70% |
| **Latency reduction** | Understanding inference helps design for faster responses |
| **Prompt engineering** | Knowing how models process input improves output quality |
| **Debugging** | Understanding tokenization helps diagnose weird model behavior |
| **Production deployment** | Capacity planning, caching, and batching strategies |
| **Agent design** | Tool-use loops depend on understanding the request/response cycle |

---

## 🏗️ Architecture Overview

```ascii
┌──────────────────────────────────────────────────────────────────────────┐
│                        COMPLETE LLM INTERACTION FLOW                      │
│                                                                          │
│  USER                                                                     │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │ "Write a function to calculate Fibonacci numbers in Python"      │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                   │                                       │
│                                   ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │                    PROMPT ASSEMBLY                                │    │
│  │                                                                   │    │
│  │  System Prompt + Messages + Tools → Tokenized → LLM              │    │
│  │                                                                   │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐  │    │
│  │  │ System     │  │ User Msgs  │  │ Tool Defs  │  │ Context  │  │    │
│  │  │ "You are   │  │ "Write     │  │ [execute,  │  │ [files,  │  │    │
│  │  │ a Python   │+ │ Fibonacci" │+ │ read_file] │+ │ errors]  │  │    │
│  │  │ expert..." │  │            │  │            │  │          │  │    │
│  │  └────────────┘  └────────────┘  └────────────┘  └──────────┘  │    │
│  └──────────────────────────┬───────────────────────────────────────┘    │
│                             │                                           │
│                             ▼                                           │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │                    TOKENIZATION                                   │    │
│  │                                                                   │    │
│  │  "Write a function..." → [1456] [892] [331] [1203] ... [789]    │    │
│  │                                                                   │    │
│  │  Input tokens: ~1,200  │  Context window used: 23%               │    │
│  └──────────────────────────┬───────────────────────────────────────┘    │
│                             │                                           │
│                             ▼                                           │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │                    LLM INFERENCE (Claude)                         │    │
│  │                                                                   │    │
│  │  1. Token embeddings → Transformer layers → Attention → FFN     │    │
│  │  2. Next-token prediction (auto-regressive)                       │    │
│  │  3. Sampling: temperature=0.7, top_p=0.9, top_k=50              │    │
│  │  4. Response generated token by token                             │    │
│  │                                                                   │    │
│  │  Output: "def fibonacci(n):\n    if n <= 1:\n        return n..." │    │
│  │  Output tokens: ~350                                              │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Links

| Topic | Read This First |
|-------|-----------------|
| **New to LLMs?** | [How Claude Works](01_HOW_CLAUDE_WORKS.md) |
| **Using Claude Code?** | [Claude Code/Editor Interaction](02_CLAUDE_CODE_INTERACTION.md) |
| **Building agents?** | [Request/Response Cycle](03_REQUEST_RESPONSE_CYCLE.md) |
| **Optimizing costs?** | [Tokenization & Cost](04_TOKENIZATION_AND_COST.md) |
| **Writing prompts?** | [System Prompt Engineering](05_SYSTEM_PROMPT_ENGINEERING.md) |

---

## 🔗 Related Modules

- **[AI Agents](../agents/README.md)** — How agents use LLMs in loops with tool calls
- **[MCP Protocol](../mcp/README.md)** — How MCP connects AI applications to tools
- **[RAG Pipeline](../rag/README.md)** — How retrieval augment LLM knowledge
