from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


def _split_paragraphs(text: str) -> List[str]:
    text = (text or "").replace("\r", "\n").strip()
    if not text:
        return []
    return [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]


def _split_sentences_cn(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    # Split on Chinese/English sentence punctuation.
    parts = re.split(r"(?<=[。！？!?；;])\s*", text)
    out = [p.strip() for p in parts if p and p.strip()]
    return out


def _escape_md_cell(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("|", "\\|")
    s = s.replace("\n", "<br>")
    return s


def _highlight_cn_terms(text: str, terms: List[str]) -> str:
    s = text or ""
    # Longest-first to avoid partial overlaps.
    for t in sorted(set(terms), key=len, reverse=True):
        if not t:
            continue
        s = s.replace(t, f"**{t}**")
    return s


def _highlight_en_terms(text: str, terms: List[str]) -> str:
    s = text or ""
    for t in sorted(set(terms), key=len, reverse=True):
        if not t:
            continue
        # Word-boundary highlighting for EN terms.
        s = re.sub(rf"(?i)\\b{re.escape(t)}\\b", f"**{t}**", s)
    return s


def _to_markdown_table(rows: List[Tuple[str, str]]) -> str:
    header = "| 中文 | English |\n|---|---|"
    body = "\n".join([f"| {_escape_md_cell(zh)} | {_escape_md_cell(en)} |" for zh, en in rows])
    return (header + "\n" + body).strip() + "\n"


def _to_markdown_table_3col(rows: List[Tuple[str, str, str]]) -> str:
    header = "| 原始中文 (Original CN) | 专利英文 (Target EN) | 反向翻译中文 (Reverse-Translation CN) |\n|---|---|---|"
    body = "\n".join(
        [
            f"| {_escape_md_cell(cn)} | {_escape_md_cell(en)} | {_escape_md_cell(back_cn)} |"
            for cn, en, back_cn in rows
        ]
    )
    return (header + "\n" + body).strip() + "\n"


@dataclass
class PatentTranslator:
    SYSTEM_PROMPT: str = (
        "你是一位精通中国专利法和欧洲专利公约(EPC)的资深双语专利律师。"
        "请将以下中文段落翻译为符合 EPO 标准的法律英语。"
        "必须严格使用专利术语：如“包括/包含”译为“comprising”，“其中”译为“wherein”，“被配置为”译为“configured to”。"
        "请按原句切分，输出中英文对照的 Markdown 表格。"
    )

    # Deterministic local vocabulary controls (attorney-facing QA).
    # Used for term highlighting and mismatch alerts.
    VOCAB: Dict[str, Dict[str, Dict[str, object]]] = field(default_factory=lambda: {
        "functional_limitations": {
            "配置为": {"target": "configured to", "alert_if": ["suitable for", "arranged to"]},
            "用于": {"target": "for", "alert_if": ["suitable for"]},
            "由...执行": {"target": "performed by", "alert_if": ["done by", "carried out by"]},
            "指示": {"target": "indicate", "alert_if": ["show", "point out"]},
            "确定": {"target": "determine", "alert_if": ["decide"]},
        },
        "scope_boundaries": {
            "包括": {"target": "comprising", "alert_if": ["consisting of", "composed of"], "risk_level": "CRITICAL"},
            "包含": {"target": "comprising", "alert_if": ["consisting of", "composed of"], "risk_level": "CRITICAL"},
            "由...组成": {"target": "consisting of", "alert_if": ["comprising", "including"], "risk_level": "CRITICAL"},
            "至少一个": {"target": "at least one of", "alert_if": []},
            "至少一项": {"target": "at least one of", "alert_if": []},
            "分别": {"target": "respectively", "alert_if": []},
        },
        "logical_triggers": {
            "基于": {"target": "based on", "alert_if": ["according to"]},
            "根据": {"target": "according to", "alert_if": ["based on"]},
            "响应于": {"target": "in response to", "alert_if": ["after", "when"]},
            "对应于": {"target": "corresponding to", "alert_if": []},
        },
        "epo_formal": {
            "其特征在于": {"target": "characterized in that", "alert_if": ["characterized by"]},
            "基本上": {"target": "substantially", "alert_if": [], "risk_level": "WARNING"},
            "其中": {"target": "wherein", "alert_if": ["in which"]},
            "所述": {"target": "the", "alert_if": ["said"]},
        },
    })

    def _cn_patterns(self) -> List[Tuple[str, str, List[str], str]]:
        """Return (cn_regex, target_en, alert_if_en_terms, risk_level)."""
        out: List[Tuple[str, str, List[str], str]] = []
        for group in self.VOCAB.values():
            for cn_key, spec in group.items():
                target = str(spec.get("target", ""))
                alert_if = [str(x) for x in (spec.get("alert_if") or []) if isinstance(x, str)]
                risk_level = str(spec.get("risk_level", ""))

                if cn_key == "由...执行":
                    out.append((r"由.+?执行", target, alert_if, risk_level))
                elif cn_key == "由...组成":
                    out.append((r"由.+?组成", target, alert_if, risk_level))
                else:
                    out.append((re.escape(cn_key), target, alert_if, risk_level))

        # Longest-first patterns reduce partial overlaps.
        out.sort(key=lambda x: len(x[0]), reverse=True)
        return out

    def _en_terms(self) -> List[str]:
        terms: List[str] = []
        for group in self.VOCAB.values():
            for spec in group.values():
                t = spec.get("target")
                if isinstance(t, str) and t:
                    terms.append(t)
                for bad in spec.get("alert_if") or []:
                    if isinstance(bad, str) and bad:
                        terms.append(bad)
        return sorted(set(terms), key=len, reverse=True)

    def _highlight_cn_vocab(self, text: str) -> str:
        s = text or ""
        for pat, _target, _alert_if, _risk in self._cn_patterns():
            s = re.sub(pat, lambda m: f"**{m.group(0)}**", s)
        return s

    def _vocab_alerts(self, *, original_cn: str, target_en: str) -> List[str]:
        alerts: List[str] = []
        o = original_cn or ""
        en = (target_en or "")
        en_l = en.lower()

        def _present(term: str) -> bool:
            """Check whether a target term appears in EN output.

            For single-token verbs, allow common inflections (s/ed/ing).
            """
            t = (term or "").strip().lower()
            if not t:
                return True

            # Multi-word targets: substring match is fine.
            if " " in t:
                if t in en_l:
                    return True
                # Special-case: performed by ~ executed by are both acceptable.
                if t == "performed by" and "executed by" in en_l:
                    return True
                return False

            # Single word: word-boundary + optional inflection suffix.
            if re.search(rf"(?i)\\b{re.escape(t)}(s|ed|ing)?\\b", en):
                return True
            # Handle drop-e forms for verbs ending with 'e' (determine->determining, indicate->indicating).
            if t.endswith("e"):
                stem = t[:-1]
                if stem and re.search(rf"(?i)\\b{re.escape(stem)}ing\\b", en):
                    return True
                # Also allow substring match for fused outputs.
                if stem and f"{stem}ing" in en_l:
                    return True
            # Fallback for punctuation-adjacent tokens (e.g., "comprising:") or fused outputs.
            if f"{t}:" in en_l or f"{t}," in en_l or f"{t}." in en_l or f"{t};" in en_l:
                return True
            # Very conservative fallback: substring match (handles determine vs determining).
            return t in en_l

        for pat, target, alert_if, risk_level in self._cn_patterns():
            if not re.search(pat, o):
                continue

            if target and not _present(target):
                tag = f"MISSING_TARGET:{target}"
                if risk_level:
                    tag = f"{risk_level}:{tag}"
                alerts.append(tag)

            for bad in alert_if:
                if bad.lower() in en_l:
                    tag = f"ALERT_IF:{bad}"
                    if risk_level:
                        tag = f"{risk_level}:{tag}"
                    alerts.append(tag)

        return alerts

    def _build_alignment_rows(self, text: str, is_confidential: bool = True) -> List[Dict[str, object]]:
        paragraphs = _split_paragraphs(text)
        if not paragraphs:
            return []

        # Engine routing (design intent):
        # - is_confidential=True: 调用本地大模型（如 Ollama）
        # - is_confidential=False: 调用在线 API（如 OpenAI/Claude）
        # NOTE: 由于目前没有真实 LLM，这里返回 Mock 的高质量翻译结果。

        rows: List[Dict[str, object]] = []
        en_terms = self._en_terms()
        for p in paragraphs:
            for sent in _split_sentences_cn(p):
                en = self._mock_translate_sentence(sent)
                back_cn = self._mock_back_translate_sentence(en)
                # Apply local glossary highlighting first.
                sent_hl = self._highlight_cn_vocab(sent)
                en_hl = _highlight_en_terms(en, en_terms)
                back_hl = self._highlight_cn_vocab(back_cn)

                # Then add mismatch annotation (kept for QA), without bolding whole sentences.
                cn_marked, back_marked = self._mark_verb_mismatch(sent_hl, back_hl)
                vocab_alerts = self._vocab_alerts(original_cn=sent, target_en=en)
                has_risk = self._has_translation_risk(original_cn=sent, target_en=en, back_cn=back_cn) or bool(vocab_alerts)
                if vocab_alerts:
                    back_marked = f"{back_marked} (VOCAB_ALERT: {', '.join(vocab_alerts)})"
                rows.append(
                    {
                        "original_cn": cn_marked,
                        "target_en": en_hl,
                        "back_cn": back_marked,
                        "has_risk": bool(has_risk or "VERB_MISMATCH" in back_marked),
                    }
                )

        return rows

    def translate_and_align_rows(self, text: str, is_confidential: bool = True) -> List[Dict[str, object]]:
        return self._build_alignment_rows(text=text, is_confidential=is_confidential)

    def rows_to_markdown(self, rows: List[Dict[str, object]]) -> str:
        triples: List[Tuple[str, str, str]] = [
            (
                str(row.get("original_cn", "")),
                str(row.get("target_en", "")),
                str(row.get("back_cn", "")),
            )
            for row in rows
        ]
        return _to_markdown_table_3col(triples)

    def translate_and_align(self, text: str, is_confidential: bool = True) -> str:
        rows = self._build_alignment_rows(text=text, is_confidential=is_confidential)
        return self.rows_to_markdown(rows)

    def _mock_translate_sentence(self, sentence_cn: str) -> str:
        s = (sentence_cn or "").strip()
        if not s:
            return ""

        # Term mapping tuned for CN->EPO patent/telecom drafting.
        mapping = [
            (r"一种无线通信方法", "A method for wireless communication"),
            (r"一种", "a"),
            (r"包括|包含", "comprising"),
            (r"其中", "wherein"),
            (r"被配置为", "configured to"),
            (r"所述", "the"),
            (r"终端设备", "a terminal device"),
            (r"网络设备", "a network device"),
            (r"发送", "transmitting"),
            (r"确定", "determining"),
            (r"以及基于该", "and based on the"),
            (r"接收", "receiving"),
            (r"下行控制信息\s*[（(]?\s*DCI\s*[）)]?", "Downlink Control Information (DCI)"),
            (r"下行控制信息\s*DCI", "Downlink Control Information (DCI)"),
            (r"混合自动重传请求\s*[（(]?\s*HARQ\s*[）)]?", "Hybrid Automatic Repeat reQuest (HARQ)"),
            (r"物理下行共享信道\s*PDSCH", "Physical Downlink Shared Channel (PDSCH)"),
            (r"定时偏移量", "a timing offset"),
            (r"方法", "method"),
            (r"格式", "format"),
            (r"权利要求\s*([0-9]+)", r"claim \1"),
        ]

        en = s
        for pat, repl in mapping:
            en = re.sub(pat, repl, en)

        # Normalize common CN punctuation into EN punctuation.
        en = en.replace("：", ": ").replace("；", "; ").replace("，", ", ")
        # Ensure token boundaries (common fused tokens).
        en = re.sub(r"([a-z])([A-Z])", r"\1 \2", en)
        en = re.sub(r"(?i)\b(comprising|wherein|configured|transmitting|receiving|determining)(?=a\b|the\b|downlink\b|physical\b|timing\b)", r"\1 ", en)
        # Fix common fused articles/phrases introduced by regex replacements.
        en = re.sub(r"(?i)thea", "the a", en)
        en = re.sub(r"(?i)offsetreceiving", "offset receiving", en)
        en = re.sub(r"(?i)\boffset(?=receiving\b)", "offset ", en)
        en = re.sub(r"(?i)\boffset(?=K[0-9]+\b)", "offset ", en)
        # Remove any residual Chinese characters from Target EN column.
        en = re.sub(r"[\u4e00-\u9fff]+", " ", en)

        # Normalize whitespace and produce EPO-style prose.
        en = re.sub(r"\s+", " ", en).strip()
        en = en.strip("。；;")

        # A few tailored sentence patterns to improve realism.
        if "claim" in en.lower() and "comprising" in en.lower():
            return (
                f"{en}."
                if en.lower().startswith("claim")
                else f"Claim 1 relates to a method {en}."
            )

        if "wherein" in en.lower():
            return f"{en}."

        # Default
        return f"{en}."

    def _has_translation_risk(self, *, original_cn: str, target_en: str, back_cn: str) -> bool:
        """Heuristic risk scoring for the mock verifier.

        We keep it intentionally conservative: only flag a few attorney-critical patterns.
        """
        o = (original_cn or "")
        en = (target_en or "").lower()
        b = (back_cn or "")

        # 1) Open-ended vs closed-ended transition (high risk)
        if re.search(r"包括|包含", o) and "consisting of" in en:
            return True

        # 2) Missing comprising when CN clearly indicates open-ended
        if re.search(r"包括|包含", o) and "comprising" not in en:
            return True

        # 3) Back-translation lost key verbs (basic guardrail)
        if re.search(r"包括|包含", o) and not re.search(r"包括|包含", b):
            return True

        return False

    def _mock_back_translate_sentence(self, sentence_en: str) -> str:
        # Deterministic back-translation (mock). This is intended only for alignment QA.
        s = (sentence_en or "").strip()
        if not s:
            return ""

        # Reverse of key patent terms.
        mapping = [
            (r"\bcomprising\b", "包括"),
            (r"\bwherein\b", "其中"),
            (r"\bconfigured\s+to\b", "被配置为"),
            (r"A\s+method\s+for\s+wireless\s+communication", "一种无线通信方法"),
            (r"\bperformed\s+by\s+a\s+terminal\s+device\b", "由终端设备执行"),
            (r"\btransmitting\b", "发送"),
            (r"\breceiving\b", "接收"),
            (r"\bdetermining\b", "确定"),
            (r"\band\s+based\s+on\s+the\b", "并基于"),
            (r"\bdynamic\s+timing\s+offset\s+field\b", "动态定时偏移字段"),
            (r"Downlink\s+Control\s+Information\s*\(DCI\)", "下行控制信息（DCI）"),
            (r"Hybrid\s+Automatic\s+Repeat\s+reQuest\s*\(HARQ\)", "混合自动重传请求（HARQ）"),
            (r"Physical\s+Downlink\s+Shared\s+Channel\s*\(PDSCH\)", "物理下行共享信道（PDSCH）"),
            (r"\bcontrol\s+info\b", "控制信息"),
            (r"\bscheduling\b", "调度"),
            (r"\ba\s+timing\s+offset\b", "定时偏移量"),
            (r"\ba\s+terminal\s+device\b", "终端设备"),
            (r"\ba\s+network\s+device\b", "网络设备"),
            (r"\bclaim\s+1\b", "权利要求 1"),
            (r"\bmethod\b", "方法"),
            (r"\bformat\b", "格式"),
        ]

        # Normalize punctuation/spacing to make reverse-mapping robust even when EN output
        # has token concatenation (e.g., transmittingDownlink...).
        cn = s.replace("：", ": ").replace("；", "; ").replace("，", ", ")
        # Fix common fused tokens from upstream EN generation (e.g., determininga).
        cn = re.sub(
            r"(?i)\b(comprising|wherein|configured|transmitting|receiving|determining)(?=a\b|the\b|downlink\b|physical\b|timing\b|dynamic\b)",
            r"\1 ",
            cn,
        )
        cn = re.sub(r"([a-z])([A-Z])", r"\1 \2", cn)
        cn = re.sub(r"\s+", " ", cn).strip()

        for pat, repl in mapping:
            cn = re.sub(pat, repl, cn, flags=re.IGNORECASE)

        # Keep token boundary readability in mixed-language terms (e.g., offsetK0 -> offset K0).
        cn = re.sub(r"(?i)\boffset(?=K[0-9]+\b)", "offset ", cn)
        # Chinese patent drafting style: keep K-index adjacent to "定时偏移量".
        cn = re.sub(r"定时偏移量\s+K([0-9]+)", r"定时偏移量K\1", cn)

        # Remove spaces between Chinese characters only, preserving spaces between English words
        # Use regex: remove space when it's between two Chinese characters ([\u4e00-\u9fff])
        cn = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", cn)
        # Also remove spaces around Chinese punctuation
        cn = re.sub(r"\s*([。！？?；;,，:：])\s*", r"\1", cn)
        cn = cn.strip().strip(".")
        if not cn.endswith("。"):
            cn = cn + "。"
        return cn

    def _mark_verb_mismatch(self, original_cn: str, back_cn: str) -> Tuple[str, str]:
        # Simulated term highlighting for attorney QA.
        verbs = ["包括", "包含", "连接", "指示", "配置为", "被配置为"]

        def found_verbs(s: str) -> List[str]:
            out: List[str] = []
            for v in verbs:
                if v in (s or ""):
                    out.append(v)
            return out

        o = (original_cn or "").strip()
        b = (back_cn or "").strip()
        ov = set(found_verbs(o))
        bv = set(found_verbs(b))
        if ov == bv:
            return o, b

        # Mark both sides when mismatch (targeted highlighting, not whole sentence).
        mismatch_note = "VERB_MISMATCH"
        o_marked = o
        for v in sorted(ov):
            o_marked = o_marked.replace(v, f"**{v}**")

        b_marked = b
        for v in sorted(bv):
            b_marked = b_marked.replace(v, f"**{v}**")
        b_marked = f"{b_marked} ({mismatch_note}: {', '.join(sorted(ov or {'∅'}))} -> {', '.join(sorted(bv or {'∅'}))})"
        return o_marked, b_marked
