"""
Shared 3GPP & EPO terminology glossary for Art. 123(2) compliance.

Structure: CN term -> {target: canonical EN translation, lethal_mismatch: [wrong translations]}
"""

from typing import Dict, Any

PATENT_GLOSSARY: Dict[str, Dict[str, Any]] = {
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
