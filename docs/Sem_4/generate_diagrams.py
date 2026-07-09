"""Generate PNG diagrams for the BITS Pilani mid-semester report.

Produces four figures under docs/Sem_4/figures/ that are embedded by
build_mid_sem_report.py:
    fig1_architecture.png     - layered system architecture
    fig2_pipeline_flow.png    - end-to-end pipeline sequence
    fig3_trust_composition.png- trust score composition
    fig4_dashboard_map.png    - dashboard information architecture
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "figures"
OUT.mkdir(parents=True, exist_ok=True)

# Walmart-ish palette
NAVY = "#041E42"
BLUE = "#0071DC"
SKY = "#A9DDF7"
YELLOW = "#FFC220"
GREEN = "#76C043"
RED = "#E0162B"
GREY = "#5A6470"
LIGHT = "#F2F4F7"
WHITE = "#FFFFFF"


def _box(ax, x, y, w, h, text, *, face=SKY, edge=NAVY, text_color=NAVY,
         fontsize=9, weight="bold"):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=1.2, edgecolor=edge, facecolor=face,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, text,
            ha="center", va="center",
            fontsize=fontsize, color=text_color, weight=weight)


def _arrow(ax, x1, y1, x2, y2, color=NAVY, style="-|>", lw=1.4, label=None,
           label_offset=(0, 0.08)):
    arrow = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle=style, mutation_scale=12,
        linewidth=lw, color=color,
        connectionstyle="arc3,rad=0.0",
    )
    ax.add_patch(arrow)
    if label:
        mx, my = (x1 + x2) / 2 + label_offset[0], (y1 + y2) / 2 + label_offset[1]
        ax.text(mx, my, label, ha="center", va="center",
                fontsize=7.5, color=GREY, style="italic")


def _group(ax, x, y, w, h, title, color=NAVY):
    """Dashed group box around a layer."""
    rect = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.18",
        linewidth=1.0, edgecolor=color, facecolor=WHITE, linestyle="--",
    )
    ax.add_patch(rect)
    ax.text(x + 0.15, y + h - 0.22, title,
            ha="left", va="center",
            fontsize=9, color=color, weight="bold",
            bbox=dict(facecolor=WHITE, edgecolor="none", pad=2))


# ---------------------------------------------------------------------------
# Figure 1 — Layered System Architecture
# ---------------------------------------------------------------------------

def fig1_architecture():
    fig, ax = plt.subplots(figsize=(11, 7.5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 9)
    ax.axis("off")

    # Layer 1 – Sources
    _group(ax, 0.3, 7.5, 11.4, 1.2, "Data Sources", color=GREY)
    _box(ax, 0.7, 7.7, 2.4, 0.7, "Reddit PRAW\n(live)", face=SKY)
    _box(ax, 3.4, 7.7, 2.6, 0.7, "Arctic-Shift\n(backfill)", face=SKY)
    _box(ax, 6.3, 7.7, 2.6, 0.7, "Reddit Images\n(i.redd.it / imgur)", face=SKY)
    _box(ax, 9.2, 7.7, 2.3, 0.7, "Twitter / X\n(planned)", face=LIGHT, edge=GREY,
         text_color=GREY)

    # Layer 2 – Ingestion
    _group(ax, 0.3, 5.9, 11.4, 1.2, "Ingestion & Preprocessing", color=BLUE)
    _box(ax, 0.7, 6.1, 2.4, 0.7, "Subreddit\nRegistry", face=LIGHT)
    _box(ax, 3.4, 6.1, 2.6, 0.7, "Fetcher\n+ Cursor State", face=LIGHT)
    _box(ax, 6.3, 6.1, 2.6, 0.7, "Dedup &\nLanguage Filter", face=LIGHT)
    _box(ax, 9.2, 6.1, 2.3, 0.7, "Image\nPreprocess", face=LIGHT)

    # Layer 3 – Trust + LLM Analysis
    _group(ax, 0.3, 3.7, 11.4, 1.8, "Trust + Model Analysis Engine", color=NAVY)
    _box(ax, 0.7, 4.6, 2.6, 0.7, "Rule-Based\nTrust Heuristics", face=YELLOW,
         text_color=NAVY)
    _box(ax, 3.6, 4.6, 2.6, 0.7, "Sentiment\n(ModernBERT-base,\nfine-tuned)", face=YELLOW,
         text_color=NAVY, fontsize=8.5)
    _box(ax, 6.5, 4.6, 2.6, 0.7, "Aspects\n(DeBERTa-v3\nzero-shot NLI)", face=YELLOW,
         text_color=NAVY, fontsize=8.5)
    _box(ax, 9.4, 4.6, 2.1, 0.7, "Vision\n(Gemma 3 4B\nmulti-pass)", face=YELLOW,
         text_color=NAVY, fontsize=8.5)
    _box(ax, 2.1, 3.85, 3.6, 0.55,
         "Priority Score = trust × sentiment_confidence", face=WHITE, edge=NAVY,
         fontsize=8.5)
    _box(ax, 6.3, 3.85, 3.6, 0.55,
         "P1 (trust≥0.70 & conf≥0.80)   |   P2 (trust≥0.50 & conf≥0.60)",
         face=WHITE, edge=NAVY, fontsize=8.5)

    # Layer 4 – Storage + Aggregation
    _group(ax, 0.3, 2.0, 11.4, 1.4, "Storage & Aggregation", color=GREEN)
    _box(ax, 0.7, 2.5, 2.6, 0.7, "SQLite\n(local.db)", face=LIGHT)
    _box(ax, 3.6, 2.5, 2.6, 0.7, "Cosmos DB\n(prod, planned)", face=LIGHT,
         edge=GREY, text_color=GREY)
    _box(ax, 6.5, 2.5, 2.6, 0.7, "Time-Series\nAggregator", face=LIGHT)
    _box(ax, 9.4, 2.5, 2.1, 0.7, "Alert Engine\n(spike + P1)", face=LIGHT)

    # Layer 5 – Dashboard
    _group(ax, 0.3, 0.2, 11.4, 1.4, "Dashboard & Reviewer Workflow", color=RED)
    _box(ax, 0.7, 0.7, 2.0, 0.6, "Brand\nHealth", face=WHITE, edge=RED,
         text_color=NAVY, fontsize=8.5)
    _box(ax, 2.9, 0.7, 2.0, 0.6, "Aspect\nDrilldown", face=WHITE, edge=RED,
         text_color=NAVY, fontsize=8.5)
    _box(ax, 5.1, 0.7, 2.0, 0.6, "Post\nExplorer", face=WHITE, edge=RED,
         text_color=NAVY, fontsize=8.5)
    _box(ax, 7.3, 0.7, 2.0, 0.6, "Alert\nFeed", face=WHITE, edge=RED,
         text_color=NAVY, fontsize=8.5)
    _box(ax, 9.5, 0.7, 2.0, 0.6, "Review\nQueue", face=WHITE, edge=RED,
         text_color=NAVY, fontsize=8.5)

    # Vertical flow arrows between layers
    for x in (2.0, 4.7, 7.6, 10.3):
        _arrow(ax, x, 7.65, x, 7.15)   # sources → ingestion (head visible)
        _arrow(ax, x, 6.05, x, 5.55)   # ingestion → analysis
        _arrow(ax, x, 4.55, x, 3.45)   # analysis → storage  (passes through tier band)
        _arrow(ax, x, 2.45, x, 1.65)   # storage → dashboard

    ax.set_title("Figure 1 — Retail Sentiment Intelligence: Layered System Architecture",
                 fontsize=11.5, weight="bold", color=NAVY, pad=14)

    fig.tight_layout()
    out = OUT / "fig1_architecture.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 2 — Pipeline Flow (sequence)
# ---------------------------------------------------------------------------

def fig2_pipeline_flow():
    stages = [
        ("1. Discover", "Subreddit registry\n(Walmart family +\nretail-adjacent)", SKY),
        ("2. Fetch", "PRAW live +\nArctic-Shift backfill\n(cursor + dedup)", SKY),
        ("3. Preprocess", "Clean, EN-filter,\nimage download +\nresize cache", SKY),
        ("4. Trust", "Rule-based heuristics:\nmetadata + retail terms\n→ trust_score [0,1]", YELLOW),
        ("5. Analyze (Text)", "ModernBERT (sentiment)\n+ DeBERTa-v3 zero-shot\n(8-aspect tagging)", YELLOW),
        ("6. Analyze (Vision)", "Gemma 3 4B via Ollama —\nmulti-pass: structure →\ntile-OCR → merge", YELLOW),
        ("7. Tier", "P1 if trust≥0.70 & conf≥0.80\nP2 if trust≥0.50 & conf≥0.60\npriority = trust × conf", YELLOW),
        ("8. Persist", "SQLite (dev) /\nCosmos DB (prod):\nposts + analyses", GREEN),
        ("9. Aggregate", "Time-series rollups\nper aspect / segment\n/ macro-segment", GREEN),
        ("10. Alert", "Spike detection +\nP1 routing →\nReview Queue", RED),
        ("11. Surface", "React dashboard:\nBrand Health, Aspect,\nAlerts, Review", RED),
    ]

    fig, ax = plt.subplots(figsize=(8.5, 12.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, len(stages) * 1.15 + 1.0)
    ax.axis("off")

    y_top = len(stages) * 1.15 + 0.4
    for i, (title, body, color) in enumerate(stages):
        y = y_top - (i + 1) * 1.15
        # Stage number bubble
        bubble = FancyBboxPatch(
            (0.4, y + 0.15), 1.1, 0.7,
            boxstyle="round,pad=0.02,rounding_size=0.35",
            linewidth=1.2, edgecolor=NAVY, facecolor=NAVY,
        )
        ax.add_patch(bubble)
        ax.text(0.95, y + 0.5, title.split(".")[0],
                ha="center", va="center", fontsize=12,
                color=WHITE, weight="bold")
        # Title
        ax.text(1.8, y + 0.78, title.split(". ", 1)[-1],
                ha="left", va="center", fontsize=10.5,
                color=NAVY, weight="bold")
        # Body card
        _box(ax, 1.8, y + 0.08, 7.8, 0.62, body,
             face=color, edge=NAVY, fontsize=9, weight="normal")
        # Connector arrow to next
        if i < len(stages) - 1:
            _arrow(ax, 0.95, y + 0.15, 0.95, y - 0.45 + 0.15,
                   color=NAVY, lw=1.6)

    ax.set_title("Figure 2 — End-to-End Pipeline Flow (single tick)",
                 fontsize=12, weight="bold", color=NAVY, pad=10)
    fig.tight_layout()
    out = OUT / "fig2_pipeline_flow.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 3 — Trust Score Composition
# ---------------------------------------------------------------------------

def fig3_trust_composition():
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 8)
    ax.axis("off")

    # Inputs (left)
    inputs = [
        ("Account Age\n(days)", 7.0),
        ("Total Karma\n(post + comment)", 5.6),
        ("Post Length\n+ Engagement", 4.2),
        ("Promo / Bot\nPhrase Regex", 2.8),
        ("Retail-Insider\nTerms (regex)", 1.4),
    ]
    for label, y in inputs:
        _box(ax, 0.4, y, 2.6, 0.85, label, face=SKY, fontsize=9)
        _arrow(ax, 3.0, y + 0.42, 5.0, 4.3, color=GREY)

    # Heuristic scorer
    _box(ax, 5.0, 3.7, 3.0, 1.1, "Rule-Based\nTrust Heuristics\n0.4 meta + 0.3 dedup\n+ 0.3 credibility",
         face=YELLOW, fontsize=9, weight="bold")

    # Output
    _box(ax, 9.0, 3.7, 2.6, 1.1, "trust_score\n∈ [0.0, 1.0]",
         face=NAVY, edge=NAVY, text_color=WHITE, fontsize=11, weight="bold")
    _arrow(ax, 8.0, 4.25, 9.0, 4.25, color=NAVY, lw=1.8)

    # Downstream tiers
    _box(ax, 5.0, 1.5, 3.0, 0.8,
         "× sentiment_confidence  →  priority_score", face=LIGHT, edge=NAVY,
         fontsize=9)
    _arrow(ax, 10.3, 3.7, 6.5, 2.3, color=NAVY)

    _box(ax, 0.4, 0.2, 5.4, 0.95,
         "P1 = trust ≥ 0.70  AND  sentiment_confidence ≥ 0.80",
         face=RED, edge=RED, text_color=WHITE, fontsize=10, weight="bold")
    _box(ax, 6.2, 0.2, 5.4, 0.95,
         "P2 = trust ≥ 0.50  AND  sentiment_confidence ≥ 0.60",
         face=YELLOW, edge=NAVY, text_color=NAVY, fontsize=10, weight="bold")

    ax.set_title("Figure 3 — Trust Score Composition and P1/P2 Tier Rules",
                 fontsize=11.5, weight="bold", color=NAVY, pad=10)
    fig.tight_layout()
    out = OUT / "fig3_trust_composition.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# Figure 4 — Dashboard Information Architecture
# ---------------------------------------------------------------------------

def fig4_dashboard_map():
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 8)
    ax.axis("off")

    # API band
    _box(ax, 0.4, 6.6, 11.2, 0.9,
         "FastAPI  /api  (aggregates · priority_negatives · alerts · pipeline status · review)",
         face=NAVY, edge=NAVY, text_color=WHITE, fontsize=10, weight="bold")

    # Pages row
    pages = [
        ("Brand Health", "KPIs · trend\nP1/P2 tiles\nPriority panel"),
        ("Aspect Drilldown", "Per-aspect\nsentiment trend\n+ sample posts"),
        ("Post Explorer", "Filter by\nsegment / aspect\n/ trust tier"),
        ("Alert Feed", "Spike alerts +\nP1 routing\n(live socket)"),
        ("Review Queue", "Analyst label\noverride +\nfeedback loop"),
        ("Pipeline", "Last run, stage,\ncounters,\nlog tail"),
    ]
    w = 1.75
    for i, (title, body) in enumerate(pages):
        x = 0.4 + i * (w + 0.1)
        _box(ax, x, 4.5, w, 1.6, f"{title}\n\n{body}", face=SKY, fontsize=8.5)
        _arrow(ax, x + w / 2, 6.55, x + w / 2, 6.15, color=NAVY)

    # Cross-cutting filters
    _box(ax, 0.4, 3.0, 11.2, 0.8,
         "Global filters: time range · segment (price/availability/quality/staff/digital/delivery) · macro-segment · trust tier",
         face=LIGHT, edge=NAVY, fontsize=9)
    for i in range(len(pages)):
        x = 0.4 + i * (w + 0.1) + w / 2
        _arrow(ax, x, 4.45, x, 3.85, color=GREY)

    # Storage
    _box(ax, 1.0, 1.2, 4.6, 1.2, "SQLite (dev) /\nCosmos DB (prod)\nposts · analyses · aggregates",
         face=GREEN, edge=NAVY, fontsize=9.5, weight="bold")
    _box(ax, 6.4, 1.2, 4.6, 1.2, "Alert engine\nfeedback store\npipeline state",
         face=GREEN, edge=NAVY, fontsize=9.5, weight="bold")
    _arrow(ax, 3.3, 2.4, 3.3, 3.0, color=NAVY)
    _arrow(ax, 8.7, 2.4, 8.7, 3.0, color=NAVY)

    # Reviewer feedback loop
    _arrow(ax, 11.2, 5.3, 11.7, 5.3, color=RED, lw=1.6)
    _arrow(ax, 11.7, 5.3, 11.7, 1.8, color=RED, lw=1.6)
    _arrow(ax, 11.7, 1.8, 11.0, 1.8, color=RED, lw=1.6)
    ax.text(11.85, 3.5, "reviewer\nfeedback", color=RED, fontsize=8.5,
            ha="left", va="center", weight="bold")

    ax.set_title("Figure 4 — Dashboard Information Architecture & Feedback Loop",
                 fontsize=11.5, weight="bold", color=NAVY, pad=10)
    fig.tight_layout()
    out = OUT / "fig4_dashboard_map.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    fig1_architecture()
    fig2_pipeline_flow()
    fig3_trust_composition()
    fig4_dashboard_map()
    print("done")
