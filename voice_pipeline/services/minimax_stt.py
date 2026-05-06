"""
MinimaxSTTService
-----------------
將 MiniMax speech-01-turbo ASR REST API 封裝為 Pipecat STTService。

工作流程：
  1. Pipecat VAD 偵測到說話結束時，將累積的 PCM bytes 傳入 run_stt()。
  2. 本 service 將 PCM 包裝成 WAV 容器後 POST 到 MiniMax ASR endpoint。
  3. 解析 JSON 回應，yield TranscriptionFrame 給下游 LLM context aggregator。

支援最多 3 次指數退避重試；網路錯誤或 4xx/5xx 均會記錄詳細 log。
"""
from __future__ import annotations

import asyncio
import io
import logging
import wave
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import aiohttp

from pipecat.frames.frames import AudioRawFrame, ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.stt_service import STTService, STTSettings

logger = logging.getLogger(__name__)

# ---------- 常數 ----------
_MINIMAX_ASR_URL = "https://api.minimax.chat/v1/audio/transcriptions"
_MAX_RETRIES = 3
_BASE_RETRY_DELAY = 1.0  # 秒；第 n 次重試等待 n * BASE 秒


# ---------- 工具函式 ----------

def _pcm_to_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """將原始 16-bit PCM 包裝成標準 WAV 容器。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)          # 16-bit = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- 主類別 ----------

class MinimaxSTTService(STTService):
    """
    MiniMax ASR 的 Pipecat STTService 封裝。

    Parameters
    ----------
    api_key      : MiniMax API Key（Bearer Token）
    group_id     : MiniMax Group ID（以 params={"GroupId":...} 方式傳入請求）
    model        : ASR 模型名稱，預設 "chinese-common"
    language     : 語言代碼，"zh"（中文）或 "en"（英文）等
    sample_rate  : 輸入 PCM 的採樣率，需與 DailyTransport 一致（預設 16000）
    asr_url      : ASR base endpoint，可覆寫以指向私有部署
    """

    def __init__(
        self,
        *,
        api_key: str,
        group_id: str,
        model: str = "chinese-common",
        language: str = "zh",
        sample_rate: int = 16000,
        asr_url: str = _MINIMAX_ASR_URL,
        **kwargs,
    ):
        super().__init__(
            settings=STTSettings(model=model, language=language),
            sample_rate=sample_rate,
            **kwargs,
        )
        self._api_key = api_key
        self._group_id = group_id
        self._model = model
        self._language = language
        self._asr_url = asr_url          # 保持乾淨，不拼 GroupId 字串
        self._http: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------
    # 私有輔助方法
    # ------------------------------------------------------------------

    async def _get_http(self) -> aiohttp.ClientSession:
        """延遲建立並復用 aiohttp session。"""
        if self._http is None or self._http.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._http = aiohttp.ClientSession(timeout=timeout)
        return self._http

    async def _call_asr(self, wav_bytes: bytes) -> str:
        """
        呼叫 MiniMax ASR API；含指數退避重試。
        成功回傳轉錄文字；失敗回傳空字串。
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
        }
        params = {"GroupId": self._group_id}

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                session = await self._get_http()

                form = aiohttp.FormData()
                form.add_field(
                    "file",
                    wav_bytes,
                    filename="audio.wav",
                    content_type="audio/wav",
                )
                form.add_field("model", self._model)
                if self._language:
                    form.add_field("language", self._language)

                async with session.post(
                    self._asr_url, data=form, headers=headers, params=params
                ) as resp:
                    if resp.status == 200:
                        payload = await resp.json(content_type=None)
                        text = (payload.get("text") or "").strip()
                        logger.debug(
                            f"[MinimaxSTT] ASR 成功（attempt {attempt}）: {text!r}"
                        )
                        return text

                    body = await resp.text()
                    logger.error(
                        f"[MinimaxSTT] HTTP {resp.status} "
                        f"(attempt {attempt}/{_MAX_RETRIES}): {body[:300]}"
                    )

            except aiohttp.ClientError as exc:
                logger.warning(
                    f"[MinimaxSTT] 網路錯誤 (attempt {attempt}/{_MAX_RETRIES}): {exc}"
                )

            if attempt < _MAX_RETRIES:
                wait = _BASE_RETRY_DELAY * attempt
                logger.info(f"[MinimaxSTT] {wait:.1f}s 後重試…")
                await asyncio.sleep(wait)

        logger.error("[MinimaxSTT] 所有重試均失敗，跳過此次轉錄。")
        return ""

    # ------------------------------------------------------------------
    # Pipecat STTService 抽象方法實作
    # ------------------------------------------------------------------

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """
        由 Pipecat 在 VAD 偵測到語音結束後呼叫。
        audio: 原始 16-bit PCM bytes（mono, self._sample_rate Hz）
        """
        if not audio:
            return

        logger.debug(
            f"[MinimaxSTT] 收到 {len(audio):,} bytes PCM，"
            f"約 {len(audio) / (self._sample_rate * 2):.2f}s"
        )

        wav_bytes = _pcm_to_wav(audio, self._sample_rate)
        text = await self._call_asr(wav_bytes)

        if text:
            logger.info(f"[MinimaxSTT] 轉錄結果: {text!r}")
            yield TranscriptionFrame(
                text=text,
                user_id="",
                timestamp=_utc_now_iso(),
            )
        else:
            logger.warning("[MinimaxSTT] 轉錄結果為空，略過此幀。")

    # ------------------------------------------------------------------
    # 資源清理
    # ------------------------------------------------------------------

    async def cleanup(self):
        if self._http and not self._http.closed:
            await self._http.close()
            logger.debug("[MinimaxSTT] HTTP session 已關閉。")
        await super().cleanup()
