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
- **Similarity Search**: Finds the nearest neighbors in the vector space using cosine similarity or Euclidean distance
- **Re-ranking** (optional): Applies cross-encoder models to refine the initial results
- **Context Assembly**: Formats retrieved chunks into a coherent context with source attributions

### 3. Generation Pipeline
The generation pipeline produces the final answer:
- **Prompt Construction**: Builds a system prompt with the retrieved context and the user's question
- **LLM Generation**: Sends the prompt to the LLM (e.g., Gemma 4B via LM Studio)
- **Response Delivery**: Returns the answer along with source citations

## Key Benefits

1. **Factual Accuracy**: Grounds responses in actual documents, reducing hallucinations
2. **Up-to-date Knowledge**: Knowledge base can be updated without retraining the model
3. **Transparency**: Sources can be cited, enabling users to verify claims
4. **Cost Efficiency**: Smaller LLMs can be used effectively when given good context
5. **Domain Adaptation**: Quickly adapt to new domains by indexing relevant documents

## Architecture Patterns

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
