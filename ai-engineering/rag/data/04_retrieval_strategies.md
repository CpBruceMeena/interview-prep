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
- Needs a vector database
- Can miss exact keyword matches

### 2. Sparse Retrieval (Keyword/BM25)
Uses traditional information retrieval based on term frequency.

```python
from rank_bm25 import BM25Okapi
tokenized_docs = [doc.split() for doc in documents]
bm25 = BM25Okapi(tokenized_docs)
results = bm25.get_top_n(query.split(), documents, n=5)
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

### 3. Hybrid Retrieval
Combines dense and sparse retrieval for the best of both worlds.

```python
dense_results = vector_store.search(query_embedding, top_k=10)
sparse_results = bm25_search(query, top_k=10)

# Reciprocal Rank Fusion (RRF)
combined = {}
for rank, (doc_id, score) in enumerate(dense_results):
    combined[doc_id] = 1 / (60 + rank)
for rank, (doc_id, score) in enumerate(sparse_results):
    combined[doc_id] = combined.get(doc_id, 0) + 1 / (60 + rank)

final_results = sorted(combined.items(), key=lambda x: -x[1])
```

**Pros**:
- Best overall retrieval quality
- Robust to different query types
- Complements weaknesses of each approach

**Cons**:
- More complex infrastructure
- Higher latency (two queries)
- Requires normalization between scores

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

Re-ranking refines initial retrieval results using a more sophisticated model.

```python
from sentence_transformers import CrossEncoder

# Initial retrieval (fast, lightweight)
initial_results = dense_retriever.retrieve(query, top_k=20)

# Re-ranking (slower but more accurate)
cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
pairs = [[query, doc] for doc in initial_results]
scores = cross_encoder.predict(pairs)

# Sort by re-ranker scores
reranked = sorted(zip(initial_results, scores), key=lambda x: -x[1])
final_results = [doc for doc, score in reranked[:5]]
```

## Similarity Metrics

| Metric | Formula | Best For | Range |
|--------|---------|----------|-------|
| Cosine Similarity | A·B/(‖A‖·‖B‖) | Normalized embeddings | [-1, 1] |
| Euclidean Distance | √(Σ(A-B)²) | Unnormalized vectors | [0, ∞) |
| Dot Product | Σ(A*B) | Unit vectors | [-d, d] |
| Inner Product | Same as dot | Optimized databases | Varies |

## Evaluation Metrics for Retrieval

- **Hit Rate**: Percentage of queries where at least one relevant document is retrieved
- **MRR** (Mean Reciprocal Rank): Average of reciprocal ranks of first relevant document
- **NDCG** (Normalized Discounted Cumulative Gain): Position-aware relevance scoring
- **MAP** (Mean Average Precision): Precision averaged across recall levels
- **Recall@K**: Fraction of relevant documents retrieved in top K
- **Precision@K**: Fraction of retrieved documents that are relevant

## Production Considerations

### Latency Budget
```
User Query → Query Embedding (10ms) → Vector Search (20ms) → Re-ranking (50ms) → Generation (500ms)
Total: ~580ms target
```

### Scaling
- **Small scale** (<100K docs): Single-node ChromaDB or FAISS
- **Medium scale** (1M-10M docs): Distributed vector databases (Pinecone, Qdrant, Weaviate)
- **Large scale** (100M+ docs): Sharded + partitioned setups with tiered caching

### Caching Strategies
- **Query cache**: Cache frequent queries and their results
- **Document cache**: Pre-fetch frequently retrieved documents
- **Embedding cache**: Cache query embeddings for repeated queries
