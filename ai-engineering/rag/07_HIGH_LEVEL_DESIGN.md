# 🏗️ High-Level Design — RAG Chatbot in Production

> **Target:** Principal Engineer | **Focus:** Scalable architecture, deployment, monitoring

---

## 1. SYSTEM OVERVIEW

**Purpose:** Production RAG chatbot answering user questions from a knowledge base of 100K+ documents.

**Scale:** 1M queries/day, 100K documents, <2s p95 latency, 99.9% uptime

**Users:** End customers, Content managers, ML engineers, Operations team

**Use Cases:** Ask question, Get grounded answer, Index new documents, Update knowledge base, Evaluate quality

**Constraints:** <2s response time, 99.9% availability, data privacy (no data leaves VPC), cost < $0.01/query

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                              │
│               Web App (React)  │  Slack Bot  │  API Clients        │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────────┐
│                       API Gateway (Kong/AWS ALB)                    │
│  - Rate limiting (10 req/s per user)                               │
│  - Authentication (JWT / API Key)                                  │
│  - Request logging                                                  │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────────┐
│                     RAG Orchestrator Service                        │
│                     (Python/FastAPI, auto-scaled)                   │
├─────────────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ Query Router  │  │ Cache        │  │ Feedback Collector       │ │
│  │ (classify +   │  │ (Redis)      │  │ (thumb up/down, ratings) │ │
│  │  route)       │  └──────────────┘  └──────────────────────────┘ │
│  └───────┬───────┘                                                 │
└──────────┼─────────────────────────────────────────────────────────┘
           │
    ┌──────┼──────────────────────────────────────────┐
    │      │                                          │
┌───▼──────▼───┐  ┌──────────────┐  ┌────────────────▼──────┐
│  Embedding   │  │  Vector      │  │  LLM Inferences       │
│  Service     │  │  Store       │  │  (LM Studio Cluster)  │
│  (GPU pod)   │  │  (Pinecone/  │  │  - Gemma 4B × 8 pods │
│              │  │   Weaviate)  │  │  - Load balanced       │
└──────────────┘  └──────────────┘  └───────────────────────┘
                                        │
                              ┌─────────▼──────────┐
                              │  Monitoring Stack   │
                              │  Prometheus +        │
                              │  Grafana + Alerting  │
                              └─────────────────────┘
```

---

## 3. COMPONENT BREAKDOWN & INTERVIEW Q&A

### 3.1 RAG Orchestrator (Python/FastAPI)

**Responsibilities:**
- Query preprocessing (spell check, query expansion)
- Multi-step retrieval (dense + sparse hybrid)
- Context assembly and prompt construction
- Response post-processing (faithfulness check)
- Caching frequent queries

**🔴 Interview Question:** *"How would you design query caching in RAG?"*

**✅ Answer:** Multi-level cache:
1. **L1 — Exact match:** Identical questions → return cached answer (Redis, TTL: 1 hour)
2. **L2 — Semantic cache:** Similar questions (cosine similarity > 0.95) → return cached answer
3. **Invalidation:** When knowledge base updates, invalidate affected cache entries
4. **Cache key:** Hash(question + top_k + llm_model) — ensures parameters match

---

### 3.2 Embedding Service (GPU Pod)

**Responsibilities:**
- Batch embedding of documents during indexing
- Real-time query embedding
- Cache frequently-used embeddings

**Scale:** 100K docs × 384 dim = ~150MB of embeddings (easily fits in memory).

**🔴 Interview Question:** *"How do you handle embedding 100K documents efficiently?"*

**✅ Answer:**
1. **Batch processing:** 256 documents/batch → 3x faster than sequential
2. **GPU acceleration:** sentence-transformers on GPU → 50x faster than CPU
3. **Parallel files:** Process multiple files concurrently with ThreadPoolExecutor
4. **Incremental indexing:** Only embed new/modified documents, not the entire corpus

---

### 3.3 Vector Store (Pinecone/Weaviate)

**Responsibilities:**
- Store 100K+ vectors with metadata
- Real-time similarity search (p99 < 100ms)
- Filter by metadata (date, category, source)
- High availability with replication

**🔴 Interview Question:** *"How do you choose between Pinecone, Weaviate, and Chroma for production?"*

| Feature | Chroma | Weaviate | Pinecone |
|---------|--------|----------|----------|
| Self-hosted | ✅ | ✅ | ❌ |
| Managed cloud | ❌ | ✅ | ✅ |
| p99 latency | 50ms | 20ms | 10ms |
| Scaling | Manual | Kubernetes | Auto |
| Cost (100K vectors) | Free | ~$200/mo | ~$300/mo |
| Best for | Dev/Prototype | Self-hosted prod | Fully managed prod |

---

### 3.4 LLM Inference (LM Studio Cluster)

**Responsibilities:**
- Load-balanced inference across multiple LM Studio instances
- Health checks and automatic failover
- Request queuing during high load

**🔴 Interview Question:** *"How do you scale LLM inference for production?"*

**✅ Answer:**
1. **Multiple LM Studio instances:** Run Gemma 4B on 8 nodes, load-balance with round-robin
2. **Request queue:** Buffer during spikes (Redis queue), process in FIFO order
3. **Batching:** If multiple requests arrive simultaneously, batch them for GPU efficiency
4. **Fallback:** If LM Studio cluster fails, fall back to OpenAI API or a cached response
5. **Model cache:** Keep model loaded in GPU memory — no reload delay

---

## 4. DATA FLOW — Complete Request Lifecycle

```
1. User sends query → API Gateway → RAG Orchestrator
2. Orchestrator checks Redis cache → MISS
3. Embedding Service embeds query → vector (5ms)
4. Vector Store searches top-5 chunks → retrieved (50ms)
5. Reranker re-orders chunks → re-ranked (50ms)
6. Context assembled: 5 chunks = ~2500 tokens
7. LLM generates response with context (800ms)
8. Faithfulness check: verify answer against context (100ms)
9. Cache response in Redis → return to user
Total: ~1 second
```

---

## 5. SCALABILITY ANALYSIS

**Bottlenecks:**
1. **LLM inference** — slowest component (800ms avg)
2. **Vector search** — degrades with >1M vectors without indexing
3. **Document loading** — PDF parsing is CPU-intensive

**Solutions:**
- LLM: Horizontal scaling (more LM Studio instances), quantization (4-bit), smaller model
- Vector search: IVF index (Inverted File Index) with 100 centroids
- Document loading: Background async task, SQS queue

---

## 6. MONITORING & OBSERVABILITY

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| **p95 latency** | > 3s | Scale LLM instances |
| **Retrieval recall@5** | < 80% | Retrain embeddings |
| **Faithfulness score** | < 90% | Check prompt, lower temperature |
| **LLM error rate** | > 5% | Fallback to OpenAI |
| **Cache hit rate** | < 20% | Pre-compute popular queries |

---

## 7. COST BREAKDOWN (Monthly)

| Component | Estimated Cost |
|-----------|---------------|
| RAG Orchestrator (auto-scaled) | $1,500 |
| Embedding Service (GPU pod) | $800 |
| Vector Store (Pinecone) | $300 |
| LLM Cluster (8 × GPU instances) | $4,000 |
| Redis Cache | $400 |
| Monitoring + Logging | $300 |
| **Total** | **$7,300** |

---

## 8. SECURITY CONSIDERATIONS

- **Data isolation:** All data stays within VPC, no external API calls
- **Model isolation:** LM Studio runs in isolated container, no internet access
- **Rate limiting:** 10 queries/second per user to prevent abuse
- **Input sanitization:** Strip prompt injection attempts from user queries
- **Audit logging:** All queries and responses logged for compliance
