# 🧠 AI Engineering — RAG, MCP & AI Agents

> **From fundamentals to production deployment — complete guides, implementations, and interview preparation for AI engineering systems**

---

## 📦 Modules

| Module | Description | Key Topics |
|--------|-------------|------------|
| 📚 **[RAG](rag/README.md)** | Retrieval-Augmented Generation | Pipeline architecture, embeddings, retrieval strategies, production scaling, fine-tuning |
| 🔌 **[MCP](mcp/README.md)** | Model Context Protocol | Protocol mechanics, server implementation, RAG integration, production deployment |
| 🤖 **[Agents](agents/README.md)** | AI Agent Engineering | Agent architecture, orchestration, tool-use loops, multi-agent systems, production guardrails |
| 🏭 **[Production AI](production-ai/INTERVIEW_QUESTIONS.md)** | Production AI Engineering & Interview Prep | RAG debugging, hallucination detection, cost optimization, latency debugging, enterprise agents, MCP security, multi-agent workflows |
| 🔧 **[Harness & Loop Engineering](harness-engineering/README.md)** | Production Scaffolding & Agentic Loops | Evaluation/agent harnesses, guardrails, sandboxing, verification loops, ReAct patterns, loop safety, termination logic |

---

## 🏗️ Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                        AI AGENT (Host)                              │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  Planning → Memory → Tool-Use → Execution → Feedback        │ │
│  └──────────────────────────┬───────────────────────────────────┘ │
│                             │                                     │
└─────────────────────────────┼─────────────────────────────────────┘
                              │ MCP Protocol (JSON-RPC 2.0)
          ┌───────────────────┼────────────────────┐
          │                   │                    │
          ▼                   ▼                    ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│   RAG Pipeline   │ │   MCP Server     │ │   External APIs  │
│  (Knowledge)     │ │  (Tools/Actions) │ │  (3rd Party)     │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

---

## 🚀 Quick Start

```bash
# RAG — Index documents and query
cd rag/
pip install -r implementation/requirements.txt
python implementation/main.py --index --docs ./data/documents/
python implementation/main.py --query "What is RAG?"

# MCP — Start servers
cd ../mcp/
python -m servers.calculator_server   # Test the calculator MCP server
python -m clients.python_client --server calculator --list  # List tools
```

---

## 📚 Recommended Learning Path

1. **RAG Fundamentals** → Understand knowledge retrieval architecture
2. **MCP Fundamentals** → Learn protocol mechanics and primitives
3. **MCP Implementation & RAG** → Build servers and connect RAG
4. **MCP Production Architecture** → Enterprise security, deployment
5. **Agents** → Orchestration, tool-use loops, production guardrails
6. **Production AI** → Debugging, optimization, and enterprise architecture for production systems
7. **Harness Engineering & Loop Engineering** → Production scaffolding, loop design
8. **Interview Questions** → Prepare for Staff/Principal-level interviews
