"""
Simple calculator MCP server demonstrating core primitives.
Run (from ai-engineering/mcp): python -m servers.calculator_server

Written against the official Python SDK v2 (`pip install "mcp>=2"`), where the
v1 `FastMCP` class is now `MCPServer`. Return type annotations become the
tool's `outputSchema`, so results carry `structuredContent` as well as text.

Errors: raise `ToolError` for failures the model should see and can act on
(they come back as a result with `isError: true` and your message). Any other
exception is treated as a crash: the client gets a generic "Error executing
tool X" and the details stay in the server log, so internals don't leak.

This server exposes:
- Tools: add, subtract, multiply, divide, power
- Resources: calculator://constants
- Prompts: solve_equation
"""

import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# Initialize server
mcp = MCPServer("Calculator")

# ════════════════════════════════════════════════════════════════
# TOOLS
# ════════════════════════════════════════════════════════════════


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


@mcp.tool()
def subtract(a: float, b: float) -> float:
    """Subtract b from a."""
    return a - b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers together."""
    return a * b


@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide a by b. Returns error if b is zero."""
    if b == 0:
        raise ToolError("Division by zero is not allowed")
    return a / b


@mcp.tool()
def power(base: float, exponent: float) -> float:
    """Raise base to the power of exponent."""
    return base ** exponent


@mcp.tool()
def square_root(x: float) -> float:
    """Calculate the square root of a non-negative number."""
    if x < 0:
        raise ToolError("Cannot calculate square root of a negative number")
    return x ** 0.5


@mcp.tool()
def percentage(value: float, total: float) -> float:
    """Calculate what percentage value is of total."""
    if total == 0:
        raise ToolError("Total cannot be zero")
    return (value / total) * 100


# ════════════════════════════════════════════════════════════════
# RESOURCES
# ════════════════════════════════════════════════════════════════


@mcp.resource("calculator://constants")
def get_constants() -> str:
    """Common mathematical constants."""
    return """pi: 3.141592653589793
e: 2.718281828459045
tau: 6.283185307179586
phi: 1.618033988749895
sqrt2: 1.4142135623730951
sqrt3: 1.7320508075688772"""


@mcp.resource("calculator://help")
def get_help() -> str:
    """Usage guide for the calculator server."""
    return """# Calculator MCP Server

Available tools:
- add(a, b) → a + b
- subtract(a, b) → a - b
- multiply(a, b) → a * b
- divide(a, b) → a / b (b ≠ 0)
- power(base, exponent) → base^exponent
- square_root(x) → √x (x ≥ 0)
- percentage(value, total) → (value/total) * 100

Available resources:
- calculator://constants — common math constants
- calculator://help — this help page
"""

# ════════════════════════════════════════════════════════════════
# PROMPTS
# ════════════════════════════════════════════════════════════════


@mcp.prompt()
def solve_equation(equation: str) -> str:
    """Create a prompt template for solving mathematical equations."""
    return f"""Solve the following mathematical equation step by step:

Equation: {equation}

Show all your work:"""


@mcp.prompt()
def explain_formula(formula: str) -> str:
    """Create a prompt to explain a mathematical formula."""
    return f"""Explain the following mathematical formula in simple terms:

Formula: {formula}

Break it down:
1. What each variable represents
2. What the formula calculates
3. A real-world example"""


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # stdio transport: stdout carries JSON-RPC, so diagnostics MUST go to stderr.
    print("Starting Calculator MCP Server (stdio)...", file=sys.stderr)
    mcp.run(transport="stdio")
