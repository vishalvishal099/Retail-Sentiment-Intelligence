"""
Interactive CLI labeler for data/benchmark_annotations.jsonl

Usage:
    python scripts/label_benchmark.py                  # label only unlabeled rows
    python scripts/label_benchmark.py --review         # walk every row (including labeled)
    python scripts/label_benchmark.py --start 50       # jump to row 50
    python scripts/label_benchmark.py --recheck        # second pass mode (writes human_sentiment_recheck)
    python scripts/label_benchmark.py --recheck --sample 30 --seed 7   # pick 30 random rows for self-agreement
    python scripts/label_benchmark.py --stats          # show progress + agreement, do not label
    python scripts/label_benchmark.py --file data/other.jsonl

Keys during labeling:
    1 = positive   2 = neutral   3 = negative
    s = skip       u = undo last   b = back one
    n = add note   q = save & quit
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path("data/benchmark_annotations.jsonl")
LABEL_KEY = "human_sentiment"
RECHECK_KEY = "human_sentiment_recheck"
LABEL_MAP = {"1": "positive", "2": "neutral", "3": "negative"}
VALID_LABELS = set(LABEL_MAP.values())
ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "magenta": "\033[35m",
}


def c(text: str, *styles: str) -> str:
    return "".join(ANSI[s] for s in styles) + text + ANSI["reset"]


def load(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def save_atomic(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    backup = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        shutil.copyfile(path, backup)
    tmp.replace(path)


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def render(row: dict, idx: int, total: int, key: str, reference_key: Optional[str] = None,
           suggestion: Optional[dict] = None) -> None:
    width = shutil.get_terminal_size((100, 24)).columns
    bar = "─" * min(width, 100)
    clear()
    print(c(bar, "cyan"))
    header = f" Post {idx + 1}/{total}   r/{row.get('subreddit', '?')}   id={row.get('id', '?')[:12]}"
    print(c(header, "bold", "cyan"))
    print(c(bar, "cyan"))
    print()
    print(c("TITLE:", "bold") + " " + (row.get("title") or "").strip())
    print()
    body = (row.get("body") or "").strip()
    if body and body != (row.get("title") or "").strip():
        print(c("BODY:", "bold"))
        print(body)
    else:
        print(c("(body same as title or empty)", "dim"))
    print()
    print(c(bar, "dim"))

    # Length info
    text_len = len(row.get("title", "") or "") + len(body)
    approx_tokens = text_len // 4
    bucket = "<256" if approx_tokens < 256 else ("256–512" if approx_tokens < 512 else (">512" if approx_tokens < 1024 else ">1024"))
    print(c(f"~{approx_tokens} tokens  ({bucket})", "dim"))

    # Model prediction (helpful but don't anchor — show last)
    mp = row.get("_model_sentiment")
    mc = row.get("_model_confidence")
    if mp:
        col = "green" if mp == "positive" else ("red" if mp == "negative" else "yellow")
        print(c(f"model predicted: {mp}  (confidence {mc})", col, "dim"))

    # Existing label if any
    existing = row.get(key)
    if existing:
        col = "green" if existing == "positive" else ("red" if existing == "negative" else "yellow")
        print(c(f"current {key}: {existing}", col))
    if reference_key and row.get(reference_key):
        ref = row.get(reference_key)
        col = "green" if ref == "positive" else ("red" if ref == "negative" else "yellow")
        print(c(f"first-pass {reference_key}: {ref}", col, "dim"))

    note = (row.get("notes") or "").strip()
    if note:
        print(c(f"note: {note}", "magenta", "dim"))

    if suggestion and suggestion.get("label") in VALID_LABELS:
        s_label = suggestion["label"]
        s_reason = suggestion.get("reason", "")
        col = "green" if s_label == "positive" else ("red" if s_label == "negative" else "yellow")
        print(c(bar, "dim"))
        print(c(f"AI suggestion: {s_label.upper()}", "bold", col))
        if s_reason:
            print(c(f"  why: {s_reason}", col, "dim"))

    print(c(bar, "dim"))
    print()
    print(c("  [1] positive   [2] neutral   [3] negative", "bold"))
    if suggestion and suggestion.get("label") in VALID_LABELS:
        print(c("  [Enter] accept AI suggestion", "bold", "green"))
    print(c("  [s] skip   [u] undo last   [b] back   [n] note   [q] save & quit", "dim"))


def stats(rows: list[dict], key: str, label: str) -> None:
    counts = Counter(r.get(key) for r in rows if r.get(key))
    labeled = sum(counts.values())
    print(f"\n{label}: {labeled}/{len(rows)} labeled")
    for lbl in ("positive", "neutral", "negative"):
        print(f"  {lbl:10} {counts.get(lbl, 0)}")


def agreement(rows: list[dict]) -> None:
    pairs = [(r.get(LABEL_KEY), r.get(RECHECK_KEY)) for r in rows if r.get(LABEL_KEY) and r.get(RECHECK_KEY)]
    if not pairs:
        print(c("\nNo recheck labels yet — nothing to compare.", "dim"))
        return
    agree = sum(1 for a, b in pairs if a == b)
    total = len(pairs)
    p_o = agree / total
    # Cohen's kappa with self
    labels = ("positive", "neutral", "negative")
    p_e = 0.0
    for lbl in labels:
        p1 = sum(1 for a, _ in pairs if a == lbl) / total
        p2 = sum(1 for _, b in pairs if b == lbl) / total
        p_e += p1 * p2
    kappa = (p_o - p_e) / (1 - p_e) if p_e < 1 else 1.0
    print(c(f"\nSelf-agreement: {agree}/{total} = {p_o:.1%}   kappa={kappa:.3f}", "bold", "green" if kappa >= 0.75 else "yellow"))
    disagree = [(r.get("id"), r.get(LABEL_KEY), r.get(RECHECK_KEY)) for r in rows if r.get(LABEL_KEY) and r.get(RECHECK_KEY) and r.get(LABEL_KEY) != r.get(RECHECK_KEY)]
    if disagree:
        print(c(f"Disagreements ({len(disagree)}):", "yellow"))
        for rid, a, b in disagree[:10]:
            print(f"  {rid[:12]}  first={a}  recheck={b}")
        if len(disagree) > 10:
            print(f"  ... and {len(disagree) - 10} more")


def select_indices(rows: list[dict], args) -> list[int]:
    """Return the ordered list of row indices to walk."""
    n = len(rows)
    key = RECHECK_KEY if args.recheck else LABEL_KEY

    if args.review:
        indices = list(range(n))
    elif args.recheck and args.sample:
        # pick `sample` already-labeled rows, deterministic with --seed
        labeled = [i for i, r in enumerate(rows) if r.get(LABEL_KEY)]
        if not labeled:
            print(c("Cannot recheck: no first-pass labels exist yet.", "red"))
            sys.exit(1)
        rng = random.Random(args.seed)
        k = min(args.sample, len(labeled))
        indices = sorted(rng.sample(labeled, k))
    else:
        indices = [i for i, r in enumerate(rows) if not r.get(key)]

    if args.start:
        indices = [i for i in indices if i >= args.start]
    return indices


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT_PATH))
    ap.add_argument("--review", action="store_true", help="walk every row, even labeled ones")
    ap.add_argument("--recheck", action="store_true", help="second pass — writes to human_sentiment_recheck")
    ap.add_argument("--sample", type=int, default=0, help="(with --recheck) randomly pick N labeled rows")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for --sample")
    ap.add_argument("--start", type=int, default=0, help="start at this row index (0-based)")
    ap.add_argument("--stats", action="store_true", help="show progress + agreement and exit")
    ap.add_argument("--assist", action="store_true",
                    help="show AI suggestions; pressing Enter accepts the suggestion")
    ap.add_argument("--suggestions", default="",
                    help="path to suggestions sidecar JSONL (defaults to <file>.suggestions.jsonl)")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(c(f"File not found: {path}", "red"))
        return 1

    rows = load(path)

    suggestions: dict[str, dict] = {}
    if args.assist:
        sug_path = Path(args.suggestions) if args.suggestions else path.with_suffix(path.suffix + ".suggestions.jsonl")
        if not sug_path.exists():
            print(c(f"--assist requested but suggestions file not found: {sug_path}", "red"))
            print(c("Generate it with: scripts/gen_suggestions.py --file <data>", "dim"))
            return 1
        with sug_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if "id" in obj:
                    suggestions[obj["id"]] = obj
        print(c(f"Loaded {len(suggestions)} AI suggestions from {sug_path}", "green"))

    if args.stats:
        stats(rows, LABEL_KEY, "First pass (human_sentiment)")
        stats(rows, RECHECK_KEY, "Recheck (human_sentiment_recheck)")
        agreement(rows)
        return 0

    indices = select_indices(rows, args)
    if not indices:
        print(c("Nothing to label — all selected rows already have a label.", "green"))
        stats(rows, LABEL_KEY, "First pass")
        return 0

    key = RECHECK_KEY if args.recheck else LABEL_KEY
    ref = LABEL_KEY if args.recheck else None
    print(c(f"\n{len(indices)} rows to label. Writing to field: {key}", "cyan"))
    input(c("Press Enter to start...", "dim"))

    pos = 0
    history: list[tuple[int, str, Optional[str]]] = []  # (row_idx, key, prev_value)
    while 0 <= pos < len(indices):
        row_idx = indices[pos]
        row = rows[row_idx]
        sug = suggestions.get(row.get("id")) if args.assist else None
        render(row, row_idx, len(rows), key, reference_key=ref, suggestion=sug)
        print(c(f"  Progress: {pos + 1}/{len(indices)} in this session", "dim"))
        try:
            choice = input(c("> ", "bold")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            choice = "q"

        # Empty input = accept AI suggestion (only in --assist mode)
        if choice == "" and sug and sug.get("label") in VALID_LABELS:
            prev = row.get(key)
            row[key] = sug["label"]
            row["_assist_accepted"] = True
            row["_assist_suggestion"] = sug.get("label")
            history.append((row_idx, key, prev))
            save_atomic(path, rows)
            pos += 1
            continue

        if choice in LABEL_MAP:
            prev = row.get(key)
            new_label = LABEL_MAP[choice]
            row[key] = new_label
            if sug and sug.get("label") in VALID_LABELS:
                row["_assist_accepted"] = (new_label == sug["label"])
                row["_assist_suggestion"] = sug["label"]
            history.append((row_idx, key, prev))
            save_atomic(path, rows)
            pos += 1
        elif choice == "s":
            pos += 1
        elif choice == "b":
            pos = max(0, pos - 1)
        elif choice == "u":
            if history:
                last_idx, last_key, prev = history.pop()
                if prev is None:
                    rows[last_idx].pop(last_key, None)
                else:
                    rows[last_idx][last_key] = prev
                save_atomic(path, rows)
                # jump back to that row
                if last_idx in indices:
                    pos = indices.index(last_idx)
        elif choice == "n":
            note = input(c("note: ", "magenta")).strip()
            row["notes"] = note
            save_atomic(path, rows)
            # stay on same row
        elif choice == "q":
            break
        else:
            print(c("Unknown key. Press 1/2/3/s/u/b/n/q.", "yellow"))
            input(c("Enter to continue...", "dim"))

    clear()
    stats(rows, LABEL_KEY, "First pass (human_sentiment)")
    stats(rows, RECHECK_KEY, "Recheck (human_sentiment_recheck)")
    agreement(rows)
    print(c(f"\nSaved to {path}", "green"))
    print(c(f"Backup at {path.with_suffix(path.suffix + '.bak')}", "dim"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
