# RAG (Retrieval-Augmented Generation) Architecture Overview

## What is RAG?

Retrieval-Augmented Generation (RAG) is an architectural pattern that enhances Large Language Models (LLMs) by providing them with relevant, up-to-date context retrieved from a knowledge base before generating a response. Instead of relying solely on the model's training data, RAG combines retrieval and generation to produce more accurate, grounded, and timely answers.

## Core Components

### 1. Document Ingestion Pipeline
The ingestion pipeline processes documents and prepares them for retrieval:
- **Document Loading**: Support for multiple formats (PDF, HTML, Markdown, plain text)
- **Text Chunking**: Splits large documents into manageable pieces with configurable size and overlap
- **Embedding Generation**: Converts text chunks into dense vector representations using models like Sentence Transformers
- **Vector Storage**: Stores embeddings in a vector database (ChromaDB, FAISS, Pinecone) for efficient similarity search

### 2. Retrieval Pipeline
At query time, the retrieval pipeline finds the most relevant chunks:
- **Query Embedding**: Converts the user's question into a vector using the same embedding model
- **Similarity Search**: Finds the approximate nearest neighbors (ANN, e.g. an HNSW index) in the vector space, usually by cosine similarity; often combined with keyword (BM25) search in a hybrid setup
- **Re-ranking** (optional): Applies cross-encoder models to refine the initial results
- **Context Assembly**: Formats retrieved chunks into a coherent context with source attributions

### 3. Generation Pipeline
The generation pipeline produces the final answer:
- **Prompt Construction**: Builds a system prompt with the retrieved context and the user's question
- **LLM Generation**: Sends the prompt to the LLM (e.g., a small Gemma or Qwen model served locally by LM Studio)
- **Response Delivery**: Returns the answer along with source citations

## Key Benefits

1. **Factual Accuracy**: Grounds responses in actual documents, reducing (not eliminating) hallucinations
2. **Up-to-date Knowledge**: Knowledge base can be updated without retraining the model
3. **Transparency**: Sources can be cited, enabling users to verify claims
4. **Cost Efficiency**: Smaller LLMs can be used effectively when given good context
5. **Domain Adaptation**: Quickly adapt to new domains by indexing relevant documents

## Architecture Patterns

The Naive / Advanced / Modular taxonomy comes from the survey by Gao et al. (2023), "Retrieval-Augmented Generation for Large Language Models: A Survey".

### Naive RAG (Basic)
- Simple retrieve-then-generate flow
- One-shot retrieval before generation
- Suitable for simple Q&A over small document sets

### Advanced RAG
- Pre-retrieval optimization (query rewriting, query expansion)
- Post-retrieval optimization (re-ranking, filtering)
- Context compression to fit more relevant information
- Suitable for production systems with larger knowledge bases

### Modular RAG
- Composable components that can be mixed and matched
- Support for multiple retrieval strategies (sparse, dense, hybrid)
- Iterative retrieval and generation loops
- Suitable for complex reasoning tasks

### Graph RAG
- An LLM extracts entities and relationships into a knowledge graph at indexing time
- Communities in the graph are summarised ahead of time (Microsoft GraphRAG, 2024)
- Answers "global" questions about a whole corpus and multi-hop relationship questions
- Indexing is expensive and the graph must be kept up to date

### Agentic RAG
- The LLM decides whether to retrieve, what to search for, and when it has enough evidence
- Retrieval is one tool among others (SQL, APIs, web search), called in a loop
- Handles multi-step questions at the cost of latency, cost and predictability
- Needs limits on steps and tokens, and evaluation of the whole trajectory
