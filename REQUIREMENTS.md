# Requirements — Retail Sentiment Intelligence

**Frozen:** 2026-06-04
**Status:** All downstream planning and implementation must conform unless explicitly revised.

---

## 1. Scope of Analysis Units
- Analyze **both posts and comments** (top-level + replies, depth ≤ 2, min score ≥ 3, max 10 comments per post).
- Each comment is a **separate analysis unit**, linked to its parent post via `parent_post_id`.

## 2. Data Sources
- **R2.1** Start with **Reddit only**. Add Twitter/X only after Reddit pipeline is stable.
- **R2.2** Ingest **all Walmart-related subreddits** (r/walmart, r/Sparkdriver, r/samsclub, etc. — full list in `data/reddit_walmart_communities.csv`).
- **R2.3** On first run, **backfill up to 90 days** of history per subreddit.
- **R2.4** **English-only** for v1; revisit Spanish if time permits.

## 3. Volume & Cadence
- **R3.1** Ingestion runs **hourly by default**, but interval is **configurable** (no hard dependency on hourly).
- **R3.2** Ingest **all posts/comments created in each interval** (no re-fetching older data except for initial backfill).
- **R3.3** LLM spend: **Start with free/OSS models** (e.g., cardiffnlp, LLaMA, DeBERTa). Code must be **modular** to swap in paid models (e.g., gpt-4o-mini) later. No hard ceiling, but **cost tracking is required**.

## 4. Taxonomy & Labels
- Use the **6-aspect taxonomy** as baseline:
  - `delivery`, `product_quality`, `returns`, `customer_support`, `pricing`, `app_website`
- Allow additional aspects to be added if coverage is insufficient (favor **maximum coverage**).
- **Multi-aspect per unit is allowed.**
- Sentiment: **3-class** (positive, negative, neutral).

## 5. Trust Filter
- Implement best-practice trust filtering: metadata heuristics + dedup + LLM credibility check.
- All units get a `trust_score` (0–1).
- Low-trust units are **flagged for review, not dropped**.
- Threshold and weighting can be tuned later.

## 6. Storage & Privacy
- **Hash Reddit usernames** before storage (no raw usernames retained).
- **Data retention: 1 year** default (configurable).
- Cosmos DB partitioning: `/subreddit` for `raw_posts`, `/time_window` for `aggregates`.

## 7. Model & Evaluation
- **R7.1** v0 model = **placeholder** (OSS first, gpt-4o-mini later when subscription available). Code must allow easy model swap via `config.model`.
- **R7.2** Start with **one model end-to-end**, then expand the comparison table.
- **R7.3** Benchmark = **150 units** total — **100 posts + 50 comments**, stratified by aspect / sentiment / trust.
- **R7.4** Target metric (hard gate): **Sentiment F1 ≥ 0.80**. Other metrics tracked but not gated.

## 8. Dashboard
- **R8.1** **Real-time alerts via WebSocket** (preferred); polling as fallback.
- **R8.2** Page priorities:
  - **P0:** Brand Health Overview, Aspect Drilldown, Review & Validate
  - **P1:** Alert Feed, Post Explorer
  - **P2:** Trust Analytics, Competitor Pulse, Copilot Chat (optional)
- **R8.3** Auth: **skip for now** (single-user dissertation demo); add bearer token or Azure AD if time permits.

## 9. Delivery & Ops
- **R9.1** **Local laptop hosting** for v1; revisit Azure App Service / Static Web App after API is stable.
- **R9.2** **Tests required** for: trust scorer, aggregator, preprocessor (dedup), any custom math.
- **R9.3** **LLM spend tracking** mandatory; kill-switch optional for v1, added when paid API is wired in.

---

## Change Log
- **2026-06-04** — Initial frozen requirements.
