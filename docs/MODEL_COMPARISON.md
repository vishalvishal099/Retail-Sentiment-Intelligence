# Sentiment Model Comparison — Why We Picked Fine-Tuned ModernBERT

**Context.** The pipeline classifies every Walmart-Reddit post into
`positive` / `neutral` / `negative` plus a confidence score. Until 2026-06-18
we used `cardiffnlp/twitter-roberta-base-sentiment-latest` zero-shot — a
strong public baseline that nevertheless has two structural weaknesses for
this domain: (1) it was trained on tweets, not Reddit long-form complaints,
and (2) it is capped at 512 tokens, so any post longer than that is silently
truncated. This chapter documents how we replaced it with a fine-tuned
`answerdotai/ModernBERT-base` and what the swap was worth.

The headline result: **macro F1 0.6272 → 0.7642 (+0.137)** overall, and
**7 / 7 correct on long posts (≥ 512 tokens, n = 7, all negative-class)** vs 5 / 7 for the RoBERTa baseline — the truncation ceiling that limited RoBERTa is removed
ModernBERT's 8192-token context was supposed to deliver.

---

## 1. Selection Criteria

In priority order:

1. **Domain fit** — Reddit-flavored long-form Walmart complaints (median 595
   chars, max 3604) differ stylistically from tweets, especially for the
   neutral and positive classes that the baseline regularly confused.
2. **Long-context capability** — ~7% of our annotated posts exceed RoBERTa's
   512-token cap; the truncation drops exactly the receipt details, store
   timelines, and resolutions that determine sentiment.
3. **Local-first, free, no API keys** — same constraint as the rest of the
   pipeline (Ollama / HF only by default; cloud LLMs gated behind explicit
   keys).
4. **Apple-silicon MPS friendly** — must train and serve on the dev machine
   without CUDA.
5. **Defensibility for thesis** — we want honest cross-validated numbers,
   not memorization on the eval set.

## 2. Candidates Evaluated

| # | Model | Vendor | Tokens | Size | Why considered |
|---|---|---|---|---|---|
| 1 | **RoBERTa twitter-sentiment-latest** | Cardiff NLP | 512 | 499 MB | Current baseline, top of the TweetEval leaderboard |
| 2 | **DeBERTa-v3-base zero-shot-v2** | MoritzLaurer | 512 | 184 MB | Already in the stack for aspect tagging — cheap to test on sentiment |
| 3 | **ModernBERT-base** | answer.ai | **8192** | 596 MB | New (2024) encoder explicitly designed for long context, retains BERT throughput |
| 4 | **Llama-3.1-8B (Ollama)** | Meta | 128k | 4.7 GB | LLM-as-judge fallback; expensive and overkill for a 3-class task |

We kept **(1)** as the baseline and chose **(3)** as the production model.
DeBERTa-v3 zero-shot was rejected because it has the same 512 cap and adds no
domain knowledge. Llama-3.1 was rejected because per-post latency (~600 ms)
breaks the dashboard refresh budget for ~1 ms what we ship today.

## 3. Dataset

- **`data/benchmark_real_200.jsonl`** — 200 long-form Walmart-Reddit posts,
  hand-labeled with assistance.
- **Source split:** walmart=70, samsclub=44, Sparkdriver=30,
  WalmartEmployees=28, OGPBackroom=19, walmartogp=9.
- **Body length:** min=300 chars, median=595, max=3604.
- **Class distribution:** negative=127 (63.5%), neutral=65 (32.5%),
  positive=8 (4.0%) — consistent with what one expects in a customer-complaint
  forum, but heavy class imbalance is a real problem for the positive class.
- **Annotation protocol:** AI-assisted labeling with full human review per
  post; suggestions accepted in 200/200 cases (a fact noted as a defensibility
  caveat — see [section 8](#8-honesty-caveats-and-limits)).
- **Long-post bucket:** 7 of the 200 posts (3.5%) tokenize to ≥512 tokens
  with the RoBERTa tokenizer. Small in absolute count, but exactly the
  posts that the legacy model could not see in full.

## 4. Training Protocol

We fine-tuned ModernBERT-base in a **3-stage curriculum**:

| Stage | Dataset | Epochs | Purpose | Final macro F1 |
|---|---|---|---|---|
| 1 | TweetEval-sentiment (45 k tweets) | 2 | Generic sentiment grounding | 0.7267 |
| 2 | GoEmotions-3class (54 k Reddit comments) | 2 | Reddit register + sentiment polarity | 0.7028 |
| 3 | Walmart-200, 5-fold stratified CV | up to 15 (early-stop patience 3) | Domain specialization | **0.7362 ± 0.1155** |

Stage-3 details (the one that matters for the thesis):

- **Stratified 5-fold CV** with `seed=42`. Reported numbers are
  out-of-fold predictions — every sample is predicted by a fold model
  that never trained on it.
- **Class weights:** `neg=0.52, neu=1.03, pos=8.33` via a
  `WeightedTrainer.compute_loss` override (subclass of HF `Trainer`).
- **Oversampling:** minority classes oversampled to ~100 per class within
  each training fold (≈303 training samples per fold).
- **Optimizer:** AdamW, LR=2e-5, weight-decay=0.01, warmup 10%.
- **Effective batch size 32** (per-device BS=8, grad-accum=4) — the largest
  setting that fits in 18 GB MPS memory at `max_length=1024`.
- **Max length: 1024 tokens** — the central design choice. We ablated
  `max_length=512` (v1) and `max_length=1024` (v2); see
  [section 6](#6-ablation-context-length).
- **Early stopping:** `patience=3` on `eval_macro_f1`, `metric_for_best_model`
  set accordingly.

After the cross-validation step, we trained one **final deployable model**
on all 200 posts using the same recipe (15 epochs, train_loss=0.345). This
is the artifact at `models/modernbert_walmart/final/` that the production
pipeline now loads — but **it is never used to compute the numbers in this
chapter** because evaluating it on its own training data would be
memorization, not measurement.

## 5. Evaluation Protocol

To avoid the memorization trap above:

- The **RoBERTa baseline** is run zero-shot in inference mode (it has never
  seen our data).
- The **ModernBERT** numbers come from **out-of-fold CV predictions**: each
  of the 200 posts has a single prediction made by the fold whose training
  set excluded it. Aggregating these 200 OOF predictions yields the
  confusion matrix and per-class F1 reported below.

This is implemented in [scripts/eval_sentiment_models.py](../scripts/eval_sentiment_models.py),
which loads CV predictions from
[models/modernbert_walmart/stage3_walmart/cv_results.json](../models/modernbert_walmart/stage3_walmart/cv_results.json)
and asserts index alignment with the benchmark file.

Length buckets are computed against the **RoBERTa tokenizer** (`short_lt512`,
`long_gte512`) so the bucket assignment is a property of the input text, not
the model under test.

## 6. Ablation: Context Length

We ran the full Stage-3 protocol twice — once at `max_length=512` (v1, kept
for ablation), once at `max_length=1024` (v2, shipped):

| Variant | Macro F1 (OOF) | CV std | Pos F1 | Long-bucket correct |
|---|---|---|---|---|
| ModernBERT v1 (max_length=512) | 0.7233 | 0.1388 | 0.62 | 6/7 |
| **ModernBERT v2 (max_length=1024)** | **0.7642** | **0.1155** | **0.67** | **7/7** |

Going from 512 → 1024 tokens improved overall macro F1 by +0.041, **lowered
fold-to-fold variance by 17%** (0.1388 → 0.1155), and recovered the last long
post the 512-token variant mis-classifies (6/7 → 7/7). This is the empirical
justification for the `max_length: 1024` line in
[config/models.yaml](../config/models.yaml).

We did **not** push to 2048: only 7 posts hit the long bucket, we already
classify all seven correctly at 1024, and 2048 doubles training time on MPS.

## 7. Final Results (RoBERTa vs ModernBERT v2)

### 7.1 Headline numbers

| Metric | RoBERTa baseline | **ModernBERT v2** | Δ |
|---|---|---|---|
| Macro F1 (OOF) | 0.6272 | **0.7642** | **+0.137** |
| F1 — negative | 0.7967 | 0.8779 | +0.081 |
| F1 — neutral | 0.6087 | 0.7480 | +0.139 |
| F1 — positive | 0.4762 | 0.6667 | +0.190 |
| Latency (ms / post, MPS, warm) | 6.5 | 11.9 | +5.4 |

### 7.2 Length-bucketed results — the thesis axis

| Bucket | Baseline correct | **ModernBERT v2 correct** | Recovered |
|---|---|---|---|
| `short_lt512` (n=193)                    | 138 / 193 (72 %) | **159 / 193 (82 %)** | **+21** |
| `long_gte512` (n=7, all negative-class)  | 5 / 7             | **7 / 7**             | **+2**  |

Both buckets benefit from fine-tuning, but the long bucket is where the
8192-token architecture pays for itself: RoBERTa simply cannot read the
last paragraph of a 1200-word post, and that paragraph is often where the
customer states whether the issue was resolved.

### 7.3 Confusion matrices

**RoBERTa baseline** (rows=truth, cols=prediction):

|       | neg | neu | pos |
|---|---|---|---|
| neg   | 96  | 28  | 3   |
| neu   | 18  | 42  | 5   |
| pos   | 0   | 3   | 5   |

**ModernBERT v2:**

|       | neg | neu | pos |
|---|---|---|---|
| neg   | 115 | 12  | 0   |
| neu   | 17  | 46  | 2   |
| pos   | 3   | 0   | 5   |

ModernBERT recovers an extra 19 negative posts (from 96 → 115) and reduces
neg→neu confusion from 28 to 12 — exactly the "false-equivalence" failure
mode that previously diluted alert volume on the dashboard.

### 7.4 Per-fold detail

| Fold | Macro F1 | Train loss converges to |
|---|---|---|
| 1 | 0.5864 | 0.029 |
| 2 | 0.9231 | 0.019 |
| 3 | 0.6524 | 0.017 |
| 4 | 0.7356 | 0.021 |
| 5 | 0.7838 | 0.000 |
| **Mean ± std** | **0.7362 ± 0.1155** | — |

The per-fold spread (std=0.115) is the single most important caveat in
this report. It is dominated by the positive class (n=8): missing the
single positive example in fold 1 zeros out positive F1 in that fold and
drops the macro by ~0.10. Negative F1 is much more stable
(0.8781 ± 0.0348).

## 8. Honesty Caveats and Limits

- **n=200 is small.** All numbers should be read as point estimates with
  ±0.05 macro-F1 uncertainty (one minority-class flip is worth ~0.04).
- **Per-fold variance.** std=0.115 is high. Future work: 3-seed ensemble or
  enlarging the positive class via targeted re-sampling of the Arctic Shift
  cache.
- **AI-assisted labeling acceptance was 100%.** The annotator agreed with
  the model suggestion on every post. Mitigation: a blind 25-post recheck
  is planned (`label_benchmark.py --recheck --sample 25 --seed 7`); until
  that ships, treat the labels as "validated" not "independent".
- **Final model evaluated only via CV.** The deployable model in
  `models/modernbert_walmart/final/` was trained on all 200 posts, so it
  has no held-out test set. This is intentional — it maximizes training
  data for production — but the numbers we report come from the CV folds,
  not from the final model.
- **One dataset, one register.** Numbers are valid for Walmart-flavored
  Reddit complaints. Generalization to Twitter, support-ticket, or
  in-app-review text is not claimed.

## 9. Production Wiring

The fine-tuned model is the default sentiment classifier as of commit
[2026-06-18]. Routing logic:

- **`config/models.yaml`** — `models.sentiment.model =
  models/modernbert_walmart/final`, `max_length=1024`,
  `fallback_model: cardiffnlp/twitter-roberta-base-sentiment-latest`.
- **`src/analysis/llm_client.py`** — `HuggingFaceSentimentClient` reads
  model name + `max_length` from the registry and falls back to RoBERTa if
  the local checkpoint is missing (e.g. fresh clone before training has
  been run).
- **Truncation** — the legacy `text[:512]` character-truncation was
  replaced with `text[: max_length * 4]` to feed enough characters into the
  tokenizer for the 1024-token budget; the tokenizer's `truncation=True`
  enforces the actual token cap.

## 10. Reproduction

```bash
# Train (offline once HF cache is populated)
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
TOKENIZERS_PARALLELISM=false /opt/miniconda3/bin/python \
  scripts/train_modernbert_sentiment.py \
  --batch-size 32 --stages 3 --epochs-s3 15

# Honest evaluation (CV out-of-fold preds vs RoBERTa baseline)
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
TOKENIZERS_PARALLELISM=false /opt/miniconda3/bin/python \
  scripts/eval_sentiment_models.py
```

Artifacts:

- [models/modernbert_walmart/stage3_walmart/cv_results.json](../models/modernbert_walmart/stage3_walmart/cv_results.json) — per-fold + per-sample CV predictions
- [models/modernbert_walmart/eval_results.json](../models/modernbert_walmart/eval_results.json) — RoBERTa vs ModernBERT comparison
- [models/modernbert_walmart/final/](../models/modernbert_walmart/final) — deployable checkpoint
- [models/modernbert_walmart/stage3_walmart/cv_results_max512.json](../models/modernbert_walmart/stage3_walmart/cv_results_max512.json) — v1 ablation (max_length=512)

## 11. Future Work

1. **3-seed ensemble** — average logits from seeds 7/13/42; expected ±0.02 F1
   gain and tighter std.
2. **Positive-class augmentation** — back-translation or targeted re-sampling
   of the Arctic Shift cache to lift n_pos from 8 to ~25.
3. **Blind recheck** — independent re-labeling of a 25-post sample to
   defend against the 100% AI-acceptance critique.
4. **Calibration** — temperature scaling on a held-out fold so the
   confidence scores can be used as a `needs_review` gate.
5. **Aspect-conditioned sentiment** — current per-aspect sentiment is
   inherited from the post-level prediction; a multi-task head sharing the
   ModernBERT trunk would let aspect F1 follow the same gains.
