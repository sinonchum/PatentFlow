"""
PatentFlow Voice Pipeline — FastAPI Server
------------------------------------------
提供 HTTP 入口供前端呼叫；每次 `/connect` 或 **`/start_bot`** 請求會：
  1. 建立（或重用）一個 Daily WebRTC 房間。
  2. 在子進程中啟動 voice_pipeline/bot.py。
  3. 回傳房間 URL 和可選的 token 給前端。

房間建立策略：
  - 若設定了 DAILY_API_KEY → 每次請求動態建立新房間（推薦生產環境）
  - 否則使用 DAILY_SAMPLE_ROOM_URL 固定房間（適合開發/測試）

啟動方式（請在專案根目錄 PatentFlow 下執行，否則 python -m voice_pipeline 會找不到套件）：
  cd <PatentFlow 根目錄>
  python -m voice_pipeline.server
  uvicorn voice_pipeline.server:app --host 0.0.0.0 --port 7860 --reload

前端頁面與 API 同源：啟動後在瀏覽器開啟 http://localhost:7860/
（靜態資源掛載自專案根目錄的 voice_pipeline_frontend/）

POST /connect 回傳的 JSON 必須含「url」（不是 room_url），以符合 Pipecat DailyTransport。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ------------------------------------------------------------------
# 全域設定
# ------------------------------------------------------------------
DAILY_API_URL = "https://api.daily.co/v1"
DAILY_API_KEY = os.getenv("DAILY_API_KEY", "")
DAILY_SAMPLE_ROOM_URL = os.getenv("DAILY_SAMPLE_ROOM_URL", "")
VOICE_SERVER_HOST = os.getenv("VOICE_SERVER_HOST", "0.0.0.0")
VOICE_SERVER_PORT = int(os.getenv("VOICE_SERVER_PORT", "7860"))

# voice_pipeline_frontend/ 與 voice_pipeline/ 同在專案根目錄
_FRONTEND_DIR = _PROJECT_ROOT / "voice_pipeline_frontend"

# 追蹤每個房間正在執行的 bot 子進程（room_url → Popen）
_active_bots: dict[str, subprocess.Popen] = {}


# ------------------------------------------------------------------
# 應用生命週期
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # 伺服器關閉時終止所有 bot 子進程
    for url, proc in list(_active_bots.items()):
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)


# ------------------------------------------------------------------
# FastAPI App
# ------------------------------------------------------------------

app = FastAPI(
    title="PatentFlow Voice Pipeline",
    description="Pipecat + MiniMax ASR/TTS + Kimi LLM 語音 AI 服務",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 生產環境請改為明確的域名列表
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# 資料模型
# ------------------------------------------------------------------

class ConnectRequest(BaseModel):
    session_id: str = ""          # 可選：前端提供的 session 標識

class ConnectResponse(BaseModel):
    """Pipecat DailyTransport / startBotAndConnect 需要鍵名 url（見官方文件 DailyCallOptions）。"""

    url: str
    token: str = ""
    session_id: str = ""


# ------------------------------------------------------------------
# 輔助函式
# ------------------------------------------------------------------

async def _create_daily_room(session: aiohttp.ClientSession) -> dict:
    """呼叫 Daily API 建立一個有效期 1 小時的房間。"""
    headers = {
        "Authorization": f"Bearer {DAILY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "properties": {
            "exp": int(time.time()) + 3600,
            "eject_at_room_exp": True,
            "enable_chat": False,
            "enable_screenshare": False,
            "start_video_off": True,
        }
    }
    async with session.post(
        f"{DAILY_API_URL}/rooms", json=payload, headers=headers
    ) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise HTTPException(
                status_code=502,
                detail=f"Daily 房間建立失敗 (HTTP {resp.status}): {body[:200]}",
            )
        return await resp.json()


async def _create_meeting_token(
    session: aiohttp.ClientSession, room_name: str, is_owner: bool = True
) -> str:
    """建立 Daily meeting token。"""
    headers = {
        "Authorization": f"Bearer {DAILY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "properties": {
            "room_name": room_name,
            "is_owner": is_owner,
            "exp": int(time.time()) + 3600,
        }
    }
    async with session.post(
        f"{DAILY_API_URL}/meeting-tokens", json=payload, headers=headers
    ) as resp:
        if resp.status != 200:
            return ""   # token 失敗不致命，繼續嘗試連接
        data = await resp.json()
        return data.get("token", "")


def _spawn_bot(room_url: str, token: str = "") -> subprocess.Popen:
    """在獨立子進程中啟動 bot.py。

    注意：使用獨立日誌檔案而非 PIPE，避免 pipe buffer 填滿後 bot 子進程卡死。
    日誌路徑：logs/bot_<timestamp>.log
    """
    # 清理已結束的舊 bot
    dead = [u for u, p in _active_bots.items() if p.poll() is not None]
    for u in dead:
        del _active_bots[u]

    env = {**os.environ, "DAILY_SAMPLE_ROOM_URL": room_url}
    if token:
        env["DAILY_TOKEN"] = token

    log_dir = _PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"bot_{int(time.time())}.log"

    log_fh = open(log_path, "w", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "-m", "voice_pipeline.bot",
         "--room-url", room_url,
         "--token", token or ""],
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdout=log_fh,
        stderr=log_fh,
    )
    # 讓 OS 幫我們關 log 檔 handle（子進程持有引用）
    log_fh.close()

    _active_bots[room_url] = proc
    import logging as _logging
    _logging.getLogger("uvicorn.error").info(
        f"Bot 子進程已啟動 PID={proc.pid}，日誌 → {log_path}"
    )
    return proc


# ------------------------------------------------------------------
# API Endpoints
# ------------------------------------------------------------------

@app.get("/health")
async def health():
    """健康檢查端點。"""
    return {
        "status": "ok",
        "active_bots": len(_active_bots),
        "mode": "dynamic" if DAILY_API_KEY else "static",
    }


@app.post("/connect", response_model=ConnectResponse)
@app.post("/start_bot", response_model=ConnectResponse)
async def connect(req: ConnectRequest = ConnectRequest()):
    """
    前端呼叫此端點以取得 Daily 房間 URL 並觸發 bot 啟動。

    回傳：
      url       : Daily 房間 URL（Pipecat 客戶端必填欄位名為 url）
      token     : 瀏覽器進房用的 meeting token（可選；請勿與後台 bot owner token 混用）
    """
    room_url: str
    client_token: str = ""
    bot_token: str = ""

    if DAILY_API_KEY:
        # 動態建立房間（生產模式）
        async with aiohttp.ClientSession() as session:
            room_data = await _create_daily_room(session)
            room_url = room_data["url"]
            room_name = room_data["name"]
            bot_token = await _create_meeting_token(
                session, room_name, is_owner=True
            )
            client_token = await _create_meeting_token(
                session, room_name, is_owner=False
            )
    elif DAILY_SAMPLE_ROOM_URL:
        # 使用靜態房間（開發模式）
        room_url = DAILY_SAMPLE_ROOM_URL
        bot_token = os.getenv("DAILY_TOKEN", "")
        # 給瀏覽器的 token（若有）；未設定則視為公開進房或可匿名加入
        client_token = os.getenv("DAILY_CLIENT_TOKEN", "")
    else:
        raise HTTPException(
            status_code=500,
            detail=(
                "請在 .env 中設定 DAILY_API_KEY（動態模式）"
                " 或 DAILY_SAMPLE_ROOM_URL（靜態模式）"
            ),
        )

    proc = _spawn_bot(room_url, bot_token)

    return ConnectResponse(
        url=room_url,
        token=client_token,
        session_id=req.session_id or str(proc.pid),
    )


@app.get("/status")
async def status():
    """回傳所有 bot 子進程狀態。"""
    return {
        url: {"pid": proc.pid, "running": proc.poll() is None}
        for url, proc in _active_bots.items()
    }


# ------------------------------------------------------------------
# 靜態前端（必須掛載在 API 路由之後，避免遮蔽 /health、/connect 等）
# ------------------------------------------------------------------

if _FRONTEND_DIR.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIR), html=True),
        name="frontend",
    )


# ------------------------------------------------------------------
# 直接執行
# ------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "voice_pipeline.server:app",
        host=VOICE_SERVER_HOST,
        port=VOICE_SERVER_PORT,
        reload=False,
        log_level="info",
    )
