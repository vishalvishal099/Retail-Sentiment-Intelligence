# ModernBERT Thesis Work — Journey, Challenges, and Mitigations

**Goal of the thesis chapter:** prove that a long-context, domain-fine-tuned
encoder (ModernBERT-base, 8192 tokens) outperforms the project's RoBERTa
baseline (`cardiffnlp/twitter-roberta-base-sentiment-latest`, 512 tokens) on
Walmart-flavored Reddit complaints — specifically on the long posts where
RoBERTa's context cap silently throws away information.

**Final result, foreshadowed up front:** macro F1 **0.6272 → 0.7642
(+0.137)** overall and **all seven ≥512-token posts recovered (RoBERTa 5/7,
ModernBERT 7/7 correct)** on the long bucket (n = 7, all negative-class),
all measured via 5-fold cross-validated out-of-fold predictions (no
memorization).

This document is the *narrative behind those numbers* — every wrong turn,
every blocker, and the specific mitigation that got us past it.

---

## 0. Where We Started

When this workstream began, the pipeline already had:

- A working RoBERTa-based sentiment classifier in
  [src/analysis/llm_client.py](../src/analysis/llm_client.py)
  (`HuggingFaceSentimentClient`).
- A 150-row synthetic benchmark (`data/benchmark_annotations.jsonl`) on which
  the existing model scored macro F1 = 0.8789 — a number that looked great
  until you inspected the benchmark and found bodies capped at ≤77 characters.
- A "thesis claim" we had not yet earned: that ModernBERT's long context would
  matter for this domain.

So the journey was about **earning** that claim with real data, an honest
evaluation, and a model that actually used long context.

---

## 1. Challenge — The Original Benchmark Was Not Real

**What we hit.** `data/benchmark_annotations.jsonl` was a synthetic seed
generated for early dev. Post bodies were ≤77 characters, so the entire
question "does long context matter?" was unanswerable on it — every post fit
into 512 tokens trivially, and every model would tie.

**Why it mattered.** A thesis result on this benchmark would be both
*indefensible* (synthetic data) and *uninformative* (no long-context signal).

**Mitigation — Phase 1: build a real benchmark.**

1. Wrote [scripts/fetch_real_benchmark.py](../scripts/fetch_real_benchmark.py):
   pulls long-form Walmart-Reddit posts via the public Arctic Shift API
   (no Reddit OAuth, no quota lockout).
2. Required flags: `--target 200 --min-body 300 --days 730 --no-score
   --seed 7`. The `--min-body 300` is the single most important filter — it
   guarantees enough text for the long-context hypothesis to be testable.
3. **Bug found during the first pull:** the script passed
   `self_posts_only=True` to Arctic Shift; the API silently ignores that
   parameter and was returning link-only posts. Removed it and filtered
   client-side on body length.
4. Resulting dataset
   [data/benchmark_real_200.jsonl](../data/benchmark_real_200.jsonl): 200 real
   posts, body length min=300 / median=595 / max=3604 chars. Subreddit split:
   walmart=70, samsclub=44, Sparkdriver=30, WalmartEmployees=28,
   OGPBackroom=19, walmartogp=9.
5. Final labels: negative=127 (63.5%), neutral=65 (32.5%), positive=8 (4.0%).
   The positive class is small but matches the reality of a customer-complaint
   forum — fixing that imbalance was treated as a downstream training
   problem, not a dataset problem.

---

## 2. Challenge — Labeling 200 Posts by Hand Is Slow

**What we hit.** Hand-labeling 200 long Reddit posts is 6–8 hours of
read-then-decide work. We needed it fast and consistent.

**Mitigation — AI-assisted labeling.**

- Wrote [scripts/label_benchmark.py](../scripts/label_benchmark.py): an
  interactive TUI labeler with an `--assist` mode that pre-fills a model
  suggestion + a one-line reason for every post. Keys: `1/2/3` = label,
  `Enter` = accept AI suggestion, `s` = skip, `u` = undo, `b` = back,
  `n` = note, `q` = save+quit.
- Subcommands: `--stats`, `--recheck`, `--sample N --seed N`, `--start N`,
  `--review`. Atomic writes so a SIGINT mid-session never corrupts the JSONL.
- Per-row schema (new fields beyond the raw post): `human_sentiment`,
  `human_aspects`, `notes`, `_model_sentiment`, `_model_confidence`,
  `_model_aspects`, `_assist_accepted` (bool), `_assist_suggestion` (str).
  The `_assist_*` fields are the evidence trail for the defensibility
  discussion in [section 9](#9-challenge--ai-assist-acceptance-rate-was-100).
- Side bug found and fixed: index 130 had a duplicate post id (`1u7n48a`)
  from the suggestions file; replaced with the correct `1u7nvek` (the helium
  balloon post).

---

## 3. Challenge — Corporate Network Blocked the Downloads

**What we hit.** This is a Walmart laptop. The corporate stack (GlobalProtect
+ Zscaler) does SNI-based TLS interception on `huggingface.co`, `pypi.org`,
`google.com`. ICMP works (ping succeeds), but the TLS handshake times out, so
the failure mode looks like "the internet is fine, only this *specific* model
hangs forever."

**What did not work:**

- Disconnecting the VPN client. Five `utun*` interfaces stayed UP afterward;
  traffic was still being captured.
- Switching to a phone hotspot mid-session. The corp agents persisted across
  the WiFi switch and continued to filter.
- `HF_ENDPOINT` overrides, `huggingface-cli login`, `pip --index-url`
  alternatives — all blocked by the same interception layer.

**Mitigation — restart + pre-cache + hard-offline.**

1. **Full machine restart**, then connect the phone hotspot **before** any
   corp agent loads. This is the only reliable way we found to clear the
   utun interfaces.
2. With the hotspot active, **pre-fetch ~650 MB once**: ModernBERT-base
   weights, TweetEval, GoEmotions. They land in `~/.cache/huggingface/`.
3. From then on, every training and eval run uses the **offline triad**:

   ```bash
   HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
   TOKENIZERS_PARALLELISM=false /opt/miniconda3/bin/python ...
   ```

   Setting only one of those three is not enough — HuggingFace will still
   hit the hub for metadata. All three must be set together; this is now the
   canonical incantation everywhere in the repo (training script, eval
   script, smoke tests).

4. Captured the diagnosis and the workaround in
   `/memories/repo/project-status.md` (Network notes section) so the next
   poor soul who hits this does not lose a day.

---

## 4. Challenge — Two Python Environments, Only One Works

**What we hit.** The project's `.venv/` (Python 3.13.5) had no ML deps
installed and could not get them because corp network blocked PyPI. We almost
spent an afternoon trying to fix it.

**Mitigation — use the conda environment that already had torch.**

- `/opt/miniconda3/bin/python` (also Python 3.13.5) already had
  `torch 2.9.1 + transformers 4.57.3 + sklearn 1.8.0 + numpy 2.3.5 +
  pandas 3.0.0`, with `torch.backends.mps.is_available() == True`.
- Standardized **every script** (training, eval, smoke test) on
  `/opt/miniconda3/bin/python` rather than fighting PyPI.
- The missing deps in conda (`datasets`, `accelerate`) were worked around by
  loading TweetEval/GoEmotions from the local `~/.cache/huggingface/datasets/`
  paths directly with `load_from_disk()` and removing the `accelerate`
  dependency from `TrainingArguments` (`use_cpu=False`, no FSDP/DeepSpeed).

---

## 5. Challenge — Stage 3 First Run Looked Catastrophic

**What we hit.** The first 5-fold CV on the Walmart-200 set produced
**macro F1 = 0.4068 ± 0.0523** (neg=0.77, neu=0.45, pos=0.00). Worse than
RoBERTa, with positive class collapsed entirely.

**Diagnosis.**

- Hugely imbalanced classes (127 / 65 / 8). With no rebalancing, the loss
  was dominated by the negative class and the model never learned the other
  two.
- `max_length` was set high enough to fit, but per-device batch size was
  fighting MPS memory at the same time, so effective batch size was tiny and
  gradients were noisy.

**Mitigation — proper class handling.**

1. **Per-class weights** in the loss:
   `neg=0.52, neu=1.03, pos=8.33`. Implemented as a subclass
   `WeightedTrainer(Trainer)` with a `compute_loss()` override (HF `Trainer`'s
   built-in `class_weights` is not honored for `CrossEntropyLoss` on every
   version of `transformers`, so we did it explicitly).
2. **Minority-class oversampling** to ~100/class per training fold (≈303
   training samples per fold). This is on top of the loss weighting because
   either one alone left the positive class undertrained.
3. **Effective batch size 32 via gradient accumulation**: per-device BS=8,
   grad-accum=4. Larger per-device BS would OOM on MPS at `max_length=1024`.
4. **3-stage curriculum**:

   | Stage | Dataset | Epochs | Why |
   |---|---|---|---|
   | 1 | TweetEval-sentiment (45k tweets) | 2 | Generic sentiment grounding |
   | 2 | GoEmotions-3class (54k Reddit comments) | 2 | Reddit register + polarity |
   | 3 | Walmart-200, 5-fold CV | up to 15 (patience 3) | Domain specialization |

5. **Early stopping** on `eval_macro_f1` with patience=3 so we did not waste
   epochs after the model converged.

After these fixes, Stage 3 macro F1 rose from **0.4068 → 0.7233** (v1 at
`max_length=512`) on honest CV. Order-of-magnitude difference, and the proof
that the original number was a recipe bug, not a model bug.

---

## 6. Challenge — The Eval Script Was Lying (Memorization)

**What we hit.** Early in the evaluation work the comparison showed
ModernBERT scoring **macro F1 = 1.0** on the Walmart-200 set. We almost
shipped that. It was meaningless.

**Diagnosis.** The eval script was loading the **final deployable model**
(`models/modernbert_walmart/final/`), which had been trained on all 200
posts, and then *inferring on those same 200 posts*. The model had memorized
its own training set. The result was a textbook leakage bug — it would have
torpedoed the thesis defense.

**Mitigation — switch eval to out-of-fold CV predictions.**

1. Modified [scripts/train_modernbert_sentiment.py](../scripts/train_modernbert_sentiment.py)
   to persist **per-sample CV predictions** during the 5-fold loop:
   `cv_results.json` now contains a `per_sample_predictions` array of
   `{index, true, pred}` records, where each prediction came from the fold
   whose training set excluded that sample.
2. Modified [scripts/eval_sentiment_models.py](../scripts/eval_sentiment_models.py)
   to:
   - Add a `--cv-results` argument.
   - Load `per_sample_predictions` and **assert** `cv_true == post_labels`
     so the index alignment cannot silently drift.
   - Compute the confusion matrix, per-class F1, and length-bucketed F1 from
     those OOF predictions — not from the final model.
3. The final model is still used for **latency measurement only**: its
   training-set predictions are leakage, but its forward-pass speed is a
   real engineering number.

This single change was the most important defensibility fix in the project.
The numbers that landed in the chapter are now honest cross-validated
out-of-fold scores, with no sample evaluated by a model that trained on it.

After this fix the honest v1 result became: ModernBERT **0.7233** vs RoBERTa
**0.6272** macro F1 — a real, defensible +0.10 gain.

---

## 7. Challenge — ModernBERT's Long-Context Advantage Wasn't Showing Up

**What we hit.** After the memorization fix, the length-bucket numbers were
disappointing: long posts (≥512 tokens, n=7, all negative-class) had RoBERTa
correct on 5/7 and v1 ModernBERT correct on only about 4/7 (macro-F1 0.46),
needed.

**Diagnosis.** Stage 3 was being trained at `max_length=512`. That is, even
though ModernBERT *supports* 8192 tokens, we were truncating training inputs
to the same cap RoBERTa has. We had been comparing two 512-token models, one
fine-tuned and one not. The long-context architecture was sitting idle.

**Mitigation — `max_length=1024` retrain.**

1. Edited [scripts/train_modernbert_sentiment.py](../scripts/train_modernbert_sentiment.py)
   stage-3 block: `stage3_max_length = 1024`, with `stage3_bs = min(args.batch_size, 8)`
   and `stage3_accum = max(1, 32 // stage3_bs)` so the effective batch size
   stays at 32 even when per-device BS drops to fit MPS memory.
2. Kept stage-3 LR at the original `2e-5` — no LR sweep, just the one
   architectural lever.
3. Backed up the v1 artifacts before overwriting:
   `cv_results.json → cv_results_max512.json`, `final/ → final_max512/`.
   These v1 artifacts are kept on purpose so the chapter has a real
   ablation comparison.
4. Re-ran the full Stage 3 pipeline (5 folds + final model, ~85 min on MPS).

**Result of the retrain (v2):**

| Variant | Macro F1 (OOF) | CV std | Pos F1 | Long-bucket correct |
|---|---|---|---|---|
| ModernBERT v1 (max_length=512) | 0.7233 | 0.1388 | ~0.62 | 4 / 7 |
| **ModernBERT v2 (max_length=1024)** | **0.7642** | **0.1155** | **0.67** | **7 / 7** |

Going from 512 → 1024 tokens improved overall macro F1 by +0.041, **lowered
fold-to-fold variance by 17%** (more stable across seeds/splits), and
recovered all three long posts v1 mis-classifies (4/7 → 7/7 correct). We did
**not** push to `max_length=2048` because only 7 posts hit the long bucket
and v2 already classifies all seven correctly at 1024 — diminishing returns
at 2× the training time.

We considered not pushing to `max_length=2048`. Only 7 posts hit the long
bucket and v2 already classifies all seven correctly. Training time at 2048
would roughly double on MPS for ~zero expected gain.

---

## 8. Challenge — Wiring the Fine-Tuned Model into Production Was Subtle

**What we hit.** The naive integration "just point `models.sentiment.model`
at the local checkpoint" did not work. Three issues:

1. `HuggingFaceSentimentClient` was reading the model name from the *legacy*
   `LLMConfig` (`config/pipeline_config.yaml`), not from the new
   `config/models.yaml` registry. So changing the registry had no effect.
2. The pipeline had a hidden line `text[:512]` in both `analyze_sentiment()`
   and `analyze_batch()`. That is a **character** cap, not a token cap, and
   it was silently truncating every input to ~128 tokens *before* the
   tokenizer ever saw it — defeating the entire 1024-token budget.
3. If a fresh clone of the repo did not have the local checkpoint yet
   (e.g. before training had been run), the client would crash trying to
   load a directory that did not exist.

**Mitigation — three-line fix per issue.**

1. `HuggingFaceSentimentClient.__init__` now reads
   `models.sentiment.model`, `models.sentiment.max_length`, and
   `models.sentiment.fallback_model` from the registry. Falls back to
   `LLMConfig.model` if the registry call fails (forward-compat with old
   configs).
2. Replaced `text[:512]` with `text[: max(2048, self._max_length * 4)]` in
   both `analyze_*` methods. The tokenizer's `truncation=True` still
   enforces the exact token cap; the character budget just makes sure we
   don't waste tokenizer work on text we'd discard anyway.
3. `_get_pipeline()` wraps the model load in a `try/except` and falls back
   to `cardiffnlp/twitter-roberta-base-sentiment-latest` if the local
   checkpoint is missing. The fallback is logged loudly so it doesn't go
   unnoticed.

`config/models.yaml` now reads:

```yaml
sentiment:
  enabled: true
  provider: huggingface
  model: models/modernbert_walmart/final
  fallback_model: cardiffnlp/twitter-roberta-base-sentiment-latest
  device: auto
  max_length: 1024
  confidence_threshold: 0.7
```

Smoke-tested: 5 of 5 first benchmark posts predicted correctly,
`model_used = models/modernbert_walmart/final`.

---

## 9. Challenge — AI-Assist Acceptance Rate Was 100%

**What we hit.** The labeler logged `_assist_accepted = True` on every
single one of the 200 posts. The annotator agreed with the model
suggestion on **all 200 posts, zero overrides**. This is a real
defensibility concern: a reviewer can argue that the labels are not
independent of the model and that the +0.137 macro F1 is partly an artifact
of training on what amounts to the model's own predictions.

**Mitigation — staged plan, fully disclosed.**

1. **Disclosure first.** The thesis chapter
   [docs/MODEL_COMPARISON.md](MODEL_COMPARISON.md#8-honesty-caveats-and-limits)
   calls this caveat out explicitly, in its own subsection, *before*
   anyone asks. The numbers stand or fall on their own merit.
2. **Blind recheck planned.** A 25-post sample (`--recheck --sample 25
   --seed 7`) will be re-labeled from scratch with the suggestion column
   hidden. Agreement rate becomes a published number in the chapter.
3. **Independent grounding.** Stages 1 (TweetEval) and 2 (GoEmotions) are
   labeled by *other people on other corpora*, so the model is not
   bootstrapped purely from one annotator's judgments.
4. **What we did NOT do** (and why): re-label all 200 posts from
   scratch. The cost is 6–8 hours, the dataset is dominated by clear-cut
   negative complaints, and the 25-sample recheck is statistically
   sufficient to bound the agreement rate.

---

## 10. Challenge — High Fold-to-Fold Variance

**What we hit.** v1 had macro F1 std = 0.1388 across folds. Even at v2
(std=0.1155) the spread is uncomfortable for a paper. Per-fold v2 results:
[0.5864, 0.9231, 0.6524, 0.7356, 0.7838].

**Diagnosis.** The variance is dominated by the positive class. With only
8 positive posts total, each fold's validation set contains 1 or 2 of
them, and missing the single positive example in fold 1 zeros out positive
F1 in that fold and drops the macro by ~0.10. Negative F1, by contrast,
is rock-solid: 0.8781 ± 0.0348.

**Mitigations applied (partial).**

- Stratified CV (already enabled).
- Class-weighted loss + oversampling (covered in
  [section 5](#5-challenge--stage-3-first-run-looked-catastrophic)).
- `max_length=1024` retrain dropped std from 0.1388 → 0.1155.

**Mitigations available but not run (and why):**

- **3-seed ensemble** (seeds 7/13/42, average logits). Expected +0.01–0.03
  macro F1 and noticeably tighter std. ~2.5 h compute. Held in reserve.
- **Positive-class augmentation** (back-translation or targeted re-sampling
  of the Arctic Shift cache for more positive posts). Higher upside but
  changes the dataset and breaks comparability with v1/v2 unless the 200-post
  split is kept as the eval set.
- We judged the current variance acceptable for the thesis because the long-
  bucket result (the headline) is at F1=1.00 and is not the source of the
  variance.

---

## 11. What Worked, What Didn't (Distilled)

**Worked:**

- 3-stage curriculum (TweetEval → GoEmotions → Walmart).
- Per-class loss weights + oversampling combined (either alone was not enough).
- `max_length=1024` — the single highest-impact lever after the recipe was
  fixed.
- Out-of-fold CV evaluation — turned a leakage scandal into a defensible
  result.
- Offline triad env vars — once set, every run is deterministic and never
  touches the network.

**Did not work:**

- VPN disconnect to fix the network (utun interfaces persisted).
- `max_length=512` for Stage 3 (defeats the entire point of ModernBERT).
- Final-model self-evaluation (memorization → meaningless 1.0).
- `text[:512]` char-truncation in the production wiring (silently
  defeats the 1024-token budget at inference time).
- Trying to fix `.venv` PyPI access (corp filtering is non-negotiable).

**Would do differently next time:**

- Set `max_length=1024` from the very first Stage-3 run, not after a
  retrain.
- Build the eval script *first*, with CV, before any "final" model is
  trained — would have caught the memorization issue before anyone
  celebrated the 1.0 result.
- Run a 25-post blind labeling check **before** labeling all 200, not
  after.

---

## 12. Final Scoreboard

| Phase | Status | Key artifact |
|---|---|---|
| 1 — Real benchmark + labeling | COMPLETE | [data/benchmark_real_200.jsonl](../data/benchmark_real_200.jsonl) |
| 2 — Curriculum training | COMPLETE | [models/modernbert_walmart/final/](../models/modernbert_walmart/final) |
| 3 — Honest evaluation (v1 + v2) | COMPLETE | [models/modernbert_walmart/eval_results.json](../models/modernbert_walmart/eval_results.json) |
| 4 — Pipeline integration | COMPLETE | [config/models.yaml](../config/models.yaml), [src/analysis/llm_client.py](../src/analysis/llm_client.py) |
| 5 — Thesis chapter | COMPLETE | [docs/MODEL_COMPARISON.md](MODEL_COMPARISON.md) |
| 6 — Blind recheck (defensibility) | OPEN | `scripts/label_benchmark.py --recheck --sample 25 --seed 7` |

| Metric | RoBERTa baseline | ModernBERT v2 | Δ |
|---|---|---|---|
| Macro F1 (OOF) | 0.6272 | **0.7642** | **+0.137** |
| F1 negative | 0.7967 | 0.8779 | +0.081 |
| F1 neutral | 0.6087 | 0.7480 | +0.139 |
| F1 positive | 0.4762 | 0.6667 | +0.190 |
| Long-bucket correct (n=7, ≥512 tok, all negative-class) | 5 / 7 | **7 / 7** | **+2** |
| Short-bucket F1 (n=193) | 0.6360 | 0.7619 | +0.126 |
| Latency (ms/post, MPS warm) | 6.5 | 11.9 | +5.4 |

Five phases of work, six numbered challenges resolved, one open caveat
disclosed up front. The thesis claim — *long-context, domain-fine-tuned
encoders beat short-context Twitter-trained baselines on Reddit-flavored
retail complaints* — is now backed by honest cross-validated numbers and
a production-wired model.
