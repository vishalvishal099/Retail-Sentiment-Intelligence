# Learning Loop — Feedback → Retraining

> Companion note for the Post Mid-Semester deck
> (slide 8 of `FINAL_PRESENTATION_VishalSingh_2020AA05641.pptx`).
> Kept as a standalone document so it can be reused in the final report,
> the viva, or a future presentation.

The **learning loop** is the mechanism that turns every human action taken
in the dashboard into a training signal for the next iteration of the model.
It is what makes the claim "the system improves over time" concrete rather
than aspirational.

---

## 1 · Why the loop exists

Sentiment models trained on Twitter or on general Reddit corpora do not
know about *Walmart's* register short-hand, *Sam's Club*'s membership tier
vocabulary, or *Spark drivers'* app slang. A model checkpoint frozen on the
day of training decays as the language of the community shifts.

The loop closes that gap with **zero engineering effort per week**:

- Every analyst correction is written to a canonical `feedback` table.
- Every posted reply is written to the same table with a different `kind`.
- Two consumers read that table:
  - **Reply generator** — pulls the last 3 posted replies into the few-shot
    prompt on every `Generate Drafts` click (in-context, no retraining).
  - **Sentiment retraining** — on a monthly cadence, corrections are added
    to the Stage-3 fine-tune set and ModernBERT is re-run with 5-fold CV.

---

## 2 · The four capture points

Every place in the dashboard where a human takes an action, that action is
logged with enough context to be replayable during retraining.

| # | UI action | Endpoint | `kind` in `feedback` | Downstream use |
|---|-----------|----------|----------------------|----------------|
| 1 | Correct sentiment / aspects in **Review & Validate** | `POST /api/review/{post_id}` | (no `kind` — it's the primary correction row) | ModernBERT Stage-3 augmentation |
| 2 | Override trust score in **Review & Validate** | same endpoint, `trust_override` field | (same row as #1) | Trust threshold calibration |
| 3 | Post a reply via **Smart Reply Composer** | `POST /api/review/{post_id}/reply` | `auto_reply_posted` | Few-shot pool for FLAN-T5 / GPT / Mistral |
| 4 | Resolve a card in **Post Lifecycle Kanban** | lifecycle upsert | (lifecycle table, not `feedback`) | SLA analytics |

The important design decision: **all these signals live in one table**.
That means the retraining script has to know exactly one schema, and the
dashboard has to write to exactly one place.

---

## 3 · The `feedback` table — schema in detail

Two shapes coexist in `feedback` depending on `kind`. Both share the same
top-level fields so the retraining script can filter with a single JSON
predicate.

### 3.1 Label / aspect / trust correction (`kind` unset or `label_correction`)

```json
{
  "id": "fb_1nn7hjxx_1735689012",
  "post_id": "1nn7hjxx",
  "analyst_id": "vishal.singh",
  "original_sentiment": "neutral",
  "corrected_sentiment": "negative",
  "original_aspects": ["product_quality"],
  "corrected_aspects": ["product_quality", "store_experience"],
  "trust_override": 0.62,
  "notes": "Also complains about store staff refusing to help",
  "created_at": "2026-08-01T09:26:04Z",
  "partition_key": "vishal.singh"
}
```

Written by `submit_review()` in `src/dashboard/api.py`. When the write
succeeds, the same call also updates the `analyses` row:

- `sentiment` ← `corrected_sentiment`
- `sentiment_confidence` ← `1.0` (human-validated)
- `aspects` ← `corrected_aspects`
- `trust_score` ← `trust_override` if provided
- `human_validated` ← `true`

That way the correction flows through **immediately** to Brand Health,
Post Explorer, drilldowns, and every KPI — the analyst doesn't wait for a
retrain to see their fix.

### 3.2 Posted reply (`kind = "auto_reply_posted"`)

```json
{
  "id": "reply_1nn7hjxx_1735689612",
  "kind": "auto_reply_posted",
  "post_id": "1nn7hjxx",
  "analyst_id": "vishal.singh",
  "reply_text": "Really sorry the pizza's been sitting in the hot case that long — DM me the club number and I'll flag it to the bakery-café team. — Ravi",
  "created_at": "2026-08-01T09:36:12Z",
  "partition_key": "vishal.singh"
}
```

Written by `save_reply()` in `src/dashboard/api.py`. This is also the row
that gets picked up on the **next** `Generate Drafts` call as a few-shot
example.

---

## 4 · How each signal is consumed

### 4.1 Posted reply → Smart Reply few-shot (in-context, live)

- **Frequency:** every `Generate Drafts` click
- **Query:** `SELECT data FROM feedback WHERE json_extract(data, '$.kind') = 'auto_reply_posted' ORDER BY json_extract(data, '$.created_at') DESC LIMIT 5;`
- **Consumer:** `_collect_reply_examples()` → `_build_reply_prompt()`
- **Cost:** zero training; +~200 tokens per LLM call
- **Latency to effect:** the next reply the analyst generates already sees
  the one they just posted

This is the *hot loop*. It closes on itself in seconds.

### 4.2 Label correction → ModernBERT Stage-3 augmentation (monthly)

- **Frequency:** operational cadence — recommendation is monthly
- **Consumer:** `scripts/train_modernbert_sentiment.py --stages 3`
- **Data flow:**
  1. Export corrections:
     ```sql
     SELECT post_id, corrected_sentiment, corrected_aspects
     FROM feedback
     WHERE corrected_sentiment IS NOT NULL
       AND created_at > <last_train_date>;
     ```
  2. Join to `raw_posts` to get the post text.
  3. Append to the Walmart-200 gold set → **Walmart-N**.
  4. Re-run Stage-3 (5-fold stratified CV) with the augmented set.
  5. Save the new best checkpoint to `models/modernbert_walmart/`.
- **Expected effect:** ModernBERT already reaches Macro-F1 0.7642 on 200
  labels; every additional 50 corrections adds roughly +0.01–0.02 F1 based
  on the Stage-2 → Stage-3 curve.

This is the *warm loop*. It closes on a monthly cadence.

### 4.3 Trust override → threshold calibration

- **Frequency:** whenever a batch of overrides accumulates
- **Consumer:** offline notebook (`evaluation/trust_score_walmart200.ipynb`)
- **What it does:** re-fits the P1 / P2 thresholds and the metadata /
  dedup / LLM weights so that the score bracket the analyst *actually*
  overrides to matches the automated tier the next time around.

---

## 5 · End-to-end example — one loop iteration

Using the same Sam's Club stale-pizza post from
[`SMART_REPLY_COMPOSER.md`](./SMART_REPLY_COMPOSER.md#5--worked-example--a-real-post-from-our-benchmark):

1. **T=0** — Post `1nn7hjxx` lands in `raw_posts` from the Arctic Shift
   ingest.
2. **T+~30 s** — Pipeline classifies it: `negative`, aspects
   `[product_quality, store_experience]`, trust 0.62 → **P2** → shows up in
   Review queue.
3. **T+~5 min** — Analyst opens the post. Model said `product_quality`
   only; analyst adds `store_experience` (they consider the "staff refused
   to help" side of the complaint). This writes row #1 above.
   → `analyses` row updated immediately, disappears from queue.
4. **T+~6 min** — Analyst clicks **Generate Drafts**. The prompt now
   includes the three most recent posted replies as few-shot examples.
   Analyst picks Draft A, edits the sign-off.
5. **T+~7 min** — Analyst clicks **Save & Open Reddit**. Row #2 above is
   written. Card auto-transitions to **Resolved** in the Kanban.
6. **T+~1 day** — A new Sam's Club pizza complaint comes in. The prompt for
   *its* draft now includes the reply we just posted at step 5. The new
   drafts sound more like our team out of the box.
7. **T+~30 days** — Retraining cadence hits. The correction from step 3
   (label + aspect override) is exported and included in the Stage-3
   augmented set. ModernBERT is re-run; new checkpoint deployed.

Every step above is deterministic and inspectable — nothing hidden.

---

## 6 · Code map

| Concern | File | Symbol |
|---------|------|--------|
| Write label / aspect / trust correction | `src/dashboard/api.py` | `submit_review(post_id, correction)` |
| Apply correction to analyses row | `src/dashboard/api.py` | same function — inline block |
| Write posted-reply row | `src/dashboard/api.py` | `save_reply(post_id, payload)` |
| Read posted replies for few-shot | `src/dashboard/api.py` | `_collect_reply_examples(limit=5)` |
| Build few-shot prompt | `src/analysis/llm_client.py` | `_build_reply_prompt` |
| Lifecycle state transition | `src/dashboard/api.py` | `_ensure_lifecycle_reply_sent` |
| Stage-3 retraining | `scripts/train_modernbert_sentiment.py` | `run_stage3(args, tokenizer, stage2_model_path)` |
| Feedback audit UI | `frontend/src/pages/ReviewQueue.tsx` | *Feedback History* pane |

---

## 7 · Monthly retraining playbook (recommended cadence)

Run each first Monday of the month, ~30 minutes on an M-series Mac.

```bash
# 1. Export new corrections (last 30 days)
python scripts/export_feedback_for_training.py \
       --since 30d \
       --out data/walmart_augmented.jsonl

# 2. Sanity-check the export (class distribution, dedup)
python scripts/eval_sentiment_models.py --dataset data/walmart_augmented.jsonl

# 3. Rerun Stage-3 with the augmented set
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
  python scripts/train_modernbert_sentiment.py \
       --stages 3 \
       --folds 5 \
       --max-length 1024 \
       --batch-size 8 \
       --walmart-data data/walmart_augmented.jsonl

# 4. Copy the new best checkpoint into production
cp -r models/modernbert_walmart/stage3_walmart/best \
      models/modernbert_walmart_v$(date +%Y%m)/

# 5. Point config/models.yaml → sentiment.model at the new folder & restart
```

The current release runs `run_stage3` fully offline in ~28 min on an M2 Pro
(24-min training, 4-min eval on 5 folds). Retraining does not need any
Walmart-internal network or GPU access.

---

## 8 · Roadmap — from monthly to continuous

Today the loop is:

```
    [dashboard]  →  feedback table  ─┐
                                      ├──> few-shot slot (live, every click)
                                      └──> retraining set (manual, monthly)
```

The near-term roadmap replaces the *manual monthly* leg with an automated
one:

- **Airflow / Kubernetes CronJob** — nightly export from `feedback` into
  `data/walmart_augmented.jsonl`, weekly Stage-3 rerun if new corrections
  exceed a threshold.
- **Model registry** — every rerun writes a new checkpoint to a versioned
  folder + drift metrics; production symlink is updated only if the new
  checkpoint beats the current on the held-out 5-fold OOF F1.
- **Auto-reply confidence gate** — once analyst edit-distance on the LLM
  drafts drops below a threshold on 200 consecutive replies, the drafts
  are promoted from "suggested" to "queued for send" (the automation
  target described in the final report's Future Work chapter).

The infrastructure to do all of this is already in place: `feedback`
schema is stable, the retraining script is idempotent, and the model
folder layout is versionable.

---

## 9 · Talking-track cheatsheet (viva prompts)

- *"Show me exactly where a correction goes."* — Open the Review panel,
  correct a post, then run
  `sqlite3 data/local.db 'SELECT data FROM feedback ORDER BY rowid DESC LIMIT 1'`.
  You will see the row from §3.1.
- *"How does this correction actually influence the model?"* — Two ways.
  Immediately, the analyses row is overwritten so every downstream chart
  reflects the correction. On the monthly retraining cadence, the row is
  concatenated to the Walmart-200 gold set and ModernBERT Stage-3 is
  re-run.
- *"Aren't you cheating by testing on the same data you train on?"* — No.
  Stage-3 uses **5-fold stratified out-of-fold cross-validation**. Every
  post appears in the validation set of exactly one fold and is scored by
  a model that was never trained on it (see §3.2 of the report).
- *"What if analysts make mistakes?"* — Each row carries `analyst_id`. In
  a multi-analyst deployment (future work) we can require 2-of-N agreement
  before a correction is admitted to the retraining set.
- *"Is this reinforcement learning?"* — No — it's plain supervised
  learning with a growing dataset (for ModernBERT) plus in-context learning
  (for the reply generators). Deliberately kept simple because analyst
  volume is still modest.
- *"How does the reply generator get better without training?"* — Every
  posted reply is a new few-shot example. The next `Generate Drafts` call
  sees the last three posted replies in its prompt and biases toward
  their tone. This is standard in-context learning.
