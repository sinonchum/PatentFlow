from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field


class SkillResult(BaseModel):
    """Standardized envelope for all skill outputs.
    
    Ensures frontend always receives a stable JSON structure with status,
    data payload, and optional error/warning metadata.
    """
    status: Literal["success", "error", "partial"] = Field(
        default="success",
        description="Overall execution status"
    )
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Skill-specific payload for frontend consumption"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if status is 'error'"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings for attorney review"
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Execution metadata (timing, cache hits, etc.)"
    )


T = TypeVar('T', bound=SkillResult)


class PatentAgentSkill(ABC, Generic[T]):
    """
    Base class for all PatentFlow deterministic skills.
    Ensures every skill has a clear input/output boundary with pydantic validation.
    """

    def __init__(self, llm_client=None):
        # Pass the local LLM client (e.g., Ollama or vLLM) here
        self.llm = llm_client

    @abstractmethod
    def execute(self, **kwargs) -> T:
        """
        Must return a SkillResult containing at least:
        - 'status': 'success', 'error', or 'partial'
        - 'data': The specific payload for the frontend UI
        - 'warnings': List of attorney-reviewable alerts
        """
        pass

    def _ok(self, data: Dict[str, Any], meta: Optional[Dict[str, Any]] = None) -> T:
        """Helper to return successful result."""
        return SkillResult(
            status="success",
            data=data,
            meta=meta or {}
        )  # type: ignore

    def _err(self, message: str, data: Optional[Dict[str, Any]] = None) -> T:
        """Helper to return error result."""
        return SkillResult(
            status="error",
            error=message,
            data=data or {}
        )  # type: ignore

    def _partial(self, data: Dict[str, Any], warnings: List[str], meta: Optional[Dict[str, Any]] = None) -> T:
        """Helper to return partial success with warnings."""
        return SkillResult(
            status="partial",
            data=data,
            warnings=warnings,
            meta=meta or {}
        )  # type: ignore
