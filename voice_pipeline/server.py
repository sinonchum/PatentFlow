"""ClaimPilot Voice Server using Gradbot + Gradium.

This replaces the legacy Pipecat/Daily implementation for local demo use.
Gradbot handles streaming STT/TTS via Gradium and the LLM via the existing
OpenAI-compatible LLM_* environment variables.

Run:
  . .voice-venv/bin/activate
  python -m voice_pipeline.server
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import time
import urllib.error
import urllib.request
from typing import Any

import fastapi
import gradbot
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

if os.getenv("VOICE_LLM_API_KEY"):
    os.environ["LLM_API_KEY"] = os.getenv("VOICE_LLM_API_KEY", "")
if os.getenv("VOICE_LLM_BASE_URL"):
    os.environ["LLM_BASE_URL"] = os.getenv("VOICE_LLM_BASE_URL", "")
if os.getenv("VOICE_LLM_MODEL"):
    os.environ["LLM_MODEL"] = os.getenv("VOICE_LLM_MODEL", "")

VOICE_SERVER_HOST = os.getenv("VOICE_SERVER_HOST", "0.0.0.0")
VOICE_SERVER_PORT = int(os.getenv("VOICE_SERVER_PORT", "7860"))
PUBLIC_BASE_URL = os.getenv("NEXT_PUBLIC_VOICE_SERVER_URL", f"http://localhost:{VOICE_SERVER_PORT}").rstrip("/")

SYSTEM_PROMPT = """You are ClaimPilot Voice Assistant, a professional patent prosecution aide.

You help European patent attorneys discuss office actions, claim charts,
Art. 56 inventive step, Art. 123(2) added-matter risk, translation issues,
and response strategy.

You are connected to the local ClaimPilot backend. When the user asks for
ClaimPilot-specific work, use tools instead of guessing:
- generate_claim_chart for Art. 56 claim/prior-art mapping.
- verify_translation for Art. 123(2) translation drift checks.
- start_claimpilot_pipeline and check_claimpilot_status for full document workflows.
- get_attorney_memory for local attorney style preferences.

Privacy rule: never expose API keys or secrets in speech or UI messages. Do not
send data to external services except the configured voice LLM/STT/TTS providers.

Rules for voice:
1. Keep replies short: one or two sentences unless the user asks for detail.
2. Be precise and cautious. Do not invent legal facts or citations.
3. If the user asks for drafting strategy, structure the answer around issue,
risk, evidence, and proposed response.
4. Use professional English by default; switch to French or Chinese if the
user speaks those languages.
"""

DEFAULT_VOICE_ID = os.getenv("GRADIUM_VOICE_ID", "YTpq7expH9539ERJ")  # Emma
CLAIMPILOT_API_BASE_URL = os.getenv("CLAIMPILOT_API_BASE_URL", "http://localhost:8000").rstrip("/")
_session_contexts: dict[str, dict[str, Any]] = {}

gradbot.init_logging()
app = fastapi.FastAPI(title="ClaimPilot Voice Assistant", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
cfg = gradbot.config.from_env()


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{CLAIMPILOT_API_BASE_URL}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": "error", "http_status": exc.code, "error": body[:1000]}


def _get_json(path: str) -> dict[str, Any]:
    url = f"{CLAIMPILOT_API_BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": "error", "http_status": exc.code, "error": body[:1000]}


def build_claimpilot_tools() -> list[gradbot.ToolDef]:
    return [
        gradbot.ToolDef(
            "generate_claim_chart",
            "Generate an Art. 56 claim chart from claim text and prior art or office action text.",
            json.dumps({
                "type": "object",
                "properties": {
                    "claim_text": {"type": "string"},
                    "prior_art_text": {"type": "string"},
                    "office_action_text": {"type": "string"},
                    "publication_number": {"type": "string"},
                    "attorney_id": {"type": "string"},
                },
            }),
        ),
        gradbot.ToolDef(
            "verify_translation",
            "Verify Chinese-to-English patent translation for Art. 123(2) added-matter risk and terminology drift.",
            json.dumps({
                "type": "object",
                "properties": {
                    "original_cn": {"type": "string"},
                    "target_en": {"type": "string"},
                    "back_cn": {"type": "string"},
                    "attorney_id": {"type": "string"},
                },
                "required": ["original_cn", "target_en"],
            }),
        ),
        gradbot.ToolDef(
            "start_claimpilot_pipeline",
            "Start the full ClaimPilot pipeline for office action and specification text.",
            json.dumps({
                "type": "object",
                "properties": {
                    "office_action_text": {"type": "string"},
                    "specification_text": {"type": "string"},
                    "examiner_preference": {"type": "string"},
                    "claim_type": {"type": "string"},
                    "attorney_name": {"type": "string"},
                },
                "required": ["office_action_text", "specification_text"],
            }),
        ),
        gradbot.ToolDef(
            "check_claimpilot_status",
            "Check status and results for a ClaimPilot task id.",
            json.dumps({"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}),
        ),
        gradbot.ToolDef(
            "get_attorney_memory",
            "Retrieve local attorney preference memory for a ClaimPilot attorney profile.",
            json.dumps({"type": "object", "properties": {"attorney_id": {"type": "string"}}, "required": ["attorney_id"]}),
        ),
    ]


def make_config(msg: dict[str, Any]) -> gradbot.SessionConfig:
    voice_id = msg.get("voice_id") or DEFAULT_VOICE_ID
    language = msg.get("language") or "en"
    prompt = msg.get("prompt") or SYSTEM_PROMPT
    return gradbot.SessionConfig(
        voice_id=voice_id,
        language=gradbot.LANGUAGES.get(language),
        instructions=prompt,
        tools=build_claimpilot_tools(),
        **({"assistant_speaks_first": True, "silence_timeout_s": 0.0} | cfg.session_kwargs),
    )


def _clip(text: Any, limit: int) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + "\n[TRUNCATED]"


def _build_session_prompt(ctx: dict[str, Any]) -> str:
    latest_result = ctx.get("latest_result") or {}
    parts = [SYSTEM_PROMPT]
    parts.append("\nCurrent ClaimPilot workspace context is attached below. Use it as the primary case file for this voice session.")
    parts.append("\nMatter metadata:")
    parts.append(f"- Attorney profile: {ctx.get('attorney_profile') or 'Default'}")
    parts.append(f"- Attorney name: {ctx.get('attorney_name') or ''}")
    parts.append(f"- Examiner preference: {ctx.get('examiner_preference') or ''}")
    parts.append(f"- Claim type: {ctx.get('claim_type') or ''}")
    parts.append(f"- Current task id: {ctx.get('task_id') or ''}")
    parts.append(f"- Current task state: {ctx.get('task_state') or ''}")

    office_action = _clip(ctx.get("office_action_text"), 12000)
    specification = _clip(ctx.get("specification_text"), 12000)
    if office_action:
        parts.append("\nOffice Action text:\n" + office_action)
    if specification:
        parts.append("\nPatent Specification text:\n" + specification)

    if latest_result:
        parts.append("\nLatest ClaimPilot result JSON:\n" + _clip(json.dumps(latest_result, ensure_ascii=False), 12000))

    parts.append(
        "\nWhen answering, explicitly rely on this attached ClaimPilot context. "
        "If the user asks to analyze the Office Action, discuss the objections, cited art, claim limitations, and response strategy. "
        "If deeper structured output is needed, call the ClaimPilot tools."
    )
    return "\n".join(parts)


async def handle_tool_call(handle, input_handle, websocket) -> None:
    try:
        tool_name = getattr(handle, "name", None) or getattr(handle, "tool_name", None)
        args = getattr(handle, "args", None) or {}
        if not isinstance(args, dict):
            args = {}

        if tool_name == "generate_claim_chart":
            result = await asyncio.to_thread(_post_json, "/api/generate-chart", {
                "claim_text": args.get("claim_text", ""),
                "prior_art_text": args.get("prior_art_text", ""),
                "office_action_text": args.get("office_action_text", ""),
                "publication_number": args.get("publication_number", ""),
                "attorney_id": args.get("attorney_id", "Default"),
            })
            await handle.send(json.dumps(result, ensure_ascii=False))
            return

        if tool_name == "verify_translation":
            result = await asyncio.to_thread(_post_json, "/api/verify-translation", {
                "original_cn": args.get("original_cn", ""),
                "target_en": args.get("target_en", ""),
                "back_cn": args.get("back_cn", ""),
                "attorney_id": args.get("attorney_id", "Default"),
            })
            await handle.send(json.dumps(result, ensure_ascii=False))
            return

        if tool_name == "start_claimpilot_pipeline":
            result = await asyncio.to_thread(_post_json, "/api/generate", {
                "office_action_text": args.get("office_action_text", ""),
                "specification_text": args.get("specification_text", ""),
                "examiner_preference": args.get("examiner_preference", ""),
                "claim_type": args.get("claim_type", "Method"),
                "attorney_name": args.get("attorney_name", ""),
            })
            await handle.send(json.dumps(result, ensure_ascii=False))
            return

        if tool_name == "check_claimpilot_status":
            task_id = str(args.get("task_id", "")).strip()
            result = await asyncio.to_thread(_get_json, f"/api/status/{task_id}")
            await handle.send(json.dumps(result, ensure_ascii=False))
            return

        if tool_name == "get_attorney_memory":
            attorney_id = str(args.get("attorney_id", "Default")).strip() or "Default"
            result = await asyncio.to_thread(_get_json, f"/api/memory/{attorney_id}")
            await handle.send(json.dumps(result, ensure_ascii=False))
            return

        await handle.send_error(f"Unknown ClaimPilot tool: {tool_name}")
    except Exception as exc:
        await handle.send_error(f"ClaimPilot tool failed: {exc}")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": "gradbot+gradium",
        "has_gradium_key": bool(os.getenv("GRADIUM_API_KEY")),
        "has_llm_key": bool(os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")),
    }


@app.post("/start_bot")
@app.post("/connect")
async def start_bot(request: fastapi.Request) -> dict[str, str]:
    # Compatibility endpoint for the main ClaimPilot frontend button.
    # Gradbot runs in the browser via WebSocket rather than spawning a Daily bot,
    # so the correct action is embedding the voice UI hosted by this service.
    try:
        ctx = await request.json()
        if not isinstance(ctx, dict):
            ctx = {}
    except Exception:
        ctx = {}
    session_id = f"pf-{int(time.time() * 1000)}"
    _session_contexts[session_id] = ctx
    return {"url": f"{PUBLIC_BASE_URL}/?session_id={session_id}", "token": "", "session_id": session_id}


@app.get("/context/{session_id}")
async def context(session_id: str) -> dict[str, Any]:
    ctx = _session_contexts.get(session_id, {})
    return {
        "session_id": session_id,
        "has_context": bool(ctx),
        "prompt": _build_session_prompt(ctx) if ctx else SYSTEM_PROMPT,
    }


@app.post("/end_session/{session_id}")
async def end_session(session_id: str) -> dict[str, Any]:
    removed = _session_contexts.pop(session_id, None) is not None
    return {"status": "ended", "session_id": session_id, "removed": removed}


@app.websocket("/ws/chat")
async def ws_chat(websocket: fastapi.WebSocket) -> None:
    await gradbot.websocket.handle_session(
        websocket,
        config=cfg,
        on_start=make_config,
        on_tool_call=handle_tool_call,
        run_kwargs=cfg.client_kwargs,
    )


gradbot.routes.setup(
    app,
    config=cfg,
    static_dir=pathlib.Path(__file__).parent / "static",
    with_voices=True,
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "voice_pipeline.server:app",
        host=VOICE_SERVER_HOST,
        port=VOICE_SERVER_PORT,
        reload=False,
        log_level="info",
    )
