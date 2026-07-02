# 🔧 Fine-Tuning Guide for RAG Pipelines

> **Strategies for optimizing each component of a RAG system**

---

## 1. OVERVIEW: WHAT CAN BE FINE-TUNED?

In a RAG pipeline, there are 3 main components that can be fine-tuned:

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Embedding   │   │   Retriever  │   │  Generator   │
│  Model       │   │   (Reranker) │   │  (LLM)       │
├──────────────┤   ├──────────────┤   ├──────────────┤
│ Better       │   │ Better       │   │ Better       │
│ semantic     │   │ ranking of   │   │ grounded     │
│ search       │   │ results      │   │ responses    │
└──────────────┘   └──────────────┘   └──────────────┘
```

---

## 2. FINE-TUNING THE EMBEDDING MODEL

**Why?** Generic embeddings may not capture domain-specific semantics (medical terms, legal jargon, code).

### Method: Contrastive Learning
```python
from sentence_transformers import SentenceTransformer, InputExample, losses

model = SentenceTransformer('all-MiniLM-L6-v2')

# Training data: (anchor, positive, negative) triplets
train_examples = [
    InputExample(texts=[
        "How do I reset my password?",           # anchor (query)
        "Password reset instructions page",       # positive (relevant doc)
        "Account billing information"             # negative (irrelevant doc)
    ]),
    # ... more examples
]

train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=16)
train_loss = losses.TripletLoss(model)

model.fit(
    train_objectives=[(train_dataloader, train_loss)],
    epochs=3,
    warmup_steps=100,
    output_path='./fine-tuned-embedding'
)
```

### When to Fine-Tune Embeddings

| Scenario | Generic Embedding | Fine-Tuned |
|----------|------------------|------------|
| General knowledge Q&A | ✅ Good | ✅ Better |
| Medical/legal domain | ❌ Misses terms | ✅ Captures nuances |
| Code documentation | ❌ Poor matching | ✅ Great |
| Company-internal terms | ❌ Fails | ✅ Perfect |

---

## 3. FINE-TUNING THE RETRIEVER (RERANKER)

**Why?** Initial retrieval (cosine similarity) can be noisy. A reranker model re-scores results for better precision.

```python
from sentence_transformers import CrossEncoder

# Cross-encoder reranker scores query-document pairs
reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

def rerank(query, documents, top_k=3):
    pairs = [(query, doc) for doc in documents]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)
    return [doc for doc, score in ranked[:top_k]]
```

**Performance impact:**
- Without reranker: 85% recall@5
- With reranker: 95% recall@5

---

## 4. FINE-TUNING THE LLM (GENERATOR)

**Why?** Base Gemma 4B might not follow RAG instructions optimally.

### Quantized Fine-Tuning (QLoRA)

QLoRA allows fine-tuning on consumer hardware:

```python
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model

# 4-bit quantization
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16
)

model = AutoModelForCausalLM.from_pretrained(
    "google/gemma-4b-it",
    quantization_config=bnb_config,
    device_map="auto"
)

# LoRA configuration
lora_config = LoraConfig(
    r=16,        # Rank
    lora_alpha=32,
    target_modules=["q_proj", "v_proj"],  # Only train attention layers
    lora_dropout=0.1,
    bias="none",
    task_type="CAUSAL_LM"
)

model = get_peft_model(model, lora_config)

# Training data format
train_data = [
    {"context": "...", "question": "...", "answer": "..."},
]
```

### Dataset Format for RAG Fine-Tuning
```json
{
  "instruction": "Answer based ONLY on the provided context.",
  "context": "RAG stands for Retrieval-Augmented Generation...",
  "question": "What does RAG stand for?",
  "output": "RAG stands for Retrieval-Augmented Generation."
}
```

---

## 5. WHEN TO FINE-TUNE VS. WHEN TO USE RAG

| Approach | Best For | Cost | Up-to-date? |
|----------|----------|------|-------------|
| **RAG only** | Dynamic knowledge, quick setup | Low | ✅ Always |
| **Fine-tune only** | Static behavior, style transfer | High upfront | ❌ Stale |
| **RAG + Fine-tune** | Best of both | Medium | ✅ Always |

**Recommendation:** Start with RAG-only. Add fine-tuning only if:
- Retrieval quality is consistently poor (try better embeddings first)
- LLM doesn't follow instructions (try prompt engineering first)
- You need specific output formatting (JSON, markdown)

---

## 6. EVALUATING FINE-TUNING

| Before Fine-Tuning | After Fine-Tuning |
|--------------------|-------------------|
| Retrieval recall@5: 82% | Recall@5: 94% |
| Faithfulness score: 0.85 | Faithfulness: 0.97 |
| Response relevance: 3.8/5 | Relevance: 4.5/5 |
| Hallucination rate: 8% | Hallucination rate: 2% |
