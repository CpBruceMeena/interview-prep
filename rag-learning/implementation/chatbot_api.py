"""FastAPI web server for the RAG chatbot."""

from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

from config import settings
from rag_pipeline import RAGPipeline

app = FastAPI(
    title="RAG Chatbot API",
    description="Retrieval-Augmented Generation chatbot with Gemma 4B via LM Studio",
    version="1.0.0",
)

pipeline: Optional[RAGPipeline] = None


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


class QueryResponse(BaseModel):
    answer: str
    sources: list
    latency_ms: float


class IndexResponse(BaseModel):
    status: str
    chunks_created: int
    message: str


class StatusResponse(BaseModel):
    status: str
    documents_indexed: int
    llm_connected: bool


@app.on_event("startup")
async def startup():
    """Initialize the RAG pipeline on server start."""
    global pipeline
    pipeline = RAGPipeline()
    print(f"🚀 RAG pipeline initialized with {settings.llm_model}")


@app.get("/health", response_model=StatusResponse)
async def health():
    """Health check endpoint."""
    global pipeline
    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    return StatusResponse(
        status="healthy",
        documents_indexed=pipeline.document_count,
        llm_connected=True,
    )


@app.post("/api/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Answer a question using RAG."""
    global pipeline
    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    result = pipeline.query(request.question, top_k=request.top_k)
    return QueryResponse(
        answer=result.get("answer", ""),
        sources=result.get("sources", []),
        latency_ms=result.get("latency_ms", 0),
    )


@app.post("/api/index", response_model=IndexResponse)
async def index_document(file: UploadFile = File(...)):
    """Upload and index a document."""
    global pipeline
    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Save uploaded file temporarily
    import tempfile
    import os
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        chunks_created = pipeline.index_document(tmp_path)
        return IndexResponse(
            status="success",
            chunks_created=chunks_created,
            message=f"Indexed {chunks_created} chunks from {file.filename}",
        )
    finally:
        os.unlink(tmp_path)


@app.post("/api/index-directory")
async def index_directory(path: str):
    """Index all documents in a directory."""
    global pipeline
    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    import os
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"Directory not found: {path}")
    chunks_created = pipeline.index_directory(path)
    return IndexResponse(
        status="success",
        chunks_created=chunks_created,
        message=f"Indexed {chunks_created} chunks from directory: {path}",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
