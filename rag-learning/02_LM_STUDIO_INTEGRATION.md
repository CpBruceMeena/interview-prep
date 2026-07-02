# 🖥️ LM Studio + Gemma 4B — Integration Guide

> **How to set up and connect a local LLM to your RAG pipeline**

---

## 1. WHAT IS LM STUDIO?

[LM Studio](https://lmstudio.ai/) is a desktop application that allows you to:
- Download and run open-source LLMs locally
- Serve models via an OpenAI-compatible HTTP API
- No GPU required (runs on CPU, optional GPU acceleration)

**Why LM Studio for RAG?**

| Advantage | Explanation |
|-----------|-------------|
| **Privacy** | All data stays on your machine |
| **No API costs** | Free inference, no token pricing |
| **Offline capable** | No internet needed after model download |
| **OpenAI-compatible** | Drop-in replacement for OpenAI API calls |
| **Model variety** | Gemma, Llama, Mistral, Phi, and 100+ more |

---

## 2. INSTALLATION & SETUP

### Step 1: Download LM Studio
```
Visit https://lmstudio.ai/ → Download → Install
```

### Step 2: Download Gemma 4B Model
```
In LM Studio:
1. Click "Search" tab
2. Search for "gemma-4b-it" or "gemma-2b-it"
3. Click "Download"
```

**Recommended models for RAG:**
| Model | Size | Quality | RAM Required |
|-------|------|---------|-------------|
| Gemma-2B-it | 2B params | Good for simple Q&A | 4GB |
| **Gemma-4B-it** | 4B params | **Best balance** | **8GB** |
| Llama-3.2-3B | 3B params | Excellent for its size | 6GB |
| Mistral-7B | 7B params | Best quality | 16GB |

### Step 3: Load Model & Start Server
```
1. Go to "Chat" tab
2. Select "gemma-4b-it" from dropdown
3. Click "Start Server" button
4. Note the server URL (default: http://localhost:1234)
```
![LM Studio Server](https://lmstudio.ai/docs/assets/images/server-running.png)

**Server configuration:**
- **Port:** 1234 (default)
- **API path:** `/v1/chat/completions`
- **Context length:** 2048-4096 tokens
- **GPU offloading:** Set to max available VRAM

---

## 3. VERIFY THE CONNECTION

### Test with cURL:
```bash
curl http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4b-it",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "What is RAG?"}
    ],
    "temperature": 0.7,
    "max_tokens": 200
  }'
```

### Test with Python:
```python
import requests

response = requests.post(
    "http://localhost:1234/v1/chat/completions",
    json={
        "model": "gemma-4b-it",
        "messages": [
            {"role": "system", "content": "You are a helpful RAG assistant."},
            {"role": "user", "content": "What is retrieval-augmented generation?"}
        ],
        "temperature": 0.3,
        "max_tokens": 500
    }
)
print(response.json()["choices"][0]["message"]["content"])
```

---

## 4. CONFIGURING FOR RAG

**Optimal generation parameters for RAG:**

| Parameter | RAG Value | Reasoning |
|-----------|-----------|-----------|
| `temperature` | 0.2 - 0.3 | Low for factual, deterministic answers |
| `top_p` | 0.9 | Slight diversity while staying focused |
| `max_tokens` | 512-1024 | Long enough for detailed answers |
| `presence_penalty` | 0.0 | No penalty — we want context-based answers |
| `frequency_penalty` | 0.0 | Same as above |

---

## 5. TOKEN PERFORMANCE

| Model | CPU (16 cores) | GPU (RTX 3060) | M1/M2 |
|-------|---------------|----------------|-------|
| Gemma-2B | 15 tok/s | 45 tok/s | 25 tok/s |
| **Gemma-4B** | **8 tok/s** | **30 tok/s** | **15 tok/s** |
| Llama-3.2-3B | 10 tok/s | 35 tok/s | 18 tok/s |
| Mistral-7B | 3 tok/s | 20 tok/s | 8 tok/s |

**For RAG:** Gemma-4B gives the best quality/speed trade-off on consumer hardware.

---

## 6. TROUBLESHOOTING

| Problem | Solution |
|---------|----------|
| **Connection refused** | Ensure LM Studio server is running |
| **Slow generation** | Reduce context length, use smaller model, enable GPU |
| **Out of memory** | Use 4-bit quantization, close other apps |
| **Wrong responses** | Lower temperature to 0.2, check prompt formatting |
| **API not found** | Verify URL: http://localhost:1234/v1/chat/completions |

---

## 7. PYTHON CLIENT CLASS

```python
import requests
from typing import List, Dict, Optional

class LMStudioClient:
    """Client for LM Studio API compatible with OpenAI's interface."""
    
    def __init__(self, base_url: str = "http://localhost:1234", 
                 model: str = "gemma-4b-it"):
        self.base_url = base_url
        self.model = model
        self.api_url = f"{base_url}/v1/chat/completions"
    
    def generate(self, messages: List[Dict[str, str]], 
                 temperature: float = 0.3,
                 max_tokens: int = 1024) -> Optional[str]:
        """Send chat completion request to LM Studio."""
        try:
            response = requests.post(
                self.api_url,
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=60
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except requests.exceptions.ConnectionError:
            print(f"❌ Cannot connect to LM Studio at {self.base_url}")
            print("   Make sure LM Studio is running with the server enabled.")
            return None
        except Exception as e:
            print(f"❌ API error: {e}")
            return None
```
