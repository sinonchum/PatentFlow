# ⚖️ PatentFlow: Async Patent Prosecution Workspace

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Frontend: Next.js](https://img.shields.io/badge/Frontend-Next.js%20%7C%20Tailwind-black)
![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI%20%7C%20Celery-green)
![Queue: Redis](https://img.shields.io/badge/Queue-Redis-red)
![Privacy: 100% Local](https://img.shields.io/badge/Privacy-100%25%20Local%20LLM-red)

**PatentFlow** is an enterprise-grade, privacy-first Document Processing Workspace featuring a robust **asynchronous task queue architecture**. Designed for European Patent Attorneys, it handles concurrent heavy-document processing via Celery + Redis while strictly maintaining 100% offline, air-gapped operation.

*Built by an IP professional, for IP professionals.*

---

## 💡 The "Why" (Design Philosophy)

After four years of working as a Patent Assistant handling Telecommunications and Optics files, I observed three major bottlenecks in legal-tech adoption:

1. **Client Confidentiality**: Public cloud AI (ChatGPT, Claude) is strictly prohibited for unpublished patent drafts.
2. **Legal Hallucinations**: Standard LLMs fail to respect rigid EPO frameworks (e.g., Art. 123(2) added matter, Art. 56 inventive step).
3. **Concurrency & OOM**: Heavy local LLM inference and regex parsing can easily cause HTTP timeouts or exhaust GPU memory (OOM) when multiple attorneys use the tool synchronously.

**PatentFlow** solves this with:
- **100% offline local AI** constrained by deterministic Python Agent Skills.
- **Async task queuing** (Celery + Redis) to gracefully handle firm-wide concurrent requests.
- **Real-time UX** via an optimistic Next.js UI that prevents user anxiety during long LLM generations.

---

## 🏗️ System Architecture

PatentFlow employs a decoupled microservices architecture, isolating the Next.js presentation layer from the heavy Python AI engine.

```mermaid
graph TD
    subgraph Frontend [Next.js Enterprise UI - Port 3000]
        UI[Workspace Dashboard] -->|POST /api/generate| API[FastAPI Gateway :8000]
        UI -->|GET /api/status/:id| API
    end

    subgraph Backend [FastAPI + Celery Workers]
        API -->|Enqueue Task| Broker[(Redis Broker :6379)]
        API -->|Fetch Result| BackendRedis[(Redis Backend)]
        
        Worker1[Celery Worker #1] -->|Consume| Broker
        Worker2[Celery Worker #2] -->|Consume| Broker
        
        Worker1 -->|Execute| Skills[Agentic Skills Engine]
        Worker2 -->|Execute| Skills
    end

    subgraph Privacy Layer [100% Offline AI Infrastructure]
        Skills --> S1[Dual-Verification Module]
        Skills --> S2[Claim Chart Generator]
        Skills --> LLM[(Local LLM - Air-gapped)]
    end

    style Frontend fill:#f8fafc,stroke:#cbd5e1
    style Backend fill:#f0fdf4,stroke:#86efac
    style Privacy Layer fill:#fef2f2,stroke:#fca5a5
```

---

## ✨ Core Capabilities (Agent Skills)

> **Note**: Specific system prompts, proprietary 3GPP mapping dictionaries, and core heuristic regex parsing algorithms are intentionally omitted from this public repository to protect the underlying intellectual logic. The demonstrable features include:

### 1. Dual-Verification Translation (Art. 123(2) Mitigation)
Generates a strict side-by-side alignment: Original CN | Target EN | Back-translated CN.

![Translation Verifier](docs/screenshots/verifier.png)

**Logic**: Automatically flags verb-scope mismatches (e.g., "comprising" vs "consisting of") with amber highlights to prevent unallowable amendments.

### 2. Automated Claim Charting (Art. 56 Analysis)
Maps specific claim features (1.1, 1.2...) to identified paragraphs in Prior Art (D1).

![Claim Charting progress](docs/screenshots/claim_chart.png)

Processes concurrently through the Celery worker pool, displaying real-time granular progress (Parsing → LLM Matching → Drafting).

### 3. EPO Response Drafting
Auto-generates formal response letters based on predefined examiner biases.

![EPO Response Drafting](docs/screenshots/response_draft.png)

Exports to clean, standard-compliant formatting.

---

## 🚀 Quick Start (Local Deployment)

### Option A: Docker Compose (Recommended for Intranet)
The entire asynchronous stack can be spun up using Docker.

```bash
docker compose up --build -d
```

- **Frontend**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs

### Option B: Manual Startup (For Development)
**Requires**: Python 3.9+, Node.js 18+, Redis instance.

```bash
# 1. Start Redis Server
redis-server

# 2. Start FastAPI Gateway
REDIS_URL=redis://localhost:6379/0 uvicorn src.api:app --host 0.0.0.0 --port 8000

# 3. Start Celery Worker
REDIS_URL=redis://localhost:6379/0 celery -A src.celery_app.celery_app worker -l info

# 4. Start Next.js Frontend
cd frontend && npm install && NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

---

## 📁 Project Structure

```plaintext
PatentFlow/
├── src/
│   ├── api.py              # FastAPI endpoints + CORS
│   ├── celery_app.py       # Celery & Redis configuration
│   ├── tasks.py            # Async LLM task definitions
│   └── skills.py           # Claim chart generator (Core logic omitted)
├── frontend/
│   └── src/app/page.tsx    # Optimistic Workspace UI
├── docker-compose.yml      # Microservices orchestration
└── requirements.txt
```

---

*Disclaimer: This project demonstrates the intersection of software engineering and patent prosecution. It is designed to assist, not replace, the strategic judgment of a qualified European Patent Attorney.*
