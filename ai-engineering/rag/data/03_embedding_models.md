# Embedding Models for RAG

## What are Embeddings?

Embeddings are dense vector representations of text that capture semantic meaning. In RAG systems, embeddings enable similarity search - finding documents that are conceptually related to the query even when they don't share exact keywords.

## Popular Embedding Models

### 1. Sentence Transformers (all-MiniLM-L6-v2)
- **Embedding Dimension**: 384
- **Context Length**: 256 tokens
- **Speed**: ~10,000 sentences/second on CPU
- **Quality**: Good general-purpose embeddings
- **Size**: ~22 MB

**Best for**: Development, prototyping, resource-constrained environments

### 2. OpenAI text-embedding-3-small
- **Embedding Dimension**: 1536
- **Context Length**: 8192 tokens
- **Speed**: API-dependent
- **Quality**: Excellent, with multilingual support
- **Cost**: $0.002 per 1K tokens

**Best for**: Production systems, when quality matters more than cost

### 3. OpenAI text-embedding-3-large
- **Embedding Dimension**: 3072
- **Quality**: Best-in-class
- **Cost**: $0.013 per 1K tokens

**Best for**: High-accuracy requirements, legal/medical domains

### 4. BGE (BAAI General Embedding) Series
- **Models**: BGE-small (384-dim), BGE-base (768-dim), BGE-large (1024-dim)
- **Context Length**: 512 tokens
- **Quality**: Competitive with OpenAI on MTEB benchmark
- **Cost**: Free, open-source

**Best for**: Self-hosted production systems, Chinese + English text

### 5. E5 (EmbEddings from bidirEctional Encoder rEpresentations)
- **Models**: small (384), base (768), large (1024)
- **Quality**: Strong MTEB performance
- **Training**: Contrastive learning on diverse datasets

**Best for**: Research, custom fine-tuning pipelines

## Embedding Quality Comparison

| Model | MTEB Score | Dimension | Speed | Cost |
|-------|-----------|-----------|-------|------|
| all-MiniLM-L6-v2 | 56.3 | 384 | Fastest | Free |
| BGE-base-en-v1.5 | 63.6 | 768 | Fast | Free |
| E5-large-v2 | 62.3 | 1024 | Moderate | Free |
| text-embedding-3-small | 62.3 | 1536 | API | Low |
| text-embedding-3-large | 64.6 | 3072 | API | High |

## Embedding Pipeline Best Practices

### Normalization
Always normalize embeddings to unit length for cosine similarity search:
```python
import numpy as np
embedding = embedding / np.linalg.norm(embedding)
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
Cache embeddings to avoid recomputation:
```python
# Simple cache using dictionary
embedding_cache = {}
if text in embedding_cache:
    embedding = embedding_cache[text]
else:
    embedding = model.encode(text)
    embedding_cache[text] = embedding
```

### Multi-lingual Support
For multilingual corpora, use models specifically trained for it:
- **intfloat/multilingual-e5-large**
- **sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2**
- **BAAI/bge-m3**

## Choosing the Right Embedding Model

Consider these factors:
1. **Budget**: Free vs paid APIs vs self-hosted infrastructure
2. **Latency requirements**: CPU vs GPU inference
3. **Language**: Single language vs multilingual
4. **Domain**: General vs specialized (legal, medical, code)
5. **Scale**: Millions of documents vs thousands
6. **Dimension impact**: Higher dimensions = more storage + slower search
