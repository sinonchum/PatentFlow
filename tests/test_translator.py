from __future__ import annotations

import re

from src.translator import PatentTranslator


def test_target_en_is_english_terms() -> None:
    tr = PatentTranslator()
    rows = tr.translate_and_align_rows("一种方法，包括：终端设备接收下行控制信息（DCI）。")
    assert rows
    target_en = str(rows[0].get("target_en", "")).lower()
    assert "comprising" in target_en
    assert "downlink control information (dci)" in target_en
    assert not re.search(r"[\u4e00-\u9fff]", target_en)


def test_back_translation_keeps_offset_k0_spacing() -> None:
    tr = PatentTranslator()
    back_cn = tr._mock_back_translate_sentence("The method uses a timing offsetK0.")
    assert "K0" in back_cn
    assert ("offset K0" in back_cn) or ("定时偏移量K0" in back_cn)


def test_back_translation_splits_fused_determininga() -> None:
    tr = PatentTranslator()
    back_cn = tr._mock_back_translate_sentence("determininga timing offset K0.")
    assert "确定" in back_cn
    assert "定时偏移量K0" in back_cn


def main() -> None:
    text = (
        "权利要求 1. 一种用于无线通信系统的方法，包括：终端设备接收来自网络设备的下行控制信息（DCI）；"
        "其中，所述DCI指示用于混合自动重传请求（HARQ）反馈的定时偏移量。"
    )

    tr = PatentTranslator()

    print(tr.translate_and_align(text, is_confidential=True))


if __name__ == "__main__":
    main()
