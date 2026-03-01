from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from celery import states
import redis

from src.celery_app import celery_app
from src.skills import generate_claim_chart
from src.translator import PatentTranslator


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(_redis_url(), decode_responses=True)


_QUEUE_KEY = "patentflow:queue:z"


@celery_app.task(bind=True)
def run_patentflow_generate(
    self,
    *,
    office_action_text: str = "",
    specification_text: str = "",
    examiner_preference: str = "",
    claim_type: str = "Method",
    queued_position: Optional[int] = None,
) -> Dict[str, Any]:
    """Run PatentFlow heavy operations asynchronously.

    This is intentionally structured as a multi-step task with progress updates.

    NOTE: This repo currently contains mocked logic; this task mirrors how we'd wrap
    real PDF parsing + local LLM calls.
    """

    def progress(step: str, extra: Optional[Dict[str, Any]] = None) -> None:
        meta: Dict[str, Any] = {"step": step}
        if queued_position is not None:
            meta["queue_position"] = queued_position
        if extra:
            meta.update(extra)
        self.update_state(state="PROGRESS", meta=meta)

    progress("Queued")
    time.sleep(0.05)

    # Remove from UX queue once we begin execution.
    try:
        r = _redis_client()
        r.zrem(_QUEUE_KEY, self.request.id)
    except Exception:
        pass

    progress("Parsing Office Action")
    time.sleep(0.1)

    # In the real engine this would parse OA/spec PDFs and extract claims/citations.
    # For now: mocked claim/prior-art text derived from inputs when available.
    claim_text = (
        "A method for wireless communication, comprising: transmitting a downlink control information (DCI) format; "
        "determining a timing offset K0; and receiving a physical downlink shared channel (PDSCH) based on the timing offset."
    )
    prior_art_text = "D1 discloses a wireless communication system with fixed timing relations."

    if specification_text and len(specification_text) > 50:
        # Keep it deterministic; just lightly incorporate user text.
        prior_art_text = (specification_text[:200] + "...").replace("\n", " ")

    progress("Generating Claim Chart (Local LLM)", {"examiner": examiner_preference, "claim_type": claim_type})
    time.sleep(0.1)
    claim_chart_result = generate_claim_chart(claim_text, prior_art_text)

    progress("Running Translation Dual-Verification")
    time.sleep(0.1)
    translator = PatentTranslator()
    # If user provides CN, it will render; otherwise a default example
    cn_text = (
        office_action_text.strip()
        if any(ch >= "\u4e00" and ch <= "\u9fff" for ch in office_action_text)
        else "一种无线通信方法，包括：发送下行控制信息DCI格式；确定定时偏移量K0；以及基于该定时偏移量接收物理下行共享信道PDSCH。"
    )
    translation_table_md = translator.translate_and_align(cn_text)

    progress("Drafting EPO Response")
    time.sleep(0.1)
    examiner_name = (examiner_preference.split(" - ")[0] if examiner_preference else "EXAMINER").strip() or "EXAMINER"
    response_draft = (
        f"RESPONSE TO EXAMINER {examiner_name.upper()} - OFFICE ACTION DATED [DATE]\n\n"
        f"Re: European Patent Application No. [Application Number]\n"
        f"Art. 56 Inventive Step Objection - {claim_type} Claim\n\n"
        "The Applicant respectfully submits the following observations.\n"
    )

    out = {
        "status": "success",
        "claim_chart": claim_chart_result.get("claim_chart", []),
        "translation_table_markdown": translation_table_md,
        "response_draft": response_draft,
    }

    # Best-effort cleanup (if we somehow still exist in the UX queue)
    try:
        r = _redis_client()
        r.zrem(_QUEUE_KEY, self.request.id)
    except Exception:
        pass

    return out
