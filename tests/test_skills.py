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
    assert chart[0]["d1_mapping"] == "..."
