import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import requests
from dotenv import load_dotenv


Message = Mapping[str, str]


class BaseLLM(ABC):
    @abstractmethod
    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        raise NotImplementedError


@dataclass
class LocalLLMConfig:
    base_url: str
    model: str
    timeout: int = 60


class LocalLLM(BaseLLM):
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 60,
    ) -> None:
        load_dotenv(override=False)

        resolved_base_url = base_url or os.getenv("LLM_BASE_URL") or "http://127.0.0.1:11434"
        resolved_model = model or os.getenv("LLM_MODEL") or ""

        self.config = LocalLLMConfig(base_url=resolved_base_url.rstrip("/"), model=resolved_model, timeout=timeout)
        self._session = requests.Session()

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        if not self.config.model:
            raise RuntimeError("LocalLLM requires LLM_MODEL to be configured.")

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

        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama response did not include message.content")
        return content


@dataclass
class CloudLLMConfig:
    provider: str
    api_key: str
    model: str
    base_url: Optional[str] = None
    timeout: int = 60


class CloudLLM(BaseLLM):
    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 60,
    ) -> None:
        load_dotenv(override=False)

        resolved_provider = (provider or os.getenv("CLOUD_PROVIDER") or "").strip().lower()
        resolved_model = (model or os.getenv("CLOUD_MODEL") or "").strip()

        resolved_api_key = api_key
        if resolved_api_key is None:
            if resolved_provider == "openai":
                resolved_api_key = os.getenv("OPENAI_API_KEY")
            elif resolved_provider == "anthropic":
                resolved_api_key = os.getenv("ANTHROPIC_API_KEY")
            else:
                resolved_api_key = os.getenv("CLOUD_API_KEY")

        if resolved_api_key is None:
            resolved_api_key = ""

        resolved_base_url = base_url or os.getenv("CLOUD_BASE_URL")

        self.config = CloudLLMConfig(
            provider=resolved_provider,
            api_key=resolved_api_key,
            model=resolved_model,
            base_url=resolved_base_url.rstrip("/") if resolved_base_url else None,
            timeout=timeout,
        )
        self._session = requests.Session()

    def is_configured(self) -> bool:
        return bool(self.config.provider and self.config.api_key and self.config.model)

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        if not self.is_configured():
            raise RuntimeError(
                "CloudLLM is not configured. Set CLOUD_PROVIDER and CLOUD_MODEL and the provider API key."
            )

        if self.config.provider == "openai":
            return self._chat_openai(messages, temperature=temperature, max_tokens=max_tokens)
        if self.config.provider == "anthropic":
            return self._chat_anthropic(messages, temperature=temperature, max_tokens=max_tokens)

        raise RuntimeError(f"Unsupported CLOUD_PROVIDER: {self.config.provider!r}. Use 'openai' or 'anthropic'.")

    def _chat_openai(
        self,
        messages: Sequence[Message],
        *,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        base_url = self.config.base_url or "https://api.openai.com"
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": list(messages),
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        resp = self._session.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenAI response did not include choices")
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenAI response did not include message.content")
        return content

    def _chat_anthropic(
        self,
        messages: Sequence[Message],
        *,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        base_url = self.config.base_url or "https://api.anthropic.com"

        system_text = ""
        user_messages: List[Dict[str, Any]] = []
        for m in messages:
            role = (m.get("role") or "").strip().lower()
            content = m.get("content") or ""
            if role == "system":
                system_text = f"{system_text}\n{content}".strip() if system_text else content
            else:
                user_messages.append({"role": role or "user", "content": content})

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": user_messages,
            "max_tokens": int(max_tokens) if max_tokens is not None else 1024,
        }
        if system_text:
            payload["system"] = system_text
        if temperature is not None:
            payload["temperature"] = temperature

        resp = self._session.post(
            f"{base_url.rstrip('/')}/v1/messages",
            json=payload,
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        content_blocks = data.get("content")
        if not isinstance(content_blocks, list) or not content_blocks:
            raise RuntimeError("Anthropic response did not include content")

        texts: List[str] = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
        result = "".join(texts).strip()
        if not result:
            raise RuntimeError("Anthropic response did not include any text content")
        return result


def route_llm(
    *,
    task_tags: Optional[Iterable[str]] = None,
    local_llm: Optional[BaseLLM] = None,
    cloud_llm: Optional[CloudLLM] = None,
) -> BaseLLM:
    tags = {t.strip().lower() for t in (task_tags or []) if t and t.strip()}

    local = local_llm or LocalLLM()
    cloud = cloud_llm or CloudLLM()

    if "sensitive_data" in tags:
        return local

    if isinstance(cloud, CloudLLM) and cloud.is_configured():
        return cloud

    return local
