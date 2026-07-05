"""
Tests for the orchestrated agent.
"""

import os
import sys
import pytest

# Ensure the agents module is on the path
_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)

from implementation.orchestrated_agent import (
    OrchestratorAgent, WorkerAgent, Tool, Task, Plan
)


# ── Fixtures ──

@pytest.fixture
def simple_worker():
    """Create a simple test worker."""
    return WorkerAgent(
        name="test_worker",
        description="A test worker",
        tools=[
            Tool("test_tool", "A test tool", lambda inp: f"Result: {inp}"),
        ]
    )


@pytest.fixture
def orchestrator(simple_worker):
    """Create an orchestrator with a single worker."""
    return OrchestratorAgent(workers=[simple_worker])


# ── Worker Tests ──

@pytest.mark.asyncio
async def test_worker_execution(simple_worker):
    """Test that a worker can execute a task."""
    task = Task(
        id="1",
        description="Test task",
        assigned_to="test_worker",
        input={"test_tool": {"input": "hello"}},
    )
    result = await simple_worker.execute(task)
    assert result.status == "completed"
    assert result.result is not None
    assert "test_worker" in result.result


@pytest.mark.asyncio
async def test_worker_unknown_tool(simple_worker):
    """Test that a worker handles unknown tools gracefully."""
    task = Task(
        id="1",
        description="Test task",
        assigned_to="test_worker",
        input={"unknown_tool": {"x": 1}},
    )
    result = await simple_worker.execute(task)
    assert result.status == "completed"  # Still completes, just logs error


# ── Orchestrator Tests ──

@pytest.mark.asyncio
async def test_orchestrator_run(orchestrator):
    """Test that the orchestrator runs and returns a result."""
    result = await orchestrator.run("Test request")
    assert result is not None
    assert len(result) > 0


@pytest.mark.asyncio
async def test_orchestrator_research_plan(orchestrator):
    """Test that research requests create multi-step plans."""
    result = await orchestrator.run("Research the impact of AI")
    assert "researcher" in result.lower()
    assert "analyst" in result.lower()
    assert "writer" in result.lower()


@pytest.mark.asyncio
async def test_orchestrator_simple_plan(orchestrator):
    """Test that non-research requests use a generalist worker."""
    result = await orchestrator.run("Hello, how are you?")
    assert "Result" in result


@pytest.mark.asyncio
async def test_orchestrator_with_multiple_workers():
    """Test orchestrator with multiple workers matching plan worker names."""
    researcher = WorkerAgent(
        name="researcher",
        description="Researcher",
        tools=[Tool("search", "Search", lambda: "Search result")],
    )
    analyst = WorkerAgent(
        name="analyst",
        description="Analyst",
        tools=[Tool("analyze", "Analyze", lambda: "Analysis result")],
    )

    orchestrator = OrchestratorAgent(workers=[researcher, analyst])

    result = await orchestrator.run("Research AI")
    assert "researcher" in result.lower()
    assert "analyst" in result.lower()


# ── Unit Tests ──

def test_task_defaults():
    """Test Task dataclass defaults."""
    task = Task(id="1", description="Test", assigned_to="worker", input={})
    assert task.status == "pending"
    assert task.result is None
    assert task.error is None


def test_plan_creation():
    """Test Plan dataclass."""
    plan = Plan(
        goal="Test goal",
        tasks=[Task(id="1", description="Task 1", assigned_to="w", input={})],
    )
    assert plan.goal == "Test goal"
    assert len(plan.tasks) == 1


def test_tool_call():
    """Test that Tool.call works correctly."""
    tool = Tool("echo", "Echo input", lambda x: f"Echo: {x}")
    result = tool.call(x="hello")
    assert result == "Echo: hello"


def test_tool_call_error_handling():
    """Test that Tool.call handles errors gracefully."""
    def failing_tool():
        raise ValueError("Something went wrong")
    tool = Tool("failing", "Always fails", failing_tool)
    result = tool.call()
    assert "Error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
