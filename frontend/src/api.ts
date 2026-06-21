const API_BASE = '/api';

export type LifecycleState = 'new' | 'acknowledged' | 'reply_sent' | 'issue_fixed' | 'resolved';

export interface LifecycleHistoryEvent {
  at: string;
  from_state: string | null;
  to_state: string;
  by: string;
  note: string;
}

export interface LifecycleRow {
  post_id: string;
  subreddit: string;
  state: LifecycleState;
  priority: 'low' | 'medium' | 'high';
  title: string;
  top_aspect: string;
  sentiment_score: number;
  sentiment_confidence: number;
  created_at: string;
  updated_at: string;
  acknowledged_at?: string | null;
  reply_sent_at?: string | null;
  resolved_at?: string | null;
  reddit_posted_id?: string | null;
  reddit_url?: string;
  history: LifecycleHistoryEvent[];
}

export interface InsightsPainPoint {
  aspect: string;
  total: number;
  negative: number;
  positive: number;
  neutral: number;
  negative_ratio: number;
  examples: Array<{ subreddit: string; excerpt: string }>;
}

export interface InsightsRecommendation {
  aspect: string;
  priority: 'low' | 'medium' | 'high';
  headline: string;
  supporting_count: number;
  competitor_negative_ratio: number;
  walmart_negative_ratio: number;
}

export interface InsightsComparison {
  aspect: string;
  competitor_negative_ratio: number;
  walmart_negative_ratio: number;
  walmart_total: number;
  delta: number;
}

export interface InsightsPayload {
  window_days: number;
  since: string;
  analyses_count: number;
  pain_points: InsightsPainPoint[];
  walmart_comparison: InsightsComparison[];
  recommendations: InsightsRecommendation[];
  top_competitor_subreddits: Array<{ subreddit: string; post_count: number }>;
}

export interface InsightsResponse {
  available: boolean;
  kind?: string;
  id?: string;
  window_days?: number;
  generated_at?: string;
  payload?: InsightsPayload;
}

async function fetchJSON<T>(url: string): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`);
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export interface TrustGateInfo {
  formula: 'score_x_confidence' | 'legacy';
  tau: number | null;
  threshold: number;
}

export interface BrandHealthData {
  date: string;
  range: string;
  segment?: string | null;
  macro_segment?: 'walmart' | 'competitor' | null;
  days_requested?: number;
  days_with_data?: number;
  total_posts: number;
  trusted_posts: number;
  trust_gate?: TrustGateInfo;
  sentiment_distribution: { positive: number; negative: number; neutral: number };
  aspect_breakdown: Record<string, number>;
  subreddit_distribution: Record<string, number>;
  segment_distribution?: Record<string, number>;
  macro_segment_distribution?: Record<string, number>;
  trend_7d: Array<{ date: string; total_posts: number; sentiment_distribution: Record<string, number> }>;
  trend_granularity?: 'hour' | 'day';
  top_issues: Array<{ aspect: string; count: number; negative_ratio: number; severity_score: number }>;
  fallback_note?: string;
}

export interface SegmentInfo {
  slug: string;
  label: string;
}

export interface MacroSegmentInfo {
  slug: 'walmart' | 'competitor';
  label: string;
}
export type MacroSegment = 'walmart' | 'competitor';

export interface Alert {
  id: string;
  type: string;
  severity: string;
  message: string;
  details: Record<string, unknown>;
  detected_at: string;
  time_window: string;
}

export interface ReviewItem {
  id: string;
  post_id: string;
  text: string;
  title: string;
  author: string;
  score: number;
  sentiment: string;
  sentiment_confidence: number;
  trust_score: number;
  is_trusted: boolean;
  aspects: string[];
  needs_review: boolean;
  subreddit: string;
  analyzed_at: string;
  model: string;
  reddit_url: string;
  created_timestamp: number;
  can_generate_reply: boolean;
  reply_posted_at: string | null;
  reply_text: string;
}

export interface ReviewStats {
  total_feedback: number;
  total_corrections: number;
  total_replies_posted: number;
  correction_matrix: Record<string, number>;
}

export interface ExplorerPost {
  id: string;
  post_id: string;
  sentiment: string;
  sentiment_confidence: number;
  subreddit: string;
  trust_score: number;
  human_validated: boolean;
  title: string;
  text: string;
  author: string;
  score: number;
  created_timestamp: number;
  analyzed_at: string;
  aspects: unknown[];
  reddit_url: string;
}

/** Negative post ranked by trust × confidence for the Brand Health priority panel. */
export interface PriorityNegativePost {
  post_id: string;
  priority_tier: 'P1' | 'P2';
  /** trust_score × sentiment_confidence — used for sorting. */
  priority_score: number;
  sentiment_confidence: number;
  trust_score: number;
  subreddit: string;
  segment: string;
  macro_segment: string;
  title: string;
  text: string;
  aspects: unknown[];
  author: string;
  score: number;
  created_timestamp: number;
  reddit_url: string;
}

export interface PriorityNegativesResponse {
  posts: PriorityNegativePost[];
  count: number;
  tiers: { P1: number; P2: number };
  range?: string;
  limit?: number;
  error?: string;
}

export type DateRange =
  | '1h' | '2h' | '3h' | '6h' | '12h' | '24h'
  | 'today' | 'yesterday' | 'week' | 'month' | '60d' | '90d';

export interface AspectPost {
  id: string;
  post_id: string;
  sentiment: string;
  sentiment_confidence: number;
  subreddit: string;
  analyzed_at: string;
  trust_score: number;
  title: string;
  text: string;
  author: string;
  score: number;
  created_timestamp: number;
  reddit_url: string;
}

export interface PipelineStatus {
  running: boolean;
  last_run_id: string | null;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_status: 'success' | 'failed' | null;
  last_exit_code: number | null;
  last_trigger: 'manual' | 'scheduled' | 'backfill' | null;
  last_log_tail: string[];
  current_stage?: 'ingest' | 'vision' | 'trust' | 'analyze' | 'aggregate' | null;
  /** Params used for the current/most-recent run (e.g. {lookback_hours: 24}). */
  last_params?: { lookback_hours?: number } | null;
  /** Live per-stage counters. Keys: ingested, processed, vision_candidates,
   *  captioned, trusted, flagged, analyzed, alerts. Update as the cycle runs. */
  last_counters?: Record<string, number> | null;
  interval_minutes: number;
  scheduler_enabled: boolean;
  scheduler_started_at?: string | null;
  next_scheduled_run_at?: string | null;
  /** Cumulative DB-side totals, refreshed on every status call.
   *  These survive across runs (unlike `last_counters`, which resets). */
  totals?: {
    raw_posts: number;
    trusted_posts: number;
    analyzed_posts: number;
    ingested_today: number;
    ingested_24h: number;
  } | null;
  /** Live per-subreddit ingest progress for the in-flight run.
   *  null when no run is active. */
  ingest_progress?: IngestProgress | null;
}

/** Per-subreddit ingest timeline + counters, populated during a backfill. */
export interface SubredditProgress {
  subreddit: string;
  /** Unix seconds — start of the requested window. */
  since_utc: number | null;
  /** Unix seconds — end of the requested window (usually "now"). */
  until_utc: number | null;
  /** Oldest post created_utc reached so far in this run. */
  oldest_utc: number | null;
  newest_utc: number | null;
  page_size: number;
  total_fetched: number;
  /** 0-100, share of the time window covered. */
  coverage_pct: number;
  position: number | null;
  total_subs: number | null;
  fetch_limit: number | null;
  window_days: number | null;
  status: 'pending' | 'running' | 'ok' | 'failed';
  started_at: string;
  last_update: string;
  finished_at?: string;
}

export interface IngestProgress {
  started_at: string;
  subs_total: number;
  subs_done: number;
  /** 0-100, average coverage across all subs in scope. */
  overall_pct: number;
  /** Seconds remaining (null until ≥5% complete). */
  eta_seconds: number | null;
  subreddits: SubredditProgress[];
}

/**
 * Per-subreddit ingestion watermark + the most recent fetch window.
 * Returned by GET /api/pipeline/cursors.
 */
export interface PipelineCursor {
  subreddit: string;
  /** Unix seconds. Highest post created_utc we've successfully stored. */
  last_fetched_utc: number | null;
  last_fetched_id: string | null;
  /** ISO timestamp of the cursor row's last update. */
  updated_at: string | null;
  /** Most recent (run, subreddit) fetch window from cursor_history. */
  last_window: {
    since_utc: number;
    until_utc: number;
    fetched: number;
    status: 'ok' | 'failed' | string;
    recorded_at: string;
    overlap_seconds: number;
  } | null;
}

// ─── Pipeline page types ──────────────────────────────────────────────────

export interface FunnelStage {
  stage: string;
  count: number;
  drop_from_prev: number;
}

export interface FunnelData {
  range: string;
  segment: string | null;
  window_start: string;
  window_end: string;
  funnel: FunnelStage[];
  media_breakdown: {
    text_only: number;
    image_only: number;
    text_plus_image: number;
    video: number;
    link_only: number;
    images_total: number;
    captioned: number;
    pct_captioned: number;
    vision_failures?: {
      timeout: number;
      fetch_failed: number;
      ollama_unavailable: number;
      no_content: number;
      other: number;
    };
  };
  funnel_detail?: {
    not_english: number;
    too_short: number;
    not_yet_analyzed: number;
    low_trust: number;
    total_posts: number;
    trust_rate: number;
    analysis_coverage: number;
  };
}

export interface IngestionSource {
  subreddit: string;
  segment: string;
  macro_group?: 'walmart' | 'competitor';
  enabled: boolean;
  fetched: number;
  analyzed: number;
  pending: number;
  last_created_ts: number | null;
  last_fetched_utc: number | null;
  last_fetched_at: string | null;
  subscribers: number;
}

export interface SubredditRegistryEntry {
  subreddit: string;
  group: string;
  segment: string;
  macro_group?: 'walmart' | 'competitor';
  subscribers: number;
  enabled: boolean;
  subreddit_type: string;
}

export interface PipelineJob {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: 'running' | 'success' | 'failed' | string;
  trigger: 'manual' | 'scheduled' | 'backfill' | string;
  duration_ms: number | null;
  counters: Record<string, number | string | string[]>;
  params: Record<string, unknown>;
  error: string | null;
  log_tail: string[];
}

export const api = {
  getBrandHealth: (range: DateRange = 'today', segment?: string | null, macroSegment?: MacroSegment | null) => {
    const qs = new URLSearchParams({ range });
    if (segment) qs.set('segment', segment);
    if (macroSegment) qs.set('macro_segment', macroSegment);
    return fetchJSON<BrandHealthData>(`/brand-health?${qs.toString()}`);
  },
  getPriorityNegatives: (
    range: DateRange = 'today',
    limit = 20,
    segment?: string | null,
    macroSegment?: MacroSegment | null,
  ) => {
    const qs = new URLSearchParams({ range, limit: String(limit) });
    if (segment) qs.set('segment', segment);
    if (macroSegment) qs.set('macro_segment', macroSegment);
    return fetchJSON<PriorityNegativesResponse>(`/brand-health/priority-negatives?${qs.toString()}`);
  },
  getSegments: () => fetchJSON<{ segments: SegmentInfo[] }>(`/segments`),
  getMacroSegments: () => fetchJSON<{ macro_segments: MacroSegmentInfo[] }>(`/macro-segments`),
  getAspects: () => fetchJSON<{ aspects: string[]; breakdown: Record<string, unknown> }>('/aspects'),
  getAspectDetail: (aspect: string, days = 14, limit = 25, range?: DateRange, macroSegment?: MacroSegment | null) => {
    const qs = new URLSearchParams({ days: String(days), limit: String(limit) });
    if (range) qs.set('range', range);
    if (macroSegment) qs.set('macro_segment', macroSegment);
    return fetchJSON<{
      aspect: string;
      range?: string | null;
      window_start?: string | null;
      window_end?: string | null;
      trend: unknown[];
      posts: AspectPost[];
      limit: number;
      returned: number;
    }>(`/aspects/${encodeURIComponent(aspect)}?${qs.toString()}`);
  },
  getAlerts: () => fetchJSON<{ alerts: Alert[]; count: number }>('/alerts'),
  getReviewQueue: (limit = 20) => fetchJSON<{ queue: ReviewItem[]; total: number }>(`/review?limit=${limit}`),
  getReviewStats: () => fetchJSON<ReviewStats>('/review/stats'),
  submitReview: (postId: string, correction: Record<string, unknown>) =>
    fetch(`${API_BASE}/review/${postId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(correction),
    }).then(r => r.json()) as Promise<{ status: string; feedback_id: string; analysis_updated: boolean }>,
  postReply: (postId: string, replyText: string, subreddit?: string, postToReddit = false) =>
    fetch(`${API_BASE}/review/${postId}/reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ reply_text: replyText, subreddit, post_to_reddit: postToReddit }),
    }).then(r => r.json()) as Promise<{
      status: string;
      feedback_id?: string;
      reply_posted_at?: string;
      reason?: string;
      reddit?: {
        ok: boolean;
        dry_run?: boolean;
        posted_id?: string | null;
        thing_id?: string;
        error?: string;
        retry_after_seconds?: number;
      };
    }>,
  generateReply: (postId: string, subreddit?: string) =>
    fetch(`${API_BASE}/review/${postId}/draft-reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subreddit }),
    }).then(r => r.json()) as Promise<{
      status: string;
      drafts?: Array<{
        reply: string;
        model_used: string;
        source: 'llm' | 'template' | 'template_fallback' | 'smart-template';
        label?: string;
        quality_score?: number;
        candidates_tried?: number;
      }>;
      reply?: string;
      model_used?: string;
      source?: 'llm' | 'template' | 'template_fallback' | 'smart-template';
      examples_used?: number;
      reason?: string;
    }>,
  getPosts: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') qs.set(k, String(v)); });
    // Tell the API the browser's timezone so "today" anchors on local midnight.
    if (!qs.has('tz_offset')) qs.set('tz_offset', String(new Date().getTimezoneOffset()));
    return fetchJSON<{ posts: ExplorerPost[]; count: number }>(`/posts?${qs}`);
  },
  getTrustStats: () => fetchJSON<Record<string, unknown>>('/trust-stats'),
  getPipelineStatus: () => fetchJSON<PipelineStatus>('/pipeline/status'),
  runPipeline: (lookbackHours?: number) => {
    const qs = lookbackHours ? `?lookback_hours=${lookbackHours}` : '';
    return fetch(`${API_BASE}/pipeline/run${qs}`, { method: 'POST' }).then(r => r.json()) as Promise<{
      started: boolean;
      reason?: string;
      state: PipelineStatus;
    }>;
  },
  stopPipeline: () =>
    fetch(`${API_BASE}/pipeline/stop`, { method: 'POST' }).then(r => r.json()) as Promise<{
      stopped: boolean;
      reason?: string;
      state: PipelineStatus;
    }>,
  retryVision: () =>
    fetch(`${API_BASE}/pipeline/retry-vision`, { method: 'POST' }).then(r => r.json()) as Promise<{
      started: boolean;
      reason?: string;
      state: PipelineStatus;
    }>,
  getPipelineCursors: () =>
    fetchJSON<{
      cursors: PipelineCursor[];
      overlap_seconds: number;
      next_scheduled_run_at: string | null;
    }>('/pipeline/cursors'),

  // ─── Pipeline page ────────────────────────────────────────────────────
  getIngestionFunnel: (range: DateRange = 'week', segment?: string | null) => {
    const qs = new URLSearchParams({ range });
    if (segment) qs.set('segment', segment);
    return fetchJSON<FunnelData>(`/ingestion/funnel?${qs}`);
  },
  getIngestionSources: (range: DateRange = 'week') =>
    fetchJSON<{ range: string; sources: IngestionSource[]; total: number }>(
      `/ingestion/sources?range=${range}`,
    ),
  getSubredditRegistry: () =>
    fetchJSON<{ subreddits: SubredditRegistryEntry[]; total: number; enabled_count: number }>(
      '/ingestion/subreddits',
    ),
  toggleSubreddits: (changes: Record<string, boolean>) =>
    fetch(`${API_BASE}/ingestion/subreddits/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ changes }),
    }).then(r => r.json()) as Promise<{ updated: number; changes: [string, boolean][] }>,
  addSubreddit: (subreddit: string, group: string, enabled = true) =>
    fetch(`${API_BASE}/ingestion/subreddits/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subreddit, group, enabled }),
    }).then(r => r.json()) as Promise<{ added?: string; segment?: string; enabled?: boolean; error?: string }>,
  removeSubreddit: (subreddit: string) =>
    fetch(`${API_BASE}/ingestion/subreddits/remove`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subreddit }),
    }).then(r => r.json()) as Promise<{ removed: boolean; subreddit: string }>,
  triggerBackfill: (params: { from: string; to: string; subreddits?: string[] }) =>
    fetch(`${API_BASE}/ingestion/backfill`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }).then(r => r.json()) as Promise<{
      started: boolean;
      reason?: string;
      window?: { from: string; to: string; days: number };
      subreddits?: string[] | string;
    }>,
  flushAllData: (confirm: string) =>
    fetch(`${API_BASE}/admin/flush?confirm=${encodeURIComponent(confirm)}`, {
      method: 'POST',
    }).then(r => r.json()) as Promise<{
      flushed: boolean;
      reason?: string;
      deleted_tables?: Record<string, number>;
      deleted_cursors?: number;
      backup_path?: string | null;
    }>,
  getRecentJobs: (limit = 25, status?: string) => {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (status) qs.set('status', status);
    return fetchJSON<{ jobs: PipelineJob[]; total: number }>(`/jobs/recent?${qs}`);
  },
  getJobDetail: (jobId: string) =>
    fetchJSON<PipelineJob | { error: string; job_id?: string; detail?: string }>(`/jobs/${jobId}`),

  // ─── Reddit OAuth ─────────────────────────────────────────────────────
  authStatus: () =>
    fetch(`${API_BASE}/auth/reddit/status`, { credentials: 'include' }).then(r => r.json()) as Promise<{
      enabled: boolean;
      dry_run: boolean;
      logged_in: boolean;
      username: string;
      expires_at: number;
      client_configured: boolean;
    }>,
  authLogin: () =>
    fetch(`${API_BASE}/auth/reddit/login`, { credentials: 'include' }).then(r => r.json()) as Promise<{
      ok: boolean;
      authorize_url?: string;
      dry_run?: boolean;
      error?: string;
    }>,
  authLogout: () =>
    fetch(`${API_BASE}/auth/reddit/logout`, { method: 'POST', credentials: 'include' }).then(r => r.json()) as Promise<{
      ok: boolean;
      logged_out: boolean;
    }>,

  // ─── Post Lifecycle (Phase 4) ─────────────────────────────────────────
  getLifecycle: (state?: string) => {
    const qs = state ? `?state=${encodeURIComponent(state)}` : '';
    return fetchJSON<{
      states: string[];
      counts: Record<string, number>;
      rows: LifecycleRow[];
    }>(`/lifecycle${qs}`);
  },
  getLifecycleDetail: (postId: string) =>
    fetchJSON<{ lifecycle: LifecycleRow; analysis: any; raw: any }>(`/lifecycle/${postId}`),
  transitionLifecycle: (postId: string, toState: string, note?: string, by?: string) =>
    fetch(`${API_BASE}/lifecycle/${postId}/transition`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to_state: toState, note, by }),
    }).then(r => r.json()) as Promise<{ ok: boolean; lifecycle?: LifecycleRow; error?: string; allowed?: string[] }>,
  resolveLifecycle: (postId: string, note?: string, by?: string) =>
    fetch(`${API_BASE}/lifecycle/${postId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note, by }),
    }).then(r => r.json()) as Promise<{ ok: boolean; lifecycle?: LifecycleRow; error?: string }>,

  // ─── Competitor Insights (Phase 5) ───────────────────────────────────
  getInsightsLatest: (kind: string = 'competitor_daily') =>
    fetchJSON<InsightsResponse>(`/insights/latest?kind=${encodeURIComponent(kind)}`),
  getInsightsHistory: (limit = 20) =>
    fetchJSON<{ history: Array<{ id: string; kind: string; window_days: number; generated_at: string }> }>(`/insights/history?limit=${limit}`),
  generateInsights: (windowDays: number = 7) =>
    fetch(`${API_BASE}/insights/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ window_days: windowDays }),
    }).then(r => r.json()) as Promise<{ id: string; kind: string; generated_at: string; payload: InsightsPayload }>,
};
