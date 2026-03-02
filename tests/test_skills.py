from __future__ import annotations

from src.skills import classify_claim, generate_claim_chart


def test_classify_claim_method_independent() -> None:
    claim = "A method for wireless communication comprising: receiving DCI; wherein the DCI indicates a timing offset."
    out = classify_claim(claim)
    assert out["category"] == "Method"
    assert out["is_independent"] is True


def test_classify_claim_apparatus_dependent() -> None:
    claim = "A device according to claim 1, wherein the UE is configured to transmit HARQ-ACK."
    out = classify_claim(claim)
    assert out["category"] == "Apparatus"
    assert out["is_independent"] is False


def test_generate_claim_chart_basic() -> None:
    claim = "receiving DCI; determining an offset; transmitting HARQ feedback"
    d1 = "D1 describes receiving DCI and transmitting HARQ feedback."
    out = generate_claim_chart(claim, d1)

    assert out["status"] == "success"
    chart = out["claim_chart"]
    assert isinstance(chart, list)
    assert len(chart) == 3
    assert chart[0]["feature_id"] == "1.1"
    assert chart[1]["feature_id"] == "1.2"
    assert chart[2]["feature_id"] == "1.3"
    assert chart[0]["claim_limitation"] == "receiving DCI"
    assert chart[0]["assessment"] in {"✅ Yes", "⚠️ Partial", "❌ No (Difference)"}
    assert "disclosure" in chart[0]
    assert "attorney_remarks" in chart[0]


def test_generate_claim_chart_supports_multiple_prior_arts() -> None:
    claim = "receiving DCI; determining K0; transmitting HARQ feedback"
    oa = (
        "D1 discloses receiving DCI in paragraph [0052]. "
        "D2 discloses K0 timing offset for PDSCH scheduling. "
        "D3 discloses HARQ feedback signaling behavior."
    )
    out = generate_claim_chart(claim, "fallback prior art", office_action_text=oa)
    assert out["status"] == "success"
    assert out["cited_docs"] == ["D1", "D2", "D3"]
    chart = out["claim_chart"]
    assert len(chart) == 3
    assert all("disclosure" in row for row in chart)
    assert all("assessment" in row for row in chart)
    assert all("[N/A]" not in str(row["disclosure"]) for row in chart)


def test_generate_claim_chart_not_disclosed_is_english_only() -> None:
    claim = "dynamic timing offset field"
    oa = "D1 discloses static RRC timing configuration."
    out = generate_claim_chart(claim, "", office_action_text=oa)
    row = out["claim_chart"][0]
    assert "Not disclosed." in row["disclosure"]
    assert "未公开" not in row["disclosure"]


def test_disclosed_without_marker_can_still_match() -> None:
    claim = "base station transmits control info to schedule downlink data"
    oa_no_marker = "D1 discloses receiving DCI in control channel signaling."
    out_no_marker = generate_claim_chart(claim, "", office_action_text=oa_no_marker)
    row_no_marker = out_no_marker["claim_chart"][0]
    assert row_no_marker["disclosure"].startswith("D1 ")
    assert row_no_marker["assessment"] in {"✅ Yes", "⚠️ Partial"}

    oa_with_marker = 'D1 [0045] "The base station transmits control info to schedule downlink data."'
    out_with_marker = generate_claim_chart(claim, "", office_action_text=oa_with_marker)
    row_with_marker = out_with_marker["claim_chart"][0]
    assert "[0045]" in row_with_marker["disclosure"]
    assert row_with_marker["assessment"] in {"✅ Yes", "⚠️ Partial"}
