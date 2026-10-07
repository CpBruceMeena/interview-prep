"""
RAG pipeline exposed as an MCP server.
Combines document indexing, retrieval, and generation through the MCP protocol.

Run (from ai-engineering/mcp):
    python -m servers.rag_server                      # stdio (default; what desktop clients launch)
    MCP_TRANSPORT=streamable-http python -m servers.rag_server   # HTTP at http://127.0.0.1:$RAG_PORT/mcp

This server wraps the RAG implementation in ai-engineering/rag/implementation/
to give AI agents knowledge-retrieval tools. Written for the Python SDK v2
(`mcp>=2`, `MCPServer`).

Environment variables:
- MCP_TRANSPORT: "stdio" (default) or "streamable-http". The old HTTP+SSE
  transport is deprecated in the spec and not offered here.
- RAG_PORT: HTTP port for Streamable HTTP (default: 8000)
- USE_MOCK_LLM: "true" to answer without a running LM Studio
- RAG_ALLOWED_ROOT: the only directory `index_document` may read from
  (default: ai-engineering/rag/data). Without a root, a prompt-injected model
  could ask the server to index (and then reveal) ~/.ssh or /etc.
- LLM settings (model name, LM Studio URL, ...) come from rag/implementation/config.py.
"""

import contextlib
import logging
import os
import sys
import time
from typing import Dict

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# ── Add implementation to Python path ──
_IMPL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "rag", "implementation")
)
if _IMPL_DIR not in sys.path:
    sys.path.insert(0, _IMPL_DIR)

from config import settings
from rag_pipeline import RAGPipeline
from embedding_service import SentenceTransformerEmbedding
from vector_store import ChromaVectorStore
from llm_service import LLMService, LMStudioClient, MockLLMService
from document_loader import TextFileLoader

# Configure logging (stderr; stdout is reserved for the stdio transport)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mcp.rag_server")

# ── Configuration ──
RAG_PORT = int(os.environ.get("RAG_PORT", "8000"))
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
RAG_ALLOWED_ROOT = os.path.realpath(os.environ.get(
    "RAG_ALLOWED_ROOT",
    os.path.join(os.path.dirname(__file__), "..", "..", "rag", "data"),
))
USE_MOCK_LLM = os.environ.get("USE_MOCK_LLM", "false").lower() == "true"

# ── Initialize MCP Server ──
mcp = MCPServer("RAGPipeline")

# ── Initialize RAG Pipeline ──
# Use MockLLM by default so the server can start without LM Studio
# Set USE_MOCK_LLM=false and ensure LM Studio is running for real responses
logger.info("Initializing RAG pipeline (embedding_model=%s, mock_llm=%s)",
             settings.embedding_model, USE_MOCK_LLM)

llm: LLMService
if USE_MOCK_LLM:
    llm = MockLLMService(
        response="I am a mock LLM. Set USE_MOCK_LLM=false and start LM Studio for real responses."
    )
else:
    llm = LMStudioClient()

# The RAG library prints progress to stdout; on stdio that would corrupt the
# JSON-RPC stream, so route any such output to stderr.
with contextlib.redirect_stdout(sys.stderr):
    pipeline = RAGPipeline(
        embedder=SentenceTransformerEmbedding(),
        store=ChromaVectorStore(),
        llm=llm,
        loader=TextFileLoader(),
    )

logger.info("RAG pipeline initialized with %d documents", pipeline.document_count)


# ── Helpers ──

def format_sources(sources: list) -> str:
    """Format source citations as a readable string."""
    if not sources:
        return ""
    output = "\n\n**Sources:**\n"
    for i, src in enumerate(sources, 1):
        source_name = src.get("source", "unknown").split("/")[-1]
        score = src.get("score", 0)
        output += f"{i}. [{source_name}] (relevance: {score:.2f})\n"
    return output


def format_chunks(results: list, max_chars: int = 500) -> str:
    """Format retrieved chunks (SearchResult: .chunk + .score) with metadata."""
    if not results:
        return "No relevant documents found."

    output = f"Retrieved {len(results)} relevant chunks:\n\n"
    for i, result in enumerate(results, 1):
        chunk, score = result.chunk, result.score
        source = chunk.metadata.get("source", "unknown").split("/")[-1]
        text = chunk.text[:max_chars]

        output += f"--- [{i}] {source} (score: {score:.4f}) ---\n"
        output += f"{text}\n"
        if len(chunk.text) > max_chars:
            output += f"...[truncated, {len(chunk.text)} total chars]\n"
        output += "\n"

    return output


# ── Tools ──


@mcp.tool()
def rag_query(question: str, top_k: int = 5) -> str:
    """Complete RAG query: retrieve context and generate an answer.

    Best for simple Q&A where you want a single, grounded answer.
    Includes source citations automatically.

    Args:
        question: The user's question to answer
        top_k: Number of document chunks to retrieve (1-10, default: 5)
    """
    logger.info("RAG query: %.100s (top_k=%d)", question, top_k)

    start = time.time()
    with contextlib.redirect_stdout(sys.stderr):
        result = pipeline.query(question, top_k=max(1, min(top_k, 10)))
    elapsed = time.time() - start

    answer = result.get("answer", "No answer generated.")
    sources = result.get("sources", [])

    output = f"**Answer:** {answer}\n"
    output += f"*Generated in {elapsed:.2f}s*"
    output += format_sources(sources)

    return output


@mcp.tool()
def retrieve(question: str, top_k: int = 5) -> str:
    """Retrieve relevant document chunks WITHOUT generating an answer.

    Use this when you want to inspect the source material directly,
    or when you need more detailed context than the RAG query provides.
    Returns full text of each chunk with relevance scores.

    Args:
        question: The search query
        top_k: Number of chunks to retrieve (1-10, default: 5)
    """
    logger.info("Retrieval: %.100s (top_k=%d)", question, top_k)

    # Access the retriever directly via the pipeline
    results = pipeline._retriever.retrieve(question, top_k=max(1, min(top_k, 10)))
    return format_chunks(results)


@mcp.tool()
def index_document(file_path: str) -> str:
    """Index a file or directory into the RAG knowledge base.

    Supported formats: .md, .txt, .pdf, .html
    The document is parsed, chunked into segments, embedded into vectors,
    and stored in the vector database for future queries.

    Args:
        file_path: Path to a file or directory under the server's allowed root
    """
    # realpath resolves "..", and symlinks, before the containment check.
    real = os.path.realpath(file_path)
    if os.path.commonpath([real, RAG_ALLOWED_ROOT]) != RAG_ALLOWED_ROOT:
        raise ToolError(f"Path '{file_path}' is outside the allowed root '{RAG_ALLOWED_ROOT}'.")
    if not os.path.exists(real):
        raise ToolError(f"Path '{file_path}' does not exist.")

    start = time.time()

    try:
        with contextlib.redirect_stdout(sys.stderr):
            if os.path.isdir(real):
                chunk_count = pipeline.index_directory(real)
                source_type = "directory"
            else:
                chunk_count = pipeline.index_document(real)
                source_type = "file"

        elapsed = time.time() - start
        total_docs = pipeline.document_count

        logger.info(
            "Indexed %d chunks from %s '%s' in %.2fs",
            chunk_count, source_type, file_path, elapsed
        )

        return (
            f"✅ Indexed **{chunk_count} chunks** from {source_type} "
            f"`{file_path}`\n"
            f"⏱️  Time: {elapsed:.2f}s\n"
            f"📊 Total documents in store: **{total_docs}**"
        )

    except Exception as e:
        logger.exception("Indexing failed")
        raise ToolError(f"Indexing failed: {type(e).__name__}") from e


# ── Resources ──


@mcp.resource("rag://status")
def rag_status() -> str:
    """Get the current status of the RAG system.

    Returns document count, embedding model, chunk settings, etc.
    Useful for debugging and monitoring.
    """
    return (
        f"**RAG Pipeline Status**\n\n"
        f"- **Document count:** {pipeline.document_count}\n"
        f"- **Embedding model:** {settings.embedding_model}\n"
        f"- **Chunk size:** {settings.chunk_size}\n"
        f"- **Chunk overlap:** {settings.chunk_overlap}\n"
        f"- **Vector store type:** {settings.vector_store}\n"
        f"- **Top-K default:** {settings.top_k}\n"
        f"- **Similarity threshold:** {settings.similarity_threshold}\n"
        f"- **LLM provider:** {settings.llm_provider}\n"
        f"- **Mock LLM mode:** {USE_MOCK_LLM}"
    )


@mcp.resource("rag://documents")
def list_documents() -> str:
    """List all indexed documents with chunk counts.

    Useful for understanding what knowledge is available in the RAG system.
    """
    # Get all documents from the store metadata
    try:
        # ChromaDB stores metadata per chunk; we aggregate by source
        all_chunks = pipeline._store._collection.get(include=["metadatas"])
        if not all_chunks or not all_chunks.get("ids"):
            return "No documents indexed yet."

        # Aggregate by source file
        doc_map: Dict[str, dict] = {}
        for i, chunk_id in enumerate(all_chunks["ids"]):
            meta = all_chunks["metadatas"][i] if all_chunks["metadatas"] else {}
            source = meta.get("source", "unknown")
            if source not in doc_map:
                doc_map[source] = {"chunks": 0}
            doc_map[source]["chunks"] += 1

        output = "**Indexed Documents:**\n\n"
        output += "| Source | Chunks |\n"
        output += "|--------|--------|\n"
        for source, info in sorted(doc_map.items()):
            name = source.split("/")[-1]
            output += f"| {name} | {info['chunks']} |\n"

        return output

    except Exception as e:
        return f"Error listing documents: {e}"


# ── Prompts ──


@mcp.prompt()
def rag_debug(question: str, answer: str) -> str:
    """Debug a RAG response by reviewing context and output."""
    return f"""Analyze the following RAG query and response for quality:

Question: {question}
Answer: {answer}

Evaluate:
1. Does the answer accurately address the question?
2. Are there any hallucinations (claims not supported by retrieved context)?
3. What could be improved in the retrieval or generation?"""


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if MCP_TRANSPORT == "streamable-http":
        logger.info("Starting RAG MCP Server: Streamable HTTP at http://127.0.0.1:%d/mcp", RAG_PORT)
        # Binds to localhost by default. Exposing it beyond that needs auth
        # (OAuth bearer tokens) and Origin checks; see 04_MCP_PRODUCTION_ARCHITECTURE.md.
        mcp.run(transport="streamable-http", host="127.0.0.1", port=RAG_PORT)
    else:
        logger.info("Starting RAG MCP Server (stdio), %d chunks indexed", pipeline.document_count)
        mcp.run(transport="stdio")
