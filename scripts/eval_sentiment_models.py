#!/usr/bin/env python3
"""
Evaluate sentiment models: ModernBERT (fine-tuned) vs RoBERTa (baseline).

Compares:
  - cardiffnlp/twitter-roberta-base-sentiment-latest (512 token context, no fine-tune)
  - ModernBERT fine-tuned on Walmart data (8192 token context)

Key thesis axis: length-bucketed evaluation (<512 vs ≥512 tokens) to show
ModernBERT's long-context advantage on verbose Reddit posts.

Usage:
  /opt/miniconda3/bin/python scripts/eval_sentiment_models.py [OPTIONS]

Options:
  --modernbert-path PATH  Path to fine-tuned ModernBERT (default: models/modernbert_walmart/final)
  --walmart-data PATH     Path to labeled Walmart JSONL (default: data/benchmark_real_200.jsonl)
  --output PATH           Results JSON output (default: models/modernbert_walmart/eval_results.json)
  --max-length INT        Max tokens for ModernBERT (default: 2048)
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from transformers import AutoModelForSequenceClassification, AutoTokenizer

LABEL2ID = {"negative": 0, "neutral": 1, "positive": 2}
ID2LABEL = {0: "negative", 1: "neutral", 2: "positive"}

# RoBERTa baseline uses different label mapping
ROBERTA_LABEL_MAP = {0: "negative", 1: "neutral", 2: "positive"}  # LABEL_0=neg, LABEL_1=neu, LABEL_2=pos


def parse_args():
    p = argparse.ArgumentParser(description="Evaluate sentiment models")
    p.add_argument("--modernbert-path", type=str, default="models/modernbert_walmart/final")
    p.add_argument("--walmart-data", type=str, default="data/benchmark_real_200.jsonl")
    p.add_argument("--output", type=str, default="models/modernbert_walmart/eval_results.json")
    p.add_argument("--max-length", type=int, default=2048)
    p.add_argument("--cv-results", type=str, default="models/modernbert_walmart/stage3_walmart/cv_results.json",
                   help="Path to CV out-of-fold predictions (avoids train=eval memorization)")
    return p.parse_args()


def get_device():
    if torch.backends.mps.is_available():
        return "mps"
    elif torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_walmart_data(data_path: str):
    """Load labeled Walmart posts with their token lengths."""
    posts = []
    with open(data_path) as f:
        for line in f:
            row = json.loads(line)
            sentiment = row.get("human_sentiment", "").strip().lower()
            if sentiment not in LABEL2ID:
                continue
            text = f"{row['title']}\n\n{row['body']}"
            posts.append({
                "id": row["id"],
                "text": text,
                "label": LABEL2ID[sentiment],
                "label_name": sentiment,
                "char_length": len(text),
            })
    return posts


def predict_batch(model, tokenizer, texts, max_length, device, batch_size=8):
    """Run inference on a list of texts. Returns predictions and latencies."""
    model.to(device)
    model.eval()

    all_preds = []
    all_confs = []
    total_time = 0.0

    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        inputs = tokenizer(
            batch_texts, truncation=True, padding=True, max_length=max_length, return_tensors="pt"
        ).to(device)

        start = time.perf_counter()
        with torch.no_grad():
            outputs = model(**inputs)
        elapsed = time.perf_counter() - start
        total_time += elapsed

        probs = torch.softmax(outputs.logits, dim=-1)
        preds = torch.argmax(probs, dim=-1).cpu().numpy()
        confs = probs.max(dim=-1).values.cpu().numpy()

        all_preds.extend(preds.tolist())
        all_confs.extend(confs.tolist())

    avg_latency_ms = (total_time / len(texts)) * 1000
    return all_preds, all_confs, avg_latency_ms


def evaluate_model(model_name, model, tokenizer, posts, max_length, device):
    """Evaluate a model on all posts and by length bucket."""
    texts = [p["text"] for p in posts]
    labels = [p["label"] for p in posts]

    # Get token lengths for bucketing (use the model's own tokenizer)
    token_lengths = []
    for text in texts:
        toks = tokenizer(text, truncation=False)["input_ids"]
        token_lengths.append(len(toks))

    for i, p in enumerate(posts):
        p["token_length"] = token_lengths[i]

    preds, confs, avg_latency = predict_batch(model, tokenizer, texts, max_length, device)

    # Overall metrics
    labels_arr = np.array(labels)
    preds_arr = np.array(preds)
    macro_f1 = f1_score(labels_arr, preds_arr, average="macro")
    per_class_f1 = f1_score(labels_arr, preds_arr, average=None, labels=[0, 1, 2])
    cm = confusion_matrix(labels_arr, preds_arr, labels=[0, 1, 2])

    result = {
        "model": model_name,
        "max_length": max_length,
        "n_posts": len(posts),
        "macro_f1": float(macro_f1),
        "f1_negative": float(per_class_f1[0]),
        "f1_neutral": float(per_class_f1[1]),
        "f1_positive": float(per_class_f1[2]),
        "avg_latency_ms": float(avg_latency),
        "confusion_matrix": cm.tolist(),
    }

    # Length-bucketed evaluation (thesis key axis)
    # Bucket: <512 tokens vs ≥512 tokens
    short_idx = [i for i, tl in enumerate(token_lengths) if tl < 512]
    long_idx = [i for i, tl in enumerate(token_lengths) if tl >= 512]

    for bucket_name, idx_list in [("short_lt512", short_idx), ("long_gte512", long_idx)]:
        if not idx_list:
            result[bucket_name] = {"n": 0, "macro_f1": None}
            continue
        b_labels = labels_arr[idx_list]
        b_preds = preds_arr[idx_list]
        b_f1 = f1_score(b_labels, b_preds, average="macro", zero_division=0)
        b_per_class = f1_score(b_labels, b_preds, average=None, labels=[0, 1, 2], zero_division=0)
        result[bucket_name] = {
            "n": len(idx_list),
            "macro_f1": float(b_f1),
            "f1_negative": float(b_per_class[0]),
            "f1_neutral": float(b_per_class[1]),
            "f1_positive": float(b_per_class[2]),
        }

    # Per-sample predictions (for error analysis)
    result["predictions"] = [
        {
            "id": posts[i]["id"],
            "true": ID2LABEL[labels[i]],
            "pred": ID2LABEL[preds[i]],
            "conf": float(confs[i]),
            "token_length": token_lengths[i],
            "correct": labels[i] == preds[i],
        }
        for i in range(len(posts))
    ]

    return result


def print_results(result):
    """Pretty-print evaluation results."""
    print(f"\n{'─'*60}")
    print(f"  Model: {result['model']}")
    print(f"  Max length: {result['max_length']} tokens")
    print(f"  N posts: {result['n_posts']}")
    print(f"{'─'*60}")
    print(f"  Overall Macro F1:  {result['macro_f1']:.4f}")
    print(f"    Negative:        {result['f1_negative']:.4f}")
    print(f"    Neutral:         {result['f1_neutral']:.4f}")
    print(f"    Positive:        {result['f1_positive']:.4f}")
    print(f"  Avg latency:       {result['avg_latency_ms']:.1f} ms/post")

    print(f"\n  Length-bucketed:")
    for bucket in ["short_lt512", "long_gte512"]:
        b = result[bucket]
        if b["n"] == 0:
            print(f"    {bucket}: (empty)")
        else:
            print(f"    {bucket} (n={b['n']}): F1={b['macro_f1']:.4f}  "
                  f"[neg={b['f1_negative']:.4f} neu={b['f1_neutral']:.4f} pos={b['f1_positive']:.4f}]")

    print(f"\n  Confusion matrix (rows=true, cols=pred):")
    print(f"  {'':>10} {'neg':>6} {'neu':>6} {'pos':>6}")
    cm = result["confusion_matrix"]
    for i, row_label in enumerate(["neg", "neu", "pos"]):
        print(f"  {row_label:>10} {cm[i][0]:>6} {cm[i][1]:>6} {cm[i][2]:>6}")


def main():
    args = parse_args()
    device = get_device()
    print(f"Sentiment Model Evaluation")
    print(f"  Device: {device}")
    print(f"  Data: {args.walmart_data}")

    # Load data
    posts = load_walmart_data(args.walmart_data)
    print(f"  Loaded {len(posts)} labeled posts")

    results = {}

    # ── Baseline: cardiffnlp RoBERTa ──
    print("\n[1/2] Loading baseline: cardiffnlp/twitter-roberta-base-sentiment-latest...")
    roberta_name = "cardiffnlp/twitter-roberta-base-sentiment-latest"
    roberta_tok = AutoTokenizer.from_pretrained(roberta_name)
    roberta_model = AutoModelForSequenceClassification.from_pretrained(roberta_name)

    results["roberta_baseline"] = evaluate_model(
        model_name=roberta_name,
        model=roberta_model,
        tokenizer=roberta_tok,
        posts=posts,
        max_length=512,
        device=device,
    )
    print_results(results["roberta_baseline"])

    # Free memory
    del roberta_model
    torch.mps.empty_cache() if device == "mps" else None

    # ── Fine-tuned ModernBERT (using CV out-of-fold predictions) ──
    cv_path = Path(args.cv_results)
    modernbert_path = args.modernbert_path
    if not cv_path.exists():
        print(f"\n[2/2] SKIPPED — CV results not found at {cv_path}")
        print("       Run train_modernbert_sentiment.py first.")
    else:
        print(f"\n[2/2] Loading CV out-of-fold predictions from {cv_path}...")
        print(f"       (Each sample predicted by a model that never trained on it)")
        with open(cv_path) as f:
            cv_data = json.load(f)

        cv_preds_raw = cv_data["per_sample_predictions"]
        assert len(cv_preds_raw) == len(posts), (
            f"CV predictions count ({len(cv_preds_raw)}) != posts count ({len(posts)})"
        )

        cv_true = [LABEL2ID[p["true"]] for p in cv_preds_raw]
        cv_pred = [LABEL2ID[p["pred"]] for p in cv_preds_raw]

        # Sanity check: CV true labels should match loaded post labels
        post_labels = [p["label"] for p in posts]
        assert cv_true == post_labels, "CV label order doesn't match data file order!"

        # Measure latency with the final model (if available), but use CV preds for accuracy
        avg_latency = 0.0
        if Path(modernbert_path).exists():
            print(f"       Measuring latency with final model at {modernbert_path}...")
            mb_tok = AutoTokenizer.from_pretrained(modernbert_path)
            mb_model = AutoModelForSequenceClassification.from_pretrained(modernbert_path)
            mb_model.to(device)
            mb_model.eval()

            # Get token lengths for bucketing
            token_lengths = []
            for p in posts:
                toks = mb_tok(p["text"], truncation=False)["input_ids"]
                token_lengths.append(len(toks))
            for i, p in enumerate(posts):
                p["token_length"] = token_lengths[i]

            # Latency benchmark (run inference but discard preds)
            texts = [p["text"] for p in posts]
            _, _, avg_latency = predict_batch(mb_model, mb_tok, texts, args.max_length, device)
            del mb_model
            torch.mps.empty_cache() if device == "mps" else None
        else:
            # No final model — still compute token lengths with a generic tokenizer
            mb_tok = AutoTokenizer.from_pretrained("answerdotai/ModernBERT-base")
            token_lengths = []
            for p in posts:
                toks = mb_tok(p["text"], truncation=False)["input_ids"]
                token_lengths.append(len(toks))
            for i, p in enumerate(posts):
                p["token_length"] = token_lengths[i]

        # Build metrics from CV out-of-fold predictions
        labels_arr = np.array(cv_true)
        preds_arr = np.array(cv_pred)
        macro_f1 = f1_score(labels_arr, preds_arr, average="macro")
        per_class_f1 = f1_score(labels_arr, preds_arr, average=None, labels=[0, 1, 2])
        cm = confusion_matrix(labels_arr, preds_arr, labels=[0, 1, 2])

        result = {
            "model": f"ModernBERT (fine-tuned, 5-fold CV out-of-fold)",
            "max_length": args.max_length,
            "n_posts": len(posts),
            "macro_f1": float(macro_f1),
            "f1_negative": float(per_class_f1[0]),
            "f1_neutral": float(per_class_f1[1]),
            "f1_positive": float(per_class_f1[2]),
            "avg_latency_ms": float(avg_latency),
            "confusion_matrix": cm.tolist(),
            "cv_macro_f1_mean": cv_data["macro_f1_mean"],
            "cv_macro_f1_std": cv_data["macro_f1_std"],
        }

        # Length-bucketed evaluation
        short_idx = [i for i, tl in enumerate(token_lengths) if tl < 512]
        long_idx = [i for i, tl in enumerate(token_lengths) if tl >= 512]

        for bucket_name, idx_list in [("short_lt512", short_idx), ("long_gte512", long_idx)]:
            if not idx_list:
                result[bucket_name] = {"n": 0, "macro_f1": None}
                continue
            b_labels = labels_arr[idx_list]
            b_preds = preds_arr[idx_list]
            b_f1 = f1_score(b_labels, b_preds, average="macro", zero_division=0)
            b_per_class = f1_score(b_labels, b_preds, average=None, labels=[0, 1, 2], zero_division=0)
            result[bucket_name] = {
                "n": len(idx_list),
                "macro_f1": float(b_f1),
                "f1_negative": float(b_per_class[0]),
                "f1_neutral": float(b_per_class[1]),
                "f1_positive": float(b_per_class[2]),
            }

        # Per-sample predictions
        result["predictions"] = [
            {
                "id": posts[i]["id"],
                "true": ID2LABEL[cv_true[i]],
                "pred": ID2LABEL[cv_pred[i]],
                "token_length": token_lengths[i],
                "correct": cv_true[i] == cv_pred[i],
            }
            for i in range(len(posts))
        ]

        results["modernbert_finetuned"] = result
        print_results(results["modernbert_finetuned"])

    # ── Comparison summary ──
    if "roberta_baseline" in results and "modernbert_finetuned" in results:
        r = results["roberta_baseline"]
        m = results["modernbert_finetuned"]
        print(f"\n{'='*60}")
        print(f"  COMPARISON SUMMARY")
        print(f"{'='*60}")
        print(f"  {'Metric':<25} {'RoBERTa':>10} {'ModernBERT':>12} {'Delta':>8}")
        print(f"  {'─'*55}")
        print(f"  {'Overall Macro F1':<25} {r['macro_f1']:>10.4f} {m['macro_f1']:>12.4f} {m['macro_f1']-r['macro_f1']:>+8.4f}")
        print(f"  {'F1 Negative':<25} {r['f1_negative']:>10.4f} {m['f1_negative']:>12.4f} {m['f1_negative']-r['f1_negative']:>+8.4f}")
        print(f"  {'F1 Neutral':<25} {r['f1_neutral']:>10.4f} {m['f1_neutral']:>12.4f} {m['f1_neutral']-r['f1_neutral']:>+8.4f}")
        print(f"  {'F1 Positive':<25} {r['f1_positive']:>10.4f} {m['f1_positive']:>12.4f} {m['f1_positive']-r['f1_positive']:>+8.4f}")
        print(f"  {'Latency (ms/post)':<25} {r['avg_latency_ms']:>10.1f} {m['avg_latency_ms']:>12.1f} {m['avg_latency_ms']-r['avg_latency_ms']:>+8.1f}")

        # Length-bucket comparison (key thesis point)
        print(f"\n  Length-bucket comparison (thesis axis):")
        for bucket in ["short_lt512", "long_gte512"]:
            rb = r[bucket]
            mb = m[bucket]
            if rb["n"] > 0 and mb["n"] > 0:
                print(f"    {bucket} (n={rb['n']}): RoBERTa={rb['macro_f1']:.4f}  ModernBERT={mb['macro_f1']:.4f}  Δ={mb['macro_f1']-rb['macro_f1']:+.4f}")

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Strip per-sample predictions for the summary file (too large)
    save_results = {}
    for k, v in results.items():
        save_results[k] = {key: val for key, val in v.items() if key != "predictions"}
    save_results["_predictions"] = {
        k: v.get("predictions", []) for k, v in results.items()
    }
    with open(output_path, "w") as f:
        json.dump(save_results, f, indent=2)
    print(f"\n  Results saved to {output_path}")


if __name__ == "__main__":
    main()
