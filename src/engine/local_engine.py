from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence

import requests
from dotenv import load_dotenv

from .base import BaseLLM, Message


@dataclass
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = ""
    timeout: int = 60
    api_key: str = ""
    # True when base_url is an OpenAI-compatible endpoint (not Ollama native)
    openai_compatible: bool = False


class OllamaEngine(BaseLLM):
    """Local engine intended for sensitive work such as 客户草案 / 答辩策略.

    Supports both Ollama native API (/api/chat) and OpenAI-compatible
    endpoints (/v1/chat/completions).  When LLM_BASE_URL is not the
    default Ollama address, it automatically switches to OpenAI mode.
    """

    SUPPORTED_TASK_TYPES = {"客户草案", "答辩策略", "claim_chart", "translation_verification", "response_draft"}

    # Default Ollama base URL used to detect native vs. compatible mode
    _OLLAMA_DEFAULT = "http://127.0.0.1:11434"

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 60,
        api_key: Optional[str] = None,
    ) -> None:
        load_dotenv(override=False)

        resolved_base_url = (base_url or os.getenv("LLM_BASE_URL") or self._OLLAMA_DEFAULT).rstrip("/")
        resolved_model = (model or os.getenv("LLM_MODEL") or "").strip()
        resolved_api_key = (api_key or os.getenv("LLM_API_KEY") or "").strip()

        # Auto-detect: if base_url is not the default Ollama address, use OpenAI-compatible mode
        openai_compat = resolved_base_url != self._OLLAMA_DEFAULT

        self.config = OllamaConfig(
            base_url=resolved_base_url,
            model=resolved_model,
            timeout=timeout,
            api_key=resolved_api_key,
            openai_compatible=openai_compat,
        )
        self._session = requests.Session()

    def generate(
        self,
        *,
        task_type: str,
        prompt: str,
        messages: Optional[Sequence[Message]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        if self.config.model == "":
            raise RuntimeError("OllamaEngine requires LLM_MODEL to be configured.")

        if task_type not in self.SUPPORTED_TASK_TYPES:
            raise RuntimeError(
                f"OllamaEngine is intended for {sorted(self.SUPPORTED_TASK_TYPES)}; got task_type={task_type!r}."
            )

        if messages is None:
            messages = [{"role": "user", "content": prompt}]

        if self.config.openai_compatible:
            return self._generate_openai_compatible(
                messages, temperature=temperature, max_tokens=max_tokens
            )
        return self._generate_ollama_native(
            messages, temperature=temperature
        )

    # -- OpenAI-compatible path (e.g. r9s.ai, OpenRouter, vLLM) --

    def _generate_openai_compatible(
        self,
        messages: Sequence[Message],
        *,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": list(messages),
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        # base_url may already include /v1, so avoid doubling it
        base = self.config.base_url.rstrip("/")
        if base.endswith("/v1"):
            chat_url = f"{base}/chat/completions"
        else:
            chat_url = f"{base}/v1/chat/completions"

        resp = self._session.post(
            chat_url,
            json=payload,
            headers=headers,
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenAI-compatible response did not include choices")
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenAI-compatible response did not include message.content")
        return content

    # -- Ollama native path (original) --

    def _generate_ollama_native(
        self,
        messages: Sequence[Message],
        *,
        temperature: Optional[float],
    ) -> str:
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": list(messages),
            "stream": False,
        }

        options: Dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if options:
            payload["options"] = options

        resp = self._session.post(
            f"{self.config.base_url}/api/chat",
            json=payload,
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        msg = data.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama response did not include message.content")
        return content
