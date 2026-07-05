"""
Agent that discovers and uses tools from MCP servers.
Connects to the calculator MCP server and uses its tools.

Run: python -m implementation.agent_with_mcp
Requires: pip install mcp (or run from ai-engineering/mcp/)
"""

import asyncio
import json
import os
from typing import Dict, List


async def discover_mcp_tools(server_name: str, command: str,
                              args: List[str]) -> List[dict]:
    """
    Connect to an MCP server and discover its tools.

    Returns a list of tool definitions compatible with the agent's tool registry.
    """
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=command,
            args=args,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.inputSchema,
                        "_server": server_name,
                        "_session_params": {
                            "command": command,
                            "args": args,
                        },
                    }
                    for t in tools.tools
                ]
    except ImportError:
        print("⚠️  MCP SDK not installed. Install with: pip install mcp")
        return []


async def call_mcp_tool(tool_def: dict, arguments: dict) -> str:
    """Call a tool on an MCP server and return the result."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = tool_def["_session_params"]
        server_params = StdioServerParameters(
            command=params["command"],
            args=params["args"],
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_def["name"], arguments)
                return result.content[0].text
    except Exception as e:
        return f"Error calling MCP tool '{tool_def['name']}': {str(e)}"


class MCPAgent:
    """
    Agent that discovers tools via MCP protocol and uses them.

    Architecture:
    1. Connect to MCP servers → discover tools via tools/list
    2. Present unified tool list to LLM
    3. Route tool calls to the correct server
    """

    def __init__(self, llm_fn=None):
        self.mcp_tools: List[dict] = []
        self._llm = llm_fn or self._default_llm
        self._history: List[str] = []

    async def connect_servers(self, server_configs: List[dict]):
        """Connect to multiple MCP servers and discover all tools."""
        all_tools = []
        for config in server_configs:
            print(f"🔌 Connecting to MCP server: {config['name']}...")
            tools = await discover_mcp_tools(
                config["name"],
                config["command"],
                config["args"],
            )
            all_tools.extend(tools)
            print(f"   Discovered {len(tools)} tools")

        self.mcp_tools = all_tools
        print(f"\n📋 Total tools available: {len(all_tools)}")

    def _default_llm(self, prompt: str) -> str:
        """Default mock LLM for demo purposes."""
        return """Thought: I have enough information to answer.
Answer: Using the MCP tools available, I completed the requested operation. 
The tools discovered via MCP protocol worked correctly."""

    def _format_tools(self) -> str:
        """Format discovered tools for LLM prompt."""
        lines = []
        for tool in self.mcp_tools:
            params = tool.get("inputSchema", {}).get("properties", {})
            params_str = ", ".join(params.keys()) if params else "no params"
            lines.append(
                f"- {tool['name']}({params_str}): {tool['description']}"
            )
        return "\n".join(lines)

    async def run(self, user_input: str) -> str:
        """Execute a task using discovered MCP tools."""
        tools_desc = self._format_tools()
        prompt = f"""You have access to the following MCP tools:

{tools_desc}

User request: {user_input}

Choose and call the appropriate tool. Respond with:
Action: <tool_name>
Arguments: <JSON arguments>

When done:
Answer: <final result>"""

        # Get LLM response
        response = self._llm(prompt)

        # Parse action
        action = None
        arguments = {}
        for line in response.split("\n"):
            if line.startswith("Action:"):
                action = line.replace("Action:", "").strip()
            elif line.startswith("Arguments:"):
                try:
                    arguments = json.loads(
                        line.replace("Arguments:", "").strip()
                    )
                except json.JSONDecodeError:
                    pass

        if action and "Answer:" not in response:
            # Find the tool definition
            tool_def = None
            for t in self.mcp_tools:
                if t["name"] == action:
                    tool_def = t
                    break

            if tool_def:
                result = await call_mcp_tool(tool_def, arguments)
                return f"**Tool called:** {action}\n**Result:** {result}"
            else:
                return f"Unknown MCP tool: {action}"

        # Return direct answer
        if "Answer:" in response:
            return response.split("Answer:")[-1].strip()
        return response


async def main():
    """Connect to MCP servers and run the agent."""
    agent = MCPAgent()

    # Try to connect to the calculator MCP server
    # (assumes it's installed: pip install -r ../requirements.txt)
    calculator_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "mcp", "servers",
        "calculator_server.py"
    )

    server_configs = []
    if os.path.exists(calculator_path):
        server_configs.append({
            "name": "Calculator",
            "command": "python",
            "args": [calculator_path],
        })
    else:
        print("⚠️  Calculator MCP server not found at expected path.")
        print("   Install MCP servers first: cd ../mcp && pip install -r requirements.txt")

    # If no servers found, use demo mode
    if not server_configs:
        server_configs.append({
            "name": "Demo",
            "command": "echo",
            "args": ["MCP server not available"],
        })

    await agent.connect_servers(server_configs)

    print("\n🤖 MCP Agent (type 'quit' to exit)")
    print("─" * 50)

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break

        result = await agent.run(user_input)
        print(f"\nAgent: {result}")


if __name__ == "__main__":
    asyncio.run(main())
