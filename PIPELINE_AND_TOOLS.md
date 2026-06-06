# Retail Sentiment Intelligence — Architecture, Pipeline & Tools

> Living reference for how data flows through the system, which tools we use at each layer, and how the LLM "learning loop" works for analyst replies.

---

## 1. End-to-end data flow

```mermaid
flowchart LR
  subgraph Sources["Data Sources (no API key)"]
    AS["Arctic Shift API<br/>arctic-shift.photon-reddit.com<br/>(public Reddit archive)"]
    PRAW["PRAW + Reddit API<br/>(optional · needs OAuth)"]
  end

  subgraph Pipeline["src/pipeline.py · hourly + on-demand"]
    direction TB
    I["1. INGEST<br/>arctic_shift.py / fetcher.py<br/>curl + JSON paging"]
    P["2. PREPROCESS<br/>preprocess.py<br/>clean · langdetect · dedup"]
    T["3. TRUST SCORING<br/>trust/scorer.py<br/>metadata + dedup + heuristics"]
    A["4. ANALYZE<br/>analysis/analyzer.py<br/>sentiment + aspects"]
    AG["5. AGGREGATE<br/>aggregation/aggregator.py<br/>hourly · daily rollups"]
    AL["6. ALERTS<br/>alerts/engine.py<br/>spike · severity rules"]
  end

  subgraph LLMs["analysis/llm_client.py · pluggable"]
    HF["HuggingFace (offline)<br/>cardiffnlp/twitter-roberta · sentiment<br/>facebook/bart-large-mnli · aspects<br/>google/flan-t5-base · reply"]
    SC["Smart Composer<br/>content-aware template<br/>(varies every call)"]
    AZ["Azure OpenAI<br/>(opt-in via config)"]
  end

  subgraph Store["src/storage/store.py · SQLite"]
    RP[(raw_posts)]
    AN[(analyses)]
    FB[(feedback)]
    AGG[(aggregates)]
    ALRT[(alerts)]
  end

  subgraph API["src/dashboard/api.py · FastAPI :8000"]
    BH["/api/brand-health"]
    PE["/api/posts"]
    RQ["/api/review*"]
    DR["/api/review/{id}/draft-reply"]
    AE["/api/alerts"]
    PS["/api/pipeline/run · status"]
  end

  subgraph UI["frontend/ · React + Vite :3001"]
    BHP["Brand Health"]
    PEP["Post Explorer"]
    RQP["Review Queue<br/>(2-draft picker)"]
    APP["Aspect Drilldown"]
    ALP["Alert Feed"]
  end

  Analyst([Analyst]) -->|edits & posts reply| RQP

  AS -->|HTTPS JSON| I
  PRAW -.->|optional| I
  I --> P --> T --> A
  A <-->|score / classify| HF
  A <-.->|opt-in| AZ
  A --> AG --> AL
  P --> RP
  A --> AN
  AG --> AGG
  AL --> ALRT

  RP & AN & FB & AGG & ALRT --> API
  API --> UI

  DR -->|generate_reply_pair| HF
  DR -->|always| SC
  RQP -->|posted reply| FB
  FB -->|few-shot examples| DR

  classDef store fill:#fef3c7,stroke:#92400e
  classDef api fill:#dbeafe,stroke:#1e40af
  classDef ui fill:#dcfce7,stroke:#166534
  classDef llm fill:#ede9fe,stroke:#5b21b6
  class RP,AN,FB,AGG,ALRT store
  class BH,PE,RQ,DR,AE,PS api
  class BHP,PEP,RQP,APP,ALP ui
  class HF,SC,AZ llm
```

---

## 2. Pipeline stages (sequence)

```mermaid
sequenceDiagram
  autonumber
  participant Sched as Scheduler (asyncio 60min)
  participant Pipe as pipeline.py
  participant Arc as Arctic Shift
  participant Pre as Preprocess
  participant Trust as TrustScorer
  participant LLM as HF Models
  participant DB as SQLite
  participant Alert as AlertEngine
  participant UI as Dashboard

  Sched->>Pipe: run --once (hourly tick or Run Now)
  Pipe->>Arc: GET posts/search?subreddit=walmart (after cursor)
  Arc-->>Pipe: JSON batch
  Pipe->>Pre: clean, langdetect, dedup
  Pre->>DB: raw_posts.insert
  Pipe->>Trust: score (metadata, dedup, heuristics)
  Pipe->>LLM: roberta sentiment + bart-mnli aspects
  LLM-->>Pipe: sentiment, confidence, aspects
  Pipe->>DB: analyses.insert
  Pipe->>Pipe: aggregate hourly + daily rollups
  Pipe->>DB: aggregates.upsert
  Pipe->>Alert: spike and severity detect
  Alert->>DB: alerts.insert
  Pipe->>UI: websocket broadcast (alerts)
```

---

## 3. Reply-generation learning loop

```mermaid
flowchart TB
  RQ["Analyst opens Review Queue"] --> Gen["Click Generate Drafts"]
  Gen --> API["POST /api/review/{id}/draft-reply"]
  API --> Coll["_collect_reply_examples · last 5 posted replies from feedback"]
  Coll --> Pair["generate_reply_pair"]

  Pair --> A["Draft A · Smart Composer<br/>extracts complaint keywords<br/>+ randomized phrase pools"]
  Pair --> B["Draft B · FLAN-T5-base<br/>multi-temp sampling + scorer<br/>fallback to composer on collapse"]

  A --> Pick["Two side-by-side cards<br/>indigo border on selected"]
  B --> Pick
  Pick --> Edit["Editable textarea<br/>analyst tweaks wording"]
  Edit --> Post["Post Reply to Reddit<br/>copy clipboard + open thread"]
  Post --> FB[("feedback table<br/>kind=auto_reply_posted")]
  FB -.->|next call few-shot tone hint| Coll

  classDef llm fill:#ede9fe,stroke:#5b21b6
  classDef sc fill:#dbeafe,stroke:#1e40af
  class B llm
  class A sc
```

---

## 4. Tools & libraries by layer

| Layer | Tool / Library | Purpose |
|---|---|---|
| **Ingestion** | `arctic-shift.photon-reddit.com` (HTTPS + `curl` subprocess) | Free, key-less Reddit data |
| | `praw` 7.7+ | Optional official Reddit API path |
| | `langdetect` | English-only filter |
| | `sentence-transformers` (MiniLM-L6-v2) | Semantic dedup |
| **Storage** | `sqlite3` (built-in) → `data/local.db` | Local dev store |
| | `azure-cosmos` | Production store (configurable) |
| **NLP / LLM** | `transformers` + `torch` | Local model runtime (offline cache) |
| | `cardiffnlp/twitter-roberta-base-sentiment-latest` | Sentiment classification |
| | `facebook/bart-large-mnli` | Zero-shot aspect classification |
| | `google/flan-t5-base` | Reply text generation (Draft B) |
| | `openai` SDK | Azure OpenAI opt-in path |
| | Custom **Smart Composer** | Always-varied, content-aware reply (Draft A) |
| **API** | `fastapi` + `uvicorn` + `websockets` | REST + live alert push (port 8000) |
| | `pydantic` | Request / response schemas |
| **Scheduling** | `asyncio` event loop (lifespan) | 60-min cron + manual Run Now |
| | `subprocess` (`python -m src.pipeline --once`) | Detached pipeline runs |
| **Frontend** | `React 18` + `TypeScript` + `Vite` (port 3001) | SPA |
| | `react-router-dom` v6 | Routing (Brand Health · Posts · Review · Alerts · Aspects) |
| | `recharts` | Sentiment pie, trend lines |
| | `tailwindcss` | Styling |
| **Observability** | `structlog` | Structured JSON logs |
| | `data/llm_costs.jsonl` (`CostTracker`) | Per-call cost ledger |
| **Config** | `pyyaml` (`config/pipeline_config.yaml`) + `python-dotenv` | Pluggable provider switches |
| **Testing** | `pytest`, `pytest-asyncio`, `scikit-learn` (metrics) | Unit + integration + F1 / AUC eval |

---

## 5. Request paths through the dashboard

```mermaid
flowchart LR
  subgraph Pages
    BH["Brand Health<br/>KPIs · trend · aspects"]
    PE["Post Explorer<br/>filter · sort by post-time"]
    RV["Review Queue<br/>correct + reply"]
    AS["Aspect Drilldown"]
    AL["Alerts Feed"]
  end

  BH -->|click %| PE
  AS -->|click aspect| PE
  RV -->|correct sentiment| AN[(analyses)]
  RV -->|post reply| FB[(feedback)]
  RV -->|generate| LLMC["LLM client"]

  BH -->|GET| BHapi["/api/brand-health"]
  PE -->|GET| Papi["/api/posts?range=&sentiment=&aspect="]
  RV -->|GET| RVapi["/api/review · /stats"]
  RV -->|POST| DRapi["/api/review/{id}/draft-reply"]
  RV -->|POST| Rapi["/api/review/{id}/reply"]
  AL -->|GET| ALapi["/api/alerts"]
  AL -.->|WS| WS["/ws/alerts"]
```

---

## 6. TL;DR

- **No Reddit key** — Arctic Shift public archive over plain HTTPS via `curl`.
- **All LLMs run locally** — three HF models cached in `~/.cache/huggingface/`, started with `TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1`.
- **One Python orchestrator** ([src/pipeline.py](src/pipeline.py)) runs the 6-stage flow hourly and on-demand.
- **FastAPI** ([src/dashboard/api.py](src/dashboard/api.py)) exposes the dashboard data + manual pipeline triggers; **React/Vite** renders 5 pages.
- **Closed feedback loop**: every analyst-posted reply lands in the `feedback` table and becomes a few-shot tone hint for the next draft.

---

## 7. Key files

| Area | File |
|---|---|
| Pipeline orchestrator | [src/pipeline.py](src/pipeline.py) |
| Arctic Shift fetcher | [src/ingestion/arctic_shift.py](src/ingestion/arctic_shift.py) |
| PRAW fetcher (optional) | [src/ingestion/reddit_client.py](src/ingestion/reddit_client.py), [src/ingestion/fetcher.py](src/ingestion/fetcher.py) |
| Preprocess + dedup | [src/ingestion/preprocess.py](src/ingestion/preprocess.py), [src/trust/dedup.py](src/trust/dedup.py) |
| Trust scoring | [src/trust/scorer.py](src/trust/scorer.py), [src/trust/heuristics.py](src/trust/heuristics.py) |
| Sentiment + aspects + reply | [src/analysis/analyzer.py](src/analysis/analyzer.py), [src/analysis/llm_client.py](src/analysis/llm_client.py) |
| Aggregation + alerts | [src/aggregation/aggregator.py](src/aggregation/aggregator.py), [src/alerts/engine.py](src/alerts/engine.py) |
| Storage | [src/storage/store.py](src/storage/store.py), [src/storage/cursor.py](src/storage/cursor.py) |
| API | [src/dashboard/api.py](src/dashboard/api.py) |
| Config | [config/pipeline_config.yaml](config/pipeline_config.yaml) |
| Frontend pages | [frontend/src/pages/BrandHealth.tsx](frontend/src/pages/BrandHealth.tsx), [frontend/src/pages/PostExplorer.tsx](frontend/src/pages/PostExplorer.tsx), [frontend/src/pages/ReviewQueue.tsx](frontend/src/pages/ReviewQueue.tsx), [frontend/src/pages/AspectDrilldown.tsx](frontend/src/pages/AspectDrilldown.tsx), [frontend/src/pages/AlertFeed.tsx](frontend/src/pages/AlertFeed.tsx) |
