from __future__ import annotations

import hashlib
import json
import os
import re
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
    from src.api import _get_llm_client
    llm_client = _get_llm_client()
    generator = ClaimChartGenerator(llm_client=llm_client)
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
    attorney_name: str = "",
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

    # Extract Claim 1 from the specification for the claim chart generator.
    # The full spec text would confuse the tokenizer — we need just the claim text.
    claim_text = ""
    prior_art_text = ""
    if specification_text and len(specification_text.strip()) > 20:
        spec = specification_text.strip()
        # Find "1. A/An/The method/system..." pattern in the CLAIMS section
        claim1_m = re.search(
            r'(?:^|\n)\s*1\.\s+((?:A|An|The)\s+.+?)(?=\n\s*2\.\s+|\Z)',
            spec, re.IGNORECASE | re.DOTALL
        )
        if claim1_m:
            claim_text = claim1_m.group(1).strip()
        else:
            claim_text = spec  # Fallback: pass full spec, generator will do its best
        # Extract abstract or first paragraph as prior_art_text
        abstract_m = re.search(r'ABSTRACT[\s\n]+(.*?)(?=={5,}|\Z)', spec, re.IGNORECASE | re.DOTALL)
        if abstract_m:
            prior_art_text = re.sub(r'\s+', ' ', abstract_m.group(1)).strip()[:400]
        else:
            prior_art_text = re.sub(r'\s+', ' ', spec[:300]).strip()

    # Load mock office action if none provided (for demo purposes)
    if not office_action_text:
        try:
            mock_path = os.path.join(os.path.dirname(__file__), "..", "mock_office_action_ep.txt")
            if os.path.exists(mock_path):
                with open(mock_path, "r", encoding="utf-8") as f:
                    office_action_text = f.read()
        except Exception:
            pass  # Fallback to empty if file not readable
    
    # cn_text drives the Art. 123(2) verifier tab.
    # Chinese OA -> use OA text directly (CN->EN translation audit).
    # English OA -> extract Claim 1 from spec for EPO terminology audit.
    if any("\u4e00" <= ch <= "\u9fff" for ch in office_action_text):
        cn_text = office_action_text.strip()
    else:
        spec = specification_text or ""
        claim1_m = re.search(
            r'(?:^|\n)\s*1\.\s+(A\s+(?:method|system|device|apparatus|quality).+?)'
            r'(?=\n\s*2\.\s+|\Z)',
            spec, re.IGNORECASE | re.DOTALL
        )
        if claim1_m:
            cn_text = claim1_m.group(1).strip()[:1200]
        elif spec.strip():
            cn_text = spec.strip()[:800]
        else:
            cn_text = claim_text[:800] if claim_text else ""

    return {
        "workflow_id": workflow_id,
        "attorney_name": attorney_name,
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
        "office_action_text": str(context.get("office_action_text", "")),
        "embedding_ref": context.get("embedding_ref"),
        "embedding_cache_hit": bool(context.get("embedding_cache_hit", False)),
    }


def _epo_terminology_audit(claim_text: str) -> List[Dict[str, Any]]:
    """
    EPO terminology compliance check for English claim text.
    Splits claim into feature segments and flags non-standard terminology.
    Returns rows compatible with the translation_rows format.
    """
    # Split on semicolons (feature boundaries in English claims)
    raw_segs = re.split(r';\s*', claim_text.strip())
    segments: List[str] = []
    for seg in raw_segs:
        seg = re.sub(r'^(?:and|or)\s+', '', seg.strip(), flags=re.IGNORECASE).rstrip('.')
        if len(seg) > 15:
            segments.append(seg)

    # EPO standard terminology rules: (non-standard → (standard, risk_level))
    RULES: List[tuple] = [
        (r'\bincluding\b', 'comprising', 'CRITICAL — "including" is ambiguous scope'),
        (r'\bconsisting\s+of\b', 'comprising', 'HIGH — closed list; amend if open-ended intended'),
        (r'\bsuitable\s+for\b', 'configured to', 'WARNING — "suitable for" is functional, not structural'),
        (r'\barranged\s+to\b', 'configured to', 'WARNING — EPO prefers "configured to"'),
        (r'\badapted\s+to\b', 'configured to', 'WARNING — EPO prefers "configured to"'),
        (r'\bsaid\b', 'the', 'WARNING — EPO style prefers definite article "the"'),
        (r'\bin\s+which\b', 'wherein', 'WARNING — EPO prefers "wherein" in claim body'),
        (r'\bif\b(?!\s+the\s+(?:patent|application))', 'when', 'WARNING — conditional "if" may raise Art. 84 clarity issues'),
        (r'\babout\b', 'approximately', 'WARNING — "about" may be unclear under Art. 84'),
        (r'\bapproximately\b', 'approximately / substantially', 'INFO — quantify or justify approximation'),
        (r'\bnot\s+limited\s+to\b', '[rephrase — open-ended language]', 'WARNING — Art. 84: claim scope should be defined, not excluded'),
    ]

    rows: List[Dict[str, Any]] = []
    for seg in segments:
        flags: List[str] = []
        compliant = seg

        for pattern, standard, risk in RULES:
            if re.search(pattern, seg, re.IGNORECASE):
                flags.append(f'"{re.search(pattern, seg, re.IGNORECASE).group(0)}" → "{standard}"  [{risk}]')  # type: ignore[union-attr]

        risk_text = " | ".join(flags) if flags else "Terminology compliant ✓"
        has_risk = bool(flags)

        # Highlight risky terms in compliant form
        for pattern, standard, _ in RULES:
            compliant = re.sub(
                pattern,
                lambda m, s=standard: f"**{s}**",
                compliant, flags=re.IGNORECASE
            )

        rows.append({
            "original_cn": seg,
            "target_en": compliant,
            "back_cn": risk_text,
            "has_risk": has_risk,
        })

    return rows


@celery_app.task(autoretry_for=(Exception,), max_retries=3, retry_backoff=True)
def translate_align(context: Dict[str, Any]) -> Dict[str, Any]:
    workflow_id = str(context.get("workflow_id", ""))
    _set_workflow_meta(workflow_id, "Running Art. 123(2) Verification", _progress_fields(3))
    time.sleep(0.1)

    cn_text = str(context.get("cn_text", ""))
    is_english = not any("一" <= ch <= "鿿" for ch in cn_text)

    if is_english:
        # English claim text → EPO terminology compliance audit
        translation_rows = _epo_terminology_audit(cn_text)
        # Build markdown table (reuse existing column structure)
        header = "| Claim Segment | EPO Compliant Form | Risk Assessment |\n|---|---|---|"
        md_lines = [header]
        for row in translation_rows:
            def _esc(s: str) -> str:
                return (s or "").replace("|", "\\|").replace("\n", " ")
            md_lines.append(
                f"| {_esc(row['original_cn'])} | {_esc(row['target_en'])} | {_esc(row['back_cn'])} |"
            )
        translation_table_md = "\n".join(md_lines)
    else:
        # Chinese OA → standard CN→EN translation verification
        translator = PatentTranslator()
        translation_rows = translator.translate_and_align_rows(cn_text)
        translation_table_md = translator.rows_to_markdown(translation_rows)

    return {
        "workflow_id": workflow_id,
        "examiner_preference": context.get("examiner_preference", ""),
        "claim_type": context.get("claim_type", "Method"),
        "translation_table_markdown": translation_table_md,
        "translation_rows": translation_rows,
        "is_english_audit": is_english,
    }


def _build_response_draft(
    claim_chart: List[Dict[str, Any]],
    office_action_text: str,
    examiner_preference: str,
    cited_docs: List[str],
    claim_type: str = "Method",
) -> str:
    oa = office_action_text or ""

    # Extract application metadata from OA header
    app_m = re.search(r'Application\s+(?:Number|No\.?):?\s*(EP[\s\d\.]+)', oa, re.IGNORECASE)
    app_no = app_m.group(1).strip() if app_m else "[Application Number]"

    date_m = re.search(r'Date\s+of\s+Communication:?\s*(.+)', oa, re.IGNORECASE)
    oa_date = date_m.group(1).strip() if date_m else "[Date]"

    exam_m = re.search(r'^Examiner:?\s+([A-Z][^\n]{2,40})', oa, re.IGNORECASE | re.MULTILINE)
    examiner_str = (
        exam_m.group(1).strip() if exam_m
        else (examiner_preference.split(" - ")[0].strip() if examiner_preference else "EXAMINER")
    )

    primary_doc = cited_docs[0] if cited_docs else "D1"
    other_docs = cited_docs[1:] if len(cited_docs) > 1 else []

    # Partition chart rows by assessment
    distinguishing = [
        r for r in claim_chart
        if (r.get("assessment") or r.get("status") or "").lower() == "no"
    ]
    partial_rows = [
        r for r in claim_chart
        if (r.get("assessment") or r.get("status") or "").lower() == "partial"
    ]

    sep = "=" * 72

    lines: List[str] = [
        "RESPONSE TO EXAMINING DIVISION",
        "Communication pursuant to Art. 94(3) EPC",
        "",
        f"Application No.:    {app_no}",
        f"Communication dated: {oa_date}",
        f"Examiner:           {examiner_str}",
        f"Claim type:         {claim_type}",
        "",
        sep,
        "I.  ART. 56 EPC — INVENTIVE STEP",
        sep,
        "",
        f"A.  Distinguishing Features over {primary_doc}",
        "",
    ]

    if distinguishing:
        other_str = (", ".join(other_docs)) if other_docs else ""
        lines.append(
            f"The Applicant respectfully submits that the following claim features are "
            f"NOT disclosed in {primary_doc}"
            + (f" or in {other_str}" if other_str else "")
            + " and constitute patentably distinguishing features:"
        )
        lines.append("")
        for idx, row in enumerate(distinguishing, 1):
            fid = row.get("feature_id", "")
            lim = (row.get("claim_limitation") or row.get("limitation") or "").strip()
            rmk = (row.get("attorney_remarks") or row.get("remarks") or "").strip()
            lines.append(f"  ({idx})  Feature {fid}:")
            lines.append(f"       Claim text: {lim}")
            if rmk and "not addressed" not in rmk.lower():
                lines.append(f"       Prior art:  {rmk[:220]}")
            lines.append(
                f"       Argument:   [Explain why {primary_doc} does not disclose "
                f"this feature, and why the skilled person would not combine it "
                f"with other cited documents to arrive at this feature.]"
            )
            lines.append("")
    else:
        lines.append(
            f"  [The claim chart does not identify any features as fully absent "
            f"from {primary_doc}. Review the Partial features below.]"
        )
        lines.append("")

    if partial_rows:
        lines += [
            f"B.  Features Only Partially Disclosed in {primary_doc}",
            "",
            f"The following features are disclosed in {primary_doc} only in part. "
            "The specific combination and technical effect are not taught:",
            "",
        ]
        for row in partial_rows:
            fid = row.get("feature_id", "")
            lim = (row.get("claim_limitation") or row.get("limitation") or "").strip()
            rmk = (row.get("attorney_remarks") or row.get("remarks") or "").strip()
            lines.append(f"  Feature {fid}: {lim}")
            if rmk:
                lines.append(f"    Analysis: {rmk[:200]}")
            lines.append("")

    lines += [
        "C.  Objective Technical Problem",
        "",
        "The distinguishing features collectively solve the objective technical problem of:",
        "  [Define the technical problem — refer to specific paragraphs of the specification",
        "   that describe the technical effect/advantage of the distinguishing features.]",
        "",
        "D.  Non-Obviousness",
        "",
        f"The skilled person, starting from {primary_doc} as the closest prior art, would not",
        "have arrived at the claimed invention for the following reasons:",
        "",
        "  (i)   [Address each obviousness argument raised by the examiner individually.]",
        "  (ii)  [Argue absence of motivation to combine the cited documents.]",
        "  (iii) [Highlight any unexpected technical effect (with test data if available).]",
        "",
    ]

    # Add Art. 84 section only if OA raises clarity objections
    art84_present = bool(re.search(r'ARTICLE\s*84|ART\.?\s*84', oa, re.IGNORECASE))
    if art84_present:
        # Extract individual 84 sub-objections
        art84_items = re.findall(
            r'(?:^|\n)\s*\d+\.\d+\s+(Claim\s+\d+[^\n]+)',
            oa, re.IGNORECASE
        )
        lines += [
            sep,
            "II. ART. 84 EPC — CLARITY",
            sep,
            "",
        ]
        if art84_items:
            for item in art84_items[:5]:
                lines.append(f"  Re: {item.strip()}")
                lines.append("    Response: [Confirm the claim language is clear or propose amendment.]")
                lines.append("")
        else:
            lines.append(
                "  [Address each clarity objection listed in the Office Action. "
                "For each, either argue clarity or propose an amendment.]"
            )
            lines.append("")

    roman = "II" if not art84_present else "III"
    lines += [
        sep,
        f"{roman}. REQUEST",
        sep,
        "",
        "For the reasons submitted above, the Applicant respectfully requests that:",
        "",
        "  (i)   The objections under Art. 56 EPC be withdrawn;",
    ]
    if art84_present:
        lines.append("  (ii)  The objections under Art. 84 EPC be withdrawn;")
        lines.append("  (iii) The application be allowed to proceed to grant.")
    else:
        lines.append("  (ii)  The application be allowed to proceed to grant.")

    lines += [
        "",
        "Respectfully submitted,",
        "",
        "[Attorney / Representative Name]",
        "[Firm / Reference Number]",
        "[Date]",
    ]

    return "\n".join(lines)


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

    office_action_text = ""
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
            office_action_text = office_action_text or str(out.get("office_action_text", ""))
            embedding_ref = out.get("embedding_ref")
            embedding_cache_hit = bool(out.get("embedding_cache_hit", False))
        if "translation_table_markdown" in out:
            translation_table_md = str(out.get("translation_table_markdown", ""))
            maybe_rows = out.get("translation_rows")
            if isinstance(maybe_rows, list):
                translation_rows = [r for r in maybe_rows if isinstance(r, dict)]

    _set_workflow_meta(workflow_id, "Drafting EPO Response", _progress_fields(4))
    time.sleep(0.1)

    response_draft = _build_response_draft(
        claim_chart=claim_chart,
        office_action_text=office_action_text,
        examiner_preference=examiner_preference,
        cited_docs=cited_docs,
        claim_type=claim_type,
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
    attorney_name: str = "",
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
            attorney_name=attorney_name,
            workflow_id=workflow_id,
        ),
        chunk_and_embed.s(),
        chord((chart_features.s(), translate_align.s()), draft_response.s()),
    )
    return self.replace(workflow)
