from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class BestMatch:
    source: str
    source_path: Optional[str]
    distance: float


def _normalize(text: str) -> str:
    text = (text or "").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(lines).strip()


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _get_cited_doc(info: Dict[str, Any], doc_id: str) -> Tuple[str, str, str]:
    doc_id = (doc_id or "").upper().strip()
    for d in info.get("cited_documents") or []:
        if not isinstance(d, dict):
            continue
        if str(d.get("id") or "").upper().strip() != doc_id:
            continue
        citation = str(d.get("citation") or "").strip()
        is_3gpp = str(d.get("is_3gpp") or "").strip().lower()
        standard_ref = str(d.get("standard_ref") or "").strip()
        return (doc_id, citation, standard_ref or ("3GPP TS" if is_3gpp == "true" else ""))
    return (doc_id, "", "")


class LegalLanguageAudit:
    def __init__(self) -> None:
        self._replacements: List[Tuple[re.Pattern, str]] = [
            (re.compile(r"\bI\s+think\b", flags=re.IGNORECASE), "The Applicant submits"),
            (re.compile(r"\bwe\s+think\b", flags=re.IGNORECASE), "The Applicant submits"),
            (re.compile(r"\bthe\s+examiner\s+says\b", flags=re.IGNORECASE), "The Examiner maintains"),
            (re.compile(r"\bthe\s+examiner\s+said\b", flags=re.IGNORECASE), "The Examiner maintained"),
            (re.compile(r"\bthe\s+examiner\s+is\s+saying\b", flags=re.IGNORECASE), "The Examiner maintains"),
        ]

    def audit(self, *, text: str, info: Dict[str, Any]) -> str:
        text = _normalize(text)
        info = info or {}

        # 1) Auto-correction of non-professional language
        for pat, repl in self._replacements:
            text = pat.sub(repl, text)

        # 2) Ensure rebuttal paragraphs begin with an EPC Article opener
        # If we detect an Art.56-like section without a formal opener, prepend it.
        if re.search(r"\bInventive\s*step\b", text, flags=re.IGNORECASE) and not re.search(
            r"^\s*Regarding\s+Article\s+56\s+EPC", text, flags=re.IGNORECASE | re.MULTILINE
        ):
            text = re.sub(
                r"^(\s*IV\.\s*REMARKS\s+UNDER\s+ARTICLE\s+56\s+EPC\s*)$",
                r"\1\nRegarding Article 56 EPC, the Applicant respectfully submits as follows:",
                text,
                flags=re.IGNORECASE | re.MULTILINE,
            )
            if not re.search(r"Regarding Article 56 EPC", text, flags=re.IGNORECASE):
                text = "Regarding Article 56 EPC, the Applicant respectfully submits as follows:\n\n" + text

        # 3) Enrich D1/D2 references with citation details when available
        d1_id, d1_cit, _ = _get_cited_doc(info, "D1")
        d2_id, d2_cit, _ = _get_cited_doc(info, "D2")
        if d1_cit:
            # If we see standalone "D1" not followed by a colon or parentheses, enrich it.
            text = re.sub(
                r"\bD1\b(?!\s*[:\(])",
                f"{d1_id} ({d1_cit})",
                text,
            )
        if d2_cit:
            text = re.sub(
                r"\bD2\b(?!\s*[:\(])",
                f"{d2_id} ({d2_cit})",
                text,
            )

        return _normalize(text) + "\n"


def _pick_best_match(results: Any) -> BestMatch:
    if not isinstance(results, list) or not results:
        raise RuntimeError("results must be a non-empty list")

    best: Optional[BestMatch] = None
    for item in results:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        source = str(meta.get("source") or "unknown")
        source_path = meta.get("source_path")
        source_path = str(source_path) if source_path else None
        dist = item.get("distance")
        if dist is None:
            continue
        try:
            dist_f = float(dist)
        except Exception:
            continue
        if best is None or dist_f < best.distance:
            best = BestMatch(source=source, source_path=source_path, distance=dist_f)

    if best is None:
        raise RuntimeError("No valid distance found in results")

    return best


def _resolve_template_path(*, best: BestMatch, kb_dirs: List[str]) -> Path:
    # Prefer explicit source_path recorded at ingestion time
    if best.source_path:
        p = Path(best.source_path)
        if p.exists() and p.is_file():
            return p

    # Otherwise, search by filename in kb dirs
    candidates: List[Path] = []
    for d in kb_dirs:
        root = Path(d)
        if not root.exists():
            continue
        candidates.extend([p for p in root.rglob(best.source) if p.is_file()])

    if candidates:
        return sorted(candidates)[0]

    raise RuntimeError(
        "Cannot resolve template file path for best match source. "
        f"source={best.source!r} source_path={best.source_path!r} searched_dirs={kb_dirs!r}"
    )


def _replace_placeholders(*, template_text: str, info: Dict[str, Any]) -> str:
    d1_id, d1_cit, _ = _get_cited_doc(info, "D1")
    d2_id, d2_cit, d2_ref = _get_cited_doc(info, "D2")
    date = str(info.get("date") or "").strip()
    examiner = str(info.get("examiner_name") or "").strip()
    basis_items = info.get("basis") or []
    basis_text = ""
    if isinstance(basis_items, list) and basis_items:
        parts = []
        for b in basis_items:
            if not isinstance(b, dict):
                continue
            para = str(b.get("paragraph") or "").strip()
            snippet = str(b.get("snippet") or "").strip()
            if not para and not snippet:
                continue
            if para:
                parts.append(f"[{para}] {snippet}".strip())
            else:
                parts.append(snippet)
        basis_text = "\n".join([p for p in parts if p]).strip()

    # Provide robust replacements: placeholders and light-touch token replacements.
    replacements = {
        "[STANDARD_REF]": d2_ref or "3GPP TS",
        "{{STANDARD_REF}}": d2_ref or "3GPP TS",
        "[D1_CITATION]": d1_cit or d1_id,
        "{{D1_CITATION}}": d1_cit or d1_id,
        "[D2_CITATION]": d2_cit or d2_id,
        "{{D2_CITATION}}": d2_cit or d2_id,
        "[D1]": d1_id,
        "{{D1}}": d1_id,
        "[D2]": d2_id,
        "{{D2}}": d2_id,
        "[DATE]": date,
        "{{DATE}}": date,
        "[EXAMINER]": examiner,
        "{{EXAMINER}}": examiner,
        "[BASIS]": basis_text,
        "{{BASIS}}": basis_text,
    }

    out = template_text
    for k, v in replacements.items():
        out = out.replace(k, v)

    # If template uses bare D1/D2 tokens, replace only when they appear as standalone tokens.
    if d1_cit:
        out = re.sub(r"\bD1\b", d1_id, out)
    if d2_cit:
        out = re.sub(r"\bD2\b", d2_id, out)

    return _normalize(out) + "\n"


class FinalResponseBuilder:
    def __init__(
        self,
        *,
        info: Dict[str, Any],
        results: Any,
        kb_dirs: Optional[List[str]] = None,
    ) -> None:
        self.info = info or {}
        self.results = results
        self.kb_dirs = kb_dirs or ["data/mock_private_knowledge_base", "private_knowledge_base"]

    def build(self) -> Tuple[str, BestMatch]:
        application_no = str(self.info.get("application_number") or "").strip()
        applicant = str(self.info.get("applicant") or "").strip()
        date = str(self.info.get("date") or "").strip()
        examiner = str(self.info.get("examiner_name") or "").strip()

        best = _pick_best_match(self.results)
        template_path = _resolve_template_path(best=best, kb_dirs=self.kb_dirs)
        template_text = template_path.read_text(encoding="utf-8", errors="ignore")
        filled_template = _replace_placeholders(template_text=template_text, info=self.info)

        basis_items = self.info.get("basis") or []
        basis_block = ""
        if isinstance(basis_items, list) and basis_items:
            lines = ["BASIS IN THE APPLICATION AS FILED", ""]
            for b in basis_items:
                if not isinstance(b, dict):
                    continue
                para = str(b.get("paragraph") or "").strip()
                snippet = str(b.get("snippet") or "").strip()
                if not snippet:
                    continue
                if para:
                    lines.append(f"- [{para}] {snippet}")
                else:
                    lines.append(f"- {snippet}")
            basis_block = "\n".join(lines).strip() + "\n\n"

        header_lines = [
            "EUROPEAN PATENT OFFICE",
            "",
            "Response to the Communication pursuant to Article 94(3) EPC",
            "",
            f"Application No: {application_no}" if application_no else "Application No:",
            f"Applicant: {applicant}" if applicant else "Applicant:",
            f"Date: {date}" if date else "Date:",
            f"Examiner: {examiner}" if examiner else "Examiner:",
            "",
            f"(Best matched template source: {best.source}, distance={best.distance:.6f})",
            "",
        ]

        body = "\n".join(header_lines) + basis_block + filled_template
        audited = LegalLanguageAudit().audit(text=body, info=self.info)
        return audited, best

    def write(self, *, output_dir: str = "data/output") -> Path:
        text, _best = self.build()

        out_root = Path(output_dir)
        out_root.mkdir(parents=True, exist_ok=True)

        application_no = str(self.info.get("application_number") or "").strip() or "Unknown"
        safe_app = re.sub(r"[^0-9A-Za-z_.-]+", "_", application_no)

        out_path = out_root / f"Response_{safe_app}_Draft.txt"
        out_path.write_text(text, encoding="utf-8")
        return out_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--info", required=True, help="Path to info JSON (parse_office_action output)")
    parser.add_argument("--results", required=True, help="Path to results JSON (list of SearchResult-like dicts)")
    parser.add_argument(
        "--kb",
        default="data/mock_private_knowledge_base,private_knowledge_base",
        help="Comma-separated KB directories to search template files (default searches mock then private)",
    )
    parser.add_argument("--output-dir", default="data/output")
    args = parser.parse_args()

    info_obj = _load_json(args.info)
    results_obj = _load_json(args.results)
    kb_dirs = [p.strip() for p in str(args.kb).split(",") if p.strip()]

    builder = FinalResponseBuilder(info=info_obj, results=results_obj, kb_dirs=kb_dirs)
    out_path = builder.write(output_dir=args.output_dir)
    print(out_path.as_posix())


if __name__ == "__main__":
    main()
