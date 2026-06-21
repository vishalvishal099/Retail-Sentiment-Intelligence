#!/usr/bin/env python3
"""
Train ModernBERT-base for 3-class sentiment (negative/neutral/positive).

3-Stage Curriculum:
  Stage 1: Warm-up on TweetEval sentiment (45k train)
  Stage 2: Fine-tune on GoEmotions collapsed to neg/neu/pos (43k train)
  Stage 3: Final adaptation on Walmart-200 (stratified 5-fold CV)

Usage:
  /opt/miniconda3/bin/python scripts/train_modernbert_sentiment.py [OPTIONS]

Options:
  --stages 1,2,3       Which stages to run (default: all)
  --output-dir PATH    Where to save model checkpoints (default: models/modernbert_walmart)
  --folds N            Number of CV folds for Stage 3 (default: 5)
  --seed INT           Random seed (default: 42)
  --batch-size INT     Training batch size (default: 16)
  --lr FLOAT           Peak learning rate (default: 2e-5)
  --epochs-s1 INT      Epochs for Stage 1 (default: 2)
  --epochs-s2 INT      Epochs for Stage 2 (default: 2)
  --epochs-s3 INT      Epochs for Stage 3 (default: 10)
  --max-length INT     Max token length (default: 2048)
  --walmart-data PATH  Path to labeled Walmart JSONL (default: data/benchmark_real_200.jsonl)
  --skip-if-exists     Skip a stage if its checkpoint dir already exists
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import StratifiedKFold
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
)

# Label scheme (consistent across all 3 stages)
LABEL2ID = {"negative": 0, "neutral": 1, "positive": 2}
ID2LABEL = {v: k for k, v in LABEL2ID.items()}
NUM_LABELS = 3

MODEL_NAME = "answerdotai/ModernBERT-base"


def parse_args():
    p = argparse.ArgumentParser(description="Train ModernBERT sentiment classifier")
    p.add_argument("--stages", type=str, default="1,2,3", help="Comma-separated stages to run")
    p.add_argument("--output-dir", type=str, default="models/modernbert_walmart")
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--epochs-s1", type=int, default=2)
    p.add_argument("--epochs-s2", type=int, default=2)
    p.add_argument("--epochs-s3", type=int, default=10)
    p.add_argument("--max-length", type=int, default=2048)
    p.add_argument("--walmart-data", type=str, default="data/benchmark_real_200.jsonl")
    p.add_argument("--skip-if-exists", action="store_true")
    return p.parse_args()


def set_seed(seed: int):
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def get_device():
    if torch.backends.mps.is_available():
        return "mps"
    elif torch.cuda.is_available():
        return "cuda"
    return "cpu"


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    macro_f1 = f1_score(labels, preds, average="macro")
    per_class = f1_score(labels, preds, average=None, labels=[0, 1, 2])
    return {
        "macro_f1": macro_f1,
        "f1_negative": per_class[0],
        "f1_neutral": per_class[1],
        "f1_positive": per_class[2],
    }


# ─── Dataset helpers ────────────────────────────────────────────────────────


class SentimentDataset(torch.utils.data.Dataset):
    """Dataset wrapping tokenized encodings + labels. Supports dynamic padding."""

    def __init__(self, encodings, labels):
        self.encodings = encodings
        self.labels = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        item = {k: torch.tensor(v[idx]) for k, v in self.encodings.items()}
        item["labels"] = torch.tensor(self.labels[idx])
        return item


class WeightedTrainer(Trainer):
    """Trainer with class-weighted cross-entropy loss."""

    def __init__(self, class_weights=None, **kwargs):
        super().__init__(**kwargs)
        if class_weights is not None:
            self.class_weights = torch.tensor(class_weights, dtype=torch.float32)
        else:
            self.class_weights = None

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        logits = outputs.logits
        if self.class_weights is not None:
            weight = self.class_weights.to(logits.device)
            loss = nn.CrossEntropyLoss(weight=weight)(logits, labels)
        else:
            loss = nn.CrossEntropyLoss()(logits, labels)
        return (loss, outputs) if return_outputs else loss


def oversample_minority(texts, labels, target_per_class=None):
    """Oversample minority classes to balance the dataset."""
    from collections import Counter
    counts = Counter(labels)
    if target_per_class is None:
        target_per_class = max(counts.values())

    new_texts, new_labels = list(texts), list(labels)
    for cls, count in counts.items():
        if count < target_per_class:
            # Get indices of this class
            cls_indices = [i for i, l in enumerate(labels) if l == cls]
            # Oversample with replacement
            n_needed = target_per_class - count
            rng = np.random.RandomState(42 + cls)
            extra_indices = rng.choice(cls_indices, size=n_needed, replace=True)
            for idx in extra_indices:
                new_texts.append(texts[idx])
                new_labels.append(labels[idx])

    return new_texts, new_labels


def load_tweeteval(tokenizer, max_length: int):
    """Load TweetEval sentiment dataset. Labels: 0=neg, 1=neu, 2=pos (matches ours)."""
    from datasets import load_dataset

    ds = load_dataset("cardiffnlp/tweet_eval", "sentiment")
    print(f"  TweetEval loaded: {len(ds['train'])} train, {len(ds['validation'])} val, {len(ds['test'])} test")

    def tokenize_split(split):
        texts = [str(t) if t is not None else "" for t in ds[split]["text"]]
        labels = ds[split]["label"]  # 0=neg, 1=neu, 2=pos — already matches
        enc = tokenizer(texts, truncation=True, padding=False, max_length=min(max_length, 128))
        return SentimentDataset(enc, labels)

    return tokenize_split("train"), tokenize_split("validation"), tokenize_split("test")


def load_goemotions(tokenizer, max_length: int):
    """Load GoEmotions and collapse 28 emotions into neg/neu/pos."""
    from datasets import load_dataset

    ds = load_dataset("google-research-datasets/go_emotions")
    print(f"  GoEmotions loaded: {len(ds['train'])} train")

    # GoEmotions label indices (0-27). Label 27 = "neutral".
    # Positive emotions: admiration(0), amusement(1), approval(2), caring(3),
    #   desire(4), excitement(5), gratitude(6), joy(7), love(8), optimism(9), relief(10)
    # Negative emotions: anger(11), annoyance(12), confusion(13), disappointment(14),
    #   disapproval(15), disgust(16), embarrassment(17), fear(18), grief(19),
    #   nervousness(20), remorse(21), sadness(22)
    # Neutral/ambiguous: curiosity(23), realization(24), surprise(25), neutral(27)
    # pride(26) → positive
    POSITIVE_IDS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 26}
    NEGATIVE_IDS = {11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22}
    NEUTRAL_IDS = {23, 24, 25, 27}

    def collapse_labels(example):
        """Map multi-label to single sentiment. Priority: negative > positive > neutral."""
        label_ids = example["labels"]
        has_neg = any(lid in NEGATIVE_IDS for lid in label_ids)
        has_pos = any(lid in POSITIVE_IDS for lid in label_ids)
        if has_neg:
            return 0  # negative
        elif has_pos:
            return 2  # positive
        else:
            return 1  # neutral

    texts, labels = [], []
    for split in ["train", "validation", "test"]:
        for ex in ds[split]:
            sentiment = collapse_labels(ex)
            texts.append(ex["text"])
            labels.append(sentiment)

    # Split: use 90% train, 10% val (deterministic)
    n = len(texts)
    indices = np.random.RandomState(42).permutation(n)
    split_idx = int(0.9 * n)
    train_idx, val_idx = indices[:split_idx], indices[split_idx:]

    train_texts = [texts[i] for i in train_idx]
    train_labels = [labels[i] for i in train_idx]
    val_texts = [texts[i] for i in val_idx]
    val_labels = [labels[i] for i in val_idx]

    print(f"  GoEmotions collapsed: {len(train_texts)} train, {len(val_texts)} val")
    dist = {ID2LABEL[i]: sum(1 for l in train_labels if l == i) for i in range(3)}
    print(f"  Distribution (train): {dist}")

    enc_train = tokenizer(train_texts, truncation=True, padding=False, max_length=min(max_length, 128))
    enc_val = tokenizer(val_texts, truncation=True, padding=False, max_length=min(max_length, 128))
    return SentimentDataset(enc_train, train_labels), SentimentDataset(enc_val, val_labels)


def load_walmart(tokenizer, max_length: int, data_path: str):
    """Load the 200 labeled Walmart posts."""
    texts, labels = [], []
    with open(data_path, "r") as f:
        for line in f:
            row = json.loads(line)
            sentiment = row.get("human_sentiment", "").strip().lower()
            if sentiment not in LABEL2ID:
                continue
            # Combine title + body for full context (ModernBERT handles 8192 tokens)
            text = f"{row['title']}\n\n{row['body']}"
            texts.append(text)
            labels.append(LABEL2ID[sentiment])

    print(f"  Walmart dataset: {len(texts)} posts")
    dist = {ID2LABEL[i]: sum(1 for l in labels if l == i) for i in range(3)}
    print(f"  Distribution: {dist}")
    return texts, labels


# ─── Training stages ────────────────────────────────────────────────────────


def train_stage(
    stage_name: str,
    model,
    tokenizer,
    train_dataset,
    eval_dataset,
    output_dir: str,
    epochs: int,
    batch_size: int,
    lr: float,
    seed: int,
    early_stopping: bool = True,
    gradient_accumulation_steps: int = 1,
):
    """Run a training stage with the Trainer API."""
    print(f"\n{'='*60}")
    print(f"  STAGE: {stage_name}")
    print(f"  Output: {output_dir}")
    print(f"  Epochs: {epochs}, BS: {batch_size}, LR: {lr}")
    print(f"{'='*60}\n")

    # MPS doesn't support fp16; use bf16 on CUDA or fp32 on MPS/CPU
    device = get_device()
    use_fp16 = device == "cuda"

    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        learning_rate=lr,
        weight_decay=0.01,
        warmup_ratio=0.1,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        save_total_limit=2,
        fp16=use_fp16,
        seed=seed,
        logging_steps=50,
        report_to="none",
        dataloader_num_workers=0,  # MPS doesn't handle multiprocess DataLoader well
    )

    callbacks = []
    if early_stopping and epochs > 3:
        callbacks.append(EarlyStoppingCallback(early_stopping_patience=3))

    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        compute_metrics=compute_metrics,
        data_collator=data_collator,
        callbacks=callbacks,
    )

    trainer.train()

    # Evaluate
    results = trainer.evaluate()
    print(f"\n  {stage_name} final eval: macro_f1={results['eval_macro_f1']:.4f}")
    print(f"    neg={results['eval_f1_negative']:.4f}  neu={results['eval_f1_neutral']:.4f}  pos={results['eval_f1_positive']:.4f}")

    # Save best model
    best_dir = os.path.join(output_dir, "best")
    trainer.save_model(best_dir)
    tokenizer.save_pretrained(best_dir)
    print(f"  Saved best model to {best_dir}")

    return trainer, results


def run_stage1(args, tokenizer):
    """Stage 1: Warm-up on TweetEval sentiment."""
    output_dir = os.path.join(args.output_dir, "stage1_tweeteval")
    if args.skip_if_exists and os.path.exists(os.path.join(output_dir, "best")):
        print(f"[SKIP] Stage 1 checkpoint exists: {output_dir}/best")
        return output_dir + "/best"

    print("\n[Stage 1] Loading TweetEval sentiment...")
    train_ds, val_ds, test_ds = load_tweeteval(tokenizer, args.max_length)

    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=NUM_LABELS,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    _, results = train_stage(
        stage_name="Stage 1: TweetEval",
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        output_dir=output_dir,
        epochs=args.epochs_s1,
        batch_size=args.batch_size,
        lr=args.lr,
        seed=args.seed,
        early_stopping=False,
    )

    return os.path.join(output_dir, "best")


def run_stage2(args, tokenizer, stage1_model_path: str):
    """Stage 2: Fine-tune on GoEmotions (collapsed to 3 classes)."""
    output_dir = os.path.join(args.output_dir, "stage2_goemotions")
    if args.skip_if_exists and os.path.exists(os.path.join(output_dir, "best")):
        print(f"[SKIP] Stage 2 checkpoint exists: {output_dir}/best")
        return output_dir + "/best"

    print("\n[Stage 2] Loading GoEmotions...")
    train_ds, val_ds = load_goemotions(tokenizer, args.max_length)

    # Load from Stage 1 checkpoint
    model = AutoModelForSequenceClassification.from_pretrained(
        stage1_model_path,
        num_labels=NUM_LABELS,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    _, results = train_stage(
        stage_name="Stage 2: GoEmotions",
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        output_dir=output_dir,
        epochs=args.epochs_s2,
        batch_size=args.batch_size,
        lr=args.lr * 0.5,  # Lower LR for second stage
        seed=args.seed,
        early_stopping=False,
    )

    return os.path.join(output_dir, "best")


def run_stage3(args, tokenizer, stage2_model_path: str):
    """Stage 3: Stratified K-fold CV on Walmart-200 with class balancing."""
    output_dir = os.path.join(args.output_dir, "stage3_walmart")
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n[Stage 3] Walmart-200 with {args.folds}-fold stratified CV...")
    texts, labels = load_walmart(tokenizer, args.max_length, args.walmart_data)

    # Use max_length=1024 for training so the model learns from long posts
    # (ModernBERT's long-context advantage — RoBERTa is capped at 512)
    stage3_max_length = 1024

    labels_arr = np.array(labels)
    skf = StratifiedKFold(n_splits=args.folds, shuffle=True, random_state=args.seed)

    # Compute class weights (inverse frequency)
    from collections import Counter
    counts = Counter(labels)
    total = len(labels)
    class_weights = [total / (NUM_LABELS * counts[i]) for i in range(NUM_LABELS)]
    print(f"  Class weights: neg={class_weights[0]:.2f}, neu={class_weights[1]:.2f}, pos={class_weights[2]:.2f}")

    fold_results = []
    all_preds = np.zeros(len(labels), dtype=int)

    # At max_length=1024, drop micro-batch to 8 and keep effective BS=32 via accumulation
    stage3_bs = min(args.batch_size, 8)
    stage3_accum = max(1, 32 // stage3_bs)
    stage3_lr = args.lr  # Use full LR (2e-5) instead of 0.25x

    for fold_idx, (train_idx, val_idx) in enumerate(skf.split(texts, labels_arr)):
        fold_dir = os.path.join(output_dir, f"fold_{fold_idx}")
        if args.skip_if_exists and os.path.exists(os.path.join(fold_dir, "best")):
            print(f"  [SKIP] Fold {fold_idx} checkpoint exists")
            continue

        print(f"\n  --- Fold {fold_idx + 1}/{args.folds} ---")
        print(f"  Train: {len(train_idx)}, Val: {len(val_idx)}")

        train_texts = [texts[i] for i in train_idx]
        train_labels = [labels[i] for i in train_idx]
        val_texts = [texts[i] for i in val_idx]
        val_labels = [labels[i] for i in val_idx]

        # Oversample minority classes in training set
        train_texts_bal, train_labels_bal = oversample_minority(train_texts, train_labels)
        print(f"  After oversampling: {len(train_labels_bal)} train samples")
        bal_dist = Counter(train_labels_bal)
        print(f"  Balanced dist: {{{', '.join(f'{ID2LABEL[k]}: {v}' for k, v in sorted(bal_dist.items()))}}}")

        # Show fold distribution
        val_dist = {ID2LABEL[i]: sum(1 for l in val_labels if l == i) for i in range(3)}
        print(f"  Val distribution: {val_dist}")

        # Tokenize with max_length=512 for training efficiency
        enc_train = tokenizer(train_texts_bal, truncation=True, padding=False, max_length=stage3_max_length)
        enc_val = tokenizer(val_texts, truncation=True, padding=False, max_length=stage3_max_length)
        train_ds = SentimentDataset(enc_train, train_labels_bal)
        val_ds = SentimentDataset(enc_val, val_labels)

        # Fresh model from Stage 2 for each fold
        model = AutoModelForSequenceClassification.from_pretrained(
            stage2_model_path,
            num_labels=NUM_LABELS,
            id2label=ID2LABEL,
            label2id=LABEL2ID,
        )

        # Training args
        fold_training_args = TrainingArguments(
            output_dir=fold_dir,
            num_train_epochs=args.epochs_s3,
            per_device_train_batch_size=stage3_bs,
            per_device_eval_batch_size=stage3_bs,
            gradient_accumulation_steps=stage3_accum,
            learning_rate=stage3_lr,
            weight_decay=0.01,
            warmup_ratio=0.1,
            eval_strategy="epoch",
            save_strategy="epoch",
            load_best_model_at_end=True,
            metric_for_best_model="macro_f1",
            greater_is_better=True,
            save_total_limit=2,
            fp16=False,
            seed=args.seed + fold_idx,
            logging_steps=20,
            report_to="none",
            dataloader_num_workers=0,
        )

        callbacks = [EarlyStoppingCallback(early_stopping_patience=3)]
        data_collator = DataCollatorWithPadding(tokenizer=tokenizer)

        trainer = WeightedTrainer(
            class_weights=class_weights,
            model=model,
            args=fold_training_args,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            compute_metrics=compute_metrics,
            data_collator=data_collator,
            callbacks=callbacks,
        )

        trainer.train()

        # Evaluate
        results = trainer.evaluate()
        print(f"\n  Stage 3 Fold {fold_idx + 1} final eval: macro_f1={results['eval_macro_f1']:.4f}")
        print(f"    neg={results['eval_f1_negative']:.4f}  neu={results['eval_f1_neutral']:.4f}  pos={results['eval_f1_positive']:.4f}")

        # Save best model
        best_dir = os.path.join(fold_dir, "best")
        trainer.save_model(best_dir)
        tokenizer.save_pretrained(best_dir)

        # Get predictions for this fold's validation set
        preds_output = trainer.predict(val_ds)
        fold_preds = np.argmax(preds_output.predictions, axis=-1)
        all_preds[val_idx] = fold_preds

        fold_results.append({
            "fold": fold_idx,
            "macro_f1": results["eval_macro_f1"],
            "f1_negative": results["eval_f1_negative"],
            "f1_neutral": results["eval_f1_neutral"],
            "f1_positive": results["eval_f1_positive"],
        })

    # Aggregate CV results
    if fold_results:
        print(f"\n{'='*60}")
        print(f"  STAGE 3 CROSS-VALIDATION RESULTS ({args.folds}-fold)")
        print(f"{'='*60}")
        macro_f1s = [r["macro_f1"] for r in fold_results]
        print(f"  Macro F1: {np.mean(macro_f1s):.4f} ± {np.std(macro_f1s):.4f}")
        for cls in ["negative", "neutral", "positive"]:
            scores = [r[f"f1_{cls}"] for r in fold_results]
            print(f"  {cls:>10}: {np.mean(scores):.4f} ± {np.std(scores):.4f}")

        # Full classification report
        print(f"\n  Aggregated classification report (out-of-fold predictions):")
        print(classification_report(labels_arr, all_preds, target_names=["negative", "neutral", "positive"]))

        # Save results
        results_path = os.path.join(output_dir, "cv_results.json")
        cv_summary = {
            "folds": args.folds,
            "seed": args.seed,
            "macro_f1_mean": float(np.mean(macro_f1s)),
            "macro_f1_std": float(np.std(macro_f1s)),
            "fold_results": fold_results,
            "per_sample_predictions": [
                {"index": i, "true": ID2LABEL[labels_arr[i]], "pred": ID2LABEL[all_preds[i]]}
                for i in range(len(labels_arr))
            ],
        }
        with open(results_path, "w") as f:
            json.dump(cv_summary, f, indent=2)
        print(f"\n  CV results saved to {results_path}")

    # Train final model on ALL data for deployment (with oversampling)
    print(f"\n  Training final model on all 200 posts (with oversampling + class weights)...")
    texts_bal, labels_bal = oversample_minority(texts, labels)
    enc_all = tokenizer(texts_bal, truncation=True, padding=False, max_length=stage3_max_length)
    all_ds = SentimentDataset(enc_all, labels_bal)

    final_model = AutoModelForSequenceClassification.from_pretrained(
        stage2_model_path,
        num_labels=NUM_LABELS,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    final_dir = os.path.join(output_dir, "final")
    training_args = TrainingArguments(
        output_dir=final_dir,
        num_train_epochs=args.epochs_s3,
        per_device_train_batch_size=stage3_bs,
        gradient_accumulation_steps=stage3_accum,
        learning_rate=stage3_lr,
        weight_decay=0.01,
        warmup_ratio=0.1,
        save_strategy="epoch",
        save_total_limit=1,
        fp16=False,
        seed=args.seed,
        logging_steps=10,
        report_to="none",
        dataloader_num_workers=0,
    )

    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)

    trainer = WeightedTrainer(
        class_weights=class_weights,
        model=final_model,
        args=training_args,
        train_dataset=all_ds,
        data_collator=data_collator,
    )
    trainer.train()

    # Save final deployable model
    deploy_dir = os.path.join(args.output_dir, "final")
    trainer.save_model(deploy_dir)
    tokenizer.save_pretrained(deploy_dir)
    print(f"\n  Final deployable model saved to {deploy_dir}")

    return deploy_dir


# ─── Main ───────────────────────────────────────────────────────────────────


def main():
    args = parse_args()
    stages = [int(s.strip()) for s in args.stages.split(",")]
    set_seed(args.seed)

    print(f"ModernBERT Sentiment Training")
    print(f"  Model: {MODEL_NAME}")
    print(f"  Device: {get_device()}")
    print(f"  Stages: {stages}")
    print(f"  Output: {args.output_dir}")
    print(f"  Max length: {args.max_length} tokens")

    os.makedirs(args.output_dir, exist_ok=True)

    # Load tokenizer once (shared across all stages)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

    # Track where each stage's best model lives
    stage1_path = os.path.join(args.output_dir, "stage1_tweeteval", "best")
    stage2_path = os.path.join(args.output_dir, "stage2_goemotions", "best")

    if 1 in stages:
        stage1_path = run_stage1(args, tokenizer)

    if 2 in stages:
        if not os.path.exists(stage1_path):
            print(f"ERROR: Stage 1 model not found at {stage1_path}. Run stage 1 first.")
            sys.exit(1)
        stage2_path = run_stage2(args, tokenizer, stage1_path)

    if 3 in stages:
        if not os.path.exists(stage2_path):
            print(f"ERROR: Stage 2 model not found at {stage2_path}. Run stages 1-2 first.")
            sys.exit(1)
        run_stage3(args, tokenizer, stage2_path)

    print("\n" + "=" * 60)
    print("  TRAINING COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
