"""
Orchestrator-Worker Agent pattern.
The orchestrator decomposes tasks into sub-tasks and delegates to workers.

Run: python -m implementation.orchestrated_agent
"""

import asyncio
import json
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field


@dataclass
class Task:
    """A unit of work for a worker agent."""
    id: str
    description: str
    assigned_to: str
    input: dict
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"
    result: Any = None
    error: Optional[str] = None


@dataclass
class Plan:
    """Decomposition of a user request into tasks."""
    goal: str
    tasks: List[Task]
    created_at: float = field(default_factory=time.time)


class Tool:
    """Simple callable tool for workers."""

    def __init__(self, name: str, description: str, fn):
        self.name = name
        self.description = description
        self.fn = fn

    def call(self, **kwargs) -> str:
        try:
            return str(self.fn(**kwargs))
        except Exception as e:
            return f"Error: {str(e)}"


class WorkerAgent:
    """A specialized worker that executes specific types of tasks."""

    def __init__(self, name: str, description: str, tools: List[Tool]):
        self.name = name
        self.description = description
        self.tools = {t.name: t for t in tools}
        self._history: List[str] = []

    async def execute(self, task: Task) -> Task:
        """Execute a task using the worker's tools."""
        task.status = "running"
        try:
            # Use the description + input as execution context
            # In production: LLM generates tool calls
            result_parts = [f"[{self.name}] Processing: {task.description}"]

            # Try to use available tools
            for tool_name, tool in self.tools.items():
                if task.input and tool_name in task.input:
                    result = tool.call(**(
                        task.input[tool_name]
                        if isinstance(task.input[tool_name], dict)
                        else {"input": task.input[tool_name]}
                    ))
                    result_parts.append(f"  {tool_name}: {result}")

            task.result = "\n".join(result_parts)
            task.status = "completed"
        except Exception as e:
            task.error = str(e)
            task.status = "failed"
        return task


class OrchestratorAgent:
    """
    Orchestrator-Worker pattern.

    Flow:
    1. Receive request → create plan (decompose into tasks)
    2. Execute tasks respecting dependencies (parallel where possible)
    3. Synthesize results into final answer
    """

    def __init__(self, workers: List[WorkerAgent]):
        self.workers = {w.name: w for w in workers}

    async def run(self, user_request: str) -> str:
        print(f"\n📋 Orchestrator received: '{user_request}'")

        # Phase 1: Plan
        plan = self._create_plan(user_request)
        print(f"📝 Plan: {len(plan.tasks)} tasks created")

        for t in plan.tasks:
            deps = f" (after: {t.dependencies})" if t.dependencies else ""
            print(f"   - [{t.assigned_to}] {t.description}{deps}")

        # Phase 2: Execute
        results = await self._execute_plan(plan)
        print(f"✅ Execution complete: {len(results)} tasks done")

        # Phase 3: Synthesize
        return self._synthesize(plan, results, user_request)

    def _create_plan(self, request: str) -> Plan:
        """Decompose a request into a DAG of tasks."""
        # In production: use LLM to plan
        # For demo: pattern-match common request types
        request_lower = request.lower()

        if "research" in request_lower or "search" in request_lower:
            return Plan(
                goal=request,
                tasks=[
                    Task(id="1", description="Search for information on topic",
                         assigned_to="researcher",
                         input={"search_web": {"query": request}}),
                    Task(id="2", description="Analyze and summarize findings",
                         assigned_to="analyst",
                         input={}, dependencies=["1"]),
                    Task(id="3", description="Compose final report",
                         assigned_to="writer",
                         input={}, dependencies=["1", "2"]),
                ]
            )
        else:
            # Default: single task
            return Plan(
                goal=request,
                tasks=[
                    Task(id="1", description=f"Process request: {request}",
                         assigned_to="generalist",
                         input={"process": {"request": request}}),
                ]
            )

    async def _execute_plan(self, plan: Plan) -> Dict[str, Task]:
        """Execute tasks respecting dependency graph."""
        completed: Dict[str, Task] = {}
        task_map = {t.id: t for t in plan.tasks}

        while len(completed) < len(plan.tasks):
            # Find tasks whose dependencies are met
            ready = [
                t for t in plan.tasks
                if t.id not in completed
                   and all(dep in completed for dep in t.dependencies)
            ]

            if not ready:
                raise RuntimeError("Deadlock in task dependencies — "
                                   "circular or missing dependency")

            # Execute ready tasks in parallel
            tasks_to_run = []
            for task in ready:
                worker = self.workers.get(task.assigned_to)
                if not worker:
                    task.status = "failed"
                    task.error = f"No worker named '{task.assigned_to}'"
                    completed[task.id] = task
                    continue
                tasks_to_run.append(worker.execute(task))

            results = await asyncio.gather(*tasks_to_run)
            for result in results:
                completed[result.id] = result

        return completed

    def _synthesize(self, plan: Plan, results: Dict[str, Task],
                    request: str) -> str:
        """Merge worker results into a final answer."""
        parts = [f"## Result\n\n"]
        parts.append(f"**Request:** {request}\n")

        for task in plan.tasks:
            result = results[task.id]
            icon = "✅" if result.status == "completed" else "❌"
            parts.append(f"\n### {icon} {task.assigned_to}")
            parts.append(f"*{task.description}*")
            if result.result:
                parts.append(f"\n{result.result}")
            if result.error:
                parts.append(f"\n**Error:** {result.error}")

        return "\n".join(parts)


async def main():
    """Run the orchestrator agent demo."""

    # Create workers with tools
    researcher = WorkerAgent(
        name="researcher",
        description="Search for and gather information",
        tools=[
            Tool("search_web", "Search the web for information",
                 lambda query: f'Results for "{query}": [simulated data]'),
        ]
    )

    analyst = WorkerAgent(
        name="analyst",
        description="Analyze data and extract insights",
        tools=[
            Tool("analyze", "Analyze data and summarize",
                 lambda input: f"Analysis: Key patterns identified in data"),
        ]
    )

    writer = WorkerAgent(
        name="writer",
        description="Compose clear, structured outputs",
        tools=[
            Tool("compose", "Write a structured report",
                 lambda input: f"Report: Structured summary based on analysis"),
        ]
    )

    generalist = WorkerAgent(
        name="generalist",
        description="Handle general requests",
        tools=[
            Tool("process", "Process a general request",
                 lambda request: f"Processed: {request}"),
        ]
    )

    # Create orchestrator
    orchestrator = OrchestratorAgent(
        workers=[researcher, analyst, writer, generalist]
    )

    # Interactive loop
    print("🤖 Orchestrator Agent (type 'quit' to exit)")
    print("─" * 60)

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break

        result = await orchestrator.run(user_input)
        print(f"\n{result}")


if __name__ == "__main__":
    asyncio.run(main())
