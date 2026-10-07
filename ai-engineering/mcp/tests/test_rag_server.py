"""
Tests for the RAG MCP server.
Requires: pip install "mcp>=2" pytest pytest-asyncio
          plus ai-engineering/rag/implementation/requirements.txt
          (sentence-transformers, chromadb, langchain-text-splitters, pydantic-settings)

The server is imported and driven in-process with a mock LLM and a throwaway
vector store, so no LM Studio and no writes into the repo. The module is
skipped when the RAG dependencies are not installed.
"""

import os
import sys
import tempfile

import pytest

# Configure BEFORE importing the server: it builds the pipeline at import time.
_TMP = tempfile.mkdtemp(prefix="rag-mcp-test-")
os.environ["USE_MOCK_LLM"] = "true"
os.environ["PERSIST_DIRECTORY"] = os.path.join(_TMP, "vector_store")
os.environ["RAG_ALLOWED_ROOT"] = _TMP

for _dep in ("chromadb", "sentence_transformers", "langchain_text_splitters",
             "langchain_community", "pydantic_settings"):
    pytest.importorskip(_dep)

from mcp import Client  # noqa: E402

from servers.rag_server import mcp as rag_server  # noqa: E402


def connect() -> Client:
    """In-process client (opened per test: see test_calculator.connect)."""
    return Client(rag_server)


async def test_list_tools():
    async with connect() as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"rag_query", "retrieve", "index_document"} <= names


async def test_list_resources():
    async with connect() as client:
        uris = {str(r.uri) for r in (await client.list_resources()).resources}
        assert {"rag://status", "rag://documents"} <= uris


async def test_rag_status_resource():
    async with connect() as client:
        result = await client.read_resource("rag://status")
        assert len(result.contents) == 1
        text = result.contents[0].text
        assert "RAG Pipeline Status" in text
        assert "Embedding model" in text


async def test_index_then_retrieve_and_query():
    doc = os.path.join(_TMP, "mcp_notes.md")
    with open(doc, "w") as f:
        f.write(
            "# MCP transports\n\nThe Model Context Protocol defines two standard "
            "transports: stdio for local subprocess servers and Streamable HTTP "
            "for remote servers.\n"
        )
    async with connect() as client:
        indexed = await client.call_tool("index_document", {"file_path": doc})
        assert not indexed.is_error, indexed.content[0].text
        assert "Indexed" in indexed.content[0].text

        retrieved = await client.call_tool(
            "retrieve", {"question": "Which transports does MCP define?", "top_k": 3}
        )
        assert not retrieved.is_error
        assert "Streamable HTTP" in retrieved.content[0].text

        answered = await client.call_tool(
            "rag_query", {"question": "Which transports does MCP define?", "top_k": 3}
        )
        assert not answered.is_error
        assert "mock LLM" in answered.content[0].text  # the mock's fixed answer


async def test_index_nonexistent_file():
    async with connect() as client:
        result = await client.call_tool(
            "index_document", {"file_path": os.path.join(_TMP, "missing.txt")}
        )
        assert result.is_error
        assert "does not exist" in result.content[0].text


async def test_index_outside_allowed_root_is_refused():
    """Path containment: a model must not be able to index arbitrary files."""
    async with connect() as client:
        result = await client.call_tool(
            "index_document", {"file_path": os.path.join(_TMP, "..", "..", "etc", "passwd")}
        )
        assert result.is_error
        assert "outside the allowed root" in result.content[0].text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
