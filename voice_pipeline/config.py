"""
配置管理：從 .env 讀取所有必要參數。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")


@dataclass
class VoiceConfig:
    # MiniMax (ASR + TTS)
    minimax_api_key: str
    minimax_group_id: str

    # Moonshot / Kimi (LLM)
    moonshot_api_key: str
    moonshot_base_url: str = "https://api.moonshot.cn/v1"
    moonshot_model: str = "moonshot-v1-8k"

    # Daily WebRTC
    daily_room_url: str = ""
    daily_api_key: str = ""   # 用於動態建立房間（可選）
    daily_token: str = ""     # Bot 進入房間用的 token（可選）

    # TTS 音色設定
    tts_voice_id: str = "male-qn-qingse"
    tts_sample_rate: int = 16000

    # STT 設定
    stt_language: str = "zh"
    stt_sample_rate: int = 16000

    # 系統提示詞
    system_prompt: str = (
        "你是一位專業的專利分析助理，精通中英文專利文件解讀、"
        "獨立請求項分析與 Office Action 回應策略。"
        "請以簡潔、準確的繁體中文回答問題。"
    )

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        def _require(key: str) -> str:
            val = os.getenv(key, "").strip()
            if not val:
                raise EnvironmentError(
                    f"必要環境變量 {key!r} 未設定，請檢查 .env 文件。"
                )
            return val

        return cls(
            minimax_api_key=_require("MINIMAX_API_KEY"),
            minimax_group_id=_require("MINIMAX_GROUP_ID"),
            moonshot_api_key=_require("MOONSHOT_API_KEY"),
            moonshot_base_url=os.getenv(
                "MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"
            ),
            moonshot_model=os.getenv("MOONSHOT_MODEL", "moonshot-v1-8k"),
            daily_room_url=os.getenv("DAILY_SAMPLE_ROOM_URL", ""),
            daily_api_key=os.getenv("DAILY_API_KEY", ""),
            daily_token=os.getenv("DAILY_TOKEN", ""),
            tts_voice_id=os.getenv("TTS_VOICE_ID", "male-qn-qingse"),
            tts_sample_rate=int(os.getenv("TTS_SAMPLE_RATE", "16000")),
            stt_language=os.getenv("STT_LANGUAGE", "zh"),
            stt_sample_rate=int(os.getenv("STT_SAMPLE_RATE", "16000")),
            system_prompt=os.getenv(
                "SYSTEM_PROMPT",
                "你是一位專業的專利分析助理，精通中英文專利文件解讀、"
                "獨立請求項分析與 Office Action 回應策略。"
                "請以簡潔、準確的繁體中文回答問題。",
            ),
        )
