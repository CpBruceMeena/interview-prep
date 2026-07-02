"""Main RAG pipeline — orchestrates the complete retrieval-augmented generation flow."""

import time
from typing import List, Optional, Dict

from config import settings
from document_loader import DocumentLoader, TextFileLoader, Document
from embedding_service import EmbeddingService, SentenceTransformerEmbedding
from vector_store import VectorStore, ChromaVectorStore, Chunk
from retrieval_engine import RetrievalEngine
from llm_service import LLMService, LMStudioClient

SYSTEM_PROMPT = """You are a helpful assistant. Answer the user's question based ONLY on the provided context below.

Rules:
1. If the context contains the answer, provide it clearly and concisely.
2. If the context does NOT contain enough information, say "I don't have enough information to answer that question."
3. Do NOT make up facts or use information outside the provided context.
4. Cite the source document names when possible.

Context:
{context}

Question: {question}

Answer:"""


class RAGPipeline:
    """Facade pattern — coordinates all RAG components."""

    def __init__(self,
                 embedder: Optional[EmbeddingService] = None,
                 store: Optional[VectorStore] = None,
                 llm: Optional[LLMService] = None,
                 loader: Optional[DocumentLoader] = None):
        self._embedder = embedder or SentenceTransformerEmbedding()
        self._store = store or ChromaVectorStore()
        self._retriever = RetrievalEngine(self._embedder, self._store)
        self._llm = llm or LMStudioClient()
        self._loader = loader or TextFileLoader()

    def index_document(self, file_path: str) -> int:
        """Load, chunk, embed, and store a single document."""
        docs = self._loader.load(file_path)
        chunks = self._chunk_documents(docs)
        self._embed_chunks(chunks)
        self._store.add_chunks(chunks)
        return len(chunks)

    def index_directory(self, directory: str) -> int:
        """Index all documents in a directory. Returns total chunks created."""
        docs = self._loader.load_directory(directory)
        chunks = self._chunk_documents(docs)
        self._embed_chunks(chunks)
        self._store.add_chunks(chunks)
        print(f"✅ Indexed {len(chunks)} chunks from {len(docs)} documents")
        return len(chunks)

    def query(self, question: str,
              top_k: Optional[int] = None) -> Dict:
        """Complete RAG query: retrieve context → generate answer."""
        start = time.time()

        # 1. Retrieve relevant context
        context = self._retriever.retrieve_context(question, top_k=top_k)
        if not context:
            elapsed = (time.time() - start) * 1000
            return {
                "answer": "I don't have enough information to answer that question.",
                "sources": [],
                "latency_ms": round(elapsed, 2),
            }

        # 2. Build prompt with context
        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    context=context, question=question
                )
            },
            {
                "role": "user",
                "content": question
            }
        ]

        # 3. Generate response
        answer = self._llm.generate(messages)
        if not answer:
            elapsed = (time.time() - start) * 1000
            return {
                "answer": "I'm sorry, the language model is currently unavailable.",
                "error": True,
                "latency_ms": round(elapsed, 2),
            }

        elapsed = (time.time() - start) * 1000

        # 4. Extract sources
        results = self._retriever.retrieve(question, top_k=top_k)
        sources = [
            {
                "text": r.chunk.text[:200],
                "score": round(r.score, 4),
                "source": r.chunk.metadata.get("source", "unknown"),
            }
            for r in results[:3]
        ]

        return {
            "answer": answer,
            "sources": sources,
            "latency_ms": round(elapsed, 2),
        }

    def _chunk_documents(self, docs: List[Document]) -> List[Chunk]:
        """Split documents into chunks using recursive text splitting."""
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", ".", " ", ""],
        )

        chunks = []
        for doc in docs:
            split_texts = splitter.split_text(doc.content)
            for i, text in enumerate(split_texts):
                chunk = Chunk(
                    text=text,
                    metadata={
                        **doc.metadata,
                        "chunk_index": i,
                    }
                )
                chunks.append(chunk)
        return chunks

    def _embed_chunks(self, chunks: List[Chunk]) -> None:
        """Embed all chunks in batch."""
        texts = [c.text for c in chunks]
        embeddings = self._embedder.embed_batch(texts)
        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding

    @property
    def document_count(self) -> int:
        return self._store.count()
