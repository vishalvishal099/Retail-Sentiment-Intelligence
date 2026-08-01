# Final Presentation — Slide-by-Slide Notes

> Companion document for
> [`FINAL_PRESENTATION_VishalSingh_2020AA05641.pptx`](./FINAL_PRESENTATION_VishalSingh_2020AA05641.pptx)
> (25 slides). Use as a viva script and cheatsheet.
>
> **Deeper references**
> - Smart Reply (slides 5–7): [SMART_REPLY_COMPOSER.md](./SMART_REPLY_COMPOSER.md)
> - Learning Loop (slide 8):  [LEARNING_LOOP.md](./LEARNING_LOOP.md)
> - Final report:             [final/FINAL_REPORT_VishalSingh_2020AA05641.pdf](./final/FINAL_REPORT_VishalSingh_2020AA05641.pdf)

**Deck structure**

| Section | Slides | Focus |
|---------|--------|-------|
| Framing | 1 – 3 | Title, agenda, what's new since mid-sem |
| Post-midsem features | 4 – 10 | HITL, Smart Reply, Learning Loop, Explorer, Lifecycle, Insights, Notifications |
| Final results | 11 – 15 | ModernBERT, Vision, Trust score, Storage, Consolidated table |
| Wrap-up | 16 – 25 | Contributions, live demo, conclusions, recommendations, future work, repo, Q&A |

---

## Slide 1 — Title

**Content**
- Title: *Retail Sentiment Intelligence — Trust-Aware Sentiment Analysis of Retail Feedback using LLMs*
- BITS ZG628T · Post Mid-Semester Presentation
- Vishal Singh · 2020AA05641 · M.Tech (AI & ML)
- Supervisor: Mr. Varunendra Pratap Singh (Walmart Global Tech)
- Additional Examiner: Ms. Pradnya Kashikar (BITS Pilani)

**Talking track**
> "Good morning. I'm Vishal Singh, presenting the post mid-semester progress of my dissertation, *Retail Sentiment Intelligence*. Since mid-sem the focus has moved from *does the pipeline work?* to *can an analyst act on it, correct it, and feed the corrections back into the model?* The dissertation work was carried out at Walmart Global Tech under Mr. Varunendra Pratap Singh."

---

## Slide 2 — Agenda

**Content** — a 16-item, 2-column grid grouped as:
- Framing (1)
- Feature stack (2 – 10)
- Final numbers (11 – 15)
- Wrap-up (16)

**Talking track**
> "The deck has three parts. First, what shipped after mid-sem — Review & Validate, Smart Reply, Learning Loop, and four new dashboard pages. Second, the final numbers for ModernBERT, Vision, and Trust. Third, conclusions and future work. About 25 slides, ~18 minutes."

---

## Slide 3 — Since Mid-Sem, What's New

**Content** — two columns side by side

| Delivered at mid-sem | Added post mid-sem |
|----------------------|--------------------|
| 6-layer offline-first pipeline (25 subreddits) | Review & Validate — HITL UI + backend |
| ModernBERT up to Stage 2 (F1 0.7285) | Smart Reply Composer (GPT + Mistral + Smart Composer) |
| Multi-pass vision (0% hallucination pilot) | Learning-loop store — corrections + posted replies |
| Trust-score design + weighted formula | Post Explorer — multi-facet search |
| Brand-Health + Alert Feed pages | Post Lifecycle Kanban with 2-step Resolve |
| Group-routed email / Slack | Insights & Competitor Analysis |
| | In-app Notification Centre |
| | ModernBERT Stage 3 → F1 0.7642 |
| | Trust-score end-to-end eval (n=200) |
| | SQLite mirroring Cosmos DB partitioning |

**Framing to close on** — *"Mid-sem answered can the pipeline produce trust-weighted sentiment? Post-midsem answers can an analyst act on it, correct it, and feed the corrections back."*

---

## Slide 4 — Review & Validate (HITL)

**Content**
- Bullets: queue sorted by priority (P1 first) · analyst overrides sentiment / aspect in one click · corrections written to `feedback` · Generate Drafts → two reply options · analyst edits + posts to Reddit · posted replies feed the few-shot pool.
- Right-hand screenshot: `docs/Sem_4/final/figures/ui/review_validate.png`

**Talking track**
> "Review & Validate is where analysts spend most of their time. Every prediction — sentiment, aspects, trust — can be corrected. Corrections write a row into the `feedback` table with the analyst ID and timestamp. The same row is used later to retrain ModernBERT."

**Why it matters** — turns a passive dashboard into a training signal.

---

## Slide 5 — Smart Reply Composer — Triple Draft

**Content** — three cards side by side

| Draft | Model | Transport | Cost | Latency (warm) |
|-------|-------|-----------|------|----------------|
| A | GPT-4o | Walmart LLM Gateway | ~USD 0.0002 | ~2 s |
| B | Mistral 7B-Instruct | Local Ollama | free | ~10–15 s |
| C | Smart Composer | Pure Python | 0 | <10 ms |

- Fallback logic: gateway down → OpenAI direct → Smart Composer; Ollama down → Smart Composer; Smart Composer always available. UI badges any slot that fell back with `[offline fallback]`.

**Talking track**
> "Instead of one reply we generate three — GPT-4o via the Walmart Gateway, Mistral via local Ollama, and a deterministic Smart Composer. All three see the same prompt so the differences are attributable to the model, not the instruction. If any engine is down, the slot falls back to Smart Composer and the UI badges it — the analyst always has three drafts."

**Deeper detail** — see [SMART_REPLY_COMPOSER.md §1–§2](./SMART_REPLY_COMPOSER.md).

---

## Slide 6 — Smart Reply — Prompt Design & Few-Shot

**Content**
- Dark code block showing the full prompt template from `_build_reply_prompt()`.
- Bottom-left card: **Few-shot source** — top-3 posted replies from `feedback`, refreshed on every click.
- Bottom-right card: **Style guardrails** — 2-4 sentences, no jargon / hashtags / emojis, no unverifiable refund promises, sign off as a person.

**Talking track**
> "The prompt has three parts: a system role, three worked examples pulled from past posted replies, and the customer post. This is standard few-shot in-context learning. The examples come from the `feedback` table — top-3 most recent posted replies. As analysts post more replies, the few-shot pool automatically adapts to the team's tone without retraining."

**Why not fine-tune?** — the reply pool is currently ~hundreds of examples, not thousands. In-context is the right regime at this scale. Fine-tune is on the future-work roadmap once the pool exceeds ~10 k.

**Deeper detail** — see [SMART_REPLY_COMPOSER.md §2–§3](./SMART_REPLY_COMPOSER.md).

---

## Slide 7 — Smart Reply — Worked Example (real, live-captured)

**Content**
- Customer complaint card — real post `reddit_1u2bgdw` from r/samsclub, with a **clickable "🔗 Open original on Reddit"** link.
- Pipeline output: `negative` (conf 0.9999997), aspects `customer service · product quality · store experience`, trust 0.66.
- Three real drafts captured live from `generate_reply_pair()` with all three engines up:
  - **Draft A / GPT-4o** — verbatim from the Walmart Gateway.
  - **Draft B / Mistral 7B** — verbatim from local Ollama.
  - **Draft C / Smart Composer** — verbatim deterministic output.

**Talking track**
> "This is a real Sam's Club member complaining that whole pies are stale at pickup. You can click the link and read the original on Reddit. Our pipeline scored it `negative` at 0.9999997 confidence with three aspects. When the analyst clicks Generate Drafts, we fire the same prompt at three engines in parallel. GPT-4o gives the most polished response; Mistral is chattier but free and offline; Smart Composer is a deterministic safety net. All three are what the system actually produced when we ran it."

**Reproduction** — [SMART_REPLY_COMPOSER.md §8](./SMART_REPLY_COMPOSER.md) has a copy-pasteable script.

---

## Slide 8 — Learning Loop — Feedback → Retraining

**Content**
- Four capture cards: **Label / aspect correction**, **Trust-score override**, **Posted reply**, **Lifecycle transition** — all feeding into one **`feedback` table** row.
- Two consumers:
  - **HOT loop (green)** — every Generate Drafts click queries `feedback` for the top-3 posted replies → injected as few-shot examples → effect visible on the next reply, no retraining.
  - **WARM loop (purple)** — monthly export of corrections → appended to Walmart-200 → ModernBERT Stage-3 rerun with 5-fold OOF CV → new checkpoint wins only if OOF F1 improves.
- Failure modes eliminated: hot loop uses in-context learning (no catastrophic forgetting); warm loop uses 5-fold OOF CV (no train/eval leakage).

**Talking track**
> "The learning loop is what makes 'the system improves over time' concrete. Every human action — corrections, trust overrides, posted replies — writes one row to the `feedback` table. Two things consume that table. The hot loop, every click, uses the last three posted replies as few-shot examples for the reply generator. The warm loop, monthly, exports corrections into the ModernBERT Stage-3 training set for a supervised re-train. No black boxes — every row is queryable in SQLite."

**Deeper detail** — see [LEARNING_LOOP.md](./LEARNING_LOOP.md).

---

## Slide 9 — Post Explorer (Multi-Facet Search)

**Content**
- Left: filter list — sentiment · confidence slider · trust-score slider · subreddit multi-select · aspect (8-item taxonomy) · date range · full-text.
- Right screenshot: `docs/Sem_4/final/figures/ui/post_explorer.png`
- Bottom: per-post card contents — title, sentiment badge, trust tier, aspect chips, subreddit, timestamp, actions.

**Talking track**
> "Post Explorer is the 'find me 20 posts I care about right now' page. Any combination of the filters can be applied simultaneously; results stream in ranked by priority × recency. Every card links back into Review & Validate."

---

## Slide 10 — Post Lifecycle (Kanban)

**Content**
- 4 states, left to right: **TRIAGED → ACKNOWLEDGED → IN PROGRESS → RESOLVED**.
- Screenshot: `docs/Sem_4/final/figures/ui/lifecycle_kanban.png`
- Resolve modal — 2-step flow:
  1. Save action note + optional LLM reply (a) Save & open Reddit (reply on clipboard) OR (b) Resolve (no reply needed).
  2. Paste on Reddit → return → Mark Resolved.
- Every transition timestamped for SLA analytics.

**Talking track**
> "Lifecycle Kanban tracks a complaint end-to-end. Cards move through four states. The Resolve modal is a two-step flow so posting to Reddit is decoupled from marking the card resolved — the analyst can't accidentally close a card without confirming the reply landed."

---

## Slide 11 — Insights & Competitor Analysis

**Content** — 2 × 2 feature grid:

| | |
|---|---|
| **Priority-Negatives** — top issues ranked by volume × severity × recency by aspect | **Competitor Pulse** — Walmart vs Costco / Target / Amazon on shared aspects |
| **Weekly LLM Summaries** — natural-language digest + action items + emerging topics | **Aspect Drilldown** — 8-aspect taxonomy · per-aspect sentiment trend + volume · representative posts |

**Talking track**
> "Where the other pages are operational, Insights is strategic. It answers 'what should the ops team focus on this week?' — the top issues weighted by volume, severity and recency, along with a cross-brand pulse and an LLM-generated weekly digest."

---

## Slide 12 — Notification Centre

**Content**
- In-app mirror of the group-routed email / Slack digest.
- Every P1 / P2 alert is mirrored in the app; grouped by subreddit ↔ team; read/unread persisted per analyst; deep-links to Review & Validate.
- Screenshot: `docs/Sem_4/final/figures/ui/notifications.png`
- Priority thresholds: **P1** — trust ≥ 0.70 ∧ conf ≥ 0.80  ·  **P2** — trust ≥ 0.50 ∧ conf ≥ 0.60.

**Talking track**
> "Post-midsem we added an in-app notification centre so analysts don't have to leave the dashboard to check emails. Alerts are grouped by team so an OGP analyst doesn't get pinged for a Spark-driver complaint. Same routing rules as the email/Slack digest — powered by the same `alerts` rows."

---

## Slide 13 — ModernBERT — Final Training Results

**Content**
- Three KPI tiles: Overall Macro-F1 **0.6272 → 0.7642**  ·  Long-post F1 (> 256 tok) **0.28 → 1.00**  ·  Uplift **+13.7 pts**.
- 3-stage curriculum table:
  | Stage | Data | Macro-F1 | Δ |
  |-------|------|----------|---|
  | Baseline (Twitter-RoBERTa) | off-the-shelf | 0.6272 | — |
  | Stage 1 | TweetEval sentiment (~45 k) | 0.6810 | +5.4 |
  | Stage 2 | GoEmotions-3class Reddit (~54 k, pseudo) | 0.7285 | +10.1 |
  | Stage 3 (final) | Walmart-200 hand-labelled | **0.7642** | **+13.7** |
- Per-length-bucket F1: short (< 64) 0.75 → 0.78, medium 0.65 → 0.74, long (> 256) 0.28 → 1.00.

**Talking track**
> "Final ModernBERT numbers on 5-fold OOF CV of 200 hand-labelled retail Reddit posts. Macro-F1 climbs the curriculum monotonically. The most dramatic gain is on long posts — the Twitter-RoBERTa baseline is capped at 512 tokens, so long complaints get truncated and F1 collapses to 0.28. ModernBERT sees the full 1024 tokens and hits 1.0 on that bucket."

---

## Slide 14 — Vision Pipeline — Multi-Pass Payoff

**Content**
- 4-pass architecture: **STRUCTURE → TILE → EXTRACT → MERGE** (image removed on the final merge → cannot invent visuals).
- Evaluation on 32 retail screenshots:
  | Metric | Single-pass | Multi-pass | Change |
  |--------|-------------|-----------|--------|
  | Hallucination rate | 50 % | **0 %** | eliminated |
  | Text-extraction success | 25 % | **75 %** | 3× |
  | Retail-signal recall | 40 % | **81 %** | 2× |
  | Latency / image (warm) | ~5 s | ~15 s | accepted |

**Talking track**
> "Vision was the biggest post-midsem win. Single-pass Gemma 3 4B was hallucinating on half of all images — inventing prices, order numbers, screenshots. The fix was structural: four passes where the last one is a text-only merge with the image removed, so the model physically cannot invent visual details. Zero hallucination on the 32-image gold set."

---

## Slide 15 — Trust-Score — End-to-End Evaluation

**Content**
- Three KPI tiles: Low-trust share **15 %**  ·  Human-agreed **12 / 15**  ·  Agreement rate **80 %**.
- Formula banner: `trust_score = 0.4·metadata + 0.3·dedup + 0.3·llm_credibility`.
- Design principle — *flag, don't drop*. Every low-trust post is surfaced with an explanatory chip and can be overridden in one click. Every constant has a stakeholder-arguable rationale in `config/models.yaml`.

**Talking track**
> "On the 200-post gold set, 15 % of posts fell into the low-trust bucket. When a human annotator cross-checked those 15, they agreed with 12 — 80 % agreement. The score is decomposed into three named components in the dashboard so the analyst can see *why* a post is low-trust and override it if they disagree."

---

## Slide 16 — Storage — SQLite → Cosmos DB Lift-and-Shift

**Content**
- 6-container schema table with partition keys (`raw_posts /subreddit`, `analyses /subreddit`, `aggregates /time_window`, `alerts /severity`, `feedback /analyst_id`, `notification_log /group_id`).
- Left card: SQLite in WAL mode, `data JSON` column mirrors Cosmos doc, `StorageBackend` pluggable, nightly backup + JSONL cost ledger.
- Right card: swap `SQLiteBackend → CosmosBackend`; same schema, partition keys already match production; zero change to pipeline / dashboard code.

**Talking track**
> "Storage is designed for a lift-and-shift to Azure Cosmos DB. Every SQLite container's partition key matches the production Cosmos partition, and the `data JSON` column mirrors the document body. The `StorageBackend` interface is a single Python file — swap it out and the pipeline runs unchanged."

---

## Slide 17 — Evaluation Summary — Post-Midsem Numbers

**Content** — combined 12-row metrics table covering sentiment (F1, long-post F1, CV method), vision (hallucination, extraction, recall), trust (low-trust share, annotator agreement), ops (25 subreddits, 6-h cadence, 8 dashboard pages).

**Talking track**
> "Consolidated numbers — one table, three subsystems, all evaluated on the same 200-post retail-Reddit gold set. Highlighted rows are the four post-midsem wins."

---

## Slide 18 — Principal Contributions (C1 – C5)

**Content**
- **C1** — Offline-first RSI pipeline (ingest → trust → sentiment → aspects → vision → aggregation → alerts → dashboard). Zero API cost, modular, Azure-deployable.
- **C2** — Fine-tuned ModernBERT with 3-stage curriculum. Macro-F1 0.6272 → 0.7642, long-post 0.28 → 1.00, 5-fold OOF CV.
- **C3** — Multi-pass vision technique on Gemma 3 4B. Hallucination 50 → 0 %, extraction 25 → 75 %.
- **C4** — Interpretable trust score + admission gate. Flag, don't drop; every constant traceable to English rationale.
- **C5** — HITL learning-loop dashboard. Review & Validate, Lifecycle, Insights, Notifications. Corrections + posted replies feed few-shot reply generation and future retraining.

**Talking track**
> "Five principal contributions, mapped one-to-one to the sections of the report. C1 is the plumbing, C2 and C3 are the model wins, C4 is the trust design, and C5 is the analyst-facing surface that makes the pipeline usable."

---

## Slide 19 — Live Demo — Dashboard Walkthrough

**Content** — 3 × 2 screenshot grid (embedded from `docs/Sem_4/final/figures/ui/`):
Brand Health · Alert Feed · Post Explorer · Review & Validate · Lifecycle Kanban · Insights.

**Talking track**
> "Rather than dropping into a live demo I'll walk through six screens: Brand Health for the top-line KPIs, Alert Feed for what's firing right now, Post Explorer for filtered search, Review & Validate for the correction loop, Lifecycle Kanban for the resolution workflow, and Insights for the strategic view."

*(If time permits, switch to `http://localhost:3001` and demo Review & Validate on the same Sam's Club pizza post from slide 7.)*

---

## Slide 20 — Conclusions — Research Questions Answered

**Content** — 4-row RQ box, all green:

| RQ | Answer |
|----|--------|
| **RQ1** — Can a fine-tuned encoder beat baselines on Reddit retail sentiment? | **YES** — ModernBERT 3-stage curriculum: Macro-F1 0.6272 → 0.7642 overall; 0.2778 → 1.0000 on long posts. |
| **RQ2** — Can a compliant open-weights VLM extract structured retail signal from screenshots? | **YES** — Multi-pass on Gemma 3 4B: hallucination 50 → 0 %, text extraction 25 → 75 %. |
| **RQ3** — Can a defensible trust score filter low-credibility posts without silent drops? | **YES** — 3-part interpretable score flagged 15 %; 12 of 15 confirmed by annotator; posts remain visible + overridable. |
| **RQ4** — Can a HITL workflow produce a re-training signal? | **YES** — Every correction and posted reply logged → feeds ModernBERT Stage-3 augmentation and reply few-shot pool. |

**Talking track**
> "Every research question was answered with a measured YES. The evidence sits on the previous slides — RQ1 in the ModernBERT numbers, RQ2 in the vision numbers, RQ3 in the trust-score evaluation, and RQ4 in the learning loop."

---

## Slide 21 — Recommendations — Immediate Follow-Ons

**Content**
1. **Monthly retraining cadence** — use the HITL feedback store as the incremental labelling stream.
2. **Bilingual pass (Hindi + English)** — validate taxonomy with native-speaker analysts before extending to Indian retail communities.
3. **Per-team SLA dashboards** — extend Lifecycle SLA analytics once analyst volume passes ~50 posts / day.

**Talking track**
> "Three follow-ons that could ship in the next quarter without any research risk. All three unlock existing infrastructure — the retraining pipeline is already scripted, the taxonomy is already extensible, and the lifecycle table already has the timestamps."

---

## Slide 22 — Future Work — Model + Product

**Content** — two columns.

**Model-level**
- Joint sentiment + aspect head on a shared encoder (~30 % inference saving).
- Distil ModernBERT to ~50 M-parameter student → CPU-only edge inference.
- Reasoning-augmented VLM captioning (LLaVA-Next 1.6 B / SmolVLM).
- 3-seed ensemble for tighter F1 variance.
- Blind 25-post recheck for defensibility.

**Product-level**
- Auto-reply confidence gate — promote LLM drafts to "queued for send" when analyst edit-distance falls below a threshold.
- Predictive P1 forecast — seasonal decomposition on daily counts (24–48 h ahead).
- Bilingual taxonomy.
- Slack-bot inline responses.
- Automated retraining pipeline hook.

**Talking track**
> "Model-level work is about efficiency — halve the inference cost with a joint head, then distil for CPU-only edge. Product-level work is about closing the last mile — promote LLM drafts to auto-send when they're consistently good, and forecast P1 volume so on-call gets a heads-up."

---

## Slide 23 — Future Work — Operational

**Content**
- **Kubernetes CronJob** — deploy pipeline as a scheduled CronJob + managed Postgres for multi-analyst concurrency.
- **Azure Cosmos DB migration** — schema already mirrors partition design; swap `SQLiteBackend → CosmosBackend`.
- **Walmart ticketing integration** — P1 alerts open cases directly.
- **Broader ingestion** — Twitter / X, YouTube comments, app-store reviews.

**Talking track**
> "Operational roadmap: containerise, migrate storage to Cosmos, wire alerts into Walmart's ticketing so the analyst never leaves the workflow, and extend beyond Reddit to Twitter, YouTube comments and app-store reviews on the same trust + sentiment stack."

---

## Slide 24 — Source Code & Deliverables

**Content**
- Repository banner:
  `https://gecgithub01.walmart.com/v0s01jh/Retail_Sentiment_Intelligence`
- Deliverables table:
  | Deliverable | Path in repo | Contents |
  |-------------|--------------|----------|
  | Final Report PDF | `docs/Sem_4/final/FINAL_REPORT_VishalSingh_2020AA05641.pdf` | 10 chapters + appendices + refs |
  | Final Report LaTeX | `docs/Sem_4/final/latex/` | Reproducible xelatex source |
  | Pipeline core | `src/pipeline.py`, `src/ingestion/`, `src/analysis/` | 6-layer async pipeline |
  | Sentiment training | `scripts/train_modernbert_sentiment.py` | 3-stage curriculum runner |
  | Evaluation notebook | `evaluation/trust_score_walmart200.ipynb` | Reproducible 5-fold OOF eval |
  | Dashboard | `frontend/` (React + Vite + Tailwind) | 8 pages, live via WebSocket |
  | Reproduction | Appendix B of the report + `start.sh` | Clone → conda → start |

**Talking track**
> "Everything is in the repo — the report LaTeX, the pipeline code, the training scripts, the evaluation notebook, the React dashboard, and the reproduction guide in Appendix B."

---

## Slide 25 — Thank You / Q&A

**Content**
- Large "Thank You" header.
- Repository URL card: `gecgithub01.walmart.com/v0s01jh/Retail_Sentiment_Intelligence`
- Report path: `docs/Sem_4/final/FINAL_REPORT_VishalSingh_2020AA05641.pdf`
- Bottom: Vishal Singh · 2020AA05641 · BITS Pilani (WILP) · Walmart Global Tech, Bengaluru

**Talking track**
> "Thank you — happy to take any questions."

---

## Appendix A — Common evaluator questions

Use these to prep for cross-questioning.

**"Isn't 200 posts too few to fine-tune on?"**
- Stage 3 is deliberately the last stage of a curriculum. Stages 1 and 2 add ~99 k pseudo-labelled tweets and Reddit posts. Stage 3 does *domain adaptation*, not from-scratch training. Class weights and oversampling handle the 200-sample class imbalance.

**"How do you know ModernBERT isn't overfitting the 200 samples?"**
- 5-fold *stratified out-of-fold* cross-validation. Every one of the 200 posts is scored by a model that never saw it in training. Early stopping on eval Macro-F1 with patience = 3.

**"Aren't the vision numbers suspiciously good?"**
- 32-image gold set is small; the paper explicitly labels the vision eval as a *pilot*. The mechanism explanation is what generalises: removing the image from the merge step *architecturally* prevents visual hallucination.

**"How does the reply generator improve over time without training?"**
- Few-shot in-context learning. Every posted reply becomes the next post's top few-shot example. The pool grows without bound; the prompt cost stays constant at 3 pairs. See [SMART_REPLY_COMPOSER.md §3](./SMART_REPLY_COMPOSER.md).

**"What if the Walmart LLM Gateway is unavailable?"**
- Circuit breaker after 3 consecutive failures → falls back to direct OpenAI (if `OPENAI_API_KEY` env is set) → falls back to Smart Composer. Slot is badged `[offline fallback]` in the UI so the analyst knows the source.

**"How does the trust score handle a legitimate but low-karma user?"**
- The score is a *soft* filter — low trust posts are flagged with an explanatory chip and can be overridden by the analyst in one click. Overrides feed the learning loop, so the threshold self-corrects for the analyst team's actual definition of trustworthy.

**"Is any part of this reinforcement learning?"**
- No. Two mechanisms: (1) in-context learning for reply generation (no weight update), (2) plain supervised fine-tuning for ModernBERT (monthly cadence, augmented dataset). Deliberately kept simple because analyst volume is still modest.

**"How would you know the retrained model is actually better?"**
- The retraining script re-runs 5-fold OOF CV on the augmented set. The new checkpoint is promoted only if the OOF Macro-F1 beats the current one. The symlink flip in `config/models.yaml` is manual by design — it's the *only* step that isn't automatable at this stage.

---

## Appendix B — Repo landmarks by slide

| Slide | Code / doc |
|-------|-----------|
| 4 | `frontend/src/pages/ReviewQueue.tsx`, `src/dashboard/api.py::submit_review` |
| 5 – 7 | `src/analysis/llm_client.py` (`WalmartLLMClient.generate_reply_pair`, `_build_reply_prompt`, `_gateway_generate_reply`, `_ollama_generate_reply`, `_smart_compose_reply`) |
| 8 | `src/dashboard/api.py::_collect_reply_examples`, `scripts/train_modernbert_sentiment.py::run_stage3` |
| 9 | `frontend/src/pages/PostExplorer.tsx` |
| 10 | `frontend/src/pages/PostLifecycle.tsx`, `_ensure_lifecycle_reply_sent` |
| 11 | `frontend/src/pages/Insights.tsx` |
| 12 | `frontend/src/pages/Notifications.tsx`, `src/notifications/` |
| 13 | `scripts/train_modernbert_sentiment.py`, `evaluation/trust_score_walmart200.ipynb` |
| 14 | `src/analysis/vision.py` |
| 15 | `src/trust/scorer.py`, `config/models.yaml` |
| 16 | `src/storage/store.py` |
