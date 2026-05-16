from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from dotenv import load_dotenv
from openai import AsyncOpenAI

from .base import BaseLLM, Message


class FastinoJSONParsingError(RuntimeError):
    """Raised when Fastino response cannot be parsed as valid JSON."""


@dataclass
class FastinoConfig:
    api_key: str = ""
    base_url: str = "https://api.pioneer.ai/v1"
    model_id: str = "59d36fbf-6e40-4e07-96d5-617d321842e8"
    temperature: float = 0.0
    max_tokens: int = 2048
    timeout: int = 30


class FastinoEngine(BaseLLM):
    """Isolated Fastino Pioneer client for privacy-mode PatentFlow analysis.

    Uses OpenAI-compatible chat completions via the Pioneer inference endpoint.
    Enforcing zero temperature for deterministic attorney outputs.
    """

    SUPPORTED_TASK_TYPES = {
        "oa_analysis",
        "claim_chart",
        "translation_verification",
        "response_draft",
    }

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_id: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: int = 30,
    ) -> None:
        load_dotenv(override=False)

        self.config = FastinoConfig(
            api_key=api_key or os.getenv("FASTINO_API_KEY", ""),
            base_url=(base_url or os.getenv("FASTINO_BASE_URL", "https://api.pioneer.ai/v1")).rstrip("/"),
            model_id=model_id or os.getenv("FASTINO_MODEL_ID", "59d36fbf-6e40-4e07-96d5-617d321842e8"),
            temperature=temperature if temperature is not None else 0.0,
            max_tokens=max_tokens if max_tokens is not None else 2048,
            timeout=timeout,
        )

        if not self.config.api_key:
            raise RuntimeError("FastinoEngine requires FASTINO_API_KEY to be set.")

        self._client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.config.api_key and self.config.model_id)

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
        """Synchronous wrapper for Fastino async inference.

        This bridges the existing BaseLLM.generate() interface.
        In a full async context (Phase 3 shadow routing) the caller
        can use generate_async() directly.
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        asyncio.run, self.generate_async(
                            task_type=task_type,
                            prompt=prompt,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            **kwargs,
                        )
                    )
                    return future.result(timeout=self.config.timeout + 10)
            return loop.run_until_complete(
                self.generate_async(
                    task_type=task_type,
                    prompt=prompt,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            )
        except RuntimeError:
            return asyncio.run(
                self.generate_async(
                    task_type=task_type,
                    prompt=prompt,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            )

    async def generate_async(
        self,
        *,
        task_type: str,
        prompt: str,
        messages: Optional[Sequence[Message]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Call Fastino Pioneer model with attorney-style JSON output enforced."""
        if task_type not in self.SUPPORTED_TASK_TYPES:
            raise RuntimeError(
                f"FastinoEngine supports {sorted(self.SUPPORTED_TASK_TYPES)}; "
                f"got task_type={task_type!r}."
            )

        resolved_messages: list[dict[str, str]] = (
            [dict(m) for m in messages]
            if messages
            else [{"role": "user", "content": prompt}]
        )

        response = await self._client.chat.completions.create(
            model=self.config.model_id,
            messages=resolved_messages,
            temperature=temperature if temperature is not None else self.config.temperature,
            max_tokens=max_tokens if max_tokens is not None else self.config.max_tokens,
        )

        content = response.choices[0].message.content or ""

        # Validate attorney output is parseable JSON
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise FastinoJSONParsingError(
                f"Fastino response for {task_type} is not valid JSON: {exc}"
            ) from exc

        return content

    async def analyze_epc_objection(
        self,
        *,
        office_action_text: str,
        attorney_profile: str = "Default",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience method for EPC objection extraction.

        Returns a parsed dict with article / affected_claims / severity /
        examiner_reasoning / recommended_action.
        """
        system_msg = (
            "You are a European Patent Attorney assistant. "
            "Extract EPC objections from the Office Action text "
            "and output ONLY valid JSON."
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Extract EPC objections: {office_action_text}"},
        ]
        raw = await self.generate_async(
            task_type="oa_analysis",
            prompt=office_action_text,
            messages=messages,
            **kwargs,
        )
        return json.loads(raw)
