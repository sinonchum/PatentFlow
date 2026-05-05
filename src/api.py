from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from celery.result import AsyncResult
import io

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import redis

from src.celery_app import celery_app
from src.engine.router import PatentRouter
from src.memory_manager import LocalMemoryManager
from src.services.epo_client import EPOClient
from src.services.tasks import process_epo_request
from src.skills import ClaimChartGenerator, TranslationVerifier
from src.tasks import run_patentflow_generate


memory_db = LocalMemoryManager()


class _LLMChatAdapter:
    """Adapts engine BaseLLM.generate() to the chat(messages) interface expected by skills."""

    def __init__(self, engine):
        self._engine = engine

    def chat(self, messages, **kwargs):
        prompt = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                prompt = m.get("content", "")
                break
        return self._engine.generate(
            task_type="claim_chart",
            prompt=prompt,
            messages=messages,
        )


def _get_llm_client():
    """Get an LLM client for skill usage, returns None if no engine available."""
    try:
        router = PatentRouter(is_sensitive=True)
        engine = router.route()
        # Check if it's a real engine (not mock)
        from src.engine.mock_engine import MockEngine
        if isinstance(engine, MockEngine):
            return None
        return _LLMChatAdapter(engine)
    except Exception:
        return None


app = FastAPI(title="PatentFlow API", version="0.1.0")

# --- API Key Authentication ---
_PATENTFLOW_API_KEY = os.getenv("PATENTFLOW_API_KEY", "").strip()
_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


@app.middleware("http")
async def api_key_auth(request, call_next):
    """Require X-API-Key or Authorization: Bearer header when PATENTFLOW_API_KEY is set."""
    if not _PATENTFLOW_API_KEY or request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    provided_key = request.headers.get("X-API-Key", "")
    if not provided_key:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            provided_key = auth_header[7:].strip()

    if provided_key != _PATENTFLOW_API_KEY:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=401,
            content={"status": "error", "error": "UNAUTHORIZED", "detail": "Invalid or missing API key."},
        )
    return await call_next(request)


def _allowed_origins() -> List[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if origins:
            return origins
    return [
        "http://localhost:3000",
        "http://localhost:3001",
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
    attorney_name: str = Field(default="", description="Attorney identity for local preference memory")


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
    claim_text: str = Field(default="", description="Patent claim text to analyze (required unless publication_number is set)")
    prior_art_text: str = Field(default="", description="Prior art text (fallback if office_action_text empty)")
    office_action_text: str = Field(default="", description="Office action text with D1/D2 references")
    attorney_id: str = Field(default="Default", description="Attorney identity for local preference memory")
    publication_number: str = Field(
        default="",
        description="EPO publication number (e.g. EP3654128). When set and claim_text is empty, "
                    "claims are fetched automatically via OPS. Requires EPO_ENABLED=true.",
    )


class GenerateChartResponse(BaseModel):
    """Response schema for /api/generate-chart endpoint."""
    status: str = Field(default="success", description="Overall execution status")
    chart: List[Dict[str, Any]] = Field(default_factory=list, description="Generated claim chart rows")
    cited_docs: List[str] = Field(default_factory=list, description="List of cited documents (D1, D2, etc.)")
    error: Optional[str] = Field(default=None, description="Error message if status is error")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings")


class MemoryAddRequest(BaseModel):
    attorney_id: str = Field(..., min_length=1, description="Attorney identifier")
    new_rule: str = Field(..., min_length=1, description="New rule to append")


class MemorySaveRequest(BaseModel):
    """Frontend-compatible memory save — accepts phrasing_rule or examiner_strategy."""
    phrasing_rule: Optional[str] = Field(default=None)
    examiner_strategy: Optional[str] = Field(default=None)


class EPOIngestRequest(BaseModel):
    """Request schema for /api/epo/ingest endpoint."""
    publication_number: str = Field(
        default="",
        description="EPO publication number (e.g. EP3654128). Triggers OPS full-text fetch.",
    )
    application_number: str = Field(
        default="",
        description="EPO application number (e.g. EP21158904). Triggers Register dossier sync.",
    )
    use_language_bridge: bool = Field(
        default=True,
        description="Automatically find an English-language family member for non-EN patents.",
    )
    claim_type: str = Field(default="Method", description="Claim category for chart generation")
    attorney_name: str = Field(default="", description="Attorney identity for preference memory")


class EPOIngestResponse(BaseModel):
    """Response schema for /api/epo/ingest endpoint."""
    task_id: str
    queue_position: Optional[int] = None
    queue_size: Optional[int] = None


class VerifyTranslationRequest(BaseModel):
    """Request schema for /api/verify-translation endpoint."""
    original_cn: str = Field(..., description="Original Chinese text segment", min_length=1)
    target_en: str = Field(..., description="Target English translation", min_length=1)
    back_cn: str = Field(default="", description="Back-translated Chinese for verification")
    attorney_id: str = Field(default="Default", description="Attorney identity for local preference memory")


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


_redis_singleton: Optional[redis.Redis] = None


def _redis_client() -> redis.Redis:
    global _redis_singleton
    if _redis_singleton is None:
        _redis_singleton = redis.Redis.from_url(_redis_url(), decode_responses=True)
    return _redis_singleton


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
        attorney_name=req.attorney_name,
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


@app.post("/api/epo/ingest", response_model=EPOIngestResponse)
def epo_ingest(req: EPOIngestRequest) -> EPOIngestResponse:
    """Dispatch an EPO ingest + claim chart pipeline to Celery.

    Accepts a publication number (fetches from OPS) and/or an application number
    (syncs the latest Art. 94(3) communication from Register). Returns a task_id
    for status polling via GET /api/status/{task_id}.

    Requires EPO_ENABLED=true and valid EPO_CONSUMER_KEY / EPO_CONSUMER_SECRET in .env.
    """
    from fastapi import HTTPException

    _epo_enabled = os.getenv("EPO_ENABLED", "false").lower() == "true"
    if not _epo_enabled:
        raise HTTPException(
            status_code=503,
            detail="EPO integration is disabled. Set EPO_ENABLED=true in .env to enable.",
        )

    if not req.publication_number and not req.application_number:
        raise HTTPException(
            status_code=422,
            detail="At least one of publication_number or application_number is required.",
        )

    async_result = process_epo_request.delay(
        publication_number=req.publication_number,
        application_number=req.application_number,
        use_language_bridge=req.use_language_bridge,
        claim_type=req.claim_type,
        attorney_name=req.attorney_name,
    )

    queue_position: Optional[int] = None
    queue_size: Optional[int] = None
    try:
        r = _redis_client()
        seq = r.incr(_QUEUE_SEQ_KEY)
        r.zadd(_QUEUE_KEY, {async_result.id: float(seq)})
        rank = r.zrank(_QUEUE_KEY, async_result.id)
        if rank is not None:
            queue_position = int(rank) + 1
        qsz = r.zcard(_QUEUE_KEY)
        queue_size = int(qsz) if qsz is not None else None
    except Exception:
        pass

    return EPOIngestResponse(
        task_id=async_result.id,
        queue_position=queue_position,
        queue_size=queue_size,
    )


@app.post("/api/generate-chart", response_model=GenerateChartResponse)
async def generate_chart(req: GenerateChartRequest) -> GenerateChartResponse:
    """Generate a claim chart comparing claim features against prior art.

    If publication_number is set and claim_text is empty, claims are fetched
    automatically from EPO OPS (requires EPO_ENABLED=true).
    Uses deterministic heuristic parsing for claim splitting and prior art matching.
    """
    claim_text = req.claim_text.strip()
    prior_art_text = req.prior_art_text
    office_action_text = req.office_action_text

    if req.publication_number and not claim_text:
        _epo_enabled = os.getenv("EPO_ENABLED", "false").lower() == "true"
        if not _epo_enabled:
            return GenerateChartResponse(
                status="error",
                chart=[],
                cited_docs=[],
                error=(
                    "EPO integration is disabled. Set EPO_ENABLED=true in .env "
                    "to use publication_number, or provide claim_text directly."
                ),
                warnings=[],
            )
        try:
            async with EPOClient() as epo:
                metadata = await epo.smart_fetch(req.publication_number)
            claim_text = metadata.claims_text
            if not prior_art_text and not office_action_text:
                prior_art_text = metadata.abstract
        except Exception as e:
            return GenerateChartResponse(
                status="error",
                chart=[],
                cited_docs=[],
                error=f"EPO_FETCH_ERROR ({req.publication_number}): {str(e)}",
                warnings=["EPO API call failed; provide claim_text directly as a fallback."],
            )

    if not claim_text:
        return GenerateChartResponse(
            status="error",
            chart=[],
            cited_docs=[],
            error="No claim text available. Provide claim_text or a valid publication_number.",
            warnings=[],
        )

    try:
        llm_client = _get_llm_client()
        generator = ClaimChartGenerator(llm_client=llm_client)
        result = generator.execute(
            claim_text=claim_text,
            prior_art_text=prior_art_text,
            office_action_text=office_action_text,
            attorney_id=req.attorney_id,
        )

        return GenerateChartResponse(
            status=result.status,
            chart=result.data.get("chart", []),
            cited_docs=result.data.get("cited_docs", []),
            warnings=result.warnings,
        )
    except Exception as e:
        return GenerateChartResponse(
            status="error",
            chart=[],
            cited_docs=[],
            error=f"CLAIM_CHART_GENERATION_ERROR: {str(e)}",
            warnings=["Failed to generate claim chart"],
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


@app.get("/api/memory/{attorney_id}")
def get_memory(attorney_id: str) -> Dict[str, str]:
    try:
        prefs = memory_db.get_preferences(attorney_id)
        return {"status": "success", "preferences": prefs}
    except Exception as e:
        return {"status": "error", "preferences": "", "error": f"MEMORY_GET_ERROR: {str(e)}"}


@app.post("/api/memory/add")
def add_memory(req: MemoryAddRequest) -> Dict[str, str]:
    try:
        ok = memory_db.add_preference(req.attorney_id, req.new_rule)
        if not ok:
            return {"status": "error", "error": "MEMORY_ADD_FAILED"}
        prefs = memory_db.get_preferences(req.attorney_id)
        return {"status": "success", "preferences": prefs}
    except Exception as e:
        return {"status": "error", "error": f"MEMORY_ADD_ERROR: {str(e)}"}


@app.post("/api/memory/{attorney_id}")
def save_memory(attorney_id: str, req: MemorySaveRequest) -> Dict[str, str]:
    """Frontend-compatible endpoint: POST /api/memory/{attorney_id} with phrasing_rule or examiner_strategy."""
    try:
        rule = req.phrasing_rule or req.examiner_strategy or ""
        rule = rule.strip()
        if not rule:
            return {"status": "error", "error": "No rule provided"}
        ok = memory_db.add_preference(attorney_id, rule)
        if not ok:
            return {"status": "error", "error": "MEMORY_ADD_FAILED"}
        prefs = memory_db.get_preferences(attorney_id)
        return {"status": "success", "preferences": prefs}
    except Exception as e:
        return {"status": "error", "error": f"MEMORY_ADD_ERROR: {str(e)}"}


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Extract plain text from an uploaded PDF, DOCX, or TXT file.

    Used by the frontend to convert uploaded documents to text before sending
    to the pipeline. Handles PDF via PyMuPDF, DOCX via python-docx, and
    falls back to UTF-8 decoding for plain text files.
    """
    filename = file.filename or "document"
    content = await file.read()
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    try:
        if ext == "pdf":
            doc = fitz.open(stream=content, filetype="pdf")
            pages_text = [page.get_text() for page in doc]
            doc.close()
            text = "\n\n".join(t for t in pages_text if t.strip())
            if not text.strip():
                return {
                    "status": "error",
                    "error": "PDF appears to be scanned (image-only). Please use a text-based PDF or paste the text directly.",
                    "text": "",
                    "filename": filename,
                }
            return {"status": "success", "text": text, "filename": filename, "pages": len(pages_text)}

        if ext == "docx":
            doc_x = DocxDocument(io.BytesIO(content))
            text = "\n".join(p.text for p in doc_x.paragraphs if p.text.strip())
            return {"status": "success", "text": text, "filename": filename}

        # TXT or any other format — decode as UTF-8
        text = content.decode("utf-8", errors="replace")
        return {"status": "success", "text": text, "filename": filename}

    except Exception as e:
        return {"status": "error", "error": f"Extraction failed: {str(e)}", "text": "", "filename": filename}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for all unhandled exceptions."""
    import logging
    from fastapi.responses import JSONResponse

    logger = logging.getLogger("patentflow.api")
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": "INTERNAL_SERVER_ERROR",
            "detail": "An unexpected error occurred. Please try again or contact support.",
        },
    )


@app.get("/health")
async def health_check():
    """Health check probe for monitoring and load balancers."""
    return {"status": "PatentFlow Engine is online."}
