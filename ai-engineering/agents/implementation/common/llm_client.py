"""
LLM client abstraction for the demo agents.

Providers:
  - "mock"      : deterministic canned responses (default; no network, used by tests)
  - "openai"    : OpenAI Responses API via the official `openai` SDK
  - "lm_studio" : any OpenAI-compatible local server (LM Studio, Ollama, vLLM)
                  via its /v1/chat/completions endpoint

Model names change often, so nothing here hard-codes a "current" model:
set LLM_MODEL explicitly when you use a real provider.
"""

import os
from typing import Optional


class LLMClient:
    """Minimal text-in / text-out LLM client for the ReAct demo."""

    def __init__(self, model: str = "mock", api_key: Optional[str] = None,
                 base_url: Optional[str] = None, temperature: float = 0.3,
                 timeout_s: float = 30.0):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url
        self.temperature = temperature
        self.timeout_s = timeout_s

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Send a prompt to the LLM and return the text response."""
        if self.model == "mock":
            return self._mock_generate(prompt, system_prompt)
        if self.base_url:
            return self._call_openai_compatible(prompt, system_prompt)
        return self._call_openai(prompt, system_prompt)

    def _call_openai(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Call OpenAI's Responses API (the recommended API for new work).

        Errors are deliberately NOT swallowed: silently falling back to a mock
        on a 401/429/5xx hides real failures. Let the caller retry or fail.
        """
        from openai import OpenAI  # ImportError is a real configuration error

        client = OpenAI(api_key=self.api_key or None, timeout=self.timeout_s)
        kwargs = {"model": self.model, "input": prompt}
        if system_prompt:
            kwargs["instructions"] = system_prompt  # system/developer instructions
        response = client.responses.create(**kwargs)
        return response.output_text or ""

    def _call_openai_compatible(self, prompt: str,
                                system_prompt: Optional[str] = None) -> str:
        """Call a local OpenAI-compatible server (Chat Completions shape)."""
        import httpx

        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = httpx.post(url, json={
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": 1024,
        }, timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"] or ""

    def _mock_generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Deterministic stand-in for an LLM, for demos and tests."""
        if "search" in prompt.lower():
            return """Thought: I need to search for information to answer this question.
Action: search_web
ActionInput: {"query": "search query from context"}"""
        return """Thought: I have gathered enough information to answer.
Answer: Based on my analysis, here is the answer to your question. The key factors to consider are the results from the tools I used."""


def create_llm_client() -> LLMClient:
    """Create an LLM client from environment variables.

    USE_MOCK_LLM=true (default) -> mock
    LLM_PROVIDER=openai|lm_studio, LLM_MODEL=<model id> otherwise.
    """
    use_mock = os.environ.get("USE_MOCK_LLM", "true").lower() == "true"
    if use_mock:
        return LLMClient(model="mock")

    provider = os.environ.get("LLM_PROVIDER", "openai")
    model = os.environ.get("LLM_MODEL")
    if provider == "lm_studio":
        return LLMClient(
            model=model or "local-model",
            base_url=os.environ.get("LM_STUDIO_URL", "http://localhost:1234"),
        )
    if not model:
        raise ValueError("Set LLM_MODEL to a current model id from your "
                         "provider's models page (ids change frequently).")
    return LLMClient(model=model, api_key=os.environ.get("OPENAI_API_KEY", ""))
