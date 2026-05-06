"""
配置管理：從 .env 讀取所有必要參數。

TTS_PROVIDER 可選值：
  elevenlabs  (預設) — 使用 ElevenLabs WebSocket TTS，支援多語言
  minimax             — 使用 MiniMax T2A V2 TTS（需填 MINIMAX_API_KEY / GROUP_ID）
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")


@dataclass
class VoiceConfig:
    # ---- TTS 提供商 ----
    tts_provider: str = "elevenlabs"   # "elevenlabs" | "minimax"

    # ---- ElevenLabs TTS ----
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_turbo_v2_5"

    # ---- MiniMax TTS（TTS_PROVIDER=minimax 時使用）----
    minimax_api_key: str = ""
    minimax_group_id: str = ""
    minimax_voice_id: str = "male-qn-qingse"
    minimax_tts_sample_rate: int = 16000

    # ---- Moonshot / Kimi (LLM) ----
    moonshot_api_key: str = ""
    moonshot_base_url: str = "https://api.moonshot.cn/v1"
    moonshot_model: str = "moonshot-v1-8k"

    # ---- Daily WebRTC ----
    daily_room_url: str = ""
    daily_api_key: str = ""
    daily_token: str = ""

    # ---- STT 設定 ----
    stt_language: str = "zh"
    stt_sample_rate: int = 16000

    # ---- 系統提示詞 ----
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

        def _get(key: str, default: str = "") -> str:
            return os.getenv(key, default).strip()

        tts_provider = _get("TTS_PROVIDER", "elevenlabs").lower()

        # ---- 按 provider 決定哪些 key 是必填 ----
        if tts_provider == "elevenlabs":
            elevenlabs_api_key = _require("ELEVENLABS_API_KEY")
            elevenlabs_voice_id = _require("ELEVENLABS_VOICE_ID")
            minimax_api_key = _get("MINIMAX_API_KEY")
            minimax_group_id = _get("MINIMAX_GROUP_ID")
        elif tts_provider == "minimax":
            elevenlabs_api_key = _get("ELEVENLABS_API_KEY")
            elevenlabs_voice_id = _get("ELEVENLABS_VOICE_ID")
            minimax_api_key = _require("MINIMAX_API_KEY")
            minimax_group_id = _require("MINIMAX_GROUP_ID")
        else:
            raise EnvironmentError(
                f"不支援的 TTS_PROVIDER={tts_provider!r}，請設為 'elevenlabs' 或 'minimax'。"
            )

        return cls(
            tts_provider=tts_provider,
            # ElevenLabs
            elevenlabs_api_key=elevenlabs_api_key,
            elevenlabs_voice_id=elevenlabs_voice_id,
            elevenlabs_model=_get("ELEVENLABS_MODEL", "eleven_turbo_v2_5"),
            # MiniMax
            minimax_api_key=minimax_api_key,
            minimax_group_id=minimax_group_id,
            minimax_voice_id=_get("MINIMAX_VOICE_ID", "male-qn-qingse"),
            minimax_tts_sample_rate=int(_get("MINIMAX_TTS_SAMPLE_RATE", "16000")),
            # LLM
            moonshot_api_key=_require("MOONSHOT_API_KEY"),
            moonshot_base_url=_get("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"),
            moonshot_model=_get("MOONSHOT_MODEL", "moonshot-v1-8k"),
            # Daily
            daily_room_url=_get("DAILY_SAMPLE_ROOM_URL"),
            daily_api_key=_get("DAILY_API_KEY"),
            daily_token=_get("DAILY_TOKEN"),
            # STT
            stt_language=_get("STT_LANGUAGE", "zh"),
            stt_sample_rate=int(_get("STT_SAMPLE_RATE", "16000")),
            # System
            system_prompt=_get(
                "SYSTEM_PROMPT",
                "你是一位專業的專利分析助理，精通中英文專利文件解讀、"
                "獨立請求項分析與 Office Action 回應策略。"
                "請以簡潔、準確的繁體中文回答問題。",
            ),
        )
