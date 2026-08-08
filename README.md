# Retail Sentiment Intelligence

Retail Sentiment Intelligence is a local-first platform for ingesting Walmart-related Reddit discussions, running trust-aware sentiment and aspect analysis, and surfacing actionable issues in a React dashboard.

It includes:
- FastAPI backend with REST + WebSocket endpoints
- React + Vite frontend for operational workflows
- Scheduled ingestion/analysis pipeline
- Trust gating and priority-based review queue
- Alerting and lifecycle management
- Optional Slack delivery via Concord (Walmart internal)

## What the System Does

1. Ingests posts and comments from Walmart-related subreddits.
2. Cleans, deduplicates, and filters content.
3. Runs trust scoring and sentiment/aspect analysis.
4. Aggregates trends and detects alert conditions.
5. Powers dashboard workflows for review, lifecycle transitions, and response drafting.

## Tech Stack

- Backend: Python, FastAPI, Uvicorn
- Frontend: React, TypeScript, Vite, Tailwind, Recharts
- Storage: SQLite (local default) or Azure Cosmos DB
- Models:
  - Sentiment: ModernBERT (local fine-tuned checkpoint) with fallback
  - Aspect tagging: DeBERTa zero-shot
  - Vision captioning: Ollama (`gemma3:4b`, fallback `llava:7b`)
  - Reply drafting: Ollama (`mistral:7b-instruct`)

## Repository Layout

- `src/` core backend code (pipeline, API, storage, alerts, trust, notifications)
- `frontend/` React dashboard
- `config/` pipeline and model configuration
- `data/` local database, benchmark files, cache
- `scripts/` utilities, scheduling, backfill, evaluation helpers
- `tests/` core and integration tests
- `docs/` architecture, flow docs, and supporting project documentation

## Prerequisites

- macOS/Linux shell (project currently used on macOS)
- Python 3.10+
- Node.js 18+ (with `npm` / `npx`)
- Optional but recommended for full feature set:
  - Ollama installed and available on PATH
  - A Python environment with `transformers` + `torch` for pipeline execution

## Quick Start

### 1. Clone and install dependencies

```bash
git clone <your-repo-url>
cd "Retail Sentiment Intelligence"

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
```

### 3. Start all services

```bash
./start.sh
```

The script starts:
- API server (default `http://localhost:8001`)
- Frontend dev server (default `http://localhost:3001`)
- Scheduler (`scripts/scheduler.py`) unless `SKIP_SCHEDULER=1`

### 4. Service controls

```bash
./start.sh status
./start.sh stop
```

Logs are written to `logs/`.

## Environment Variables (Key)

Copy from `.env.example` and set only what you need for your mode.

### Core
- `FETCHER_PROVIDER` (`arctic_shift` or `praw`)
- `INGESTION_INTERVAL_MINUTES`
- `BACKFILL_DAYS`
- `TRUST_THRESHOLD`
- `CONFIDENCE_THRESHOLD`

### LLM / model routing
- `LLM_PROVIDER` (`huggingface`, `openai`, `azure_openai`, `llm_gateway`, `local`)
- `LLM_MODEL`
- `WMT_LLM_GATEWAY_URL`
- `WMT_LLM_GATEWAY_KEY`

### Azure OpenAI (if used)
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_KEY`
- `AZURE_OPENAI_API_VERSION`
- `AZURE_OPENAI_DEPLOYMENT`

### Concord + Slack (if used)
- `CONCORD_API_TOKEN`
- `CONCORD_API_URL`
- `CONCORD_ORG`
- `CONCORD_PROJECT`
- `CONCORD_REPO`
- `CONCORD_ENTRY_POINT`
- `CONCORD_ACTIVE_PROFILES`
- `CONCORD_FOOTER`

### Dashboard runtime
- `DASHBOARD_HOST`
- `DASHBOARD_PORT`
- `API_PORT` (used by `start.sh`, defaults to `8001`)
- `FRONTEND_PORT` (used by `start.sh`, defaults to `3001`)

## Main Dashboard Workflows

### Brand Health Overview (P0)
- Snapshot of volume, trust, sentiment, aspects, and trend windows.
- Macro segmentation support (Walmart vs competitor).

### Review & Validate (P0)
- Prioritized queue for negative content (P1/P2 visibility).
- Validation actions and response drafting.
- Supports multiple draft modes (including GPT and Mistral-backed internal action note outputs).

### Post Lifecycle (operational)
- Lifecycle states:
  - `new`
  - `acknowledged`
  - `reply_sent`
  - `issue_fixed`
  - `resolved`
- Transition modal requires action context for closure-oriented states and supports team assignment.

### Alert Feed (P1)
- Rule-driven alerts (sentiment crash, competitor negative pressure, etc.).
- Includes enriched context where available (group/subreddit/macro information).

## Running Without `start.sh` (Manual)

Backend:

```bash
source .venv/bin/activate
python -m src.dashboard.api
```

Frontend:

```bash
cd frontend
npm run dev -- --port 3001
```

Scheduler:

```bash
source .venv/bin/activate
python scripts/scheduler.py
```

## Testing

```bash
source .venv/bin/activate
pytest
```

Current test suite lives in `tests/`.

## Troubleshooting

### API 500 on dashboard calls
- Check backend logs in `logs/api.log`.
- Confirm the local DB exists and is readable (`data/local.db`).
- Verify model/runtime dependencies in the interpreter used by the pipeline.

### Frontend cannot reach backend
- Ensure API is running on the expected port (`API_PORT`, default 8001).
- Confirm frontend is pointing to `/api` proxy path and dev server is up.

### Slack/Concord notifications not visible in channel
- Successful Concord process creation does not guarantee channel visibility.
- Validate Slack channel name, workspace, app/bot permissions, and posting rights.
- Verify Concord token validity and org/project configuration.

### Slow model loading or hangs on startup
- The startup flow runs in offline-first mode for HF (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`) to avoid network stalls.
- If you need fresh model pulls, temporarily override those env vars.

### Vision captions missing
- Ensure Ollama is installed and running (`http://localhost:11434`).
- Pull the configured model (for example `gemma3:4b`) before start.

## Useful Documentation

- `ARCHITECTURE.md` - system architecture and data model
- `REQUIREMENTS.md` - frozen functional requirements
- `IMPLEMENTATION_PLAN.md` - implementation roadmap
- `DASHBOARD_DESIGN.md` - UI/page design intent
- `PIPELINE_AND_TOOLS.md` - pipeline/tooling details
- `docs/LIVE_DEMO_VISION_PIPELINE.md` - live demo pipeline behavior

## Notes

- This repo is configured for local-first development and demo execution.
- Production hardening (auth, deployment topology, observability, secrets management) should be added before external rollout.
