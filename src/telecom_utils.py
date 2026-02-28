from __future__ import annotations

import re
from typing import List


_3GPP_REF_RE = re.compile(
    r"\b3GPP\b\s+(?P<series>TS|TR)\s+(?P<spec>\d{2}\.\d{3})"
    r"(?:\s+V(?P<ver>\d{1,2}\.\d{1,2}\.\d{1,2}))?",
    flags=re.IGNORECASE,
)


def extract_3gpp_standard_refs(text: str) -> List[str]:
    """Extract normalized 3GPP standard references.

    Examples:
      - '3GPP TS 38.213 V15.2.0' -> '3GPP TS 38.213 V15.2.0'
      - '3gpp tr 38.901' -> '3GPP TR 38.901'
    """
    refs: List[str] = []
    seen = set()

    for m in _3GPP_REF_RE.finditer(text or ""):
        series = (m.group("series") or "").upper()
        spec = m.group("spec")
        ver = m.group("ver")

        if ver:
            ref = f"3GPP {series} {spec} V{ver}"
        else:
            ref = f"3GPP {series} {spec}"

        if ref not in seen:
            seen.add(ref)
            refs.append(ref)

    return refs


_POWER_RE = re.compile(
    r"(?P<val>[+\-]?\d+(?:\.\d+)?)\s*(?P<unit>dBm|dB|W|mW)\b",
    flags=re.IGNORECASE,
)

_FREQ_RE = re.compile(
    r"(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>GHz|MHz|kHz)\b",
    flags=re.IGNORECASE,
)

_NR_BAND_RE = re.compile(r"\bn\d{2,3}\b", flags=re.IGNORECASE)
_LTE_BAND_RE = re.compile(r"\bBand\s*\d{1,3}\b", flags=re.IGNORECASE)


def redact_telecom_fingerprints(text: str) -> str:
    """Redact telecom-specific numeric fingerprints before persistence.

    - Power values (e.g. '23 dBm', '-3 dB', '0.5 W') -> '<POWER_VALUE>'
    - Frequency values (e.g. '3.5 GHz', '3500 MHz') -> '<FREQ_VALUE>'
    - Band identifiers (e.g. 'n78', 'Band 3') -> '<BAND>'

    This is intentionally simple and conservative.
    """

    if not text:
        return ""

    text = _POWER_RE.sub("<POWER_VALUE>", text)
    text = _FREQ_RE.sub("<FREQ_VALUE>", text)
    text = _NR_BAND_RE.sub("<BAND>", text)
    text = _LTE_BAND_RE.sub("<BAND>", text)
    return text
