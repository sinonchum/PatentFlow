"""
MinimaxTTSService
-----------------
將 MiniMax T2A V2 串流 TTS API 封裝為 Pipecat TTSService。

工作流程：
  1. Pipecat 將 LLM 輸出的文字句子傳入 run_tts()。
  2. 本 service 以 SSE 串流模式呼叫 MiniMax T2A V2 API。
  3. 解析每個 SSE data chunk（hex 編碼的 PCM）並即時 yield AudioRawFrame。
  4. 串流結束後 yield TTSStoppedFrame，通知 transport 播放完畢。

支援最多 3 次指數退避重試；同時對 hex / base64 音訊編碼自動偵測。
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import AsyncGenerator, Optional

import aiohttp
from loguru import logger

from pipecat.frames.frames import (
    AudioRawFrame,
    ErrorFrame,
    Frame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService, TTSSettings

# ---------- 常數 ----------
# api.minimaxi.chat（多一個 i）是 MiniMax 中國大陸正式端點
_MINIMAX_T2A_URL = "https://api.minimaxi.chat/v1/t2a_v2"
_MAX_RETRIES = 3
_BASE_RETRY_DELAY = 1.0


# ---------- 工具函式 ----------

def _decode_audio(raw: str) -> Optional[bytes]:
    """
    嘗試 hex 解碼（MiniMax T2A V2 預設格式），失敗則嘗試 base64。
    兩種皆失敗回傳 None。
    """
    if not raw:
        return None
    try:
        return bytes.fromhex(raw)
    except (ValueError, TypeError):
        pass
    try:
        return base64.b64decode(raw)
    except Exception:
        pass
    logger.warning("[MinimaxTTS] 無法解碼音訊字串，長度=%d", len(raw))
    return None


# ---------- 主類別 ----------

class MinimaxTTSService(TTSService):
    """
    MiniMax T2A V2 串流 TTS 的 Pipecat TTSService 封裝。

    Parameters
    ----------
    api_key      : MiniMax API Key
    group_id     : MiniMax Group ID（放入 URL query 參數）
    voice_id     : 音色 ID，預設 "male-qn-qingse"
                   其他選項: "female-shaonv", "female-yujie", "male-qn-jingying" 等
    model        : T2A 模型，預設 "speech-01-turbo"（token plan 通用；升級後可改 "speech-02-turbo"）
    speed        : 語速，0.5 ~ 2.0
    vol          : 音量，0.1 ~ 10.0
    pitch        : 音調，-12 ~ 12
    sample_rate  : 輸出 PCM 採樣率（16000 或 24000）
    tts_url      : TTS endpoint，可覆寫以指向私有部署
    """

    def __init__(
        self,
        *,
        api_key: str,
        group_id: str,
        voice_id: str = "male-qn-qingse",
        model: str = "speech-01-turbo",
        speed: float = 1.0,
        vol: float = 1.0,
        pitch: int = 0,
        sample_rate: int = 16000,
        tts_url: str = _MINIMAX_T2A_URL,
        **kwargs,
    ):
        super().__init__(
            settings=TTSSettings(model=model, voice=voice_id, language=None),
            sample_rate=sample_rate,
            **kwargs,
        )
        self._api_key = api_key
        self._group_id = group_id
        self._voice_id = voice_id
        self._model = model
        self._speed = speed
        self._vol = vol
        self._pitch = pitch
        self._tts_url = tts_url
        self._http: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------
    # 私有輔助方法
    # ------------------------------------------------------------------

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            # 串流 TTS 可能耗時較長，設定寬鬆的 read timeout
            timeout = aiohttp.ClientTimeout(total=120, connect=10)
            self._http = aiohttp.ClientSession(timeout=timeout)
        return self._http

    def _build_payload(self, text: str) -> dict:
        return {
            "model": self._model,
            "text": text,
            "stream": True,
            "voice_setting": {
                "voice_id": self._voice_id,
                "speed": self._speed,
                "vol": self._vol,
                "pitch": self._pitch,
            },
            "audio_setting": {
                "sample_rate": self._sample_rate,
                "bitrate": 128000,
                "format": "pcm",
                "channel": 1,
            },
        }

    # ------------------------------------------------------------------
    # Pipecat TTSService 抽象方法實作
    # ------------------------------------------------------------------

    async def run_tts(self, text: str, context_id: str = "") -> AsyncGenerator[Frame, None]:
        """
        由 Pipecat 在需要合成語音時呼叫（pipecat 0.0.108 簽名：text + context_id）。
        text: LLM 輸出的文字片段。
        context_id: pipecat 內部傳入的上下文 ID，本 service 不使用。
        """
        if not text.strip():
            return

        logger.info(f"[MinimaxTTS] 開始合成（{len(text)} 字元）: {text[:60]!r}")

        url = f"{self._tts_url}?GroupId={self._group_id}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(text)

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                session = await self._get_http()

                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(
                            f"[MinimaxTTS] HTTP {resp.status} "
                            f"(attempt {attempt}/{_MAX_RETRIES}): {body[:300]}"
                        )
                        if attempt < _MAX_RETRIES:
                            await asyncio.sleep(_BASE_RETRY_DELAY * attempt)
                            continue
                        yield ErrorFrame(f"MiniMax TTS HTTP {resp.status}: {body[:100]}")
                        return

                    # ---- 先讀取全部回應內容，判斷是否為 API 錯誤（非 SSE）----
                    raw_body = await resp.read()
                    body_text = raw_body.decode("utf-8", errors="replace")

                    # 若回應是 JSON 物件（不含 "data:" 行），表示 API 層級錯誤
                    if "data:" not in body_text:
                        try:
                            err_obj = json.loads(body_text.strip())
                            br = err_obj.get("base_resp", {})
                            status_code = br.get("status_code", -1)
                            status_msg = br.get("status_msg", body_text[:200])
                            logger.error(
                                f"[MinimaxTTS] API 錯誤（attempt {attempt}/{_MAX_RETRIES}）: "
                                f"status_code={status_code}, msg={status_msg}"
                            )
                        except json.JSONDecodeError:
                            logger.error(
                                f"[MinimaxTTS] 非預期回應（attempt {attempt}/{_MAX_RETRIES}）: "
                                f"{body_text[:200]}"
                            )
                        if attempt < _MAX_RETRIES:
                            await asyncio.sleep(_BASE_RETRY_DELAY * attempt)
                            continue
                        yield ErrorFrame(f"MiniMax TTS API 錯誤: {body_text[:100]}")
                        return

                    # ---- 開始串流解析 ----
                    yield TTSStartedFrame()
                    first_audio = True

                    for line in body_text.splitlines():
                        line = line.strip()

                        # SSE 行必須以 "data:" 開頭
                        if not line.startswith("data:"):
                            continue

                        data_str = line[5:].strip()
                        if not data_str:
                            continue

                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError as exc:
                            logger.warning(f"[MinimaxTTS] JSON 解析失敗: {exc} | 原始: {data_str[:80]}")
                            continue

                        # 檢查 API 層級錯誤
                        base_resp = chunk.get("base_resp", {})
                        if base_resp.get("status_code", 0) != 0:
                            err_msg = base_resp.get("status_msg", "unknown error")
                            logger.error(f"[MinimaxTTS] API 錯誤: {err_msg}")
                            break

                        inner = chunk.get("data", {})
                        status = inner.get("status", 0)
                        audio_raw = inner.get("audio", "")

                        if status == 1 and audio_raw:
                            audio_bytes = _decode_audio(audio_raw)
                            if audio_bytes:
                                if first_audio:
                                    logger.debug("[MinimaxTTS] 首個音訊片段已接收 (TTFB)")
                                    first_audio = False
                                yield AudioRawFrame(
                                    audio=audio_bytes,
                                    sample_rate=self._sample_rate,
                                    num_channels=1,
                                )
                        elif status == 2:
                            logger.debug("[MinimaxTTS] 串流結束（status=2）")
                            break

                    if first_audio:
                        logger.warning("[MinimaxTTS] 串流結束但未產生任何音訊，請確認 voice_id / model 設定。")
                    else:
                        logger.info("[MinimaxTTS] 合成完成，音訊已送出。")
                    yield TTSStoppedFrame()
                    return  # 成功，不重試

            except aiohttp.ClientError as exc:
                logger.warning(
                    f"[MinimaxTTS] 網路錯誤 (attempt {attempt}/{_MAX_RETRIES}): {exc}"
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_BASE_RETRY_DELAY * attempt)
                else:
                    yield ErrorFrame(f"MiniMax TTS 網路錯誤: {exc}")

    # ------------------------------------------------------------------
    # 資源清理
    # ------------------------------------------------------------------

    async def cleanup(self):
        if self._http and not self._http.closed:
            await self._http.close()
            logger.debug("[MinimaxTTS] HTTP session 已關閉。")
        await super().cleanup()
