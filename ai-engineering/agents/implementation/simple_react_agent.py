"""
Simple ReAct (Reasoning + Acting) Agent implementation.
Demonstrates the core agent loop: Thought → Action → Observation → Repeat.

Run: python -m implementation.simple_react_agent
"""

import json
import time
from typing import List, Optional
from implementation.common.llm_client import LLMClient, create_llm_client
from implementation.common.tool_registry import ToolRegistry, ToolSpec
from implementation.common.memory import AgentMemory
from implementation.common.guardrails import InputGuard, OutputGuard, TokenBucket


def search_web(query: str) -> str:
    """Simulate a web search."""
    return f'Search results for "{query}": [Simulated: found 3 relevant results about {query}]'


def get_time() -> str:
    """Get the current time."""
    return f"Current time: {time.ctime()}"


def calculate(expression: str) -> str:
    """Evaluate a mathematical expression safely."""
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return "Error: Invalid characters in expression"
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as e:
        return f"Error: {str(e)}"


class ReActAgent:
    """
    ReAct (Reasoning + Acting) Agent.

    Loop:
      1. Thought: LLM reasons about what to do
      2. Action: LLM chooses a tool to call
      3. Observation: Tool result is fed back
      4. Repeat until final answer
    """

    def __init__(self, llm: LLMClient, tool_registry: ToolRegistry,
                 max_steps: int = 10):
        self.llm = llm
        self.tools = tool_registry
        self.max_steps = max_steps
        self.memory = AgentMemory()
        self.input_guard = InputGuard()
        self.output_guard = OutputGuard()
        self.rate_limiter = TokenBucket(rate=20, burst=30)

    def run(self, user_input: str) -> str:
        """Execute the agent loop for a user request."""
        # Input guardrail
        check = self.input_guard.validate(user_input)
        if not check.passed:
            return f"I cannot process this request: {check.message}"

        # Rate limit
        if not self.rate_limiter.consume():
            return "I'm receiving too many requests. Please wait a moment."

        # Initialize memory
        self.memory.add_conversation_turn("user", user_input)

        # Agent loop
        for step in range(self.max_steps):
            prompt = self._build_prompt()
            system_prompt = self._build_system_prompt()

            response = self.llm.generate(prompt, system_prompt)
            self.memory.add_conversation_turn("assistant", response)

            parsed = self._parse_response(response)

            if "answer" in parsed:
                final = parsed["answer"]
                check = self.output_guard.validate(final)
                if not check.passed:
                    return "I apologize, but I cannot provide that response."
                return final

            if "action" in parsed:
                tool_name = parsed["action"]
                try:
                    action_input = json.loads(
                        parsed.get("action_input", "{}")
                    )
                except json.JSONDecodeError:
                    action_input = {}

                observation = self.tools.execute(tool_name, action_input)
                self.memory.add_conversation_turn("observation", observation)

        return ("I've taken too many steps to answer this. "
                "Please try rephrasing your question.")

    def _build_system_prompt(self) -> str:
        tools_desc = self.tools.get_tool_descriptions()
        return f"""You are a helpful AI agent with access to these tools:

{tools_desc}

Always respond in this format:

Thought: <your reasoning>
Action: <tool_name>
ActionInput: <JSON arguments>

When you have the final answer:

Thought: I now know the answer
Answer: <your response to the user>"""

    def _build_prompt(self) -> str:
        return self.memory.get_context()

    def _parse_response(self, response: str) -> dict:
        """Parse the LLM response to extract actions or answer."""
        result = {}

        if "Answer:" in response:
            answer_part = response.split("Answer:")[-1].strip()
            result["answer"] = answer_part

        lines = response.split("\n")
        for line in lines:
            if line.startswith("Action:"):
                result["action"] = line.replace("Action:", "").strip()
            elif line.startswith("ActionInput:"):
                result["action_input"] = line.replace(
                    "ActionInput:", ""
                ).strip()

        return result


def main():
    """Run the ReAct agent with example tools."""
    llm = create_llm_client()

    # Set up tools
    registry = ToolRegistry()
    registry.register_tool(
        "search_web",
        "Search the web for current information on a topic",
        search_web,
        {"query": {"type": "string", "description": "Search query"}},
    )
    registry.register_tool(
        "get_time",
        "Get the current system time",
        get_time,
        {},
    )
    registry.register_tool(
        "calculate",
        "Evaluate a mathematical expression",
        calculate,
        {"expression": {"type": "string", "description": "Math expression"}},
    )

    agent = ReActAgent(llm=llm, tool_registry=registry)

    print("🤖 ReAct Agent (type 'quit' to exit)")
    print("─" * 50)

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break

        print("\nAgent thinking...")
        result = agent.run(user_input)
        print(f"Agent: {result}")


if __name__ == "__main__":
    main()
