# 🎯 AI Engineer & Forward Deploy Engineer — Comprehensive Preparation Strategy

> **Your guide to landing roles at the intersection of software engineering and AI**  
> **Target Roles:** AI Engineer · Forward Deployed Engineer (FDE) · AI Infrastructure Engineer · ML Engineer (Applied)

---

## Table of Contents

1. [Role Breakdown — What Each Role Actually Does](#1-role-breakdown)
2. [The AI Interview Landscape (2025-2026)](#2-the-ai-interview-landscape-2025-2026)
3. [Preparation Roadmap by Role](#3-preparation-roadmap-by-role)
4. [Core Technical Pillars](#4-core-technical-pillars)
5. [System Design for AI Systems](#5-system-design-for-ai-systems)
6. [Forward Deploy Engineer — Special Preparation](#6-forward-deploy-engineer-special-preparation)
7. [The Behavioral Interview — AI Edition](#7-the-behavioral-interview-ai-edition)
8. [Study Resources & Practice Plan](#8-study-resources-practice-plan)

---

## 1. Role Breakdown

### AI Engineer

**What they do:** Design and build AI-powered features — agentic systems, RAG pipelines, tool-use infrastructure, evaluation frameworks.

| Skill | Weight | Why |
|-------|--------|-----|
| Agent architectures (ReAct, Plan-and-Execute) | 🔴 Critical | Core of most AI features |
| RAG pipeline design | 🔴 Critical | Most common AI pattern in production |
| Tool-use & function calling | 🔴 Critical | Agents need tools to act |
| Prompt engineering & optimization | 🟡 High | Quality depends on prompt design |
| Evaluation (LLM-as-judge, test suites) | 🟡 High | Non-deterministic outputs need rigorous testing |
| Vector databases & embeddings | 🟡 High | Memory, RAG, semantic search |
| MCP Protocol | 🟢 Medium | Emerging standard for tool integration |
| Fine-tuning basics | 🟢 Medium | When RAG isn't enough |

**Typical interview loop:**
1. **Phone screen** — Background, project deep-dive, system design light
2. **Take-home / coding** — Build a simple agent or RAG pipeline
3. **System design** — Design an AI customer support system, code generation agent, etc.
4. **Deep dive** — Agent architectures, evaluation, failure modes
5. **Behavioral** — "Tell me about a time an agent gave wrong answers"

### Forward Deployed Engineer (FDE)

**What they do:** Deploy AI solutions into customer environments — often on-premise, air-gapped, or restricted. Act as the bridge between product engineering and customer success.

| Skill | Weight | Why |
|-------|--------|-----|
| Problem decomposition | 🔴 Critical | FDEs get vague customer problems, must decompose into technical solutions |
| Full-stack engineering | 🔴 Critical | You own the entire integration end-to-end |
| Deployment in restricted environments | 🟡 High | On-prem, air-gapped, VPC-only, compliance |
| Customer empathy & communication | 🔴 Critical | You work directly with customers daily |
| AI/agent fundamentals | 🟡 High | You deploy AI systems, but don't need to train models |
| Infrastructure (K8s, Docker, networking) | 🔴 Critical | You set up the environment |
| Debugging in production | 🔴 Critical | Things WILL break in customer environments |
| Data pipeline integration | 🟡 High | Connect AI to customer data sources |

**Typical interview loop:**
1. **Phone screen** — Background, customer-facing experience
2. **Coding** — LeetCode medium-hard (polymorphism, system design coding)
3. **System design / Whiteboarding** — "Design a solution for a customer who wants to..."
4. **Problem decomposition** — Given a vague customer request, break it down
5. **Behavioral (heavy)** — Customer empathy, trade-off stories, "ship and iterate"

### AI Infrastructure Engineer

**What they do:** Build the infrastructure that serves AI models — inference clusters, model serving, GPU orchestration, LLMOps pipelines.

| Skill | Weight | Why |
|-------|--------|-----|
| Model serving (vLLM, TGI, Triton) | 🔴 Critical | Core of the role |
| GPU orchestration (K8s, SLURM) | 🔴 Critical | Managing expensive GPU resources |
| Quantization & optimization | 🟡 High | AWQ, GPTQ, FP8, speculative decoding |
| Networking (RDMA, InfiniBand) | 🟡 High | Multi-node inference |
| Storage (object, shared FS) | 🟡 High | Model weights, KV cache |
| CI/CD for ML | 🟡 High | Automating model deployments |
| Monitoring & observability | 🟡 High | GPU utilization, latency, throughput |

**Typical interview loop:**
1. **Phone screen** — Systems background, infrastructure experience
2. **Coding** — Concurrency, networking, systems programming
3. **System design** — "Design a model serving cluster for 1000 QPS"
4. **Deep infrastructure** — GPU architecture, CUDA basics, networking
5. **Behavioral** — On-call experience, incident response

---

## 2. The AI Interview Landscape (2025-2026)

### Key Trend: Decomposition Over Memorization

The #1 reason candidates fail AI interviews is **not** lack of knowledge — it's **jumping to implementation without decomposing the problem**.

```diff
- ❌ "Let's build an agent with LangGraph that uses RAG..."
+ ✅ "Let me first understand what the user needs. Are we optimizing for accuracy, latency, or cost? What's the data source? Do we need real-time or batch? What's the failure mode?"
```

### What Changed From 2024

| Old (2024) | New (2025-2026) |
|------------|-----------------|
| "Build a chatbot with RAG" | "Design an agent system that uses multiple tools, maintains context across sessions, and handles failures gracefully" |
| "Fine-tune a model" | "When would you fine-tune vs RAG vs prompt engineer? Design the decision system" |
| "Deploy an LLM endpoint" | "Design a multi-model inference cluster with cost-aware routing" |
| "Write a prompt" | "Design a prompt management system with versioning, testing, and monitoring" |
| Basic eval metrics | "Build an evaluation framework for non-deterministic agent outputs" |

### Company Archetypes

| Archetype | Example | Interview Style |
|-----------|---------|-----------------|
| **AI-Native Startup** | Sarvam AI, Cohere, Glean | Deep agent architecture, RAG design, hands-on coding |
| **Big Tech AI** | Google, Meta, Microsoft | LeetCode + system design + ML fundamentals |
| **Enterprise AI** | Salesforce, ServiceNow | System design with legacy integration, customer stories |
| **AI Infra** | Together AI, Fireworks, Replicate | Model serving, GPU orchestration, distributed systems |
| **Forward Deployed** | Palantir, Databricks, Anduril | Problem decomposition, customer empathy, full-stack |
| **Consulting / Agency** | McKinsey QuantumBlack, BCG X | Business impact, rapid prototyping, data pipelines |

---

## 3. Preparation Roadmap by Role

### AI Engineer — 6-Week Plan

```
Week 1-2: Foundations
  ├── Agent architectures (ReAct, Plan-and-Execute, Reflection)
  ├── RAG pipeline (indexing, retrieval, generation)
  ├── Tool-use patterns & function calling
  └── Prompt engineering & optimization

Week 3-4: Production Systems
  ├── Agent memory systems (episodic, semantic, working)
  ├── Multi-agent orchestration
  ├── Guardrails & safety (defense in depth)
  ├── Evaluation frameworks (LLM-as-judge, test suites)
  └── Observability (traces, metrics, debugging)

Week 5-6: System Design & Mock Interviews
  ├── AI system design patterns
  ├── Design: customer support agent, code gen, research assistant
  ├── Design: RAG at scale, multi-modal agent
  └── Mock interviews (focus on decomposition)
```

### Forward Deployed Engineer — 6-Week Plan

```
Week 1-2: Engineering Foundations
  ├── Full-stack coding (API design, database, auth)
  ├── Infrastructure (Docker, K8s, networking basics)
  ├── CI/CD pipelines
  └── LeetCode (medium, with system design hybrid)

Week 3-4: AI & Customer Context
  ├── Agent architectures (you deploy these, not build them from scratch)
  ├── RAG pipeline understanding
  ├── AI system design for enterprise
  ├── Deployment patterns (on-prem, air-gapped, hybrid cloud)
  └── Data pipeline integration (ETL, connectors, auth)

Week 5-6: Customer-Facing & Decomposition
  ├── Problem decomposition practice
  ├── "Tell me about a time" stories
  ├── Trade-off articulation (perfect vs shipped)
  ├── Customer empathy scenarios
  └── Mock interviews with vague requirements
```

### AI Infrastructure Engineer — 6-Week Plan

```
Week 1-2: Systems Foundations
  ├── Distributed systems (consensus, replication, sharding)
  ├── Networking (TCP, HTTP/2, gRPC, RDMA basics)
  ├── Storage (object stores, distributed FS)
  └── Concurrency & parallelism patterns

Week 3-4: Model Serving
  ├── Inference architectures (vLLM, TGI, Triton)
  ├── Quantization (AWQ, GPTQ, FP8, INT4)
  ├── Speculative decoding & KV cache optimization
  ├── GPU architecture basics (SM, memory hierarchy, CUDA)
  └── Load balancing & auto-scaling for inference

Week 5-6: LLMOps & Production
  ├── CI/CD for ML pipelines
  ├── Model registry & versioning
  ├── Monitoring (GPU util, latency, throughput, cost)
  ├── A/B testing for model changes
  └── Incident response for AI systems
```

---

## 4. Core Technical Pillars

### Pillar 1: Agent Architectures

Already well-covered in our [Agent Fundamentals](agents/01_AGENT_FUNDAMENTALS.md) and [Agent Production Architecture](agents/04_AGENT_PRODUCTION_ARCHITECTURE.md). Key things to master:

- **ReAct** — The foundation. Understand the Thought-Action-Observation loop deeply.
- **Plan-and-Execute** — When to pre-plan vs when to act incrementally.
- **Orchestrator-Worker** — Delegation, parallel execution, conflict resolution.
- **Reflection** — Critic-refiner loops, quality iteration.
- **When to use which** — This is the Staff-level differentiator.

### Pillar 2: RAG (Retrieval-Augmented Generation)

Well-covered in our [RAG Fundamentals](rag/01_RAG_FUNDAMENTALS.md) and related files. Key additions for interviews:

- **Hybrid search** — Combining semantic + keyword search for better retrieval.
- **Agentic RAG** — Using RAG as a tool within an agent loop (the agent decides when to query).
- **Self-RAG** — The agent reflects on whether retrieved docs are relevant before generating.
- **Corrective RAG** — If retrieval fails, try a different strategy or fall back.
- **Multi-hop RAG** — Chain multiple retrieval steps (e.g., "Find the author of the paper that...")
- **GraphRAG** — Using knowledge graphs for structured retrieval.

### Pillar 3: Memory Systems

Covered in our [Memory Guide — see separate file](agents/15_AGENT_MEMORY_SYSTEMS.md). Essential for interviews:

- **Short-term** — Sliding window, summary compression, token budgeting
- **Working** — Current task context, goals, progress tracking
- **Long-term** — Vector stores, key-value stores, hybrid approaches
- **Episodic** — Past resolutions learned from experience
- **Procedural** — Learned tool-use patterns and workflows

### Pillar 4: Evaluation & Observability

Some coverage in [Agent Observability](agents/07_AGENT_OBSERVABILITY.md) and [Agent Interview Questions](agents/02_AGENT_INTERVIEW_QUESTIONS.md). Key interview topics:

- **Deterministic tests** — Tool call order, parameter validation, output format checks
- **Semantic tests** — LLM-as-judge with rubrics (accuracy, groundedness, safety)
- **Statistical testing** — Run each test N times, track pass rate and variance
- **Trajectory evaluation** — Not just final answer, but the path taken
- **Production metrics** — Success rate, escalation rate, cost per task, user satisfaction
- **Debugging workflow** — "How do you investigate an agent that gave a wrong answer?"

### Pillar 5: Safety & Guardrails

Covered in existing content. Key interview themes:

- **Defense in depth** — Input validation → Auth → Rate limiting → Tool validation → Output filtering
- **Prompt injection prevention** — Input sanitization, parameterized tool calls
- **PII detection & redaction** — Both input and output
- **Human-in-the-loop** — When to escalate, approval workflows
- **Failure modes** — Tool loops, context swamping, hallucination cascades

### Pillar 6: Infrastructure & Deployment

Key interview topics (especially for FDE and Infra roles):

- **Model serving** — vLLM, TGI, Triton Inference Server
- **GPU orchestration** — K8s with GPU scheduling, node pools, spot instances
- **Quantization** — AWQ, GPTQ, FP8 — when to use each
- **Speculative decoding** — Draft model + target model for faster inference
- **KV cache management** — PagedAttention, prefix caching, continuous batching
- **Prompt caching** — Reusing common prefixes across requests
- **CI/CD for AI** — Model validation, A/B testing, canary deployments, rollback

---

## 5. System Design for AI Systems

### The AI System Design Framework

When designing AI systems in interviews, use this structured approach:

```diff
Step 1: Clarify requirements
  ├── What's the user goal? (accuracy, latency, cost?)
  ├── What data is available? (structured, unstructured, real-time?)
  ├── Scale? (100 QPS? 10K QPS? Batch?)
  ├── Constraints? (on-premise? air-gapped? compliance?)
  └── Failure tolerance? (wrong answer vs no answer?)

Step 2: Design the AI pipeline
  ├── Model selection (capabilities, cost, latency)
  ├── RAG or fine-tuning or prompt engineering?
  ├── Agent architecture (which pattern?)
  ├── Memory system (short-term, long-term, episodic)
  └── Tool integration (MCP, REST, etc.)

Step 3: Design the infrastructure
  ├── Model serving (batch, streaming, real-time)
  ├── Data pipeline (ETL, indexing, updates)
  ├── State management (session persistence, checkpointing)
  ├── Scaling (horizontal, vertical, GPU)
  └── Cost optimization (caching, model routing, batching)

Step 4: Safety & Observability
  ├── Guardrails (input, output, tool call)
  ├── Evaluation (test suites, monitoring)
  ├── Debugging (traceability, replay)
  └── Human-in-the-loop (escalation, approval)
```

### Common AI System Design Questions

| Question | Key Considerations |
|----------|-------------------|
| **Design a customer support agent** | Multi-intent classification, KB RAG, escalation, learning from feedback |
| **Design a code generation assistant** | Context management (large codebases), tool integration (git, lint), evaluation |
| **Design a research assistant agent** | Multi-step research, source attribution, conflicting information handling |
| **Design an enterprise document Q&A** | Multi-tenant RAG, document versioning, access control, citation accuracy |
| **Design a model inference serving platform** | Multi-model, GPU scheduling, autoscaling, cost allocation, monitoring |
| **Design an on-premise AI deployment** | Air-gapped, no external APIs, local model, data sovereignty |
| **Design an agent evaluation platform** | Test case management, automated scoring, regression tracking, human review |

---

## 6. Forward Deploy Engineer — Special Preparation

### What Makes FDE Different

FDE interviews are **NOT** standard SWE interviews. The emphasis is:

1. **Problem Decomposition (> Coding)**
   - You'll get vague, ambiguous customer problems
   - The interviewer wants to see you **break it down**, not code it
   - Practice: Take vague requirements → write down assumptions → clarify → propose solution

2. **Customer Empathy (> Technical Perfection)**
   - "The customer wants to reduce customer service costs by 50% in 3 months"
   - You need to balance what's possible vs what's perfect
   - Stories of "I shipped an imperfect solution that delivered value" > "I built a perfect system"

3. **Deployment Experience (> Novel Research)**
   - You deploy existing technology into customer environments
   - Experience with on-prem, air-gapped, VPC-restricted, compliance-heavy deployments
   - Understanding of enterprise security, networking, auth (SSO, SAML, OIDC)

4. **Rapid Iteration (> Deep Optimization)**
   - FDEs ship fast, learn, and iterate
   - "How would you deploy a solution in 2 weeks vs 2 months?"

### Common FDE Interview Questions

**Problem Decomposition:**
```
"A large retail customer wants to use AI to improve their customer support.
They have 500 support agents, a knowledge base of 50K articles, and data
in Salesforce, Zendesk, and a legacy on-premise database. They want to
reduce response time by 50% in 6 months. Where do you start?"
```

**How to approach:**
1. **Understand the goal:** 50% response time reduction — what metric?
2. **Map the current state:** Data sources, systems, access patterns
3. **Identify constraints:** On-premise data? Compliance? Budget?
4. **Propose phased approach:**
   - Phase 1 (2 weeks): RAG Q&A on knowledge base (quick win)
   - Phase 2 (1 month): Agent-assisted responses for agents
   - Phase 3 (3 months): Direct customer-facing agent with escalation
5. **Call out risks:** Data quality, latency requirements, user adoption

**Technical Architecture (Whiteboarding):**
```
"Design a system that takes customer data from their on-premise SQL database,
indexes it for RAG, and serves it through an agent. The customer cannot use
external APIs (air-gapped)."
```

**Key decisions:**
- Local LLM (Llama, Mistral) vs on-premise API (vLLM on customer infra)
- Containerized deployment (Docker + K8s on customer cluster)
- Data pipeline: Change Data Capture (CDC) or batch ETL?
- Auth: Integrate with customer SSO (SAML/OIDC)
- Monitoring: Prometheus + Grafana on customer infra

**Behavioral Questions (very heavy for FDE):**
```
"Tell me about a time a customer was unhappy with your solution."
→ The answer should show: empathy → action → outcome

"Tell me about a time you had to balance customer needs with engineering reality."
→ Trade-off articulation, communication, shipped value

"Tell me about a time you deployed something that broke in production."
→ Incident response, learning, improvement
```

### The FDE Story Framework

For every behavioral story, structure it as:

```
Context: Customer with problem X
Challenge: Constraints Y (on-premise, legacy data, timeline)
Action: What I built/deployed
Trade-off: Why I chose this approach over the perfect solution
Impact: Measurable outcome (50% faster, 30% cost reduction)
Lesson: What I'd do differently
```

---

## 7. The Behavioral Interview — AI Edition

AI roles have unique behavioral questions that test your understanding of non-deterministic systems.

### Common AI Behavioral Questions

| Question | What They're Testing |
|----------|---------------------|
| "Tell me about an AI system you built that gave wrong answers" | Understanding of failure modes, debugging approach |
| "How do you know your agent is working correctly?" | Evaluation philosophy, testing rigor |
| "Tell me about a time you had to choose between accuracy and latency" | Trade-off reasoning, cost awareness |
| "How do you handle hallucination in production?" | Practical mitigation strategies |
| "Tell me about a RAG system that wasn't retrieving well" | Debugging RAG, iteration on retrieval strategy |
| "How do you evaluate non-deterministic outputs?" | Evaluation framework, statistical testing |
| "Tell me about a time you deployed an AI feature that users didn't trust" | UX of AI, transparency, user education |

### Your Story Bank

Prepare stories covering these scenarios:

```
1. A time an agent/tool failed in production → how you debugged and fixed
2. A time you chose a simpler solution over a complex AI solution
3. A time you evaluated an AI system and found it wasn't good enough
4. A time you had to deploy under constraints (time, data, compute)
5. A time you had to explain AI limitations to non-technical stakeholders
6. A time you improved an AI system's quality by 2x+
7. A time you caught a subtle bug in an AI pipeline (data leakage, bias, drift)
```

---

## 8. Study Resources & Practice Plan

### Daily Practice (30 min)

```
Weekdays:
  - 10 min: Read one AI paper abstract or blog post
  - 10 min: Practice one system design scenario (decomposition only)
  - 10 min: Practice one behavioral story aloud

Weekends:
  - 1 hour: Deep study of one missing topic
  - 1 hour: Mock interview (find a partner)
  - 30 min: Review and update your story bank
```

### Recommended Resources

| Topic | Resource |
|-------|----------|
| **Agent architectures** | Anthropic's agent patterns guide, LangGraph docs |
| **RAG patterns** | LlamaIndex docs, "Advanced RAG" by Pinecone |
| **System design** | Alex Xu's System Design Interview, our [CS Architecture notes](../cs-interview/software-architecture/INTERVIEW_QUESTIONS.md) |
| **FDE preparation** | Sundeep Teki's FDE Guide, Palantir engineering blog |
| **Model serving** | vLLM docs, TGI docs, NVIDIA Triton docs |
| **Evaluation** | LangSmith docs, "LLM-as-Judge" papers |
| **Behavioral** | "Cracking the PM Interview" (customer stories), your own experience |

### The Week Before Interviews

```
Day 1-2: Review all agent architectures. Practice drawing them from memory.
Day 3-4: Practice system design whiteboarding (voice-record yourself).
Day 5-6: Mock interviews with feedback.
Day 7: Rest. Review your story bank. Prepare questions to ask interviewers.
```

### Questions to Ask Interviewers

```
To AI Engineer team:
  "How do you evaluate agent quality in production?"
  "What's your approach to handling hallucination?"
  "How do you choose between open-source and proprietary models?"

To FDE team:
  "What's the most challenging deployment environment you've worked with?"
  "How do you balance customer requests with product roadmap?"
  "What does a typical week look like for an FDE?"

To AI Infra team:
  "What's your inference stack and why did you choose it?"
  "How do you manage GPU utilization across multiple models?"
  "What's your incident response process for model serving issues?"
```

---

## Quick Reference: Role Comparison

| Dimension | AI Engineer | FDE | AI Infra |
|-----------|-------------|-----|----------|
| **Primary focus** | Building AI features | Deploying into customer environments | Serving infrastructure |
| **Coding depth** | Agent logic, RAG, tools | Full-stack, integration | Systems, networking |
| **AI depth** | Deep (architectures, prompting) | Medium (deployment patterns) | Medium (model serving) |
| **Customer exposure** | Low-Medium | Very High (daily) | Low |
| **Infrastructure** | Medium (API design) | High (on-prem, K8s) | Very High (GPU clusters) |
| **Evaluation focus** | Agent quality | Customer impact | Latency, throughput |
| **Key interview risk** | Over-engineering | Not decomposing enough | Missing cost-awareness |

---

> **Remember:** The interview is a conversation, not an interrogation. Show your thinking process, ask clarifying questions, and demonstrate that you care about building systems that work for real users — not just technically impressive ones.
