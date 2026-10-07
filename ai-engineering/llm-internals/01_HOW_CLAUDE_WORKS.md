# 🤖 How Claude Works — Model, Training, Context & Inference

> **What is publicly known about Claude, the general transformer mechanics every frontier LLM shares, and how inference, sampling and the context window behave in practice.**

!!! warning "Read this first: what is public and what isn't"
    Anthropic does **not** publish Claude's architecture: parameter count, layer count, attention variant, whether it uses mixture-of-experts, positional-encoding scheme, or tokenizer vocabulary are all undisclosed. Anything below labelled **general LLM background** describes how modern decoder-only transformers typically work (open models such as Llama, Mistral, Qwen and the research literature). It is the right mental model for an interview, but don't state it as "how Claude is built".
    What *is* documented: the models and their limits ([models overview](https://platform.claude.com/docs/en/about-claude/models/overview)), the API behaviour, and Anthropic's published training and safety research (Constitutional AI, Claude's constitution, the Responsible Scaling Policy).

**30-second answer:** Claude is Anthropic's family of large language models. Like every frontier LLM it is trained first to predict the next token on a large corpus, then post-trained (supervised fine-tuning plus reinforcement learning from human and AI feedback, guided by a written constitution) to be helpful, honest and harmless. At inference time it reads the whole prompt in one parallel pass (prefill), then generates one token at a time (decode), reusing a KV cache. Everything it "knows" about your conversation lives in the context window; it has no memory between API calls.

---

## 1. WHAT IS CLAUDE?

**Claude** is a family of large language models developed by Anthropic, sold through the Claude API, Amazon Bedrock, Google Cloud Vertex AI, Microsoft Foundry, and Anthropic's own apps (claude.ai, Claude Code).

### Model Generations

| Generation | Models | What it introduced |
|-----------|--------|-------------------|
| **Claude 3** (Mar 2024) | Haiku, Sonnet, Opus | Vision input, 200K context, tiered sizes |
| **Claude 3.5** (Jun–Oct 2024) | Sonnet, Haiku | Big coding jump; computer use (beta) with the Oct 2024 Sonnet |
| **Claude 3.7 Sonnet** (Feb 2025) | Sonnet | First "hybrid reasoning" model: optional extended thinking |
| **Claude 4 / 4.x** (May 2025 onward) | Opus 4 → 4.8, Sonnet 4 → 4.6, Haiku 4.5 | Agentic coding focus; `effort` control (Opus 4.5), adaptive thinking (4.6); 1M context on the larger models |
| **Claude 5 / 5.x** (2026) | Opus 5 / 5.5, Sonnet 5 / 5.5, Fable 5 / 5.1 | Current generation (see below) |

**Current lineup (from the models overview page, checked 7 Oct 2026; this rots, so re-check):**

| Model | Positioning | Context | Max output |
|-------|-------------|---------|-----------|
| Claude Fable 5.1 | Most capable; demanding reasoning, long-horizon agents | 1M | 128K |
| Claude Opus 5.5 | Anthropic's recommended default for most workloads | 1M | 128K |
| Claude Sonnet 5.5 | Speed/intelligence balance | 1M | 128K |
| Claude Haiku 4.5 | Fastest, cheapest | 200K | 64K |

Interview-safe framing: *"There's a capability/latency/cost ladder (Haiku → Sonnet → Opus → Fable). I pick the cheapest tier that passes my evals, and re-run the evals when a new model ships."*

---

## 2. MODEL ARCHITECTURE (GENERAL LLM BACKGROUND)

Claude is generally understood to be a **decoder-only transformer** language model; Anthropic's interpretability research is done on transformer models, but the production architecture is not disclosed. The diagram is the standard modern design.

```ascii
┌──────────────────────────────────────────────────────────────┐
│         TYPICAL DECODER-ONLY TRANSFORMER (general)           │
│                                                              │
│  Token IDs  [1456] [892] [331] ...                           │
│        │                                                     │
│        ▼                                                     │
│  Embedding lookup: ID → vector (d_model dims)                │
│        │                                                     │
│        ▼                                                     │
│  ┌────────────────────── × N layers ──────────────────────┐  │
│  │  x = x + Attention(Norm(x))     ← causal self-attention│  │
│  │        • Q, K, V projections, many heads               │  │
│  │        • softmax(QKᵀ/√d_k + causal mask) · V           │  │
│  │        • position injected via RoPE (common choice)    │  │
│  │  x = x + FFN(Norm(x))           ← per-token MLP        │  │
│  │        • e.g. SwiGLU; or a mixture-of-experts layer    │  │
│  └────────────────────────────────────────────────────────┘  │
│        │                                                     │
│        ▼                                                     │
│  Final norm → unembedding → logits over the vocabulary       │
│        │                                                     │
│        ▼                                                     │
│  Sampling picks ONE next token; repeat                       │
└──────────────────────────────────────────────────────────────┘
```

### Common Design Choices in Modern LLMs

| Technique | What it does | Why it's used |
|---------|-------------|----------------|
| **Causal self-attention** | Each token attends to all earlier tokens | Lets the model use the full prefix; cost is O(n²) in sequence length for prefill |
| **Grouped-query / multi-query attention (GQA/MQA)** | Several query heads share one K/V head | Shrinks the KV cache, so long contexts and big batches fit in GPU memory |
| **RoPE** | Rotates Q/K by position-dependent angles | Relative-position awareness; can be stretched (with tricks) to longer contexts |
| **SwiGLU FFN** | Gated MLP | Better quality per FLOP than ReLU/GELU MLPs |
| **Mixture of experts (MoE)** | Router sends each token to a few expert FFNs | More parameters without proportional compute per token |
| **Pre-norm (LayerNorm/RMSNorm) + residuals** | Normalise the input to each sub-layer | Stable training of very deep stacks |

None of these is confirmed for Claude. If asked "how does Claude handle 1M tokens?", the honest answer is: *"Not disclosed; the usual ingredients are KV-cache-efficient attention (GQA), position schemes that extend to long sequences, long-context training data, and serving tricks like prompt caching."* Don't claim Claude uses "sparse attention".

---

## 3. TRAINING PROCESS

```ascii
PHASE 1: PRE-TRAINING (self-supervised)
┌─────────────────────────────────────────────────────────────────┐
│  Data: large corpus of public web text, licensed data, code...  │
│  Objective: next-token prediction (cross-entropy loss)          │
│  Result: base model; knows language, facts, code patterns,     │
│          but isn't an assistant yet                             │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
PHASE 2: POST-TRAINING (making it an assistant)
┌─────────────────────────────────────────────────────────────────┐
│  • Supervised fine-tuning on demonstrations                     │
│  • RLHF: humans compare outputs → reward/preference model →     │
│    RL optimises the policy against it                           │
│  • Constitutional AI / RLAIF: the model critiques and revises   │
│    its own outputs against written principles, and AI-generated│
│    preference labels replace many human labels                  │
│  • Character / values training from Claude's constitution       │
│  • Capability training: tool use, coding, agentic tasks         │
│    (RL on verifiable tasks is common industry practice;         │
│    Anthropic doesn't publish its exact recipe)                  │
│  Result: the deployed Claude model                              │
└─────────────────────────────────────────────────────────────────┘
```

Facts worth citing precisely:

- **Constitutional AI** (Anthropic paper, Dec 2022): a supervised phase where the model critiques and revises its own responses using a list of principles, then an RL phase using **AI feedback** (RLAIF) instead of human harmlessness labels. It is *not* "self-supervised learning"; pre-training is the self-supervised phase.
- **Claude's constitution** (published 21 Jan 2026, CC0): a long natural-language document explaining the values Anthropic wants Claude to have and *why*, rather than a list of rules. It orders priorities as broadly safe, broadly ethical, compliant with Anthropic's guidelines, then genuinely helpful, and lists a small set of hard constraints (for example, no serious uplift for weapons of mass destruction). Source: [anthropic.com/news/claude-new-constitution](https://www.anthropic.com/news/claude-new-constitution).
- "Context window extension" as a named post-training phase is not something Anthropic documents; long-context ability comes from training and architecture choices that aren't public.

---

## 4. CONTEXT WINDOW

The **context window** is everything the model can attend to in one request: system prompt, tool definitions, the whole message history, *and* the tokens it generates in its response.

```ascii
┌──────────────────────────────────────────────────────────────────┐
│                 CONTEXT WINDOW (one API request)                 │
│  ┌──────────┬────────────┬───────────┬──────────────┬──────────┐ │
│  │ System + │  Message   │ Tool      │ New user     │ Output   │ │
│  │ tool defs│  history   │ results   │ message      │ (≤ max_  │ │
│  │          │            │ (files…)  │              │  tokens) │ │
│  └──────────┴────────────┴───────────┴──────────────┴──────────┘ │
│   input tokens ─────────────────────────────────────▶ output     │
│   input + max_tokens must fit in the window                      │
└──────────────────────────────────────────────────────────────────┘
```

| Fact | Detail |
|------|--------|
| Size | 1M tokens on current Opus/Sonnet/Fable models, 200K on Haiku 4.5 (Oct 2026) |
| Rough size | 200K tokens ≈ 150K English words; 1M ≈ 555K words on the tokenizer introduced with Opus 4.7 (about 750K words on older tokenizers) |
| Stateless | The API keeps no conversation; the client resends the history every call |
| Thinking | Thinking tokens count toward the window and `max_tokens`. Previous turns' thinking blocks are **kept** by default on Opus 4.5+/Sonnet 4.6+/Fable, and **stripped** automatically on earlier models and Haiku ([context-windows docs](https://platform.claude.com/docs/en/build-with-claude/context-windows)) |
| Caching | Cached prefixes still occupy the window; caching changes the price, not the count |
| Overflow | Input alone over the limit → 400 "prompt is too long". On Claude 4.5+ models, input + `max_tokens` over the limit is accepted and generation stops with `stop_reason: "model_context_window_exceeded"`. Agents stay under the limit with compaction (summarise old turns), context editing (clear old tool results) or sub-agents |

**Bigger isn't free.** Every token in the window is re-processed (or read from cache) on every call, so cost and latency scale with context size. Anthropic's docs say it plainly: as token count grows, accuracy and recall degrade ("context rot"), and models recall facts in the middle of very long prompts less reliably than at the start or end ("lost in the middle", Liu et al. 2023). Curate what goes in; don't treat the window as free storage.

---

## 5. INFERENCE (HOW A RESPONSE IS GENERATED)

Generation has two phases with very different performance profiles (general LLM background, true of every transformer server):

```ascii
PREFILL (once per request)                DECODE (once per output token)
┌──────────────────────────────┐          ┌──────────────────────────────┐
│ All input tokens processed   │          │ One new token per forward    │
│ in parallel; K/V for every   │ ───────▶ │ pass; attends to cached K/V; │
│ position written to KV cache │          │ appends its own K/V          │
│ Compute-bound (big matmuls)  │          │ Memory-bandwidth-bound       │
│ Drives time-to-first-token   │          │ Drives tokens/second         │
└──────────────────────────────┘          └──────────────────────────────┘
```

- **KV cache:** keys and values for every previous token are stored so decode doesn't recompute them. It grows linearly with context length and is the main GPU-memory cost of long contexts. GQA/MQA exist to shrink it.
- **Why output tokens cost more:** prefill processes thousands of tokens per forward pass; decode produces one token per pass per sequence and is limited by reading weights and KV cache from memory. That's why Anthropic prices output at 5× input across the current lineup.
- **Prompt caching** (API feature) reuses the server-side state for an identical prompt prefix, cutting prefill cost and time-to-first-token on repeated prefixes. See [Tokenization & Cost](04_TOKENIZATION_AND_COST.md#4-prompt-caching).
- **Autoregressive:** each generated token is appended to the input and the model runs again. A response of 500 tokens is 500 sequential decode steps; that's the floor on latency.

### Sampling Parameters (Claude Messages API)

| Parameter | What it controls | Notes |
|-----------|-----------------|-------|
| `max_tokens` | Hard cap on generated tokens | **Required.** Hitting it gives `stop_reason: "max_tokens"` (truncated output) |
| `temperature` | Randomness | Range 0–1, **default 1.0**. Now marked **deprecated** in the API reference: models released after Opus 4.6 accept only 1.0 |
| `top_p` / `top_k` | Truncate the distribution before sampling | Advanced knobs; on older models adjust temperature *or* top_p, not both |
| `stop_sequences` | Custom strings that end generation | Gives `stop_reason: "stop_sequence"` |
| `output_config.effort` | How much thinking/tokens the model spends (`low` … `max`) | The main quality/cost knob on current models |

!!! note "Version-sensitive"
    Models released after Opus 4.6 (Opus 4.7+, Sonnet 5.x, Fable 5.x) **reject** non-default `temperature`/`top_p`/`top_k` with a 400 error; you steer them with `effort` and prompting instead. Even on older models, `temperature: 0` is *not* guaranteed to be deterministic (floating-point and batching effects).

### How Sampling Works

```ascii
At each step the model outputs a logit z_i for EVERY vocabulary token.

  token        logit   p (T=1.0)
  "def"         2.1      0.45
  "function"    1.3      0.20
  "import"      1.0      0.15
  ...

Temperature T:  p_i = softmax(z_i / T)
   T < 1 sharpens the distribution (more likely tokens win more often)
   T → 0 approaches greedy decoding (always the argmax)
   T = 1 samples from the model's raw distribution
top_k:  keep only the k highest-probability tokens, renormalise
top_p:  keep the smallest set whose cumulative probability ≥ p, renormalise
Then draw one token from what's left.
```

### Thinking (reasoning tokens)

Current models can "think" before answering: they generate reasoning tokens in `thinking` content blocks, then the visible answer. With **adaptive thinking** the model decides how much to think, steered by `effort`. Thinking tokens are billed as output tokens. On current models the raw chain of thought is not returned: by default the thinking text is omitted, and `display: "summarized"` returns a summary. ([Thinking docs](https://platform.claude.com/docs/en/build-with-claude/thinking))

---

## 6. SAFETY & CONSTITUTION

| Layer | What it is |
|-------|-----------|
| **Training-time values** | Constitutional AI, RLHF, and Claude's constitution shape default behaviour |
| **Usage Policy** | What customers may and may not build; enforced at the account level |
| **Runtime safeguards** | Classifiers can stop a response; the API then returns `stop_reason: "refusal"` (with a `stop_details.category` on recent models). Handle it like any other stop reason |
| **Responsible Scaling Policy (RSP)** | Anthropic's framework of AI Safety Levels (ASL): capability thresholds that trigger stronger security and deployment safeguards |
| **Red-teaming & evals** | Pre-release testing, published in each model's system card |

What the constitution emphasises (paraphrased; read the source for exact wording): being broadly safe (not undermining human oversight of AI), broadly ethical (honest, avoids harm), following Anthropic's more specific guidelines, and being genuinely helpful rather than reflexively cautious. Honesty is treated as close to a hard rule: don't deceive, acknowledge uncertainty.

---

## 7. CAPABILITIES & LIMITATIONS

### What Current Claude Models Are Strong At

| Capability | Notes |
|-----------|-------|
| **Coding & agentic work** | Multi-file changes, long tool-use loops (Claude Code is built on this) |
| **Reasoning** | Multi-step logic and maths, especially with thinking enabled |
| **Long-document analysis** | Up to 1M-token inputs on the larger models |
| **Tool use** | Client tools (you execute), server tools (web search, code execution), MCP |
| **Vision** | Images and PDFs as input (text output only) |

### Known Limitations

| Limitation | Why | Mitigation |
|-----------|-----|------------|
| **Hallucination** | Generates the most plausible continuation, not a verified fact | Grounding (RAG, citations), tools, verification steps |
| **Knowledge cutoff** | Training data stops at a date | Web search, RAG, pass the current date in the prompt |
| **Degradation in long contexts** | Attention spread thin; middle-of-context recall weaker | Put long documents first and the question last; trim irrelevant context |
| **Context limit** | Hard ceiling on input + output | Compaction, chunking, sub-agents |
| **No memory between calls** | API is stateless | Resend history; external memory (files, DB, memory tool) |
| **Non-determinism** | Sampling; even greedy decoding varies slightly | Evals over many samples, structured outputs, validation |
| **Prompt injection** | Instructions inside tool results or documents can be followed | Treat tool output as data, least-privilege tools, human approval for risky actions |

---

## 8. QUICK REFERENCE

```ascii
                    CLAUDE AT A GLANCE (Oct 2026)
                    ─────────────────────────────
  Architecture:   Not disclosed (assume decoder-only transformer)
  Training:       Pre-training → SFT + RLHF + Constitutional AI (RLAIF)
                  + constitution-based character training
  Context:        1M tokens (Opus/Sonnet/Fable), 200K (Haiku 4.5)
  Generation:     Prefill (parallel) then decode (one token at a time)
  Pricing:        Per token; output = 5× input; cache reads ≈ 0.1× input
  Modalities:     Text + image/PDF in, text out
  Tool use:       Client tools, server tools, MCP
  Control knobs:  max_tokens, effort, system prompt, (temperature on older models)
```

### What Interviewers Probe Next

- **"Why is the first token slow but the rest fast?"** Prefill vs decode; TTFT scales with input length, tokens/sec with model size and server load.
- **"Why does a long agent session get expensive?"** Every call resends the whole history; cumulative input grows roughly quadratically with turns unless you cache, compact or reset.
- **"How would you make outputs reproducible?"** You can't fully; pin the model ID, use structured outputs, validate, and evaluate statistically.
- **"What's the difference between the context window and memory?"** The window is per-request input; memory is something your application stores and re-injects.

---

> **Next:** [Claude Code — Interaction Flow](02_CLAUDE_CODE_INTERACTION.md) → How Claude Code drives the model, tools and your file system
