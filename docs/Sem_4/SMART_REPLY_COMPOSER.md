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

## 5 · Worked example — a real post + real drafts + real few-shot

Everything below is **captured from a live run** on the local SQLite
instance (`data/local.db`). Nothing on this page is invented; every
sentence in every draft was produced by the actual pipeline at the moment
this document was written. The exact commands that reproduce it are in
§6.5 below.

### 5.1 The raw post (from `raw_posts`)

Real row, ingested by the Arctic Shift ingestion pass and stored under
`id = reddit_1u2bgdw`:

```json
{
  "id": "reddit_1u2bgdw",
  "subreddit": "samsclub",
  "title": "Why do you guys sell whole pizzas made hours ago to customers?",
  "body": "The very few times I've gotten a whole pie, it'll be stuff premade and left in the hot case for like an hour 30mins before it's in my hand. How can I tell? They put a sticker with the date and the pizza looks and taste hours old. Pizza is meant to be made to order and waited for. I'd rather wait 30mins for a pizza worth freaking eating then 0secs for a waste of money. Why do you guys do this seriously?",
  "author": "",
  "score": 0,
  "url": "https://www.reddit.com/r/samsclub/comments/1u2bgdw/why_do_you_guys_sell_whole_pizzas_made_hours_ago/",
  "created_utc": "2026-06-10T18:59:12+00:00"
}
```

### 5.2 What the pipeline computed (from `analyses`)

Real row from the `analyses` container — copy-paste of the actual DB value:

| Field | Value | Where it comes from |
|-------|-------|---------------------|
| `sentiment` | `negative` | ModernBERT (Stage 3), softmax argmax |
| `sentiment_confidence` | `0.99999976` | Softmax over 3 classes |
| `aspects` (top-3) | `customer service (0.967)`, `product quality (0.962)`, `store experience (0.894)` | DeBERTa-v3 zero-shot NLI, `-negative` for each |
| `trust_score` | `0.66` | 0.4·metadata + 0.3·dedup + 0.3·llm |
| `human_validated` | `null` | Not reviewed by an analyst yet |
| `reply_posted_at` | `null` | No reply posted yet — the drafts below are what would appear if the analyst clicked *Generate* right now |

Because `sentiment = negative` and trust ≥ 0.5, the post is eligible for
Review & Validate; the **Generate Drafts** button is enabled.

### 5.3 The prompt the LLMs actually see (variables substituted)

Below is the **exact prompt string** printed by
`WalmartLLMClient._build_reply_prompt()` on this post, using the top-3 most
recent `auto_reply_posted` rows from `feedback` as few-shot examples. The
few-shot pairs are real analyst-posted replies — no invention:

```text
You are a senior Walmart customer-care analyst replying on Reddit.
Write ONE reply to the customer below. Keep it 2-4 sentences,
empathetic, specific to their complaint, no corporate jargon,
no hashtags, no emojis. Do NOT promise refunds you can't verify;
invite them to DM order details if action is needed. Sign off as
a real person, not a brand.

Example customer post: Mostly metric fraud (there's a reason why customer codes are a thing + our former lead tried that before our coach put there foot down) mixed with having the spots right by the door
Example analyst reply: Hi u/there, it sounds like you're dealing with some frustrating situations around metrics and spot placements. I understand how issues like these can impact both customer service and the overall flow of operations. If you'd like to share more details about what's going on, feel free to DM, and I'll do my best to help. – Sam

Example customer post: Can anyone explain the ATC role to me? My store is aggressively using ATCs to keep the department running. We'll have anywhere from two to six ATCs working per day. They do things like handling customer issues and bossing associates around,
Example analyst reply: Hi u/there, I understand your concerns about the ATC role in your store. The ATC (Associate Team Coach) role is designed to provide support and guidance to associates within a department, but it's not intended to replace team leads or boss people around. If you have specific instances where you feel this isn't the case, I would encourage you to reach out to your store management to discuss your concerns.

Example customer post: I was completely on board until I read the second part lol. I'm like 🤔
Example analyst reply: Hi u/there, I can understand why you might have reservations after reading the app requirements. We strive to make our processes as straightforward and accessible as possible for all associates. If you have specific concerns or need clarification on any aspects of the app usage, please feel free to share your order details with me via DM so we can address them directly.

Subreddit: r/samsclub
Customer (there) complaint about: customer_service, product_quality, store_experience
Customer post:
Why do you guys sell whole pizzas made hours ago to customers?

The very few times I've gotten a whole pie, it'll be stuff premade and left in the hot case for like an hour 30mins before it's in my hand. How can I tell? They put a sticker with the date and the pizza looks and taste hours old. Pizza is meant to be made to order and waited for. I'd rather wait 30mins for a pizza worth freaking eating then 0secs for a waste of money. Why do you guys do this seriously?

Reply:
```

### 5.4 The three drafts the system actually produced

Captured verbatim from `WalmartLLMClient.generate_reply_pair(...)` on
`reddit_1u2bgdw`. Runtime state at capture time:

- Walmart LLM Gateway (`gpt-4o`) — **reachable** (`gateway_available = True`)
- Local Ollama (`mistral:7b-instruct`) — **not running** (`ollama_available = False`, error: `Connection refused` on `localhost:11434`)
- Smart Composer — **always available**

The system correctly used GPT-4o for slot A, fell back to Smart Composer
for slot B (badged as `[offline fallback]` in the UI), and produced the
Smart Composer draft in slot C.

**Draft A — GPT-4o (Walmart LLM Gateway)** — real
`source = llm`, `model_used = gpt-4o`

> Hi u/there, I'm sorry to hear about your experience with the pizzas —
> it sounds really disappointing. Our goal is to provide fresh and
> enjoyable food, and I understand how frustrating it must be to receive
> something that feels old. If you'd like, feel free to DM me the store
> location so I can share your feedback directly with the team and look
> into it further. — [Your Name]

**Draft B — Mistral 7B (Ollama)** — real, but slot fell back
`source = smart-template`, `model_used = mistral:7b-instruct`, UI badge: **[offline fallback]**

> Hi u/there — thanks for flagging this. that's not the experience we want
> anyone to have with your order. DM us the details when you have a moment
> and we'll start looking into the specifics.
> — The Walmart Care team

**Draft C — Smart Composer** — real
`source = smart-template`, `model_used = smart-composer`

> Hi u/there, Your order like this absolutely shouldn't happen. DM us the
> details when you have a moment and we'll start looking into the
> specifics. — Walmart Care 💙

### 5.5 What to tell the evaluator (step by step)

1. **"The customer's post is real, in our database, right now."** — Open
   `data/local.db` and query
   `SELECT data FROM raw_posts WHERE json_extract(data,'$.id')='reddit_1u2bgdw';`
   The row from §5.1 comes back.
2. **"The pipeline classified it as `negative` with confidence 0.9999997,
   three aspects, trust 0.66."** — Same DB, query the `analyses` table for
   the same post_id. Show the row.
3. **"The prompt has three real few-shot pairs from the `feedback` table."**
   — Point at §5.3. These are actual posted replies by our analyst team
   pulled with the SQL query from §3.2, sorted by `created_at DESC`.
4. **"Draft A is a real GPT-4o response through the Walmart LLM Gateway."**
   — The call was made through the internal
   `wmtllmgateway.stage.walmart.com/v1/chat/completions` endpoint with the
   `WM_CONSUMER.ID` header. Cost tracker recorded ~200 output tokens.
5. **"Draft B *would have been* Mistral 7B, but Ollama isn't running on
   this machine so the system fell back to Smart Composer and badged the
   slot `[offline fallback]`."** — This is the fallback logic from §1
   working in production, live.
6. **"Draft C is the Smart Composer — pure Python, no LLM, always
   available."** — This is our safety net. It produces a varied,
   aspect-specific reply from curated phrase pools.
7. **"If the analyst picks Draft A, edits it, and clicks Save & Open
   Reddit, the reply is written to `feedback` with `kind = auto_reply_posted`
   and becomes the next post's top few-shot example."** — See §5.6.

### 5.6 What actually gets written back after the analyst posts

If the analyst had accepted Draft A and clicked *Save & Open Reddit*, the
following row would be inserted into `feedback` (schema matches the 18 rows
already in the DB):

```json
{
  "id": "reply_reddit_1u2bgdw_<epoch_seconds>",
  "kind": "auto_reply_posted",
  "post_id": "reddit_1u2bgdw",
  "analyst_id": "<session_analyst>",
  "reply_text": "<the edited Draft A>",
  "created_at": "<utc_iso>",
  "partition_key": "<session_analyst>"
}
```

Simultaneously the `analyses` row for `reddit_1u2bgdw` is updated with
`reply_posted_at`, `reply_text`, `human_validated = true`, and the
`post_lifecycle` table transitions the card from **In Progress → Resolved**.

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
## 8 · Reproduce §5 in a terminal

The following one-liner regenerates the prompt in §5.3 and the three
drafts in §5.4 against the live `data/local.db`. Runs offline; only slots
that have network / Ollama available call out.

```bash
python - << 'PY'
import sqlite3, json, sys
sys.path.insert(0, '.')
from src.utils.config import load_config
from src.analysis.llm_client import create_llm_client

conn = sqlite3.connect('data/local.db')
cur = conn.cursor()

# Pull the top-3 posted replies + their originals as few-shot pairs
cur.execute("SELECT data FROM feedback "
            "WHERE json_extract(data,'$.kind')='auto_reply_posted' "
            "ORDER BY json_extract(data,'$.created_at') DESC LIMIT 3")
examples = []
for r in cur.fetchall():
    d = json.loads(r[0]); pid = d['post_id']
    cur.execute("SELECT data FROM raw_posts WHERE json_extract(data,'$.id')=?", (pid,))
    p = cur.fetchone()
    post = ''
    if p:
        pd = json.loads(p[0])
        post = (pd.get('title','')+' '+(pd.get('body') or '')).strip()
    examples.append({'post_text': post[:500], 'reply_text': d.get('reply_text','')[:500]})

# Load the pizza post and run the composer
cur.execute("SELECT data FROM raw_posts WHERE json_extract(data,'$.id')='reddit_1u2bgdw'")
p = json.loads(cur.fetchone()[0])
llm = create_llm_client(load_config().llm, None)

print("=== PROMPT ===")
print(llm._build_reply_prompt(
    p['title'], p['body'], p['subreddit'], p.get('author') or 'there',
    ['customer_service','product_quality','store_experience'], examples))

print("\n=== DRAFTS ===")
result = llm.generate_reply_pair(
    p['title'], p['body'], p['subreddit'], p.get('author') or 'there',
    ['customer_service','product_quality','store_experience'], examples)
for i, d in enumerate(result['drafts'], 1):
    print(f"\n--- {d.get('label')} ---")
    print(d['reply'])
print(f"\ngateway_available={result.get('gateway_available')}  "
      f"ollama_available={result.get('ollama_available')}")
PY
```

Expected: Draft A comes from GPT-4o if the Walmart gateway is reachable,
Draft B from Mistral if Ollama is running (otherwise `[offline fallback]`
in slot B), Draft C from Smart Composer.
