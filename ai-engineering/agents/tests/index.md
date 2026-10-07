# Tests — AI Agents Module

> Pytest test suite for the AI Agents module

## Test Files

- **[test_simple_agent.py](test_simple_agent.py)** — Agent loop with the mock LLM, input guardrail, tool registry validation, response parsing
- **[test_orchestrated_agent.py](test_orchestrated_agent.py)** — Worker execution, plan creation, dependency handling, missing workers

## Running Tests

```bash
cd ai-engineering/agents/
pip install pytest pytest-asyncio jsonschema
python -m pytest tests/ -v
```

The tests use the mock LLM (`LLMClient(model="mock")`), so they need no API key or network.
