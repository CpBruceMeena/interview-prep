# 🔧 Harness & Loop Engineering

> **The emerging disciplines of building production-grade scaffolding around AI models and designing autonomous agentic loops.**

---

## Overview

As AI models converge in raw intelligence, the **differentiator** for enterprise systems is the quality of the infrastructure surrounding them. **Harness Engineering** and **Loop Engineering** are the two pillars of this infrastructure layer.

```ascii
┌─────────────────────────────────────────────────────────────────┐
│                    AI SYSTEM ARCHITECTURE                         │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                  THE HARNESS (Scaffolding)                   │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │ │
│  │  │Guardrails│ │Execution │ │Verifcation│ │Observability │  │ │
│  │  │(Safety)  │ │Sandbox   │ │(Testing)  │ │(Tracing)     │  │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                             │                                     │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                   THE LOOP (Orchestration)                   │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │ │
│  │  │ Perceive │ →  Reason  │ →   Act    │ →   Observe    │  │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────┬───────┘  │ │
│  │                                                │           │ │
│  │  └────────────────── Iterate ──────────────────┘           │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Agent = Model + Harness                                          │
│  Quality = Loop Design × Harness Robustness                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Contents

| # | Document | Description |
|---|----------|-------------|
| 1 | [Harness Engineering](01_HARNESS_ENGINEERING.md) | Evaluation harnesses, agent scaffolding, guardrails, verification loops, enterprise runtime |
| 2 | [Loop Engineering](02_LOOP_ENGINEERING.md) | Agentic loops, ReAct patterns, feedback cycles, termination logic, production loop design |

---

## Key Insight

> **"The model is the brain. The harness is the body. The loop is the circulatory system."**

- **Harness Engineering** answers: *How do we make the agent safe, observable, and controllable?*
- **Loop Engineering** answers: *How do we make the agent autonomous, iterative, and goal-directed?*

---

## Related Modules

- **[Agents](../agents/README.md)** — Agent architectures, orchestration, tool-use patterns
- **[MCP](../mcp/README.md)** — Protocol for agent-tool communication (connectors in the harness)
- **[RAG](../rag/README.md)** — Knowledge retrieval (memory in the harness)
