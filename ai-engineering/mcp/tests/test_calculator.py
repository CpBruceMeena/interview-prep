"""
Tests for the Calculator MCP server.
Requires: pip install "mcp>=2" pytest pytest-asyncio   (run from ai-engineering/mcp)

Most tests connect in-process (`Client(server_object)`): no subprocess, no
JSON-RPC framing, fast and deterministic. One end-to-end test launches the
server over stdio to prove the real transport works (and that nothing the
server prints corrupts stdout).
"""

import os
import sys

import pytest
from mcp import Client, StdioServerParameters

from servers.calculator_server import mcp as calculator

MCP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def connect() -> Client:
    """An MCP client connected in-process to the calculator server.

    Opened inside each test rather than in an async-generator fixture: the
    client holds an anyio cancel scope, which must be exited by the same task
    that entered it, and pytest-asyncio may run fixture teardown in another task.
    """
    return Client(calculator)


async def test_list_tools():
    """Verify the server exposes all expected tools."""
    async with connect() as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools.tools}
        expected = {"add", "subtract", "multiply", "divide", "power", "square_root", "percentage"}
        assert expected <= tool_names


async def test_tools_have_output_schema():
    """Return annotations become an outputSchema (structured tool output)."""
    async with connect() as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert tools["add"].output_schema["properties"]["result"]["type"] == "number"


@pytest.mark.parametrize(
    "tool, args, expected",
    [
        ("add", {"a": 5, "b": 3}, 8.0),
        ("subtract", {"a": 10, "b": 4}, 6.0),
        ("multiply", {"a": 6, "b": 7}, 42.0),
        ("divide", {"a": 10, "b": 2}, 5.0),
        ("power", {"base": 2, "exponent": 10}, 1024.0),
        ("square_root", {"x": 9}, 3.0),
        ("percentage", {"value": 25, "total": 200}, 12.5),
    ],
)
async def test_arithmetic(tool, args, expected):
    async with connect() as client:
        result = await client.call_tool(tool, args)
        assert not result.is_error
        # Structured result for programs, text block for the model.
        assert result.structured_content == {"result": expected}
        assert result.content[0].text == str(expected)


@pytest.mark.parametrize(
    "tool, args, message",
    [
        ("divide", {"a": 1, "b": 0}, "Division by zero"),
        ("square_root", {"x": -1}, "Cannot calculate square root"),
        ("percentage", {"value": 1, "total": 0}, "Total cannot be zero"),
    ],
)
async def test_tool_errors_are_results_not_protocol_errors(tool, args, message):
    """A ToolError comes back as isError=true with the message, so the model can recover."""
    async with connect() as client:
        result = await client.call_tool(tool, args)
        assert result.is_error
        assert message in result.content[0].text


async def test_invalid_arguments_are_tool_errors():
    """Argument validation failures are also returned as tool errors (spec 2025-11-25+)."""
    async with connect() as client:
        result = await client.call_tool("add", {"a": "not-a-number", "b": 1})
        assert result.is_error


async def test_list_resources():
    async with connect() as client:
        resources = await client.list_resources()
        uris = {str(r.uri) for r in resources.resources}
        assert {"calculator://constants", "calculator://help"} <= uris


async def test_read_constants_resource():
    async with connect() as client:
        result = await client.read_resource("calculator://constants")
        assert len(result.contents) == 1
        text = result.contents[0].text
        assert "pi: 3.141592653589793" in text
        assert "e: 2.718281828459045" in text


async def test_list_prompts():
    async with connect() as client:
        prompts = await client.list_prompts()
        names = {p.name for p in prompts.prompts}
        assert {"solve_equation", "explain_formula"} <= names


async def test_stdio_end_to_end():
    """Launch the server as a subprocess and talk to it over stdio."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "servers.calculator_server"],
        cwd=MCP_ROOT,
    )
    async with Client(params) as c:
        result = await c.call_tool("multiply", {"a": 6, "b": 7})
        assert result.structured_content == {"result": 42.0}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
