from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .base import BaseLLM, Message
from .cloud_engine import CloudEngine
from .local_engine import OllamaEngine
from .mock_engine import MockEngine
from src.memory_manager import LocalMemoryManager


_DEFAULT_SENSITIVE_PATTERNS = (
    r"\bApplication\s+No\b",
    r"\bClient\s+Name\b",
)


@dataclass
class PatentRouter:
    is_sensitive: bool
    local_engine: Optional[OllamaEngine] = None
    cloud_engine: Optional[CloudEngine] = None
    mock_engine: Optional[MockEngine] = None
    sensitive_patterns: Sequence[str] = _DEFAULT_SENSITIVE_PATTERNS

    def _scan_for_sensitive(self, text: str) -> bool:
        for pat in self.sensitive_patterns:
            if re.search(pat, text, flags=re.IGNORECASE):
                return True
        return False

    def _warn_if_mismatch(self, prompt: str, messages: Optional[Sequence[Message]]) -> None:
        if self.is_sensitive:
            return

        texts = [prompt]
        if messages:
            for m in messages:
                content = m.get("content")
                if isinstance(content, str):
                    texts.append(content)

        joined = "\n".join([t for t in texts if t])
        if joined and self._scan_for_sensitive(joined):
            warnings.warn(
                "Sensitive keywords detected but is_sensitive is False. "
                "Consider setting is_sensitive=True to force the local engine.",
                RuntimeWarning,
                stacklevel=2,
            )

    def _ollama_available(self, engine: OllamaEngine) -> bool:
        if not getattr(engine, "config", None) or not engine.config.base_url:
            return False

        try:
            resp = engine._session.get(f"{engine.config.base_url}/api/tags", timeout=2)
            return 200 <= resp.status_code < 300
        except Exception:
            return False

    def route(self) -> BaseLLM:
        local = self.local_engine or OllamaEngine()
        cloud = self.cloud_engine or CloudEngine()
        mock = self.mock_engine or MockEngine()

        local_ready = bool(getattr(local, "config", None) and local.config.model) and self._ollama_available(local)
        cloud_ready = cloud.is_configured()

        if self.is_sensitive:
            return local if local_ready else mock

        if cloud_ready:
            return cloud

        if local_ready:
            return local

        return mock

    def generate(
        self,
        *,
        task_type: str,
        prompt: str,
        messages: Optional[Sequence[Message]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: object,
    ) -> str:
        attorney_name = str(kwargs.get("attorney_name") or "").strip()
        if attorney_name:
            manager = LocalMemoryManager()
            prefs = manager.get_preferences(attorney_name)
            if prefs:
                injected = (
                    "[CRITICAL USER PREFERENCES TO FOLLOW STRICTLY]\n"
                    f"{prefs}\n"
                    "[/CRITICAL USER PREFERENCES]"
                )
                if messages is None:
                    messages = [
                        {"role": "system", "content": injected},
                        {"role": "user", "content": prompt},
                    ]
                else:
                    msgs = list(messages)
                    first_role = str((msgs[0] or {}).get("role") or "").strip().lower() if msgs else ""
                    if first_role == "system":
                        content = str((msgs[0] or {}).get("content") or "")
                        msgs[0] = {"role": "system", "content": (content + "\n\n" + injected).strip()}
                    else:
                        msgs.insert(0, {"role": "system", "content": injected})
                    messages = msgs

        self._warn_if_mismatch(prompt, messages)
        engine = self.route()
        return engine.generate(
            task_type=task_type,
            prompt=prompt,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )


def route_engine(*, is_sensitive: bool) -> BaseLLM:
    return PatentRouter(is_sensitive=is_sensitive).route()
