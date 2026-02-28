from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Mapping, Optional, Sequence


Message = Mapping[str, str]


class BaseLLM(ABC):
    @abstractmethod
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
        raise NotImplementedError
