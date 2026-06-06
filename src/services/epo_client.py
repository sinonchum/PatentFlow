"""
ClaimPilot EPO Integration Layer
=================================
OPS (Open Patent Services) + Register API client with:
  - Redis-backed OAuth2 singleton (token TTL 1200s)
  - Redis-based rate limiting (per-second quota)
  - Exponential backoff on 403/429
  - XML sanitizer for claims/description/abstract
  - INPADOC family language bridge
  - Register dossier sync (Art. 94(3) communications)

All secrets loaded from .env via python-dotenv.
All network I/O is async (httpx.AsyncClient + redis.asyncio).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
import redis.asyncio
from lxml import etree
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

logger = logging.getLogger("claimpilot.epo")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class EPOConfig(BaseModel):
    """EPO API credentials and settings — loaded from .env.

    Env vars: EPO_CONSUMER_KEY, EPO_CONSUMER_SECRET, EPO_ENABLED
    """

    consumer_key: str = ""
    consumer_secret: str = ""
    token_url: str = "https://ops.epo.org/3.2/auth/accesstoken"
    ops_base_url: str = "https://ops.epo.org/3.2/rest-services"
    register_base_url: str = "https://register.epo.org/rest-service"
    timeout: int = 30
    max_retries: int = 3
    rate_limit_per_second: int = 4  # EPO free tier: ~4 req/s

    @field_validator("consumer_key", "consumer_secret", mode="before")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip() if v else ""

    @property
    def is_configured(self) -> bool:
        return bool(self.consumer_key and self.consumer_secret)


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------


class EPOTokenData(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 1200


class EPOPublicationRef(BaseModel):
    country: str = ""
    doc_number: str = ""
    kind: str = ""


class EPOTitle(BaseModel):
    text: str = ""
    lang: str = ""


class EPOMetadata(BaseModel):
    """Lightweight biblio + fulltext metadata for a published patent."""

    publication_number: str = ""
    country: str = ""
    doc_number: str = ""
    kind: str = ""
    titles: List[EPOTitle] = Field(default_factory=list)
    applicants: List[str] = Field(default_factory=list)
    abstract: str = ""
    claims_text: str = ""
    description_text: str = ""
    lang: str = "en"


class INPADOCFamilyMember(BaseModel):
    publication_number: str = ""
    country: str = ""
    lang: str = ""


class DossierEvent(BaseModel):
    date: str = ""
    code: str = ""
    description: str = ""
    phase: str = ""


class OfficeActionSummary(BaseModel):
    """Latest Art. 94(3) communication extracted from the dossier."""

    application_number: str = ""
    communication_date: str = ""
    event_code: str = ""
    description: str = ""
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Redis helper
# ---------------------------------------------------------------------------


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _async_redis_client() -> redis.asyncio.Redis:
    return redis.asyncio.Redis.from_url(_redis_url(), decode_responses=True)


# ---------------------------------------------------------------------------
# XML Sanitizer
# ---------------------------------------------------------------------------


class EPOXMLSanitizer:
    """Extract clean, structured text from EPO OPS XML responses.

    Targets: claims, description, abstract.
    Handles nested EPO XML namespaces and mixed content.
    """

    _NS = {
        "ops": "http://ops.epo.org",
        "epo": "http://www.epo.org/exchange",
        "ft": "http://www.epo.org/fulltext",
    }

    _STRIP_TAGS = {
        "epo:legal-status",
        "epo:designated-states",
        "epo:classification-ipc",
        "epo:classification-ipcr",
        "ops:legal-status",
    }

    @classmethod
    def extract_claims(cls, xml_bytes: bytes) -> str:
        """Extract all claim text from an OPS full-text XML response."""
        try:
            tree = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError:
            tree = etree.fromstring(xml_bytes, parser=etree.XMLParser(recover=True))

        claims: List[str] = []
        for claim_el in tree.xpath("//epo:claim|//ft:claim", namespaces=cls._NS):
            text = cls._extract_text_content(claim_el)
            claim_num = claim_el.get("num", claim_el.get("number", ""))
            if claim_num:
                text = f"{claim_num}. {text}"
            claims.append(text)

        return "\n\n".join(claims) if claims else ""

    @classmethod
    def extract_description(cls, xml_bytes: bytes) -> str:
        """Extract description text from an OPS full-text XML response."""
        try:
            tree = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError:
            tree = etree.fromstring(xml_bytes, parser=etree.XMLParser(recover=True))

        desc_el = tree.xpath("//epo:description|//ft:description", namespaces=cls._NS)
        if not desc_el:
            return ""

        parts: List[str] = []
        for el in desc_el:
            text = cls._extract_text_content(el)
            text = re.sub(r"\[\d{4}\]\s*", "", text)
            parts.append(text)

        return "\n\n".join(parts)

    @classmethod
    def extract_abstract(cls, xml_bytes: bytes) -> str:
        """Extract abstract text from an OPS full-text XML response."""
        try:
            tree = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError:
            tree = etree.fromstring(xml_bytes, parser=etree.XMLParser(recover=True))

        abs_el = tree.xpath("//epo:abstract|//ft:abstract", namespaces=cls._NS)
        if not abs_el:
            return ""

        text = cls._extract_text_content(abs_el[0])
        text = re.sub(r"\[\d{4}\]\s*", "", text)
        return text.strip()

    @classmethod
    def extract_biblio_titles(cls, xml_bytes: bytes) -> List[EPOTitle]:
        """Extract invention titles from biblio XML, preferring English."""
        try:
            tree = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError:
            tree = etree.fromstring(xml_bytes, parser=etree.XMLParser(recover=True))

        titles: List[EPOTitle] = []
        for t_el in tree.xpath("//epo:invention-title", namespaces=cls._NS):
            text = t_el.text or ""
            lang = t_el.get("{http://www.w3.org/XML/1998/namespace}lang", "")
            if not text:
                text = t_el.get("{$}", "")
            titles.append(EPOTitle(text=text, lang=lang))

        titles.sort(key=lambda t: (0 if t.lang == "en" else 1))
        return titles

    @classmethod
    def _extract_text_content(cls, el: etree._Element) -> str:
        """Recursively extract all text from an element, ignoring markup."""
        parts: List[str] = []

        tag_local = etree.QName(el.tag).localname if isinstance(el.tag, str) else ""
        ns_uri = etree.QName(el.tag).namespace if isinstance(el.tag, str) else ""
        full_tag = f"{{{ns_uri}}}{tag_local}" if ns_uri else tag_local

        if full_tag in cls._STRIP_TAGS or tag_local in cls._STRIP_TAGS:
            return ""

        if el.text:
            parts.append(el.text.strip())

        for child in el:
            child_text = cls._extract_text_content(child)
            if child_text:
                parts.append(child_text)
            if child.tail:
                parts.append(child.tail.strip())

        return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# EPO Client — Async OAuth2 Singleton + Rate Limiting + Backoff
# ---------------------------------------------------------------------------


class EPOClient:
    """Enterprise-grade async EPO OPS + Register API client.

    Features:
      - Redis-backed OAuth2 token (TTL 1200s, auto-refresh 30s before expiry)
      - Redis-based rate limiter (per-second quota, non-blocking via asyncio.sleep)
      - Exponential backoff on 403/429
      - Async httpx for all network calls
      - Smart caching via Redis (SHA-256 hashed publication number, 7-day TTL)

    Usage (inside an async context or via asyncio.run()):
        async with EPOClient() as client:
            metadata = await client.smart_fetch("EP3654128")
    """

    _TOKEN_KEY = "claimpilot:epo:access_token"
    _RATE_KEY_PREFIX = "claimpilot:epo:rate:"
    _CACHE_KEY_PREFIX = "claimpilot:epo:cache:"
    _CACHE_TTL = 86400 * 7  # 7 days

    def __init__(self, config: Optional[EPOConfig] = None) -> None:
        load_dotenv(override=False)

        if config is None:
            config = EPOConfig(
                consumer_key=os.getenv("EPO_CONSUMER_KEY", ""),
                consumer_secret=os.getenv("EPO_CONSUMER_SECRET", ""),
            )

        self.config = config
        self._http = httpx.AsyncClient(timeout=config.timeout, follow_redirects=True)
        self._redis = _async_redis_client()

    # ------------------------------------------------------------------
    # OAuth2 Token Management
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        """Get a valid access token. Redis cache is shared across all workers."""
        cached = await self._redis.get(self._TOKEN_KEY)
        if cached:
            return cached

        token_data = await self._fetch_token()
        ttl = max(0, token_data.expires_in - 30)  # refresh 30s before real expiry
        await self._redis.setex(self._TOKEN_KEY, ttl, token_data.access_token)
        logger.info("EPO OAuth2 token refreshed, TTL=%ds", ttl)
        return token_data.access_token

    async def _fetch_token(self) -> EPOTokenData:
        """Fetch a new OAuth2 token from EPO."""
        if not self.config.is_configured:
            raise RuntimeError(
                "EPO credentials not configured. "
                "Set EPO_CONSUMER_KEY and EPO_CONSUMER_SECRET in .env"
            )

        creds = base64.b64encode(
            f"{self.config.consumer_key}:{self.config.consumer_secret}".encode()
        ).decode()

        resp = await self._http.post(
            self.config.token_url,
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {creds}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        payload = resp.json()

        return EPOTokenData(
            access_token=payload["access_token"],
            token_type=payload.get("token_type", "Bearer"),
            expires_in=int(payload.get("expires_in", 1200)),
        )

    async def _invalidate_token(self) -> None:
        """Force token refresh on next call."""
        await self._redis.delete(self._TOKEN_KEY)

    # ------------------------------------------------------------------
    # Rate Limiting
    # ------------------------------------------------------------------

    async def _rate_limit_check(self) -> None:
        """Redis-based per-second rate limiter. Yields if quota exceeded."""
        now = int(time.time())
        key = f"{self._RATE_KEY_PREFIX}{now}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 2)  # auto-expire after 2s
        if count > self.config.rate_limit_per_second:
            sleep_time = 1.0 - (time.time() % 1.0)
            logger.debug("EPO rate limit reached, sleeping %.2fs", sleep_time)
            await asyncio.sleep(sleep_time + 0.05)

    # ------------------------------------------------------------------
    # Core HTTP Request with Backoff
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None,
        json_body: Any = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        """Execute an authenticated request with rate limiting and exponential backoff.

        Retries on 401 (token expired), 403/429 (rate limit) with async sleep.
        """
        for attempt in range(self.config.max_retries):
            await self._rate_limit_check()

            token = await self._get_token()
            merged_headers: Dict[str, str] = {
                "Authorization": f"Bearer {token}",
                "Accept": accept,
            }
            if headers:
                merged_headers.update(headers)

            resp = await self._http.request(
                method=method.upper(),
                url=url,
                params=params,
                headers=merged_headers,
                data=data,
                json=json_body,
            )

            if resp.status_code == 401:
                logger.warning("EPO token expired (401), refreshing")
                await self._invalidate_token()
                continue

            if resp.status_code in (403, 429):
                wait = 2 ** attempt + (0.5 * attempt)
                logger.warning(
                    "EPO API returned %d, retrying in %.1fs (attempt %d/%d)",
                    resp.status_code, wait, attempt + 1, self.config.max_retries,
                )
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            return resp

        raise RuntimeError(
            f"EPO API request failed after {self.config.max_retries} retries"
        )

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_key(self, prefix: str, identifier: str) -> str:
        hashed = hashlib.sha256(identifier.encode()).hexdigest()[:16]
        return f"{self._CACHE_KEY_PREFIX}{prefix}:{hashed}"

    async def _get_cached(self, key: str) -> Optional[str]:
        val = await self._redis.get(key)
        if val:
            logger.debug("EPO cache hit: %s", key)
        return val

    async def _set_cached(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        await self._redis.setex(key, ttl or self._CACHE_TTL, value)

    # ==================================================================
    # Phase 2: Automated Prior Art Retrieval (OPS Publication)
    # ==================================================================

    async def fetch_biblio(self, publication_number: str) -> EPOMetadata:
        """Fetch bibliographic metadata for a publication number.

        Publication number format: EP3654128 or EP3654128A1 (country + number + optional kind).
        """
        cache_key = self._cache_key("biblio", publication_number)
        cached = await self._get_cached(cache_key)
        if cached:
            return EPOMetadata.model_validate_json(cached)

        country, doc_number, kind = self._parse_publication_number(publication_number)
        docdb_id = f"{country}.{doc_number}"
        if kind:
            docdb_id += f".{kind}"

        url = f"{self.config.ops_base_url}/published-data/publication/docdb/{docdb_id}/biblio"
        resp = await self._request("GET", url)

        metadata = self._parse_biblio_response(resp.content, publication_number)
        await self._set_cached(cache_key, metadata.model_dump_json())
        return metadata

    async def fetch_fulltext(self, publication_number: str) -> EPOMetadata:
        """Fetch full claims + description text via OPS.

        This is the primary method for prior art ingestion into the pipeline.
        Checks Redis cache before making any billable API calls.
        """
        cache_key = self._cache_key("fulltext", publication_number)
        cached = await self._get_cached(cache_key)
        if cached:
            return EPOMetadata.model_validate_json(cached)

        metadata = await self.fetch_biblio(publication_number)

        country, doc_number, kind = self._parse_publication_number(publication_number)
        docdb_id = f"{country}.{doc_number}"
        if kind:
            docdb_id += f".{kind}"

        url = f"{self.config.ops_base_url}/published-data/publication/docdb/{docdb_id}/fulltext"
        resp = await self._request("GET", url, accept="text/xml")

        xml_bytes = resp.content
        metadata.claims_text = EPOXMLSanitizer.extract_claims(xml_bytes)
        metadata.description_text = EPOXMLSanitizer.extract_description(xml_bytes)
        metadata.abstract = EPOXMLSanitizer.extract_abstract(xml_bytes)

        await self._set_cached(cache_key, metadata.model_dump_json())
        logger.info(
            "EPO fulltext fetched: %s (%d claim chars, %d desc chars)",
            publication_number, len(metadata.claims_text), len(metadata.description_text),
        )
        return metadata

    def _parse_biblio_response(self, xml_bytes: bytes, publication_number: str) -> EPOMetadata:
        try:
            tree = etree.fromstring(xml_bytes, parser=etree.XMLParser(recover=True))
        except etree.XMLSyntaxError:
            return EPOMetadata(publication_number=publication_number)

        country, doc_number, kind = self._parse_publication_number(publication_number)

        titles = EPOXMLSanitizer.extract_biblio_titles(xml_bytes)
        abstract = EPOXMLSanitizer.extract_abstract(xml_bytes)

        applicants: List[str] = []
        for app_el in tree.xpath(
            "//epo:applicants/epo:applicant/epo:applicant-name",
            namespaces=EPOXMLSanitizer._NS,
        ):
            name_el = app_el.xpath("epo:name", namespaces=EPOXMLSanitizer._NS)
            if name_el:
                name_text = name_el[0].get("{$}", name_el[0].text or "")
                if name_text:
                    applicants.append(name_text)

        lang = titles[0].lang if titles else "en"

        return EPOMetadata(
            publication_number=publication_number,
            country=country,
            doc_number=doc_number,
            kind=kind,
            titles=titles,
            applicants=applicants,
            abstract=abstract,
            lang=lang,
        )

    # ==================================================================
    # Phase 3: INPADOC Family Language Bridge
    # ==================================================================

    async def fetch_inpadoc_family(self, publication_number: str) -> List[INPADOCFamilyMember]:
        """Fetch the INPADOC patent family for a given publication."""
        cache_key = self._cache_key("family", publication_number)
        cached = await self._get_cached(cache_key)
        if cached:
            # Each element is a dict (from json.loads), not a JSON string
            return [INPADOCFamilyMember.model_validate(m) for m in json.loads(cached)]

        country, doc_number, kind = self._parse_publication_number(publication_number)
        docdb_id = f"{country}.{doc_number}"
        if kind:
            docdb_id += f".{kind}"

        url = f"{self.config.ops_base_url}/family/publication/docdb/{docdb_id}"
        resp = await self._request("GET", url)

        members = self._parse_family_response(resp.content)
        await self._set_cached(cache_key, json.dumps([m.model_dump() for m in members]))
        return members

    async def find_english_equivalent(self, publication_number: str) -> Optional[str]:
        """If a document is non-English, find an English-language family member.

        Priority: EP (English) > US > any other English country.
        Returns None if the original is already English or no equivalent found.
        """
        try:
            biblio = await self.fetch_biblio(publication_number)
            if biblio.lang == "en":
                return None
        except Exception:
            pass

        members = await self.fetch_inpadoc_family(publication_number)
        if not members:
            return None

        for member in members:
            if member.country == "EP" and member.lang == "en":
                return member.publication_number

        for member in members:
            if member.country == "US" and member.lang == "en":
                return member.publication_number

        for member in members:
            if member.lang == "en":
                return member.publication_number

        return None

    def _parse_family_response(self, xml_bytes: bytes) -> List[INPADOCFamilyMember]:
        """Parse INPADOC family XML response."""
        try:
            tree = etree.fromstring(xml_bytes, parser=etree.XMLParser(recover=True))
        except etree.XMLSyntaxError:
            return []

        members: List[INPADOCFamilyMember] = []
        ns = EPOXMLSanitizer._NS

        for member_el in tree.xpath("//epo:family-member", namespaces=ns):
            pub_refs = member_el.xpath(
                "epo:publication-reference/epo:document-id", namespaces=ns
            )
            for doc_id in pub_refs:
                if doc_id.get("document-id-type", "") != "docdb":
                    continue

                country_el = doc_id.xpath("epo:country", namespaces=ns)
                docnum_el = doc_id.xpath("epo:doc-number", namespaces=ns)
                kind_el = doc_id.xpath("epo:kind", namespaces=ns)

                country = country_el[0].get("{$}", country_el[0].text or "") if country_el else ""
                doc_number = docnum_el[0].get("{$}", docnum_el[0].text or "") if docnum_el else ""
                kind = kind_el[0].get("{$}", kind_el[0].text or "") if kind_el else ""

                pub_num = f"{country}{doc_number}"
                if kind:
                    pub_num += kind

                members.append(INPADOCFamilyMember(
                    publication_number=pub_num,
                    country=country,
                    lang=self._country_to_language(country),
                ))

        return members

    @staticmethod
    def _country_to_language(country: str) -> str:
        """Map ISO country codes to their most common patent language."""
        if country in {"US", "GB", "AU", "CA", "NZ", "IE", "EP", "WO"}:
            return "en"
        if country in {"CN", "TW"}:
            return "zh"
        if country in {"JP"}:
            return "ja"
        if country in {"KR"}:
            return "ko"
        if country in {"DE", "AT"}:
            return "de"
        if country in {"FR"}:
            return "fr"
        return "unknown"

    # ==================================================================
    # Phase 4: Office Action Dossier Sync (Register API)
    # ==================================================================

    async def fetch_dossier(self, application_number: str) -> List[DossierEvent]:
        """Fetch the procedural dossier for a given application number.

        Application number format: EP21158904 (country + serial, no dot)
        """
        cache_key = self._cache_key("dossier", application_number)
        cached = await self._get_cached(cache_key)
        if cached:
            # Each element is a dict (from json.loads), not a JSON string
            return [DossierEvent.model_validate(e) for e in json.loads(cached)]

        url = f"{self.config.register_base_url}/register/{application_number}/dossier"
        resp = await self._request("GET", url, accept="application/json")

        events = self._parse_dossier_response(resp.json())
        await self._set_cached(cache_key, json.dumps([e.model_dump() for e in events]))
        return events

    async def fetch_latest_office_action(
        self, application_number: str
    ) -> Optional[OfficeActionSummary]:
        """Find the most recent Art. 94(3) EPC communication in the dossier.

        Returns the latest OA metadata and raw text content if available.
        """
        events = await self.fetch_dossier(application_number)

        # Art. 94(3) communication event codes used in the EPO Register
        oa_codes = {"WIO1", "WIO2", "WISA", "WIPC", "WISN", "CLAI"}

        latest_oa: Optional[DossierEvent] = None
        for event in events:
            if event.code in oa_codes or "94(3)" in event.description:
                if latest_oa is None or event.date >= latest_oa.date:
                    latest_oa = event

        if not latest_oa:
            for event in events:
                desc_lower = event.description.lower()
                if "communication" in desc_lower and "article" in desc_lower:
                    if latest_oa is None or event.date >= latest_oa.date:
                        latest_oa = event

        if not latest_oa:
            return None

        raw_text = ""
        try:
            raw_text = await self._fetch_oa_raw_text(application_number, latest_oa)
        except Exception as e:
            logger.warning("Could not fetch OA raw text: %s", e)

        return OfficeActionSummary(
            application_number=application_number,
            communication_date=latest_oa.date,
            event_code=latest_oa.code,
            description=latest_oa.description,
            raw_text=raw_text,
        )

    async def _fetch_oa_raw_text(self, application_number: str, event: DossierEvent) -> str:
        """Attempt to fetch raw text of an Office Action from the Register API."""
        url = f"{self.config.register_base_url}/register/{application_number}/dossier"
        resp = await self._request("GET", url, accept="application/json")

        data = resp.json()
        if isinstance(data, dict):
            dossier = data.get("dossier", data)
            if isinstance(dossier, dict):
                procs = dossier.get("procedural-steps", [])
                if isinstance(procs, list):
                    for step in procs:
                        if not isinstance(step, dict):
                            continue
                        if step.get("code") == event.code and step.get("date") == event.date:
                            for doc in step.get("documents", []):
                                if isinstance(doc, dict):
                                    text = doc.get("text", doc.get("content", ""))
                                    if text:
                                        return str(text)

        return ""

    def _parse_dossier_response(self, data: Any) -> List[DossierEvent]:
        """Parse the Register API dossier JSON response."""
        events: List[DossierEvent] = []

        if not isinstance(data, dict):
            return events

        dossier = data.get("dossier", data)
        procs = (
            dossier.get("procedural-steps", [])
            if isinstance(dossier, dict)
            else data.get("procedural-steps", [])
        )

        if isinstance(procs, list):
            for step in procs:
                if not isinstance(step, dict):
                    continue
                events.append(DossierEvent(
                    date=str(step.get("date", "")),
                    code=str(step.get("code", "")),
                    description=str(step.get("description", "")),
                    phase=str(step.get("phase", "")),
                ))

        return events

    # ==================================================================
    # Utility: Smart Fetch (with language bridge)
    # ==================================================================

    async def smart_fetch(self, publication_number: str) -> EPOMetadata:
        """Fetch full text with automatic language bridge.

        If the document is non-English, automatically finds an English
        equivalent via INPADOC family and fetches that instead.
        """
        english_pub = await self.find_english_equivalent(publication_number)
        if english_pub:
            logger.info(
                "Language bridge: %s -> %s (English equivalent)",
                publication_number, english_pub,
            )
            publication_number = english_pub

        return await self.fetch_fulltext(publication_number)

    # ==================================================================
    # Utility: Publication number parsing
    # ==================================================================

    @staticmethod
    def _parse_publication_number(pub: str) -> Tuple[str, str, str]:
        """Parse a publication number into (country, doc_number, kind).

        Examples:
            EP3654128   -> ("EP", "3654128", "")
            EP3654128A1 -> ("EP", "3654128", "A1")
            US20190123456A1 -> ("US", "20190123456", "A1")
        """
        pub = pub.strip()

        m = re.match(r"^([A-Z]{2})(\d+)([A-Z]\d)?$", pub)
        if m:
            return m.group(1), m.group(2), m.group(3) or ""

        # Dot-separated: EP.3654128.A1
        m = re.match(r"^([A-Z]{2})\.(\d+)\.([A-Z]\d)$", pub)
        if m:
            return m.group(1), m.group(2), m.group(3)

        if len(pub) >= 4:
            return pub[:2], pub[2:], ""

        return pub, "", ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the async HTTP client and Redis connection pool."""
        await self._http.aclose()
        await self._redis.aclose()

    def close(self) -> None:
        """No-op kept for backward compatibility. Use aclose() or async with."""
        pass

    async def __aenter__(self) -> "EPOClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
