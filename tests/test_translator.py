from __future__ import annotations

from src.translator import PatentTranslator


def main() -> None:
    text = (
        "权利要求 1. 一种用于无线通信系统的方法，包括：终端设备接收来自网络设备的下行控制信息（DCI）；"
        "其中，所述DCI指示用于混合自动重传请求（HARQ）反馈的定时偏移量。"
    )

    tr = PatentTranslator()

    print(tr.translate_and_align(text, is_confidential=True))


if __name__ == "__main__":
    main()
