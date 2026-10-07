# Tests — MCP Module

> Pytest suite for the MCP servers (Python SDK v2)

- **[test_calculator.py](test_calculator.py)**: tools, structured output, tool errors vs protocol errors, resources, prompts, plus one end-to-end test over the real stdio transport.
- **[test_rag_server.py](test_rag_server.py)**: index, retrieve and answer with a mock LLM and a throwaway vector store, plus the path-containment check. Skipped when the RAG dependencies aren't installed.

Most tests use the SDK's in-process client, `Client(server_object)`: no subprocess and no JSON-RPC framing, so they are fast and deterministic.

## Running

```bash
cd ai-engineering/mcp/
pip install -r requirements.txt          # add ../rag/implementation/requirements.txt for the RAG tests
python -m pytest tests/ -v
```
