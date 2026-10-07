# Text Chunking Strategies for RAG

## Why Chunking Matters

Chunking is the process of splitting documents into smaller pieces before embedding and indexing. The quality of chunking directly impacts retrieval accuracy, context relevance, and eventually the quality of generated responses.

## Chunking Methods

### 1. Fixed-Size Chunking
The simplest approach: split text into chunks of a fixed number of characters or tokens.

```
Example: chunk_size=500, chunk_overlap=50
Document: [0-500][450-950][900-1400]...
```

**Pros**:
- Simple to implement
- Predictable number of chunks and token budget per chunk

**Cons**:
- May split sentences or paragraphs mid-stream
- Loses semantic boundaries

**Best for**: General-purpose documents with uniform content

### 2. Recursive Character Text Splitting
Splits text recursively using a hierarchy of separators.

```python
separators = ["\n\n", "\n", ".", " ", ""]
```

The splitter tries each separator in order, working from largest to smallest semantic units.

**Pros**:
- Respects paragraph and sentence boundaries
- Produces more coherent chunks
- Configurable separator hierarchy

**Cons**:
- Slightly more complex
- Chunk sizes may vary

**Best for**: Most general text documents, articles, documentation

### 3. Semantic Chunking
Uses sentence embeddings to detect topic boundaries.

```python
sentences = split_into_sentences(text)
embeddings = embed_model.encode(sentences)
boundaries = detect_topic_shifts(embeddings)
chunks = group_by_boundaries(sentences, boundaries)
```

**Pros**:
- Topic-aware chunking
- Highly coherent chunks
- Better retrieval relevance

**Cons**:
- Computationally expensive
- Requires embedding at chunking time
- Adds latency to ingestion
- Gains over good structural splitting are inconsistent; measure before adopting

**Best for**: Long documents with multiple topics, research papers

### 4. Document Structure-Based Chunking
Leverages document structure (headings, sections, lists).

```markdown
# Section 1
Content here...

## Subsection 1.1
More content...

## Subsection 1.2
Even more content...
```

**Pros**:
- Naturally aligned with document organization
- Preserves hierarchical context
- Excellent for structured documents

**Cons**:
- Format-specific (markdown, HTML, LaTeX)
- Requires structure parsing logic

**Best for**: Documentation, wikis, manuals, web pages

### 5. Context-Enriched Chunking
A chunk embedded on its own loses its surrounding context ("revenue grew 3%": whose revenue?). Three ways to put the context back:

- **Contextual chunk headers**: prepend the document title and heading path to every chunk. Free and effective.
- **Contextual retrieval** (Anthropic, September 2024): an LLM writes a short (50-100 token) description situating each chunk within its document; it is prepended before embedding and before BM25 indexing. Anthropic reported 35% fewer top-20 retrieval failures with contextual embeddings and 49% with contextual embeddings plus contextual BM25 (67% when a reranker is added). Cost: one LLM call per chunk, reduced by prompt caching.
- **Late chunking** (Jina AI, 2024): run a long-context embedding model over the whole document first, then average the token embeddings inside each chunk's span. Every chunk vector is informed by the full document, with no LLM calls. Requires an embedding model with a long context window that exposes token-level outputs.

## Chunk Size Considerations

Sizes below are in tokens. Note that many splitters (for example LangChain's `RecursiveCharacterTextSplitter`) count characters by default; roughly 4 characters per English token.

| Size | Token Range | Use Case |
|------|------------|----------|
| Small | 128-256 | Precise facts, Q&A over specific details |
| Medium | 384-512 | General purpose, balanced approach |
| Large | 768-1024 | Narrative content, summaries |
| X-Large | 1536+ | Document-level retrieval, long-form content |

## Chunk Overlap Strategies

These are common starting points, not rules:

- **10-20% overlap**: Typical default for prose
- **Higher overlap**: Dense text where facts straddle boundaries (costs index size and returns near-duplicate chunks)
- **No overlap**: Structure-based chunks (whole sections), or when storage is tight

## Best Practices

1. **Stay under the embedding model's max input length**: longer text is silently truncated
2. **Budget the prompt**: top-k chunks × chunk size must fit the LLM context with room for the answer
3. **Align with document structure**: Use headings as natural boundaries; never split inside tables or code blocks
4. **Include metadata**: Store source, section, and position for each chunk
5. **Test different strategies**: Measure Recall@k on a labelled query set for your domain
6. **Consider hybrid approaches**: Use different strategies for different document types
