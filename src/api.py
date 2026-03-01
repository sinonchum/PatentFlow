from __future__ import annotations

import os
from typing import Any, Dict, Optional

from celery.result import AsyncResult
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import redis

from src.celery_app import celery_app
from src.tasks import run_patentflow_generate


app = FastAPI(title="PatentFlow API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"] ,
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


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(_redis_url(), decode_responses=True)


_QUEUE_KEY = "patentflow:queue:z"
_QUEUE_SEQ_KEY = "patentflow:queue:seq"


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

    payload = StatusResponse(task_id=task_id, state=res.state, meta=meta or None)

    if res.state == "SUCCESS":
        try:
            # Use res.result directly for completed tasks (avoid timeout issues with get())
            result_obj = res.result if res.result is not None else res.get(timeout=1)
            if isinstance(result_obj, dict):
                payload.result = result_obj
            else:
                payload.result = {"value": result_obj}
        except Exception as e:
            payload.error = str(e)

    if res.state == "FAILURE":
        payload.error = str(res.info)

    return payload
