# Retrieval Strategies for RAG

## Core Retrieval Approaches

### 1. Dense Retrieval (Vector Search)
Uses neural embeddings to find semantically similar content.

```python
query_vector = embedder.encode("What is chunking?")
results = vector_store.search(query_vector, top_k=5)
```

**Pros**:
- Captures semantic similarity beyond keyword matching
- Handles synonyms and paraphrasing
- Works across languages with multilingual embeddings

**Cons**:
- Requires embedding computation at query time
- Needs a vector index (approximate nearest neighbour search, e.g. HNSW)
- Can miss exact keyword matches: IDs, error codes, product names, rare acronyms

### 2. Sparse Retrieval (Keyword/BM25)
Uses traditional information retrieval based on term frequency.

```python
from rank_bm25 import BM25Okapi
tokenized_docs = [doc.lower().split() for doc in documents]   # real systems: proper analyzer
bm25 = BM25Okapi(tokenized_docs)
results = bm25.get_top_n(query.lower().split(), documents, n=5)
```

**Pros**:
- Fast, no GPU needed
- Good at exact keyword matching
- Well-understood, deterministic
- No embedding cost

**Cons**:
- Misses semantic relationships
- Vocabulary mismatch problem
- No cross-lingual capability
- Quality depends on tokenization and stemming (analyzers), especially for code and non-English text

### 3. Hybrid Retrieval
Combines dense and sparse retrieval for the best of both worlds.

```python
dense_results = vector_store.search(query_embedding, top_k=50)   # [(doc_id, score), ...] best first
sparse_results = bm25_search(query, top_k=50)

# Reciprocal Rank Fusion (Cormack et al., 2009): score(d) = sum over lists of 1 / (k + rank)
# k = 60 is the conventional constant; ranks start at 1.
K = 60
combined = {}
for results in (dense_results, sparse_results):
    for rank, (doc_id, _score) in enumerate(results, start=1):
        combined[doc_id] = combined.get(doc_id, 0.0) + 1.0 / (K + rank)

final_results = sorted(combined.items(), key=lambda x: -x[1])[:10]
```

RRF uses only ranks, so the raw scores of the two systems (cosine similarity vs unbounded BM25) never need to be made comparable. The alternative, weighted score fusion (`alpha * dense + (1 - alpha) * bm25`), requires normalizing both score ranges first and tuning `alpha`.

**Pros**:
- Best overall retrieval quality
- Robust to different query types
- Complements weaknesses of each approach

**Cons**:
- More complex infrastructure (two indexes to keep in sync)
- Slightly higher latency (two searches, usually run in parallel)
- Weighted score fusion needs score normalization and tuning (RRF avoids this)

## Advanced Retrieval Techniques

### 4. Query Rewriting
Transforms the user's query to improve retrieval quality.

```python
def rewrite_query(original_query, llm):
    prompt = f"Rewrite this question to be more specific for document retrieval:\nOriginal: {original_query}\nRewritten:"
    return llm.generate(prompt)
```

**Use cases**:
- Short or ambiguous queries
- Follow-up questions without context
- Domain-specific terminology expansion

### 5. Query Expansion
Generates multiple variations of the query to increase recall.

```python
def expand_query(query, llm):
    variations = llm.generate(f"Generate 3 alternative phrasings of: {query}")
    return [query] + variations.split("\n")
```

A related technique, **HyDE** (Hypothetical Document Embeddings), asks the LLM to write a hypothetical answer and embeds that instead of the question, because an answer looks more like the documents than the question does.

**Use cases**:
- High-recall requirements (legal, compliance)
- Technical or niche domains
- When missing critical documents is costly

### 6. Multi-Hop Retrieval
Retrieves information iteratively, using each step's findings to inform the next.

```python
def multi_hop_retrieve(question, retriever, max_hops=3):
    context = ""
    for hop in range(max_hops):
        # Use previous context to refine the query
        enhanced_query = f"{context}\nQuestion: {question}"
        results = retriever.retrieve(enhanced_query)
        new_info = extract_new_information(results, context)
        if not new_info:
            break
        context += new_info
    return context
```

**Use cases**:
- Complex reasoning chains
- Questions requiring multiple pieces of evidence
- Comparative analysis across documents

## Re-Ranking

Re-ranking refines initial retrieval results using a more expensive model. A **cross-encoder** reads the query and a candidate document together and outputs a relevance score. It is far more accurate than comparing two independently computed embeddings, but needs one model call per candidate, so it is applied only to the top 20-100 candidates. Rerankers improve precision at the top of the list; they cannot recover a relevant document that first-stage retrieval missed.

```python
from sentence_transformers import CrossEncoder

# Initial retrieval (fast, lightweight)
initial_results = dense_retriever.retrieve(query, top_k=20)

# Re-ranking (slower but more accurate)
cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2')
pairs = [[query, doc] for doc in initial_results]
scores = cross_encoder.predict(pairs)

# Sort by re-ranker scores
reranked = sorted(zip(initial_results, scores), key=lambda x: -x[1])
final_results = [doc for doc, score in reranked[:5]]
```

Hosted rerankers (Cohere Rerank, Voyage rerank, Jina Reranker) and open-weight ones (BGE-reranker-v2-m3, Qwen3-Reranker, mxbai-rerank) are common production choices; an LLM can also rerank a short list at higher cost.

### Late Interaction (ColBERT)
ColBERT (Khattab and Zaharia, 2020) sits between bi-encoders and cross-encoders. It stores one embedding **per token** for each document and scores a query by summing, for each query token, its maximum similarity to any document token ("MaxSim"). Documents are still encoded offline, but matching happens at token level, which gives accuracy close to a cross-encoder. The cost is a much larger index; ColBERTv2 compresses token vectors to reduce it. The same idea applied to images of document pages is ColPali.

## Similarity Metrics

| Metric | Formula | Best For | Range |
|--------|---------|----------|-------|
| Cosine Similarity | A·B/(‖A‖·‖B‖) | Text embeddings (direction matters, length doesn't) | [-1, 1] |
| Euclidean (L2) Distance | √(Σ(A-B)²) | Models trained with L2 | [0, ∞) |
| Dot (Inner) Product | Σ(A·B) | Unit vectors (equals cosine) or models trained for it | Unbounded; [-1, 1] for unit vectors |

For unit-normalized vectors all three give the **same ranking**, because ‖A−B‖² = 2 − 2·cos(A, B). Use the metric the embedding model was trained with.

## Evaluation Metrics for Retrieval

- **Hit Rate@K**: Percentage of queries where at least one relevant document is in the top K
- **MRR** (Mean Reciprocal Rank): Average of reciprocal ranks of first relevant document
- **NDCG** (Normalized Discounted Cumulative Gain): Position-aware relevance scoring
- **MAP** (Mean Average Precision): Precision averaged across recall levels
- **Recall@K**: Fraction of relevant documents retrieved in top K
- **Precision@K**: Fraction of retrieved documents that are relevant

## Production Considerations

### Latency Budget
Illustrative numbers; measure your own:
```
User Query → Query Embedding (~10-30ms) → Hybrid Search (~20-50ms) → Re-ranking (~50-150ms)
           → LLM time to first token (~300-800ms) → full answer (seconds, streamed)
```
The LLM dominates, so stream the answer and keep the prompt short.

### Scaling
Count **chunks** (vectors), not documents: one document often becomes 10-20 chunks.

- **Small scale** (up to a few million vectors): single node: Chroma, FAISS, pgvector, or one Qdrant/Weaviate node
- **Medium scale** (tens of millions): replicated vector database, quantization to save memory
- **Large scale** (hundreds of millions+): sharded indexes, quantization plus rescoring, disk-based ANN indexes

### Caching Strategies
- **Query cache**: Cache frequent queries and their results (keyed by index version and user permissions, so updates and access control are respected)
- **Document cache**: Pre-fetch frequently retrieved documents
- **Embedding cache**: Cache query embeddings for repeated queries
