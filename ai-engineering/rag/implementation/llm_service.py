"""LLM service — interfaces with LM Studio / any OpenAI-compatible API."""

import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import requests

from config import settings

# Log (to stderr) rather than print: stdout may be a protocol channel (MCP stdio).
log = logging.getLogger(__name__)


class LLMService(ABC):
    """Abstract LLM service. Returns None on failure so callers can degrade."""

    @abstractmethod
    def generate(self, messages: List[Dict[str, str]],
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> Optional[str]:
        """Generate a response from the LLM given a message list."""

    def is_available(self) -> bool:
        """Cheap liveness probe for health checks."""
        return True


def _payload(model: str, messages, temperature, max_tokens) -> dict:
    # `is None`, not `or`: temperature=0.0 is a valid (greedy) setting.
    return {
        "model": model,
        "messages": messages,
        "temperature": settings.temperature if temperature is None else temperature,
        "max_tokens": settings.max_tokens if max_tokens is None else max_tokens,
    }


class OpenAICompatibleClient(LLMService):
    """Client for any server exposing POST {base}/v1/chat/completions."""

    def __init__(self, api_url: str, api_key: str = "", model: str = "",
                 timeout: float = 120):
        # api_url is the ".../v1" base, e.g. "http://localhost:1234/v1".
        self.v1_url = api_url.rstrip("/")
        self.base_url = self.v1_url
        self.api_url = self.v1_url + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def generate(self, messages: List[Dict[str, str]],
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> Optional[str]:
        try:
            response = requests.post(
                self.api_url,
                json=_payload(self.model, messages, temperature, max_tokens),
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except requests.exceptions.ConnectionError:
            log.error("Cannot connect to LLM server at %s", self.base_url)
        except requests.exceptions.Timeout:
            log.error("LLM request timed out after %ss", self.timeout)
        except requests.exceptions.HTTPError as e:
            # e.g. 404/400 when `model` doesn't match a loaded model id
            log.error("LLM server returned an error: %s — %s", e, e.response.text[:300])
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            log.error("Unexpected LLM response shape: %r", e)
        return None

    def is_available(self) -> bool:
        try:
            return requests.get(self.v1_url + "/models", headers=self._headers(),
                                timeout=2).ok
        except requests.exceptions.RequestException:
            return False


class LMStudioClient(OpenAICompatibleClient):
    """LM Studio's OpenAI-compatible server (default http://localhost:1234/v1)."""

    def __init__(self, base_url: Optional[str] = None,
                 model: Optional[str] = None):
        root = (base_url or settings.lm_studio_url).rstrip("/")
        super().__init__(api_url=f"{root}/v1", model=model or settings.llm_model)
        self.base_url = root  # server root, as before; v1_url adds "/v1"


class MockLLMService(LLMService):
    """Mock LLM for testing — returns a fixed response."""

    def __init__(self, response: str = "This is a test response."):
        self._response = response

    def generate(self, messages: List[Dict[str, str]],
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> Optional[str]:
        return self._response
