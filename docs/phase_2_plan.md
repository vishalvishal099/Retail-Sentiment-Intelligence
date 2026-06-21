# Phase 2 Plan: Post-Vision-Fix Enhancements (6 Features)

> **Created:** 2026-06-12  
> **Status:** Draft — open for additions  
> **Prerequisite:** Vision/image processing pipeline fix (completed)

---

## TL;DR

After the image processing fix, flush data and re-backfill 90 days with vision enabled. Segment sources into Walmart vs Competitors. Implement real Reddit reply posting via OAuth user session. Add a Post Lifecycle page with Slack notifications and state tracking (New → Acknowledged → Reply Sent → Issue Fixed → Resolved). Generate daily + on-demand competitive insights from non-Walmart posts. Recommend additional improvements.

---

## Phase 1: Data Flush & 90-Day Re-Backfill

### Goal
Clean slate with properly vision-processed data for full 90-day window.

### Steps
1. Add `POST /api/admin/flush` endpoint — truncates raw_posts, analyses, aggregates, alerts, feedback tables; resets all cursors
2. Add flush button to Pipeline.tsx (with confirmation modal — "This will delete ALL data. Are you sure?")
3. After flush, trigger full 90-day backfill (existing `POST /api/ingestion/backfill` with all enabled subs)
4. Frontend dropdown already supports 90d — **no change needed** (RANGE_OPTIONS already includes '90d')

### Files to modify
- `src/dashboard/api.py` — new `/api/admin/flush` endpoint
- `src/storage/store.py` — `flush_all()` method + cursor reset
- `src/storage/cursor.py` — `reset_all_cursors()` method
- `frontend/src/pages/Pipeline.tsx` — flush button + confirmation
- `frontend/src/api.ts` — `flushData()` method

### Acceptance Criteria
- [ ] After flush: all tables empty, all cursors reset to 0
- [ ] After backfill: 90 days of data present with vision captions on image posts
- [ ] `SELECT COUNT(*) FROM raw_posts` shows fresh data
- [ ] No stale/corrupt data from pre-fix pipeline

---

## Phase 2: Walmart-Focused Source Segmentation

### Goal
Separate Walmart-owned subreddits from competitor/general retail subreddits so analysis can be focused and comparative.

### Macro Groups

| Group | Subreddits |
|-------|-----------|
| **walmart** | walmart, WalmartEmployees, samsclub, OGPBackroom, WalmartPlus, Sparkdriver, WalmartSparkDrivers, walmartogp, walmart_RX, WalmartCanada, Sams_Club |
| **competitor** | Costco, Target, doordash_drivers, AmazonFlexDrivers, instacart, AmazonPrime, Flipkart, TalesFromRetail, Frugal, MaliciousCompliance, ecommerce, deals, Coupons, CustomerService |

### Steps
1. Add `macro_group` column to `data/subreddits_clean.csv` — values: `walmart` or `competitor`
2. Update `src/utils/segments.py` — add `macro_segment_for(subreddit)` returning "walmart"|"competitor"
3. Update `src/ingestion/subreddit_registry.py` — read/write macro_group in dataclass + CSV I/O
4. Update aggregator to compute separate aggregates per macro_group
5. Update dashboard API to accept `macro_segment` filter param on brand-health + aspects endpoints
6. Update BrandHealth.tsx — add Walmart/Competitor toggle above existing segment dropdown

### Files to modify
- `data/subreddits_clean.csv` — new column
- `src/utils/segments.py` — `macro_segment_for()`, `MACRO_GROUPS` dict
- `src/ingestion/subreddit_registry.py` — dataclass + CSV I/O
- `src/aggregation/aggregator.py` — group-aware aggregation
- `src/dashboard/api.py` — filter params
- `frontend/src/pages/BrandHealth.tsx` — macro-segment toggle
- `frontend/src/api.ts` — pass macro_segment param

### Acceptance Criteria
- [ ] `/api/brand-health?macro_segment=walmart` returns only Walmart data
- [ ] `/api/brand-health?macro_segment=competitor` returns only competitor data
- [ ] UI toggle switches views cleanly
- [ ] Aggregates are computed per group

---

## Phase 3: Reddit Reply Posting via OAuth Session

### Approach
User logs in via Reddit OAuth (no bot credentials needed). If logged in → post reply via their session. If not → prompt login. Includes dry-run mode for testing.

### Steps
1. **Reddit OAuth flow:**
   - `src/reddit/oauth.py` — OAuth2 authorization_code flow (redirect to Reddit login → get access_token + refresh_token)
   - `GET /api/auth/reddit/login` → redirects to Reddit consent page
   - `GET /api/auth/reddit/callback` → exchanges code for token, stores in server-side session
   - `GET /api/auth/reddit/status` → returns `{logged_in: bool, username: str}`
   - `POST /api/auth/reddit/logout` → clears session

2. **Reply posting service:**
   - `src/reddit/poster.py` — `post_reply(post_id, reply_text, access_token)` using Reddit API
   - Rate limiting: max 1 reply per 10 minutes (Reddit's spam filter)
   - Dry-run mode: if `reddit_oauth.dry_run: true` in config → log intent + return mock success

3. **Integration:**
   - Update `/api/review/{post_id}/reply` → after saving to feedback, call `poster.post_reply()` if session active
   - Frontend: Reddit login button in header/nav, status indicator
   - ReviewQueue "Post Reply" button becomes real when logged in

4. **Config addition to `pipeline_config.yaml`:**
   ```yaml
   reddit_oauth:
     client_id: ""
     client_secret: ""
     redirect_uri: "http://localhost:8000/api/auth/reddit/callback"
     dry_run: true  # set false when credentials ready
   ```

### Files to create
- `src/reddit/__init__.py`
- `src/reddit/oauth.py`
- `src/reddit/poster.py`

### Files to modify
- `src/dashboard/api.py` — auth endpoints + update reply endpoint
- `config/pipeline_config.yaml` — reddit_oauth section
- `frontend/src/components/Layout.tsx` — Reddit login button + status
- `frontend/src/pages/ReviewQueue.tsx` — real post behavior
- `frontend/src/api.ts` — auth methods

### Acceptance Criteria
- [ ] OAuth login flow works (redirect → consent → callback → token stored)
- [ ] Dry-run mode logs reply without posting
- [ ] When logged in, reply actually appears on Reddit (test on r/test)
- [ ] Rate limiting enforced (1 per 10 min)
- [ ] Graceful fallback if session expired

---

## Phase 4: Post Lifecycle Page (New Page)

### States
```
New → Acknowledged → Reply Sent → Issue Fixed → Resolved
```
Each transition is timestamped and attributed to a team member.

### Steps

1. **New DB table `post_lifecycle`:**
   ```sql
   CREATE TABLE post_lifecycle (
     id TEXT PRIMARY KEY,
     post_id TEXT UNIQUE,
     subreddit TEXT,
     state TEXT DEFAULT 'new',  -- new|acknowledged|reply_sent|issue_fixed|resolved
     assigned_to TEXT,
     slack_notified_at TEXT,
     acknowledged_at TEXT,
     reply_sent_at TEXT,
     reply_text TEXT,
     issue_fixed_at TEXT,
     resolved_at TEXT,
     resolution_note TEXT,
     created_at TEXT,
     updated_at TEXT
   );
   ```

2. **Slack notification service:**
   - `src/notifications/slack.py` — sends webhook message before reply
   - Configurable webhook URL + channel in pipeline_config.yaml
   - Message format: "🚨 Negative post requires attention: [title] in r/{sub} — Assigned to {team}"
   - Dummy webhook for dev: logs to console instead of HTTP call

3. **Backend endpoints:**
   - `GET /api/lifecycle` — list posts with lifecycle state, filterable by state
   - `GET /api/lifecycle/{post_id}` — full timeline for one post
   - `POST /api/lifecycle/{post_id}/transition` — advance state (body: `{to_state, note, assigned_to}`)
   - `POST /api/lifecycle/{post_id}/resolve` — mark fixed + post follow-up reply ("This issue has been resolved")

4. **Auto-entry:**
   - When pipeline flags a post as negative with high confidence → auto-insert into `post_lifecycle` with state=`new`
   - Fire Slack notification immediately

5. **Frontend — New page `PostLifecycle.tsx`:**
   - Kanban-style columns: New | Acknowledged | Reply Sent | Issue Fixed | Resolved
   - Cards show: post title, subreddit, aspect, time in current state
   - Click card → detail panel: full post text, analysis, reply draft, state history timeline
   - Transition buttons: "Acknowledge" → "Send Reply" → "Mark Fixed" → "Resolve"
   - "Mark Fixed" triggers follow-up reply: "Hi! We wanted to let you know this issue has been addressed. [resolution_note]"

6. **Config addition:**
   ```yaml
   notifications:
     slack:
       enabled: true
       webhook_url: "https://hooks.slack.com/services/DUMMY/WEBHOOK/URL"
       channel: "#walmart-sentiment-alerts"
     auto_lifecycle: true  # auto-create lifecycle entries for negative posts
   ```

### Files to create
- `src/notifications/__init__.py`
- `src/notifications/slack.py`
- `frontend/src/pages/PostLifecycle.tsx`

### Files to modify
- `src/storage/store.py` — post_lifecycle table + CRUD methods
- `src/dashboard/api.py` — lifecycle endpoints
- `src/pipeline.py` — auto-insert negative posts into lifecycle
- `frontend/src/api.ts` — lifecycle API methods
- `frontend/src/App.tsx` — new route `/lifecycle`
- `frontend/src/components/Layout.tsx` — nav link "Post Lifecycle"
- `config/pipeline_config.yaml` — notifications section

### Acceptance Criteria
- [ ] Negative posts auto-enter lifecycle with state "new"
- [ ] Slack webhook fires on new entry (or logs in dry-run)
- [ ] State transitions work: New → Acknowledged → Reply Sent → Issue Fixed → Resolved
- [ ] Each transition records timestamp + actor
- [ ] "Resolve" posts follow-up reply on Reddit
- [ ] Kanban UI renders correctly with drag or button transitions

---

## Phase 5: Competitor Learnings & Insights

### Approach
LLM analyzes non-Walmart posts daily (batch) + on-demand (button click). Generates: top pain points at competitors, what Walmart can learn, actionable suggestions.

### Steps

1. **New LLM prompt** in `src/analysis/prompts.py`:
   - `COMPETITOR_INSIGHTS_PROMPT` — takes batch of negative competitor posts → outputs structured JSON:
     ```json
     {
       "competitor_pain_points": [
         {"competitor": "Costco", "issue": "Long checkout lines on weekends", "frequency": 12}
       ],
       "walmart_learnings": [
         "Costco members complain about checkout — Walmart's self-checkout advantage could be marketed"
       ],
       "recommendations": [
         {"priority": "high", "action": "Expand self-checkout messaging", "rationale": "Competitor weakness = our strength"}
       ],
       "generated_at": "2026-06-12T10:00:00Z"
     }
     ```

2. **New module `src/analysis/competitor_insights.py`:**
   - `generate_daily_insights()` — fetch yesterday's competitor negative posts → LLM summarize
   - `generate_on_demand_insights(days=7)` — last N days, triggered by button
   - Store results in new `insights` table

3. **Scheduler integration:** Run daily after aggregation step in `scripts/scheduler.py`

4. **Backend endpoints:**
   - `GET /api/insights/latest` — most recent daily insight
   - `GET /api/insights/history` — last 30 daily insights
   - `POST /api/insights/generate` — trigger on-demand generation

5. **Frontend — New page `CompetitorInsights.tsx`:**
   - "Competitor Learnings" header with last-generated timestamp
   - Pain points table: competitor name, issue description, frequency count
   - "What Walmart Can Learn" — bullet list of actionable learnings
   - Recommendations with priority badges (High/Medium/Low)
   - "Regenerate Now" button for on-demand generation

### Files to create
- `src/analysis/competitor_insights.py`
- `frontend/src/pages/CompetitorInsights.tsx`

### Files to modify
- `src/analysis/prompts.py` — new COMPETITOR_INSIGHTS_PROMPT
- `src/storage/store.py` — insights table schema + CRUD
- `src/dashboard/api.py` — insights endpoints
- `scripts/scheduler.py` — daily insights job
- `frontend/src/api.ts` — insights API methods
- `frontend/src/App.tsx` — new route `/insights`
- `frontend/src/components/Layout.tsx` — nav link "Competitor Insights"

### Acceptance Criteria
- [ ] Daily insights generated automatically after aggregation
- [ ] On-demand generation works via button
- [ ] JSON output is structured and parseable
- [ ] UI renders pain points, learnings, recommendations correctly
- [ ] Historical insights accessible (last 30 days)

---

## Phase 6: Additional Recommendations

### Add
1. **Sentiment trend alerts per competitor** — notify when a competitor's negative ratio spikes (opportunity for Walmart to capitalize)
2. **Response time SLA tracking** — measure time from "New" to "Reply Sent" in lifecycle; show average + SLA breach alerts
3. **Reply effectiveness scoring** — track if post author responds positively after our reply (upvote, "thanks" reply detection)
4. **Export/reporting** — weekly PDF report: Walmart health + competitor insights + lifecycle stats (for leadership)
5. **Auto-escalation** — if a post stays in "New" > 4 hours, re-notify Slack + escalate to manager channel

### Remove/Simplify
1. **Remove separate Review Queue page** — fold its functionality into the Post Lifecycle page (lifecycle is a superset of review)
2. **Deprecate smart-template replies** — once LLM replies are working well with few-shot learning, templates add noise
3. **Remove "60d" from range dropdown** — redundant when 30d + 90d exist

---

## Execution Order & Dependencies

```
Phase 1 (flush + backfill)  → BLOCKS everything else (need clean data first)
Phase 2 (segmentation)      ─┐
Phase 3 (Reddit OAuth)       ├─ can run in parallel after Phase 1
Phase 4 (lifecycle)          ─┘ depends on Phase 3 for "Send Reply" state
Phase 5 (competitor insights) → depends on Phase 2 (macro_group segmentation)
Phase 6 (extras)              → after Phases 4+5 are stable
```

---

## Verification Checklist

1. **After Phase 1:** `SELECT COUNT(*) FROM raw_posts` shows fresh 90-day data; vision captions present on image posts
2. **After Phase 2:** `/api/brand-health?macro_segment=walmart` vs `?macro_segment=competitor` return different datasets
3. **After Phase 3:** Post a test reply on r/test subreddit via OAuth session; verify it appears
4. **After Phase 4:** Create a lifecycle entry, transition through all states, verify Slack webhook fires at each notification point
5. **After Phase 5:** Generate competitor insights, verify JSON structure and actionable recommendations render in UI
6. **Integration E2E:** Negative post ingested → lifecycle created → Slack notified → team acknowledges → reply posted → issue fixed → follow-up posted → resolved

---

## Open Questions / TODO

<!-- Add items here as you refine the plan -->
- [ ] _Add more details here..._
