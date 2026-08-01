# Final Presentation — Slide-by-Slide Notes

> Companion document for
> [`FINAL_PRESENTATION_VishalSingh_2020AA05641.pptx`](./FINAL_PRESENTATION_VishalSingh_2020AA05641.pptx)
> (22 slides). Use as a viva script and cheatsheet.
>
> **Deeper references**
> - Smart Reply (slides 5–7): [SMART_REPLY_COMPOSER.md](./SMART_REPLY_COMPOSER.md)
> - Learning Loop (slide 8):  [LEARNING_LOOP.md](./LEARNING_LOOP.md)
> - Final report:             [final/FINAL_REPORT_VishalSingh_2020AA05641.pdf](./final/FINAL_REPORT_VishalSingh_2020AA05641.pdf)

**Deck structure**

| Section | Slides | Focus |
|---------|--------|-------|
| Framing | 1 – 3 | Title, agenda, what's new since mid-sem |
| Post-midsem features | 4 – 12 | HITL, Smart Reply, Learning Loop, Explorer, Lifecycle, Insights, Notifications |
| Final results | 13 – 16 | ModernBERT, Vision, Trust score, Consolidated table |
| Wrap-up | 17 – 22 | Contributions, live demo, honest conclusions, grounded future work, repo, Q&A |

---

## Slide 1 — Title

**Content**
- Title: *Retail Sentiment Intelligence*
- Sub-title: *Real-Time Social Media Mining and Trust-Aware Sentiment Analysis Using Large Language Models for Retail Feedback Optimization*
- BITS ZG628T · Post Mid-Semester Presentation
- **Faculty Mentor:** Ms. Pradnya Kashikar — BITS Pilani (WILP)
- **Supervisor:** Mr. Varunendra Pratap Singh — Principal Software Engineer, Walmart Global Tech, Bengaluru
- **Candidate:** Vishal Singh · 2020AA05641 — M.Tech (AI & ML), BITS Pilani (WILP)

**Talking track**
> "Good morning. I'm Vishal Singh, presenting the post mid-semester progress of my dissertation, *Retail Sentiment Intelligence — Real-Time Social Media Mining and Trust-Aware Sentiment Analysis Using LLMs for Retail Feedback Optimization*. Since mid-sem the focus has moved from *does the pipeline work?* to *can an analyst act on it, correct it, and feed the corrections back into the model?* The dissertation is carried out at Walmart Global Tech under Mr. Varunendra Pratap Singh, and mentored on the BITS side by Ms. Pradnya Kashikar."

---

## Slide 2 — Agenda

**Content** — 15-item, 2-column grid grouped as: framing (1), feature stack (2 – 10), final numbers (11 – 13), wrap-up (14 – 15).

**Talking track**
> "The deck has three parts. First, what shipped after mid-sem — Review & Validate, Smart Reply, Learning Loop, and four new dashboard pages. Second, the final numbers for ModernBERT, Vision, and Trust. Third, live demo and an honest conclusions + future work. About 22 slides, ~18 minutes."

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

**Framing to close on** — *"Mid-sem answered can the pipeline produce trust-weighted sentiment? Post-midsem answers can an analyst act on it, correct it, and feed the corrections back."*

---

## Slide 4 — Review & Validate (HITL)

**Content**
- Bullets: queue sorted by priority (P1 first) · analyst overrides sentiment / aspect in one click · corrections written to `feedback` · Generate Drafts → three reply options · analyst edits + posts to Reddit · posted replies feed the few-shot pool.
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

**Talking track**
> "The learning loop is what makes 'the system improves over time' concrete. Every human action — corrections, trust overrides, posted replies — writes one row to the `feedback` table. Two things consume that table. The hot loop, every click, uses the last three posted replies as few-shot examples for the reply generator. The warm loop, monthly, exports corrections into the ModernBERT Stage-3 training set for a supervised re-train. No black boxes — every row is queryable in SQLite."

**Deeper detail** — see [LEARNING_LOOP.md](./LEARNING_LOOP.md).

---

## Slide 9 — Post Explorer (Multi-Facet Search)

**Content**
- Left: filter list — sentiment · confidence slider · trust-score slider · subreddit multi-select · aspect (8-item taxonomy) · date range · full-text.
- Right screenshot: `docs/Sem_4/final/figures/ui/post_explorer.png`

**Talking track**
> "Post Explorer is the 'find me 20 posts I care about right now' page. Any combination of the filters can be applied simultaneously; results stream in ranked by priority × recency. Every card links back into Review & Validate."

---

## Slide 10 — Post Lifecycle (Kanban)

**Content**
- 4 states: **TRIAGED → ACKNOWLEDGED → IN PROGRESS → RESOLVED**.
- Screenshot: `docs/Sem_4/final/figures/ui/lifecycle_kanban.png`
- Resolve modal — 2-step flow (save action note + optional reply → paste on Reddit → Mark Resolved).

**Talking track**
> "Lifecycle Kanban tracks a complaint end-to-end. Cards move through four states. The Resolve modal is a two-step flow so posting to Reddit is decoupled from marking the card resolved — the analyst can't accidentally close a card without confirming the reply landed."

---

## Slide 11 — Insights & Competitor Analysis

**Content** — 2 × 2 feature grid: Priority-Negatives · Competitor Pulse · Weekly LLM Summaries · Aspect Drilldown.

**Talking track**
> "Where the other pages are operational, Insights is strategic. It answers 'what should the ops team focus on this week?' — the top issues weighted by volume, severity and recency, along with a cross-brand pulse and an LLM-generated weekly digest."

---

## Slide 12 — Notification Centre

**Content**
- In-app mirror of the group-routed email / Slack digest.
- Screenshot: `docs/Sem_4/final/figures/ui/notifications.png`
- Priority thresholds: **P1** — trust ≥ 0.70 ∧ conf ≥ 0.80  ·  **P2** — trust ≥ 0.50 ∧ conf ≥ 0.60.

**Talking track**
> "Post-midsem we added an in-app notification centre so analysts don't have to leave the dashboard to check emails. Alerts are grouped by team so an OGP analyst doesn't get pinged for a Spark-driver complaint. Same routing rules as the email/Slack digest — powered by the same `alerts` rows."

---

## Slide 13 — ModernBERT — Final Training Results

**Content**
- Three KPI tiles: Overall Macro-F1 **0.6272 → 0.7642**  ·  Long posts (≥ 512 tok, n = 7, all negative) **5/7 → 7/7 correct**  ·  Uplift **+13.7 pts Macro-F1**.
- 3-stage curriculum table (Baseline → Stage 1 → Stage 2 → Stage 3 final).
- Per-length-bucket accuracy: short-to-medium (< 512, n=193) 138/193 → 159/193 correct; long (≥ 512, n=7, all negative-class) 5/7 → 7/7 correct.

**Talking track**
> "Final ModernBERT numbers on 5-fold OOF CV of 200 hand-labelled retail Reddit posts. Macro-F1 climbs the curriculum monotonically. The most dramatic move is on the long bucket — the Twitter-RoBERTa baseline is capped at 512 tokens, so long complaints get truncated. Of the seven ≥512-token posts, all seven happen to be labelled negative by our annotator; RoBERTa gets 5 of 7 right, ModernBERT gets all 7. Two caveats I want to make explicit: n is only 7 and all of them are negative-class, so I read this as evidence the truncation ceiling is gone, not that the model is perfect on long text."

---

## Slide 14 — Vision Pipeline — Multi-Pass Payoff

**Content**
- 4-pass architecture: **STRUCTURE → TILE → EXTRACT → MERGE** (image removed on the final merge → cannot invent visuals).
- Eval on 32 retail screenshots — hallucination 50 → 0 %, text extraction 25 → 75 %, retail-signal recall 40 → 81 %.

**Talking track**
> "Vision was the biggest post-midsem win. Single-pass Gemma 3 4B was hallucinating on half of all images — inventing prices, order numbers, screenshots. The fix was structural: four passes where the last one is a text-only merge with the image removed, so the model physically cannot invent visual details. Zero hallucination on the 32-image gold set. Same caveat as sentiment — 32 images is a pilot, not production evidence."

---

## Slide 15 — Trust-Score — End-to-End Evaluation

**Content**
- Three KPI tiles: Low-trust share **15 %**  ·  Human-agreed **12 / 15**  ·  Agreement rate **80 %**.
- Formula: `trust_score = 0.4·metadata + 0.3·dedup + 0.3·llm_credibility`.
- *Flag, don't drop* — every low-trust post is surfaced with an explanatory chip and can be overridden in one click.

**Talking track**
> "On the 200-post gold set, 15 % of posts fell into the low-trust bucket. When a human annotator cross-checked those 15, they agreed with 12 — 80 % agreement. The score is decomposed into three named components in the dashboard so the analyst can see *why* a post is low-trust and override it if they disagree."

---

## Slide 16 — Evaluation Summary — Post-Midsem Numbers

**Content** — combined 12-row metrics table (sentiment, vision, trust, ops) all measured against the same 200-post gold set.

**Talking track**
> "Consolidated numbers — one table, three subsystems, all evaluated on the same 200-post retail-Reddit gold set. Highlighted rows are the four post-midsem wins."

---

## Slide 17 — Principal Contributions (C1 – C5)

**Content**
- **C1** — Offline-first RSI pipeline.
- **C2** — Fine-tuned ModernBERT with 3-stage curriculum.
- **C3** — Multi-pass vision technique on Gemma 3 4B.
- **C4** — Interpretable trust score + admission gate.
- **C5** — HITL learning-loop dashboard.

**Talking track**
> "Five principal contributions, mapped one-to-one to the sections of the report. C1 is the plumbing, C2 and C3 are the model wins, C4 is the trust design, and C5 is the analyst-facing surface that makes the pipeline usable."

---

## Slide 18 — Live Demo — Dashboard Walkthrough

**Content** — 3 × 2 screenshot grid (Brand Health · Alert Feed · Post Explorer · Review & Validate · Lifecycle Kanban · Insights).

**Talking track**
> "Rather than dropping into a live demo I'll walk through six screens: Brand Health for the top-line KPIs, Alert Feed for what's firing right now, Post Explorer for filtered search, Review & Validate for the correction loop, Lifecycle Kanban for the resolution workflow, and Insights for the strategic view."

*(If time permits, switch to `http://localhost:3001` and demo Review & Validate on the same Sam's Club pizza post from slide 7.)*

---

## Slide 19 — Conclusions — What Worked, What's Still Open

Deliberately grounded — not a green wall of ticks.

**What worked**
- 3-stage ModernBERT curriculum landed the sentiment win we set out for (0.62 → 0.76 on 5-fold OOF).
- Long-post recovery came for free once we switched off truncation  (5/7 → 7/7 correct on the ≥1024-tok context).
- Removing the image on the vision merge step ended the 50 % hallucination problem — the mechanism, not just the number.
- Trust score as *flag-not-drop* matched the annotator on 12 / 15 low-trust posts; analysts trust it because they can override it.
- HITL feedback table quietly became the most useful piece of infrastructure — drives few-shot today, retraining tomorrow.

**What's still open (honest)**
- 200-post gold set is small; a bigger blind held-out set is needed before I'd claim generalisation.
- Vision eval is 32 images — enough to sanity-check the mechanism, not to claim production-grade quality.
- Long bucket has only 7 posts and they are all negative-class — 7/7 correct is evidence the truncation ceiling is gone, not proof of long-text mastery.
- Reply drafts still need an analyst edit — we track edit-distance but haven't shown it dropping consistently yet.
- Everything runs on one Mac. Multi-analyst concurrency and retraining automation aren't done.

**Talking track**
> "Two columns, deliberately. On the left, what worked. On the right, what's still open — because on 200 posts and 32 images, a 100 % green wall would be dishonest. The mechanism-level wins are what I want you to take away; the sample-size caveats are what the next horizon of work has to close."

---

## Slide 20 — Future Work — Grounded 3-Horizon Roadmap

Only items with a clear next step. Everything else lives in the report's Future Work chapter.

- **Now → 1 month** — grow the gold set to ~500 posts using HITL feedback already being produced; rerun 5-fold OOF and check the F1 delta.
- **1 → 3 months** — wire the monthly ModernBERT retrain into a Cron / Airflow job so it stops being a manual notebook run; add a promotion gate on OOF F1.
- **3 → 6 months** — migrate storage to managed Postgres or Cosmos so multiple analysts can use the same feedback table concurrently; extend ingestion beyond Reddit only if the demand from the analyst team is real.

**Deliberately excluded** — auto-reply gate, seasonal P1 forecast, bilingual taxonomy — ideas without a clear next step at this scale. They're in the report's Future Work chapter.

**Talking track**
> "Three horizons, and I've been strict about only listing things that have a clear next step. Growing the gold set is the highest-leverage move at 200 posts. Automating the retrain unblocks the whole learning loop. Concurrency lets more than one analyst use the system without stepping on each other. Everything else — auto-reply, bilingual, P1 forecasting — is in the report; I'm not putting it on this slide because I don't have a first step for it yet."

---

## Slide 21 — Source Code & Deliverables

**Content**
- Repository: `https://gecgithub01.walmart.com/v0s01jh/Retail_Sentiment_Intelligence`
- Deliverables table (report PDF/LaTeX, pipeline core, training scripts, evaluation notebook, dashboard, reproduction guide in Appendix B).

**Talking track**
> "Everything is in the repo — the report LaTeX, the pipeline code, the training scripts, the evaluation notebook, the React dashboard, and the reproduction guide in Appendix B."

---

## Slide 22 — Thank You / Q&A

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

