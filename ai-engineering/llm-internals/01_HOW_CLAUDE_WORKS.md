# 🤖 How Claude Works — Model Architecture & Capabilities

> **A deep-dive into Claude's architecture, training, context window mechanics, safety systems, and model capabilities.**

---

## 1. WHAT IS CLAUDE?

**Claude** is a family of large language models developed by Anthropic. The name comes from Claude Shannon, the father of information theory.

### Model Generations

| Generation | Models | Key Features |
|-----------|--------|-------------|
| **Claude 3** (2024) | Haiku, Sonnet, Opus | Multimodal (vision), 200K context, tool use |
| **Claude 3.5** (2024-2025) | Haiku, Sonnet | Faster, better coding, computer use |
| **Claude 4** (2025-2026) | Sonnet, Opus | Extended thinking, deeper reasoning, agentic |

---

## 2. MODEL ARCHITECTURE

Claude uses a **Transformer** architecture with several key innovations:

```ascii
┌──────────────────────────────────────────────────────────────┐
│                    CLAUDE MODEL ARCHITECTURE                   │
│                                                               │
│  INPUT: Token Embeddings                                      │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ [1456] [892] [331] [1203] [445] [678] ... [901]      │    │
│  └──────────────────────────────────────────────────────┘    │
│                          │                                    │
│                          ▼                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              POSITIONAL ENCODING                       │    │
│  │  (Rotary Position Embeddings — RoPE)                  │    │
│  │  Encodes token position information                    │    │
│  └──────────────────────────────────────────────────────┘    │
│                          │                                    │
│                          ▼                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │           TRANSFORMER LAYERS (× N)                    │    │
│  │                                                       │    │
│  │  ┌────────────────────────────────────────────┐      │    │
│  │  │  Layer N:                                  │      │    │
│  │  │  ┌──────────────────────────────────────┐  │      │    │
│  │  │  │  Multi-Head Attention                 │  │      │    │
│  │  │  │  • Each head attends to different     │  │      │    │
│  │  │  │    parts of the input                 │  │      │    │
│  │  │  │  • Q, K, V projections                │  │      │    │
│  │  │  │  • Scaled dot-product attention       │  │      │    │
│  │  │  └──────────────────────────────────────┘  │      │    │
│  │  │                    │                        │      │    │
│  │  │  ┌──────────────────────────────────────┐  │      │    │
│  │  │  │  Feed-Forward Network                  │  │      │    │
│  │  │  │  • MLP with SwiGLU activation          │  │      │    │
│  │  │  │  • Expands and contracts dimensions    │  │      │    │
│  │  │  └──────────────────────────────────────┘  │      │    │
│  │  │                    │                        │      │    │
│  │  │  ┌──────────────────────────────────────┐  │      │    │
│  │  │  │  Residual Connection + LayerNorm      │  │      │    │
│  │  │  ├──────────────────────────────────────┤  │      │    │
│  │  │  │  Output → Next Layer                  │  │      │    │
│  │  │  └──────────────────────────────────────┘  │      │    │
│  │  └────────────────────────────────────────────┘      │    │
│  └──────────────────────────────────────────────────────┘    │
│                          │                                    │
│                          ▼                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              OUTPUT PROJECTION                        │    │
│  │  (Unembedding → Token probabilities)                  │    │
│  └──────────────────────────────────────────────────────┘    │
│                          │                                    │
│                          ▼                                    │
│  OUTPUT: "def fibonacci(n):\\n    if n <= 1:\\n..."          │
└──────────────────────────────────────────────────────────────┘
```

### Key Architectural Features

| Feature | What It Does | Why It Matters |
|---------|-------------|----------------|
| **Sparse Attention** | Attends to relevant tokens, not all | Handles 200K+ context efficiently |
| **SwiGLU Activation** | Gated linear unit variant | Better gradient flow, faster training |
| **Grouped Query Attention** | Shared KV heads | Reduces memory, faster inference |
| **RoPE** | Rotary Position Embeddings | Better extrapolation to longer sequences |
| **Deep Normalization** | Pre-norm with LayerNorm | Stable training at scale |

---

## 3. TRAINING PROCESS

Claude is trained in multiple phases:

```ascii
PHASE 1: PRE-TRAINING
┌─────────────────────────────────────────────────────────────────┐
│  Data: Large corpus of internet text, books, code (~T tokens)   │
│  Objective: Next-token prediction                               │
│  Result: Base model — knows language patterns, facts, reasoning │
│  "The capital of France is ___" → "Paris"                       │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
PHASE 2: SELF-SUPERVISED LEARNING
┌─────────────────────────────────────────────────────────────────┐
│  Constitution: Set of rules and values                           │
│  RLHF: Reinforcement Learning from Human Feedback                │
│  • Human raters rank model outputs                               │
│  • Reward model learns preferences                               │
│  • Policy optimization (PPO)                                     │
│  Result: Helpful, harmless, honest assistant                     │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
PHASE 3: POST-TRAINING
┌─────────────────────────────────────────────────────────────────┐
│  Tool use fine-tuning: Learn to call functions                  │
│  Code specialization: Enhanced coding ability                   │
│  Safety fine-tuning: Refuse harmful requests                    │
│  Context window extension: 200K token handling                  │
│  Result: Production-ready Claude model                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. CONTEXT WINDOW

The **context window** is the maximum amount of text the model can "see" at once.

```ascii
┌────────────────────────────────────────────────────────────────────┐
│                       CONTEXT WINDOW (200K tokens)                   │
│                                                                     │
│  ┌──────────────┬──────────────┬──────────────┬────────────────┐   │
│  │  System      │   History    │  New Input   │  Reserved      │   │
│  │  Prompt      │  (Messages)  │  (Question)  │  (Generation)  │   │
│  │              │              │              │                │   │
│  │  ~2,000      │  ~50,000     │  ~5,000      │  ~8,000        │   │
│  │  tokens      │  tokens      │  tokens      │  tokens        │   │
│  └──────────────┴──────────────┴──────────────┴────────────────┘   │
│                                                                     │
│  200K tokens ≈ 150,000 words ≈ ~500 pages of text                  │
└────────────────────────────────────────────────────────────────────┘
```

### What Fits in 200K Tokens?

| Content Type | Approximate Amount |
|-------------|-------------------|
| **Code** | Full codebase of a small project (50+ files) |
| **Books** | ~500 pages (entire "The Great Gatsby") |
| **Documents** | ~200-page technical report with diagrams |
| **Conversations** | ~8 hours of dialogue |
| **Research papers** | 50+ papers with full text |

---

## 5. INFERENCE (HOW CLAUDE GENERATES RESPONSES)

Claude generates responses **auto-regressively** — one token at a time.

```ascii
Step 1:  "def"                    ← Token 1
Step 2:  "def fibonacci"          ← Token 2
Step 3:  "def fibonacci(n)"       ← Token 3
Step 4:  "def fibonacci(n):\n"    ← Token 4
Step 5:  "def fibonacci(n):\n    " ← Token 5
...
Step 50: "def fibonacci(n):\n    if n <= 1:\n        return n"
```

### Sampling Parameters

| Parameter | What It Controls | Low Value | High Value | Default |
|-----------|-----------------|-----------|------------|---------|
| **Temperature** | Randomness | 0.0 (deterministic) | 1.0 (creative) | 0.7 |
| **top_p** | Nucleus sampling | 0.1 (focused) | 1.0 (diverse) | 0.9 |
| **top_k** | Top-K sampling | 10 (focused) | 100 (diverse) | 50 |
| **max_tokens** | Max output length | 100 (short) | 8192 (long) | 4096 |
| **stop_sequences** | Stop generation | — | — | [] |

### How Sampling Works

```ascii
At each step, the model calculates probabilities for EVERY token:

Token           Probability
──────────────────────────
"def"           0.45       ← Most likely
"function"      0.20
"import"        0.15
"# "            0.08
"from"          0.05
...others...    0.07

Sampling (temperature=0.7):
  1. Scale logits by temperature: logits / 0.7
  2. Apply softmax: get new probabilities
  3. Sample from distribution (higher temp = more uniform)
  4. Result: might pick "def" (likely) or "function" (less likely)

Greedy (temperature=0.0):
  1. Always pick token with highest probability
  2. Result: always "def" (deterministic)
```

---

## 6. SAFETY & CONSTITUTION

Claude uses a **Constitutional AI** approach to safety.

| Safety Layer | What It Does |
|-------------|-------------|
| **Constitution** | Set of rules defining helpful, harmless, honest behavior |
| **RLHF** | Reinforcement Learning from Human Feedback |
| **Red-teaming** | Adversarial testing for vulnerabilities |
| **Refusal training** | Learning to decline harmful requests |
| **Input/output guardrails** | Filtering at API level |

### The Constitution Covers

- **Helpfulness:** Be useful, accurate, and thorough
- **Harmlessness:** Don't assist with illegal, dangerous, or unethical tasks
- **Honesty:** Acknowledge uncertainty, don't fabricate information
- **Privacy:** Don't reveal personal information
- **Fairness:** Treat all users equally, avoid bias

---

## 7. CAPABILITIES & LIMITATIONS

### What Claude Excels At

| Capability | Description |
|-----------|-------------|
| **Coding** | Full-stack development, debugging, code review |
| **Reasoning** | Multi-step logic, math, problem-solving |
| **Analysis** | Document analysis, data interpretation, research |
| **Writing** | Prose, technical docs, creative writing |
| **Tool use** | Function calling, MCP, agentic behavior |
| **Vision** | Image analysis, diagram understanding, OCR |

### Known Limitations

| Limitation | Why | Mitigation |
|-----------|-----|------------|
| **Hallucination** | Model generates plausible but wrong facts | RAG, citations, grounded generation |
| **Outdated knowledge** | Training data cutoff | Web search, RAG for fresh data |
| **Context forgetting** | Attends less to middle of context | Restructure prompts, important info at start/end |
| **Token limits** | Hard ceiling on input+output | Chunking, summarization, pagination |
| **No persistent memory** | Each session starts fresh | External memory systems, vector stores |
| **No real-time awareness** | Doesn't know current time/events | Explicit time context, search tools |

---

## 8. QUICK REFERENCE

```ascii
                    CLAUDE AT A GLANCE
                    ─────────────────
                    
  Architecture:    Transformer (decoder-only)
  Training:        Pre-training → Constitutional AI → RLHF
  Context:         200K tokens (Claude 3+)
  Output:          Auto-regressive, token-by-token
  Pricing:         Per-token (input cheaper than output)
  Modalities:      Text + Code + Vision (images)
  Tool use:        Native function calling + MCP
  Safety:          Constitutional AI + RLHF + red-teaming
```

---

> **Next:** [Claude Code/Editor — Interaction Flow](02_CLAUDE_CODE_INTERACTION.md) → How Claude Code interacts with models and the file system
