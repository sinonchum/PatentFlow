from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.data_processor import PatentParser
from src.report_generator import FinalResponseBuilder
from src.vector_store import PatentVectorStore


def _build_query_text(info: Dict[str, Any]) -> str:
    refs = []
    for d in info.get("cited_documents") or []:
        if isinstance(d, dict) and d.get("standard_ref"):
            refs.append(str(d.get("standard_ref")).strip())
    refs_str = ", ".join([r for r in refs if r]) if refs else "3GPP TS"

    # Include D1/D2 signals if available
    d1 = ""
    d2 = ""
    for d in info.get("cited_documents") or []:
        if not isinstance(d, dict):
            continue
        if str(d.get("id") or "").upper() == "D1":
            d1 = str(d.get("citation") or "").strip() or "D1"
        if str(d.get("id") or "").upper() == "D2":
            d2 = str(d.get("citation") or "").strip() or "D2"

    d1_str = f"D1: {d1}. " if d1 else ""
    d2_str = f"D2: {d2}. " if d2 else ""

    return (
        d1_str
        + d2_str
        + f"Art. 56 inventive step objection combining D1 with D2 ({refs_str}). "
        + "Office action alleges obviousness by applying standard HARQ-ACK / PHY procedure teaching to D1 in 5G NR. "
        + "Need rebuttal: no motivation, options in standard, reasonable expectation of success, protocol-layer incompatibility, avoid hindsight."
    )


def _parse_keywords(val: str) -> List[str]:
    if not val:
        return []
    parts = [p.strip() for p in str(val).split(",")]
    return [p for p in parts if p]


def run_pipeline(
    *,
    oa_path: str,
    kb_dir: str,
    persist_dir: str,
    collection: str,
    spec_path: str = "",
    basis_keywords: Optional[Sequence[str]] = None,
) -> Path:
    oa_file = Path(oa_path)
    if not oa_file.exists():
        raise RuntimeError(f"OA file not found: {oa_path}")

    oa_text = oa_file.read_text(encoding="utf-8", errors="ignore")

    parser = PatentParser()
    info = parser.parse_office_action(oa_text)

    # Optional basis search in specification
    spec_path = str(spec_path or "").strip()
    kws = [k.strip() for k in (basis_keywords or []) if k and k.strip()]
    if spec_path:
        if not kws:
            kws = [
                "dynamic scheduling offset",
                "K0",
                "K2",
                "HARQ",
                "HARQ-ACK",
                "DCI",
                "PDSCH",
                "PUSCH",
            ]
        info["basis"] = parser.find_basis(spec_path, keywords=kws)

    raw_dir = Path("data/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    stem = oa_file.stem
    info_path = raw_dir / f"{stem}.info.json"
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    store = PatentVectorStore(persist_path=persist_dir, collection_name=collection)
    query_text = _build_query_text(info)
    results = store.query_similar_logic(
        query_text,
        n_results=5,
        examiner_name=str(info.get("examiner_name") or ""),
    )

    results_path = raw_dir / f"{stem}.results.json"
    results_path.write_text(
        json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    builder = FinalResponseBuilder(info=info, results=[r.__dict__ for r in results], kb_dirs=[kb_dir, "private_knowledge_base"])
    out_path = builder.write(output_dir="data/output")

    # Minimal console output for the bash wrapper
    print(json.dumps({"info": info_path.as_posix(), "results": results_path.as_posix(), "output": out_path.as_posix()}, ensure_ascii=False))
    return out_path


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--oa_path", required=True)
    ap.add_argument("--kb_dir", default="data/mock_private_knowledge_base")
    ap.add_argument("--persist", default="data/vector_db")
    ap.add_argument("--collection", default="telecom_responses")
    ap.add_argument("--spec_path", default="", help="Optional path to specification text to search for basis")
    ap.add_argument(
        "--basis_keywords",
        default="",
        help="Comma-separated keywords to locate basis paragraphs in the specification (used with --spec_path)",
    )
    args = ap.parse_args()

    run_pipeline(
        oa_path=args.oa_path,
        kb_dir=args.kb_dir,
        persist_dir=args.persist,
        collection=args.collection,
        spec_path=args.spec_path,
        basis_keywords=_parse_keywords(args.basis_keywords),
    )


if __name__ == "__main__":
    main()
