from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

from celery import chain, chord
import redis

from src.celery_app import celery_app
from src.skills import ClaimChartGenerator, TranslationVerifier
from src.translator import PatentTranslator  # Keep for backward compat fallback


# Legacy adapter functions for backward compatibility
def generate_claim_chart(claim_text: str, prior_art_text: str, office_action_text: str = "") -> Dict[str, Any]:
    """Backward-compatible adapter using new ClaimChartGenerator skill."""
    generator = ClaimChartGenerator()
    result = generator.execute(
        claim_text=claim_text,
        prior_art_text=prior_art_text,
        office_action_text=office_action_text
    )
    # Map new field names to legacy format expected by frontend
    chart_data = result.data.get("chart", [])
    legacy_chart = []
    for row in chart_data:
        legacy_chart.append({
            "feature_id": row.get("feature_id", ""),
            "claim_limitation": row.get("limitation", ""),
            "disclosure": row.get("d1_disclosure", ""),
            "assessment": row.get("assessment", ""),
            "attorney_remarks": row.get("remarks", ""),
            "prior_art_mapping": row.get("d1_disclosure", ""),
            "status": row.get("assessment", ""),
            "evidence_source": "D1",
            "d1_mapping": row.get("d1_disclosure", ""),
        })
    return {
        "status": result.status,
        "claim_chart": legacy_chart,
        "cited_docs": result.data.get("cited_docs", []),
    }


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(_redis_url(), decode_responses=True)


_QUEUE_KEY = "patentflow:queue:z"
_WORKFLOW_META_KEY_PREFIX = "patentflow:taskmeta:"
_RESULT_BACKEND_MAX_BYTES = int(os.getenv("RESULT_BACKEND_MAX_BYTES", "262144"))
_LARGE_PAYLOAD_KEYS = ("base64", "blob", "binary")
_SUBSTEP_TOTAL = 5


def _json_size_bytes(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))


def _sanitize_backend_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Keep Celery result backend payloads compact and JSON-safe.

    Large binary/base64 artifacts should go to file/object storage and be returned
    by reference, not inlined into Redis/RPC result backend payloads.
    """
    out = dict(payload)
    omitted_keys = []

    for k in list(out.keys()):
        lk = k.lower()
        if any(token in lk for token in _LARGE_PAYLOAD_KEYS):
            if out[k]:
                omitted_keys.append(k)
            out.pop(k, None)

    size = _json_size_bytes(out)
    if size > _RESULT_BACKEND_MAX_BYTES:
        # Keep essential keys and mark overflow to avoid oversized backend records.
        out = {
            "status": out.get("status", "success"),
            "warning": "RESULT_TOO_LARGE_FOR_BACKEND",
            "result_size_bytes": size,
            "max_backend_bytes": _RESULT_BACKEND_MAX_BYTES,
            "artifact_hint": "Persist large outputs in artifact storage and return a reference.",
        }

    if omitted_keys:
        out["omitted_artifact_keys"] = omitted_keys

    return out


def _set_workflow_meta(workflow_id: str, step: str, extra: Optional[Dict[str, Any]] = None) -> None:
    if not workflow_id:
        return
    try:
        r = _redis_client()
        meta: Dict[str, Any] = {"step": step}
        if extra:
            meta.update(extra)
        r.setex(f"{_WORKFLOW_META_KEY_PREFIX}{workflow_id}", 24 * 3600, json.dumps(meta, ensure_ascii=False))
    except Exception:
        pass


def _progress_fields(index: int, total: int = _SUBSTEP_TOTAL) -> Dict[str, int]:
    safe_index = max(0, min(index, total))
    percent = int((safe_index / max(total, 1)) * 100)
    return {
        "substep_index": safe_index,
        "substep_total": total,
        "percent": percent,
    }


@celery_app.task(autoretry_for=(Exception,), max_retries=3, retry_backoff=True)
def parse_docs(
    *,
    office_action_text: str = "",
    specification_text: str = "",
    examiner_preference: str = "",
    claim_type: str = "Method",
    workflow_id: str = "",
) -> Dict[str, Any]:
    _set_workflow_meta(workflow_id, "Parsing Office Action", _progress_fields(1))
    time.sleep(0.1)

    # Remove from UX queue once execution begins.
    if workflow_id:
        try:
            _redis_client().zrem(_QUEUE_KEY, workflow_id)
        except Exception:
            pass

    claim_text = (
        "A method for wireless communication, comprising: transmitting a downlink control information (DCI) format; "
        "determining a timing offset K0; and receiving a physical downlink shared channel (PDSCH) based on the timing offset."
    )
    if specification_text and len(specification_text.strip()) > 20:
        claim_text = specification_text.strip()
    
    prior_art_text = "D1 discloses a wireless communication system with fixed timing relations."
    if specification_text and len(specification_text) > 50:
        prior_art_text = (specification_text[:200] + "...").replace("\n", " ")
    
    # Load mock office action if none provided (for demo purposes)
    if not office_action_text:
        try:
            mock_path = os.path.join(os.path.dirname(__file__), "..", "mock_office_action_ep.txt")
            if os.path.exists(mock_path):
                with open(mock_path, "r", encoding="utf-8") as f:
                    office_action_text = f.read()
        except Exception:
            pass  # Fallback to empty if file not readable
    
    cn_text = (
        office_action_text.strip()
        if any("\u4e00" <= ch <= "\u9fff" for ch in office_action_text)
        else "一种无线通信方法，包括：发送下行控制信息DCI格式；确定定时偏移量K0；以及基于该定时偏移量接收物理下行共享信道PDSCH。"
    )

    return {
        "workflow_id": workflow_id,
        "claim_text": claim_text,
        "prior_art_text": prior_art_text,
        "office_action_text": office_action_text,
        "cn_text": cn_text,
        "examiner_preference": examiner_preference,
        "claim_type": claim_type,
    }


@celery_app.task(autoretry_for=(Exception,), max_retries=3, retry_backoff=True)
def chunk_and_embed(context: Dict[str, Any]) -> Dict[str, Any]:
    workflow_id = str(context.get("workflow_id", ""))
    _set_workflow_meta(workflow_id, "Chunking & Embedding Prior Art", _progress_fields(2))
    time.sleep(0.1)

    # Placeholder cache marker for future real embedding pipeline.
    prior_art_text = str(context.get("prior_art_text", ""))
    prior_hash = hashlib.sha256(prior_art_text.encode("utf-8")).hexdigest()
    cache_key = f"patentflow:embed:cache:{prior_hash}"
    cache_hit = False
    try:
        r = _redis_client()
        cache_hit = bool(r.exists(cache_key))
        if not cache_hit:
            r.setex(cache_key, 24 * 3600, "embedded")
    except Exception:
        cache_hit = False

    context = dict(context)
    context["embedding_ref"] = cache_key
    context["embedding_cache_hit"] = cache_hit
    return context


@celery_app.task(autoretry_for=(Exception,), max_retries=3, retry_backoff=True)
def chart_features(context: Dict[str, Any]) -> Dict[str, Any]:
    workflow_id = str(context.get("workflow_id", ""))
    chart_meta = _progress_fields(3)
    chart_meta.update(
        {
            "examiner": context.get("examiner_preference"),
            "claim_type": context.get("claim_type"),
        }
    )
    _set_workflow_meta(workflow_id, "Generating Claim Chart (Local LLM)", chart_meta)
    time.sleep(0.1)
    claim_chart_result = generate_claim_chart(
        str(context.get("claim_text", "")),
        str(context.get("prior_art_text", "")),
        office_action_text=str(context.get("office_action_text", "")),
    )
    return {
        "workflow_id": workflow_id,
        "examiner_preference": context.get("examiner_preference", ""),
        "claim_type": context.get("claim_type", "Method"),
        "claim_chart": claim_chart_result.get("claim_chart", []),
        "cited_docs": claim_chart_result.get("cited_docs", []),
        "embedding_ref": context.get("embedding_ref"),
        "embedding_cache_hit": bool(context.get("embedding_cache_hit", False)),
    }


@celery_app.task(autoretry_for=(Exception,), max_retries=3, retry_backoff=True)
def translate_align(context: Dict[str, Any]) -> Dict[str, Any]:
    workflow_id = str(context.get("workflow_id", ""))
    _set_workflow_meta(workflow_id, "Running Translation Dual-Verification", _progress_fields(3))
    time.sleep(0.1)

    translator = PatentTranslator()
    translation_rows = translator.translate_and_align_rows(str(context.get("cn_text", "")))
    translation_table_md = translator.rows_to_markdown(translation_rows)
    return {
        "workflow_id": workflow_id,
        "examiner_preference": context.get("examiner_preference", ""),
        "claim_type": context.get("claim_type", "Method"),
        "translation_table_markdown": translation_table_md,
        "translation_rows": translation_rows,
    }


@celery_app.task(autoretry_for=(Exception,), max_retries=3, retry_backoff=True)
def draft_response(parallel_outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    workflow_id = ""
    claim_chart: List[Dict[str, Any]] = []
    translation_table_md = ""
    translation_rows: List[Dict[str, Any]] = []
    examiner_preference = ""
    claim_type = "Method"
    embedding_ref = None
    embedding_cache_hit = False
    cited_docs: List[str] = []

    for out in parallel_outputs:
        if not isinstance(out, dict):
            continue
        workflow_id = workflow_id or str(out.get("workflow_id", ""))
        examiner_preference = examiner_preference or str(out.get("examiner_preference", ""))
        claim_type = str(out.get("claim_type", claim_type))
        if "claim_chart" in out:
            claim_chart = out.get("claim_chart", []) or []
            maybe_docs = out.get("cited_docs")
            if isinstance(maybe_docs, list):
                cited_docs = [str(d) for d in maybe_docs if isinstance(d, str)]
            embedding_ref = out.get("embedding_ref")
            embedding_cache_hit = bool(out.get("embedding_cache_hit", False))
        if "translation_table_markdown" in out:
            translation_table_md = str(out.get("translation_table_markdown", ""))
            maybe_rows = out.get("translation_rows")
            if isinstance(maybe_rows, list):
                translation_rows = [r for r in maybe_rows if isinstance(r, dict)]

    _set_workflow_meta(workflow_id, "Drafting EPO Response", _progress_fields(4))
    time.sleep(0.1)
    examiner_name = (examiner_preference.split(" - ")[0] if examiner_preference else "EXAMINER").strip() or "EXAMINER"
    response_draft = (
        f"RESPONSE TO EXAMINER {examiner_name.upper()} - OFFICE ACTION DATED [DATE]\n\n"
        f"Re: European Patent Application No. [Application Number]\n"
        f"Art. 56 Inventive Step Objection - {claim_type} Claim\n\n"
        "The Applicant respectfully submits the following observations.\n"
    )

    out: Dict[str, Any] = {
        "status": "success",
        "claim_chart": claim_chart,
        "cited_docs": cited_docs,
        "translation_table_markdown": translation_table_md,
        "translation_rows": translation_rows,
        "response_draft": response_draft,
        "embedding_ref": embedding_ref,
        "embedding_cache_hit": embedding_cache_hit,
    }

    if workflow_id:
        try:
            r = _redis_client()
            r.zrem(_QUEUE_KEY, workflow_id)
            r.delete(f"{_WORKFLOW_META_KEY_PREFIX}{workflow_id}")
        except Exception:
            pass

    return _sanitize_backend_result(out)


@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=3, retry_backoff=True)
def run_patentflow_generate(
    self,
    *,
    office_action_text: str = "",
    specification_text: str = "",
    examiner_preference: str = "",
    claim_type: str = "Method",
) -> Dict[str, Any]:
    """Orchestrate the generation pipeline using Celery chain + chord."""
    workflow_id = self.request.id
    _set_workflow_meta(workflow_id, "Queued", _progress_fields(0))

    workflow = chain(
        parse_docs.s(
            office_action_text=office_action_text,
            specification_text=specification_text,
            examiner_preference=examiner_preference,
            claim_type=claim_type,
            workflow_id=workflow_id,
        ),
        chunk_and_embed.s(),
        chord((chart_features.s(), translate_align.s()), draft_response.s()),
    )
    return self.replace(workflow)
