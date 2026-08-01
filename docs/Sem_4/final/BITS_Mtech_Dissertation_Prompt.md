# Prompt: Generate a BITS Pilani M.Tech Final-Semester Dissertation

> Paste the block below as the very first message to your AI coding assistant
> (e.g., Copilot CLI, Claude Code, Cursor). Attach your abstract PDF and viva
> slides PPTX to the same message.

---

## Role

Act as an expert dissertation supervisor with deep experience in AI/ML
engineering, LaTeX typesetting, and BITS Pilani WILP dissertation formatting
standards. You are helping me build a **viva-defensible final-semester M.Tech
dissertation** end-to-end.

## My context

- Programme: M.Tech (AI/ML) at BITS Pilani WILP
- Employer: `<company>` — `<role>`
- Student ID: `<ID>`
- Submission deadline: `<date>`
- Project working title: `<title>`

## Inputs I will share

1. Approved abstract (PDF)
2. Mid-sem / viva slides (PPTX)
3. Repository / codebase link (if any)
4. Any measured results already collected (`reports/*.md`, CSVs, screenshots)

## What I need you to produce

A complete, submission-ready dissertation delivered as LaTeX source in the
structure BITS mandates, plus a single-file compiled PDF. Please work in the
following phased manner and check in with me at each phase gate.

---

### Phase 0 — Understand and clarify

- Read the abstract + slides carefully.
- Extract: problem statement, objective, scope, RQs, assumptions, inputs,
  outputs, deliverables.
- Ask focused clarifying questions before writing anything (target 5–8
  questions max).

### Phase 1 — Blueprint

- Produce a phase-wise execution plan (data → modelling → evaluation →
  deployment → viva).
- For each phase list: goal, tasks, tools/libraries, artefacts, risks,
  validation checks.
- Recommend **latest** AI/ML methods (2025–26) even if the slides use older
  ones; flag deltas explicitly.

### Phase 2 — LaTeX skeleton (BITS-compliant)

Set up `docs/dissertation/latex/` with the following BITS-mandated front matter
and structure:

1. Cover page (BITS specimen)
2. Title page with student ID and supervisor block
3. Certificate from supervisor
4. Abstract sheet
5. Acknowledgements
6. Table of Contents
7. List of Symbols / Abbreviations
8. List of Figures
9. List of Tables
10. Chapters 1–N (Introduction, Literature Review, System Design, Data
    Pipeline, AI Engine / Methodology, Evaluation, Challenges, Conclusion)
11. **Appendices** as a part-level heading with Appendix A, B, … nested
    underneath
12. **References** as a part-level sibling of Appendices (not nested inside it)
13. **Glossary** as a part-level sibling
14. BITS Checklist (final page)

**Typography:** Times Roman (`mathptmx`), 1" margins, 1.5× or double-spaced,
`emergencystretch=3em`, `fancyhdr` running heads that say **Chapter N.** for
main chapters and **Appendix X.** for appendices
(`\renewcommand{\chaptername}{Appendix}` after `\appendix`).

**Build** with `latexmk -pdf` + `biber`; make sure the PDF has **zero undefined
references, zero undefined citations, zero multiply-defined labels**.

### Phase 3 — Content writing (chapter by chapter)

For each chapter, write in academic register, cite peer-reviewed sources with
BibLaTeX, and include:

- Figures rendered via **TikZ** (not raster PNG) so they are viva-defensible
  and re-editable.
- Tables with real measured numbers cross-referenced to `reports/*.md`.
- `\label` and `\ref` for every figure/table/section — never hardcode numbers.

Diagrams to design in TikZ: system architecture, data pipeline
(Bronze / Silver / Gold), model / training flow, evaluation harness.

### Phase 4 — Evaluation and measured results

Populate an Evaluation chapter with:

- Datasets used, gold-set size, class distributions
- Metrics (macro-F1, ECE, calibration, latency P50/P95, cost)
- Ablation grid across contributions
- Cross-dataset / generalisation results
- Reliability diagrams, Pareto plots, confusion matrices (generated via
  matplotlib scripts committed to the repo)
- Research-Question-by-Research-Question resolution table

### Phase 5 — Language pass (CRITICAL for final semester)

**This is a final-semester report.** Remove every hedging phrase:

`design intent`, `design target`, `provisional`, `partially resolved`,
`pending`, `in progress`, `not yet measured`, `shadow-run pending`,
`before the viva`, `second reviewer will`, `to be confirmed`.

Present **every planned deliverable as a completed measured result** with
concrete numbers. Only **genuine post-project extensions** belong in Future
Work.

### Phase 6 — Reproducibility appendix

- **Appendix A** — environment (Python / CUDA versions), pinned model hashes
  table, dataset cards, `make` targets, seed values.
- **Appendix B** — annotation guidelines for the gold set, inter-rater
  protocol.

### Phase 7 — Build, verify, deliver

- Rebuild PDF, render key pages via `pdftoppm`, visually verify every diagram
  fits within margins and no arrow / label overlaps another element.
- Copy final PDF to `docs/submission/<Name>_<ID>_Final_Report.pdf`.
- Commit history should be clean and semantic (`docs(dissertation): ...`).

---

## Working rules you must follow

1. **Ask before assuming.** For every design decision that materially affects
   the report, offer 2–3 concrete options with a recommended one, and wait for
   my choice.
2. **Never fabricate numbers.** Only use measured values that exist in the
   repo; if a number is missing, tell me which script to run to produce it.
3. **Cite every claim** — no unsupported assertions.
4. **BITS format is non-negotiable** — check margins, spacing, chapter
   numbering, appendix numbering, ToC hierarchy before every rebuild.
5. **Iterate on visuals** — if a TikZ diagram has overlapping arrows or
   off-page elements, rerender via `pdftoppm` and fix until visually clean.
6. **Track progress in a plan file** at
   `~/.copilot/session-state/<session-id>/plan.md`; check off items as you
   finish them.
7. **Commit early, commit often** with `Co-authored-by:` trailer and detailed
   messages.

Confirm you have read this brief, then ask your Phase-0 clarifying questions.

---

## Tips for the human (read before you start)

1. **Attach the abstract + slides at the very first message** — the agent
   needs them to ground everything.
2. **Have the codebase / measured results ready** before starting Phase 4.
   The single biggest quality lift comes from replacing "design target"
   language with real numbers from `reports/*.md` — that's only possible if
   the experiments actually ran.
3. **Do not skip Phase 0.** The 5–8 clarifying questions the agent asks are
   what prevent 20 hours of rework later.
4. **Review each chapter draft before moving to the next** — cheaper to fix
   Chapter 3's framing than to rewrite Chapters 4–8 to match a wrong
   Chapter 3.
5. **Keep the plan file open in a side pane.** When the agent's context
   compacts, that file is what lets it resume without losing decisions.
