"""
PatentFlow Voice Bot
--------------------
Pipecat 流水線主入口。

流水線架構（左 → 右）：

  DailyTransport.input()
    → SileroVADAnalyzer         # 人聲偵測
    → WhisperSTTService         # 語音 → 文字 (本地 Faster Whisper base 中文)
    → LLMUserContextAggregator  # 累積對話上下文
    → OpenAILLMService          # Kimi / Moonshot LLM（OpenAI 兼容模式）
    → ElevenLabsTTSService      # 文字 → 語音（預設）
      或 MinimaxTTSService      # 文字 → 語音（TTS_PROVIDER=minimax）
    → DailyTransport.output()
    → LLMAssistantContextAggregator # 記錄 AI 回應

TTS 提供商設定（.env）：
  TTS_PROVIDER=elevenlabs   → ElevenLabs（預設，需設定 ELEVENLABS_API_KEY / VOICE_ID）
  TTS_PROVIDER=minimax      → MiniMax T2A V2（需設定 MINIMAX_API_KEY / GROUP_ID）

啟動方式（請在 PatentFlow 倉庫根目錄執行）：
  cd <PatentFlow>
  python -m voice_pipeline.bot
  python -m voice_pipeline.bot --room-url <URL> --token <BOT_TOKEN>
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import warnings
from pathlib import Path

# 壓制 pipecat 0.0.108 遷移期間的大量 deprecated 警告，避免塞滿 log
warnings.filterwarnings("ignore", category=DeprecationWarning)

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import AudioRawFrame, Frame, LLMMessagesFrame, TTSStartedFrame, TTSStoppedFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.daily.transport import DailyParams, DailyTransport

from voice_pipeline.config import VoiceConfig
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transcriptions.language import Language
from voice_pipeline.services.minimax_tts import MinimaxTTSService

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")


# ------------------------------------------------------------------
# 音訊診斷處理器：計算 TTS 實際送出的音訊幀數量
# 確認後可移除（或設 AUDIO_DIAG=false 在 .env 關閉）
# ------------------------------------------------------------------
class AudioDiagnostics(FrameProcessor):
    """插在 tts → transport.output() 之間，確認音訊幀確實存在。"""

    def __init__(self):
        super().__init__()
        self._audio_frames = 0
        self._total_bytes = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSStartedFrame):
            self._audio_frames = 0
            self._total_bytes = 0
            logger.info("[AudioDiag] TTS 開始 → 等待音訊幀…")

        elif isinstance(frame, AudioRawFrame):
            self._audio_frames += 1
            self._total_bytes += len(frame.audio)
            if self._audio_frames == 1:
                logger.info(
                    f"[AudioDiag] ✅ 第一個音訊幀！"
                    f" rate={frame.sample_rate} Hz, channels={frame.num_channels},"
                    f" size={len(frame.audio)} bytes"
                )
            elif self._audio_frames % 20 == 0:
                logger.info(
                    f"[AudioDiag] 音訊幀累計 {self._audio_frames}，共 {self._total_bytes} bytes"
                )

        elif isinstance(frame, TTSStoppedFrame):
            if self._audio_frames == 0:
                logger.warning("[AudioDiag] ⚠️  TTS 結束但沒有產生任何音訊幀！（可能靜默失敗）")
            else:
                logger.info(
                    f"[AudioDiag] TTS 結束，共送出 {self._audio_frames} 幀 / {self._total_bytes} bytes"
                )

        await self.push_frame(frame, direction)

# ------------------------------------------------------------------
# 設定 loguru 輸出格式
# ------------------------------------------------------------------
logger.remove()
logger.add(
    sys.stderr,
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> - {message}"
    ),
    colorize=True,
)

# 讓標準 logging 也路由到 loguru（供 aiohttp 等第三方庫使用）
logging.basicConfig(handlers=[logging.StreamHandler(sys.stderr)], level=logging.WARNING)


# ------------------------------------------------------------------
# 流水線工廠
# ------------------------------------------------------------------

async def run_bot(room_url: str, token: str = "") -> None:
    cfg = VoiceConfig.from_env()

    # 若指定了 room_url 參數則覆寫 env 設定
    if room_url:
        cfg.daily_room_url = room_url
    if token:
        cfg.daily_token = token

    if not cfg.daily_room_url:
        logger.error("Daily room URL 未設定，請設定 DAILY_SAMPLE_ROOM_URL 或傳入 --room-url")
        sys.exit(1)

    logger.info(f"連接 Daily 房間: {cfg.daily_room_url}")

    # ---- Transport (WebRTC) ----
    transport = DailyTransport(
        room_url=cfg.daily_room_url,
        token=cfg.daily_token or None,
        bot_name="PatentFlow 語音助理",
        params=DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            transcription_enabled=False,   # 由 MinimaxSTT 自行處理
            # vad_analyzer 仍放在 TransportParams 以觸發 VAD（pipecat 0.0.108 仍支援，只是 deprecated warning）
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    # ---- STT（本地 Faster Whisper，base 模型，中文）----
    # MiniMax 沒有 STT REST API，改用本地 Faster Whisper。
    # 首次啟動會自動下載 base 模型（~150MB）。
    stt = WhisperSTTService(
        settings=WhisperSTTService.Settings(
            model="base",
            language=Language.ZH,
            no_speech_prob=0.4,
        ),
        device="cpu",
        compute_type="int8",
    )

    # ---- LLM（OpenAI 兼容模式對接 Kimi / Moonshot）----
    llm = OpenAILLMService(
        api_key=cfg.moonshot_api_key,
        base_url=cfg.moonshot_base_url,
        model=cfg.moonshot_model,
    )

    # ---- TTS（根據 TTS_PROVIDER 切換）----
    if cfg.tts_provider == "elevenlabs":
        logger.info(
            f"TTS: ElevenLabs — model={cfg.elevenlabs_model}, voice={cfg.elevenlabs_voice_id}"
        )
        tts = ElevenLabsTTSService(
            api_key=cfg.elevenlabs_api_key,
            settings=ElevenLabsTTSService.Settings(
                model=cfg.elevenlabs_model,
                voice=cfg.elevenlabs_voice_id,
            ),
        )
    elif cfg.tts_provider == "minimax":
        logger.info(
            f"TTS: MiniMax — model=speech-01-turbo, voice={cfg.minimax_voice_id}"
        )
        tts = MinimaxTTSService(
            api_key=cfg.minimax_api_key,
            group_id=cfg.minimax_group_id,
            voice_id=cfg.minimax_voice_id,
            sample_rate=cfg.minimax_tts_sample_rate,
        )
    else:
        logger.error(f"不支援的 TTS_PROVIDER={cfg.tts_provider!r}")
        sys.exit(1)

    # ---- 對話上下文 ----
    initial_messages = [
        {
            "role": "system",
            "content": cfg.system_prompt,
        }
    ]
    context = OpenAILLMContext(initial_messages)
    context_aggregator = llm.create_context_aggregator(context)

    # ---- 組裝 Pipeline ----
    audio_diag = AudioDiagnostics()
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            audio_diag,          # ← 診斷：確認音訊幀是否存在
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    # ---- 建立 PipelineTask ----
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,   # 允許用戶打斷 AI 回應
            enable_metrics=True,
            send_initial_empty_metrics=False,
        ),
    )

    # ---- Daily 事件處理器 ----

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        pid = participant.get("id", "unknown")
        logger.info(f"第一位參與者加入: {pid}")
        # 主動送出 bot-ready：修正競態條件——瀏覽器可能在 bot 加入前已發送
        # client-ready 並在等待 bot-ready；直接通知它 bot 已就緒即可。
        if task.rtvi:
            try:
                await task.rtvi.set_bot_ready()
                logger.info("bot-ready 已主動送出")
            except Exception as exc:
                logger.warning(f"set_bot_ready 失敗: {exc}")
        # 觸發 LLM 發出歡迎語
        await task.queue_frames([LLMMessagesFrame(initial_messages)])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        pid = participant.get("id", "unknown")
        logger.info(f"參與者離開: {pid}，原因: {reason}")
        await task.cancel()

    @transport.event_handler("on_call_state_updated")
    async def on_call_state_updated(transport, state):
        logger.info(f"通話狀態更新: {state}")
        if state == "left":
            await task.cancel()

    # ---- 啟動 ----
    runner = PipelineRunner()
    logger.info("語音流水線啟動，等待參與者加入…")
    await runner.run(task)


# ------------------------------------------------------------------
# CLI 入口
# ------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PatentFlow Voice Bot")
    parser.add_argument(
        "--room-url",
        default="",
        help="Daily 房間 URL（覆寫 .env 中的 DAILY_SAMPLE_ROOM_URL）",
    )
    parser.add_argument(
        "--token",
        default="",
        help="Daily Bot Token（可選，用於私有房間認證）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(run_bot(room_url=args.room_url, token=args.token))
