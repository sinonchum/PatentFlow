# PatentFlow

Privacy-first patent prosecution workspace for European patent attorneys.

PatentFlow is a full-stack document processing system for Office Action analysis, claim-chart generation, translation risk review, attorney memory, and response drafting. It is designed for professional patent prosecution workflows where confidentiality, traceability, and structured legal reasoning matter more than generic chat output.

## Key Use Cases

- EPO Office Action analysis for Art. 56 EPC inventive-step objections
- Feature-by-feature claim chart generation against cited prior art
- Art. 123(2) EPC translation and terminology risk review
- Attorney preference memory for firm-specific drafting style and examiner strategy
- Draft response skeletons for attorney review
- Optional real-time voice session for attorney-in-the-loop analysis
- Optional Fastino Pioneer privacy mode for local or controlled inference routing

## Product Positioning

PatentFlow is not a general-purpose chatbot. It is a prosecution workspace that converts unstructured patent documents into structured, reviewable attorney work product.

Primary design goals:

- Confidential by default: local persistence, no analytics layer, controlled model routing
- Structured output: claim charts, verification rows, and draft sections instead of free-form answers
- Attorney reviewability: every generated artifact is intended for human legal review
- Operational pragmatism: FastAPI, Celery, Redis, and a static Next.js frontend for local deployment

## Architecture

```mermaid
flowchart TD
    User[Patent Attorney] --> UI[Next.js Workspace UI<br/>Port 3000]

    UI -->|Upload OA / Specification| UploadAPI[FastAPI Upload API<br/>/api/upload]
    UI -->|Start Analysis| GenerateAPI[FastAPI Generate API<br/>/api/generate]
    UI -->|Poll Status| StatusAPI[FastAPI Status API<br/>/api/status/:task_id]
    UI -->|Memory CRUD| MemoryAPI[FastAPI Memory API<br/>/api/memory/*]
    UI -->|Start / End Voice Session| VoiceServer[Gradbot Voice Server<br/>Port 7860]

    GenerateAPI --> Queue[Redis Broker<br/>Port 6379]
    Queue --> Worker[Celery Worker]

    Worker --> Parse[Document Parsing<br/>PDF / DOCX / TXT]
    Parse --> Chart[Claim Chart Generator<br/>Art. 56 EPC]
    Parse --> Verify[Translation / Terminology Verifier<br/>Art. 123(2) EPC]
    Chart --> Draft[Response Draft Builder]
    Verify --> Draft
    Draft --> ResultStore[Redis Result Backend]
    ResultStore --> StatusAPI

    MemoryAPI --> MemoryDB[(SQLite Attorney Memory)]
    MemoryDB --> Chart
    MemoryDB --> Draft

    GenerateAPI --> EPO[EPO OPS / Register APIs<br/>Optional prior-art ingestion]
    EPO --> Parse

    Chart --> Router[Model Router]
    Verify --> Router
    Draft --> Router

    Router -->|Default local-sensitive route| LocalLLM[Local / OpenAI-compatible LLM]
    Router -->|Optional privacy mode| Fastino[Fastino Pioneer<br/>Fine-tuned PatentFlow Attorney Model]
    Router -->|Fallback / public workflow| CloudLLM[Configured Cloud LLM]

    VoiceServer -->|STT -> LLM -> TTS| VoiceRuntime[Gradbot Runtime]
    VoiceRuntime --> Router
```

## System Components

- Frontend: Next.js static workspace UI
- API: FastAPI service for uploads, job submission, status polling, memory, EPO ingestion, and translation verification
- Worker: Celery pipeline for parsing, claim-chart generation, verification, and response drafting
- Broker and result backend: Redis
- Local memory: SQLite-backed attorney preference store
- Voice service: Gradbot-based voice runtime exposed separately on port 7860
- Model routing: OpenAI-compatible local/cloud engines with optional Fastino Pioneer privacy-mode routing

## Core Workflows

### 1. Office Action to Structured Work Product

1. Upload an Office Action and patent specification.
2. PatentFlow extracts text and identifies claim/prior-art context.
3. The worker generates:
   - Art. 56 claim chart
   - Art. 123(2) terminology review
   - attorney-reviewable draft response
4. The frontend polls task status and renders the structured result.

### 2. Claim Chart Generation

PatentFlow converts claims and cited prior art into reviewable rows:

- feature identifier
- claim limitation
- prior-art disclosure mapping
- assessment: Yes / No / Partial
- attorney remarks and reasoning

The chart is designed as a first-pass prosecution work product, not a final legal conclusion.

### 3. Translation and Terminology Review

The verifier flags potential Art. 123(2) and terminology risks, including:

- semantic drift between source and target text
- ambiguous claim language
- EPO style issues such as open-ended terms, unclear functional language, and risky wording shifts

### 4. Attorney Memory

PatentFlow stores attorney or firm preferences locally and injects them into generation contexts. Typical examples:

- preferred response tone
- examiner-specific strategy notes
- terminology and phrasing conventions
- firm drafting preferences

### 5. Voice Session

The voice workflow is intentionally embedded in the main PatentFlow UI. It does not open a separate Gradium room, iframe, or external chat window.

- `Start the session` initializes a voice context and requests microphone access
- browser voice runtime connects to `ws://localhost:7860/ws/chat`
- Gradbot handles streaming STT, model calls, and TTS
- `End the session` closes the websocket, stops audio resources, and clears server-side context

Worker and AudioWorklet assets are served same-origin from the frontend under `/voice-runtime/` to avoid browser Worker cross-origin restrictions.

### 6. Fastino Pioneer Privacy Mode

Fastino integration is opt-in and non-invasive.

- Default mode preserves the existing public or online LLM workflow
- Privacy mode routes supported analysis calls through a Fastino Pioneer model
- If Fastino is unavailable, times out, or returns invalid JSON, the router logs the failure and falls back to the existing route
- Secrets remain local and must not be committed

Relevant environment variables:

```env
ENABLE_LOCAL_PRIVACY_MODE=false
FASTINO_API_KEY=
FASTINO_BASE_URL=https://api.pioneer.ai/v1
FASTINO_MODEL_ID=59d36fbf-6e40-4e07-96d5-617d321842e8
```

## API Overview

### Core API

- `GET /health`
  - Service health check
- `POST /api/upload`
  - Extract text from PDF, DOCX, or TXT uploads
- `POST /api/generate`
  - Enqueue the full prosecution pipeline
- `GET /api/status/{task_id}`
  - Retrieve queue state, progress metadata, and final result
- `POST /api/generate-chart`
  - Generate a claim chart directly
- `POST /api/verify-translation`
  - Run translation or terminology verification directly

### Memory API

- `GET /api/memory/{attorney_id}`
- `POST /api/memory/{attorney_id}`
- `POST /api/memory/add`

### EPO Integration

- `POST /api/epo/ingest`
  - Optional EPO OPS / Register ingestion path

### Voice API

- `GET /health` on the voice server
- `POST /start_bot`
- `POST /end_session/{session_id}`
- `WS /ws/chat`

## Local Development

### 1. Environment

```bash
cp .env.example .env
```

Configure Redis, API base URL, model routing, and optional EPO/Fastino credentials in `.env`.

Do not commit `.env` or real API keys.

### 2. Backend API

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Redis

```bash
redis-server
```

### 4. Celery Worker

```bash
source .venv/bin/activate
celery -A src.celery_app.celery_app worker -l info --concurrency=1 --prefetch-multiplier=1
```

### 5. Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run build
python3 -m http.server 3000 --bind 0.0.0.0 --directory out
```

### 6. Voice Server

```bash
python3 -m venv .voice-venv
source .voice-venv/bin/activate
pip install -r voice_pipeline/requirements.txt
python -m voice_pipeline.server
```

Open the workspace at:

```text
http://localhost:3000
```

## Docker Development

```bash
docker compose config
docker compose build
docker compose up
```

The default compose topology includes:

- frontend
- api
- redis
- worker

Confirm host port availability before starting compose services.

## Verification Checklist

Before presenting the workspace as ready:

```bash
curl -sS http://localhost:8000/health
redis-cli ping
celery -A src.celery_app.celery_app inspect ping --timeout=3
cd frontend && NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run build
```

For voice:

```bash
curl -sS http://localhost:7860/health
curl -I http://localhost:3000/voice-runtime/decoderWorker.min.js
```

Expected outcomes:

- API health returns `PatentFlow Engine is online`
- Redis returns `PONG`
- Celery returns at least one online node
- frontend build completes successfully
- voice runtime assets are served from the frontend origin

## Security and Privacy Notes

- PatentFlow is designed for local-first deployment and controlled inference routing.
- Uploaded documents are processed through the configured local stack.
- Attorney memory is stored locally in SQLite.
- Voice sessions are ephemeral and should not persist audio by default.
- Fastino credentials and model keys must remain in `.env` or a secure local secret store.
- Public repositories should omit proprietary prompts, private dictionaries, production client data, and model weights.

## Repository Hygiene

Do not commit:

- `.env` or API keys
- model weights or cache directories
- local virtual environments
- generated build artifacts unless explicitly required
- client confidential documents or real Office Actions

## Intended Use

PatentFlow is intended for professional evaluation, internal prototyping, and controlled deployment patterns for patent prosecution workflows. Outputs require review by a qualified patent professional before use in any legal filing or client advice.
