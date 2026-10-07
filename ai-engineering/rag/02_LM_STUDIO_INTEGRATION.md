# 🖥️ LM Studio + a Small Local Model — Integration Guide

> **How to run a local LLM and connect it to the RAG pipeline.** Model names and UI labels change often; this page is accurate for LM Studio 0.4.x (2026). Check the [LM Studio docs](https://lmstudio.ai/docs) if a menu has moved.

!!! tip "30-second answer: why a local model behind an OpenAI-compatible API?"
    LM Studio runs open-weight models (GGUF via llama.cpp, and MLX on Apple Silicon) and serves them at `http://localhost:1234/v1` with the same request/response shape as OpenAI. Your RAG code talks to "an OpenAI-compatible endpoint", so swapping LM Studio for OpenAI, vLLM or Ollama is a config change (base URL + model id). Local inference buys privacy, offline use and zero per-token cost; it costs you quality (small models), throughput, and the ops work of running it yourself.

---

## 1. WHAT IS LM STUDIO?

[LM Studio](https://lmstudio.ai/) is a desktop app (plus a CLI, `lms`, and since 0.4 a headless daemon, *llmster*) that:

- downloads open-weight models from Hugging Face (GGUF, and MLX on Apple Silicon),
- runs them on CPU, or GPU via Metal / CUDA / Vulkan,
- serves them over HTTP: OpenAI-compatible endpoints (`/v1/models`, `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/responses`) plus LM Studio's own REST API and SDKs.

**Why LM Studio for this RAG demo?**

| Advantage | Explanation |
|-----------|-------------|
| **Privacy** | Prompts and documents never leave the machine |
| **No per-token cost** | You pay in hardware and electricity instead |
| **Offline** | No network needed after the model download |
| **OpenAI-compatible** | Point any OpenAI client at `http://localhost:1234/v1` |
| **Model variety** | Gemma, Qwen, Llama, Phi, Mistral and many more |

**What it is not:** a production serving stack for many concurrent users. 0.4 added parallel requests with continuous batching and a headless daemon, which is fine for a team or a lab box. For high-QPS production, dedicated servers (vLLM, SGLang, TGI, TensorRT-LLM) give higher throughput, better observability and Kubernetes-native deployment.

---

## 2. INSTALLATION & SETUP

### Step 1: Download LM Studio
Install from <https://lmstudio.ai/>. The `lms` CLI ships with it.

### Step 2: Download a small instruction-tuned model
In the app's model search (or `lms get <model>`), pick a small instruct model. Examples as of 2026:

| Family | Example sizes | Notes |
|---|---|---|
| **Gemma 4** (Apr 2026, Apache 2.0) | E2B, E4B, 26B MoE, 31B | E2B/E4B are edge-sized, multimodal |
| Gemma 3 | 1B, 4B, 12B, 27B | Still widely used |
| Qwen3 | 0.6B – 32B dense, plus MoE | Strong small models, multilingual |
| Llama 3.x | 1B, 3B, 8B | Broad ecosystem |
| Phi-4-mini, Mistral Small | ~4B, ~24B | Alternatives |

**Rule of thumb for memory:** a 4-bit quantised model needs roughly *params × 0.5–0.6 bytes*, plus the KV cache, which grows with context length. So a ~4B model needs about 3 GB for weights and runs comfortably on an 8 GB machine; a 7–8B model wants ~6 GB+. Check the file size LM Studio shows; it is the best estimate.

### Step 3: Load the model and start the server

- **App:** open the **Developer** tab, load the model, and toggle **Start server**.
- **CLI:**
  ```bash
  lms server start          # serves on http://localhost:1234
  lms load <model-key>      # load a downloaded model
  lms ls                    # list downloaded models
  ```

**Server notes:**

- **Port:** 1234 by default; OpenAI base URL `http://localhost:1234/v1`.
- **Model id:** call `GET /v1/models` and use the exact `id` returned (e.g. `google/gemma-4-e4b`) in the `model` field.
- **Context length** is set when the model is loaded. RAG prompts are long (system prompt + k chunks + question), so 8K or more is a sensible minimum; larger contexts cost memory for the KV cache.
- **GPU offload:** as many layers as fit in VRAM.

---

## 3. VERIFY THE CONNECTION

### Test with cURL
```bash
curl http://localhost:1234/v1/models

curl http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google/gemma-4-e4b",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "What is RAG?"}
    ],
    "temperature": 0.2,
    "max_tokens": 200
  }'
```

### Test with Python

Using the official OpenAI client:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")  # key is ignored locally

resp = client.chat.completions.create(
    model="google/gemma-4-e4b",            # id from GET /v1/models
    messages=[
        {"role": "system", "content": "You are a helpful RAG assistant."},
        {"role": "user", "content": "What is retrieval-augmented generation?"},
    ],
    temperature=0.2,
    max_tokens=500,
)
print(resp.choices[0].message.content)
```

Using the OpenAI client (rather than raw `requests`) gets you retries, timeouts, streaming and typed responses, and the code moves to a hosted provider unchanged.

---

## 4. CONFIGURING FOR RAG

| Parameter | RAG Value | Reasoning |
|-----------|-----------|-----------|
| `temperature` | 0 – 0.3 | Factual answers; less paraphrase drift from the context |
| `top_p` | 1.0 (leave default) or ~0.9 | Tune temperature *or* top_p, not both |
| `max_tokens` | 512–1024 | Enough for an answer with citations; caps cost and latency |
| `presence_penalty` / `frequency_penalty` | 0 | Penalties push the model away from repeating context terms, which is what you want it to do |
| `stream` | `true` in UIs | Users see the first token in well under the total generation time |

Low temperature reduces randomness; it does **not** stop hallucination. Grounding comes from retrieval quality, the abstain instruction and verification.

---

## 5. TOKEN PERFORMANCE

Throughput depends on model size, quantisation, hardware, context length and the runtime, so measure on your machine instead of trusting published tables. What to know for an interview:

- **Decode speed is memory-bandwidth-bound.** Each generated token reads all the (active) weights, so tokens/s ≈ memory bandwidth ÷ model size in bytes. This is why 4-bit quantisation roughly doubles speed versus 8-bit, why Apple Silicon (high unified-memory bandwidth) runs local models well, and why MoE models with few active parameters decode fast.
- **Prefill (reading the prompt) is compute-bound** and parallel. Long RAG prompts mostly show up as **time to first token (TTFT)**.
- Measure **TTFT** and **tokens/s** separately: RAG makes prompts long, so TTFT often dominates.
- Quick check: LM Studio shows tokens/s and time to first token for each response in the chat view.

---

## 6. TROUBLESHOOTING

| Problem | Solution |
|---------|----------|
| **Connection refused** | Start the server (Developer tab or `lms server start`); check the port |
| **404 / "model not found"** | `model` must match an id from `GET /v1/models`; load the model |
| **Slow first token** | Prompt too long: fewer/shorter chunks, enable GPU offload |
| **Out of memory** | Smaller model or lower-bit quant, shorter context length |
| **Rambling or ignores context** | Lower temperature, put rules in the system message, try a stronger model |
| **Truncated answers** | Raise `max_tokens`; check that the context length fits prompt + answer |

---

## 7. PYTHON CLIENT CLASS

The repo's client is `implementation/llm_service.py`: `LMStudioClient` extends a generic `OpenAICompatibleClient`. A minimal version:

```python
import logging
from typing import Dict, List, Optional

import requests

log = logging.getLogger(__name__)


class LMStudioClient:
    """Minimal client for LM Studio's OpenAI-compatible chat endpoint."""

    def __init__(self, base_url: str = "http://localhost:1234",
                 model: str = "google/gemma-4-e4b", timeout: float = 120):
        self.api_url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self.model = model
        self.timeout = timeout

    def generate(self, messages: List[Dict[str, str]],
                 temperature: Optional[float] = 0.2,
                 max_tokens: int = 1024) -> Optional[str]:
        try:
            resp = requests.post(
                self.api_url,
                json={"model": self.model, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            log.error("LM Studio call failed: %s", e)   # log, don't print
            return None                                 # caller degrades gracefully
```

**Design points an interviewer may probe:**

- **Return `None` vs raise:** returning `None` lets the pipeline answer "model unavailable" cleanly. Raising typed errors is better when callers need to tell timeout from bad request.
- **Timeouts and retries:** always set a timeout. Retry only idempotent failures (connection errors, 429/503) with backoff, and never retry for longer than the user will wait.
- **Temperature 0 bug:** `temperature or default` silently turns `0.0` into the default. Use `default if temperature is None else temperature` (the repo code does).
