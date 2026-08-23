# ParcelPilot AI Support and Operations Agent

ParcelPilot is a natural-language internal support assistant built over the supplied synthetic workbook and PDF data pack. It answers account, order, ticket, policy, agreement, and operational questions with structured evidence, controlled access, and confirmation-gated escalation actions.

## Problem

Support teams need fast answers that combine operational records with the right current policy or customer agreement. They also need to notice important operational failures before a customer asks, without allowing an AI model to execute unsafe actions.

## Features

- Gemini-powered LangGraph investigation agent
- Parameterized SQLite account, order, and ticket lookups
- Page-aware PDF extraction and persistent ChromaDB retrieval
- Current/deprecated document metadata and source authority
- Python-enforced tool authorization and audit logging
- Human confirmation workflow for escalation actions
- Deterministic proactive issue detection
- Streamlit chat, evidence, data, tool activity, and confirmation UI

## Architecture

```text
Streamlit -> UI integration -> LangGraph agent -> controlled tools
                                      -> authorization -> SQLite / ChromaDB
                                      -> confirmation API -> escalation action
```

See [docs/architecture.md](docs/architecture-note.md) for the detailed design and Mermaid diagram.

## Technology stack

Python 3.11+, Streamlit, LangGraph, LangChain, Gemini via `langchain-google-genai`, pandas, SQLite, PyMuPDF, Sentence Transformers, ChromaDB, Pydantic, and pytest.

## Repository structure

- `app.py`: thin Streamlit entrypoint
- `src/agent/`: LangGraph state, graph, prompts, routing, confirmation
- `src/tools/`: controlled document, data, monitoring, and action tools
- `src/data/`: workbook loader, SQLite manager, and schemas
- `src/rag/`: PDF ingestion, chunking, embeddings, and retrieval
- `src/security/`: mock users, permissions, and audit logging
- `src/monitoring/`: deterministic proactive issue detector and model
- `src/ui/`: Streamlit integration helpers
- `data/`: supplied workbook, PDFs, and generated vector data
- `scripts/`: database/data loading scripts
- `tests/`: focused and regression tests
- `docs/`: evaluation, architecture, product, demo, and submission notes

## Setup

```powershell
cd C:\Dell\parcelpoint_ai_agent\parcelpoint_ai_agent
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set the local Gemini credential:

```text
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.1-flash-lite
LLM_API_KEY=your_api_key_here
```

`python-dotenv` loads the repository-root `.env` automatically. Non-empty process environment variables take precedence. `.env` is ignored by Git; never put a real key in source, tests, or documentation.

## Initialize data

```powershell
python scripts/load_data.py
```

This loads `data/ParcelPilot_Assessment_Data.xlsx` into `database/parcelpilot.db`. PDF ingestion is repeatable and persists ChromaDB under `data/processed/chroma`.

## Run the application

```powershell
streamlit run app.py
```

Use the sidebar mock user selector, chat input, Evidence/Data expanders, Tools used list, and Scan for Issues control. The UI never accesses SQLite or ChromaDB directly.

## Authorization and confirmation

Mock users receive fixed permissions from `src/security/auth.py`. Each protected tool checks authorization in Python before backend access. Escalation requests create a pending `CONF-*` confirmation; only `confirm_action()` can execute the action after ownership, permission, TTL, and single-use checks. The agent and UI never execute escalations automatically.

## RAG and source reliability

PDF extraction preserves filename and page. Chunks retain source metadata, including current/deprecated status, account, authority, and retrieval distance. Customer agreements have the highest applicable authority, current policy/SOP and product documentation provide general guidance, and historical ticket resolutions remain context rather than policy. Retrieval preserves competing evidence; comparison is a separate business-rule concern.

## Proactive monitoring

The read-only detector identifies cancellation after pickup, carrier-at-fault missed pickup, broad operational failure tickets, and multiple issues for one account. Findings include deterministic severity, affected IDs, and exact structured evidence. Recommendations remain subject to the same confirmation workflow.

## Tests

```powershell
pytest -q
```

## Known limitations

- Mock authentication is not production identity management.
- Confirmation state is in memory and is not durable across process restarts.
- The supplied synthetic data is a snapshot, not a live operational system.
- Local embedding model startup may require a model download.
- Gemini access requires a valid local API key and network connectivity.
- A production deployment would need durable audits, monitoring schedules, integrations, and outcome-labelled evaluation data.

## Future roadmap

Priorities are durable confirmation/audit storage, production identity, monitoring precision evaluation, richer triage views, approved notifications, and verified first-contact resolution measurement.

## AI tool usage disclosure

This repository was developed with AI coding assistance in VS Code/GitHub Copilot. Human review, local inspection, tests, and manual verification were used to validate generated changes. No real API key or secret was provided to the coding assistant or committed to the repository.

## Documentation
- [Architecture Note](docs/architecture.md)
- [Product Note](docs/product.md)
