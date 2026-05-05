"""
PatentFlow EPO Celery Tasks
============================
Async pipeline for heavy EPO network operations.

Celery workers are synchronous; EPO calls use asyncio.run() to drive the
async EPOClient from within each sync task body. This works correctly with
Celery's default prefork pool (no existing event loop in worker processes).

Tasks:
  - epo_ingest_publication: Fetch fulltext for a single publication number
  - epo_sync_dossier: Fetch latest OA from Register API
  - process_epo_request: End-to-end pipeline (fetch → claim chart)
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional, Tuple

import redis

from src.celery_app import celery_app
from src.services.epo_client import EPOClient, EPOMetadata, OfficeActionSummary


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(_redis_url(), decode_responses=True)


# ---------------------------------------------------------------------------
# Async helpers — called via asyncio.run() from sync Celery task bodies
# ---------------------------------------------------------------------------


async def _async_ingest(publication_number: str, use_language_bridge: bool) -> EPOMetadata:
    async with EPOClient() as client:
        if use_language_bridge:
            return await client.smart_fetch(publication_number)
        return await client.fetch_fulltext(publication_number)


async def _async_dossier(application_number: str) -> Optional[OfficeActionSummary]:
    async with EPOClient() as client:
        return await client.fetch_latest_office_action(application_number)


async def _async_full_pipeline(
    publication_number: str,
    application_number: str,
    use_language_bridge: bool,
) -> Tuple[Optional[EPOMetadata], Optional[OfficeActionSummary]]:
    """Fetch pub fulltext and/or dossier OA in a single async context."""
    async with EPOClient() as client:
        pub_meta: Optional[EPOMetadata] = None
        oa: Optional[OfficeActionSummary] = None

        if publication_number:
            if use_language_bridge:
                pub_meta = await client.smart_fetch(publication_number)
            else:
                pub_meta = await client.fetch_fulltext(publication_number)

        if application_number:
            oa = await client.fetch_latest_office_action(application_number)

        return pub_meta, oa


# ---------------------------------------------------------------------------
# EPO Ingest Task — Full-text retrieval
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
)
def epo_ingest_publication(
    self,
    *,
    publication_number: str,
    use_language_bridge: bool = True,
) -> Dict[str, Any]:
    """Fetch full claims + description text from EPO OPS.

    Args:
        publication_number: E.g. EP3654128 or EP3654128A1
        use_language_bridge: If True, automatically find English equivalent for non-EN docs

    Returns:
        Dict with metadata, claims_text, description_text, abstract
    """
    task_id = self.request.id

    try:
        metadata = asyncio.run(_async_ingest(publication_number, use_language_bridge))

        return {
            "task_id": task_id,
            "status": "success",
            "publication_number": metadata.publication_number,
            "country": metadata.country,
            "doc_number": metadata.doc_number,
            "kind": metadata.kind,
            "titles": [t.model_dump() for t in metadata.titles],
            "applicants": metadata.applicants,
            "abstract": metadata.abstract,
            "claims_text": metadata.claims_text,
            "description_text": metadata.description_text,
            "lang": metadata.lang,
        }

    except Exception as e:
        return {
            "task_id": task_id,
            "status": "error",
            "publication_number": publication_number,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# EPO Dossier Sync Task — Latest OA
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
)
def epo_sync_dossier(
    self,
    *,
    application_number: str,
) -> Dict[str, Any]:
    """Fetch latest Art. 94(3) Office Action from the EPO Register.

    Args:
        application_number: E.g. EP21158904

    Returns:
        Dict with OA summary data
    """
    task_id = self.request.id

    try:
        oa = asyncio.run(_async_dossier(application_number))

        if oa is None:
            return {
                "task_id": task_id,
                "status": "no_oa_found",
                "application_number": application_number,
                "error": "No Art. 94(3) communication found in dossier",
            }

        return {
            "task_id": task_id,
            "status": "success",
            "application_number": oa.application_number,
            "communication_date": oa.communication_date,
            "event_code": oa.event_code,
            "description": oa.description,
            "raw_text": oa.raw_text,
        }

    except Exception as e:
        return {
            "task_id": task_id,
            "status": "error",
            "application_number": application_number,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Full Pipeline: EPO Ingest -> Claim Chart
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
)
def process_epo_request(
    self,
    *,
    publication_number: str = "",
    application_number: str = "",
    office_action_text: str = "",
    claim_type: str = "Method",
    attorney_name: str = "",
    use_language_bridge: bool = True,
) -> Dict[str, Any]:
    """End-to-end EPO pipeline: ingest patent data, then generate claim chart.

    Accepts either publication_number, application_number, or both.
    """
    task_id = self.request.id
    claims_text = ""
    prior_art_text = ""
    oa_text = office_action_text
    epo_metadata: Dict[str, Any] = {}

    try:
        pub_meta, oa = asyncio.run(
            _async_full_pipeline(publication_number, application_number, use_language_bridge)
        )

        if pub_meta:
            claims_text = pub_meta.claims_text
            prior_art_text = pub_meta.description_text[:5000] if pub_meta.description_text else ""
            epo_metadata["publication"] = pub_meta.model_dump()

        if oa:
            oa_text = oa.raw_text or oa.description or oa_text
            epo_metadata["office_action"] = oa.model_dump()

    except Exception as e:
        return {
            "task_id": task_id,
            "status": "error",
            "error": f"EPO fetch failed: {str(e)}",
        }

    # Local import avoids circular dependency at module load time
    from src.api import _get_llm_client
    from src.skills import ClaimChartGenerator

    llm_client = _get_llm_client()
    generator = ClaimChartGenerator(llm_client=llm_client)

    chart_result = generator.execute(
        claim_text=claims_text,
        prior_art_text=prior_art_text,
        office_action_text=oa_text,
        attorney_id=attorney_name,
    )

    return {
        "task_id": task_id,
        "status": "success",
        "epo_metadata": epo_metadata,
        "claim_chart": chart_result.data.get("chart", []),
        "cited_docs": chart_result.data.get("cited_docs", []),
        "warnings": chart_result.warnings,
    }
