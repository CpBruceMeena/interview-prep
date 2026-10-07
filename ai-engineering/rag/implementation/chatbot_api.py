"""FastAPI web server for the RAG chatbot."""

import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from config import settings
from document_loader import is_supported
from rag_pipeline import RAGPipeline

pipeline: Optional[RAGPipeline] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the pipeline once at startup (replaces deprecated @app.on_event)."""
    global pipeline
    pipeline = RAGPipeline()
    yield
    pipeline = None


app = FastAPI(
    title="RAG Chatbot API",
    description="Retrieval-Augmented Generation chatbot backed by a local LLM via LM Studio",
    version="1.1.0",
    lifespan=lifespan,
)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)


class QueryResponse(BaseModel):
    answer: str
    sources: list
    latency_ms: float


class IndexResponse(BaseModel):
    status: str
    chunks_created: int
    message: str


class IndexDirectoryRequest(BaseModel):
    # Relative to settings.data_directory; absolute paths are rejected.
    path: str = "."


class StatusResponse(BaseModel):
    status: str
    documents_indexed: int  # number of chunks in the store
    llm_connected: bool


def _require_pipeline() -> RAGPipeline:
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    return pipeline


# Handlers that call the pipeline are plain `def` or use run_in_threadpool:
# embedding and the LLM HTTP call are blocking, and running them directly in an
# `async def` would stall the event loop for every other request.

@app.get("/health", response_model=StatusResponse)
def health():
    p = _require_pipeline()
    return StatusResponse(
        status="healthy",
        documents_indexed=p.document_count,
        llm_connected=p._llm.is_available(),
    )


@app.post("/api/query", response_model=QueryResponse)
def query(request: QueryRequest):
    """Answer a question using RAG."""
    p = _require_pipeline()
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    result = p.query(request.question, top_k=request.top_k)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["answer"])
    return QueryResponse(
        answer=result["answer"],
        sources=result.get("sources", []),
        latency_ms=result.get("latency_ms", 0),
    )


@app.post("/api/index", response_model=IndexResponse)
async def index_document(file: UploadFile = File(...)):
    """Upload and index a document (.pdf, .txt, .md, .html)."""
    p = _require_pipeline()
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    filename = Path(file.filename).name  # never trust client paths
    suffix = Path(filename).suffix.lower()
    if not is_supported(suffix):
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        chunks_created = await run_in_threadpool(
            p.index_document, tmp_path, source_name=filename
        )
    finally:
        os.unlink(tmp_path)

    return IndexResponse(
        status="success",
        chunks_created=chunks_created,
        message=f"Indexed {chunks_created} chunks from {filename}",
    )


@app.post("/api/index-directory", response_model=IndexResponse)
def index_directory(request: IndexDirectoryRequest):
    """Index a directory on the server, confined to settings.data_directory.

    Letting a client name an arbitrary server path would let it read (and then
    query back) any file the process can open.
    """
    p = _require_pipeline()
    root = Path(settings.data_directory).resolve()
    target = (root / request.path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Path must be inside the data directory")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {request.path}")

    chunks_created = p.index_directory(str(target))
    return IndexResponse(
        status="success",
        chunks_created=chunks_created,
        message=f"Indexed {chunks_created} chunks from {request.path}",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
