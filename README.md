# 🌊 PatentFlow: Local-First AI Assistant for European Patent Attorneys

**PatentFlow** is a privacy-centric, RAG-driven workflow automation tool designed for European Patent Attorneys and IP professionals.
It automates parsing EPO Office Actions, retrieves relevant defensive arguments from a localized offline knowledge base, and drafts standard-compliant responses—while ensuring **zero client data leakage** to public LLMs.

## 🎯 The Core Problem: Privacy vs. AI Efficiency

Patent law firms handle highly confidential data (undisclosed inventions, internal prosecution strategies).
Using public cloud-based LLMs for drafting may breach confidentiality requirements.
Moreover, generic LLMs often lack EPC-specific rigor (e.g., Art. 56 inventive step / Art. 84 clarity).

## 💡 The PatentFlow Solution (Hybrid Architecture)

PatentFlow employs a strict **Data Routing Strategy** to balance intelligence with absolute privacy:

- **Confidential data** (drafts, internal strategies, client specs): processed offline using local LLMs (e.g., Ollama) and local vector databases (ChromaDB).
- **Public data** (prior art, standards, 3GPP docs): can be routed to online APIs for speed (reserved interface).

## Privacy & Security (non-negotiable)

- **Do not commit secrets**: keep your `.env` local.
- **Do not commit private legal documents**: store them only in `private_knowledge_base/`.
- This project should be used in a way that **does not upload confidential legal text to external services**.

The repository includes a `.gitignore` that excludes:

- `venv/`
- `.env`
- `private_knowledge_base/`

## ✨ Key Features

- **Smart OA parsing**
  - Extracts Application No, cited documents (D1/D2), EPC Articles, and Examiner details from EPO communications.
- **Institutional-memory RAG**
  - Searches a local database of historical responses to retrieve the best defense logic.
- **Examiner analytics (retrieval bias)**
  - Adjusts retrieval ranking based on the specific examiner’s historically accepted argument patterns.
- **CN→EN legal translation (CN to EPO)**
  - Aligns Chinese text to EPO-style legal English terminology (e.g., “包括”→“comprising”, “其中”→“wherein”, “被配置为”→“configured to”).
  - **Precision CN-EN Dual-Verification Table**
    - Dual-Language Alignment: generates professional side-by-side comparison tables (Markdown/CSV) optimized for Chinese priority documents.
    - Back-Translation (Re-verification): implements a "closed-loop" verification by translating the generated English claims back into Chinese to spot semantic drifts (e.g., ensuring "comprising" maps back to the open-ended "包括").
    - Article 123(2) Risk Mitigation: helps verify that the English translation remains strictly within the original disclosure of the Chinese priority application.
- **Automated drafting**
  - Generates structured response drafts and can integrate “basis in the application as filed” excerpts.

## 🧩 Modules (selected)

### 1) CN→EN translation with alignment + back-translation QA

The translation module is implemented in `src/translator.py` (`PatentTranslator`).

- It is optimized for CN→EPO drafting.
- It produces a lawyer-friendly **three-column** Markdown table:
  - **Original CN**
  - **Target EN (EPO-style legal English)**
  - **Back-trans CN** (reverse translation for consistency checking)

Back-translation is used as a lightweight QA signal: if key verbs differ (e.g., “包括/连接/配置为/指示”), the table will include a mismatch marker.

Run the demo:

```bash
source venv/bin/activate
python3 tests/test_translator.py
```

### 2) LegalLanguageAudit (professional legal phrasing)

`src/report_generator.py` contains `LegalLanguageAudit`, which post-processes drafts to:

- Replace non-professional phrases (e.g., “I think”, “The examiner says”) with formal equivalents.
- Enforce EPC-appropriate openers (e.g., “Regarding Article 56 EPC, ...”).
- Enrich D1/D2 mentions with citation details when available.

### 3) Examiner-aware retrieval bias

`src/vector_store.py` stores template metadata (e.g., `#Examiner: ...`) during ingestion and biases retrieval for examiner-matched templates.

To ingest mock templates:

```bash
source venv/bin/activate
python -m src.vector_store --kb data/mock_private_knowledge_base
```

### 4) Basis extraction (application as filed)

When you pass a specification (`--spec_path`), the pipeline extracts basis paragraphs (e.g., `[0015]`) using keyword matching/fuzzy scoring (`src/data_processor.py`).

```bash
bash scripts/run_pipeline.sh data/raw/sample_oa.txt data/raw/my_spec.txt
```

### 5) Agent skills (claim chart / claim classification)

`src/skills.py` contains lightweight, composable “agent skills” for patent prosecution tasks:

- `generate_claim_chart(claim_text, prior_art_text)`
  - Produces a feature-by-feature chart skeleton for Art. 56 EPC analysis.
- `classify_claim(claim_text)`
  - Classifies a claim as Method/Apparatus and makes a simple independent/dependent guess.

Run tests:

```bash
source venv/bin/activate
python3 -m pytest -q tests/test_skills.py
```

## 📝 New copy (TODO)

Paste your new marketing / positioning copy here and we will integrate it into the README.

## Project structure

- `src/` : source code
- `config/` : configuration files
- `data/` : public / non-sensitive data
- `private_knowledge_base/` : **sensitive** local-only legal documents (never commit)

For development and demos, this repository also uses:

- `data/mock_private_knowledge_base/` : mock templates safe to commit (for local testing only)

## Quick start

### 1) Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2) Install dependencies

This template currently uses:

- `requests`
- `python-dotenv`
- `pymupdf`

Install them:

```bash
pip install -U pip
pip install -r requirements.txt
```

### 3) Configure environment variables

Copy the example file and edit it:

```bash
cp .env.example .env
```

#### EPO (optional)

By default, EPO is disabled in `.env.example`:

- Set `EPO_ENABLED=true`
- Add your own `EPO_CONSUMER_KEY` and `EPO_CONSUMER_SECRET`

If you do not have EPO credentials yet, keep EPO disabled and the project should still run (EPO-related calls will be blocked).

#### Offline LLM (abstract interface)

This repository intentionally does **not** mandate a specific local LLM stack.

Configure:

- `LLM_PROVIDER` : identifier for your local stack (e.g. `ollama`, `llamacpp`, `vllm`, `local`)
- `LLM_BASE_URL` : where your local model server listens
- `LLM_MODEL` : model name / id used by your server

You are responsible for deploying your own offline model server.

## EPO client behavior

The EPO client (`src/epo_client.py`) is designed to be safe by default:

- If `EPO_ENABLED=false` **or** credentials are missing, the client becomes **disabled**.
- When disabled, it will **not** attempt to fetch tokens or call EPO.
- If you call `request(...)` while disabled, it raises a clear error telling you what to configure.

## Notes

- This repository is a guide/template. You are expected to adapt it to your environment and security requirements.

## 🚀 Quick Start & Demo (RAG drafting)

### 1) Ingest templates into local ChromaDB (mock KB)

```bash
source venv/bin/activate
python -m src.vector_store --kb data/mock_private_knowledge_base
```

### 2) Run the end-to-end pipeline

```bash
bash scripts/run_pipeline.sh data/raw/sample_oa.txt
```

Output:

- `data/raw/sample_oa.info.json`
- `data/raw/sample_oa.results.json`
- `data/output/Response_<ApplicationNo>_Draft.txt`

### 3) (Optional) Include specification basis excerpts

```bash
bash scripts/run_pipeline.sh data/raw/sample_oa.txt data/raw/my_spec.txt
```

### 4) Test CN→EN aligned translation

```bash
source venv/bin/activate
python3 tests/test_translator.py
```
