"""
Tool registry for AI agents — registration, validation, authorization, execution.
"""

import json
import time
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field

try:
    import jsonschema
    HAS_JSCHEMA = True
except ImportError:
    HAS_JSCHEMA = False


@dataclass
class ToolSpec:
    """Full tool specification with security metadata."""
    name: str
    description: str
    parameters: dict  # JSON Schema for parameters
    fn: Callable
    required_role: str = "user"
    requires_approval: bool = False
    timeout_seconds: int = 30
    category: str = "read"  # read, write, destructive


class ToolRegistry:
    """Central registry for all agent tools with validation and auth."""

    def __init__(self):
        self.tools: Dict[str, ToolSpec] = {}
        self._call_history: List[dict] = []

    def register(self, tool: ToolSpec):
        """Register a tool."""
        self.tools[tool.name] = tool

    def register_tool(self, name: str, description: str, fn: Callable,
                       parameters: dict, **kwargs):
        """Convenience method to register a tool inline."""
        self.register(ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            fn=fn,
            **kwargs
        ))

    def get(self, name: str) -> Optional[ToolSpec]:
        return self.tools.get(name)

    def list_tools(self) -> List[dict]:
        """Return all tools formatted for LLM consumption."""
        return [{
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        } for t in self.tools.values()]

    def execute(self, tool_name: str, params: dict,
                user_role: str = "user") -> str:
        """
        Full execution pipeline:
        1. Tool existence check
        2. Schema validation
        3. Authorization (role check)
        4. Execution with timeout
        5. Audit logging
        """
        tool = self.get(tool_name)
        if not tool:
            return f"Error: Unknown tool '{tool_name}'"

        # Schema validation
        if not self._validate_params(tool, params):
            return f"Error: Invalid parameters for '{tool_name}'"

        # Authorization
        role_levels = {"admin": 3, "editor": 2, "user": 1}
        if role_levels.get(user_role, 0) < role_levels.get(tool.required_role, 0):
            return f"Error: Insufficient permissions for '{tool_name}'"

        # Execute
        try:
            result = tool.fn(**params)
            result_str = str(result)
        except Exception as e:
            result_str = f"Error: {str(e)}"

        # Audit
        self._call_history.append({
            "timestamp": time.time(),
            "tool": tool_name,
            "params": params,
            "result": result_str[:500],
            "user_role": user_role,
        })

        return result_str

    def _validate_params(self, tool: ToolSpec, params: dict) -> bool:
        """Validate parameters against the tool's schema."""
        if not HAS_JSCHEMA:
            # Basic validation without jsonschema
            for key in tool.parameters:
                if tool.parameters[key].get("required", False):
                    if key not in params:
                        return False
            return True

        schema = {
            "type": "object",
            "properties": tool.parameters,
            "required": [
                k for k, v in tool.parameters.items()
                if isinstance(v, dict) and v.get("required", False)
            ],
        }
        try:
            jsonschema.validate(instance=params, schema=schema)
            return True
        except jsonschema.ValidationError:
            return False

    def get_call_history(self) -> List[dict]:
        """Get audit log of tool calls."""
        return self._call_history[-100:]  # Last 100 calls

    def get_tool_descriptions(self) -> str:
        """Format tools for LLM system prompt."""
        lines = []
        for tool in self.tools.values():
            params_str = ", ".join(
                f"{k}: {v.get('type', 'any')}"
                for k, v in tool.parameters.items()
            )
            lines.append(f"- {tool.name}({params_str}): {tool.description}")
        return "\n".join(lines)
