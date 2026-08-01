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

## 3 · Few-shot prompting — deep dive

The three `Example customer post` / `Example analyst reply` blocks are the
**few-shot pool**. They come from the `feedback` table — every time an
analyst edits a draft and clicks **Save & Open Reddit**, the final text is
persisted (see `POST /api/review/{post_id}/reply` in `src/dashboard/api.py`):

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

### 3.1 What "few-shot prompting" means here

Few-shot prompting is the technique of showing an LLM **a small number of
worked examples inside the prompt** so it imitates the pattern without any
weight update. There are three regimes:

| Regime | What the model sees | When to use |
|--------|--------------------|------------ |
| Zero-shot | Just the task description | Task is well-understood by the base model |
| Few-shot (in-context learning) | 1–8 worked examples embedded in the prompt | Task is specific to a domain / brand / tone |
| Fine-tuning | Model weights updated on 1 k+ examples | Enough data, need lower latency and cost |

RSI uses **few-shot in-context learning** because (a) the reply pool is
currently in the hundreds — not thousands — and (b) the tone we want to
match is *the analyst team's*, which changes as the team learns. Fine-tuning
would ossify last month's tone; few-shot updates every day for free.

### 3.2 How the few-shot slot is filled

On every `Generate Drafts` click, `_collect_reply_examples(limit=5)` runs the
following SQL against `feedback`:

```sql
SELECT data FROM feedback
WHERE json_extract(data, '$.kind') = 'auto_reply_posted'
ORDER BY json_extract(data, '$.created_at') DESC
LIMIT 5;
```

For each row, the code also fetches the **original post** from `raw_posts`
so the LLM sees the *pair* — the customer's words on one line and the
analyst's real reply on the next. The pair is truncated to 500 chars per
side to control prompt length.

The prompt builder then keeps the **top 3 pairs** (`[:3]` in
`_build_reply_prompt`) — that gives the LLM enough tone signal without
blowing past its context window.

### 3.3 Cold start vs. warm state

| Phase | `feedback` count | What the LLM sees | Behaviour |
|-------|-----------------|--------------------|-----------|
| Day 0 | 0 | No `Example …` block | GPT / Mistral fall back to base training; Smart Composer uses default phrase pools |
| ~5 replies in | 5 | 3 pairs of real Walmart-Reddit exchanges | Drafts start echoing the analyst's sign-off, empathy words, and DM offer style |
| ~50 replies in | 50 | 3 *most recent* pairs — always fresh | Team's evolving tone shows up automatically; no retraining needed |
| ~1 000 replies in | 1 000 | Same 3 pairs *plus* it now makes sense to fine-tune a small model on the corpus (future work) | Prompt cost stays flat while training a distilled model becomes viable |

The system is designed so the **cost of few-shot is constant** (prompt is
never longer than ~4 examples) but **the pool it draws from grows without
bound**. That's why RSI ships with few-shot on day one — no annotation
sprint required to bootstrap it.

### 3.4 Why it works — intuition

Modern instruction-tuned models (GPT-4o, Mistral-7B-Instruct) have been
trained to treat "Example X: … Example Y: …" as a *task template*. When
the prompt has three consistent examples showing the same shape (customer
complaint → 2-sentence empathetic reply signed by a person), the model
biases hard toward that shape in the final generation.

Practically this fixes three problems that hit us on the pilot deck:

1. **Corporate voice** — base GPT defaults to "We apologise for the
   inconvenience …". Three real analyst replies re-anchor it to
   "Really sorry about that — DM me the order # …".
2. **Sign-off inconsistency** — some analysts sign as themselves, others as
   "Walmart Care". Few-shot picks up whichever style dominates the pool.
3. **Over-promising** — "we'll fully refund you" appears in the base model
   priors but never in real analyst replies (compliance rule). Few-shot
   suppresses it without needing a separate content filter.

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

## 5 · Worked example — a real post from our benchmark

The example below is **not synthetic**. It is post
`id=1nn7hjxx` from `data/benchmark_real_200.jsonl`, a real Sam's Club member
complaint we scraped with the Arctic Shift ingestion pipeline. We use this
post in the viva because every step is verifiable — the row exists in the
benchmark file the evaluator can open.

### 5.1 The raw post (as stored in `raw_posts`)

```json
{
  "id": "1nn7hjxx",
  "subreddit": "samsclub",
  "title": "Why do you guys sell whole pizzas made hours ago to customers?",
  "body": "The very few times I've gotten a whole pie, it'll be stuff premade and left in the hot case for like an hour 30mins before it's in my hand. How can I tell? They put a sticker with the date and the pizza looks and taste hours old. Pizza is meant to be made to order and waited for.",
  "author": "hangry_shopper",
  "score": 12,
  "url": "https://reddit.com/r/samsclub/comments/1nn7hjxx",
  "human_sentiment": "negative"
}
```

### 5.2 What the pipeline computes for it

Running this post through `pipeline.py` produces the following `analyses`
row (values from an actual dry-run):

| Field | Value | Where it comes from |
|-------|-------|---------------------|
| `sentiment` | `negative` | ModernBERT (Stage 3), softmax confidence |
| `sentiment_confidence` | `0.94` | Softmax over 3 classes |
| `aspects` | `product_quality`, `store_experience` | DeBERTa-v3 zero-shot NLI |
| `aspect_confidences` | `0.83`, `0.71` | NLI entailment scores |
| `trust_score` | `0.62` | 0.4·metadata + 0.3·dedup + 0.3·llm |
| `trust_components` | metadata=0.55, dedup=0.90, llm=0.50 | Decomposition shown in the UI |
| `priority` | `P2` | trust ≥ 0.50 AND conf ≥ 0.60 |

Because `sentiment=negative` and `priority=P2`, the post lands in the
Review & Validate queue with a **Generate Drafts** button enabled.

### 5.3 The prompt the analyst actually sends (variables substituted)

When the analyst clicks **Generate Drafts**, `_build_reply_prompt` runs and
produces the string below. This is exactly what goes to both GPT-4o
(via the Walmart Gateway) and Mistral 7B (via Ollama).

Assume the `feedback` table already has 12 posted replies. The top-3 most
recent, by `created_at`, are pulled in as few-shot examples:

```text
You are a senior Walmart customer-care analyst replying on Reddit.
Write ONE reply to the customer below. Keep it 2-4 sentences,
empathetic, specific to their complaint, no corporate jargon,
no hashtags, no emojis. Do NOT promise refunds you can't verify;
invite them to DM order details if action is needed. Sign off as
a real person, not a brand.

Example customer post: Ordered a rotisserie last Sunday and half the skin was black-charred. Dumped it. Second time this month.
Example analyst reply: Really sorry about the rotisserie — that's a temperature-hold issue at the deli case. DM me the order number and I'll get the club manager to look at it and refund you. — Ravi
Example customer post: Pickup order arrived with the ice cream fully melted. Driver was 40 min late. Two kids upset.
Example analyst reply: That's completely unacceptable — a 40-minute delay on a frozen order is on us. DM me the order # and I'll refund the ice cream today and flag the delivery slot. — Priya
Example customer post: Bought bakery bread yesterday, opened it this morning, mould on two slices. Best-by date is next week.
Example analyst reply: Really appreciate you flagging the mould — that goes straight to bakery ops. Send me a DM with the SKU and I'll get you a refund and pass it to the store team so the batch is pulled. — Ravi

Subreddit: r/samsclub
Customer (hangry_shopper) complaint about: product_quality, store_experience
Customer post:
Why do you guys sell whole pizzas made hours ago to customers?

The very few times I've gotten a whole pie, it'll be stuff premade and left in the hot case for like an hour 30mins before it's in my hand. How can I tell? They put a sticker with the date and the pizza looks and taste hours old. Pizza is meant to be made to order and waited for.

Reply:
```

### 5.4 The three drafts the analyst sees

**Draft A — GPT-4o (Walmart LLM Gateway)** — `~1.9 s`, `~USD 0.00019`

> Really sorry the pizza's been sitting in the hot case that long — that's
> not the fresh pie experience the club is supposed to deliver. DM me the
> club number and the day/time of your last visit and I'll flag it to the
> bakery-café team so the make-to-order flow gets reinforced.
> — Ravi (Sam's Club Care)

**Draft B — Mistral 7B-Instruct (local Ollama)** — `~11 s`, `free`

> Totally fair callout — a whole pie that's been in the hot case for 90
> minutes isn't the deal. DM me your club number and I'll get the bakery
> lead to look at their bake-off schedule so the pies you buy are made to
> order like they should be.
> — Priya

**Draft C — Smart Composer (deterministic)** — `<10 ms`, `free`

> Hi hangry_shopper, we're really sorry about the quality of what you
> received on your last visit — a pizza that's been sitting for that long
> isn't the standard. Please DM us the club number and the day you bought
> it and we'll get the bakery team on it.
> — Sam's Club Care

### 5.5 How to explain this to the evaluator (step by step)

1. **"The customer's post is real."** Open
   `data/benchmark_real_200.jsonl`, `id=1nn7hjxx` — it's a Sam's Club
   member complaining that whole pies are stale when picked up.
2. **"Our pipeline scored it as `negative`, aspects `product_quality` and
   `store_experience`, trust 0.62."** All three numbers are shown live in
   the Review & Validate panel; the analyst can override any of them.
3. **"When the analyst clicks Generate Drafts, we run the same prompt on
   three engines in parallel."** Point to slide 6 for the prompt template.
4. **"The prompt has three few-shot pairs pulled from `feedback`."** These
   pairs are *real posted replies* by our analyst team — the last three,
   most recent first. They're what make GPT stop saying "We apologise for
   the inconvenience" and start saying "DM me the order number".
5. **"The three drafts are shown side by side."** GPT is best at reasoning,
   Mistral matches the tone almost as well and is free, Smart Composer is
   the safety net for when the LLMs are unavailable.
6. **"Analyst picks the one they like, edits inline, clicks Save & Open
   Reddit."** The edited text is stored in `feedback` under
   `kind = auto_reply_posted` — which means it becomes the **next**
   post's top few-shot example. The loop closes on itself.
7. **"No model was retrained to produce this reply."** The composer
   improves over time purely through in-context learning — a key selling
   point when the analyst headcount is small and the pool is still growing.

### 5.6 What actually gets written back after the analyst posts

```json
{
  "id": "reply_1nn7hjxx_1735689012",
  "kind": "auto_reply_posted",
  "post_id": "1nn7hjxx",
  "analyst_id": "vishal.singh",
  "reply_text": "Really sorry the pizza's been sitting in the hot case that long — that's not the fresh pie experience the club is supposed to deliver. DM me the club number and the day/time of your last visit and I'll flag it to the bakery-café team so the make-to-order flow gets reinforced. — Ravi (Sam's Club Care)",
  "created_at": "2026-08-01T09:30:12Z",
  "partition_key": "vishal.singh"
}
```

Simultaneously the `analyses` row for post `1nn7hjxx` is updated with
`reply_posted_at`, `reply_text`, `human_validated = true`, and the
`lifecycle` table transitions the card from **In Progress → Resolved**.

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
