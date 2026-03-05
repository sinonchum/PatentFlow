import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .base import PatentAgentSkill, SkillResult
from src.memory_manager import LocalMemoryManager


class ChartRow(BaseModel):
    """Single row in the Art. 56 Claim Chart."""
    feature_id: str = Field(description="Feature identifier (e.g., 1.1, 1.2)")
    limitation: str = Field(description="Claim limitation text")
    d1_disclosure: str = Field(description="Prior art disclosure text with paragraph refs")
    assessment: Literal["Yes", "No", "Partial"] = Field(description="Disclosure assessment")
    remarks: str = Field(default="", description="Attorney remarks (blank for manual entry)")


class ClaimChartResult(SkillResult):
    """Typed result envelope for claim chart generation."""
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "chart": [],
            "cited_docs": []
        }
    )


class ClaimChartGenerator(PatentAgentSkill[ClaimChartResult]):
    """
    Skill for Art. 56 Inventive Step Analysis.
    Generates a structured mapping between claims and Prior Art.

    Design principle: Deterministic heuristic parsing for claim splitting,
    then LLM-assisted matching for prior art disclosure assessment.
    """

    def _tokenize_claim(self, claim_text: str) -> List[Dict[str, str]]:
        """
        TRADE SECRET LOGIC: Deterministic heuristic parsing.
        Splits a claim into features (1.1, 1.2) based on transitional phrases
        and punctuation, ignoring nested clauses.
        """
        text = (claim_text or "").strip()
        if not text:
            return []

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)

        # Handle comprising: as the main transition
        comprising_match = re.search(r'\bcomprising\s*[:;，,]\s*', text, flags=re.IGNORECASE)

        features = []
        if comprising_match:
            # Preamble is everything up to and including comprising:
            preamble = text[:comprising_match.end()].strip()
            if preamble:
                features.append({
                    "feature_id": "1.1",
                    "limitation": preamble
                })

            # The rest is body elements separated by semicolons or periods
            rest = text[comprising_match.end():]
            # Split on semicolons, periods, or Chinese punctuation
            parts = re.split(r'[;；\.。]\s*', rest)

            idx = 2  # Start from 1.2
            for part in parts:
                clean = part.strip()
                # Skip transitional phrases alone
                if clean and clean.lower() not in ('and', 'or', 'wherein', '所述'):
                    features.append({
                        "feature_id": f"1.{idx}",
                        "limitation": clean
                    })
                    idx += 1
        else:
            # Fallback: split on punctuation if no comprising found
            parts = re.split(r'[;；\.。]\s*', text)
            for i, part in enumerate(parts, 1):
                clean = part.strip()
                if clean:
                    features.append({
                        "feature_id": f"1.{i}",
                        "limitation": clean
                    })

        return features

    def _extract_cited_docs(self, office_action_text: str) -> List[str]:
        """Extract cited documents (D1, D2, etc.) from office action."""
        if not office_action_text:
            return []
        docs = set(re.findall(r'\bD([1-9][0-9]*)\b', office_action_text, flags=re.IGNORECASE))
        return [f"D{n}" for n in sorted(docs, key=lambda x: int(x))]

    def _extract_snippets_for_doc(self, office_action_text: str, doc_id: str) -> List[str]:
        """Extract relevant text snippets mentioning a specific document."""
        if not office_action_text:
            return []

        # Strategy 1: Look for Document X is regarded as... followed by bullet points
        # Pattern: "Document D1 is regarded as... discloses:" followed by list items
        doc_section_pattern = rf'(?:Document\s+{re.escape(doc_id)}|{re.escape(doc_id)}).*?(?:discloses|describes).*?(?:(?:Paragraph\s*\[[0-9]+\]).*?)+((?:-\s+.+?(?:Paragraph\s*\[[0-9]+\][;,]?).*?)+)'
        matches = re.findall(doc_section_pattern, office_action_text, flags=re.IGNORECASE | re.DOTALL)
        if matches:
            # Split bullet points
            bullets = re.findall(r'-\s+(.+?)(?=\n\s*-|\n\n|$)', matches[0], flags=re.DOTALL)
            if bullets:
                return [b.strip() for b in bullets if b.strip()]

        # Strategy 2: Find doc-scoped sections (more lenient)
        pattern = rf'(?:^|\n)(?:\s*\d+\.\d+\s+)?.*?\b{re.escape(doc_id)}\b.*?(?:\n|$)(.*?)(?=\n(?:\s*\d+\.\d+\s+)?\bD[1-9][0-9]*\b|\Z)'
        scoped = re.findall(pattern, office_action_text, flags=re.IGNORECASE | re.DOTALL)
        out = [s.strip() for s in scoped if s and s.strip()]
        if out:
            # Further split by bullet points or sentences
            result = []
            for section in out:
                # Look for bullet points
                bullets = re.findall(r'[-•\*]\s*(.+?)(?=\n\s*[-•\*]|\n\n|$)', section, flags=re.DOTALL)
                if bullets:
                    result.extend([b.strip() for b in bullets if b.strip()])
                else:
                    # Split by paragraph references
                    para_splits = re.split(r'(Paragraph\s*\[[0-9]+\][;,]?)', section)
                    if len(para_splits) > 1:
                        for i in range(0, len(para_splits)-1, 2):
                            text_part = para_splits[i].strip()
                            para_ref = para_splits[i+1] if i+1 < len(para_splits) else ""
                            if text_part:
                                result.append(f"{text_part} ({para_ref.strip()})".strip())
                    else:
                        result.append(section)
            return result

        # Strategy 3: Fallback - split by sentences and filter
        sentences = re.split(r'(?<=[.!?。；;])\s+', office_action_text)
        doc_sentences = [s.strip() for s in sentences if re.search(rf'\b{re.escape(doc_id)}\b', s, flags=re.IGNORECASE)]
        
        # Extract paragraphs from these sentences too
        result = []
        for sent in doc_sentences:
            para_refs = re.findall(r'Paragraph\s*\[([0-9]+)\]', sent, flags=re.IGNORECASE)
            if para_refs:
                # Include the sentence with its paragraph reference
                result.append(sent)
        
        return result if result else doc_sentences

    def _extract_refs(self, text: str) -> List[str]:
        """Extract paragraph or figure references like [0045], Fig. 1."""
        refs = re.findall(r'\[[0-9]{3,4}\]|Fig\.?\s*[0-9A-Za-z]+', text or "", flags=re.IGNORECASE)
        seen = set()
        out = []
        for r in refs:
            rr = r.strip()
            if rr not in seen:
                seen.add(rr)
                out.append(rr)
        return out

    def _format_disclosure(self, doc_id: str, snippet: str, refs: List[str]) -> str:
        """Format prior art disclosure text with reference markers."""
        s = (snippet or "").strip()
        s = re.sub(r'\s+', ' ', s)

        # Remove duplicated leading phrases
        s = re.sub(rf'(?i)^(?:\s*{re.escape(doc_id)}\s+discloses\s+)+', '', s)

        # Remove wrapping quotes
        s = s.strip().strip('"').strip("'")
        s = s.rstrip(" .")

        # If already has reference marker, don't add another
        if re.search(r'\(\s*(paragraph|see)\s+[^)]+\)', s, flags=re.IGNORECASE):
            return f"{doc_id} discloses {s}."

        # Add reference if available
        if refs:
            ref = refs[0]
            if ref.startswith('['):
                # Clean any existing paragraph reference in snippet
                s_clean = re.sub(r'\(\s*paragraph\s+\[[0-9]{3,4}\]\s*\)', '', s, flags=re.IGNORECASE).strip().rstrip(" .")
                if re.search(re.escape(ref), s, flags=re.IGNORECASE):
                    return f"{doc_id} discloses {s_clean}."
                return f"{doc_id} discloses {s_clean} (paragraph {ref})."
            else:
                s_clean = re.sub(r'\(\s*see\s+[^)]+\)', '', s, flags=re.IGNORECASE).strip().rstrip(" .")
                if re.search(re.escape(ref), s, flags=re.IGNORECASE):
                    return f"{doc_id} discloses {s_clean}."
                return f"{doc_id} discloses {s_clean} (see {ref})."

        return f"{doc_id} discloses {s}."

    def _token_overlap(self, text1: str, text2: str) -> int:
        """Count token overlap between two texts (simple heuristic)."""
        tokens1 = set(re.findall(r'[A-Za-z0-9]{3,}', text1.lower()))
        tokens2 = set(re.findall(r'[A-Za-z0-9]{3,}', text2.lower()))
        return len(tokens1 & tokens2)

    def _parse_llm_assessment_json(self, raw: str) -> tuple[Literal["Yes", "No", "Partial"], str]:
        import json

        text = (raw or "").strip()
        if not text:
            raise ValueError("Empty LLM response")

        # Best-effort extraction if the model wrapped JSON in prose / markdown.
        start = text.find("{")
        end = text.rfind("}")
        candidate = text
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]

        obj = json.loads(candidate)
        if not isinstance(obj, dict):
            raise ValueError("LLM response JSON is not an object")

        assessment_raw = str(obj.get("assessment") or "").strip()
        reasoning = str(obj.get("reasoning") or "").strip()

        if assessment_raw not in {"Yes", "No", "Partial"}:
            raise ValueError(f"Invalid assessment value: {assessment_raw!r}")

        return assessment_raw, reasoning

    def execute(
        self,
        claim_text: str,
        prior_art_text: str,
        office_action_text: str = "",
        attorney_id: str = "Default",
    ) -> ClaimChartResult:
        """
        Generate claim chart comparing claim features against prior art.

        Args:
            claim_text: The patent claim text
            prior_art_text: General prior art description (fallback)
            office_action_text: Office action text with D1/D2 references

        Returns:
            ClaimChartResult with chart rows and cited documents
        """
        preferences = ""
        if (attorney_id or "").strip() and attorney_id != "Default":
            try:
                preferences = LocalMemoryManager().get_preferences(attorney_id)
            except Exception:
                preferences = ""

        base_system_prompt = (
            "You are an EPO Patent Examiner. Analyze if the following claim feature is disclosed in the Prior Art."
        )
        if preferences:
            system_prompt = (
                f"{base_system_prompt}\n\n"
                "[CRITICAL USER PREFERENCES TO FOLLOW STRICTLY]\n"
                f"{preferences}\n"
                "[/CRITICAL USER PREFERENCES]"
            )
        else:
            system_prompt = base_system_prompt

        # Step 1: Deterministically split claim into features
        features = self._tokenize_claim(claim_text)

        # Step 2: Extract cited documents from office action
        cited_docs = self._extract_cited_docs(office_action_text)
        if not cited_docs:
            cited_docs = ["D1"]

        # Step 3: Extract snippets for each cited doc
        doc_to_snippets = {
            d: self._extract_snippets_for_doc(office_action_text, d)
            for d in cited_docs
        }

        # Step 4: Match each feature to best prior art evidence
        chart_data = []
        # Track used snippets to ensure different features get different snippets
        used_snippet_indices: set[tuple[str, int]] = set()

        for feature in features:
            best_doc = cited_docs[0]
            best_snippet = ""
            best_refs = []
            best_snippet_idx = (-1, -1)  # (doc_idx, snippet_idx)

            # Find best matching snippet across all cited docs
            for doc_idx, doc_id in enumerate(cited_docs):
                snippets = doc_to_snippets.get(doc_id, [])
                if not snippets:
                    continue

                for snippet_idx, snippet in enumerate(snippets):
                    # Prefer unused snippets; otherwise prefer longer snippets as richer context.
                    if (doc_idx, snippet_idx) in used_snippet_indices:
                        continue

                    if not best_snippet or len(snippet) > len(best_snippet):
                        best_doc = doc_id
                        best_snippet = snippet
                        best_refs = self._extract_refs(snippet)
                        best_snippet_idx = (doc_idx, snippet_idx)

                # Fallback: if everything is used, take the longest snippet from this doc.
                if not best_snippet:
                    longest_idx = max(range(len(snippets)), key=lambda i: len(snippets[i]))
                    best_doc = doc_id
                    best_snippet = snippets[longest_idx]
                    best_refs = self._extract_refs(best_snippet)
                    best_snippet_idx = (doc_idx, longest_idx)

            # Mark this snippet as used
            if best_snippet_idx[0] >= 0:
                used_snippet_indices.add(best_snippet_idx)

            # Use fallback prior_art_text if no match found
            if not best_snippet:
                best_snippet = prior_art_text or "Not disclosed in prior art."
                best_refs = []

            assessment: Literal["Yes", "No", "Partial"] = "Partial"
            remarks = ""

            # LLM-based semantic assessment (strict JSON)
            try:
                if self.llm is None:
                    raise RuntimeError("LLM client is not configured for ClaimChartGenerator")

                limitation = str(feature.get("limitation") or "").strip()
                prior_art_context = (best_snippet or "").strip()

                user_prompt = (
                    "You will be given:\n"
                    "(1) a claim feature (limitation) and\n"
                    "(2) a prior art excerpt.\n\n"
                    "Task: Decide whether the prior art discloses the limitation.\n\n"
                    "Output MUST be strict JSON only, with exactly these keys:\n"
                    '{"assessment":"Yes|No|Partial","reasoning":"..."}\n\n'
                    f"Limitation:\n{limitation}\n\n"
                    f"Prior Art Excerpt:\n{prior_art_context}\n"
                )

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]

                if hasattr(self.llm, "chat"):
                    raw = self.llm.chat(messages)  # type: ignore[attr-defined]
                elif hasattr(self.llm, "generate"):
                    raw = self.llm.generate(prompt=user_prompt, messages=messages)  # type: ignore[attr-defined]
                else:
                    raise RuntimeError("Unsupported LLM client interface; expected .chat(...) or .generate(...)")

                assessment, reasoning = self._parse_llm_assessment_json(str(raw))
                remarks = reasoning
            except Exception as e:
                # Graceful fallback on LLM/JSON issues.
                assessment = "Partial"
                remarks = f"LLM_ASSESSMENT_ERROR: {str(e)}"

            # Format disclosure text
            disclosure = self._format_disclosure(best_doc, best_snippet, best_refs)

            chart_data.append({
                "feature_id": feature["feature_id"],
                "limitation": feature["limitation"],
                "d1_disclosure": disclosure,
                "assessment": assessment,
                "remarks": remarks,
            })

        # Return standardized result
        return self._ok({
            "chart": chart_data,
            "cited_docs": cited_docs
        })
