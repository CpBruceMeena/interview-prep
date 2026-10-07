# Embedding Models for RAG

## What are Embeddings?

Embeddings are dense vector representations of text that capture semantic meaning. In RAG systems, embeddings enable similarity search: finding documents that are conceptually related to the query even when they don't share exact keywords. Most RAG systems use **bi-encoders**: the query and each document are embedded separately, so document vectors can be computed once and indexed.

## Popular Embedding Models

Model names and leaderboard positions change every few months. The models below are well-known reference points; check the MTEB leaderboard and your own evaluation before choosing.

### 1. Sentence Transformers (all-MiniLM-L6-v2)
- **Embedding Dimension**: 384
- **Max input**: 256 word pieces (longer text is truncated)
- **Size**: ~22M parameters (~90 MB in float32)
- **Quality**: Decent general-purpose baseline, English only; well behind current models on retrieval
- **Speed**: Fast enough for CPU-only use

**Best for**: Development, prototyping, tests, resource-constrained environments (it is this repo's default)

### 2. OpenAI text-embedding-3-small
- **Embedding Dimension**: 1536 (can be shortened with the `dimensions` parameter)
- **Max input**: 8191 tokens
- **Quality**: Good, multilingual
- **Cost**: Low per-token API price (check current pricing)

**Best for**: Teams already on OpenAI who want a cheap hosted model

### 3. OpenAI text-embedding-3-large
- **Embedding Dimension**: 3072 (can be shortened with the `dimensions` parameter)
- **Quality**: Higher than 3-small, at a higher price
- **Note**: Both 3-series models are Matryoshka-trained (see below)

**Best for**: Higher-accuracy needs on the OpenAI stack

### 4. BGE (BAAI General Embedding) Series
- **English v1.5 models**: bge-small (384-dim), bge-base (768-dim), bge-large (1024-dim), 512-token max input; separate Chinese (`-zh`) variants exist
- **BGE-M3**: multilingual (100+ languages), up to 8192 tokens, and produces dense, sparse (lexical) and multi-vector (ColBERT-style) outputs from one model
- **Cost**: Free, open weights

**Best for**: Self-hosted production systems; BGE-M3 for multilingual or hybrid retrieval

### 5. E5 (EmbEddings from bidirEctional Encoder rEpresentations)
- **Models**: small (384), base (768), large (1024); multilingual-e5 variants
- **Training**: Contrastive pre-training on large weakly supervised pair data, then fine-tuning
- **Gotcha**: Inputs must be prefixed with `"query: "` or `"passage: "`; forgetting the prefixes hurts retrieval

**Best for**: Self-hosted retrieval, custom fine-tuning pipelines

### 6. Current Model Families (as of 2026)
- **Open weights**: Qwen3-Embedding (0.6B to 8B, multilingual, long input, instruction-aware), BGE-M3, GTE, Nomic Embed, Jina Embeddings, Google EmbeddingGemma (small, on-device), NVIDIA NV-Embed
- **Hosted APIs**: OpenAI text-embedding-3, Cohere Embed (v3, v4 with multimodal input), Voyage AI (general, code, finance, legal and multimodal models), Google Gemini Embedding
- Larger, LLM-based embedding models lead the leaderboards but cost more to run and produce larger vectors; small models are often good enough after fine-tuning

## Embedding Quality Comparison

Scores below are the **original MTEB English benchmark average (56 tasks)** as published around 2023-2024. MTEB has since been revised (MMTEB and new English and multilingual task sets), so these numbers are not comparable with today's leaderboard; use them only to see the relative gap between these older models.

| Model | MTEB avg (original English) | Dimension | Speed | Cost |
|-------|-----------|-----------|-------|------|
| all-MiniLM-L6-v2 | ~56.3 | 384 | Fastest | Free |
| BGE-base-en-v1.5 | ~63.6 | 768 | Fast | Free |
| E5-large-v2 | ~62.3 | 1024 | Moderate | Free |
| text-embedding-3-small | ~62.3 | 1536 | API | Low |
| text-embedding-3-large | ~64.6 | 3072 | API | Higher |

For RAG, look at the **retrieval** task scores (for example nDCG@10) in your language rather than the overall average, which also includes classification and clustering.

## Matryoshka Embeddings

Matryoshka Representation Learning (Kusupati et al., 2022) trains a model so that the **first N dimensions** of a vector are themselves a good embedding. You can truncate a 3072-dimensional vector to 1024, 512 or 256 dimensions (re-normalise after truncating) and keep most of the retrieval quality while cutting storage and search cost. A common pattern is a fast first-pass search with short vectors, then rescoring the top candidates with full vectors. Combined with int8 or binary quantization, this reduces index memory by an order of magnitude or more.

## Embedding Pipeline Best Practices

### Normalization
Normalize embeddings to unit length when searching by cosine similarity; then cosine similarity equals the dot product:
```python
import numpy as np
embedding = embedding / np.linalg.norm(embedding)

# sentence-transformers can do it for you:
vectors = model.encode(texts, normalize_embeddings=True)
```

### Batch Processing
Process documents in batches for efficiency:
```python
batch_size = 32
for i in range(0, len(documents), batch_size):
    batch = documents[i:i+batch_size]
    embeddings = model.encode(batch)
```

### Caching
Cache embeddings to avoid recomputation. Key the cache by the **model name and a hash of the text**, so changing models never returns stale vectors:
```python
import hashlib

embedding_cache = {}
key = (model_name, hashlib.sha256(text.encode()).hexdigest())
if key in embedding_cache:
    embedding = embedding_cache[key]
else:
    embedding = model.encode(text)
    embedding_cache[key] = embedding
```

### Query and Document Prefixes
Many retrieval models are asymmetric: queries and documents are encoded differently (E5 prefixes, BGE and Qwen3 query instructions). Recent sentence-transformers versions provide `encode_query()` and `encode_document()`, which apply a model's configured prompts.

### Multi-lingual Support
For multilingual corpora, use models specifically trained for it:
- **intfloat/multilingual-e5-large**
- **sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2**
- **BAAI/bge-m3**
- **Qwen3-Embedding** models

## Choosing the Right Embedding Model

Consider these factors:
1. **Quality on your data**: Build a small labelled query set and measure Recall@k; leaderboards are only a first filter
2. **Budget**: Free vs paid APIs vs self-hosted infrastructure
3. **Latency requirements**: CPU vs GPU inference, model size
4. **Language**: Single language vs multilingual
5. **Domain**: General vs specialized (legal, medical, code); consider fine-tuning
6. **Max input length**: Must exceed your chunk size in tokens
7. **Dimension impact**: Higher dimensions = more storage and slower search (Matryoshka truncation and quantization help)
8. **Switching cost**: Changing the model means re-embedding the entire corpus
