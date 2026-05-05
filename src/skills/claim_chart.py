import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from .base import PatentAgentSkill, SkillResult
from src.memory_manager import LocalMemoryManager


class ChartRow(BaseModel):
    """Single row in the Art. 56 Claim Chart."""
    feature_id: str = Field(description="Feature identifier (e.g., 1.1, 1.2)")
    limitation: str = Field(description="Claim limitation text")
    d1_disclosure: str = Field(description="Prior art disclosure text with paragraph refs")
    assessment: Literal["Yes", "No", "Partial"] = Field(description="Disclosure assessment")
    remarks: str = Field(default="", description="LLM reasoning / attorney remarks")


class ClaimChartResult(SkillResult):
    data: Dict[str, Any] = Field(
        default_factory=lambda: {"chart": [], "cited_docs": []}
    )


class ClaimChartGenerator(PatentAgentSkill[ClaimChartResult]):
    """
    Art. 56 Inventive Step Claim Chart Generator.

    Pipeline:
      1. Tokenize claim into features using gerundive-verb detection
         (preserves nested comprising sub-items as a single feature).
      2. Parse the Office Action's structured disclosure (a)/(b)/... and
         distinguishing feature (i)/(ii)/... sections.
      3. Anchor each claim feature to its OA disclosure by positional mapping;
         downgrade to Partial/No when overlap with a distinguishing item is found.
      4. Optionally override assessment with LLM semantic judgement.
    """

    # ------------------------------------------------------------------ #
    # Step 1 — Claim Tokenizer                                            #
    # ------------------------------------------------------------------ #

    def _tokenize_claim(self, claim_text: str) -> List[Dict[str, str]]:
        """
        Gerundive-verb-based claim feature splitter.

        Method claims separate features with "; [gerundive]" patterns.
        Nested comprising sub-items ("a first phase...; a second phase...")
        are NOT gerundives so they stay bundled with their parent feature.
        Apparatus claims fall back to semicolon splitting.
        """
        text = re.sub(r"\s+", " ", (claim_text or "").strip())
        if not text:
            return []

        # Locate the top-level transition phrase
        m = re.search(
            r'\b(?:comprising|characterized\s+in\s+that)\s*:\s*',
            text, re.IGNORECASE
        )
        features: List[Dict[str, str]] = []

        if m:
            preamble = text[:m.end()].strip()
            features.append({"feature_id": "1.1", "limitation": preamble})
            body = text[m.end():]
        else:
            body = text

        # Split on "; [optional: and/or] [feature_start]" where feature_start is:
        #   - a gerundive verb ([a-z]+ing, hyphenated fine-tuning, etc.)
        #   - a conditional prefix (when ΔT..., if condition...)
        # "when\b" does NOT match "wherein" since "wherein" starts with w-h-e-r, not w-h-e-n.
        gerundive_split = re.compile(
            r';\s*(?:(?:and|or)\s+)?'
            r'(?=[a-z](?:[a-z]+-)?[a-z]*ing\b'   # gerundive (acquiring/fine-tuning…)
            r'|when\b'                              # conditional "when ΔT < …, [verb]"
            r'|if\b(?!\s+the\s+(?:patent|application|claim))'  # conditional "if"
            r')',
            re.IGNORECASE
        )
        segments = gerundive_split.split(body)

        if len(segments) > 1:
            for seg in segments:
                clean = re.sub(
                    r'^(?:and|or)\s+', '', seg.strip(), flags=re.IGNORECASE
                ).rstrip('.')
                if clean and clean.lower() not in ('and', 'or', 'wherein', '所述'):
                    features.append({
                        "feature_id": f"1.{len(features) + 1}",
                        "limitation": clean
                    })
        else:
            # Apparatus / system claim fallback: split on semicolons
            for part in re.split(r'[;；]\s*', body):
                clean = re.sub(
                    r'^(?:and|or)\s+', '', part.strip(), flags=re.IGNORECASE
                ).rstrip('.')
                if clean and clean.lower() not in ('and', 'or', 'wherein', '所述'):
                    features.append({
                        "feature_id": f"1.{len(features) + 1}",
                        "limitation": clean
                    })

        return features

    # ------------------------------------------------------------------ #
    # Step 2 — Office Action Structure Parser                             #
    # ------------------------------------------------------------------ #

    def _parse_oa_structure(self, oa_text: str) -> Dict[str, Any]:
        """
        Parse the OA's feature-by-feature disclosure analysis and its
        distinguishing feature list.

        Handles two EPO OA bullet styles:
          Style A: "  (a) Acquiring digital images... (D1, [0034], claim 1(a));"
          Style B: "  Feature (a): acquiring temperature... (D1, [0026], claim 1(a));"

        Returns {
          "disclosed":       [{"letter", "text", "refs", "doc"}, ...],
          "distinguishing":  [{"numeral", "text"}, ...]
        }
        """
        disclosed: List[Dict[str, Any]] = []
        distinguishing: List[Dict[str, Any]] = []

        if not oa_text:
            return {"disclosed": disclosed, "distinguishing": distinguishing}

        # Lettered items (a)-(e) anchored to line start with 1-10 leading spaces.
        # Lookahead terminates at the next bullet or end of string.
        letter_pat = re.compile(
            r'^\s{1,10}(?:Feature\s+)?\(([a-e])\)\s*:?\s*(.+?)'
            r'(?=\n\s{0,10}(?:Feature\s+)?\([a-e]\)|\Z)',
            re.IGNORECASE | re.MULTILINE | re.DOTALL
        )
        for m in letter_pat.finditer(oa_text):
            letter = m.group(1).lower()
            if any(d["letter"] == letter for d in disclosed):
                continue
            body = re.sub(r'\s+', ' ', m.group(2)).strip().rstrip(';.')
            doc_m = re.search(r'\((D[1-9])', body, re.IGNORECASE)
            refs = re.findall(
                r'\[[0-9]+(?:-[0-9]+)?\]|claim\s+\w+|FIG\.?\s*\w+',
                body[:300], re.IGNORECASE
            )
            # Remove claim sub-letter refs like claim 1(a) from refs list
            refs = [r for r in refs if not re.match(r'^claim\s+\d+\([a-e]\)$', r, re.IGNORECASE)]
            disclosed.append({
                "letter": letter,
                "text": body,
                "refs": refs[:3],
                "doc": doc_m.group(1).upper() if doc_m else "D1"
            })

        # Roman-numeral items (i)/(ii)/(iii) — distinguishing features
        roman_pat = re.compile(
            r'^\s{1,10}\(\s*(i{1,3}|iv|v[i]{0,3})\s*\)\s*(.+?)'
            r'(?=\n\s{0,10}\(\s*(?:i{1,3}|iv|v[i]{0,3})\s*\)|\Z)',
            re.IGNORECASE | re.MULTILINE | re.DOTALL
        )
        for m in roman_pat.finditer(oa_text):
            body = re.sub(r'\s+', ' ', m.group(2)).strip().rstrip('.')
            # Keep only the description of the distinguishing feature (first ~2 sentences).
            # The examiner's OBVIOUSNESS argumentation is separated by keywords.
            trunc = re.split(
                r'(?:^|\s)(?:OBVIOUSNESS|Regarding\s+distinguishing|'
                r'The\s+skilled\s+person|No\s+unexpected|'
                r'\bstep\s+(?:for|would|of)\b|The\s+use\s+of)',
                body, flags=re.IGNORECASE
            )[0].strip()
            # Also cap at ~280 chars so one-liner OA sentences work fully
            distinguishing.append({"numeral": m.group(1).lower(), "text": trunc[:280]})

        return {"disclosed": disclosed, "distinguishing": distinguishing}

    def _extract_cited_docs(self, office_action_text: str) -> List[str]:
        if not office_action_text:
            return []
        docs = set(re.findall(r'\bD([1-9][0-9]*)\b', office_action_text))
        return [f"D{n}" for n in sorted(docs, key=int)]

    def _extract_snippets_for_doc(self, oa_text: str, doc_id: str) -> List[str]:
        """Return sentences from the OA that explicitly reference doc_id."""
        if not oa_text or not doc_id:
            return []
        pattern = re.compile(r'\b' + re.escape(doc_id) + r'\b', re.IGNORECASE)
        snippets: List[str] = []
        for sent in re.split(r'(?<=[.!?])\s+', oa_text.strip()):
            sent = sent.strip()
            if sent and pattern.search(sent):
                snippets.append(sent)
        return snippets

    # ------------------------------------------------------------------ #
    # Step 3 — Feature Anchoring                                          #
    # ------------------------------------------------------------------ #

    def _token_overlap_score(self, text1: str, text2: str) -> float:
        """Jaccard-style overlap between domain-specific keyword tokens."""
        stop = {
            'the', 'a', 'an', 'of', 'in', 'on', 'by', 'to', 'is', 'are',
            'and', 'or', 'for', 'with', 'from', 'at', 'as', 'be', 'it',
            'that', 'this', 'which', 'each', 'all', 'not', 'using', 'its',
            # Common domain-generic terms that appear everywhere in patent text
            'method', 'claim', 'step', 'wherein', 'comprising', 'based',
            'data', 'one', 'two', 'than', 'least', 'more', 'less', 'only',
            'image', 'images', 'network', 'model', 'training', 'trained',
            'further', 'may', 'can', 'will', 'has', 'have', 'been', 'were',
            'said', 'set', 'any', 'also', 'between', 'after', 'before',
            'into', 'such', 'via', 'per', 'first', 'second', 'third',
            'output', 'input', 'value', 'layer', 'parameter', 'number',
        }
        def _tokens(t: str) -> set:
            raw = set(re.findall(r'[A-Za-z0-9ΔαΓ][A-Za-z0-9ΔαΓ]+', t.lower()))
            return raw - stop
        t1, t2 = _tokens(text1), _tokens(text2)
        if not t1 or not t2:
            return 0.0
        overlap = len(t1 & t2)
        # Require at least 2 tokens in common to avoid single-word coincidences
        if overlap < 2:
            return 0.0
        return overlap / min(len(t1), len(t2))

    def _primary_verb_stem(self, limitation: str) -> str:
        """Extract the primary action verb stem from a claim limitation."""
        # Handle "when/if CONDITION, VERB-ing ..." patterns first
        cond_m = re.search(
            r'(?:when|if)\s+\S+(?:\s+\S+){0,8},\s*([a-z](?:[a-z]+-)?[a-z]*ing)\b',
            limitation, re.IGNORECASE
        )
        if cond_m:
            stem = cond_m.group(1).lower()
            return re.sub(r'ing$', '', stem)
        # Otherwise use the first gerundive in the first 80 chars
        gerundive_m = re.search(
            r'\b([a-z](?:[a-z]+-)?[a-z]*ing)\b',
            limitation[:80], re.IGNORECASE
        )
        if gerundive_m:
            stem = gerundive_m.group(1).lower()
            return re.sub(r'ing$', '', stem)
        return ""

    def _assess_from_oa(
        self,
        limitation: str,
        disclosed_item: Optional[Dict[str, Any]],
        distinguishing: List[Dict[str, Any]],
    ) -> Tuple[Literal["Yes", "No", "Partial"], str]:
        """
        Determine assessment by:
          1. Checking token overlap with any distinguishing feature text.
          2. If significant overlap found, downgrade to Partial or No depending
             on whether the distinguishing text implies total absence vs. a
             specific aspect not being disclosed.
        """
        if disclosed_item is None:
            return "No", "Feature not addressed in the office action's D1 analysis."

        verb_stem = self._primary_verb_stem(limitation)

        # Two-group approach:
        # Group A — distinguishing features where the primary verb stem matches
        #            (high confidence: this distinguishing item describes the same action)
        # Group B — all other distinguishing features
        # Strategy: prefer Group A at threshold 0.30; fall back to Group B at 0.55.
        # This prevents shared domain symbols (ΔT/ΔT1) or shared noun phrases
        # ("dataset comprising <500 images") from masking the true distinguishing match.
        group_a_best, group_a_text = 0.0, ""
        group_b_best, group_b_text = 0.0, ""

        for dist in distinguishing:
            score = self._token_overlap_score(limitation, dist["text"])
            stem_found = (
                not (verb_stem and len(verb_stem) >= 4)
                or bool(re.search(re.escape(verb_stem), dist["text"], re.IGNORECASE))
            )
            if stem_found:
                if score > group_a_best:
                    group_a_best, group_a_text = score, dist["text"]
            else:
                if score > group_b_best:
                    group_b_best, group_b_text = score, dist["text"]

        # Pick effective score: Group A at normal threshold, Group B at elevated threshold
        if group_a_best > 0.30:
            best_score, best_text = group_a_best, group_a_text
        elif group_b_best > 0.42:
            best_score, best_text = group_b_best, group_b_text
        else:
            best_score, best_text = 0.0, ""

        if best_score > 0.30:
            # Significant overlap with a distinguishing feature
            # Detect "completely absent" language (→ "No") vs. "only partially" (→ "Partial")
            fully_absent = bool(re.search(
                r'\bD[12]\s+discloses\s+only\b|'
                r'\bonly\s+(?:a\s+single|one)\b|'
                r'\bnot\s+disclosed\b|'
                r'\bdoes\s+not\s+disclose\b|'
                r'\bno\s+\w+\s+(?:is|are)\s+disclose',
                best_text, re.IGNORECASE
            ))
            assessment: Literal["Yes", "No", "Partial"] = "No" if fully_absent else "Partial"
            doc = disclosed_item.get("doc", "D1")
            refs = disclosed_item.get("refs", [])
            ref_str = ", ".join(refs[:2]) if refs else ""
            remarks = (
                f"{doc} discloses the general concept"
                + (f" ({ref_str})" if ref_str else "")
                + f", but the specific claimed feature differs: {best_text[:220]}"
            )
            return assessment, remarks

        # No significant overlap with distinguishing features → fully disclosed
        doc = disclosed_item.get("doc", "D1")
        refs = disclosed_item.get("refs", [])
        ref_str = ", ".join(refs[:2]) if refs else ""
        remarks = (
            f"Fully disclosed in {doc}"
            + (f" ({ref_str})" if ref_str else "")
            + "."
        )
        return "Yes", remarks

    def _format_disclosure(
        self, doc_id: str, snippet: str, refs: List[str]
    ) -> str:
        """Format a clean disclosure string with paragraph references."""
        s = re.sub(r'\s+', ' ', (snippet or "")).strip()
        # Remove leading "D1 discloses" if already there
        s = re.sub(rf'(?i)^{re.escape(doc_id)}\s+discloses\s+', '', s)
        # Strip surrounding quotes
        s = s.strip('"\'')
        # Remove trailing doc ref in parentheses that will be re-added
        s = re.sub(r'\s*\(D[1-9][^)]*\)\s*$', '', s).strip().rstrip('.,')

        ref_str = ", ".join(refs[:2]) if refs else ""
        if ref_str:
            return f"{doc_id} discloses {s} ({ref_str})."
        return f"{doc_id} discloses {s}."

    # ------------------------------------------------------------------ #
    # Step 4 — LLM Assessment (optional override)                         #
    # ------------------------------------------------------------------ #

    def _parse_llm_assessment_json(
        self, raw: str
    ) -> Tuple[Literal["Yes", "No", "Partial"], str]:
        import json
        text = (raw or "").strip()
        if not text:
            raise ValueError("Empty LLM response")
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start: end + 1]
        obj = json.loads(text)
        assessment_raw = str(obj.get("assessment") or "").strip()
        reasoning = str(obj.get("reasoning") or "").strip()
        if assessment_raw not in {"Yes", "No", "Partial"}:
            raise ValueError(f"Invalid assessment: {assessment_raw!r}")
        return assessment_raw, reasoning  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    # Main execute()                                                       #
    # ------------------------------------------------------------------ #

    def execute(
        self,
        claim_text: str,
        prior_art_text: str,
        office_action_text: str = "",
        attorney_id: str = "Default",
    ) -> ClaimChartResult:
        """
        Generate Art. 56 claim chart.

        Args:
            claim_text:          Patent claim 1 text.
            prior_art_text:      General prior art fallback (used only when
                                 no OA structure is found).
            office_action_text:  Full Office Action text (drives feature
                                 anchoring and cited-doc extraction).
            attorney_id:         Attorney profile for memory injection.
        """
        # --- Attorney memory injection ---
        preferences = ""
        if (attorney_id or "").strip() and attorney_id != "Default":
            try:
                preferences = LocalMemoryManager().get_preferences(attorney_id)
            except Exception:
                preferences = ""

        base_system_prompt = (
            "You are an EPO Patent Examiner. Analyze if the following claim "
            "feature is disclosed in the Prior Art. Respond in strict JSON only: "
            '{"assessment":"Yes|No|Partial","reasoning":"..."}'
        )
        system_prompt = (
            f"{base_system_prompt}\n\n"
            "[ATTORNEY PREFERENCES — follow strictly]\n"
            f"{preferences}\n"
            "[/ATTORNEY PREFERENCES]"
        ) if preferences else base_system_prompt

        # --- Step 1: Tokenize claim ---
        features = self._tokenize_claim(claim_text)

        # --- Step 2: Parse OA structure ---
        oa_struct = self._parse_oa_structure(office_action_text)
        disclosed: List[Dict[str, Any]] = oa_struct["disclosed"]
        distinguishing: List[Dict[str, Any]] = oa_struct["distinguishing"]

        # --- Step 3: Cited documents ---
        cited_docs = self._extract_cited_docs(office_action_text)
        if not cited_docs:
            cited_docs = ["D1"]

        # --- Step 4: Build chart rows ---
        chart_data: List[Dict[str, Any]] = []

        for i, feature in enumerate(features):
            limitation = str(feature.get("limitation") or "").strip()
            feature_id = str(feature.get("feature_id") or f"1.{i + 1}")

            if i == 0:
                # Preamble — always contextually disclosed
                assessment: Literal["Yes", "No", "Partial"] = "Yes"
                disclosure = (
                    f"{cited_docs[0]} discloses the general method category "
                    "and claim structure."
                )
                remarks = (
                    "Claim preamble (method category, intended application) "
                    "is disclosed in the prior art."
                )
            else:
                # Map feature index → OA disclosed item (0-based after preamble)
                feat_idx = i - 1
                oa_item: Optional[Dict[str, Any]] = (
                    disclosed[feat_idx] if feat_idx < len(disclosed) else None
                )

                # Heuristic assessment from OA structure
                assessment, remarks = self._assess_from_oa(
                    limitation, oa_item, distinguishing
                )

                # Build disclosure string from OA item
                if oa_item:
                    disclosure = self._format_disclosure(
                        oa_item["doc"], oa_item["text"], oa_item["refs"]
                    )
                else:
                    disclosure = (
                        f"{cited_docs[0]}: Not explicitly addressed in the "
                        "office action's prior art analysis."
                    )

                # Optional LLM augmentation — enriches remarks with natural-language
                # reasoning but does NOT override the heuristic assessment.
                # The heuristic is calibrated against EPO OA structure (positional
                # mapping of disclosed/distinguishing items) and is the authoritative
                # source for Yes/No/Partial. The LLM adds readable attorney-facing
                # explanation of WHY the heuristic result holds.
                if self.llm is not None:
                    try:
                        # Tell LLM the heuristic conclusion so it explains rather
                        # than re-decides. Pass only the RELEVANT distinguishing item
                        # (feat_idx-aligned), not all items, to avoid context bleed.
                        relevant_dist = (
                            distinguishing[feat_idx]["text"]
                            if feat_idx < len(distinguishing)
                            else ""
                        )
                        user_prompt = (
                            f"Heuristic assessment: {assessment}\n\n"
                            "Claim feature:\n"
                            f"{limitation}\n\n"
                            "D1 prior art excerpt:\n"
                            f"{disclosure}\n\n"
                            + (f"Relevant distinguishing aspect (OA):\n{relevant_dist}\n\n"
                               if relevant_dist else "")
                            + "Write 1-2 sentences explaining the heuristic assessment above. "
                              'Output strict JSON: {"assessment":"' + assessment + '","reasoning":"..."}'
                        )
                        messages = [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ]
                        if hasattr(self.llm, "chat"):
                            raw = self.llm.chat(messages)  # type: ignore
                        elif hasattr(self.llm, "generate"):
                            raw = self.llm.generate(prompt=user_prompt, messages=messages)  # type: ignore
                        else:
                            raise RuntimeError("Unsupported LLM interface")
                        _, llm_remarks = self._parse_llm_assessment_json(str(raw))
                        remarks = llm_remarks  # Use LLM's richer explanation
                    except Exception:
                        pass  # Keep heuristic remarks on LLM failure

            chart_data.append({
                "feature_id": feature_id,
                "limitation": limitation,
                "d1_disclosure": disclosure,
                "assessment": assessment,
                "remarks": remarks,
            })

        return self._ok({
            "chart": chart_data,
            "cited_docs": cited_docs
        })
