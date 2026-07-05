# LM Studio Setup and Configuration

## What is LM Studio?

LM Studio is a desktop application that allows you to run local LLMs on your machine. It provides an OpenAI-compatible API server, making it perfect for RAG systems that need privacy, offline capability, and cost control.

## Supported Models

LM Studio downloads models from Hugging Face. Recommended models for RAG:

| Model | Size | RAM Needed | Quality | Speed |
|-------|------|-----------|---------|-------|
| Gemma 4B (Google) | 4B params | 4GB | Good | Fast |
| Mistral 7B | 7B params | 8GB | Very Good | Moderate |
| Llama 3.2 3B | 3B params | 4GB | Good | Fast |
| Phi-3 Mini (Microsoft) | 3.8B params | 4GB | Very Good | Fast |
| Zephyr 7B | 7B params | 8GB | Good | Moderate |

## Setup Steps

### 1. Download and Install
Download LM Studio from the official website and install it.

### 2. Download a Model
- Open LM Studio
- Search for your model (e.g., "gemma-4b-it-GGUF")
- Click Download
- Wait for the model to download

### 3. Load the Model
- Go to the "Chat" tab
- Select your downloaded model
- Configure settings:
  - GPU Offload: Max (for speed)
  - Context Length: 4096 tokens
  - Temperature: 0.3 for factual tasks

### 4. Start the API Server
- Click the "Server" button (or go to server tab)
- Enable "Cross-Origin Requests" (CORS)
- Note the server URL (default: http://localhost:1234)
- Click "Start Server"

## API Endpoints

LM Studio exposes OpenAI-compatible endpoints:

### Chat Completions
```
POST http://localhost:1234/v1/chat/completions
Content-Type: application/json

{
  "model": "gemma-4b-it",
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

### Embeddings (if model supports it)
```
POST http://localhost:1234/v1/embeddings
Content-Type: application/json

{
  "model": "gemma-4b-it",
  "input": "Text to embed"
}
```

## Configuration for RAG

### Optimal Settings for RAG
```python
settings = {
    "temperature": 0.3,  # Lower = more deterministic
    "max_tokens": 1024,  # Enough for detailed answers
    "context_length": 4096,  # Model's max context window
    "repeat_penalty": 1.1,  # Prevent repetition
}
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
- **Q4_K_M**: Best balance of quality and speed (recommended)
- **Q5_K_M**: Higher quality, slightly slower
- **Q8_0**: Maximum quality, requires more RAM
- **Q2_K**: Fastest, lowest quality

### GPU Acceleration
- macOS: Metal API (automatic)
- Windows: CUDA (NVIDIA) or DirectML (AMD)
- Linux: CUDA (NVIDIA) or Vulkan

### Batch Processing
For indexing many documents, disable the LLM and use dedicated embedding models:
```
all-MiniLM-L6-v2 for embeddings → ~10ms per chunk
Gemma 4B for generation → ~500ms per response
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Connection refused | Check LM Studio is running and server is started |
| Out of memory | Use a smaller model or lower quantization |
| Slow responses | Enable GPU offload, reduce context length |
| Gibberish output | Lower temperature, increase repeat penalty |
| Empty responses | Check model is loaded, increase max_tokens |
| API timeout | Reduce context length, check system resources |
