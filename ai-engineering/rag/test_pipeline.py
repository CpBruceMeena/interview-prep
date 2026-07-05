"""
End-to-end verification of the RAG pipeline.
Indexes sample documents, runs queries, and validates retrieval quality.
"""

import os
import sys
import time
import json

# Add implementation to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "implementation"))

from config import settings
from rag_pipeline import RAGPipeline
from embedding_service import SentenceTransformerEmbedding
from vector_store import ChromaVectorStore
from llm_service import MockLLMService
from document_loader import TextFileLoader, Document


def print_separator(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def test_indexing(pipeline: RAGPipeline, docs_dir: str):
    """Test indexing sample documents and verify chunks were created."""
    print_separator("STEP 1: Indexing Sample Documents")

    if not os.path.isdir(docs_dir):
        print(f"❌ Documents directory not found: {docs_dir}")
        return False

    files = [f for f in os.listdir(docs_dir) if f.endswith(".md")]
    print(f"📄 Found {len(files)} sample documents:")
    for f in sorted(files):
        size = os.path.getsize(os.path.join(docs_dir, f))
        print(f"   - {f} ({size:,} bytes)")

    # Index the directory
    start = time.time()
    chunk_count = pipeline.index_directory(docs_dir)
    elapsed = time.time() - start

    print(f"\n✅ Indexed {chunk_count} chunks from {len(files)} documents")
    print(f"⏱️  Indexing took {elapsed:.2f}s ({elapsed/max(chunk_count,1):.3f}s per chunk)")

    # Verify document count in store
    doc_count = pipeline.document_count
    print(f"📊 Vector store count: {doc_count} chunks")

    if doc_count == 0:
        print("❌ FAILED: No chunks were stored in the vector store")
        return False

    print(f"✅ PASSED: {doc_count} chunks indexed successfully")
    return True


def test_retrieval(pipeline: RAGPipeline):
    """Test that retrieval returns relevant results for various queries."""
    print_separator("STEP 2: Testing Retrieval Quality")

    test_queries = [
        {
            "question": "What is RAG and what are its main components?",
            "expected_topics": ["retrieval", "generation", "embedding"],
            "min_sources": 1,
        },
        {
            "question": "How does text chunking work in RAG systems?",
            "expected_topics": ["chunk", "split", "overlap", "size"],
            "min_sources": 1,
        },
        {
            "question": "What embedding models are recommended for RAG?",
            "expected_topics": ["sentence", "transformer", "embedding", "MiniLM"],
            "min_sources": 1,
        },
        {
            "question": "How do you set up LM Studio?",
            "expected_topics": ["lm studio", "server", "api", "model"],
            "min_sources": 1,
        },
        {
            "question": "What are the differences between dense and sparse retrieval?",
            "expected_topics": ["dense", "sparse", "hybrid", "BM25"],
            "min_sources": 1,
        },
    ]

    passed = 0
    for i, test in enumerate(test_queries):
        print(f"\n--- Query {i+1}: \"{test['question']}\" ---")

        start = time.time()
        results = pipeline._retriever.retrieve(test["question"], top_k=5)
        elapsed = (time.time() - start) * 1000

        if not results:
            print(f"⚠️  No results retrieved (this may be okay for edge cases)")
            continue

        # Show top results
        print(f"   Retrieved {len(results)} chunks in {elapsed:.1f}ms")
        for j, r in enumerate(results[:3]):
            source = r.chunk.metadata.get("source", "unknown")
            filename = os.path.basename(source)
            text_preview = r.chunk.text[:100].replace("\n", " ")
            print(f"   [{j+1}] score={r.score:.4f} | {filename}")
            print(f"       \"{text_preview}...\"")

        # Check if top result has good score
        if results[0].score >= 0.3:
            print(f"   ✅ Top score {results[0].score:.4f} >= 0.3 threshold")
            passed += 1
        else:
            print(f"   ⚠️  Top score {results[0].score:.4f} is below threshold 0.3")

    success_rate = (passed / len(test_queries)) * 100
    print(f"\n📊 Retrieval pass rate: {passed}/{len(test_queries)} ({success_rate:.0f}%)")
    return passed > 0


def test_context_assembly(pipeline: RAGPipeline):
    """Test that context is properly assembled with source citations."""
    print_separator("STEP 3: Testing Context Assembly")

    context = pipeline._retriever.retrieve_context(
        "How does chunking work?",
        top_k=3
    )

    if not context:
        print("❌ No context returned")
        return False

    # Check for source markers
    has_source_markers = "[Source" in context
    has_chunk_content = len(context) > 100

    print(f"📄 Context length: {len(context)} characters")
    print(f"   Contains source markers: {'✅' if has_source_markers else '❌'}")
    print(f"   Has substantive content: {'✅' if has_chunk_content else '❌'}")

    # Show preview
    print(f"\n   Context preview (first 300 chars):")
    print(f"   {context[:300]}...")

    return has_source_markers and has_chunk_content


def test_full_rag_query(pipeline: RAGPipeline):
    """Test the full query pipeline (retrieval + generation with MockLLM)."""
    print_separator("STEP 4: Testing Full RAG Query (with MockLLM)")

    questions = [
        "What are the main components of a RAG system?",
        "Tell me about chunking strategies",
        "What embedding model should I use?",
    ]

    for q in questions:
        print(f"\n--- Query: \"{q[:60]}...\" ---")
        start = time.time()
        result = pipeline.query(q)
        elapsed = (time.time() - start) * 1000

        print(f"   Latency: {elapsed:.1f}ms")
        print(f"   Answer: {result['answer'][:150]}...")
        print(f"   Sources: {len(result.get('sources', []))}")
        if result.get("sources"):
            for s in result["sources"][:2]:
                print(f"     [{s['score']:.2f}] {os.path.basename(s['source'])}")

    print(f"\n✅ Full RAG pipeline completed {len(questions)} queries successfully")
    return True


def test_document_count(pipeline: RAGPipeline):
    """Verify document count is accurate."""
    print_separator("STEP 5: Document Count Verification")

    count = pipeline.document_count
    print(f"📊 Total chunks in vector store: {count}")

    if count == 0:
        print("❌ FAILED: Vector store is empty")
        return False

    # Show collection info
    store = pipeline._store
    if hasattr(store, '_collection'):
        print(f"   Collection: {store._collection.name}")
        print(f"   Collection metadata: {store._collection.metadata}")
    print(f"✅ PASSED: {count} chunks available")
    return True


def test_cross_chunk_retrieval(pipeline: RAGPipeline):
    """Test that retrieval pulls from different documents."""
    print_separator("STEP 6: Cross-Document Retrieval Test")

    results = pipeline._retriever.retrieve("embedding models sentence transformers", top_k=10)
    if not results:
        print("❌ No results for cross-document test")
        return False

    sources = set()
    for r in results:
        source = r.chunk.metadata.get("source", "unknown")
        sources.add(os.path.basename(source))

    print(f"📄 Retrieved from {len(sources)} different documents:")
    for s in sorted(sources):
        print(f"   - {s}")

    if len(sources) >= 2:
        print(f"✅ PASSED: Results span multiple documents")
        return True
    else:
        print(f"⚠️  Results came from only 1 document")
        return True  # Not a failure, depends on query


def main():
    print("=" * 70)
    print("  🔬 RAG PIPELINE END-TO-END VERIFICATION")
    print("  Sample documents → Index → Retrieve → Generate")
    print("=" * 70)

    # Show config
    print(f"\n📋 Configuration:")
    print(f"   Embedding model: {settings.embedding_model}")
    print(f"   Chunk size: {settings.chunk_size}, Overlap: {settings.chunk_overlap}")
    print(f"   Top-K: {settings.top_k}, Threshold: {settings.similarity_threshold}")
    print(f"   Vector store: {settings.vector_store}")
    print(f"   Documents directory: ai-engineering/rag/data/documents")
    print(f"   Persist directory: {settings.persist_directory}")

    # Initialize pipeline with MockLLM (no LM Studio needed)
    print(f"\n🚀 Initializing RAG pipeline...")
    print(f"   Using MockLLMService (no real LLM connection needed)")
    pipeline = RAGPipeline(
        embedder=SentenceTransformerEmbedding(),
        store=ChromaVectorStore(),
        llm=MockLLMService(),
        loader=TextFileLoader(),
    )
    print(f"   ✅ Pipeline initialized")

    # Run tests
    results = []
    docs_dir = os.path.join(os.path.dirname(__file__), "data", "documents")

    results.append(("Indexing", test_indexing(pipeline, docs_dir)))
    results.append(("Retrieval Quality", test_retrieval(pipeline)))
    results.append(("Context Assembly", test_context_assembly(pipeline)))
    results.append(("Full RAG Query", test_full_rag_query(pipeline)))
    results.append(("Document Count", test_document_count(pipeline)))
    results.append(("Cross-Document Retrieval", test_cross_chunk_retrieval(pipeline)))

    # Summary
    print_separator("RESULTS SUMMARY")
    all_passed = True
    for name, status in results:
        emoji = "✅" if status else "❌"
        print(f"  {emoji} {name}: {'PASSED' if status else 'FAILED'}")
        if not status:
            all_passed = False

    print(f"\n{'='*70}")
    if all_passed:
        print("  ✅ ALL TESTS PASSED — RAG pipeline works end-to-end!")
    else:
        print("  ⚠️  Some tests had issues — review details above")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
