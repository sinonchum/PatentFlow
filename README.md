# ⚖️ PatentFlow — Privacy-Aware Agentic Patent Prosecution Workspace

![UI: Next.js](https://img.shields.io/badge/UI-Next.js-black)
![API: FastAPI](https://img.shields.io/badge/API-FastAPI-009688)
![Queue: Celery](https://img.shields.io/badge/Queue-Celery-37814A)
![Broker: Redis](https://img.shields.io/badge/Broker-Redis-DC382D)
![Memory: SQLite](https://img.shields.io/badge/Memory-SQLite-003B57)
![LLM: Local](https://img.shields.io/badge/LLM-Local%20LLM-6B7280)
![LLM: Kimi](https://img.shields.io/badge/LLM-Kimi%20%2F%20Moonshot-7C3AED)
![Voice: Pipecat](https://img.shields.io/badge/Voice-Pipecat-2563EB)
![TTS: Minimax](https://img.shields.io/badge/TTS-Minimax-10B981)

**PatentFlow** is an enterprise-grade, privacy-aware Document Processing Workspace designed for **European Patent Attorneys**. It targets the realities of prosecution work:

- **Art. 123(2) EPC** risk (added matter) where wording choices can be fatal
- **Art. 56 EPC** inventive-step mapping where semantic interpretation matters
- **Client confidentiality** where “cloud by default” is not acceptable
- **Real-time attorney interaction** through a voice-first AI copilot

PatentFlow is not a generic chatbot. It is a structured, auditable, attorney-in-the-loop prosecution workspace that combines live EPO data, local/private LLM routing, optional high-quality API reasoning, and real-time voice interaction.

Built by an IP professional, for IP professionals.

---

## Why PatentFlow

### 1) Legal accuracy under institutional constraints
Patent prosecution is not “generic writing.” It is **risk management**:

- A single phrasing shift can trigger an Art. 123(2) issue
- Inventive-step reasoning requires structured, repeatable mapping
- Prior-art analysis requires grounded evidence, not hallucinated citations
- Quality and traceability matter more than “chatty” UX

PatentFlow focuses on structured outputs such as claim charts, translation risk checks, and draft prosecution responses that remain reviewable by a qualified patent attorney.

### 2) Privacy-aware operation for client confidentiality
PatentFlow is designed around **privacy-aware LLM routing**:

- Sensitive client files can be routed to local LLMs
- Offline / air-gapped deployment remains possible for core workflows
- Non-sensitive reasoning can use Kimi / Moonshot API via OpenAI-compatible mode
- Local persistence for attorney-specific preferences
- No sensitive client data should be written to logs or external telemetry

The principle is simple:

> Sensitive data stays local. Non-sensitive reasoning can use high-quality API models.

### 3) Real-time voice copilot for prosecution work
PatentFlow is not only a document automation tool. It also includes a **voice-first AI copilot** built with a Pipecat pipeline.

Attorneys can speak naturally to the system and ask questions such as:

- “What is the main difference between Claim 1 and D1?”
- “Can we argue that D1 lacks dynamic TDRA configuration?”
- “Check whether this amendment creates Art. 123(2) risk.”
- “Rewrite this response in a more formal EPO attorney style.”

The voice copilot is designed to make prosecution review more interactive, especially during first-pass analysis, claim chart inspection, and draft refinement.

### 4) Enterprise UX: minimal, information-dense, institutional
The UI follows a **Bloomberg Terminal-style** aesthetic:

- High signal density
- Subtle controls
- Low-friction review of structured outputs
- Calm, traceable progress for long-running legal analysis tasks

---

## Legal Disclaimer & Usage Policy

> **The attorney is the pilot; AI is the co-pilot.**

PatentFlow is a specialized productivity tool for patent prosecution workflows. It assists with document analysis, prior-art comparison, claim chart generation, translation checks, and draft response preparation.

It does **not** replace the professional judgment, legal advice, or strategic responsibility of a qualified patent attorney. All outputs are designed for attorney review, validation, and final approval before any professional or procedural use.

---

## Trade Secret / Black Box Disclaimer

Specific system prompts, proprietary dictionaries, attorney-style rules, and heuristic parsing algorithms are **intentionally omitted** from this public repository to protect intellectual property.

PatentFlow exposes stable interfaces and deterministic boundaries while keeping core prompt logic and proprietary linguistic assets internal.

---

## System Architecture

```mermaid
graph TD
    subgraph Frontend [Next.js Enterprise UI - Port 3000]
        UI[Workspace Dashboard]
        UI -->|POST /api/generate| API[FastAPI Gateway :8000]
        UI -->|GET /api/status/:id| API
        UI -->|GET/POST /api/memory/*| API
        UI -->|Voice Session| VoiceClient[Voice Copilot UI]
    end

    subgraph Backend [FastAPI + Celery Workers]
        API -->|Enqueue Tasks| Broker[(Redis Broker :6379)]
        API -->|Fetch Results| BackendRedis[(Redis Result Backend)]
        Broker -->|Consume| Worker[Celery Worker]

        Worker --> Skills[Skills Interface]
        SQLite[(Local Profile DB)] --> Skills
    end

    subgraph ExternalData [Optional Data Sources]
        EPO[EPO OPS / Register API] -->|Prior Art Retrieval| API
    end

    subgraph LLMRouting [Privacy-Aware LLM Runtime]
        Skills --> Router[LLM Router]
        Router -->|Sensitive Files| LocalLLM[(Local LLM / Ollama)]
        Router -->|Non-Sensitive Tasks| Kimi[Kimi / Moonshot API]
    end

    subgraph Voice [Pipecat Voice Copilot]
        VoiceClient --> DailyIn[DailyTransport.input]
        DailyIn --> VAD[SileroVADAnalyzer]
        VAD --> STT[WhisperSTTService<br/>Local Faster Whisper]
        STT --> UserCtx[LLMUserContextAggregator]
        UserCtx --> VoiceLLM[OpenAILLMService<br/>Kimi / Moonshot Compatible]
        VoiceLLM --> TTS[MinimaxTTSService<br/>Preferred]
        TTS --> DailyOut[DailyTransport.output]
        DailyOut --> AssistantCtx[LLMAssistantContextAggregator]
    end
