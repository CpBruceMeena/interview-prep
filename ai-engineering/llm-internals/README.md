# 🤖 LLM Internals — Claude, Claude Code, Tokens & the Request/Response Cycle

> **How LLMs like Claude work under the hood, from prompt assembly to tokenization, inference, sampling, tool-use loops and cost. Claude- and Claude Code–specific claims are checked against Anthropic's official docs (October 2026); general transformer mechanics are labelled as such, because Anthropic doesn't publish Claude's architecture.**

---

## 📦 Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [How Claude Works](01_HOW_CLAUDE_WORKS.md) | What's public vs not, transformer background, training (pre-training, RLHF, Constitutional AI), context window, prefill/decode, sampling, safety |
| 2 | [Claude Code — Interaction Flow](02_CLAUDE_CODE_INTERACTION.md) | The agentic harness: what's loaded into context, real tool names, the request/stream/tool loop, context management, permissions |
| 3 | [The Request/Response Cycle](03_REQUEST_RESPONSE_CYCLE.md) | Messages API request anatomy, what happens server-side, streaming events, stop reasons, token growth across tool calls |
| 4 | [Tokenization & Token Calculation](04_TOKENIZATION_AND_COST.md) | BPE, counting tokens with the API, input/output/cache/batch pricing, prompt caching mechanics |
| 5 | [System Prompt Engineering](05_SYSTEM_PROMPT_ENGINEERING.md) | Anthropic's current prompting guidance, patterns, antipatterns, and evaluating prompts |
| 6 | [How Claude Makes Code Changes](06_HOW_CLAUDE_MAKES_CODE_CHANGES.md) | Traced code-change and debugging loops: Read/Edit/Write/Bash, permissions, hooks, checkpoints |
| 7 | [Cost Optimization Best Practices](07_COST_OPTIMIZATION_BEST_PRACTICES.md) | The cost levers in order of payoff, measurement, and Claude Code habits |

---

## 🎯 Why This Matters

| Reason | Impact |
|--------|--------|
| **Cost** | Token-aware design (caching, batching, context hygiene) is usually the biggest lever on an LLM bill |
| **Latency** | Prefill drives time-to-first-token; decode drives tokens per second |
| **Prompt quality** | Knowing what the model actually sees explains most "weird" behaviour |
| **Debugging** | Tokenization explains character-level failures and surprising token counts |
| **Production** | Capacity planning, rate limits, caching and batching strategies |
| **Agent design** | Tool-use loops are just repeated requests with growing context |

---

## 🏗️ Architecture Overview

```ascii
┌──────────────────────────────────────────────────────────────────────────┐
│                        ONE LLM REQUEST, END TO END                       │
│                                                                          │
│  USER: "Write a function to calculate Fibonacci numbers in Python"       │
│                                   │                                      │
│                                   ▼                                      │
│  PROMPT ASSEMBLY (client)   tools → system → messages                    │
│    tool defs   system prompt   history + tool results   new message      │
│                                   │                                      │
│                                   ▼                                      │
│  TOKENIZATION (server)      text → token IDs (model-specific tokenizer)  │
│    e.g. ~1,200 input tokens; count exactly with count_tokens             │
│                                   │                                      │
│                                   ▼                                      │
│  INFERENCE                                                               │
│    1. Prefill: all input tokens in parallel → KV cache                   │
│       (cached prefix reused if prompt caching hits)                      │
│    2. Decode: one token per step, sampled from the next-token            │
│       distribution (shaped by effort/thinking on current models)         │
│    3. Stop: end_turn | tool_use | max_tokens | stop_sequence | refusal   │
│                                   │                                      │
│                                   ▼                                      │
│  RESPONSE  content blocks (thinking, text, tool_use) + stop_reason       │
│            + usage (input, cache read/write, output tokens)              │
│    "def fibonacci(n):\n    if n <= 1:\n        return n ..."             │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Links

| Topic | Read This First |
|-------|-----------------|
| **New to LLMs?** | [How Claude Works](01_HOW_CLAUDE_WORKS.md) |
| **Using Claude Code?** | [Claude Code Interaction](02_CLAUDE_CODE_INTERACTION.md) |
| **Building agents?** | [Request/Response Cycle](03_REQUEST_RESPONSE_CYCLE.md) |
| **Optimizing costs?** | [Cost Optimization Best Practices](07_COST_OPTIMIZATION_BEST_PRACTICES.md) (start here) or [Tokenization & Cost](04_TOKENIZATION_AND_COST.md) (deep dive) |
| **Writing prompts?** | [System Prompt Engineering](05_SYSTEM_PROMPT_ENGINEERING.md) |

---

## 🔗 Related Modules

- **[AI Agents](../agents/README.md)** — How agents use LLMs in loops with tool calls
- **[MCP Protocol](../mcp/README.md)** — How MCP connects AI applications to tools
- **[RAG Pipeline](../rag/README.md)** — How retrieval augments LLM knowledge
- **[Harness & Loop Engineering](../harness-engineering/README.md)** — Building the scaffolding around the model
