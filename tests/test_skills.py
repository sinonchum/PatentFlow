from __future__ import annotations

from src.skills import ClaimChartGenerator, TranslationVerifier


# ---------------------------------------------------------------------------
# ClaimChartGenerator — deterministic tokenization (no LLM needed)
# ---------------------------------------------------------------------------

class TestClaimTokenizer:
    """Test the deterministic claim splitting logic."""

    def _tokenize(self, claim_text: str):
        gen = ClaimChartGenerator()
        return gen._tokenize_claim(claim_text)

    def test_comprising_split(self) -> None:
        claim = (
            "A method for wireless communication, comprising: "
            "receiving DCI; determining an offset; transmitting HARQ feedback."
        )
        features = self._tokenize(claim)
        assert len(features) == 4
        assert features[0]["feature_id"] == "1.1"
        assert "comprising" in features[0]["limitation"].lower()
        assert features[1]["feature_id"] == "1.2"
        assert "receiving DCI" in features[1]["limitation"]

    def test_no_comprising_fallback(self) -> None:
        claim = "receiving DCI; determining an offset; transmitting HARQ feedback"
        features = self._tokenize(claim)
        assert len(features) == 3
        assert features[0]["feature_id"] == "1.1"
        assert features[0]["limitation"] == "receiving DCI"

    def test_empty_claim(self) -> None:
        assert self._tokenize("") == []
        assert self._tokenize("   ") == []

    def test_single_feature(self) -> None:
        claim = "A method for wireless communication, comprising: receiving DCI."
        features = self._tokenize(claim)
        assert len(features) == 2
        assert "comprising" in features[0]["limitation"].lower()


# ---------------------------------------------------------------------------
# ClaimChartGenerator — cited document extraction
# ---------------------------------------------------------------------------

class TestCitedDocExtraction:
    def _extract(self, oa_text: str):
        gen = ClaimChartGenerator()
        return gen._extract_cited_docs(oa_text)

    def test_basic_d1_d2(self) -> None:
        oa = "Document D1 discloses... Document D2 describes..."
        assert self._extract(oa) == ["D1", "D2"]

    def test_multiple_docs(self) -> None:
        oa = "D1 discloses receiving DCI. D2 discloses K0 timing. D3 discloses HARQ."
        assert self._extract(oa) == ["D1", "D2", "D3"]

    def test_no_docs(self) -> None:
        assert self._extract("") == []
        assert self._extract("no documents here") == []


# ---------------------------------------------------------------------------
# ClaimChartGenerator — snippet extraction
# ---------------------------------------------------------------------------

class TestSnippetExtraction:
    def _extract_snippets(self, oa_text: str, doc_id: str):
        gen = ClaimChartGenerator()
        return gen._extract_snippets_for_doc(oa_text, doc_id)

    def test_basic_snippet(self) -> None:
        oa = "D1 discloses receiving DCI in paragraph [0052]. D2 discloses K0."
        snippets = self._extract_snippets(oa, "D1")
        assert len(snippets) > 0
        assert any("DCI" in s for s in snippets)

    def test_empty_oa(self) -> None:
        assert self._extract_snippets("", "D1") == []


# ---------------------------------------------------------------------------
# ClaimChartGenerator — full execute (mock LLM, deterministic fallback)
# ---------------------------------------------------------------------------

class TestClaimChartExecute:
    def test_basic_chart(self) -> None:
        gen = ClaimChartGenerator()
        result = gen.execute(
            claim_text="receiving DCI; determining an offset; transmitting HARQ feedback",
            prior_art_text="D1 describes receiving DCI and transmitting HARQ feedback.",
            office_action_text="D1 discloses receiving DCI in paragraph [0052].",
        )
        assert result.status in {"success", "partial"}
        chart = result.data.get("chart", [])
        assert len(chart) == 3
        assert chart[0]["feature_id"] == "1.1"
        assert chart[0]["assessment"] in {"Yes", "No", "Partial"}

    def test_multiple_prior_arts(self) -> None:
        gen = ClaimChartGenerator()
        oa = (
            "D1 discloses receiving DCI in paragraph [0052]. "
            "D2 discloses K0 timing offset for PDSCH scheduling. "
            "D3 discloses HARQ feedback signaling behavior."
        )
        result = gen.execute(
            claim_text="receiving DCI; determining K0; transmitting HARQ feedback",
            prior_art_text="fallback prior art",
            office_action_text=oa,
        )
        assert result.status in {"success", "partial"}
        assert set(result.data.get("cited_docs", [])) >= {"D1", "D2", "D3"}
        chart = result.data.get("chart", [])
        assert len(chart) == 3
        for row in chart:
            assert "d1_disclosure" in row or "d1_disclosure" in row


# ---------------------------------------------------------------------------
# TranslationVerifier — glossary-based risk detection
# ---------------------------------------------------------------------------

class TestTranslationVerifier:
    def test_safe_translation(self) -> None:
        verifier = TranslationVerifier()
        result = verifier.execute(
            original_cn="一种无线通信方法，包括发送下行控制信息",
            target_en="A method for wireless communication, comprising transmitting Downlink Control Information",
            back_cn="一种无线通信方法，包括发送下行控制信息",
        )
        assert result.status == "success"
        assert result.data["overall_risk"] in {"Safe", "Warning"}

    def test_lethal_mismatch(self) -> None:
        """'包括' should never map to 'consisting of' — that's a lethal mismatch."""
        verifier = TranslationVerifier()
        result = verifier.execute(
            original_cn="一种方法，包括发送DCI",
            target_en="A method, consisting of transmitting DCI",
            back_cn="一种方法，组成发送DCI",
        )
        assert result.data["overall_risk"] == "CRITICAL"

    def test_missing_comprising(self) -> None:
        """Missing 'comprising' when CN has '包括' is critical."""
        verifier = TranslationVerifier()
        result = verifier.execute(
            original_cn="一种方法，包括发送DCI",
            target_en="A method, including transmitting DCI",
            back_cn="一种方法，包括发送DCI",
        )
        # 'including' is not 'comprising' — should flag
        rows = result.data.get("rows", [])
        assert len(rows) > 0
        # At least one row should have warnings
        has_warning = any(r.get("warnings") for r in rows)
        has_critical = result.data["overall_risk"] == "CRITICAL"
        assert has_warning or has_critical

    def test_empty_input(self) -> None:
        verifier = TranslationVerifier()
        result = verifier.execute(original_cn="", target_en="", back_cn="")
        assert result.status == "success"

    def test_highlight_cn_terms(self) -> None:
        verifier = TranslationVerifier()
        highlighted = verifier._highlight_cn_terms("一种方法，包括发送DCI，其中所述终端被配置为接收")
        assert "**包括**" in highlighted
        assert "**其中**" in highlighted
        assert "**配置为**" in highlighted or "**被配置为**" in highlighted
