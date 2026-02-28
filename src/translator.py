from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


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


def _to_markdown_table(rows: List[Tuple[str, str]]) -> str:
    header = "| 中文 | English |\n|---|---|"
    body = "\n".join([f"| {_escape_md_cell(zh)} | {_escape_md_cell(en)} |" for zh, en in rows])
    return (header + "\n" + body).strip() + "\n"


def _to_markdown_table_3col(rows: List[Tuple[str, str, str]]) -> str:
    header = "| 原始中文 (Original CN) | 专利英文 (Target EN) | 反向校验中文 (Back-trans CN) |\n|---|---|---|"
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

    def translate_and_align(self, text: str, is_confidential: bool = True) -> str:
        paragraphs = _split_paragraphs(text)
        if not paragraphs:
            return _to_markdown_table_3col([])

        # Engine routing (design intent):
        # - is_confidential=True: 调用本地大模型（如 Ollama）
        # - is_confidential=False: 调用在线 API（如 OpenAI/Claude）
        # NOTE: 由于目前没有真实 LLM，这里返回 Mock 的高质量翻译结果。

        rows: List[Tuple[str, str, str]] = []
        for p in paragraphs:
            for sent in _split_sentences_cn(p):
                en = self._mock_translate_sentence(sent)
                back_cn = self._mock_back_translate_sentence(en)
                cn_marked, back_marked = self._mark_verb_mismatch(sent, back_cn)
                rows.append((cn_marked, en, back_marked))

        return _to_markdown_table_3col(rows)

    def _mock_translate_sentence(self, sentence_cn: str) -> str:
        s = (sentence_cn or "").strip()
        if not s:
            return ""

        # Term mapping tuned for CN->EPO patent/telecom drafting.
        mapping = [
            (r"\b包括\b|\b包含\b", "comprising"),
            (r"\b其中\b", "wherein"),
            (r"被配置为", "configured to"),
            (r"终端设备", "a terminal device"),
            (r"网络设备", "a network device"),
            (r"下行控制信息\s*（?DCI）?", "Downlink Control Information (DCI)"),
            (r"混合自动重传请求\s*（?HARQ）?", "Hybrid Automatic Repeat reQuest (HARQ)"),
            (r"定时偏移量", "a timing offset"),
            (r"方法", "method"),
            (r"权利要求\s*([0-9]+)", r"claim \1"),
        ]

        en = s
        for pat, repl in mapping:
            en = re.sub(pat, repl, en)

        # Normalize punctuation and produce EPO-style, legally cautious prose.
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
            (r"Downlink\s+Control\s+Information\s*\(DCI\)", "下行控制信息（DCI）"),
            (r"Hybrid\s+Automatic\s+Repeat\s+reQuest\s*\(HARQ\)", "混合自动重传请求（HARQ）"),
            (r"\ba\s+timing\s+offset\b", "定时偏移量"),
            (r"\ba\s+terminal\s+device\b", "终端设备"),
            (r"\ba\s+network\s+device\b", "网络设备"),
            (r"\bclaim\s+1\b", "权利要求 1"),
            (r"\bmethod\b", "方法"),
        ]

        cn = s
        for pat, repl in mapping:
            cn = re.sub(pat, repl, cn, flags=re.IGNORECASE)

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

        # Mark both sides when mismatch.
        mismatch_note = "VERB_MISMATCH"
        o_marked = f"**{o}**"
        b_marked = f"**{b}** ({mismatch_note}: {', '.join(sorted(ov or {'∅'}))} -> {', '.join(sorted(bv or {'∅'}))})"
        return o_marked, b_marked
