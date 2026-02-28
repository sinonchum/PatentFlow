from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

import requests
from dotenv import load_dotenv

from .base import BaseLLM, Message


@dataclass
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = ""
    timeout: int = 60


class OllamaEngine(BaseLLM):
    """Local engine intended for sensitive work such as 客户草案 / 答辩策略."""

    SUPPORTED_TASK_TYPES = {"客户草案", "答辩策略"}

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 60,
    ) -> None:
        load_dotenv(override=False)

        resolved_base_url = (base_url or os.getenv("LLM_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
        resolved_model = (model or os.getenv("LLM_MODEL") or "").strip()

        self.config = OllamaConfig(base_url=resolved_base_url, model=resolved_model, timeout=timeout)
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
        else:
            messages = list(messages)

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
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
