from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from celery.result import AsyncResult
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import redis

from src.celery_app import celery_app
from src.skills import ClaimChartGenerator, TranslationVerifier
from src.tasks import run_patentflow_generate


app = FastAPI(title="PatentFlow API", version="0.1.0")


def _allowed_origins() -> List[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if origins:
            return origins
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]


def _json_size_bytes(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))


_STATUS_RESPONSE_MAX_BYTES = int(os.getenv("STATUS_RESPONSE_MAX_BYTES", "262144"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    office_action_text: str = Field(default="", description="Raw text extracted from OA (or user-provided text)")
    specification_text: str = Field(default="", description="Raw text extracted from specification")
    examiner_preference: str = Field(default="", description="Examiner preference bias label")
    claim_type: str = Field(default="Method", description="Claim category")


class GenerateResponse(BaseModel):
    task_id: str
    queue_position: Optional[int] = None
    queue_size: Optional[int] = None


class StatusResponse(BaseModel):
    task_id: str
    state: str
    meta: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class GenerateChartRequest(BaseModel):
    """Request schema for /api/generate-chart endpoint."""
    claim_text: str = Field(..., description="Patent claim text to analyze", min_length=10)
    prior_art_text: str = Field(default="", description="Prior art text (fallback if office_action_text empty)")
    office_action_text: str = Field(default="", description="Office action text with D1/D2 references")


class GenerateChartResponse(BaseModel):
    """Response schema for /api/generate-chart endpoint."""
    status: str = Field(default="success", description="Overall execution status")
    chart: List[Dict[str, Any]] = Field(default_factory=list, description="Generated claim chart rows")
    cited_docs: List[str] = Field(default_factory=list, description="List of cited documents (D1, D2, etc.)")
    error: Optional[str] = Field(default=None, description="Error message if status is error")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings")


class VerifyTranslationRequest(BaseModel):
    """Request schema for /api/verify-translation endpoint."""
    original_cn: str = Field(..., description="Original Chinese text segment", min_length=1)
    target_en: str = Field(..., description="Target English translation", min_length=1)
    back_cn: str = Field(default="", description="Back-translated Chinese for verification")


class VerifyTranslationResponse(BaseModel):
    """Response schema for /api/verify-translation endpoint."""
    status: str = Field(default="success", description="Overall execution status")
    rows: List[Dict[str, Any]] = Field(default_factory=list, description="Translation analysis rows")
    markdown_table: str = Field(default="", description="Markdown formatted table")
    overall_risk: str = Field(default="Safe", description="Overall risk assessment (Safe/Warning/CRITICAL)")
    error: Optional[str] = Field(default=None, description="Error message if status is error")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings")


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(_redis_url(), decode_responses=True)


_QUEUE_KEY = "patentflow:queue:z"
_QUEUE_SEQ_KEY = "patentflow:queue:seq"
_WORKFLOW_META_KEY_PREFIX = "patentflow:taskmeta:"


@app.post("/api/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    # Enqueue task and return immediately.
    async_result = run_patentflow_generate.delay(
        office_action_text=req.office_action_text,
        specification_text=req.specification_text,
        examiner_preference=req.examiner_preference,
        claim_type=req.claim_type,
    )

    queue_position: Optional[int] = None
    queue_size: Optional[int] = None
    try:
        r = _redis_client()
        # Put the task id into a visible queue sorted-set for UI position estimation.
        # Celery itself is the authoritative broker; this structure is UX-only.
        seq = r.incr(_QUEUE_SEQ_KEY)
        r.zadd(_QUEUE_KEY, {async_result.id: float(seq)})
        rank = r.zrank(_QUEUE_KEY, async_result.id)
        if rank is not None:
            queue_position = int(rank) + 1
        qsz = r.zcard(_QUEUE_KEY)
        queue_size = int(qsz) if qsz is not None else None
    except Exception:
        queue_position = None
        queue_size = None

    return GenerateResponse(task_id=async_result.id, queue_position=queue_position, queue_size=queue_size)


@app.get("/api/status/{task_id}", response_model=StatusResponse)
def status(task_id: str) -> StatusResponse:
    res = AsyncResult(task_id, app=celery_app)

    meta: Optional[Dict[str, Any]] = None
    if isinstance(res.info, dict):
        meta = res.info
    elif isinstance(res.info, str):
        meta = {"detail": res.info}

    # Enrich meta with queue position, if available.
    if meta is None:
        meta = {}

    queue_position: Optional[int] = None
    queue_size: Optional[int] = None
    try:
        r = _redis_client()
        rank = r.zrank(_QUEUE_KEY, task_id)
        if rank is not None:
            queue_position = int(rank) + 1
        qsz = r.zcard(_QUEUE_KEY)
        queue_size = int(qsz) if qsz is not None else None
    except Exception:
        queue_position = None
        queue_size = None

    if queue_position is not None and res.state in {"PENDING", "PROGRESS", "STARTED"}:
        meta.setdefault("queue_position", queue_position)
    if queue_size is not None and res.state in {"PENDING", "PROGRESS", "STARTED"}:
        meta.setdefault("queue_size", queue_size)

    # Fallback: workflow meta side-channel written by chain/chord subtasks.
    try:
        r = _redis_client()
        raw_meta = r.get(f"{_WORKFLOW_META_KEY_PREFIX}{task_id}")
        if raw_meta:
            workflow_meta = json.loads(raw_meta)
            if isinstance(workflow_meta, dict):
                for k, v in workflow_meta.items():
                    meta.setdefault(k, v)
    except Exception:
        pass

    payload = StatusResponse(task_id=task_id, state=res.state, meta=meta or None)

    if res.state == "SUCCESS":
        if meta is not None:
            meta.setdefault("percent", 100)
            meta.setdefault("substep_index", meta.get("substep_total", 5))
        try:
            # Use res.result directly for completed tasks (avoid timeout issues with get())
            result_obj = res.result if res.result is not None else res.get(timeout=1)
            if isinstance(result_obj, dict):
                result_size = _json_size_bytes(result_obj)
                if result_size > _STATUS_RESPONSE_MAX_BYTES:
                    payload.error = (
                        f"RESULT_TOO_LARGE: {result_size} bytes exceeds "
                        f"{_STATUS_RESPONSE_MAX_BYTES} bytes"
                    )
                    payload.result = {
                        "status": "omitted",
                        "reason": "Use artifact storage or dedicated download endpoint for large payloads.",
                        "result_size_bytes": result_size,
                        "max_response_bytes": _STATUS_RESPONSE_MAX_BYTES,
                    }
                else:
                    payload.result = result_obj
            else:
                boxed = {"value": result_obj}
                result_size = _json_size_bytes(boxed)
                if result_size > _STATUS_RESPONSE_MAX_BYTES:
                    payload.error = (
                        f"RESULT_TOO_LARGE: {result_size} bytes exceeds "
                        f"{_STATUS_RESPONSE_MAX_BYTES} bytes"
                    )
                    payload.result = {
                        "status": "omitted",
                        "reason": "Use artifact storage or dedicated download endpoint for large payloads.",
                        "result_size_bytes": result_size,
                        "max_response_bytes": _STATUS_RESPONSE_MAX_BYTES,
                    }
                else:
                    payload.result = boxed
        except Exception as e:
            payload.error = f"RESULT_DESERIALIZE_ERROR: {e}"

    if res.state == "FAILURE":
        payload.error = str(res.info)

    if res.state in {"SUCCESS", "FAILURE", "REVOKED"}:
        # Best-effort terminal cleanup for UX-only queue/meta keys.
        try:
            r = _redis_client()
            r.zrem(_QUEUE_KEY, task_id)
            r.delete(f"{_WORKFLOW_META_KEY_PREFIX}{task_id}")
        except Exception:
            pass

    return payload


@app.post("/api/generate-chart", response_model=GenerateChartResponse)
def generate_chart(req: GenerateChartRequest) -> GenerateChartResponse:
    """
    Generate a claim chart comparing claim features against prior art.
    
    Uses deterministic heuristic parsing for claim splitting and prior art matching.
    """
    try:
        generator = ClaimChartGenerator()
        result = generator.execute(
            claim_text=req.claim_text,
            prior_art_text=req.prior_art_text,
            office_action_text=req.office_action_text
        )
        
        return GenerateChartResponse(
            status=result.status,
            chart=result.data.get("chart", []),
            cited_docs=result.data.get("cited_docs", []),
            warnings=result.warnings
        )
    except Exception as e:
        return GenerateChartResponse(
            status="error",
            chart=[],
            cited_docs=[],
            error=f"CLAIM_CHART_GENERATION_ERROR: {str(e)}",
            warnings=["Failed to generate claim chart"]
        )


@app.post("/api/verify-translation", response_model=VerifyTranslationResponse)
def verify_translation(req: VerifyTranslationRequest) -> VerifyTranslationResponse:
    """
    Verify translation against glossary rules for Art. 123(2) compliance.
    
    Uses deterministic dictionary-based risk detection.
    """
    try:
        verifier = TranslationVerifier()
        result = verifier.execute(
            original_cn=req.original_cn,
            target_en=req.target_en,
            back_cn=req.back_cn
        )
        
        return VerifyTranslationResponse(
            status=result.status,
            rows=result.data.get("rows", []),
            markdown_table=result.data.get("markdown_table", ""),
            overall_risk=result.data.get("overall_risk", "Safe"),
            warnings=result.warnings
        )
    except Exception as e:
        return VerifyTranslationResponse(
            status="error",
            rows=[],
            markdown_table="",
            overall_risk="Unknown",
            error=f"TRANSLATION_VERIFICATION_ERROR: {str(e)}",
            warnings=["Failed to verify translation"]
        )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for all unhandled exceptions."""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": f"INTERNAL_SERVER_ERROR: {str(exc)}",
            "detail": "An unexpected error occurred. Please try again or contact support."
        }
    )


@app.get("/health")
async def health_check():
    """Health check probe for monitoring and load balancers."""
    return {"status": "PatentFlow Engine is online."}
