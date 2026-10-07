"""
Tool registry for AI agents — registration, validation, authorization, execution.
"""

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
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
    # Property map: {"arg": {"type": "string", "required": True, ...}}.
    # "required" is a convenience flag; it is lifted into a proper JSON Schema
    # `required` array before validation (see _json_schema).
    parameters: dict
    fn: Callable
    required_role: str = "user"
    requires_approval: bool = False
    timeout_seconds: int = 30
    category: str = "read"  # read, write, destructive


class ToolRegistry:
    """Central registry for all agent tools with validation and auth."""

    def __init__(self, max_workers: int = 8):
        self.tools: Dict[str, ToolSpec] = {}
        self._call_history: List[dict] = []
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

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
            "parameters": self._json_schema(t),
        } for t in self.tools.values()]

    def execute(self, tool_name: str, params: dict,
                user_role: str = "user", approved: bool = False) -> str:
        """
        Full execution pipeline:
        1. Tool existence check
        2. Schema validation
        3. Authorization (role check) and human-approval gate
        4. Execution with timeout
        5. Audit logging

        Errors are returned as strings so the agent loop can feed them back
        to the model as an observation instead of crashing.
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
        if tool.requires_approval and not approved:
            return f"Error: '{tool_name}' requires human approval"

        # Execute with a timeout. A Python thread cannot be killed, so a hung
        # tool keeps its worker thread; real systems run tools in a subprocess
        # or remote sandbox when they need hard cancellation.
        future = self._executor.submit(tool.fn, **params)
        try:
            result_str = str(future.result(timeout=tool.timeout_seconds))
        except FutureTimeout:
            result_str = (f"Error: '{tool_name}' timed out after "
                          f"{tool.timeout_seconds}s")
        except Exception as e:
            result_str = f"Error: {e}"

        # Audit
        self._call_history.append({
            "timestamp": time.time(),
            "tool": tool_name,
            "params": params,
            "result": result_str[:500],
            "user_role": user_role,
        })

        return result_str

    @staticmethod
    def _json_schema(tool: ToolSpec) -> dict:
        """Build a valid JSON Schema object from the property map.

        `required: True` inside a property is not valid JSON Schema (draft 4+
        expects a `required` array on the parent object), so lift it out.
        """
        properties, required = {}, []
        for name, prop in tool.parameters.items():
            prop = dict(prop)
            if prop.pop("required", False):
                required.append(name)
            properties[name] = prop
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,  # reject hallucinated arguments
        }

    def _validate_params(self, tool: ToolSpec, params: dict) -> bool:
        """Validate parameters against the tool's schema."""
        if not isinstance(params, dict):
            return False
        schema = self._json_schema(tool)
        if not HAS_JSCHEMA:
            # Minimal fallback: required keys present, no unknown keys.
            return (all(k in params for k in schema["required"])
                    and all(k in schema["properties"] for k in params))
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
