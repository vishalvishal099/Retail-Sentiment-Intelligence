"""
Generate the FINAL post-midsem dissertation presentation.

Focus: only post-midsem work — no mid-sem recap. Content pulled from
the final dissertation report (docs/Sem_4/final/latex/) and the UI
screenshots captured for the report (docs/Sem_4/final/figures/ui/).

Output: docs/Sem_4/FINAL_PRESENTATION_VishalSingh_2020AA05641.pptx
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

HERE = Path(__file__).parent
FIG_DIR = HERE / "figures"
UI_DIR = HERE / "final" / "figures" / "ui"
OUT = HERE / "FINAL_PRESENTATION_VishalSingh_2020AA05641.pptx"

# Palette — matches the mid-sem deck for continuity.
WALMART_BLUE = RGBColor(0x00, 0x71, 0xDC)
DARK_BLUE    = RGBColor(0x04, 0x1E, 0x42)
LIGHT_BLUE   = RGBColor(0xE8, 0xF4, 0xFD)
YELLOW       = RGBColor(0xFF, 0xC2, 0x20)
WHITE        = RGBColor(0xFF, 0xFF, 0xFF)
DARK_GRAY    = RGBColor(0x33, 0x33, 0x33)
MED_GRAY     = RGBColor(0x66, 0x66, 0x66)
LIGHT_GRAY   = RGBColor(0xF5, 0xF5, 0xF5)
GREEN        = RGBColor(0x10, 0xB9, 0x81)
RED          = RGBColor(0xEF, 0x44, 0x44)
PURPLE       = RGBColor(0x7C, 0x3A, 0xED)
AMBER        = RGBColor(0xD9, 0x77, 0x06)
GREEN_TINT   = RGBColor(0xDC, 0xFC, 0xE7)
AMBER_TINT   = RGBColor(0xFE, 0xF3, 0xC7)
RED_TINT     = RGBColor(0xFE, 0xE2, 0xE2)
PURPLE_TINT  = RGBColor(0xED, 0xE9, 0xFE)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


# ─── helpers ─────────────────────────────────────────────────────────────────
def _set_bg(slide, color):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _tx(slide, left, top, width, height, text, *,
        size=Pt(14), bold=False, color=DARK_GRAY,
        align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    lines = text.split("\n") if isinstance(text, str) else text
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.alignment = align
        for r in p.runs:
            r.font.size = size
            r.font.bold = bold
            r.font.color.rgb = color
    return box


def _rect(slide, left, top, width, height, fill, line=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
    shp.shadow.inherit = False
    return shp


def _header_bar(slide, title, subtitle=None):
    _rect(slide, Inches(0), Inches(0), SLIDE_W, Inches(0.85), DARK_BLUE)
    _tx(slide, Inches(0.4), Inches(0.12), Inches(12.5), Inches(0.5),
        title, size=Pt(26), bold=True, color=WHITE)
    if subtitle:
        _tx(slide, Inches(0.4), Inches(0.5), Inches(12.5), Inches(0.35),
            subtitle, size=Pt(12), color=LIGHT_BLUE)
    _rect(slide, Inches(0), Inches(0.85), SLIDE_W, Inches(0.05), YELLOW)


def _footer(slide, page_no, total):
    _tx(slide, Inches(0.4), Inches(7.15), Inches(9), Inches(0.3),
        "Retail Sentiment Intelligence  ·  BITS ZG628T Dissertation  ·  Vishal Singh  ·  Post Mid-Semester Presentation",
        size=Pt(9), color=MED_GRAY)
    _tx(slide, Inches(12.0), Inches(7.15), Inches(1.2), Inches(0.3),
        f"{page_no} / {total}", size=Pt(9), color=MED_GRAY, align=PP_ALIGN.RIGHT)


def _bullets(slide, left, top, width, height, items, *,
             size=Pt(14), color=DARK_GRAY, bold=False):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {item}"
        p.space_after = Pt(4)
        for r in p.runs:
            r.font.size = size
            r.font.color.rgb = color
            r.font.bold = bold
    return box


def _table(slide, left, top, width, height, data, *,
           header_fill=DARK_BLUE, header_color=WHITE,
           body_font=Pt(11), first_col_bold=False,
           highlight_rows=None):
    highlight_rows = highlight_rows or {}
    rows = len(data)
    cols = len(data[0])
    tbl_shape = slide.shapes.add_table(rows, cols, left, top, width, height)
    tbl = tbl_shape.table
    for r_idx, row in enumerate(data):
        for c_idx, val in enumerate(row):
            cell = tbl.cell(r_idx, c_idx)
            cell.text = str(val)
            if r_idx == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = header_fill
            elif r_idx in highlight_rows:
                cell.fill.solid()
                cell.fill.fore_color.rgb = highlight_rows[r_idx]
            else:
                cell.fill.solid()
                cell.fill.fore_color.rgb = WHITE if r_idx % 2 else LIGHT_GRAY
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    run.font.size = body_font
                    if r_idx == 0:
                        run.font.color.rgb = header_color
                        run.font.bold = True
                    else:
                        run.font.color.rgb = DARK_GRAY
                        if first_col_bold and c_idx == 0:
                            run.font.bold = True
    return tbl


def _kpi_tile(slide, left, top, width, height, label, value, *,
              tint=LIGHT_BLUE, value_color=WALMART_BLUE, value_size=Pt(28)):
    _rect(slide, left, top, width, height, tint, line=WALMART_BLUE)
    _tx(slide, left, top + Inches(0.15), width, Inches(0.35),
        label, size=Pt(11), bold=True, color=MED_GRAY, align=PP_ALIGN.CENTER)
    _tx(slide, left, top + Inches(0.55), width, height - Inches(0.7),
        value, size=value_size, bold=True, color=value_color,
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def _arrow(slide, x, y, w=Inches(0.35), h=Inches(0.35), color=YELLOW):
    a = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x, y, w, h)
    a.fill.solid()
    a.fill.fore_color.rgb = color
    a.line.fill.background()


def _stage_card(slide, x, y, w, h, label, title, body, color):
    _rect(slide, x, y, w, h, LIGHT_GRAY, line=color)
    _rect(slide, x, y, w, Inches(0.45), color)
    _tx(slide, x, y + Inches(0.05), w, Inches(0.35),
        label, size=Pt(11), bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    _tx(slide, x, y + Inches(0.55), w, Inches(0.4),
        title, size=Pt(13), bold=True, color=DARK_BLUE, align=PP_ALIGN.CENTER)
    _tx(slide, x, y + Inches(1.0), w, h - Inches(1.05),
        body, size=Pt(11), color=DARK_GRAY, align=PP_ALIGN.CENTER)


def _image(slide, path: Path, left, top, width=None, height=None):
    if not path.exists():
        _rect(slide, left, top, width or Inches(6), height or Inches(3),
              LIGHT_GRAY, line=MED_GRAY)
        _tx(slide, left, top, width or Inches(6), height or Inches(3),
            f"[missing image: {path.name}]", size=Pt(11), color=MED_GRAY,
            align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        return
    kw = {}
    if width is not None:
        kw["width"] = width
    if height is not None:
        kw["height"] = height
    slide.shapes.add_picture(str(path), left, top, **kw)


# ─── deck ────────────────────────────────────────────────────────────────────
def build():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    TOTAL = 23
    page = [0]

    def new():
        page[0] += 1
        return prs.slides.add_slide(prs.slide_layouts[6])

    # 1 · Title ──────────────────────────────────────────────────────────────
    s = new()
    _set_bg(s, DARK_BLUE)
    _rect(s, Inches(0), Inches(2.5), Inches(0.4), Inches(2.7), YELLOW)
    _tx(s, Inches(0.9), Inches(1.2), Inches(11.5), Inches(0.9),
        "Retail Sentiment Intelligence", size=Pt(44), bold=True, color=WHITE)
    _tx(s, Inches(0.9), Inches(2.15), Inches(11.5), Inches(0.6),
        "Trust-Aware Sentiment Analysis of Retail Feedback using LLMs",
        size=Pt(20), color=YELLOW)
    _tx(s, Inches(0.9), Inches(2.95), Inches(11.5), Inches(0.4),
        "BITS ZG628T  ·  Dissertation  ·  Post Mid-Semester Presentation",
        size=Pt(14), bold=True, color=WHITE)
    _tx(s, Inches(0.9), Inches(3.9), Inches(11.5), Inches(0.4),
        "Vishal Singh   ·   ID No. 2020AA05641",
        size=Pt(18), bold=True, color=WHITE)
    _tx(s, Inches(0.9), Inches(4.35), Inches(11.5), Inches(0.4),
        "M.Tech (Artificial Intelligence & Machine Learning)",
        size=Pt(14), color=LIGHT_BLUE)
    _tx(s, Inches(0.9), Inches(4.7), Inches(11.5), Inches(0.4),
        "Birla Institute of Technology & Science, Pilani  (WILP)",
        size=Pt(14), color=LIGHT_BLUE)
    _tx(s, Inches(0.9), Inches(5.5), Inches(11.5), Inches(0.4),
        "Dissertation work at  Walmart Global Tech, Bengaluru",
        size=Pt(12), color=WHITE)
    _tx(s, Inches(0.9), Inches(5.85), Inches(11.5), Inches(0.4),
        "Supervisor:  Mr. Varunendra Pratap Singh  —  Principal Software Engineer, Walmart Global Tech",
        size=Pt(12), color=WHITE)
    _tx(s, Inches(0.9), Inches(6.2), Inches(11.5), Inches(0.4),
        "Additional Examiner:  Ms. Pradnya Kashikar  —  BITS Pilani",
        size=Pt(12), color=WHITE)
    _tx(s, Inches(0.9), Inches(6.85), Inches(11.5), Inches(0.4),
        "August 2026", size=Pt(11), color=MED_GRAY)

    # 2 · Agenda ─────────────────────────────────────────────────────────────
    s = new()
    _header_bar(s, "Agenda", "Focus of today — post mid-semester work only")
    items = [
        ("1", "Since Mid-Sem — What's New",         "Post-midsem workstream map"),
        ("2", "Review & Validate  (HITL)",           "Human-in-the-loop correction workflow"),
        ("3", "Smart Reply Composer",                "Dual-draft:  rule-based  +  LLM"),
        ("4", "Learning Loop",                       "Corrections + posted replies → retraining"),
        ("5", "Post Explorer",                       "Multi-facet search across analysed posts"),
        ("6", "Post Lifecycle  (Kanban)",            "Triage → Acknowledged → In-Progress → Resolved"),
        ("7", "Insights & Competitor Analysis",      "Strategic weekly summaries + cross-brand"),
        ("8", "Notification Centre",                 "In-app + email + Slack, group-routed"),
        ("9", "ModernBERT — Final Results",          "Macro-F1  0.6272 → 0.7642  (+13.7 pts)"),
        ("10", "Vision — Multi-Pass Payoff",         "Hallucination  50% → 0%,  extraction 25% → 75%"),
        ("11", "Trust-Score Evaluation",             "15% flagged; 12 of 15 confirmed by annotator"),
        ("12", "Storage — SQLite → Cosmos DB",       "Lift-and-shift ready"),
        ("13", "Live Demo",                          "Dashboard walkthrough (screenshots)"),
        ("14", "Conclusions & Future Work",          "RQ1–RQ4 outcomes + roadmap"),
    ]
    x0, y0 = Inches(0.5), Inches(1.15)
    col_w, row_h = Inches(6.15), Inches(0.4)
    for i, (n, title, sub) in enumerate(items):
        col = i // 7
        row = i % 7
        lx = x0 + col * (col_w + Inches(0.15))
        ly = y0 + row * (row_h + Inches(0.11))
        _rect(s, lx, ly, col_w, row_h, LIGHT_BLUE, line=WALMART_BLUE)
        _tx(s, lx + Inches(0.1), ly + Inches(0.05), Inches(0.5), Inches(0.3),
            n, size=Pt(12), bold=True, color=WALMART_BLUE)
        _tx(s, lx + Inches(0.6), ly + Inches(0.03), col_w - Inches(0.7), Inches(0.2),
            title, size=Pt(11), bold=True, color=DARK_BLUE)
        _tx(s, lx + Inches(0.6), ly + Inches(0.22), col_w - Inches(0.7), Inches(0.2),
            sub, size=Pt(9), color=MED_GRAY)
    _footer(s, page[0], TOTAL)

    # 3 · What's new since mid-sem ──────────────────────────────────────────
    s = new()
    _header_bar(s, "Since Mid-Sem — What's New",
                "Mid-sem shipped the pipeline; post-midsem made it usable for analysts")
    _tx(s, Inches(0.5), Inches(1.05), Inches(6.0), Inches(0.35),
        "Delivered at mid-sem", size=Pt(13), bold=True, color=AMBER)
    _bullets(s, Inches(0.5), Inches(1.4), Inches(6.0), Inches(3.8), [
        "6-layer offline-first pipeline (25 subreddits)",
        "ModernBERT fine-tuning up to Stage 2  (F1 0.7285)",
        "Multi-pass vision with 0% hallucination on pilot",
        "Trust-score design + weighted formula",
        "Brand-Health + Alert Feed dashboard pages",
        "Group-routed email / Slack notifications",
    ], size=Pt(12))
    _tx(s, Inches(6.85), Inches(1.05), Inches(6.0), Inches(0.35),
        "Added post-midsem  (this deck)", size=Pt(13), bold=True, color=GREEN)
    _bullets(s, Inches(6.85), Inches(1.4), Inches(6.0), Inches(3.8), [
        "Review & Validate  —  human-in-the-loop UI + backend",
        "Smart Reply Composer  —  dual-draft (rule + FLAN-T5)",
        "Learning-loop store  —  corrections & posted replies",
        "Post Explorer  —  multi-facet search",
        "Post Lifecycle  —  Kanban with 2-step Resolve",
        "Insights & Competitor Analysis page",
        "In-app Notification Centre mirroring the digest",
        "ModernBERT Stage 3 (final)  —  F1 0.7285 → 0.7642",
        "Trust-score end-to-end evaluation (n = 200)",
        "SQLite schema mirroring Cosmos DB partitioning",
    ], size=Pt(12))
    _rect(s, Inches(0.5), Inches(5.55), Inches(12.3), Inches(1.35),
          LIGHT_BLUE, line=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(5.7), Inches(12.0), Inches(0.4),
        "Framing", size=Pt(13), bold=True, color=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(6.1), Inches(12.0), Inches(0.8),
        "Mid-sem answered can the pipeline produce trust-weighted sentiment?    "
        "Post-midsem answers can an analyst act on it, correct it, and feed the corrections back into the model?",
        size=Pt(12), color=DARK_GRAY)
    _footer(s, page[0], TOTAL)

    # 4 · Review & Validate ─────────────────────────────────────────────────
    s = new()
    _header_bar(s, "Review & Validate  —  Human-in-the-Loop",
                "Every prediction can be corrected; every correction is logged")
    _bullets(s, Inches(0.5), Inches(1.05), Inches(6.0), Inches(2.8), [
        "Queue sorted by  priority (P1 first)  ·  trust × confidence",
        "Analyst can override sentiment and aspect tags in one click",
        "Corrections written to  feedback table  with analyst + timestamp",
        "Generate Drafts  →  two reply options  (rule + LLM)",
        "Analyst picks A or B, edits, and posts to Reddit",
        "Posted replies also captured  →  future few-shot pool",
    ], size=Pt(12))
    _image(s, UI_DIR / "review_validate.png",
           Inches(6.75), Inches(1.05), width=Inches(6.2))
    _rect(s, Inches(0.5), Inches(5.7), Inches(6.0), Inches(1.2),
          GREEN_TINT, line=GREEN)
    _tx(s, Inches(0.7), Inches(5.85), Inches(5.6), Inches(0.35),
        "Why it matters", size=Pt(12), bold=True, color=GREEN)
    _tx(s, Inches(0.7), Inches(6.2), Inches(5.6), Inches(0.7),
        "Turns a passive dashboard into a training signal — corrections harvested here "
        "drive the ModernBERT re-training loop and reply few-shot pool.",
        size=Pt(11), color=DARK_GRAY)
    _footer(s, page[0], TOTAL)

    # 5 · Smart Reply Composer ──────────────────────────────────────────────
    s = new()
    _header_bar(s, "Smart Reply Composer  —  Dual-Draft",
                "Deterministic composer + LLM composer, analyst chooses")
    _rect(s, Inches(0.5), Inches(1.05), Inches(6.05), Inches(3.4),
          LIGHT_BLUE, line=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(1.2), Inches(5.7), Inches(0.4),
        "Draft A  ·  Rule / Smart Composer", size=Pt(14), bold=True, color=WALMART_BLUE)
    _bullets(s, Inches(0.7), Inches(1.65), Inches(5.7), Inches(2.7), [
        "Keyword & aspect extraction from post",
        "Curated phrase pool  →  templated apology + resolution",
        "Deterministic — same input, same output",
        "Always available, zero latency, zero cost",
        "Strong default tone for common complaints",
    ], size=Pt(12))
    _rect(s, Inches(6.75), Inches(1.05), Inches(6.05), Inches(3.4),
          PURPLE_TINT, line=PURPLE)
    _tx(s, Inches(6.95), Inches(1.2), Inches(5.7), Inches(0.4),
        "Draft B  ·  FLAN-T5-base", size=Pt(14), bold=True, color=PURPLE)
    _bullets(s, Inches(6.95), Inches(1.65), Inches(5.7), Inches(2.7), [
        "Multi-temperature sampling  (T = 0.7, 0.9, 1.1)",
        "Best-of-N scorer over drafts",
        "Higher variety, less templated tone",
        "Learns from posted replies over time",
        "Fallback to Draft A if model unavailable",
    ], size=Pt(12))
    _rect(s, Inches(0.5), Inches(4.6), Inches(12.3), Inches(1.9),
          LIGHT_GRAY, line=DARK_BLUE)
    _tx(s, Inches(0.7), Inches(4.75), Inches(12.0), Inches(0.4),
        "Composer pipeline", size=Pt(13), bold=True, color=DARK_BLUE)
    steps = ["post + aspects", "Draft A + Draft B", "analyst picks + edits",
             "posted reply", "feedback store"]
    x = Inches(0.7)
    for i, txt in enumerate(steps):
        _rect(s, x, Inches(5.25), Inches(2.15), Inches(0.7),
              WHITE, line=WALMART_BLUE)
        _tx(s, x, Inches(5.3), Inches(2.15), Inches(0.6),
            txt, size=Pt(11), bold=True, color=DARK_BLUE,
            align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        if i < len(steps) - 1:
            _arrow(s, x + Inches(2.16), Inches(5.42), Inches(0.18), Inches(0.36))
        x = x + Inches(2.35)
    _footer(s, page[0], TOTAL)

    # 6 · Learning Loop ─────────────────────────────────────────────────────
    s = new()
    _header_bar(s, "Learning Loop  —  Feedback → Retraining",
                "HITL corrections + posted replies become the next training set")
    stages = [
        ("STEP 1", "CAPTURE",  "analyst overrides sentiment\nand aspect tags", AMBER),
        ("STEP 2", "STORE",    "feedback(post_id,\nold, new, analyst_id, ts)", WALMART_BLUE),
        ("STEP 3", "CURATE",   "weekly export of\ndisagreements\n(model ≠ analyst)", PURPLE),
        ("STEP 4", "RETRAIN",  "add to Stage-3\nfine-tune set,\nrerun 5-fold CV", GREEN),
    ]
    x = Inches(0.4)
    y = Inches(1.35)
    w = Inches(3.0)
    h = Inches(2.4)
    for i, (label, title, body, col) in enumerate(stages):
        _stage_card(s, x, y, w, h, label, title, body, col)
        if i < 3:
            _arrow(s, x + w + Inches(0.005),
                   y + Inches(0.9), Inches(0.18), Inches(0.4))
        x = x + w + Inches(0.15)
    _tx(s, Inches(0.5), Inches(4.1), Inches(12.3), Inches(0.4),
        "Two signals feed the loop", size=Pt(13), bold=True, color=DARK_BLUE)
    _table(s, Inches(0.5), Inches(4.55), Inches(12.3), Inches(2.05), [
        ["Signal",                 "Table",                          "Downstream use"],
        ["Label corrections",      "feedback (sentiment / aspect)",  "ModernBERT Stage-3 augmentation"],
        ["Posted replies",         "feedback (reply_text)",          "FLAN-T5 few-shot pool"],
        ["Trust-tier overrides",   "feedback (trust_override)",      "Trust-score threshold calibration"],
    ], first_col_bold=True)
    _footer(s, page[0], TOTAL)

    # 7 · Post Explorer ─────────────────────────────────────────────────────
    s = new()
    _header_bar(s, "Post Explorer  —  Multi-Facet Search",
                "Find the exact 20 posts an analyst needs to look at today")
    _tx(s, Inches(0.5), Inches(1.05), Inches(6.0), Inches(0.35),
        "Facets", size=Pt(13), bold=True, color=DARK_BLUE)
    _bullets(s, Inches(0.5), Inches(1.4), Inches(6.0), Inches(3.8), [
        "Sentiment  ·  neg / neu / pos",
        "Confidence slider  (0.50 – 1.00)",
        "Trust-score slider  (0.00 – 1.00)",
        "Subreddit  —  multi-select from 25 tracked",
        "Aspect  —  8-item retail taxonomy",
        "Date range  —  today / week / month / custom",
        "Full-text search  —  title + body",
    ], size=Pt(12))
    _image(s, UI_DIR / "post_explorer.png",
           Inches(6.75), Inches(1.05), width=Inches(6.2))
    _rect(s, Inches(0.5), Inches(5.55), Inches(12.3), Inches(1.35),
          LIGHT_GRAY, line=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(5.7), Inches(12.0), Inches(0.35),
        "Per-post card", size=Pt(12), bold=True, color=DARK_BLUE)
    _tx(s, Inches(0.7), Inches(6.05), Inches(12.0), Inches(0.8),
        "Title + body excerpt · sentiment badge with confidence % · trust tier (H / M / L) · aspect chips · "
        "subreddit + timestamp · actions:  Review  ·  Add to Lifecycle  ·  View Details.",
        size=Pt(11), color=DARK_GRAY)
    _footer(s, page[0], TOTAL)

    # 8 · Post Lifecycle Kanban ─────────────────────────────────────────────
    s = new()
    _header_bar(s, "Post Lifecycle  —  Kanban Workflow",
                "Track a complaint from Triage to Resolved with SLA visibility")
    states = [
        ("TRIAGED",       "New P1 / P2\nposts land here",       AMBER),
        ("ACKNOWLEDGED",  "Assigned\nto analyst",               WALMART_BLUE),
        ("IN PROGRESS",   "Reply being\ndrafted / posted",      PURPLE),
        ("RESOLVED",      "Reply posted or\nno-action closed",  GREEN),
    ]
    x = Inches(0.5)
    y = Inches(1.35)
    w = Inches(3.0)
    h = Inches(1.9)
    for i, (t, body, col) in enumerate(states):
        _rect(s, x, y, w, h, LIGHT_GRAY, line=col)
        _rect(s, x, y, w, Inches(0.45), col)
        _tx(s, x, y + Inches(0.05), w, Inches(0.35),
            t, size=Pt(13), bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        _tx(s, x, y + Inches(0.55), w, h - Inches(0.6),
            body, size=Pt(12), color=DARK_GRAY, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE)
        if i < 3:
            _arrow(s, x + w + Inches(0.005),
                   y + Inches(0.75), Inches(0.15), Inches(0.4))
        x = x + w + Inches(0.15)
    _image(s, UI_DIR / "lifecycle_kanban.png",
           Inches(0.5), Inches(3.55), width=Inches(7.5))
    _rect(s, Inches(8.3), Inches(3.55), Inches(4.5), Inches(3.15),
          LIGHT_BLUE, line=WALMART_BLUE)
    _tx(s, Inches(8.5), Inches(3.7), Inches(4.2), Inches(0.35),
        "Resolve modal  —  2-step flow", size=Pt(12), bold=True, color=WALMART_BLUE)
    _bullets(s, Inches(8.5), Inches(4.05), Inches(4.2), Inches(2.6), [
        "Step 1 · save action note + optional LLM reply",
        "(a) Save & open Reddit  →  reply copied to clipboard",
        "(b) OR  Resolve (no-reply)  →  close without posting",
        "Step 2 · paste on Reddit → Mark Resolved",
        "All transitions timestamped  →  SLA analytics",
    ], size=Pt(11))
    _footer(s, page[0], TOTAL)

    # 9 · Insights & Competitor ─────────────────────────────────────────────
    s = new()
    _header_bar(s, "Insights & Competitor Analysis",
                "Strategic view — issue rankings, cross-brand pulse, LLM summaries")
    features = [
        ("Priority-Negatives",     "Top issues ranked by\nvolume × severity × recency\nby aspect",       WALMART_BLUE),
        ("Competitor Pulse",       "Walmart vs Costco,\nTarget, Amazon on shared aspects",              PURPLE),
        ("Weekly LLM Summaries",   "Natural-language weekly\ndigest + action items\n+ emerging topics", GREEN),
        ("Aspect Drilldown",       "8-aspect taxonomy\nper-aspect sentiment trend\n+ representative posts", AMBER),
    ]
    positions = [(0.5, 1.05), (6.9, 1.05), (0.5, 3.55), (6.9, 3.55)]
    for (t, body, col), (lx, ly) in zip(features, positions):
        _rect(s, Inches(lx), Inches(ly), Inches(6.0), Inches(2.35),
              LIGHT_GRAY, line=col)
        _rect(s, Inches(lx), Inches(ly), Inches(6.0), Inches(0.45), col)
        _tx(s, Inches(lx), Inches(ly + 0.06), Inches(6.0), Inches(0.35),
            t, size=Pt(13), bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        _tx(s, Inches(lx + 0.2), Inches(ly + 0.55), Inches(5.6), Inches(1.7),
            body, size=Pt(12), color=DARK_GRAY, align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE)
    _tx(s, Inches(0.5), Inches(6.15), Inches(12.3), Inches(0.75),
        "Screenshot on Slide 17 (Live Demo grid) — insights_competitor page.",
        size=Pt(10), color=MED_GRAY, align=PP_ALIGN.CENTER)
    _footer(s, page[0], TOTAL)

    # 10 · Notification Centre ──────────────────────────────────────────────
    s = new()
    _header_bar(s, "Notification Centre",
                "In-app mirror of the group-routed email / Slack digest")
    _bullets(s, Inches(0.5), Inches(1.05), Inches(6.0), Inches(3.5), [
        "Every P1 / P2 email or Slack alert is mirrored in the app",
        "Notifications grouped by  subreddit ↔ business team",
        "Read / unread state persisted per analyst",
        "Deep-links open the post directly in Review & Validate",
        "Powered by the same  alerts  rows that drive email/Slack",
    ], size=Pt(12))
    _image(s, UI_DIR / "notifications.png",
           Inches(6.75), Inches(1.05), width=Inches(6.2))
    _rect(s, Inches(0.5), Inches(5.05), Inches(6.0), Inches(1.8),
          LIGHT_BLUE, line=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(5.2), Inches(5.6), Inches(0.35),
        "Priority thresholds", size=Pt(12), bold=True, color=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(5.55), Inches(5.6), Inches(1.25),
        "P1 — trust ≥ 0.70  and  confidence ≥ 0.80\nP2 — trust ≥ 0.50  and  confidence ≥ 0.60\nSource: config/models.yaml + dispatcher.py",
        size=Pt(11), color=DARK_GRAY)
    _footer(s, page[0], TOTAL)

    # 11 · ModernBERT Final Results ─────────────────────────────────────────
    s = new()
    _header_bar(s, "ModernBERT  —  Final Training Results",
                "3-stage curriculum,  5-fold out-of-fold CV,  n = 200")
    _kpi_tile(s, Inches(0.5), Inches(1.05), Inches(4.0), Inches(1.75),
              "Overall Macro-F1", "0.6272 → 0.7642",
              value_color=GREEN, tint=GREEN_TINT, value_size=Pt(24))
    _kpi_tile(s, Inches(4.65), Inches(1.05), Inches(4.0), Inches(1.75),
              "Long-post F1  (> 256 tok)", "0.28 → 1.00",
              value_color=GREEN, tint=GREEN_TINT, value_size=Pt(24))
    _kpi_tile(s, Inches(8.8), Inches(1.05), Inches(4.0), Inches(1.75),
              "Uplift over baseline", "+13.7 pts",
              value_color=WALMART_BLUE, value_size=Pt(28))
    _tx(s, Inches(0.5), Inches(3.0), Inches(12.3), Inches(0.35),
        "3-stage curriculum", size=Pt(13), bold=True, color=DARK_BLUE)
    _table(s, Inches(0.5), Inches(3.4), Inches(12.3), Inches(1.85), [
        ["Stage", "Data",                                          "Macro-F1", "Δ vs baseline"],
        ["Baseline (Twitter-RoBERTa)",  "off-the-shelf",           "0.6272",   "—"],
        ["Stage 1",   "TweetEval sentiment (~45 k tweets)",        "0.6810",   "+5.4"],
        ["Stage 2",   "GoEmotions-3class Reddit (~54 k, pseudo)",  "0.7285",   "+10.1"],
        ["Stage 3  (final)", "Walmart-200 hand-labelled",          "0.7642",   "+13.7"],
    ], first_col_bold=True, highlight_rows={4: GREEN_TINT})
    _tx(s, Inches(0.5), Inches(5.4), Inches(12.3), Inches(0.35),
        "Per-length-bucket F1", size=Pt(13), bold=True, color=DARK_BLUE)
    _table(s, Inches(0.5), Inches(5.8), Inches(12.3), Inches(1.1), [
        ["Bucket",                    "Baseline", "ModernBERT",  "Δ"],
        ["Short  (< 64 tokens)",       "0.7500",  "0.7800",       "+3.0"],
        ["Medium  (64 – 256 tokens)",  "0.6500",  "0.7400",       "+9.0"],
        ["Long  (> 256 tokens)",       "0.2778",  "1.0000",       "+72.2"],
    ], first_col_bold=True, highlight_rows={3: GREEN_TINT})
    _footer(s, page[0], TOTAL)

    # 12 · Vision Multi-Pass Payoff ─────────────────────────────────────────
    s = new()
    _header_bar(s, "Vision Pipeline  —  Multi-Pass Payoff",
                "Same model (Gemma 3 4B), same hardware, smarter calling strategy")
    passes = [
        ("PASS 1", "STRUCTURE",  "What TYPE of image?\nscreenshot / photo /\nreceipt / app / meme", PURPLE),
        ("PASS 2", "TILE",       "Split into 2–4 crops\n→ 2–4× effective\nresolution, no resize",   WALMART_BLUE),
        ("PASS 3", "EXTRACT",    "Per tile: read ALL\ntext verbatim\n(quotes, prices, UI)",         AMBER),
        ("PASS 4", "MERGE",      "Text-only LLM call\n— image REMOVED —\ncannot invent visuals",     GREEN),
    ]
    x = Inches(0.4)
    y = Inches(1.15)
    w = Inches(3.0)
    h = Inches(2.15)
    for i, (label, title, body, col) in enumerate(passes):
        _stage_card(s, x, y, w, h, label, title, body, col)
        if i < 3:
            _arrow(s, x + w + Inches(0.005),
                   y + Inches(0.8), Inches(0.18), Inches(0.4))
        x = x + w + Inches(0.15)
    _tx(s, Inches(0.5), Inches(3.65), Inches(12.3), Inches(0.35),
        "Evaluation on 32 retail screenshots", size=Pt(13), bold=True, color=DARK_BLUE)
    _table(s, Inches(0.5), Inches(4.05), Inches(12.3), Inches(2.6), [
        ["Metric",                    "Single-pass",  "Multi-pass",  "Change"],
        ["Hallucination rate",         "50 %",         "0 %",         "eliminated"],
        ["Text-extraction success",    "25 %",         "75 %",        "3× better"],
        ["Retail-signal recall",       "40 %",         "81 %",        "2× better"],
        ["Fabricated claims",          "many",         "0",           "eliminated"],
        ["Latency / image (warm)",     "~5 s",         "~15 s",       "3× (accepted)"],
    ], first_col_bold=True,
       highlight_rows={1: GREEN_TINT, 2: GREEN_TINT, 3: GREEN_TINT})
    _footer(s, page[0], TOTAL)

    # 13 · Trust-Score Evaluation ───────────────────────────────────────────
    s = new()
    _header_bar(s, "Trust-Score  —  End-to-End Evaluation",
                "On the 200-post gold set, does the trust filter catch bad posts?")
    _kpi_tile(s, Inches(0.5), Inches(1.05), Inches(4.0), Inches(1.9),
              "Low-trust share  (T < 0.4)", "15 %",
              value_color=AMBER, tint=AMBER_TINT, value_size=Pt(38))
    _kpi_tile(s, Inches(4.65), Inches(1.05), Inches(4.0), Inches(1.9),
              "Human-agreed  (annotator cross-check)", "12 / 15",
              value_color=GREEN, tint=GREEN_TINT, value_size=Pt(38))
    _kpi_tile(s, Inches(8.8), Inches(1.05), Inches(4.0), Inches(1.9),
              "Agreement rate", "80 %",
              value_color=WALMART_BLUE, value_size=Pt(38))
    _tx(s, Inches(0.5), Inches(3.15), Inches(12.3), Inches(0.35),
        "Weighted formula  (decomposition shown inline in dashboard)",
        size=Pt(13), bold=True, color=DARK_BLUE)
    _rect(s, Inches(0.5), Inches(3.55), Inches(12.3), Inches(0.85),
          LIGHT_BLUE, line=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(3.7), Inches(12.0), Inches(0.55),
        "trust_score  =  0.4 × metadata  +  0.3 × dedup  +  0.3 × llm_credibility",
        size=Pt(18), bold=True, color=DARK_BLUE, align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE)
    _rect(s, Inches(0.5), Inches(4.65), Inches(12.3), Inches(2.15),
          GREEN_TINT, line=GREEN)
    _tx(s, Inches(0.7), Inches(4.8), Inches(12.0), Inches(0.35),
        "Design principle — flag, don't drop", size=Pt(13), bold=True, color=GREEN)
    _tx(s, Inches(0.7), Inches(5.15), Inches(12.0), Inches(1.6),
        "Low-trust posts are surfaced with an explanatory chip (\"promotional / duplicate / thin-metadata\") and can be "
        "overridden by an analyst in one click — the override is captured for the learning loop. "
        "Every constant in the formula has a stakeholder-arguable English rationale in config/models.yaml.",
        size=Pt(12), color=DARK_GRAY)
    _footer(s, page[0], TOTAL)

    # 14 · Storage — SQLite → Cosmos DB ─────────────────────────────────────
    s = new()
    _header_bar(s, "Storage  —  SQLite → Cosmos DB Lift-and-Shift",
                "Same schema, same partition keys, no calling-code change")
    _table(s, Inches(0.5), Inches(1.05), Inches(12.3), Inches(3.4), [
        ["Container",           "Partition Key",  "Key Fields",                                       "Purpose"],
        ["raw_posts",           "/subreddit",     "id, title, body, author_hash, created_utc",         "Ingested (privacy-safe)"],
        ["analyses",            "/subreddit",     "post_id, sentiment, confidence, aspects, trust",    "AI analysis results"],
        ["aggregates",          "/time_window",   "subreddit, window, metrics_json",                    "Pre-computed KPIs"],
        ["alerts",              "/severity",      "type, aspect, threshold_breached",                   "Triggered anomalies"],
        ["feedback",            "/analyst_id",    "post_id, correction, reply_text",                    "HITL corrections + replies"],
        ["notification_log",    "/group_id",      "post_id, channel, status, sent_at",                  "Delivery audit trail"],
    ], first_col_bold=True, body_font=Pt(10))
    _rect(s, Inches(0.5), Inches(4.6), Inches(6.0), Inches(2.3),
          LIGHT_BLUE, line=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(4.75), Inches(5.6), Inches(0.35),
        "Design choices", size=Pt(12), bold=True, color=WALMART_BLUE)
    _bullets(s, Inches(0.7), Inches(5.1), Inches(5.6), Inches(1.7), [
        "SQLite in WAL mode for hot dev data",
        "data JSON column mirrors Cosmos doc",
        "Pluggable StorageBackend interface",
        "Nightly backup + JSONL cost ledger",
    ], size=Pt(11))
    _rect(s, Inches(6.75), Inches(4.6), Inches(6.05), Inches(2.3),
          GREEN_TINT, line=GREEN)
    _tx(s, Inches(6.95), Inches(4.75), Inches(5.7), Inches(0.35),
        "Migration story", size=Pt(12), bold=True, color=GREEN)
    _bullets(s, Inches(6.95), Inches(5.1), Inches(5.7), Inches(1.7), [
        "Swap SQLiteBackend → CosmosBackend",
        "Same CREATE TABLE mapped to container spec",
        "Partition keys already match production",
        "Zero change to pipeline / dashboard code",
    ], size=Pt(11))
    _footer(s, page[0], TOTAL)

    # 15 · Evaluation summary ───────────────────────────────────────────────
    s = new()
    _header_bar(s, "Evaluation Summary  —  Post-Midsem Numbers",
                "All results reported against the same 200-post retail-Reddit gold set")
    _table(s, Inches(0.5), Inches(1.1), Inches(12.3), Inches(5.6), [
        ["Area",             "Metric",                                          "Value",         "Notes"],
        ["Sentiment",        "Macro-F1 (final)",                                "0.7642",        "+13.7 pts vs RoBERTa baseline"],
        ["Sentiment",        "Long-post F1  (> 256 tokens)",                    "1.0000",        "From 0.2778 baseline"],
        ["Sentiment",        "Cross-validation",                                "5-fold OOF",    "No test-set leakage"],
        ["Vision",           "Hallucination rate",                              "0 %",           "From 50 % on single-pass"],
        ["Vision",           "Text extraction success",                         "75 %",          "From 25 % on single-pass"],
        ["Vision",           "Retail-signal recall",                            "81 %",          "From 40 % on single-pass"],
        ["Trust",            "Low-trust share  (T < 0.4)",                      "15 %",          "Of the 200-post set"],
        ["Trust",            "Annotator agreement on low-trust",                "12 / 15",       "80 %"],
        ["Ops",              "Subreddits tracked",                              "25",            "Six community groups"],
        ["Ops",              "Scheduler cadence",                               "6 h + manual",  "asyncio lifespan task"],
        ["Ops",              "Dashboard pages shipped",                         "8",             "Brand Health · Alerts · Explorer · Review · Lifecycle · Insights · Pipeline · Notifications"],
    ], first_col_bold=True, body_font=Pt(10),
       highlight_rows={1: GREEN_TINT, 2: GREEN_TINT, 4: GREEN_TINT, 5: GREEN_TINT})
    _footer(s, page[0], TOTAL)

    # 16 · Contributions ────────────────────────────────────────────────────
    s = new()
    _header_bar(s, "Principal Contributions",
                "What this dissertation delivered — end to end")
    contribs = [
        ("C1", "Offline-first RSI pipeline",
         "Ingestion → trust → sentiment → aspects → vision → aggregation → alerts → dashboard.  Zero API cost, modular, deployable to Azure."),
        ("C2", "Fine-tuned ModernBERT (3-stage curriculum)",
         "Macro-F1 0.6272 → 0.7642 overall; 0.28 → 1.00 on long posts.  5-fold OOF cross-validation, offline training."),
        ("C3", "Multi-pass vision technique on Gemma 3 4B",
         "Hallucination 50 % → 0 %,  extraction 25 % → 75 %.  Adapts techniques from 5 recent VLM papers without vendor-blocked models."),
        ("C4", "Interpretable trust score + admission gate",
         "trust × confidence gate flags rather than drops low-credibility posts.  Every constant traceable to English rationale in config."),
        ("C5", "HITL learning-loop dashboard",
         "Review & Validate, Lifecycle Kanban, Insights, Notification centre.  Corrections & posted replies feed few-shot reply generation and future retraining."),
    ]
    y = Inches(1.05)
    for tag, title, body in contribs:
        _rect(s, Inches(0.5), y, Inches(12.3), Inches(1.05),
              LIGHT_GRAY, line=WALMART_BLUE)
        _rect(s, Inches(0.5), y, Inches(0.9), Inches(1.05), WALMART_BLUE)
        _tx(s, Inches(0.5), y, Inches(0.9), Inches(1.05),
            tag, size=Pt(20), bold=True, color=WHITE,
            align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        _tx(s, Inches(1.55), y + Inches(0.05), Inches(11.0), Inches(0.35),
            title, size=Pt(13), bold=True, color=DARK_BLUE)
        _tx(s, Inches(1.55), y + Inches(0.4), Inches(11.0), Inches(0.65),
            body, size=Pt(11), color=DARK_GRAY)
        y = y + Inches(1.14)
    _footer(s, page[0], TOTAL)

    # 17 · Live Demo (screenshot grid) ──────────────────────────────────────
    s = new()
    _header_bar(s, "Live Demo  —  Dashboard Walkthrough",
                "One post → alert → review → reply → lifecycle → resolved")
    shots = [
        ("Brand Health",       UI_DIR / "brand_health.png"),
        ("Alert Feed",         UI_DIR / "alert_feed.png"),
        ("Post Explorer",      UI_DIR / "post_explorer.png"),
        ("Review & Validate",  UI_DIR / "review_validate.png"),
        ("Lifecycle Kanban",   UI_DIR / "lifecycle_kanban.png"),
        ("Insights",           UI_DIR / "insights_competitor.png"),
    ]
    # 3 across × 2 down
    thumb_w = Inches(4.15)
    thumb_h = Inches(2.55)
    x0, y0 = Inches(0.35), Inches(1.05)
    gap = Inches(0.1)
    for i, (label, path) in enumerate(shots):
        col = i % 3
        row = i // 3
        lx = x0 + col * (thumb_w + gap)
        ly = y0 + row * (thumb_h + Inches(0.3))
        _image(s, path, lx, ly, width=thumb_w, height=thumb_h)
        _tx(s, lx, ly + thumb_h + Inches(0.02), thumb_w, Inches(0.25),
            label, size=Pt(11), bold=True, color=DARK_BLUE, align=PP_ALIGN.CENTER)
    _footer(s, page[0], TOTAL)

    # 18 · Conclusions (RQ1–RQ4) ────────────────────────────────────────────
    s = new()
    _header_bar(s, "Conclusions  —  Research Questions Answered")
    rqs = [
        ("RQ1", "Can a fine-tuned encoder beat baselines on Reddit retail sentiment?",
         "YES  —  ModernBERT 3-stage curriculum raised Macro-F1 from 0.6272 → 0.7642 overall  "
         "and from 0.2778 → 1.0000 on long posts.", GREEN),
        ("RQ2", "Can a compliant open-weights VLM extract structured retail signal from screenshots?",
         "YES  —  Multi-pass pipeline on Gemma 3 4B reduced hallucination from 50 % → 0 %  "
         "and lifted text extraction from 25 % → 75 %.", GREEN),
        ("RQ3", "Can a defensible trust score filter low-credibility posts without silent drops?",
         "YES  —  Interpretable 3-part score flagged 15 % of posts;  12 of 15 confirmed by human annotator.  "
         "All low-trust posts remain visible and analyst-overridable.", GREEN),
        ("RQ4", "Can a HITL workflow produce a re-training signal from analyst corrections?",
         "YES  —  Every correction and posted reply is logged in the  feedback  table  →  "
         "feeds ModernBERT Stage-3 augmentation and FLAN-T5 few-shot pool.", GREEN),
    ]
    y = Inches(1.05)
    for tag, q, a, col in rqs:
        _rect(s, Inches(0.5), y, Inches(12.3), Inches(1.35),
              LIGHT_GRAY, line=col)
        _rect(s, Inches(0.5), y, Inches(0.9), Inches(1.35), col)
        _tx(s, Inches(0.5), y, Inches(0.9), Inches(1.35),
            tag, size=Pt(18), bold=True, color=WHITE,
            align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        _tx(s, Inches(1.55), y + Inches(0.08), Inches(11.0), Inches(0.4),
            q, size=Pt(12), bold=True, color=DARK_BLUE)
        _tx(s, Inches(1.55), y + Inches(0.5), Inches(11.0), Inches(0.85),
            a, size=Pt(11), color=DARK_GRAY)
        y = y + Inches(1.44)
    _footer(s, page[0], TOTAL)

    # 19 · Recommendations ──────────────────────────────────────────────────
    s = new()
    _header_bar(s, "Recommendations  —  Immediate Follow-Ons")
    recs = [
        ("Monthly retraining cadence",
         "Use the HITL feedback store as the incremental labelling stream and re-run the 3-stage curriculum monthly.",
         WALMART_BLUE),
        ("Bilingual pass  (Hindi + English)",
         "Validate the retail taxonomy with native-speaker analysts before extending to Indian retail communities.",
         PURPLE),
        ("Per-team SLA dashboards",
         "Extend the Post Lifecycle SLA analytics into per-team dashboards once analyst volume passes ~50 posts / day.",
         GREEN),
    ]
    y = Inches(1.2)
    for title, body, col in recs:
        _rect(s, Inches(0.5), y, Inches(12.3), Inches(1.65),
              LIGHT_GRAY, line=col)
        _rect(s, Inches(0.5), y, Inches(0.2), Inches(1.65), col)
        _tx(s, Inches(0.9), y + Inches(0.15), Inches(11.5), Inches(0.5),
            title, size=Pt(15), bold=True, color=DARK_BLUE)
        _tx(s, Inches(0.9), y + Inches(0.7), Inches(11.5), Inches(0.9),
            body, size=Pt(12), color=DARK_GRAY)
        y = y + Inches(1.8)
    _footer(s, page[0], TOTAL)

    # 20 · Future Work — Model + Product ────────────────────────────────────
    s = new()
    _header_bar(s, "Future Work  —  Model + Product",
                "Directions grouped by layer of the stack")
    _rect(s, Inches(0.5), Inches(1.05), Inches(6.05), Inches(5.6),
          LIGHT_BLUE, line=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(1.2), Inches(5.7), Inches(0.4),
        "Model-level", size=Pt(14), bold=True, color=WALMART_BLUE)
    _bullets(s, Inches(0.7), Inches(1.65), Inches(5.7), Inches(4.8), [
        "Joint sentiment + aspect head on a shared encoder  (~30 % inference saving)",
        "Distil ModernBERT to ~50 M-parameter student  →  CPU-only edge inference",
        "Reasoning-augmented VLM captioning  (LLaVA-Next 1.6 B or SmolVLM)",
        "3-seed ensemble for tighter F1 variance",
        "Blind 25-post recheck for defensibility",
    ], size=Pt(12))
    _rect(s, Inches(6.75), Inches(1.05), Inches(6.05), Inches(5.6),
          PURPLE_TINT, line=PURPLE)
    _tx(s, Inches(6.95), Inches(1.2), Inches(5.7), Inches(0.4),
        "Product-level", size=Pt(14), bold=True, color=PURPLE)
    _bullets(s, Inches(6.95), Inches(1.65), Inches(5.7), Inches(4.8), [
        "Auto-reply confidence gate  —  promote LLM drafts to \"queued to send\" when analyst edit-distance < threshold",
        "Predictive P1 forecast  —  seasonal decomposition on daily counts (24–48 h ahead)",
        "Bilingual (Hindi + English) taxonomy",
        "Slack-bot inline notification responses",
        "Automated retraining pipeline hook",
    ], size=Pt(12))
    _footer(s, page[0], TOTAL)

    # 21 · Future Work — Operational ────────────────────────────────────────
    s = new()
    _header_bar(s, "Future Work  —  Operational",
                "Path from local prototype to Walmart-production service")
    ops = [
        ("Kubernetes CronJob",
         "Deploy the pipeline as a scheduled Kubernetes CronJob backed by a managed Postgres instance for multi-analyst concurrency.",
         WALMART_BLUE),
        ("Azure Cosmos DB migration",
         "Swap SQLiteBackend for CosmosBackend (schema already mirrors partition design)  —  no calling-code change.",
         GREEN),
        ("Walmart ticketing integration",
         "P1 alerts open cases directly in Walmart's internal ticketing so the analyst never leaves the workflow.",
         AMBER),
        ("Broader ingestion",
         "Extend beyond Reddit to Twitter / X, YouTube comments, and app-store reviews on the same trust + sentiment stack.",
         PURPLE),
    ]
    y = Inches(1.15)
    for title, body, col in ops:
        _rect(s, Inches(0.5), y, Inches(12.3), Inches(1.3),
              LIGHT_GRAY, line=col)
        _rect(s, Inches(0.5), y, Inches(0.2), Inches(1.3), col)
        _tx(s, Inches(0.9), y + Inches(0.12), Inches(11.5), Inches(0.45),
            title, size=Pt(14), bold=True, color=DARK_BLUE)
        _tx(s, Inches(0.9), y + Inches(0.6), Inches(11.5), Inches(0.7),
            body, size=Pt(11), color=DARK_GRAY)
        y = y + Inches(1.42)
    _footer(s, page[0], TOTAL)

    # 22 · Source Code + Deliverables ───────────────────────────────────────
    s = new()
    _header_bar(s, "Source Code & Deliverables")
    _rect(s, Inches(0.5), Inches(1.05), Inches(12.3), Inches(1.1),
          LIGHT_BLUE, line=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(1.15), Inches(12.0), Inches(0.35),
        "Repository", size=Pt(12), bold=True, color=WALMART_BLUE)
    _tx(s, Inches(0.7), Inches(1.55), Inches(12.0), Inches(0.55),
        "https://gecgithub01.walmart.com/v0s01jh/Retail_Sentiment_Intelligence",
        size=Pt(16), bold=True, color=DARK_BLUE, anchor=MSO_ANCHOR.MIDDLE)
    _table(s, Inches(0.5), Inches(2.35), Inches(12.3), Inches(4.5), [
        ["Deliverable",              "Path in repo",                                                   "Contents"],
        ["Final Report (PDF)",       "docs/Sem_4/final/FINAL_REPORT_VishalSingh_2020AA05641.pdf",       "10 chapters + appendices + refs"],
        ["Final Report (LaTeX)",     "docs/Sem_4/final/latex/",                                        "Reproducible xelatex source"],
        ["Pipeline core",             "src/pipeline.py, src/ingestion/, src/analysis/",                 "6-layer async pipeline"],
        ["Sentiment training",       "scripts/train_modernbert_sentiment.py",                          "3-stage curriculum runner"],
        ["Evaluation notebook",      "evaluation/trust_score_walmart200.ipynb",                        "Reproducible 5-fold OOF eval"],
        ["Dashboard",                "frontend/  (React + Vite + Tailwind)",                           "8 pages, live via WebSocket"],
        ["Reproduction",             "Appendix B of the report  ·  start.sh",                          "Clone → conda → start"],
    ], first_col_bold=True, body_font=Pt(10))
    _footer(s, page[0], TOTAL)

    # 23 · Thank You / Q&A ──────────────────────────────────────────────────
    s = new()
    _set_bg(s, DARK_BLUE)
    _tx(s, Inches(0.5), Inches(1.9), Inches(12.3), Inches(1.2),
        "Thank You", size=Pt(72), bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    _tx(s, Inches(0.5), Inches(3.3), Inches(12.3), Inches(0.5),
        "Retail Sentiment Intelligence  ·  Post Mid-Semester Presentation",
        size=Pt(18), color=YELLOW, align=PP_ALIGN.CENTER)
    _tx(s, Inches(0.5), Inches(4.1), Inches(12.3), Inches(0.5),
        "Questions ?", size=Pt(28), bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    _rect(s, Inches(2.0), Inches(5.05), Inches(9.3), Inches(1.4),
          LIGHT_BLUE, line=YELLOW)
    _tx(s, Inches(2.2), Inches(5.2), Inches(8.9), Inches(0.35),
        "Repository", size=Pt(11), bold=True, color=WALMART_BLUE,
        align=PP_ALIGN.CENTER)
    _tx(s, Inches(2.2), Inches(5.55), Inches(8.9), Inches(0.5),
        "gecgithub01.walmart.com/v0s01jh/Retail_Sentiment_Intelligence",
        size=Pt(15), bold=True, color=DARK_BLUE, align=PP_ALIGN.CENTER)
    _tx(s, Inches(2.2), Inches(6.05), Inches(8.9), Inches(0.35),
        "Report:  docs/Sem_4/final/FINAL_REPORT_VishalSingh_2020AA05641.pdf",
        size=Pt(11), color=MED_GRAY, align=PP_ALIGN.CENTER)
    _tx(s, Inches(0.5), Inches(6.75), Inches(12.3), Inches(0.4),
        "Vishal Singh  ·  2020AA05641  ·  BITS Pilani (WILP)  ·  Walmart Global Tech, Bengaluru",
        size=Pt(12), color=LIGHT_BLUE, align=PP_ALIGN.CENTER)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"[OK] wrote {OUT}  ({page[0]} slides)")


if __name__ == "__main__":
    build()
