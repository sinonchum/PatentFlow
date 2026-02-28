from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union


@dataclass
class TemplateHit:
    text: str
    source: str
    distance: Optional[float] = None


def _normalize(text: str) -> str:
    text = (text or "").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(lines).strip()


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


_STRUCTURED_TELECOM_ART56_TEMPLATE = """EUROPEAN PATENT OFFICE

Response to the Communication pursuant to Article 94(3) EPC

Application No: {application_number}
Applicant: {applicant}

Title: Response to Art. 56 EPC objection (Telecom / NR standard-based combination)

I. INTRODUCTION
The Applicant thanks the Examining Division for the detailed examination and hereby responds to the objection under Article 56 EPC.

II. DOCUMENTS CITED
{d1_line}
{d2_line}

III. SUMMARY OF THE OBJECTION
The objection is understood as an inventive-step attack based on {d1_id} combined with {d2_id}. In particular, the Office Action argues that the skilled person would find it obvious to apply teachings from the cited standard document to the system of {d1_id}.

IV. REMARKS UNDER ARTICLE 56 EPC
IV.1 Closest prior art
For the purpose of discussion, {d1_id} is considered the closest prior art.

IV.2 Distinguishing features
The claimed subject-matter is distinguished from {d1_id} at least by:
1) a specific timing/mapping interdependency relating to HARQ feedback timing; and/or
2) an explicit scheduling-offset definition aligned with the claimed protocol-layer responsibilities.

IV.3 Technical effect
The distinguishing timing interdependency provides deterministic and efficient feedback behavior under NR timing constraints, reducing ambiguity and improving reliability.

IV.4 Objective technical problem
Starting from {d1_id}, the objective technical problem may be formulated as:
"How to implement a deterministic HARQ feedback timing/mapping in an NR context while preserving reliable operation under timing constraints and avoiding unnecessary signaling overhead."

IV.5 Non-obviousness of combining {d1_id} with {d2_id}
(a) Standard documents define interoperability envelopes, not a single implementation blueprint
{d2_standard_label} is a standardization document. It contains normative requirements ("shall") as well as alternative configurations and options ("may"). Such documents typically provide a menu of permitted behaviors rather than a singular teaching to implement a specific timing relationship.

(b) Lack of a specific motivation and compatibility bridge
Even if the skilled person consults {d2_id}, there is no direct and unambiguous teaching that would motivate the skilled person to modify {d1_id} towards the particular timing/mapping interdependency as claimed.
Moreover, applying standard-level procedures to a disclosure like {d1_id} requires a concrete compatibility bridge (protocol-layer allocation of responsibilities, signaling assumptions, and timing constraints). {d1_id} does not provide such a bridge.

(c) Avoidance of hindsight
The combination reasoning is affected by ex post facto analysis: it starts from the claimed interdependency and then retrospectively selects elements from the standard that could be fitted to {d1_id}.

(d) Technical synergy beyond a mere collocation
The specific timing interdependency between D1 and D2 as claimed provides a technical synergy that goes beyond a mere collocation of features.

Accordingly, the subject-matter of claim 1 involves an inventive step within the meaning of Article 56 EPC.

V. CONCLUSION
The Applicant respectfully requests that the objection under Article 56 EPC be withdrawn.

Yours faithfully,

{signature}
"""


def generate_structured_telecom_art56_response(*, info: Dict[str, Any]) -> str:
    info = info or {}
    application_number = str(info.get("application_number") or "").strip() or "[to be filled]"
    applicant = str(info.get("applicant") or "").strip() or "[to be filled]"

    d1_id, d1_cit, _ = _get_cited_doc(info, "D1")
    d2_id, d2_cit, d2_ref = _get_cited_doc(info, "D2")
    d2_standard_label = d2_ref or "D2 (3GPP TS standard)"

    d1_line = f"- {d1_id}: {d1_cit}" if d1_cit else f"- {d1_id}"
    d2_line = f"- {d2_id}: {d2_cit}" if d2_cit else f"- {d2_id}"

    signature = applicant if applicant != "[to be filled]" else "Applicant / Representative"

    rendered = _STRUCTURED_TELECOM_ART56_TEMPLATE.format(
        application_number=application_number,
        applicant=applicant,
        d1_id=d1_id,
        d2_id=d2_id,
        d1_line=d1_line,
        d2_line=d2_line,
        d2_standard_label=d2_standard_label,
        signature=signature,
    )
    return _normalize(rendered) + "\n"


def _load_results(results_obj: Any) -> List[TemplateHit]:
    hits: List[TemplateHit] = []

    if results_obj is None:
        return hits

    if isinstance(results_obj, list):
        for item in results_obj:
            if isinstance(item, str):
                hits.append(TemplateHit(text=_normalize(item), source="unknown"))
                continue

            if isinstance(item, dict):
                txt = _normalize(str(item.get("text") or ""))
                meta = item.get("metadata") or {}
                source = "unknown"
                if isinstance(meta, dict):
                    source = str(meta.get("source") or meta.get("source_path") or "unknown")
                dist = item.get("distance")
                try:
                    dist_f = float(dist) if dist is not None else None
                except Exception:
                    dist_f = None
                if txt:
                    hits.append(TemplateHit(text=txt, source=source, distance=dist_f))
                continue

    if isinstance(results_obj, dict) and "text" in results_obj:
        txt = _normalize(str(results_obj.get("text") or ""))
        meta = results_obj.get("metadata") or {}
        source = str(meta.get("source") or meta.get("source_path") or "unknown") if isinstance(meta, dict) else "unknown"
        dist = results_obj.get("distance")
        try:
            dist_f = float(dist) if dist is not None else None
        except Exception:
            dist_f = None
        if txt:
            hits.append(TemplateHit(text=txt, source=source, distance=dist_f))

    return hits


def _pick_best_template_label(hits: Sequence[TemplateHit]) -> str:
    joined = "\n".join([h.source for h in hits]).lower()
    if "telecom_template_a" in joined:
        return "A"
    if "telecom_template_b" in joined:
        return "B"
    if "telecom_template_c" in joined:
        return "C"
    return "B" if hits else "B"


def _extract_3gpp_refs(info: Dict[str, Any]) -> List[str]:
    refs: List[str] = []
    for d in info.get("cited_documents") or []:
        if not isinstance(d, dict):
            continue
        ref = (d.get("standard_ref") or "").strip()
        if ref:
            refs.append(ref)
    seen = set()
    out: List[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


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


def generate_inventive_step_argument(*, info: Dict[str, Any], results: Any) -> str:
    info = info or {}
    hits = _load_results(results)

    d1_id, d1_cit, _ = _get_cited_doc(info, "D1")
    d2_id, d2_cit, d2_ref = _get_cited_doc(info, "D2")
    d2_label = d2_ref or "a 3GPP TS standard"

    def _pick_template_text() -> str:
        for h in hits:
            if "telecom_template_a" in (h.source or "").lower():
                return h.text
        return hits[0].text if hits else ""

    template_text = _pick_template_text()

    d1_cite_line = f"{d1_id}: {d1_cit}" if d1_cit else d1_id
    d2_cite_line = f"{d2_id}: {d2_cit}" if d2_cit else d2_id

    synergy_sentence = (
        "The specific timing interdependency between D1 and D2 as claimed provides a technical synergy "
        "that goes beyond a mere collocation of features."
    )

    remarks = "\n".join(
        [
            "REMARKS",
            f"The Examining Division alleges that the subject-matter of claim 1 is obvious over {d1_id} in view of {d2_id}.",
            f"{d1_cite_line}",
            f"{d2_cite_line}",
            "",
            f"The Applicant respectfully submits that {d2_label} is a standardization document containing normative requirements (\"shall\") alongside optional or alternative procedures (\"may\"/options). ",
            "The mere existence of a standardized procedure does not, by itself, provide a teaching or motivation to implement the specific timing/mapping relationship recited in claim 1.",
            "",
            f"Furthermore, {d2_id} addresses interoperability at the standard level, whereas {d1_id} represents a particular disclosure/implementation context. ",
            "Without a concrete pointer in the prior art, the skilled person would not automatically transplant a standard-compliance mechanism into the specific architecture of D1, ",
            "especially where doing so requires aligning protocol-layer responsibilities, timing constraints, and signaling assumptions that are not disclosed in D1.",
            "",
            synergy_sentence,
            "",
            "In addition, the combination reasoning is affected by hindsight: the Office Action starts from the claimed solution (a particular timing interdependency) ",
            "and then retrospectively searches for elements in the standard that could be fitted to D1. Standards frequently provide multiple permitted configurations; ",
            "selecting the claimed interdependency from among those alternatives is not derivable without knowledge of the invention.",
            "",
        ]
    ).strip()

    if template_text:
        remarks = (remarks + "\n" + "Template anchor:\n" + _normalize(template_text)).strip()

    return remarks + "\n"


def generate_draft(info: Dict[str, Any], results: Any) -> str:
    info = info or {}
    hits = _load_results(results)

    application_no = str(info.get("application_number") or "").strip()
    applicant = str(info.get("applicant") or "").strip()
    cited = info.get("cited_documents") or []
    epc_articles = info.get("epc_articles") or []

    best = _pick_best_template_label(hits)
    refs = _extract_3gpp_refs(info)
    refs_str = ", ".join(refs) if refs else "3GPP TS document(s)"

    d1 = "D1"
    d2 = "D2"
    for d in cited:
        if isinstance(d, dict) and str(d.get("id") or "").upper() == "D1":
            d1 = f"D1: {d.get('citation') or 'D1'}"
        if isinstance(d, dict) and str(d.get("id") or "").upper() == "D2":
            d2 = f"D2: {d.get('citation') or 'D2'}"

    header = "\n".join(
        [
            "EUROPEAN PATENT OFFICE",
            "",
            "Response to the Communication pursuant to Article 94(3) EPC",
            "",
            f"Application No: {application_no}" if application_no else "Application No:",
            f"Applicant: {applicant}" if applicant else "Applicant:",
            "",
        ]
    ).rstrip()

    intro = "\n".join(
        [
            "1. Introduction",
            "The Applicant hereby responds to the objections raised in the Communication.",
            "The present response is drafted based on an internal response template selected from the local template library.",
            f"Template used: {best}",
            "",
            "2. Cited documents",
            f"- {d1}",
            f"- {d2}",
            "",
        ]
    )

    has84 = "Art. 84" in [str(a) for a in epc_articles]
    has56 = "Art. 56" in [str(a) for a in epc_articles]

    art84 = "\n".join(
        [
            "3. Clarity (Art. 84 EPC)",
            "The term \"dynamic scheduling offset\" in claim 1 is clarified to provide objective technical boundaries.",
            "In the 5G NR context, this offset can relate to well-understood scheduling timing parameters such as K0 (PDSCH scheduling) or K2 (PUSCH scheduling).",
            "To avoid ambiguity, the claim wording is amended (where appropriate) to explicitly tie the offset to the relevant channel and scheduling timing, and to specify the entity and protocol layer responsible for applying the offset.",
            "The clarification is supported by the application as filed, which describes the scheduling timing relationship in the NR procedure context (e.g., downlink vs uplink scheduling timelines), thereby providing basis in the description for the amended terminology.",
            "",
        ]
    )

    art56 = "\n".join(
        [
            "4. Inventive step (Art. 56 EPC)",
            "The objection is understood as a combination attack based on D1 in view of D2.",
            "The alleged combination relies on the assumption that the skilled person would directly apply a standard document teaching to the system of D1. However, such a step is not automatic and requires a specific technical motivation and a compatible protocol-layer context.",
            f"In particular, {refs_str} describes procedures/options in a standardization context and does not uniquely teach the specific mapping/relationship recited in claim 1. Standards often provide multiple alternatives, and do not provide a motivation to select the specific coupling absent hindsight.",
            "Moreover, the claimed mapping concerns a concrete implementation constraint (e.g., a timing/mapping rule for HARQ feedback) that is not disclosed in D1 and is not derivable as a mandatory consequence from D2.",
            "Accordingly, the skilled person starting from D1 would not arrive at the claimed subject-matter without ex post facto analysis.",
            "",
            generate_inventive_step_argument(info=info, results=results).rstrip(),
            "",
        ]
    )

    templ = "\n".join(
        [
            "5. Retrieved template excerpts (for traceability)",
            *(
                [
                    f"[Source: {h.source}{'' if h.distance is None else f', distance={h.distance:.4f}'}]",
                    _normalize(h.text),
                    "",
                ]
                for h in hits[:3]
            ),
        ]
    ).rstrip()

    body_parts: List[str] = [header, intro]
    if has84:
        body_parts.append(art84)
    if has56:
        body_parts.append(art56)
    if hits:
        body_parts.append(templ)

    closing = "\n".join(
        [
            "Yours faithfully,",
            "",
            "Global Telecom Solutions Inc.",
        ]
    )

    return "\n".join([p.rstrip() for p in body_parts if p.strip()] + [closing]).strip() + "\n"


def finalize_with_local_llm(*, info: Dict[str, Any], results: Any, draft: str) -> str:
    from src.engine.router import PatentRouter

    info = info or {}
    hits = _load_results(results)

    top_logic = hits[0].text if hits else ""
    prompt = f"""
You are a European patent attorney assistant. Rewrite and polish the following draft into a formal EPO response letter.

## Parsed Office Action info (structured)
{json.dumps(info, ensure_ascii=False, indent=2)}

## Retrieved response logic excerpt (most relevant)
{top_logic}

## Rules
- Keep the letter structure and headings suitable for EPO practice.
- Do NOT introduce new technical features not supported by the draft/info.
- Keep Art. 84 and Art. 56 reasoning consistent across sections.
- If amendments are mentioned, keep them minimal and explicitly anchored to the description as filed (generic citation is OK).

## Draft to polish
{draft}
""".strip()

    router = PatentRouter()
    engine = router.route(prompt, is_sensitive=True)
    return engine.generate(prompt)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--info", required=True, help="Path to info JSON (e.g., PatentParser.parse_office_action output)")
    parser.add_argument(
        "--results",
        required=True,
        help="Path to results JSON (list of SearchResult-like dicts) or a .txt containing template excerpt",
    )
    parser.add_argument(
        "--structured-template",
        action="store_true",
        help="If set, ignore results/LLM and render a highly structured telecom Art.56 response letter purely from info.",
    )
    parser.add_argument(
        "--finalize-with-llm",
        action="store_true",
        help="If set, use local Ollama (PatentRouter with is_sensitive=True) to polish the rule-based draft into final text.",
    )
    parser.add_argument(
        "--only-final",
        action="store_true",
        help="If set together with --finalize-with-llm, only print the final LLM output.",
    )
    args = parser.parse_args()

    info_obj = _load_json(args.info)

    if args.structured_template:
        print(generate_structured_telecom_art56_response(info=info_obj))
        return

    results_path = Path(args.results)
    if results_path.suffix.lower() == ".txt":
        results_obj: Any = results_path.read_text(encoding="utf-8", errors="ignore")
        results_obj = [results_obj]
    else:
        results_obj = _load_json(args.results)

    draft = generate_draft(info=info_obj, results=results_obj)

    final_text: Optional[str] = None
    if args.finalize_with_llm:
        final_text = finalize_with_local_llm(info=info_obj, results=results_obj, draft=draft)

    if args.only_final and final_text is not None:
        print(final_text)
        return

    print("===== RULE-BASED DRAFT =====")
    print(draft)
    if final_text is not None:
        print("===== OLLAMA FINAL =====")
        print(final_text)


if __name__ == "__main__":
    main()
