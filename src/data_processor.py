from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import difflib

import fitz  # PyMuPDF
from .telecom_utils import extract_3gpp_standard_refs


class PatentParser:
    def extract_text(self, pdf_path: str) -> str:
        pdf_path = str(Path(pdf_path))

        if self.is_scanned_pdf(pdf_path):
            raise RuntimeError(
                "This PDF appears to have no text layer (likely scanned). Please run OCR first (not implemented)."
            )

        doc = fitz.open(pdf_path)
        try:
            pages_text: List[str] = []
            for page_index, page in enumerate(doc, start=1):
                page_text = self._extract_page_text_blocks(page)
                page_text = self._remove_page_number_noise(page_text, page_index=page_index)
                pages_text.append(_normalize_text(page_text))
            return _normalize_text("\n\n".join([p for p in pages_text if p]))
        finally:
            doc.close()

    def is_scanned_pdf(self, pdf_path: str) -> bool:
        doc = fitz.open(str(Path(pdf_path)))
        try:
            sampled_pages = min(3, doc.page_count)
            total_chars = 0
            for i in range(sampled_pages):
                total_chars += len((doc.load_page(i).get_text("text") or "").strip())
            return total_chars < 30
        finally:
            doc.close()

    def _extract_page_text_blocks(self, page: fitz.Page) -> str:
        blocks = page.get_text("blocks") or []
        cleaned: List[Tuple[float, float, str]] = []
        for b in blocks:
            if not isinstance(b, (list, tuple)) or len(b) < 5:
                continue
            x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
            if not isinstance(text, str):
                continue
            t = text.strip()
            if not t:
                continue
            cleaned.append((float(y0), float(x0), t))

        cleaned.sort(key=lambda t: (round(t[0], 1), round(t[1], 1)))
        return "\n".join([t[2] for t in cleaned])

    def _remove_page_number_noise(self, page_text: str, *, page_index: int) -> str:
        lines = [ln.rstrip() for ln in page_text.splitlines()]
        filtered: List[str] = []
        for i, ln in enumerate(lines):
            s = ln.strip()
            if not s:
                filtered.append(ln)
                continue

            if re.fullmatch(r"\d{1,4}", s) and (i <= 1 or i >= len(lines) - 2):
                continue
            if re.fullmatch(r"Page\s+\d+\s*(?:/\s*\d+)?", s, flags=re.IGNORECASE) and (
                i <= 1 or i >= len(lines) - 2
            ):
                continue
            filtered.append(ln)
        return "\n".join(filtered)

    def parse_office_action(self, text: str) -> Dict[str, Any]:
        text = _normalize_text(text)

        application_no = self._extract_application_number(text)
        applicant = self._extract_applicant(text)
        date = self._extract_communication_date(text)
        examiner_name = self._extract_examiner_name(text)
        cited_docs = self._extract_cited_documents(text)
        epc_articles = self._extract_epc_articles(text)
        rejected_claims = self._extract_rejected_claims(text)

        return {
            "application_number": application_no,
            "applicant": applicant,
            "date": date,
            "examiner_name": examiner_name,
            "cited_documents": cited_docs,
            "epc_articles": epc_articles,
            "rejected_claims": rejected_claims,
        }

    def find_basis_paragraphs(
        self,
        specification_text: str,
        *,
        keywords: Sequence[str],
        max_hits: int = 8,
        window_chars: int = 380,
    ) -> List[Dict[str, str]]:
        specification_text = _normalize_text(specification_text)
        kws = [k.strip() for k in (keywords or []) if k and k.strip()]
        if not specification_text or not kws:
            return []

        # Try paragraph-numbered format common in published specs: [0001], [0002], ...
        para_pat = re.compile(r"^\s*\[(\d{4})\]\s*(.*)$", flags=re.MULTILINE)
        paragraphs: List[Tuple[str, str]] = []
        matches = list(para_pat.finditer(specification_text))
        if matches:
            # Slice by paragraph anchors
            starts = [(m.start(), m.end(), m.group(1)) for m in matches]
            for i, (s0, e0, pid) in enumerate(starts):
                s1 = starts[i + 1][0] if i + 1 < len(starts) else len(specification_text)
                chunk = specification_text[e0:s1].strip()
                paragraphs.append((pid, _normalize_text(matches[i].group(2) + "\n" + chunk)))
        else:
            # Fallback: split into paragraphs
            parts = [p.strip() for p in re.split(r"\n\s*\n+", specification_text) if p.strip()]
            for idx, p in enumerate(parts, start=1):
                paragraphs.append((str(idx), p))

        hits: List[Dict[str, str]] = []
        seen = set()
        for pid, ptext in paragraphs:
            lower = ptext.lower()
            if not any(k.lower() in lower for k in kws):
                continue
            key = (pid, ptext[:120])
            if key in seen:
                continue
            seen.add(key)
            snippet = ptext
            if len(snippet) > window_chars:
                snippet = snippet[:window_chars].rstrip() + "..."
            hits.append({"paragraph": pid, "snippet": snippet})
            if len(hits) >= int(max_hits):
                break

        return hits

    def find_basis(
        self,
        spec_path: str,
        keywords: Sequence[str],
        *,
        max_hits: int = 8,
        window_chars: int = 420,
        fuzzy_threshold: float = 0.78,
    ) -> List[Dict[str, str]]:
        path = Path(str(spec_path))
        if not path.exists():
            raise RuntimeError(f"Specification path does not exist: {spec_path}")

        text = ""
        if path.suffix.lower() == ".pdf":
            text = self.extract_text(str(path))
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")

        text = _normalize_text(text)
        kws = [k.strip() for k in (keywords or []) if k and k.strip()]
        if not text or not kws:
            return []

        para_pat = re.compile(r"^\s*\[(\d{4})\]\s*(.*)$", flags=re.MULTILINE)
        paragraphs: List[Tuple[str, str]] = []
        matches = list(para_pat.finditer(text))
        if matches:
            starts = [(m.start(), m.end(), m.group(1)) for m in matches]
            for i, (s0, e0, pid) in enumerate(starts):
                s1 = starts[i + 1][0] if i + 1 < len(starts) else len(text)
                chunk = text[e0:s1].strip()
                paragraphs.append((pid, _normalize_text(matches[i].group(2) + "\n" + chunk)))
        else:
            parts = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
            for idx, p in enumerate(parts, start=1):
                paragraphs.append((str(idx), p))

        def score_paragraph(ptext: str) -> float:
            lower = ptext.lower()
            tokens = re.findall(r"[a-z0-9_./-]+", lower)
            if not tokens:
                return 0.0

            kw_hits = 0
            fuzzy_hits = 0
            for kw in kws:
                kw_l = kw.lower()
                if kw_l in lower:
                    kw_hits += 1
                    continue
                r = difflib.SequenceMatcher(None, kw_l, lower).ratio()
                if r >= float(fuzzy_threshold):
                    fuzzy_hits += 1

            density = (kw_hits + 0.5 * fuzzy_hits) / max(1.0, len(tokens) / 80.0)
            return float(density)

        scored: List[Tuple[float, str, str]] = []
        for pid, ptext in paragraphs:
            s = score_paragraph(ptext)
            if s <= 0:
                continue
            scored.append((s, pid, ptext))

        scored.sort(key=lambda t: t[0], reverse=True)
        out: List[Dict[str, str]] = []
        for s, pid, ptext in scored[: int(max_hits)]:
            snippet = ptext
            if len(snippet) > int(window_chars):
                snippet = snippet[: int(window_chars)].rstrip() + "..."
            out.append({"paragraph": pid, "snippet": snippet, "score": f"{s:.4f}"})
        return out

    def split_sections(self, text: str) -> Dict[str, str]:
        full_text = _normalize_text(text)
        abstract = _slice_section(
            full_text,
            start_patterns=[r"^\s*ABSTRACT\s*$", r"^\s*Abstract\s*$", r"\bABSTRACT\b"],
            end_patterns=[
                r"^\s*CLAIMS\s*$",
                r"^\s*Claims\s*$",
                r"^\s*DESCRIPTION\s*$",
                r"^\s*Detailed\s+Description\s*$",
                r"^\s*BRIEF\s+DESCRIPTION\s+OF\s+THE\s+DRAWINGS\s*$",
            ],
        )

        claims = _slice_section(
            full_text,
            start_patterns=[
                r"^\s*CLAIMS\s*$",
                r"^\s*Claims\s*$",
                r"^\s*What\s+is\s+claimed\s+is\s*[:\-]?\s*$",
                r"\bWhat\s+is\s+claimed\s+is\b",
            ],
            end_patterns=[
                r"^\s*DESCRIPTION\s*$",
                r"^\s*Detailed\s+Description\s*$",
                r"^\s*BACKGROUND\s*$",
                r"^\s*FIELD\s*$",
                r"^\s*SUMMARY\s*$",
            ],
        )

        description = _slice_section(
            full_text,
            start_patterns=[
                r"^\s*DESCRIPTION\s*$",
                r"^\s*Detailed\s+Description\s*$",
            ],
            end_patterns=[],
        )
        if not description:
            description = ""

        return {
            "Claims": claims,
            "Description": description,
            "Abstract": abstract,
        }

    def chunk_internal_response(self, text: str, *, min_chunk_chars: int = 200) -> List[str]:
        text = _normalize_text(text)
        if not text:
            return []

        parts = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]

        chunks: List[str] = []
        buf: List[str] = []
        size = 0
        for p in parts:
            if size + len(p) < min_chunk_chars:
                buf.append(p)
                size += len(p)
                continue
            if buf:
                chunks.append("\n\n".join(buf).strip())
                buf = []
                size = 0
            chunks.append(p)

        if buf:
            chunks.append("\n\n".join(buf).strip())
        return chunks

    def _extract_application_number(self, text: str) -> str:
        m = re.search(
            r"\bApplication\s+No\s*[:\-]\s*([0-9]{6,}[0-9./\-\s]*)",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
        return ""

    def _extract_communication_date(self, text: str) -> str:
        # Typical forms: Date: 28.02.2026 or Date - 28.02.2026
        m = re.search(r"\bDate\s*[:\-]\s*([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4})\b", text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return ""

    def _extract_examiner_name(self, text: str) -> str:
        # Office Actions often contain: Examiner: <Name> or "Examining Division: <Name>"
        m = re.search(r"\bExaminer\s*[:\-]\s*(.{2,80})", text, flags=re.IGNORECASE)
        if m:
            return _normalize_text(m.group(1)).splitlines()[0].strip()
        m = re.search(r"\bExamining\s+Division\s*[:\-]\s*(.{2,120})", text, flags=re.IGNORECASE)
        if m:
            return _normalize_text(m.group(1)).splitlines()[0].strip()
        return ""

    def _extract_applicant(self, text: str) -> str:
        m = re.search(r"\(\s*Applicant\s*[:\-]\s*([^\)]+)\)", text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"\bApplicant\s*[:\-]\s*(.{3,200})", text, flags=re.IGNORECASE)
        if m:
            return _normalize_text(m.group(1)).splitlines()[0].strip()
        return ""

    def _extract_cited_documents(self, text: str) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []

        patterns = [
            r"^\s*(D\d+)\s*[:\-]\s*(.+)$",
            r"^\s*(D\d+)\s+(.+)$",
        ]

        matches: List[Tuple[str, str]] = []
        for pat in patterns:
            for m in re.finditer(pat, text, flags=re.IGNORECASE | re.MULTILINE):
                doc_id = m.group(1).upper()
                citation = m.group(2).strip()
                if citation:
                    matches.append((doc_id, citation))

        seen = set()
        for doc_id, citation in matches:
            key = (doc_id, citation)
            if key in seen:
                continue
            seen.add(key)

            citation = re.sub(r"\s+", " ", citation).strip()

            is_3gpp = bool(
                re.search(
                    r"\b3GPP\b\s+TS\s+\d{2}\.\d{3}\b",
                    citation,
                    flags=re.IGNORECASE,
                )
            )

            standard_refs = extract_3gpp_standard_refs(citation)
            standard_ref = standard_refs[0] if standard_refs else ""

            out.append(
                {
                    "id": doc_id,
                    "citation": citation,
                    "is_3gpp": "true" if is_3gpp else "false",
                    "standard_ref": standard_ref,
                }
            )

        return out

    def _extract_epc_articles(self, text: str) -> List[str]:
        arts = set()
        for m in re.finditer(r"\bArt\.?\s*(\d{1,3})\b", text, flags=re.IGNORECASE):
            arts.add(f"Art. {m.group(1)}")
        for m in re.finditer(r"\bArticle\s*(\d{1,3})\b", text, flags=re.IGNORECASE):
            arts.add(f"Art. {m.group(1)}")
        return sorted(arts, key=lambda s: int(re.search(r"\d+", s).group(0))) if arts else []

    def _extract_rejected_claims(self, text: str) -> List[str]:
        results: List[str] = []

        patterns = [
            r"Claims?\s+([0-9]+(?:\s*[\-,–]\s*[0-9]+)?(?:\s*,\s*[0-9]+)*)\s+(?:are\s+)?(?:rejected|objected|not\s+allowable)",
            r"Claim\s+([0-9]+)\s+(?:is\s+)?(?:rejected|objected|not\s+allowable)",
        ]
        for pat in patterns:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                results.append(m.group(1).strip())

        if results:
            return results

        found = set()
        for m in re.finditer(r"\bclaim\s+(\d{1,3})\b", text, flags=re.IGNORECASE):
            found.add(m.group(1))
        return sorted(found, key=lambda s: int(s))


@dataclass
class PatentPDFData:
    title: str
    applicant: str
    claims: str
    abstract: str

    def to_json_dict(self) -> Dict[str, str]:
        return {k: (v or "") for k, v in asdict(self).items()}


def _normalize_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_pages_text(pdf_path: str) -> List[str]:
    doc = fitz.open(pdf_path)
    try:
        pages: List[str] = []
        for page in doc:
            pages.append(_normalize_text(page.get_text("text") or ""))
        return pages
    finally:
        doc.close()


def _find_heading_span(full_text: str, heading_patterns: Sequence[str]) -> Optional[Tuple[int, int]]:
    for pat in heading_patterns:
        m = re.search(pat, full_text, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            return m.start(), m.end()
    return None


def _slice_section(
    full_text: str,
    *,
    start_patterns: Sequence[str],
    end_patterns: Sequence[str],
) -> str:
    start_span = _find_heading_span(full_text, start_patterns)
    if not start_span:
        return ""

    start = start_span[1]
    tail = full_text[start:]

    end = None
    for pat in end_patterns:
        m = re.search(pat, tail, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            end = start + m.start()
            break

    chunk = full_text[start:end] if end is not None else full_text[start:]
    chunk = _normalize_text(chunk)

    chunk = re.sub(r"^[:\-\s]+", "", chunk)
    return chunk.strip()


def _guess_title(first_page_text: str) -> str:
    lines = [ln.strip() for ln in first_page_text.splitlines() if ln.strip()]
    if not lines:
        return ""

    noisy = re.compile(
        r"^(?:\(?\d{2}\)?\s*)?(?:EP|WO|US|CN|JP|KR)?\s*[A-Z]{0,3}\s*\d[\d\s/,-]*[A-Z0-9-]*$",
        flags=re.IGNORECASE,
    )

    candidates: List[str] = []
    for ln in lines[:40]:
        if len(ln) < 6:
            continue
        if noisy.match(ln):
            continue
        if re.search(r"\b(patent|publication|application)\b", ln, flags=re.IGNORECASE):
            continue
        candidates.append(ln)

    if not candidates:
        return lines[0]

    best = max(candidates[:10], key=lambda s: len(s))
    return best


def _guess_applicant(first_pages_text: str) -> str:
    patterns = [
        r"^\s*Applicant\(s\)\s*[:\-]\s*(.+)$",
        r"^\s*Applicant\s*[:\-]\s*(.+)$",
        r"^\s*Applicants\s*[:\-]\s*(.+)$",
        r"^\s*Assignee\s*[:\-]\s*(.+)$",
        r"^\s*Applicant name\s*[:\-]\s*(.+)$",
    ]

    for pat in patterns:
        m = re.search(pat, first_pages_text, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            val = m.group(1).strip()
            val = re.split(r"\s{2,}|\t|\n", val)[0].strip()
            return val

    m = re.search(
        r"\bapplicant\b\s*[:\-]\s*(.{3,200})",
        first_pages_text,
        flags=re.IGNORECASE,
    )
    if m:
        return _normalize_text(m.group(1)).splitlines()[0].strip()

    return ""


def process_pdf(pdf_path: str) -> Dict[str, str]:
    pdf_path = str(Path(pdf_path))
    pages = _extract_pages_text(pdf_path)

    first_page = pages[0] if pages else ""
    first_two_pages = "\n\n".join(pages[:2])
    full_text = "\n\n".join(pages)

    title = _guess_title(first_page)
    applicant = _guess_applicant(first_two_pages)

    abstract = _slice_section(
        full_text,
        start_patterns=[r"^\s*ABSTRACT\s*$", r"^\s*Abstract\s*$", r"\bABSTRACT\b"],
        end_patterns=[
            r"^\s*CLAIMS\s*$",
            r"^\s*Claims\s*$",
            r"^\s*DESCRIPTION\s*$",
            r"^\s*Detailed\s+Description\s*$",
            r"^\s*BRIEF\s+DESCRIPTION\s+OF\s+THE\s+DRAWINGS\s*$",
        ],
    )

    claims = _slice_section(
        full_text,
        start_patterns=[
            r"^\s*CLAIMS\s*$",
            r"^\s*Claims\s*$",
            r"^\s*What\s+is\s+claimed\s+is\s*[:\-]?\s*$",
            r"\bWhat\s+is\s+claimed\s+is\b",
        ],
        end_patterns=[
            r"^\s*DESCRIPTION\s*$",
            r"^\s*Detailed\s+Description\s*$",
            r"^\s*BACKGROUND\s*$",
            r"^\s*FIELD\s*$",
            r"^\s*SUMMARY\s*$",
        ],
    )

    data = PatentPDFData(
        title=title,
        applicant=applicant,
        claims=claims,
        abstract=abstract,
    )
    return data.to_json_dict()


def process_pdf_to_json(pdf_path: str) -> str:
    return json.dumps(process_pdf(pdf_path), ensure_ascii=False, indent=2)
