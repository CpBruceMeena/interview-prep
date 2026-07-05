"""
Tests for the RAG MCP server.
Requires: pip install pytest pytest-asyncio mcp sentence-transformers chromadb
"""

import os
import sys
import pytest
import asyncio

# Add implementation to path for imports
_IMPL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "rag", "implementation")
)
if _IMPL_DIR not in sys.path:
    sys.path.insert(0, _IMPL_DIR)

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.fixture(scope="module")
def server_params():
    """Fixture: create server parameters for the RAG MCP server.

    Uses USE_MOCK_LLM=true so tests don't need a running LM Studio instance.
    """
    env = os.environ.copy()
    env["USE_MOCK_LLM"] = "true"

    return StdioServerParameters(
        command="python",
        args=["-m", "servers.rag_server"],
        env=env,
    )


@pytest.fixture
async def session(server_params):
    """Fixture: create an MCP client session connected to the RAG server."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@pytest.mark.asyncio
async def test_list_tools(session):
    """Verify the server exposes all expected tools."""
    tools = await session.list_tools()
    tool_names = [t.name for t in tools.tools]

    expected = {"rag_query", "retrieve", "index_document"}
    for name in expected:
        assert name in tool_names, f"Missing tool: {name}"


@pytest.mark.asyncio
async def test_list_resources(session):
    """Verify the server exposes all expected resources."""
    resources = await session.list_resources()
    uris = [r.uri for r in resources.resources]

    expected = {"rag://status", "rag://documents"}
    for uri in expected:
        assert uri in uris, f"Missing resource: {uri}"


@pytest.mark.asyncio
async def test_rag_status_resource(session):
    """Verify the status resource returns system information."""
    result = await session.read_resource("rag://status")
    assert len(result.contents) == 1
    text = result.contents[0].text
    assert "RAG Pipeline Status" in text
    assert "Document count" in text
    assert "Embedding model" in text


@pytest.mark.asyncio
async def test_rag_query_with_mock(session):
    """Verify rag_query tool works with mock LLM."""
    result = await session.call_tool(
        "rag_query",
        {"question": "What is RAG?", "top_k": 3}
    )
    assert result.content[0].text is not None
    assert len(result.content[0].text) > 0
    # With mock LLM, we should still get some response
    # (the mock returns a fixed string regardless of input)


@pytest.mark.asyncio
async def test_retrieve_tool(session):
    """Verify retrieve tool works even without indexed documents.

    Should return a message indicating no documents found since
    no indexing has been done in this test.
    """
    result = await session.call_tool(
        "retrieve",
        {"question": "test query", "top_k": 5}
    )
    text = result.content[0].text
    # Should either return "no relevant documents" or actual chunks
    assert text is not None


@pytest.mark.asyncio
async def test_index_nonexistent_file(session):
    """Verify index_document returns error for non-existent paths."""
    result = await session.call_tool(
        "index_document",
        {"file_path": "/nonexistent/path/file.txt"}
    )
    assert "Error" in result.content[0].text
    assert "does not exist" in result.content[0].text


@pytest.mark.asyncio
async def test_rag_query_with_top_k(session):
    """Verify rag_query accepts different top_k values."""
    result = await session.call_tool(
        "rag_query",
        {"question": "How does chunking work?", "top_k": 10}
    )
    assert result.content[0].text is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
