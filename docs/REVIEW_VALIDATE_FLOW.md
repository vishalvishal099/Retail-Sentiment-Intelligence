# Review & Validate — Complete Flow

## Overview

Posts enter the Review Queue when the sentiment model's confidence is below the threshold (65%).  
An analyst works through them using the **Review & Validate** page.

---

## Flow Diagram

```mermaid
flowchart TD
    A[🔄 Pipeline ingests Reddit post\nModernBERT / RoBERTa analysis] --> B{Confidence\n≥ 65%?}

    B -- Yes --> Z[✅ Flows directly to\nBrand Health Dashboard\naggregates + charts]

    B -- No --> C[📋 PENDING REVIEW\nneeds_review = true]

    %% ── PENDING actions ─────────────────────────────────────────────
    C --> D{Analyst picks action}

    D -- "Change sentiment\n✓Positive / —Neutral / ✗Negative" --> E[Sentiment corrected\nHITL feedback recorded\nneeds_review = false]

    D -- "✓ Confirm\n(model was right)" --> F[Confirmation recorded\nHITL feedback recorded\nneeds_review = false]

    D -- "✨ Generate Drafts" --> G[Two outputs generated\nin parallel via GPT-4o]

    G --> G1[📨 Customer Reply\nDraft A: GPT-4o\nDraft B: Mistral\nDraft C: Smart Composer]
    G --> G2[⚡ Internal Action Note\nGPT-4o recommendation\neditable before saving]

    %% ── Move to Reviewed ────────────────────────────────────────────
    E --> R[📂 REVIEWED TAB]
    F --> R

    G1 --> H[Analyst edits reply\nthen clicks Post Reply]
    H --> I[Reply posted\nreply_posted_at stamped\nLifecycle → reply_sent]
    I --> R

    %% ── Close paths ─────────────────────────────────────────────────
    R --> J{Close — pick path}

    J -- "No reply was sent\n✕ Close" --> K[lifecycle → resolved\nResolved count++ on dashboard]

    J -- "Reply sent + action needed\n⚡ Action identified" --> L[lifecycle → issue_fixed\nAction note saved\nAppears in Actionable Items]

    J -- "Reply sent, watching\n👁 Monitoring" --> M[lifecycle → reply_sent\nAppears in Ack & Reply Sent]

    %% ── Lifecycle kanban ─────────────────────────────────────────────
    L --> N[/Lifecycle Page\nActionable Items card\nwith action_note/]
    M --> O[/Lifecycle Page\nAck & Reply Sent card/]
    K --> P[/Lifecycle Page\nResolved card/]

    O -- "3+ days unresolved" --> FU[⚠️ Follow-up needed\nbanner shown on card]

    %% ── Styles ───────────────────────────────────────────────────────
    style C fill:#fef3c7,stroke:#f59e0b,color:#000
    style R fill:#dbeafe,stroke:#3b82f6,color:#000
    style K fill:#dcfce7,stroke:#16a34a,color:#000
    style L fill:#fef9c3,stroke:#ca8a04,color:#000
    style M fill:#e0f2fe,stroke:#0284c7,color:#000
    style Z fill:#f0fdf4,stroke:#86efac,color:#000
    style FU fill:#fff7ed,stroke:#fb923c,color:#000
```

---

## Action Reference

| Button | What happens | Lifecycle state |
|--------|-------------|-----------------|
| `✓ Positive` / `— Neutral` / `✗ Negative` | Corrects model label, marks reviewed | — |
| `✓ Confirm` | Agrees with model label, marks reviewed | — |
| `✨ Generate Drafts` | Generates customer reply (GPT-4o/Mistral/Smart) + internal action note | — |
| `Post Reply` | Saves reply to audit log, posts to Reddit (if OAuth live) | `reply_sent` |
| `✕ Close` (no reply sent) | Direct resolve, no response needed | `resolved` |
| `⚡ Action identified` (after reply) | Action note sent to ops team | `issue_fixed` |
| `👁 Monitoring` (after reply) | Reply sent, watching for resolution | `reply_sent` |

---

## Where results appear

| Lifecycle state | Lifecycle kanban column | Dashboard counter |
|----------------|------------------------|-------------------|
| `reply_sent` | Ack & Reply Sent | Addressed & replied |
| `issue_fixed` | Actionable Items | — |
| `resolved` | Resolved | Resolved count |

---

## Key data fields (SQLite `analyses` table)

| Field | Meaning |
|-------|---------|
| `needs_review` | `true` = still in Pending queue |
| `human_validated` | `true` = analyst has acted on this post |
| `reply_posted_at` | ISO timestamp when reply was posted |
| `close_reason` | `no_reply` / `issue_fixed` / `reply_sent` |
| `action_note` | GPT-generated internal action recommendation |
