"""
Tests for the Calculator MCP server.
Requires: pip install pytest pytest-asyncio mcp
"""

import pytest
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.fixture(scope="module")
def server_params():
    """Fixture: create server parameters pointing to the calculator server."""
    return StdioServerParameters(
        command="python",
        args=["-m", "servers.calculator_server"],
    )


@pytest.fixture
async def session(server_params):
    """Fixture: create an MCP client session connected to the calculator server."""
    async with stdio_client(server_params) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            yield session


@pytest.mark.asyncio
async def test_list_tools(session):
    """Verify the server exposes all expected tools."""
    tools = await session.list_tools()
    tool_names = [t.name for t in tools.tools]

    expected = {"add", "subtract", "multiply", "divide", "power", "square_root", "percentage"}
    for name in expected:
        assert name in tool_names, f"Missing tool: {name}"
    assert len(tool_names) >= len(expected)


@pytest.mark.asyncio
async def test_add(session):
    """Test addition."""
    result = await session.call_tool("add", {"a": 5, "b": 3})
    assert result.content[0].text == "8.0"


@pytest.mark.asyncio
async def test_subtract(session):
    """Test subtraction."""
    result = await session.call_tool("subtract", {"a": 10, "b": 4})
    assert result.content[0].text == "6.0"


@pytest.mark.asyncio
async def test_multiply(session):
    """Test multiplication."""
    result = await session.call_tool("multiply", {"a": 6, "b": 7})
    assert result.content[0].text == "42.0"


@pytest.mark.asyncio
async def test_divide(session):
    """Test division."""
    result = await session.call_tool("divide", {"a": 10, "b": 2})
    assert result.content[0].text == "5.0"


@pytest.mark.asyncio
async def test_divide_by_zero(session):
    """Test division by zero returns error message."""
    result = await session.call_tool("divide", {"a": 1, "b": 0})
    assert result.isError
    assert "Division by zero" in result.content[0].text


@pytest.mark.asyncio
async def test_power(session):
    """Test exponentiation."""
    result = await session.call_tool("power", {"base": 2, "exponent": 10})
    assert result.content[0].text == "1024.0"


@pytest.mark.asyncio
async def test_square_root(session):
    """Test square root."""
    result = await session.call_tool("square_root", {"x": 9})
    assert result.content[0].text == "3.0"


@pytest.mark.asyncio
async def test_square_root_negative(session):
    """Test square root of negative number returns error message."""
    result = await session.call_tool("square_root", {"x": -1})
    assert result.isError
    assert "Cannot calculate square root" in result.content[0].text


@pytest.mark.asyncio
async def test_percentage(session):
    """Test percentage calculation."""
    result = await session.call_tool("percentage", {"value": 25, "total": 200})
    assert result.content[0].text == "12.5"


@pytest.mark.asyncio
async def test_percentage_zero_total(session):
    """Test percentage with zero total returns error message."""
    result = await session.call_tool("percentage", {"value": 1, "total": 0})
    assert result.isError
    assert "Total cannot be zero" in result.content[0].text


@pytest.mark.asyncio
async def test_list_resources(session):
    """Verify the server exposes expected resources."""
    resources = await session.list_resources()
    uris = [str(r.uri) for r in resources.resources]
    assert "calculator://constants" in uris
    assert "calculator://help" in uris


@pytest.mark.asyncio
async def test_read_constants_resource(session):
    """Verify the constants resource returns expected content."""
    result = await session.read_resource("calculator://constants")
    assert len(result.contents) == 1
    text = result.contents[0].text
    assert "pi: 3.141592653589793" in text
    assert "e: 2.718281828459045" in text


@pytest.mark.asyncio
async def test_list_prompts(session):
    """Verify the server exposes expected prompts."""
    prompts = await session.list_prompts()
    names = [p.name for p in prompts.prompts]
    assert "solve_equation" in names
    assert "explain_formula" in names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
