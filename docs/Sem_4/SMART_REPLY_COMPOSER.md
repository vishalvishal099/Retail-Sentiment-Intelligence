# Smart Reply Composer — Full Design Reference

> Companion note for the Post Mid-Semester deck
> (slides 5, 6, 7 of `FINAL_PRESENTATION_VishalSingh_2020AA05641.pptx`).
> Kept as a standalone document so it can be reused in the final report,
> the viva, or a future presentation.

The Smart Reply Composer is the sub-system that produces the customer-facing
reply drafts an analyst chooses from in **Review & Validate**. It is a
**triple-draft** composer — a cascade of two LLMs plus a deterministic
template, all fed the **same prompt** so the drafts are directly comparable.

---

## 1 · Three drafts, one prompt

For every negative post the analyst reviews, the backend calls
`generate_reply_pair(...)` on `src/analysis/llm_client.py`
(class `WalmartLLMClient`). The method returns exactly **three drafts**:

| # | Draft | Model | Transport | Cost | Latency (warm) | Role |
|---|-------|-------|-----------|------|----------------|------|
| A | **GPT-4o** | `gpt-4o` | Walmart LLM Gateway (`/chat/completions`) — HTTPS + `Authorization: Bearer <gateway_key>` + `WM_CONSUMER.ID` / `WM_SVC.NAME` / `WM_SVC.ENV` headers | ~USD 0.0002 per reply | ~2 s | Highest-quality reasoning, brand-safe by policy |
| B | **Mistral 7B-Instruct** | `mistral:7b-instruct` | Local **Ollama** at `http://localhost:11434/api/generate` | Free (compute-only) | ~10–15 s | Open-weights, offline, strong at retail slang |
| C | **Smart Composer** | `_smart_compose_reply(...)` | Pure Python, no model | 0 | <10 ms | Deterministic safety-net; always available |

The three drafts are shown side-by-side in the UI. The analyst picks one,
edits inline, and clicks **Save & Open Reddit** — the posted reply is written
to the `feedback` table and becomes a **future few-shot example**.

### Cascade & fallback logic

Every slot is guaranteed to have a draft:

1. **GPT-4o path (slot A)**
   - Primary → Walmart LLM Gateway
   - Fallback → direct OpenAI SDK (if `OPENAI_API_KEY` env var is set)
   - Fallback → Smart Composer with an `[offline fallback]` badge in the UI
   - Reasons surfaced to the UI: `no_gateway_key`, `no_consumer_id`, `network_unreachable`
2. **Mistral path (slot B)**
   - Primary → local Ollama HTTP endpoint
   - Fallback → Smart Composer with `[offline fallback]` badge
3. **Smart Composer path (slot C)**
   - Never fails; produces a varied, aspect-specific reply from curated phrase pools

A circuit-breaker disables the gateway after 3 consecutive failures per API
process so a bad token or network blip doesn't hang the dashboard.

---

## 2 · Prompt design

The prompt is assembled by `_build_reply_prompt(...)` and fed **verbatim** to
both GPT-4o and Mistral. Keeping the prompt identical makes A/B comparison
meaningful: differences between drafts A and B reflect only the model, not
the instruction.

### 2.1 Template

```text
You are a senior Walmart customer-care analyst replying on Reddit.
Write ONE reply to the customer below. Keep it 2-4 sentences,
empathetic, specific to their complaint, no corporate jargon,
no hashtags, no emojis. Do NOT promise refunds you can't verify;
invite them to DM order details if action is needed. Sign off as
a real person, not a brand.

Example customer post: {past_post_1}
Example analyst reply: {past_reply_1}
Example customer post: {past_post_2}
Example analyst reply: {past_reply_2}
Example customer post: {past_post_3}
Example analyst reply: {past_reply_3}

Subreddit: r/{subreddit}
Customer ({author}) complaint about: {aspect_1}, {aspect_2}
Customer post:
{post_title + "\n\n" + post_body, truncated to 1200 chars}

Reply:
```

### 2.2 Style guardrails (baked into the system role)

- **Length** — 2 to 4 sentences. Prevents wall-of-text corporate replies.
- **Tone** — empathetic, specific to the actual complaint (no boilerplate).
- **Forbidden content** — corporate jargon, hashtags, emojis.
- **Compliance** — no unverifiable refund promises; ask the customer to DM
  order details if action is needed.
- **Identity** — sign off as a real person (e.g. "— Ravi (Walmart Care)"),
  never as an anonymous brand handle.

### 2.3 Input variables

| Variable | Source | Notes |
|----------|--------|-------|
| `{subreddit}` | post record | e.g. `walmart`, `WalmartEmployees` |
| `{author}` | post record | Reddit handle, defaults to `there` when unknown |
| `{aspect_1}, {aspect_2}` | RSI aspect head | Top aspects from the 8-item retail taxonomy |
| `{post_title + post_body}` | post record | Concatenated, truncated to 1200 chars |
| `{past_post_i}, {past_reply_i}` | `feedback` table | Top-3 human-validated replies from the same aspect |

### 2.4 Sampling parameters

| Model | `temperature` | `top_p` | `max_tokens` | Notes |
|-------|--------------|---------|--------------|-------|
| GPT-4o (Walmart Gateway) | 0.7 | (default) | 300 | Warm reasoning without going off-brand |
| Mistral 7B-Instruct (Ollama) | 0.55 | 0.9 | 220 (`num_predict`) | Slightly cooler; open-weights model is chattier |
| Smart Composer | n/a | n/a | n/a | Seeded RNG picks phrase-pool variants; new seed per call |

---

## 3 · Few-shot prompting — the feedback loop

The three `Example customer post` / `Example analyst reply` blocks are the
**few-shot pool**. They come from the `feedback` table — every time an
analyst edits a draft and clicks **Save & Open Reddit**, the final text is
persisted with:

```python
{
    "kind": "auto_reply_posted",
    "post_id": <original_post_id>,
    "analyst_id": <session_analyst>,
    "reply_text": <final_reply>,
    "created_at": <utc_iso>,
    "partition_key": <analyst_id>,
}
```

On the next `Generate Drafts` click, the query for few-shot examples pulls
the **top-3 most recent posted replies** that share at least one aspect with
the current post. That means:

- **Cold start**: first few weeks the pool is empty → GPT / Mistral behave
  purely on their pre-training; Smart Composer uses its default phrase pools.
- **Warm state** (after ~50 posted replies): each `Generate Drafts` call
  automatically adapts to the analyst team's preferred phrasing, sign-off
  style, and handling of common aspects (returns, delivery, product quality).
- **No retraining needed** — the few-shot slot is refreshed at inference
  time. Model weights are not touched.

The same `feedback` rows are the primary re-training signal for a **future**
ModernBERT and FLAN-T5 fine-tune (see the Learning Loop slide).

---

## 4 · Smart Composer (Draft C) — how it works without an LLM

`_smart_compose_reply(...)` produces a **content-aware, varied** reply
without calling any model. It combines four ingredients:

1. **Topic extraction** — scans title + body against a keyword table
   (`_COMPLAINT_KEYWORDS`) for the specific complaint noun the customer
   actually used: `refund`, `damaged item`, `expired product`, `late delivery`,
   `billing issue`, `the self-checkout issue`, and so on.

2. **Aspect phrase** — the primary aspect (e.g. `product_quality`) is mapped
   to a customer-facing phrase (`the quality of what you received`) via
   `_ASPECT_LABELS`. Both new-taxonomy names and legacy aliases are handled.

3. **Randomised phrase pools** — openings, acknowledgments, actions, and
   closings are picked from curated pools with a seeded RNG. Every call gets
   a fresh seed (based on wall-clock time), so consecutive `Regenerate`
   clicks produce genuinely different replies rather than the same template.

4. **Handle personalisation** — the reply is addressed to the actual Reddit
   handle (`u/hangry_shopper` → `hangry_shopper`).

The composer is the deterministic **safety net**: if both GPT and Mistral
are unreachable, the UI still shows three drafts.

---

## 5 · Worked example

**Customer complaint** (r/walmart, aspects: `product_quality`, `returns`)

> **u/hangry_shopper** — *"Bought a 2-lb strawberry pack from OGP pickup last
> night and half of them are mouldy today. Store said returns close at 9pm
> and refused to help. Second time this month — is this the new normal?"*

**Draft A — GPT-4o (Walmart LLM Gateway)**

> Really sorry to see mouldy berries twice in one month — that's not the
> pickup quality we want you to have. Please DM the order number and I'll
> get produce ops to look at that store's chill-chain and cover the refund
> for you.
> — Ravi (Walmart Care)

**Draft B — Mistral 7B-Instruct (Ollama)**

> That's genuinely frustrating — nobody expects two bad pickups in a row.
> Send me a DM with the order # and I'll route it to the store manager and
> produce ops so we can dig into the chill chain and refund you today.
> — Priya

**Draft C — Smart Composer**

> Hi hangry_shopper, we're sorry about the quality of what you received on
> your pickup — returns closing at 9pm shouldn't leave you without a refund.
> Please DM us your order details and we'll get the produce team on it.
> — Walmart Care

**What happens next**

- Analyst reviews all three; picks Draft A, tweaks the sign-off.
- Clicks **Save & Open Reddit** → the reply is copied to the clipboard, the
  Reddit thread opens, and a row is written to `feedback`.
- The analyst pastes on Reddit and returns to the dashboard; the post moves
  from `In Progress` → `Resolved` in the Kanban board.
- The posted reply is now eligible as a few-shot example for the *next*
  `product_quality` / `returns` complaint.

---

## 6 · Code map

| Concern | File | Symbol |
|---------|------|--------|
| Public entry point | `src/analysis/llm_client.py` | `WalmartLLMClient.generate_reply_pair` |
| GPT-4o via Walmart Gateway | `src/analysis/llm_client.py` | `WalmartLLMClient._gateway_generate_reply` |
| GPT-4o direct OpenAI fallback | `src/analysis/llm_client.py` | inline in `_gateway_generate_reply` |
| Mistral via Ollama | `src/analysis/llm_client.py` | `WalmartLLMClient._ollama_generate_reply` |
| Smart Composer | `src/analysis/llm_client.py` | `_smart_compose_reply` |
| Prompt builder | `src/analysis/llm_client.py` | `WalmartLLMClient._build_reply_prompt` |
| API route | `src/dashboard/api.py` | `POST /api/review/{post_id}/draft-reply-all` |
| UI | `frontend/src/pages/ReviewQueue.tsx` | Draft cards & selector |
| Feedback persistence | `src/dashboard/api.py` | `POST /api/review/{post_id}/reply` |
| Config knobs | `src/utils/config.py` | `LLMConfig` (`wmt_gateway_*`, `ollama_*`, `openai_*`) |

---

## 7 · Configuration knobs (excerpt from `LLMConfig`)

```python
azure_deployment: str = "gpt-4o-mini"    # legacy Azure path (rarely used)
wmt_gateway_model: str = "gpt-4o"        # gateway model name for slot A
wmt_gateway_url:   str                    # https://<gateway>/v1
wmt_gateway_key:   str                    # bearer token
wmt_consumer_id:   str                    # WM_CONSUMER.ID header
wmt_svc_name:      str = "WMTLLMGATEWAY"
wmt_svc_env:       str = "stage"
ollama_url:        str = "http://localhost:11434"
ollama_model:      str = "mistral:7b-instruct"     # slot B
openai_api_key:    str                    # optional slot-A fallback
openai_model:      str = "gpt-4o-mini"
```

---

## 8 · Talking-track cheatsheet (viva prompts)

- *"Why three drafts, not one?"* — LLMs are non-deterministic and different
  models have different failure modes. Showing three drafts lets the
  analyst pick the best tone in one click; the Smart Composer guarantees a
  draft even offline.
- *"Why the same prompt for GPT and Mistral?"* — Fair A/B comparison; any
  quality difference is model-attributable.
- *"How does the loop improve replies over time?"* — Every posted reply is
  written to the `feedback` table; the next `Generate` pulls the top-3 most
  recent aspect-matched replies into the few-shot slot. No retraining.
- *"What if the Walmart gateway is down?"* — Circuit breaker after 3
  failures → falls back to direct OpenAI (if key set), then to the Smart
  Composer. The UI badges the slot as `[offline fallback]` so the analyst
  knows the source.
- *"Why not a fine-tuned reply model?"* — Currently the reply pool is
  ~hundreds of examples; not enough for supervised fine-tuning. Few-shot
  prompting on top of GPT-4o / Mistral is the right regime at this scale.
  A fine-tune is on the future-work roadmap once the pool passes ~10 k.
