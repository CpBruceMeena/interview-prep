"""
Python client for connecting to MCP servers.
Supports both calculator and RAG MCP servers.

Usage:
    # Test calculator server
    python -m clients.python_client --server calculator --add 5 3

    # Query RAG server
    python -m clients.python_client --server rag --query "What is RAG?"

    # List tools from any server
    python -m clients.python_client --server calculator --list

    # Interactive mode
    python -m clients.python_client --server calculator --interactive
"""

import asyncio
import argparse
import json
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER_COMMANDS = {
    "calculator": {
        "command": sys.executable or "python",
        "args": ["-m", "servers.calculator_server"],
    },
    "database": {
        "command": sys.executable or "python",
        "args": ["-m", "servers.database_server"],
    },
    "rag": {
        "command": sys.executable or "python",
        "args": ["-m", "servers.rag_server"],
    },
}


async def list_tools(server_name: str) -> None:
    """Connect to an MCP server and list its available tools."""
    config = SERVER_COMMANDS[server_name]
    params = StdioServerParameters(
        command=config["command"],
        args=config["args"],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List tools
            tools_result = await session.list_tools()
            print(f"\n🔧 Tools available on '{server_name}' server:\n")
            for tool in tools_result.tools:
                print(f"  📌 {tool.name}")
                print(f"     {tool.description}")
                if tool.inputSchema and tool.inputSchema.get("properties"):
                    print(f"     Parameters:")
                    for p_name, p_info in tool.inputSchema["properties"].items():
                        p_type = p_info.get("type", "any")
                        p_desc = p_info.get("description", "")
                        req = (
                            "required"
                            if p_name in tool.inputSchema.get("required", [])
                            else "optional"
                        )
                        print(f"       - {p_name} ({p_type}, {req}): {p_desc}")
                print()

            # List resources
            resources_result = await session.list_resources()
            if resources_result.resources:
                print(f"📦 Resources available on '{server_name}' server:\n")
                for resource in resources_result.resources:
                    print(f"  📄 {resource.uri}")
                    if resource.description:
                        print(f"     {resource.description}")
                    print()

            # List prompts
            prompts_result = await session.list_prompts()
            if prompts_result.prompts:
                print(f"💡 Prompts available on '{server_name}' server:\n")
                for prompt in prompts_result.prompts:
                    print(f"  📝 {prompt.name}")
                    if prompt.description:
                        print(f"     {prompt.description}")
                    print()


async def call_tool(server_name: str, tool_name: str, arguments: dict) -> str:
    """Call a tool on an MCP server and return the result."""
    config = SERVER_COMMANDS[server_name]
    params = StdioServerParameters(
        command=config["command"],
        args=config["args"],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result.content[0].text if result.content else "No content returned"


async def read_resource(server_name: str, uri: str) -> str:
    """Read a resource from an MCP server."""
    config = SERVER_COMMANDS[server_name]
    params = StdioServerParameters(
        command=config["command"],
        args=config["args"],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource(uri)
            if result and result.contents:
                return result.contents[0].text
            return "No content returned"


async def interactive_mode(server_name: str) -> None:
    """Interactive REPL for exploring an MCP server."""
    print(f"\n🔮 Interactive mode — '{server_name}' MCP Server\n")
    print("Available commands:")
    print("  /tools          — List all tools")
    print("  /resources      — List all resources")
    print("  /call TOOL ARGS — Call a tool (ARGS as JSON)")
    print("  /read URI       — Read a resource")
    print("  /help           — Show this help")
    print("  /quit           — Exit")
    print()

    while True:
        try:
            line = input("mcp> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        if line == "/quit":
            break
        elif line == "/help":
            print("Commands: /tools, /resources, /call TOOL JSON_ARGS, /read URI, /help, /quit")
        elif line == "/tools":
            await list_tools(server_name)
        elif line == "/resources":
            config = SERVER_COMMANDS[server_name]
            params = StdioServerParameters(
                command=config["command"],
                args=config["args"],
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    resources = await session.list_resources()
                    if resources.resources:
                        for r in resources.resources:
                            print(f"  📄 {r.uri} — {r.description or 'No description'}")
                    else:
                        print("  No resources available.")
        elif line.startswith("/call "):
            parts = line[6:].strip().split(" ", 1)
            if len(parts) < 2:
                print("Usage: /call TOOL_NAME JSON_ARGS")
                continue
            tool_name = parts[0]
            try:
                args = json.loads(parts[1]) if parts[1].strip() else {}
            except json.JSONDecodeError as e:
                print(f"Invalid JSON: {e}")
                continue
            result = await call_tool(server_name, tool_name, args)
            print(result)
        elif line.startswith("/read "):
            uri = line[6:].strip()
            result = await read_resource(server_name, uri)
            print(result)
        else:
            print(f"Unknown command: {line}. Type /help for available commands.")


def main():
    parser = argparse.ArgumentParser(description="MCP Client — Connect to MCP Servers")
    parser.add_argument(
        "--server", "-s",
        choices=list(SERVER_COMMANDS.keys()),
        default="calculator",
        help="MCP server to connect to"
    )
    parser.add_argument("--list", action="store_true", help="List available tools")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive REPL mode")

    # Tool-specific arguments
    parser.add_argument("--add", nargs=2, type=float, metavar=("A", "B"), help="Add two numbers")
    parser.add_argument("--query", type=str, help="Query the RAG server")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K for RAG retrieval")

    args = parser.parse_args()

    if args.list:
        asyncio.run(list_tools(args.server))
    elif args.interactive:
        asyncio.run(interactive_mode(args.server))
    elif args.add and args.server == "calculator":
        result = asyncio.run(call_tool("calculator", "add", {"a": args.add[0], "b": args.add[1]}))
        print(f"{args.add[0]} + {args.add[1]} = {result}")
    elif args.query and args.server == "rag":
        result = asyncio.run(call_tool(
            "rag", "rag_query",
            {"question": args.query, "top_k": args.top_k}
        ))
        print(result)
    else:
        # Default: list tools
        asyncio.run(list_tools(args.server))


if __name__ == "__main__":
    main()
