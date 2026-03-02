import pytest

from src.skills import TranslationVerifier


def test_including_flags_consisting_of_as_critical() -> None:
    verifier = TranslationVerifier()

    result = verifier.execute(
        original_cn="一种方法，包括：发送下行控制信息。",
        target_en="A method consisting of transmitting downlink control information.",
        back_cn="一种方法，由发送下行控制信息组成。",
    )

    assert result.status == "success"
    assert result.data.get("overall_risk") == "CRITICAL"

    rows = result.data.get("rows")
    assert isinstance(rows, list)
    assert rows
    assert rows[0]["risk_level"] == "CRITICAL"

    warnings = rows[0].get("warnings")
    assert isinstance(warnings, list)
    assert any("lethal mismatch" in w.lower() for w in warnings)
