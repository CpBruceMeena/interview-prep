# 🎯 RAG — Interview Questions & Answers

> **Principal Software Engineer level | 15+ years experience persona**

---

## Question 1: RAG Architecture Design

**Interviewer:** *"Design a RAG system for a customer support chatbot handling 10K product documents."*

### 🎯 Expected Answer

**Overview:**
```
1. Ingestion: PDF/HTML docs → chunk → embed → store
2. Query: User question → embed → retrieve top-5 chunks
3. Generate: Context + question → LLM → answer
4. Feedback: User rating → log for improvement
```

**Key decisions:**
- **Chunk size:** 500 tokens with 50 overlap — balances retrieval precision with context completeness
- **Embedding model:** `bge-small-en-v1.5` — good quality/performance trade-off
- **Vector store:** Chroma for dev, Pinecone for production (managed, scalable)
- **LLM:** Gemma 4B via LM Studio for local, GPT-4 for high-accuracy production
- **Hybrid search:** Dense embeddings + BM25 sparse for 15% recall improvement

**🔴 Follow-up:** *"How do you handle documents with tables and images?"*

**✅ Answer:** Tables → convert to markdown format. Images → extract captions + OCR text, store as text metadata. Don't embed images directly — describe them textually.

---

## Question 2: Chunking Strategy

**Interviewer:** *"Your RAG keeps retrieving incomplete answers. How do you fix chunking?"*

### 🎯 Answer

**Diagnosis:** High recall, low faithfulness → chunks are too small. Low recall → chunks are too large.

**Solutions:**

| Problem | Chunk Size | Overlap | Strategy |
|---------|-----------|---------|----------|
| Missing context | Increase to 800-1000 | 100-200 | Larger chunks |
| Too much noise | Decrease to 200-300 | 20-50 | Smaller, focused chunks |
| Boundary issues | Keep size | 20%+ overlap | Increase overlap |
| Poor relevance | 500 | 50 | Try semantic chunking |

**Parent Document Retriever:**
```python
# Retrieve small child chunks, return parent as context
child_splitter = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=20)
parent_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)

# Store: child_chunk → parent_chunk_id
# Query: search child chunks → retrieve parent for full context
```

---

## Question 3: Improving Retrieval Quality

**Interviewer:** *"Users complain the chatbot gives wrong answers. How do you debug?"*

### 🎯 Answer

**Debugging pipeline:**
```
User Question
    ↓
1. Is retrieval good? → Check top-5 chunks relevance
    ↓ (no)
    ↓ Try: Better embeddings → hybrid search → reranker
    ↓ (yes)
2. Is prompt good? → Check if context is used
    ↓ (no)
    ↓ Try: Stronger instruction → system prompt engineering
    ↓ (yes)
3. Is LLM following instructions? → Check faithfulness
    ↓ (no)
    ↓ Try: Lower temperature → better model → fine-tune
```

**Evaluation framework:**
```python
def evaluate_rag(question, expected_answer, retrieved_docs, generated_answer):
    metrics = {
        "retrieval_hit": is_relevant(retrieved_docs, question),    # Recall
        "faithfulness": is_supported(generated_answer, retrieved_docs),  # Avoid hallucination
        "answer_relevance": cosine_sim(generated_answer, expected_answer),  # Quality
    }
    return metrics
```

---

## Question 4: Production Scaling

**Interviewer:** *"How do you scale RAG to 10M documents with <1s response time?"*

### 🎯 Answer

**Architecture:**
```
                   ┌──────────┐
User ──▶ API GW ──▶  Cache    ──▶ Retriever ──▶ LLM
                   │ (Redis)  │    │
                   └──────────┘    │
                           ┌───────▼──────┐
                           │ Vector Store │
                           │ (Pinecone)   │
                           │ - 10 shards  │
                           │ - 2 replicas │
                           └──────────────┘
```

**Latency budget (target <1s):**
- Embedding: 50ms (cached queries)
- Vector search: 100ms (indexed, sharded)
- Reranking: 100ms (cross-encoder)
- LLM generation: 500ms (Gemma 4B local)
- Overhead: 250ms

**Caching strategies:**
- **Query cache:** Identical questions → return cached answer (TTL: 1 hour)
- **Document cache:** Frequently retrieved docs → Redis (TTL: 10 min)
- **Embedding cache:** Pre-compute embeddings for common queries

---

## Question 5: Handling Hallucination

**Interviewer:** *"How do you ensure the LLM doesn't make up information?"*

### 🎯 Answer

**Multi-layer approach:**
1. **Prompt engineering:** "Answer based ONLY on the provided context. If unsure, say 'I don't know.'"
2. **Temperature:** 0.2 for factual answers
3. **Faithfulness check:** Post-generation verification
```python
def verify_faithfulness(answer, context):
    prompt = f"""Does the answer below contain any claims NOT supported by the context?
    
    Context: {context}
    
    Answer: {answer}
    
    Respond with ONLY: SUPPORTED or UNSUPPORTED with explanation."""
    
    result = llm.generate(prompt)
    return "UNSUPPORTED" not in result
```
4. **Fallback:** If not faithful, return "I don't have enough information" instead
5. **Human-in-loop:** For high-stakes answers, route to human review

---

## Question 6: RAG vs Fine-Tuning

**Interviewer:** *"When would you RAG vs. fine-tune a model?"*

| Criteria | RAG | Fine-Tune | 
|----------|-----|-----------|
| **Knowledge updates** | Instant (update docs) | Days (retrain) |
| **Domain complexity** | Low-medium | Medium-high |
| **Data volume** | Any | 500+ examples |
| **Latency** | +200ms retrieval | Same as base model |
| **Cost** | Low (embedding+store) | High (GPU training) |
| **Explainability** | Shows source docs | Black box |

**Rule of thumb:** Start with RAG. Add fine-tuning only if RAG hits a ceiling on quality.

---

## Question 7: Multi-Modal RAG

**Interviewer:** *"How would you extend RAG to handle images?"*

**✅ Answer:**
```python
class MultiModalRAG:
    def index_image(self, image_path):
        # Option 1: Caption-based (simpler)
        caption = image_captioning_model(image_path)  # BLIP, GIT
        text_chunk = f"[IMAGE: {caption}]"
        
        # Option 2: Embedding-based (better)
        image_embedding = clip_model.encode_image(image_path)
        store_image(image_path, image_embedding)
    
    def retrieve(self, query):
        text_results = text_retriever.search(query)
        image_results = image_retriever.search(query)  # CLIP similarity
        return {"text": text_results, "images": image_results}
```

---

## Question 8: Evaluation & Metrics

**Interviewer:** *"How do you measure RAG quality in production?"*

### 🎯 Answer

**Production metrics:**
- **Retrieval recall@5:** % of queries where top-5 chunks contain the answer
- **Faithfulness score:** % of claims in response supported by retrieved chunks
- **End-user rating:** Thumbs up/down after each answer
- **Latency p95:** Time from query to response
- **Fallback rate:** % of queries answered with "I don't know"

**A/B testing framework:**
```python
# Compare two RAG configurations
control = RAGPipeline(chunk_size=500, top_k=5)
variant = RAGPipeline(chunk_size=800, top_k=10)

results = ab_test(control, variant, test_queries)
# Compare: faithfulness, latency, user satisfaction
```
