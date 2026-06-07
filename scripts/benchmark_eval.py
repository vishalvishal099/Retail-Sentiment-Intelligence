"""
Retail Sentiment Intelligence — 150-Unit Benchmark Evaluation
=============================================================
Evaluates sentiment classification and aspect extraction against human-labeled 
ground truth. Outputs metrics suitable for dissertation Chapter 5 (Evaluation).

Usage:
    # Step 1: Generate annotation file (first time only)
    python scripts/benchmark_eval.py --generate-annotation-file

    # Step 2: After manual labeling, run evaluation
    python scripts/benchmark_eval.py --evaluate

    # Quick check: evaluate using model predictions as proxy ground truth
    python scripts/benchmark_eval.py --self-eval
"""

import argparse
import json
import sys
import time
from pathlib import Path
from collections import Counter
from datetime import datetime

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import load_config
from src.utils.cost_tracker import CostTracker
from src.analysis.llm_client import HuggingFaceSentimentClient
from src.utils.logger import get_logger

log = get_logger("benchmark")

BENCHMARK_FILE = Path("data/benchmark_150.jsonl")
ANNOTATION_FILE = Path("data/benchmark_annotations.jsonl")
RESULTS_FILE = Path("data/benchmark_results.json")

SENTIMENT_CLASSES = ["positive", "negative", "neutral"]
ASPECT_CATEGORIES = [
    "pricing", "product quality", "store experience",
    "customer service", "online/app", "delivery/pickup"
]


def load_benchmark():
    """Load the 150-unit benchmark dataset."""
    posts = []
    with open(BENCHMARK_FILE) as f:
        for line in f:
            posts.append(json.loads(line))
    return posts


def load_annotations():
    """Load human annotations."""
    annotations = {}
    with open(ANNOTATION_FILE) as f:
        for line in f:
            a = json.loads(line)
            annotations[a["id"]] = a
    return annotations


def generate_annotation_file():
    """Generate a file for human annotation in JSONL format."""
    posts = load_benchmark()
    
    with open(ANNOTATION_FILE, "w") as f:
        for i, p in enumerate(posts):
            annotation = {
                "id": p["id"],
                "index": i + 1,
                "subreddit": p["subreddit"],
                "title": p["title"],
                "body": p["body"],
                "human_sentiment": "",  # Fill: positive/negative/neutral
                "human_aspects": [],    # Fill: list from ASPECT_CATEGORIES
                "notes": "",
                # Model predictions (for reference during annotation)
                "_model_sentiment": p["predicted_sentiment"],
                "_model_confidence": p["predicted_confidence"],
                "_model_aspects": p["predicted_aspects"],
            }
            f.write(json.dumps(annotation) + "\n")
    
    print(f"Generated annotation file: {ANNOTATION_FILE}")
    print(f"Contains {len(posts)} posts to label.")
    print(f"\nInstructions:")
    print(f"  1. Open {ANNOTATION_FILE}")
    print(f"  2. For each entry, fill 'human_sentiment' with: positive, negative, or neutral")
    print(f"  3. Fill 'human_aspects' with applicable categories from:")
    print(f"     {ASPECT_CATEGORIES}")
    print(f"  4. Run: python scripts/benchmark_eval.py --evaluate")


def compute_metrics(y_true, y_pred, classes):
    """Compute per-class precision, recall, F1, and macro averages."""
    metrics = {}
    
    # Confusion matrix
    cm = {c: {c2: 0 for c2 in classes} for c in classes}
    for t, p in zip(y_true, y_pred):
        if t in cm and p in cm[t]:
            cm[t][p] += 1
    
    # Per-class metrics
    macro_p, macro_r, macro_f1 = 0, 0, 0
    weighted_f1, total_support = 0, 0
    
    for c in classes:
        tp = cm[c][c]
        fp = sum(cm[other][c] for other in classes if other != c)
        fn = sum(cm[c][other] for other in classes if other != c)
        support = tp + fn
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        
        metrics[c] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support
        }
        
        macro_p += precision
        macro_r += recall
        macro_f1 += f1
        weighted_f1 += f1 * support
        total_support += support
    
    n_classes = len(classes)
    metrics["macro_avg"] = {
        "precision": round(macro_p / n_classes, 4),
        "recall": round(macro_r / n_classes, 4),
        "f1": round(macro_f1 / n_classes, 4),
    }
    metrics["weighted_avg"] = {
        "f1": round(weighted_f1 / total_support, 4) if total_support > 0 else 0
    }
    metrics["accuracy"] = round(sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true), 4)
    metrics["confusion_matrix"] = cm
    metrics["n_samples"] = len(y_true)
    
    return metrics


def compute_aspect_metrics(true_aspects_list, pred_aspects_list):
    """Compute aspect extraction metrics (multi-label)."""
    # Normalize aspect names
    def normalize(aspects):
        norm_map = {
            "product_quality": "product quality",
            "store_experience": "store experience",
            "customer_service": "customer service",
            "online_ordering": "online/app",
            "delivery": "delivery/pickup",
            "returns": "customer service",
        }
        result = set()
        for a in aspects:
            a_lower = a.lower().strip()
            result.add(norm_map.get(a_lower, a_lower))
        return result
    
    total_tp, total_fp, total_fn = 0, 0, 0
    per_aspect = {a: {"tp": 0, "fp": 0, "fn": 0} for a in ASPECT_CATEGORIES}
    
    for true_set, pred_set in zip(true_aspects_list, pred_aspects_list):
        true_norm = normalize(true_set)
        pred_norm = normalize(pred_set)
        
        tp = true_norm & pred_norm
        fp = pred_norm - true_norm
        fn = true_norm - pred_norm
        
        total_tp += len(tp)
        total_fp += len(fp)
        total_fn += len(fn)
        
        for a in tp:
            if a in per_aspect:
                per_aspect[a]["tp"] += 1
        for a in fp:
            if a in per_aspect:
                per_aspect[a]["fp"] += 1
        for a in fn:
            if a in per_aspect:
                per_aspect[a]["fn"] += 1
    
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    result = {
        "micro_precision": round(precision, 4),
        "micro_recall": round(recall, 4),
        "micro_f1": round(f1, 4),
        "total_true_labels": total_tp + total_fn,
        "total_predicted_labels": total_tp + total_fp,
        "per_aspect": {}
    }
    
    for a in ASPECT_CATEGORIES:
        d = per_aspect[a]
        p = d["tp"] / (d["tp"] + d["fp"]) if (d["tp"] + d["fp"]) > 0 else 0
        r = d["tp"] / (d["tp"] + d["fn"]) if (d["tp"] + d["fn"]) > 0 else 0
        f = 2 * p * r / (p + r) if (p + r) > 0 else 0
        result["per_aspect"][a] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f, 4),
            "support": d["tp"] + d["fn"]
        }
    
    return result


def run_model_inference(posts):
    """Re-run sentiment model on benchmark posts."""
    config = load_config()
    cost_tracker = CostTracker()
    client = HuggingFaceSentimentClient(config.llm, cost_tracker)
    
    results = []
    start = time.time()
    
    # Build texts like the pipeline does
    texts = []
    for p in posts:
        title = p.get("title", "") or ""
        body = p.get("body", "") or ""
        text = f"[r/{p.get('subreddit', 'unknown')}] {title}\n{body}".strip()
        texts.append(text)
    
    # Batch inference
    batch_size = 32
    all_results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        batch_results = client.analyze_batch(batch)
        all_results.extend(batch_results)
    
    elapsed = time.time() - start
    log.info("inference_complete", n=len(posts), elapsed_s=round(elapsed, 2),
             ms_per_sample=round(elapsed/len(posts)*1000, 1))
    
    return all_results, elapsed


def evaluate(use_self_eval=False):
    """Run full evaluation against ground truth."""
    posts = load_benchmark()
    
    if use_self_eval:
        print("=" * 70)
        print("SELF-EVALUATION MODE (model predictions as ground truth)")
        print("This verifies model consistency; use --evaluate for true accuracy")
        print("=" * 70)
        # Use model predictions as "ground truth" - tests reproducibility
        ground_truth = {
            p["id"]: {
                "human_sentiment": p["predicted_sentiment"],
                "human_aspects": p["predicted_aspects"]
            }
            for p in posts
        }
    else:
        if not ANNOTATION_FILE.exists():
            print(f"Error: {ANNOTATION_FILE} not found.")
            print("Run: python scripts/benchmark_eval.py --generate-annotation-file")
            sys.exit(1)
        
        ground_truth = load_annotations()
        # Validate annotations
        unlabeled = [pid for pid, a in ground_truth.items() if not a.get("human_sentiment")]
        if unlabeled:
            print(f"Warning: {len(unlabeled)} posts not yet labeled. Skipping them.")
            posts = [p for p in posts if ground_truth.get(p["id"], {}).get("human_sentiment")]
    
    # Re-run inference
    print(f"\nRunning model inference on {len(posts)} posts...")
    predictions, latency = run_model_inference(posts)
    
    # Collect paired labels
    y_true_sentiment = []
    y_pred_sentiment = []
    true_aspects_list = []
    pred_aspects_list = []
    confidence_by_correctness = {"correct": [], "incorrect": []}
    
    for post, pred in zip(posts, predictions):
        gt = ground_truth.get(post["id"], {})
        true_s = gt.get("human_sentiment", "").lower().strip()
        pred_s = pred.get("sentiment", "").lower().strip()
        
        if true_s not in SENTIMENT_CLASSES:
            continue
        
        y_true_sentiment.append(true_s)
        y_pred_sentiment.append(pred_s)
        
        conf = pred.get("sentiment_confidence", 0)
        if true_s == pred_s:
            confidence_by_correctness["correct"].append(conf)
        else:
            confidence_by_correctness["incorrect"].append(conf)
        
        # Aspects
        true_a = gt.get("human_aspects", [])
        pred_a = [a["aspect"] if isinstance(a, dict) else a for a in pred.get("aspects", [])]
        true_aspects_list.append(true_a)
        pred_aspects_list.append(pred_a)
    
    # Compute metrics
    sent_metrics = compute_metrics(y_true_sentiment, y_pred_sentiment, SENTIMENT_CLASSES)
    aspect_metrics = compute_aspect_metrics(true_aspects_list, pred_aspects_list)
    
    # Confidence calibration
    avg_conf_correct = (sum(confidence_by_correctness["correct"]) / len(confidence_by_correctness["correct"])) if confidence_by_correctness["correct"] else 0
    avg_conf_incorrect = (sum(confidence_by_correctness["incorrect"]) / len(confidence_by_correctness["incorrect"])) if confidence_by_correctness["incorrect"] else 0
    
    # Build full results
    results = {
        "evaluation_date": datetime.now().isoformat(),
        "mode": "self_eval" if use_self_eval else "human_annotated",
        "n_samples": len(y_true_sentiment),
        "model": "cardiffnlp/twitter-roberta-base-sentiment-latest + MoritzLaurer/deberta-v3-base-zeroshot-v2.0",
        "device": "Apple Silicon MPS",
        "latency": {
            "total_s": round(latency, 2),
            "ms_per_sample": round(latency / len(posts) * 1000, 1),
            "throughput_per_s": round(len(posts) / latency, 1)
        },
        "sentiment": sent_metrics,
        "aspects": aspect_metrics,
        "confidence_calibration": {
            "mean_confidence_correct": round(avg_conf_correct, 4),
            "mean_confidence_incorrect": round(avg_conf_incorrect, 4),
            "confidence_gap": round(avg_conf_correct - avg_conf_incorrect, 4)
        },
        "cost": "$0.00 (local inference)"
    }
    
    # Save
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    
    # Print report
    print_report(results, use_self_eval)
    
    return results


def print_report(results, is_self_eval=False):
    """Print dissertation-ready evaluation report."""
    print("\n")
    print("=" * 70)
    print("  RETAIL SENTIMENT INTELLIGENCE — BENCHMARK EVALUATION REPORT")
    print("=" * 70)
    print(f"  Date: {results['evaluation_date'][:10]}")
    print(f"  Mode: {'Self-Evaluation (consistency check)' if is_self_eval else 'Human-Annotated Ground Truth'}")
    print(f"  Samples: {results['n_samples']} (stratified: 50 pos / 50 neg / 50 neu)")
    print(f"  Model: {results['model']}")
    print(f"  Device: {results['device']}")
    print()
    
    # Sentiment Classification
    sm = results["sentiment"]
    print("─" * 70)
    print("  SENTIMENT CLASSIFICATION")
    print("─" * 70)
    print(f"  Overall Accuracy: {sm['accuracy']:.1%}")
    print(f"  Macro F1:         {sm['macro_avg']['f1']:.4f}")
    print(f"  Weighted F1:      {sm['weighted_avg']['f1']:.4f}")
    print()
    print(f"  {'Class':<12} {'Precision':<12} {'Recall':<12} {'F1':<12} {'Support':<10}")
    print(f"  {'─'*56}")
    for c in SENTIMENT_CLASSES:
        m = sm[c]
        print(f"  {c:<12} {m['precision']:<12.4f} {m['recall']:<12.4f} {m['f1']:<12.4f} {m['support']:<10}")
    ma = sm["macro_avg"]
    print(f"  {'─'*56}")
    print(f"  {'macro avg':<12} {ma['precision']:<12.4f} {ma['recall']:<12.4f} {ma['f1']:<12.4f} {results['n_samples']:<10}")
    
    # Confusion Matrix
    print()
    print(f"  Confusion Matrix (rows=true, cols=predicted):")
    cm = sm["confusion_matrix"]
    print(f"  {'':>12} {'positive':>10} {'negative':>10} {'neutral':>10}")
    for c in SENTIMENT_CLASSES:
        row = [cm[c].get(c2, 0) for c2 in SENTIMENT_CLASSES]
        print(f"  {c:>12} {row[0]:>10} {row[1]:>10} {row[2]:>10}")
    
    # Aspect Extraction
    print()
    print("─" * 70)
    print("  ASPECT EXTRACTION (Zero-Shot DeBERTa)")
    print("─" * 70)
    am = results["aspects"]
    print(f"  Micro Precision: {am['micro_precision']:.4f}")
    print(f"  Micro Recall:    {am['micro_recall']:.4f}")
    print(f"  Micro F1:        {am['micro_f1']:.4f}")
    print()
    print(f"  {'Aspect':<20} {'Precision':<12} {'Recall':<12} {'F1':<12} {'Support':<10}")
    print(f"  {'─'*64}")
    for a in ASPECT_CATEGORIES:
        if a in am["per_aspect"]:
            m = am["per_aspect"][a]
            print(f"  {a:<20} {m['precision']:<12.4f} {m['recall']:<12.4f} {m['f1']:<12.4f} {m['support']:<10}")
    
    # Latency
    print()
    print("─" * 70)
    print("  PERFORMANCE")
    print("─" * 70)
    lat = results["latency"]
    print(f"  Total inference time: {lat['total_s']:.2f}s")
    print(f"  Per-sample latency:   {lat['ms_per_sample']:.1f}ms")
    print(f"  Throughput:           {lat['throughput_per_s']:.1f} posts/sec")
    print(f"  Cost:                 {results['cost']}")
    
    # Confidence Calibration
    cc = results["confidence_calibration"]
    print()
    print("─" * 70)
    print("  CONFIDENCE CALIBRATION")
    print("─" * 70)
    print(f"  Mean confidence (correct predictions):   {cc['mean_confidence_correct']:.4f}")
    print(f"  Mean confidence (incorrect predictions): {cc['mean_confidence_incorrect']:.4f}")
    print(f"  Confidence gap (higher = better):        {cc['confidence_gap']:.4f}")
    
    # Summary
    print()
    print("=" * 70)
    f1 = sm['macro_avg']['f1']
    target = 0.80
    status = "✓ PASS" if f1 >= target else "✗ BELOW TARGET"
    print(f"  DISSERTATION TARGET: Macro F1 ≥ {target:.2f}")
    print(f"  ACHIEVED:            Macro F1 = {f1:.4f}  [{status}]")
    print("=" * 70)
    print(f"\n  Full results saved to: {RESULTS_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark Evaluation")
    parser.add_argument("--generate-annotation-file", action="store_true",
                        help="Generate annotation JSONL for human labeling")
    parser.add_argument("--evaluate", action="store_true",
                        help="Evaluate against human annotations")
    parser.add_argument("--self-eval", action="store_true",
                        help="Self-evaluation (model consistency check)")
    
    args = parser.parse_args()
    
    if args.generate_annotation_file:
        generate_annotation_file()
    elif args.evaluate:
        evaluate(use_self_eval=False)
    elif args.self_eval:
        evaluate(use_self_eval=True)
    else:
        parser.print_help()
        print("\nQuick start: python scripts/benchmark_eval.py --self-eval")
