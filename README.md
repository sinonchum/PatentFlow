# ⚖️ PatentFlow: Async Patent Prosecution Workspace

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Frontend: Next.js](https://img.shields.io/badge/Frontend-Next.js%20%7C%20Tailwind-black)
![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI%20%7C%20Celery-green)
![Queue: Redis](https://img.shields.io/badge/Queue-Redis-red)
![Privacy: 100% Local](https://img.shields.io/badge/Privacy-100%25%20Local%20LLM-red)

**PatentFlow** is an enterprise-grade, privacy-first Document Processing Workspace with **async task queue architecture**. Designed for European Patent Attorneys, it handles concurrent document processing via Celery + Redis while maintaining 100% offline operation.

*Built by an IP professional, for IP professionals.*

---

## 💡 The "Why" (Design Philosophy)

After four years working as a Patent Assistant handling Telecommunications and Optics files, I observed three major bottlenecks:

1. **Client Confidentiality**: Public cloud AI is strictly prohibited for unpublished patent drafts.
2. **Legal Hallucinations**: Standard LLMs fail to respect rigid EPO frameworks (Art. 123(2), Art. 56).
3. **Concurrency & OOM**: Heavy LLM and document parsing tasks can timeout or exhaust memory when run synchronously.

**PatentFlow** solves this with:
- **100% offline local LLM** constrained by deterministic Python Agent Skills
- **Async task queue** (Celery + Redis) for concurrent request handling
- **Real-time progress tracking** with queue position display
- **Minimalist Next.js UI** for heavy document reading

---

## 🏗️ System Architecture

```mermaid
graph TD
    subgraph Frontend [Next.js 16 + Tailwind - Port 3000/3001]
        UI[Workspace Dashboard] -->|POST /api/generate| API[FastAPI Backend :8000]
        UI -->|GET /api/status/{task_id}| API
        UI -.->|Renders| View1[Claim Chart Tab]
        UI -.->|Renders| View2[Translation Verifier Tab]
        UI -.->|Renders| View3[Response Draft Tab]
    end

    subgraph Backend [FastAPI + Celery Workers]
        API -->|Enqueue Task| Broker[(Redis Broker :6379)]
        API -->|Store Results| BackendRedis[(Redis Result Backend)]
        
        Worker1[Celery Worker #1] -->|Consume| Broker
        Worker2[Celery Worker #2] -->|Consume| Broker
        
        Worker1 -->|Execute| Skills[Agentic Skills]
        Worker2 -->|Execute| Skills
    end

    subgraph SkillsEngine [PatentFlow Core Skills]
        Skills --> S1[Dual-Verification Translator]
        Skills --> S2[Claim Chart Generator]
        Skills --> S3[Response Draft Builder]
        Skills --> LLM[(Local LLM Engine)]
    end

    style Frontend fill:#f8fafc,stroke:#cbd5e1
    style Backend fill:#f0fdf4,stroke:#86efac
    style SkillsEngine fill:#fef2f2,stroke:#fca5a5
```

### Architecture Highlights

| Component | Role | Port |
|-----------|------|------|
| **Next.js Frontend** | Attorney workspace UI | 3000/3001 |
| **FastAPI Gateway** | REST API + CORS + Task enqueue | 8000 |
| **Redis** | Message broker + Result backend | 6379 |
| **Celery Workers** | Async task processors | - |
| **Local LLM** | Offline AI inference | (internal) |

---

## ⚡ Async Task Flow

```
Browser (Next.js)
    |
    | POST /api/generate
    v
FastAPI Gateway -----> Redis Broker (ZSET queue)
    |                       |
    |                       | task picked up
    |                       v
    |<------------------ Celery Worker
    |                       |
    | GET /api/status/{id}  | execute + update_state
    | (poll every 2s)       v
    |<------------------ Redis Result Backend
```

**Key Features:**
- **Queue Position**: Redis Sorted Set (ZSET) for O(logN) position lookup
- **Progress Steps**: `Queued → Parsing → LLM → Drafting → Success`
- **Concurrent**: Multiple workers supported via `--concurrency=N`

---

## ✨ Core Capabilities (Agent Skills)

### 1. Dual-Verification Translation (Art. 123(2))

For Chinese priority applications:
- **Alignment Table**: Original CN | Target EN | Back-translated CN
- **Mismatch Detection**: Automatically flags verb-scope errors
- **Risk Highlighting**: Amber background for discrepancies

### 2. Automated Claim Charting (Art. 56)

- Maps claim features (1.1, 1.2...) to Prior Art paragraphs
- Displays real-time progress: `Queued (Position 2/5) → Parsing → LLM → Drafting`
- Supports concurrent batch processing

### 3. EPO Response Drafting

- Auto-generates formal response letters
- Editable textarea with examiner preference bias
- Export-ready formatting

---

## 🚀 Quick Start

### Option A: Local Development (No Docker)

Requires: Python 3.9+, Node.js 18+, Redis (Homebrew)

#### 1. Install Redis
```bash
brew install redis
brew services start redis
redis-cli ping  # Should return PONG
```

#### 2. Setup Python Environment
```bash
cd /path/to/PatentFlow
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 3. Start FastAPI (Terminal 1)
```bash
cd /path/to/PatentFlow
source venv/bin/activate
REDIS_URL=redis://localhost:6379/0 python3 -m uvicorn src.api:app --host 0.0.0.0 --port 8000
```

#### 4. Start Celery Worker (Terminal 2)
```bash
cd /path/to/PatentFlow
source venv/bin/activate
REDIS_URL=redis://localhost:6379/0 python3 -m celery -A src.celery_app.celery_app worker -l info --concurrency=1
```

#### 5. Start Next.js (Terminal 3)
```bash
cd /path/to/PatentFlow/frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev -- -p 3001
```

Open [http://localhost:3001](http://localhost:3001)

---

### Option B: Docker Compose (Production-like)

```bash
docker compose up --build
```

Services:
- Frontend: http://localhost:3000
- API Docs: http://localhost:8000/docs
- Redis: localhost:6379

---

## 📡 API Reference

### POST /api/generate
Enqueue a new document processing task.

**Request:**
```json
{
  "office_action_text": "...",
  "specification_text": "...",
  "examiner_preference": "Jukka Tapaninen - Telecom",
  "claim_type": "Method"
}
```

**Response:**
```json
{
  "task_id": "63627cdd-0508-4b1c-9b77-523193b51c21",
  "queue_position": 1,
  "queue_size": 3
}
```

### GET /api/status/{task_id}
Poll task status every 2 seconds.

**Response (SUCCESS):**
```json
{
  "task_id": "...",
  "state": "SUCCESS",
  "meta": {"step": "Drafting EPO Response"},
  "result": {
    "status": "success",
    "claim_chart": [...],
    "translation_table_markdown": "...",
    "response_draft": "..."
  }
}
```

---

## 🎛️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis broker + backend |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | FastAPI endpoint |

---

## 📁 Project Structure

```
PatentFlow/
├── src/
│   ├── api.py              # FastAPI endpoints + CORS
│   ├── celery_app.py       # Celery configuration
│   ├── tasks.py            # Async task definitions
│   ├── skills.py           # Claim chart generator
│   ├── translator.py       # Dual-verification logic
│   └── pipeline.py         # Document orchestration
├── frontend/
│   └── src/app/page.tsx    # Main workspace UI
├── docker-compose.yml      # Full stack orchestration
├── Dockerfile.api          # FastAPI container
├── Dockerfile.worker       # Celery worker container
└── requirements.txt
```

---

> **Disclaimer:** This project demonstrates the intersection of software engineering and patent prosecution. It assists, not replaces, the strategic judgment of a qualified European Patent Attorney.
