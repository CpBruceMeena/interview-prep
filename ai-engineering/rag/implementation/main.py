"""CLI entry point for the RAG chatbot."""

import argparse
import sys
import os

from config import settings
from rag_pipeline import RAGPipeline


def setup_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RAG Chatbot — Retrieval-Augmented Generation with Gemma 4B",
    )
    parser.add_argument(
        "--index", action="store_true",
        help="Index documents from the data directory"
    )
    parser.add_argument(
        "--docs", type=str, default=settings.data_directory,
        help="Path to documents directory (default: ./data/documents)"
    )
    parser.add_argument(
        "--query", "-q", type=str,
        help="Ask a question"
    )
    parser.add_argument(
        "--interactive", "-i", action="store_true",
        help="Start interactive chat mode"
    )
    parser.add_argument(
        "--serve", action="store_true",
        help="Start the FastAPI web server"
    )
    return parser


def interactive_mode(pipeline: RAGPipeline):
    """Interactive chat loop."""
    print("\n🧠 RAG Chatbot — Interactive Mode")
    print("   Type 'exit' to quit, '/count' to see document count")
    print(f"   LLM: {settings.llm_model} via LM Studio at {settings.lm_studio_url}\n")

    while True:
        try:
            question = input("You: ").strip()
            if not question:
                continue
            if question.lower() in ("exit", "quit"):
                print("Goodbye!")
                break
            if question == "/count":
                print(f"📚 Documents indexed: {pipeline.document_count}")
                continue

            result = pipeline.query(question)
            print(f"\n🤖 Answer: {result['answer']}")
            if result.get("sources"):
                print(f"\n📖 Sources:")
                for s in result["sources"]:
                    print(f"   [{s['score']:.2f}] {s['source']}")
            print(f"   (took {result.get('latency_ms', 0)}ms)")
            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break


def main():
    parser = setup_argparse()
    args = parser.parse_args()

    if not any([args.index, args.query, args.interactive, args.serve]):
        parser.print_help()
        sys.exit(0)

    if args.serve:
        # Start web server
        import uvicorn
        print(f"🚀 Starting RAG API server on {settings.host}:{settings.port}")
        uvicorn.run(
            "chatbot_api:app",
            host=settings.host,
            port=settings.port,
            reload=False,
        )
        return

    # Initialize pipeline
    pipeline = RAGPipeline()

    # Index documents
    if args.index:
        docs_path = args.docs
        if not os.path.isdir(docs_path):
            print(f"❌ Documents directory not found: {docs_path}")
            print(f"   Create it or specify with --docs <path>")
            sys.exit(1)
        pipeline.index_directory(docs_path)

    # Single query
    if args.query:
        result = pipeline.query(args.query)
        print(f"\n🤖 {result['answer']}")
        if result.get("sources"):
            print(f"\n📖 Sources:")
            for s in result["sources"]:
                print(f"   [{s['score']:.2f}] {s['source']}")
        print(f"   (took {result.get('latency_ms', 0)}ms)")

    # Interactive mode
    if args.interactive:
        interactive_mode(pipeline)


if __name__ == "__main__":
    main()
