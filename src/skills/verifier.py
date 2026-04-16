import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .base import PatentAgentSkill, SkillResult


class TranslationRow(BaseModel):
    """Single row in the translation verification table."""
    original_cn: str = Field(description="Original Chinese text segment")
    target_en: str = Field(description="Target English translation")
    back_cn: str = Field(description="Back-translated Chinese for verification")
    risk_level: Literal["Safe", "Warning", "CRITICAL"] = Field(
        default="Safe",
        description="Risk assessment level"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Specific terminology mismatch warnings"
    )
    highlighted_cn: Optional[str] = Field(
        default=None,
        description="CN text with glossary terms marked for frontend highlighting"
    )


class TranslationResult(SkillResult):
    """Typed result envelope for translation verification."""
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "rows": [],
            "markdown_table": ""
        }
    )


class TranslationVerifier(PatentAgentSkill[TranslationResult]):
    """
    Skill for Art. 123(2) Added Matter Mitigation.
    Cross-checks English translations against Chinese originals using a strict glossary.

    Design principle: Deterministic dictionary-based risk detection,
    no LLM intelligence required for critical term validation.
    """

    # Proprietary 3GPP & EPO Glossary
    # Structure: CN term -> {target: canonical EN translation, lethal_mismatch: [wrong translations]}
    GLOSSARY = {
        # Action / Function
        "包括": {"target": "comprising", "lethal_mismatch": ["consisting of", "composed of"]},
        "包含": {"target": "comprising", "lethal_mismatch": ["consisting of", "composed of"]},
        "配置为": {"target": "configured to", "lethal_mismatch": ["suitable for", "arranged to", "adapted to"]},
        "被配置为": {"target": "configured to", "lethal_mismatch": ["suitable for", "arranged to", "adapted to"]},
        "确定": {"target": "determine", "lethal_mismatch": []},
        "响应于": {"target": "in response to", "lethal_mismatch": ["based on"]},
        "执行": {"target": "performed by", "lethal_mismatch": []},
        "用于": {"target": "for", "lethal_mismatch": []},
        "发送": {"target": "transmitting", "lethal_mismatch": ["sending"]},
        "接收": {"target": "receiving", "lethal_mismatch": []},

        # Condition / Dependency
        "基于": {"target": "based on", "lethal_mismatch": ["in response to", "according to"]},
        "根据": {"target": "according to", "lethal_mismatch": ["based on"]},
        "当": {"target": "when", "lethal_mismatch": ["if"]},
        "如果": {"target": "if", "lethal_mismatch": ["when"]},
        "其中": {"target": "wherein", "lethal_mismatch": ["in which"]},

        # Scope / Quantity (HIGH RISK)
        "基本上": {"target": "substantially", "lethal_mismatch": []},
        "大约": {"target": "approximately", "lethal_mismatch": ["about"]},
        "多个": {"target": "a plurality of", "lethal_mismatch": ["a plurality of"]},
        "至少一个": {"target": "at least one", "lethal_mismatch": []},

        # EPO Formal Terms
        "权利要求": {"target": "claim", "lethal_mismatch": []},
        "说明书": {"target": "description", "lethal_mismatch": []},
        "实施例": {"target": "embodiment", "lethal_mismatch": []},
        "现有技术": {"target": "prior art", "lethal_mismatch": []},
    }

    def _highlight_cn_terms(self, text: str) -> str:
        """Mark glossary terms in CN text with **term** for frontend highlighting."""
        result = text
        for cn_term in sorted(self.GLOSSARY.keys(), key=len, reverse=True):
            pattern = re.escape(cn_term)
            result = re.sub(pattern, lambda m: f"**{m.group(0)}**", result)
        return result

    def _check_term_risk(
        self,
        cn_term: str,
        rules: Dict[str, Any],
        target_en: str,
        back_cn: str
    ) -> tuple[Literal["Safe", "Warning", "CRITICAL"], List[str]]:
        """Check a single glossary term for translation risks."""
        risk_level: Literal["Safe", "Warning", "CRITICAL"] = "Safe"
        warnings: List[str] = []

        target = rules.get("target", "")
        lethal_mismatches = rules.get("lethal_mismatch", [])

        en_lower = target_en.lower()

        # Check for lethal mismatches in target EN
        for lethal in lethal_mismatches:
            if lethal.lower() in en_lower:
                risk_level = "CRITICAL"
                warnings.append(
                    f"Expected '{target}', found lethal mismatch '{lethal}' for '{cn_term}'"
                )

        # Check if target term is missing (but only for critical terms)
        if target and not self._term_present(target, target_en):
            # "基本上 substantially" is not critical unless wrong term used
            if cn_term in ("包括", "包含", "配置为", "响应于", "基于"):
                risk_level = "CRITICAL"
                warnings.append(f"Missing target term '{target}' for '{cn_term}'")

        return risk_level, warnings

    def _term_present(self, target: str, en_text: str) -> bool:
        """Check if target term appears in English text with inflection handling."""
        if not target:
            return True

        t = target.lower().strip()
        en_lower = en_text.lower()

        # Multi-word targets: substring match
        if " " in t:
            return t in en_lower

        # Single word: check base form + inflections
        # Pattern: word boundary + term + optional (s|ed|ing) + word boundary
        if re.search(rf"(?i)\\b{re.escape(t)}(s|ed|ing)?\\b", en_text):
            return True

        # Handle drop-e forms (determine -> determining)
        if t.endswith("e"):
            stem = t[:-1]
            if stem and re.search(rf"(?i)\\b{re.escape(stem)}ing\\b", en_text):
                return True
            if stem and f"{stem}ing" in en_lower:
                return True

        # Punctuation-adjacent (e.g., "comprising:")
        for punct in [":", ",", ".", ";"]:
            if f"{t}{punct}" in en_lower:
                return True

        # Conservative fallback: substring
        return t in en_lower

    def _split_sentences(self, text: str) -> List[str]:
        """Split Chinese text into sentences."""
        if not text:
            return []
        # Split on Chinese sentence markers and semicolons
        sentences = re.split(r'[。；;！!？?]\s*', text)
        return [s.strip() for s in sentences if s.strip()]

    def execute(
        self,
        original_cn: str,
        target_en: str,
        back_cn: str
    ) -> TranslationResult:
        """
        Verify translation against glossary rules.

        Args:
            original_cn: Original Chinese text (may contain multiple sentences)
            target_en: Target English translation
            back_cn: Back-translated Chinese for verification

        Returns:
            TranslationResult with risk analysis per sentence/segment
        """
        analysis_result = []
        overall_risk: Literal["Safe", "Warning", "CRITICAL"] = "Safe"

        # Split into sentences/segments for analysis
        sentences = self._split_sentences(original_cn)
        if not sentences:
            sentences = [original_cn] if original_cn else []

        # For simplicity, analyze each sentence segment
        for sent_cn in sentences:
            row_risk: Literal["Safe", "Warning", "CRITICAL"] = "Safe"
            flagged_terms: List[str] = []

            # Check each glossary term present in this sentence
            for cn_term, rules in self.GLOSSARY.items():
                if cn_term in sent_cn:
                    term_risk, term_warnings = self._check_term_risk(
                        cn_term, rules, target_en, back_cn
                    )
                    if term_warnings:
                        flagged_terms.extend(term_warnings)
                        if term_risk == "CRITICAL":
                            row_risk = "CRITICAL"
                        elif term_risk == "Warning" and row_risk != "CRITICAL":
                            row_risk = "Warning"

            # Update overall risk
            if row_risk == "CRITICAL":
                overall_risk = "CRITICAL"
            elif row_risk == "Warning" and overall_risk != "CRITICAL":
                overall_risk = "Warning"

            # Generate highlighted version for frontend
            highlighted = self._highlight_cn_terms(sent_cn)

            analysis_result.append({
                "original_cn": sent_cn,
                "target_en": target_en,
                "back_cn": back_cn,
                "risk_level": row_risk,
                "warnings": flagged_terms,
                "highlighted_cn": highlighted
            })

        # Build markdown table for legacy compatibility
        md_lines = [
            "| Original CN | Target EN | Back CN | Risk |",
            "|-------------|-----------|---------|------|"
        ]
        for row in analysis_result:
            risk_badge = row["risk_level"]
            warnings_str = "; ".join(row["warnings"]) if row["warnings"] else ""
            md_lines.append(
                f"| {row['original_cn']} | {row['target_en']} | {row['back_cn']} | {risk_badge} |"
            )
            if warnings_str:
                md_lines.append(f"| | | | ⚠️ {warnings_str} |")

        return TranslationResult(
            status="success",
            data={
                "rows": analysis_result,
                "markdown_table": "\n".join(md_lines),
                "overall_risk": overall_risk
            },
            warnings=[w for r in analysis_result for w in r["warnings"] if w]
        )
