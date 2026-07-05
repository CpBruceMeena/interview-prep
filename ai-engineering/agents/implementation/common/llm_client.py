"""
LLM Client abstraction for AI agents.
Supports multiple providers: OpenAI, LM Studio, Mock.
"""

import os
import json
from typing import Optional, Callable, List, Dict


class LLMClient:
    """Abstract LLM client for agent use."""

    def __init__(self, model: str = "gpt-4o-mini", api_key: Optional[str] = None,
                 base_url: Optional[str] = None, temperature: float = 0.3):
        self.model = model
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = base_url
        self.temperature = temperature

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Send a prompt to the LLM and return the response."""
        if self.base_url:
            return self._call_lm_studio(prompt, system_prompt)
        return self._call_openai(prompt, system_prompt)

    def _call_openai(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Call OpenAI-compatible API."""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
            )
            return response.choices[0].message.content or ""
        except ImportError:
            return self._mock_generate(prompt, system_prompt)

    def _call_lm_studio(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Call LM Studio local API."""
        try:
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
            }, timeout=30)
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            return self._mock_generate(prompt, system_prompt)

    def _mock_generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Mock LLM for testing without API keys."""
        if "search" in prompt.lower():
            return """Thought: I need to search for information to answer this question.
Action: search_web
ActionInput: {"query": "search query from context"}"""
        return """Thought: I have gathered enough information to answer.
Answer: Based on my analysis, here is the answer to your question. The key factors to consider are the results from the tools I used."""


def create_llm_client() -> LLMClient:
    """Create an LLM client based on environment configuration."""
    use_mock = os.environ.get("USE_MOCK_LLM", "true").lower() == "true"
    if use_mock:
        return LLMClient(model="mock")

    provider = os.environ.get("LLM_PROVIDER", "openai")
    if provider == "lm_studio":
        return LLMClient(
            model=os.environ.get("LLM_MODEL", "local-model"),
            base_url=os.environ.get("LM_STUDIO_URL", "http://localhost:1234"),
            temperature=0.3,
        )
    return LLMClient(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        temperature=0.3,
    )
