# ⚖️ PatentFlow: Offline-First Patent Prosecution Workspace

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Frontend: Next.js](https://img.shields.io/badge/Frontend-Next.js%20%7C%20Tailwind-black)
![Backend: Python](https://img.shields.io/badge/Backend-Python%20%7C%20FastAPI-green)
![Privacy: 100% Local](https://img.shields.io/badge/Privacy-100%25%20Local%20LLM-red)

**PatentFlow** is an enterprise-grade, privacy-first Document Processing Workspace designed specifically for European Patent Attorneys. It bridges the gap between raw technical specifications (e.g., 3GPP Telecom standards) and strict EPC legal requirements.

*Built by an IP professional, for IP professionals.*

## 💡 The "Why" (Design Philosophy)

After four years of working as a Patent Assistant handling Telecommunications and Optics files, I observed two major bottlenecks in integrating AI into daily firm operations:
1. **Client Confidentiality**: Public cloud AI (like ChatGPT or Claude) is strictly prohibited for unpublished patent drafts and sensitive client communications.
2. **Legal Hallucinations**: Standard LLMs fail to respect rigid EPO frameworks (e.g., Article 123(2) added subject-matter limits, Article 56 inventive step logic).

**PatentFlow** solves this by running a **100% offline local LLM** constrained by deterministic Python "Agent Skills." The tool is wrapped in a minimalist, high-density Next.js UI tailored for heavy document reading, avoiding the inefficient "chatbot" paradigm.

---

## 🏗️ System Architecture

PatentFlow employs a decoupled architecture: a sophisticated React frontend for the attorney workspace, and a robust Python backend for document parsing and local AI orchestration.

```mermaid
graph TD
    subgraph Frontend [Next.js Enterprise UI - Client Side]
        UI[Workspace Dashboard] -->|REST API| Gateway[FastAPI Backend]
        UI -.->|Renders| View1[Claim Chart View]
        UI -.->|Renders| View2[Translation Verifier]
    end

    subgraph Backend [Python AI Engine - Local Server]
        Gateway --> Engine[PatentFlow Core Orchestrator]
        Engine --> PDF[Document Parser]
        Engine --> Skills[Agentic Skills Engine]
        
        Skills --> S1[Dual-Verification Module]
        Skills --> S2[Claim Chart Generator]
        Skills --> S3[Telecom Acronym Decoder]
    end

    subgraph Privacy Layer [100% Offline Infrastructure]
        Skills --> LLM[(Local LLM - Air-gapped)]
        Engine --> VectorStore[(Local Vector DB)]
    end

    style Frontend fill:#f8fafc,stroke:#cbd5e1
    style Backend fill:#f0fdf4,stroke:#86efac
    style Privacy Layer fill:#fef2f2,stroke:#fca5a5
```
