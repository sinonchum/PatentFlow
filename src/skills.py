from __future__ import annotations

from typing import Any, Dict


def generate_claim_chart(claim_text: str, prior_art_text: str) -> Dict[str, Any]:
    """Agent Skill: Generates a feature-by-feature comparison chart between a claim and prior art.

    Useful for overcoming EPC Article 56 (Inventive Step) objections.
    """

    # 1. Split claim into individual features
    features = claim_text.split(";")
    chart = []

    # 2. Map features to prior art (Simulated logic for demonstration)
    for i, feature in enumerate(features):
        chart.append(
            {
                "feature_id": f"1.{i+1}",
                "claim_limitation": feature.strip(),
                "d1_mapping": "...",  # AI 会填充这里
            }
        )

    return {"status": "success", "claim_chart": chart}


def classify_claim(claim_text: str) -> Dict[str, Any]:
    """Agent Skill: Analyzes claim text to identify its statutory category and structure."""

    category = "Unknown"
    if "method" in claim_text.lower():
        category = "Method"
    elif "apparatus" in claim_text.lower() or "device" in claim_text.lower():
        category = "Apparatus"

    return {"category": category, "is_independent": "according to" not in claim_text.lower()}
