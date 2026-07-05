"""LLM service — interfaces with LM Studio / OpenAI-compatible API."""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import requests
import json

from config import settings


class LLMService(ABC):
    """Abstract LLM service — supports LM Studio and OpenAI."""

    @abstractmethod
    def generate(self, messages: List[Dict[str, str]],
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> Optional[str]:
        """Generate a response from the LLM given a message list."""
        pass


class LMStudioClient(LLMService):
    """Client for LM Studio's OpenAI-compatible API endpoint."""

    def __init__(self, base_url: Optional[str] = None,
                 model: Optional[str] = None):
        self.base_url = (base_url or settings.lm_studio_url).rstrip("/")
        self.model = model or settings.llm_model
        self.api_url = f"{self.base_url}/v1/chat/completions"

    def generate(self, messages: List[Dict[str, str]],
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> Optional[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or settings.temperature,
            "max_tokens": max_tokens or settings.max_tokens,
        }

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=120,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

        except requests.exceptions.ConnectionError:
            print(f"❌ Cannot connect to LM Studio at {self.base_url}")
            print("   Start LM Studio, load model, and enable server.")
            return None
        except requests.exceptions.Timeout:
            print("❌ LM Studio request timed out (120s)")
            return None
        except (KeyError, json.JSONDecodeError) as e:
            print(f"❌ Invalid response from LM Studio: {e}")
            return None
        except Exception as e:
            print(f"❌ LM Studio error: {e}")
            return None


class OpenAICompatibleClient(LLMService):
    """Generic client for any OpenAI-compatible API."""

    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model

    def generate(self, messages: List[Dict[str, str]],
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> Optional[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or settings.temperature,
            "max_tokens": max_tokens or settings.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self.api_url, json=payload, headers=headers, timeout=120
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"❌ API error: {e}")
            return None


class MockLLMService(LLMService):
    """Mock LLM for testing — returns a fixed response."""

    def __init__(self, response: str = "This is a test response."):
        self._response = response

    def generate(self, messages: List[Dict[str, str]],
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> Optional[str]:
        return self._response
