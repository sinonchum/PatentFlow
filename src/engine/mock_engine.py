from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .base import BaseLLM, Message


@dataclass
class MockEngine(BaseLLM):
    """A deterministic engine for local debugging when no AI is available."""

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
        normalized = (task_type or "").strip()

        if normalized in {"已公开专利", "专利请求"}:
            return "Mock: Analysis of claim 1..."
        if normalized in {"法律条文查询"}:
            return "Mock: Retrieved relevant statutes and summarized key points..."
        if normalized in {"客户草案"}:
            return "Mock: Draft for client document..."
        if normalized in {"答辩策略"}:
            return "Mock: Defense strategy outline..."

        return "Mock: Response generated for debugging..."
