# LM Studio Setup and Configuration

## What is LM Studio?

LM Studio is a desktop application (with a command-line tool, `lms`, and since version 0.4 a headless server daemon called llmster) for running open-weight LLMs locally. It serves them through an OpenAI-compatible API on `http://localhost:1234/v1`, which makes it a good fit for RAG prototypes that need privacy, offline capability, and cost control. For high-traffic production serving, dedicated engines such as vLLM or SGLang are the usual choice.

## Supported Models

LM Studio downloads models from Hugging Face in GGUF format (llama.cpp engine) and, on Apple Silicon, MLX format. Small instruction-tuned models that work well for RAG prototypes (as of 2026):

| Model family | Example sizes | Approx. RAM at 4-bit | Notes |
|-------|------|-----------|-------|
| Gemma 4 (Google, April 2026) | E2B, E4B | ~2-4GB | Edge-sized, multimodal, Apache 2.0 |
| Gemma 3 (Google) | 4B, 12B | ~3GB, ~8GB | Widely used |
| Qwen3 (Alibaba) | 4B, 8B | ~3GB, ~5GB | Strong multilingual small models |
| Llama 3.2 / 3.1 (Meta) | 3B, 8B | ~2GB, ~5GB | Large ecosystem |
| Phi-4-mini (Microsoft) | 3.8B | ~3GB | Good reasoning for its size |

RAM figures are rough: 4-bit weights take about half a byte per parameter, plus the KV cache, which grows with context length.

## Setup Steps

### 1. Download and Install
Download LM Studio from the official website and install it.

### 2. Download a Model
- Open LM Studio and search for a model (e.g., "gemma 4" or "qwen3 4b"), or run `lms get <model>`
- Pick a quantization (Q4_K_M is a good default) and download

### 3. Load the Model
- Load the model in the app, or run `lms load <model>`
- Configure load settings:
  - GPU Offload: as many layers as fit in GPU memory
  - Context Length: 8192 tokens or more for RAG (system prompt + several chunks + answer)

### 4. Start the API Server
- Open the **Developer** tab and toggle **Start server**, or run `lms server start`
- Default URL: http://localhost:1234 (OpenAI-compatible base URL: http://localhost:1234/v1)
- Enable CORS only if a browser app calls the server directly
- Call `GET /v1/models` and use the exact model id it returns in your requests

## API Endpoints

LM Studio exposes OpenAI-compatible endpoints (`/v1/models`, `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/responses`), plus its own REST API and SDKs:

### Chat Completions
```
POST http://localhost:1234/v1/chat/completions
Content-Type: application/json

{
  "model": "google/gemma-4-e4b",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is RAG?"}
  ],
  "temperature": 0.3,
  "max_tokens": 1024
}
```

### List Models
```
GET http://localhost:1234/v1/models
```

### Embeddings (requires an embedding model)
A chat model cannot serve this endpoint; load a dedicated embedding model (for example a Nomic Embed or BGE GGUF) and use its id:
```
POST http://localhost:1234/v1/embeddings
Content-Type: application/json

{
  "model": "text-embedding-nomic-embed-text-v1.5",
  "input": "Text to embed"
}
```
Whatever model you use, index and query embeddings must come from the same one.

## Configuration for RAG

### Optimal Settings for RAG
```python
request_settings = {
    "temperature": 0.2,   # Lower = less random; it does not by itself prevent hallucination
    "max_tokens": 1024,   # Enough for detailed answers with citations
}
# Set when loading the model (not per request):
#   context length >= 8192 tokens, GPU offload as high as fits
# Sampling options such as repeat penalty live in LM Studio's model settings.
```

### System Prompt Template
```python
SYSTEM_PROMPT = """
You are a helpful assistant. Answer based ONLY on the provided context.

Rules:
1. If context contains the answer, provide it clearly with citations
2. If context is insufficient, say "I don't have enough information"
3. Do NOT make up facts outside the context
4. Cite source document names when possible

Context:
{context}

Question: {question}
Answer:
"""
```

## Performance Optimization

### Quantization Levels
GGUF quantization names describe bits per weight; fewer bits = smaller and faster, with some quality loss:
- **Q4_K_M**: Common default; good balance of quality, size and speed
- **Q5_K_M / Q6_K**: Higher quality, larger and slower
- **Q8_0**: Close to full precision, roughly twice the memory of Q4
- **Q2_K / Q3_K**: Smallest, noticeably lower quality; only when memory is very tight

Generation speed is mostly limited by memory bandwidth (each token reads all the weights), so smaller quantizations generate faster.

### GPU Acceleration
- macOS (Apple Silicon): Metal for GGUF models, plus the MLX engine for MLX models
- Windows / Linux: CUDA for NVIDIA GPUs; Vulkan (and ROCm on supported AMD GPUs) for others

### Batch Processing
Indexing does not need the chat model at all: embed documents with a dedicated embedding model (for example all-MiniLM-L6-v2 via sentence-transformers, which embeds in batches), and use the LLM only at query time. LM Studio 0.4 can also process parallel requests to the same model with continuous batching, which helps when several users query at once.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Connection refused | Check LM Studio is running and server is started |
| Out of memory | Use a smaller model or lower quantization |
| Slow responses | Enable GPU offload, reduce context length |
| 404 or "model not found" | Use the exact id from `GET /v1/models`; make sure the model is loaded |
| Gibberish output | Wrong chat template or a broken quantization; try another build of the model, lower temperature |
| Empty responses | Check model is loaded, increase max_tokens |
| API timeout | Reduce context length, check system resources |
