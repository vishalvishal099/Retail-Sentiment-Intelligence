"""Generate the additional flow-chart PNGs for the FINAL dissertation report.

Writes four figures into docs/Sem_4/figures/ (same folder the report reads):
    fig5_review_validate_flow.png  - Human-in-the-Loop Review & Validate flow
    fig6_reply_cascade.png         - Smart Reply Composer: triple-draft (GPT + Mistral + Smart) + few-shot
    fig7_learning_loop.png         - Feedback learning loop → future retraining (HITL removal)
    fig8_lifecycle_kanban.png      - Post Lifecycle Kanban states + close paths

Run:  /opt/miniconda3/bin/python docs/Sem_4/final/generate_final_diagrams.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "figures"
OUT.mkdir(parents=True, exist_ok=True)

NAVY = "#041E42"
BLUE = "#0071DC"
SKY = "#A9DDF7"
YELLOW = "#FFC220"
GREEN = "#76C043"
RED = "#E0162B"
GREY = "#5A6470"
LIGHT = "#F2F4F7"
WHITE = "#FFFFFF"
PURPLE = "#7B5EA7"


def _box(ax, x, y, w, h, text, *, face=SKY, edge=NAVY, text_color=NAVY,
         fontsize=9, weight="bold"):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.10",
        linewidth=1.2, edgecolor=edge, facecolor=face))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, color=text_color, weight=weight)


def _diamond(ax, x, y, w, h, text, *, face=YELLOW, edge=NAVY, fontsize=8.5):
    cx, cy = x + w / 2, y + h / 2
    pts = [(cx, y + h), (x + w, cy), (cx, y), (x, cy)]
    ax.add_patch(plt.Polygon(pts, closed=True, linewidth=1.2,
                             edgecolor=edge, facecolor=face))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize,
            color=NAVY, weight="bold")


def _arrow(ax, x1, y1, x2, y2, color=NAVY, lw=1.5, label=None,
           label_off=(0.0, 0.12), rad=0.0):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=13,
        linewidth=lw, color=color,
        connectionstyle=f"arc3,rad={rad}"))
    if label:
        mx, my = (x1 + x2) / 2 + label_off[0], (y1 + y2) / 2 + label_off[1]
        ax.text(mx, my, label, ha="center", va="center", fontsize=7.5,
                color=GREY, style="italic")


def _title(ax, text):
    ax.set_title(text, fontsize=12, weight="bold", color=NAVY, pad=10)


# ---------------------------------------------------------------------------
# Figure 5 — Review & Validate HITL flow
# ---------------------------------------------------------------------------

def fig5_review_validate_flow():
    fig, ax = plt.subplots(figsize=(9.5, 9.0))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 15)
    ax.axis("off")

    _box(ax, 2.5, 13.6, 7.0, 1.0,
         "Pending Queue  —  needs_review = true, ordered P1 → P2",
         face=NAVY, edge=NAVY, text_color=WHITE, fontsize=10)
    _arrow(ax, 6.0, 13.6, 6.0, 13.05)

    _box(ax, 2.5, 12.0, 7.0, 1.0,
         "Analyst opens card  (title · body · sentiment · aspects · trust · vision caption)",
         face=SKY, fontsize=9)
    _arrow(ax, 6.0, 12.0, 6.0, 11.45)

    _box(ax, 0.5, 10.3, 3.3, 1.0, "Correct sentiment\n(pos / neu / neg)", face=LIGHT, fontsize=8.5)
    _box(ax, 4.35, 10.3, 3.3, 1.0, "Add / remove aspects\n(customer · employee)", face=LIGHT, fontsize=8.5)
    _box(ax, 8.2, 10.3, 3.3, 1.0, "Override trust\nscore", face=LIGHT, fontsize=8.5)
    for cx in (2.15, 6.0, 9.85):
        _arrow(ax, 6.0, 12.0, cx, 11.35, color=GREY, lw=1.1)
        _arrow(ax, cx, 10.3, 6.0, 9.75, color=GREY, lw=1.1)

    _box(ax, 3.0, 8.75, 6.0, 1.0,
         "Generate Drafts  →  Smart Reply Composer (Fig 6)",
         face=YELLOW, fontsize=9.5)
    _arrow(ax, 6.0, 8.75, 6.0, 8.2)

    _diamond(ax, 4.3, 6.7, 3.4, 1.6, "Post public\nreply?", face=SKY)
    _arrow(ax, 6.0, 8.75 - 0.0, 6.0, 8.3)

    # Yes path
    _box(ax, 8.0, 6.9, 3.6, 1.1,
         "Post Reply\n(dry-run gate → Reddit)\nsave to audit log",
         face=GREEN, fontsize=8.5)
    _arrow(ax, 7.7, 7.5, 8.0, 7.45, color=GREEN, label="yes", label_off=(0.1, 0.25))

    # No path
    _box(ax, 0.4, 6.9, 3.6, 1.1,
         "Close as:\nreply_sent · action_needed\n· no_reply_required",
         face=LIGHT, fontsize=8.5)
    _arrow(ax, 4.3, 7.5, 4.0, 7.45, color=GREY, label="no", label_off=(-0.1, 0.25))

    _box(ax, 2.5, 4.9, 7.0, 1.0,
         "needs_review = false  (atomic)  →  card leaves queue",
         face=NAVY, edge=NAVY, text_color=WHITE, fontsize=9.5)
    _arrow(ax, 9.8, 6.9, 8.0, 5.9, color=NAVY)
    _arrow(ax, 2.2, 6.9, 4.0, 5.9, color=NAVY)

    _box(ax, 2.5, 3.0, 7.0, 1.2,
         "feedback table  ←  post · corrected label · corrected aspects ·\n"
         "approved reply · model used · action note",
         face=PURPLE, edge=NAVY, text_color=WHITE, fontsize=8.8)
    _arrow(ax, 6.0, 4.9, 6.0, 4.25, color=PURPLE, lw=1.8)

    _box(ax, 2.5, 1.2, 7.0, 1.0,
         "Learning Loop (Fig 7):  few-shot now  →  fine-tune later",
         face=LIGHT, edge=PURPLE, fontsize=9)
    _arrow(ax, 6.0, 3.0, 6.0, 2.25, color=PURPLE)

    _title(ax, "Figure 5 — Human-in-the-Loop Review & Validate Flow")
    fig.tight_layout()
    out = OUT / "fig5_review_validate_flow.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 6 — Smart Reply Composer: triple-draft + few-shot prompting
# ---------------------------------------------------------------------------

def fig6_reply_cascade():
    fig, ax = plt.subplots(figsize=(11, 6.6))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8.5)
    ax.axis("off")

    # Inputs (top-left)
    _box(ax, 0.4, 6.7, 4.6, 1.2,
         "Post text + aspects + subreddit\n+ vision caption (if image)",
         face=SKY, fontsize=9)
    _box(ax, 0.4, 4.9, 4.6, 1.3,
         "Few-shot exemplars\n(top-3 recent approved replies\nfrom feedback table)",
         face=PURPLE, edge=NAVY, text_color=WHITE, fontsize=8.8)

    # Composer hub (center)
    _box(ax, 5.6, 5.4, 2.8, 1.9,
         "Smart Reply\nComposer\n(one prompt)",
         face=YELLOW, fontsize=10)
    _arrow(ax, 5.0, 7.3, 5.6, 7.0, color=NAVY)
    _arrow(ax, 5.0, 5.55, 5.6, 5.8, color=PURPLE, lw=1.8,
           label="injected as\nexamples", label_off=(0, 0.55))

    # Three draft engines (right column, top to bottom)
    _box(ax, 9.4, 7.1, 4.2, 1.0,
         "Draft A — GPT-4o  (Walmart Gateway)\nhighest-quality, ~$0.0002 / reply",
         face=SKY, fontsize=8.6)
    _box(ax, 9.4, 5.8, 4.2, 1.0,
         "Draft B — Mistral 7B  (local Ollama)\nopen-weights, free, offline",
         face=PURPLE, edge=NAVY, text_color=WHITE, fontsize=8.6)
    _box(ax, 9.4, 4.5, 4.2, 1.0,
         "Draft C — Smart Composer  (no LLM)\ndeterministic safety net",
         face=GREEN, fontsize=8.6)
    _arrow(ax, 8.4, 6.6, 9.4, 7.6, color=NAVY, lw=1.5)
    _arrow(ax, 8.4, 6.3, 9.4, 6.3, color=NAVY, lw=1.5)
    _arrow(ax, 8.4, 6.0, 9.4, 5.0, color=NAVY, lw=1.5)

    # Fallback annotation
    ax.text(11.5, 3.9, "if slot A or B fails  →  slot falls back to Smart Composer  ([offline fallback] badge)",
            ha="center", fontsize=8, color=GREY, style="italic")

    # Output to analyst
    _box(ax, 3.2, 2.0, 7.6, 1.1,
         "Three drafts + action note  →  Analyst picks A / B / C, edits, posts",
         face=NAVY, edge=NAVY, text_color=WHITE, fontsize=9.5)
    _arrow(ax, 9.4, 5.0, 8.0, 3.1, color=NAVY, lw=1.3)

    # Feedback loop back to few-shot
    _box(ax, 3.2, 0.4, 7.6, 1.0,
         "Approved reply stored in feedback table  →  becomes next few-shot exemplar",
         face=PURPLE, edge=NAVY, text_color=WHITE, fontsize=8.8)
    _arrow(ax, 7.0, 2.0, 7.0, 1.4, color=PURPLE, lw=1.8)
    _arrow(ax, 3.2, 0.9, 1.6, 0.9, color=PURPLE, lw=1.3)
    _arrow(ax, 1.6, 0.9, 1.6, 5.55, color=PURPLE, lw=1.3, rad=0.0)
    _arrow(ax, 1.6, 5.55, 0.4, 5.55, color=PURPLE, lw=1.3)

    _title(ax, "Figure 6 — Smart Reply Composer: Triple-Draft (GPT-4o + Mistral + Smart Composer) with Few-Shot Prompting")
    fig.tight_layout()
    out = OUT / "fig6_reply_cascade.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 7 — Learning loop → future retraining
# ---------------------------------------------------------------------------

def fig7_learning_loop():
    fig, ax = plt.subplots(figsize=(11, 6.4))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8)
    ax.axis("off")

    _box(ax, 0.5, 6.4, 4.0, 1.1,
         "Analyst approves reply\n+ correction + action note",
         face=SKY, fontsize=9)
    _arrow(ax, 4.5, 6.95, 5.4, 6.0, color=NAVY)

    _box(ax, 5.4, 5.2, 3.4, 1.6,
         "feedback table\n(post → approved reply,\nlabel, aspects, model,\naction note)",
         face=PURPLE, edge=NAVY, text_color=WHITE, fontsize=8.6)

    # Near-term branch
    _box(ax, 9.6, 6.4, 4.0, 1.1,
         "NEAR TERM — few-shot prompts\n(no training, tone improves)",
         face=GREEN, fontsize=8.6)
    _arrow(ax, 8.8, 6.3, 9.6, 6.9, color=GREEN)

    _box(ax, 9.6, 4.7, 4.0, 1.1,
         "Periodic ModernBERT\nre-calibration on new labels",
         face=YELLOW, fontsize=8.6)
    _arrow(ax, 8.8, 5.7, 9.6, 5.25, color=NAVY)

    # Long-term branch
    _diamond(ax, 5.2, 2.7, 3.8, 1.6, "corpus ≈\n1M pairs?", face=SKY, fontsize=8.5)
    _arrow(ax, 7.1, 5.2, 7.1, 4.3, color=NAVY)

    _box(ax, 9.6, 2.9, 4.0, 1.1,
         "LONG TERM — fine-tune Mistral\non Walmart post→reply data",
         face=RED, edge=NAVY, text_color=WHITE, fontsize=8.6)
    _arrow(ax, 9.0, 3.5, 9.6, 3.45, color=RED, label="yes", label_off=(0.1, 0.25))
    _arrow(ax, 7.1, 2.7, 7.1, 2.1, color=GREY, label="keep collecting", label_off=(1.4, 0.0))

    _box(ax, 9.6, 1.1, 4.0, 1.1,
         "Supervised / auto-reply mode\nHITL reserved for hard cases",
         face=NAVY, edge=NAVY, text_color=WHITE, fontsize=8.6)
    _arrow(ax, 11.6, 2.9, 11.6, 2.2, color=RED, lw=1.8)

    ax.text(2.4, 0.6,
            "Design goal: every human correction manufactures training data that "
            "progressively removes the HITL dependency.",
            ha="left", fontsize=8.5, color=GREY, style="italic")

    _title(ax, "Figure 7 — Feedback Learning Loop: from Few-Shot Today to Auto-Reply Tomorrow")
    fig.tight_layout()
    out = OUT / "fig7_learning_loop.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 8 — Post Lifecycle Kanban
# ---------------------------------------------------------------------------

def fig8_lifecycle_kanban():
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7)
    ax.axis("off")

    states = [
        ("TRIAGED", "New P1/P2\nposts land here", SKY),
        ("ACKNOWLEDGED", "Analyst owns\nthe case", SKY),
        ("IN PROGRESS", "Reply drafted /\naction under way", YELLOW),
        ("RESOLVED", "Reply posted /\ncase closed", GREEN),
    ]
    w = 2.9
    xs = []
    for i, (title, body, color) in enumerate(states):
        x = 0.5 + i * (w + 0.55)
        xs.append(x)
        _box(ax, x, 4.2, w, 1.7, f"{title}\n\n{body}", face=color, fontsize=9)
        if i < len(states) - 1:
            _arrow(ax, x + w, 5.05, x + w + 0.55, 5.05, color=NAVY, lw=1.8)

    # transition labels (moved ABOVE the boxes so they don't overlap the state cards)
    ax.text(xs[0] + w + 0.27, 6.05, "acknowledge", ha="center", fontsize=7.5, color=GREY, style="italic")
    ax.text(xs[1] + w + 0.27, 6.05, "start work",  ha="center", fontsize=7.5, color=GREY, style="italic")
    ax.text(xs[2] + w + 0.27, 6.05, "resolve",     ha="center", fontsize=7.5, color=GREY, style="italic")

    # Two-step resolve note
    _box(ax, 0.5, 2.5, 6.0, 1.1,
         "Two-step resolve:\n1) save action note + draft   2) post on Reddit → mark Resolved",
         face=LIGHT, edge=NAVY, fontsize=8.6)
    # Close paths
    _box(ax, 7.0, 2.5, 6.5, 1.1,
         "Close paths: reply_sent (monitoring) ·\naction_needed (with note) · no_reply_required",
         face=LIGHT, edge=NAVY, fontsize=8.6)

    # every transition timestamped + follow-up banner
    _box(ax, 0.5, 0.7, 13.0, 1.0,
         "Every transition timestamped → SLA metrics.   Follow-up banner: reply sent ≥ 3 days, no resolution.",
         face=NAVY, edge=NAVY, text_color=WHITE, fontsize=9)
    _arrow(ax, xs[3] + w / 2, 4.2, xs[3] + w / 2, 3.6, color=GREEN)
    _arrow(ax, 3.5, 2.5, 3.5, 1.7, color=NAVY)
    _arrow(ax, 10.2, 2.5, 10.2, 1.7, color=NAVY)

    _title(ax, "Figure 8 — Post Lifecycle Kanban Workflow")
    fig.tight_layout()
    out = OUT / "fig8_lifecycle_kanban.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 9 — Ingestion & Pre-processing flow
# ---------------------------------------------------------------------------

def fig9_ingestion_flow():
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 5.5)
    ax.axis("off")

    steps = [
        ("25 subreddits\n(Walmart family +\ncompetitors)", SKY),
        ("Arctic Shift API\n(cursor pagination)\n+ optional PRAW", SKY),
        ("Clean HTML /\nMarkdown", LIGHT),
        ("langdetect →\nEnglish only", LIGHT),
        ("MiniLM-L6-v2 dedup\ncosine > 0.92\n= near-duplicate", YELLOW),
        ("SHA-hash usernames\n(1-year retention)", GREEN),
        ("raw_posts\ntable", NAVY),
    ]
    w = 2.0
    for i, (txt, color) in enumerate(steps):
        x = 0.3 + i * (w + 0.24)
        tc = WHITE if color == NAVY else NAVY
        _box(ax, x, 2.2, w, 1.6, txt, face=color, text_color=tc, fontsize=8.2)
        if i < len(steps) - 1:
            _arrow(ax, x + w, 3.0, x + w + 0.24, 3.0, color=NAVY, lw=1.6)

    ax.text(8.0, 1.4, "Incremental: only posts created since the last cursor are fetched "
                      "(90-day back-fill on first run).",
            ha="center", fontsize=8.3, color=GREY, style="italic")
    _title(ax, "Figure 9 — Data Ingestion and Pre-processing Flow")
    fig.tight_layout()
    out = OUT / "fig9_ingestion_flow.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 10 — ModernBERT 3-stage curriculum
# ---------------------------------------------------------------------------

def fig10_modernbert_curriculum():
    fig, ax = plt.subplots(figsize=(11, 5.2))
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 6)
    ax.axis("off")

    stages = [
        ("Stage 1\nTweetEval\n45k tweets", "Generic sentiment\ngrounding", "macro-F1 0.7267", SKY),
        ("Stage 2\nGoEmotions\n54k Reddit", "Reddit register +\npolarity",  "macro-F1 0.7028", SKY),
        ("Stage 3\nWalmart-200\n5-fold CV", "Domain specialise\n(class weights +\noversampling)", "macro-F1 0.7362 ± 0.12", YELLOW),
    ]
    w = 3.1
    gap = 0.35
    for i, (title, mid, metric, color) in enumerate(stages):
        x = 0.4 + i * (w + gap)
        _box(ax, x, 3.4, w, 1.7, title, face=color, fontsize=9.5)
        _box(ax, x, 1.9, w, 1.3, mid, face=LIGHT, fontsize=8.3)
        ax.text(x + w / 2, 1.4, metric, ha="center", fontsize=8.6, color=NAVY, weight="bold")
        if i < len(stages) - 1:
            _arrow(ax, x + w, 4.25, x + w + gap, 4.25, color=NAVY, lw=1.8)

    # Final model box — safely clear of Stage 3 (Stage 3 ends at x = 0.4 + 2*(w+gap) + w = 10.75)
    final_x = 11.30
    _box(ax, final_x, 3.4, 3.2, 1.7,
         "Final model\n(all 200 posts)\ndeployed", face=GREEN, edge=NAVY, fontsize=9)
    _arrow(ax, final_x - gap, 4.25, final_x, 4.25, color=NAVY, lw=1.8)
    ax.text(7.5, 0.6, "Reported numbers are 5-fold out-of-fold (no sample scored by a model "
                      "that trained on it). RoBERTa baseline: 0.6272.",
            ha="center", fontsize=8.3, color=GREY, style="italic")
    _title(ax, "Figure 10 — ModernBERT Three-Stage Fine-Tuning Curriculum")
    fig.tight_layout()
    out = OUT / "fig10_modernbert_curriculum.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 11 — Zero-shot NLI aspect tagging
# ---------------------------------------------------------------------------

def fig11_aspect_nli():
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 7)
    ax.axis("off")

    _box(ax, 0.4, 3.0, 3.2, 1.2, "Post text\n(+ vision caption)", face=SKY, fontsize=9)

    hyps = ["pricing", "delivery_pickup", "returns", "online_app", "workforce_hr"]
    for i, h in enumerate(hyps):
        # Start higher so the 5 hypothesis boxes don't collide with the bottom caption.
        y = 6.05 - i * 0.98
        _box(ax, 4.6, y, 3.2, 0.75,
             f"\u201cThis post is about {h}\u201d", face=LIGHT, fontsize=8.2)
        _arrow(ax, 3.6, 3.6, 4.6, y + 0.37, color=GREY, lw=1.0)
        _arrow(ax, 7.8, y + 0.37, 9.0, 3.6, color=GREY, lw=1.0)

    _box(ax, 9.0, 3.0, 2.8, 1.2, "DeBERTa-v3\nNLI entailment", face=YELLOW, fontsize=9)
    _box(ax, 12.2, 3.0, 2.5, 1.2, "score ≥ τ →\nmulti-aspect tags", face=NAVY,
         edge=NAVY, text_color=WHITE, fontsize=8.8)
    _arrow(ax, 11.8, 3.6, 12.2, 3.6, color=NAVY, lw=1.6)

    _box(ax, 4.6, 0.3, 7.2, 1.0,
         "Two sub-taxonomies kept separate: customer (7) · employee / workforce_hr (5)",
         face=LIGHT, edge=NAVY, fontsize=8.6)
    _arrow(ax, 13.4, 3.0, 8.2, 1.35, color=NAVY)

    _title(ax, "Figure 11 — Zero-Shot NLI Aspect Tagging (multi-aspect, no training data)")
    fig.tight_layout()
    out = OUT / "fig11_aspect_nli.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 12 — Vision multi-pass captioning pipeline
# ---------------------------------------------------------------------------

def fig12_vision_multipass():
    fig, ax = plt.subplots(figsize=(11, 5.4))
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 6.5)
    ax.axis("off")

    _box(ax, 0.4, 2.9, 2.4, 1.3, "Attached\nimage", face=SKY, fontsize=9)

    passes = [
        ("Pass 1\nSTRUCTURE", "What type?\n(screenshot / receipt\n/ photo / app)", SKY),
        ("Pass 2\nTILE", "Split into 2–4 crops\n(2–4× effective\nresolution)", SKY),
        ("Pass 3\nEXTRACT", "Read ALL text\nverbatim per tile\n(Gemma 3 4B)", YELLOW),
        ("Pass 4\nMERGE", "Text-only LLM —\nNO image →\ncannot hallucinate", GREEN),
    ]
    w = 2.55
    for i, (title, body, color) in enumerate(passes):
        x = 3.1 + i * (w + 0.35)
        _box(ax, x, 3.5, w, 1.3, title, face=color, fontsize=9)
        _box(ax, x, 1.9, w, 1.4, body, face=LIGHT, fontsize=7.8)
        if i == 0:
            _arrow(ax, 2.8, 3.55, x, 4.15, color=NAVY, lw=1.6)
        else:
            _arrow(ax, x - 0.35, 4.15, x, 4.15, color=NAVY, lw=1.6)

    _box(ax, 3.1, 0.5, 10.9, 0.95,
         "Result: hallucination 50% → 0% · text extraction 25% → 75% (Section 6.2)",
         face=NAVY, edge=NAVY, text_color=WHITE, fontsize=9)
    _title(ax, "Figure 12 — Vision Multi-Pass Anti-Hallucination Captioning Pipeline")
    fig.tight_layout()
    out = OUT / "fig12_vision_multipass.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 13 — Alert engine + notification routing
# ---------------------------------------------------------------------------

def fig13_alert_routing():
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 7)
    ax.axis("off")

    _box(ax, 0.4, 5.4, 3.0, 1.1, "analyses +\naggregates", face=SKY, fontsize=9)
    _box(ax, 0.4, 3.4, 3.0, 1.4,
         "Alert engine\nspike > 2σ ·\nsentiment drop > 0.3", face=YELLOW, fontsize=8.6)
    _arrow(ax, 1.9, 5.4, 1.9, 4.8, color=NAVY)

    _diamond(ax, 4.2, 3.4, 3.2, 1.6, "P1 / P2\nclassify", face=SKY, fontsize=9)
    _arrow(ax, 3.4, 4.1, 4.2, 4.2, color=NAVY)

    _box(ax, 8.0, 5.2, 6.6, 1.2,
         "Live Alert Feed (WebSocket push → dashboard)",
         face=GREEN, edge=NAVY, fontsize=9)
    _arrow(ax, 7.4, 4.6, 8.0, 5.4, color=GREEN, lw=1.6)

    _box(ax, 8.0, 3.2, 3.1, 1.5,
         "Notification groups\n(subreddit-owned:\nemail DL · Slack ·\npriority filter)", face=SKY, fontsize=8.2)
    _arrow(ax, 7.4, 4.0, 8.0, 3.95, color=NAVY)

    _box(ax, 11.5, 3.2, 3.1, 1.5,
         "Dispatch:\nEmail / Slack\n+ audit log\n(dry-run mode)", face=LIGHT, edge=NAVY, fontsize=8.2)
    _arrow(ax, 11.1, 3.95, 11.5, 3.95, color=NAVY, lw=1.6)

    _box(ax, 4.2, 1.1, 7.0, 1.0,
         "One-click from feed → Post Explorer → Review & Validate → Lifecycle",
         face=NAVY, edge=NAVY, text_color=WHITE, fontsize=8.8)
    _arrow(ax, 11.3, 5.2, 8.0, 2.1, color=GREEN)

    _title(ax, "Figure 13 — Alert Engine and Group-Based Notification Routing")
    fig.tight_layout()
    out = OUT / "fig13_alert_routing.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 14 — Sentiment results (grouped bar chart)
#
# Left panel  = Macro-F1 on the buckets where F1 is meaningful
#               (overall, and the short-to-medium bucket that carries
#                193 / 200 posts and covers all three sentiment classes).
# Right panel = Long bucket reported as raw correct-count out of 7 posts;
#               a per-class F1 would collapse to a single-class score
#               here because all 7 gold-set long posts happen to be
#               negative-class, so the honest metric is "how many did
#               the model classify correctly".
# ---------------------------------------------------------------------------

def fig14_sentiment_results():
    import numpy as np
    fig, (ax_f1, ax_ct) = plt.subplots(1, 2, figsize=(11.0, 5.2),
                                       gridspec_kw={"width_ratios": [2, 1]})

    # ── Left: Macro-F1 on the two meaningful buckets ────────────────────
    groups = ["Overall\n(n = 200)", "Short-to-medium\n(< 512 tok, n = 193)"]
    roberta_f1    = [0.6272, 0.6360]
    modernbert_f1 = [0.7642, 0.7619]

    x = np.arange(len(groups))
    bw = 0.36
    b1 = ax_f1.bar(x - bw / 2, roberta_f1,    bw, label="RoBERTa baseline",
                   color=GREY, edgecolor=NAVY)
    b2 = ax_f1.bar(x + bw / 2, modernbert_f1, bw, label="Fine-tuned ModernBERT",
                   color=BLUE, edgecolor=NAVY)
    for bars in (b1, b2):
        for r in bars:
            ax_f1.text(r.get_x() + r.get_width() / 2, r.get_height() + 0.015,
                       f"{r.get_height():.2f}", ha="center", va="bottom",
                       fontsize=9, color=NAVY, weight="bold")
    ax_f1.set_ylim(0, 1.0)
    ax_f1.set_ylabel("Macro-F1 (5-fold out-of-fold CV)", fontsize=10, color=NAVY)
    ax_f1.set_xticks(x)
    ax_f1.set_xticklabels(groups, fontsize=9.5)
    ax_f1.legend(loc="upper left", fontsize=9, frameon=True)
    ax_f1.set_title("Macro-F1 by bucket", fontsize=10.5, weight="bold", color=NAVY)
    ax_f1.spines["top"].set_visible(False)
    ax_f1.spines["right"].set_visible(False)
    ax_f1.grid(axis="y", linestyle=":", alpha=0.5)

    # ── Right: Long-post bucket as raw correct count ────────────────────
    labels = ["RoBERTa", "ModernBERT"]
    correct = [5, 7]
    xr = np.arange(len(labels))
    br = ax_ct.bar(xr, correct, 0.55,
                   color=[GREY, BLUE], edgecolor=NAVY)
    for r, c in zip(br, correct):
        ax_ct.text(r.get_x() + r.get_width() / 2, c + 0.1,
                   f"{c} / 7", ha="center", va="bottom",
                   fontsize=10, color=NAVY, weight="bold")
    ax_ct.set_ylim(0, 8.2)
    ax_ct.set_ylabel("Posts classified correctly", fontsize=10, color=NAVY)
    ax_ct.set_xticks(xr)
    ax_ct.set_xticklabels(labels, fontsize=9.5)
    ax_ct.set_title("Long posts  (≥ 512 tok,  n = 7,  all negative-class)",
                    fontsize=10.5, weight="bold", color=NAVY)
    ax_ct.spines["top"].set_visible(False)
    ax_ct.spines["right"].set_visible(False)
    ax_ct.grid(axis="y", linestyle=":", alpha=0.5)

    fig.suptitle("Figure 14 — Sentiment: RoBERTa vs Fine-Tuned ModernBERT",
                 fontsize=12, weight="bold", color=NAVY, y=1.02)
    fig.tight_layout()
    out = OUT / "fig14_sentiment_results.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    fig5_review_validate_flow()
    fig6_reply_cascade()
    fig7_learning_loop()
    fig8_lifecycle_kanban()
    fig9_ingestion_flow()
    fig10_modernbert_curriculum()
    fig11_aspect_nli()
    fig12_vision_multipass()
    fig13_alert_routing()
    fig14_sentiment_results()
    print("done")
