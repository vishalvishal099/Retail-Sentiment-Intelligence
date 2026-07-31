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
  image_caption?: string;
  image_url?: string;
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

export interface CompetitorTrendPoint {
  date: string;
  score: number | null;
  posts: number;
}
export interface CompetitorSeries {
  label: string;
  subreddits: string[];
  total_posts: number;
  points: CompetitorTrendPoint[];
}
export interface CompetitorTrend {
  days: string[];
  series: CompetitorSeries[];
  share_of_voice: Array<{ label: string; posts: number }>;
  walmart_subreddits: string[];
  top_competitors: string[];
}

export interface NotificationGroup {
  id: string;
  group_name: string;
  subreddits: string[];
  email_dl: string[];
  slack_channel?: string;
  enabled: boolean;
  priority_filter: string[];
  created_at: string;
  updated_at: string;
}

export interface NotificationLogEntry {
  id: number;
  group_id: string;
  group_name?: string;
  post_id: string;
  channel: string;
  status: string;
  error?: string | null;
  sent_at: string;
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
  /** Rows in raw_posts for the window (before analyzer runs). Always ≥ total_posts.
   *  The difference is `pending_analysis`. */
  fetched_count?: number;
  /** How many posts have been ingested but not yet analyzed in this window. */
  pending_analysis?: number;
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

export interface AspectHeatmap {
  aspects: string[];
  days: string[];
  cells: Array<{
    aspect: string;
    date: string;
    count: number;
    positive: number;
    negative: number;
    neutral: number;
    negative_ratio: number;
  }>;
  totals: Record<string, number>;
}

export interface Alert {
  id: string;
  type: string;
  severity: string;
  title?: string;
  message?: string;
  details: Record<string, unknown>;
  detected_at: string;
  time_window: string;
  state?: 'new' | 'acknowledged' | 'investigating' | 'resolved';
  state_updated_at?: string;
  state_updated_by?: string;
  state_history?: Array<{ from: string; to: string; at: string; by: string; note: string }>;
}

export interface AlertTimelineBucket {
  date: string;
  high: number;
  medium: number;
  low: number;
  total: number;
}

export interface AlertRule {
  enabled: boolean;
  description: string;
  sigma_threshold?: number;
  drop_threshold?: number;
  min_posts?: number;
  window_hours?: number;
}
export type AlertRules = Record<string, AlertRule>;

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
  validated_at?: string;
  validated_by?: string;
  close_reason?: string;
  model: string;
  reddit_url: string;
  created_timestamp: number;
  can_generate_reply: boolean;
  reply_posted_at: string | null;
  reply_text: string;
  follow_up_needed?: boolean;
}

export interface ReviewStats {
  total_feedback: number;
  total_reviewed: number;
  total_corrections: number;
  total_confirmations: number;
  total_replies_posted: number;
  agreement_rate: number;
  correction_matrix: Record<string, number>;
  daily_accuracy: Array<{ date: string; reviewed: number; confirmed: number; agreement_rate: number }>;
}

export interface FeedbackHistoryItem {
  id: string;
  post_id: string;
  analyst_id: string;
  original_sentiment: string;
  corrected_sentiment: string;
  changed: boolean;
  aspects_changed: string[];
  trust_override: number | null;
  notes: string;
  created_at: string;
}

export interface TrustExample {
  id: string;
  subreddit: string;
  author: string;
  title: string;
  text: string;
  trust_score: number;
  trust_components: { metadata?: number; dedup?: number; llm?: number };
  trust_flags: string[];
  score: number;
  url: string;
  created_timestamp: number;
}

export interface TrustStats {
  total: number;
  trusted: number;
  flagged: number;
  trust_rate: number;
  distribution: Record<string, number>;
  flag_breakdown: Record<string, number>;
  component_avg: { metadata: number | null; dedup: number | null; llm: number | null };
  low_trust_examples: TrustExample[];
  threshold: number;
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
  image_caption?: string;
  image_url?: string;
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
  last_status: 'success' | 'failed' | 'stopped' | null;
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
  /** Unix seconds. The `since` boundary passed to the fetcher on the next run.
   *  NOT the newest post we've seen — use `newest_post_utc` for that. */
  last_fetched_utc: number | null;
  last_fetched_id: string | null;
  /** ISO timestamp of the cursor row's last update. */
  updated_at: string | null;
  /** MAX(created_timestamp) actually in raw_posts for this sub — the true
   *  "last post seen". Can differ from last_fetched_utc when cursor drift
   *  occurs (a lookback-hours rewind that upstream returned 0 for). */
  newest_post_utc: number | null;
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

// ─── Data-freshness / gap-fill ────────────────────────────────────────────

export interface GapEntry {
  subreddit: string;
  post_count: number;
  newest_post_utc: number | null;
  cursor_utc: number | null;
  gap_hours: number | null;
  cursor_drift_hours: number;
  resume_from_utc: number;
  needs_fetch: boolean;
  /** 'fresh' | 'stale' | 'cursor_ahead_of_data' | 'never_fetched' */
  reason: string;
}

export interface GapReport {
  generated_at: string;
  gap_threshold_hours: number;
  totals: { subreddits: number; stale: number; drifted: number; fresh: number };
  /** Metadata about the last successful ingest — drives the "Catch up from …" button.
   *  Null if no successful ingest has ever run. */
  last_successful_ingest?: {
    id: string;
    started_at: string;
    finished_at: string;
    trigger: string;
    ingested: number;
    analyzed: number;
    hours_ago: number | null;
  } | null;
  subreddits: GapEntry[];
}

export interface FillGapsPlanEntry {
  subreddit: string;
  old_cursor_utc: number;
  new_cursor_utc: number;
  rewind_hours: number | null;
  reason: string;
}

export interface FillGapsResponse {
  started: boolean;
  reason?: string;
  detail?: string;
  dry_run?: boolean;
  plan?: {
    dry_run: boolean;
    since_utc: number | null;
    gap_threshold_hours: number;
    rewound_subreddits: number;
    plan: FillGapsPlanEntry[];
    gap_report: GapReport;
  };
  state?: PipelineStatus;
}

export interface AnalysisBacklog {
  raw_posts: number;
  analyses: number;
  pending: number;
}

export interface ImageFailureSample {
  post_id: string;
  subreddit: string;
  created_utc: number;
  title: string;
  url: string;
  status: string;   // fetched | deleted | throttled | forbidden | gone | too_large | not_image | server_error | connection_error | decode_error | client_error
  http_code: number | null;
  error: string;
  checked_at: string | null;
  permalink: string | null;
}

export interface ImageFailuresReport {
  total_checked: number;
  total_fetched: number;
  total_failed: number;
  totals_by_status: Record<string, number>;
  samples: ImageFailureSample[];
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
  getAspectHeatmap: (days = 7, topN = 6) =>
    fetchJSON<AspectHeatmap>(`/aspect-heatmap?days=${days}&top_n=${topN}`),
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
  getAlerts: (opts: { range?: string; severity?: string; type?: string; state?: string; limit?: number; live?: boolean } = {}) => {
    const qs = new URLSearchParams();
    if (opts.range) qs.set('range', opts.range);
    if (opts.severity) qs.set('severity', opts.severity);
    if (opts.type) qs.set('type', opts.type);
    if (opts.state) qs.set('state', opts.state);
    if (opts.limit) qs.set('limit', String(opts.limit));
    if (opts.live) qs.set('live', 'true');
    const query = qs.toString();
    return fetchJSON<{ alerts: Alert[]; count: number; total?: number; source?: string; range?: string }>(
      query ? `/alerts?${query}` : '/alerts',
    );
  },
  updateAlertState: (alertId: string, state: 'new' | 'acknowledged' | 'investigating' | 'resolved', note?: string) =>
    fetch(`${API_BASE}/alerts/${encodeURIComponent(alertId)}/state`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state, note }),
    }).then(r => r.json()) as Promise<{ status: string; alert?: Alert; reason?: string }>,
  getAlertsTimeline: (days = 30) =>
    fetchJSON<{ buckets: AlertTimelineBucket[] }>(`/alerts/timeline?days=${days}`),
  getAlertRules: () => fetchJSON<{ rules: AlertRules }>('/alerts/rules'),
  updateAlertRules: (rules: Partial<AlertRules>) =>
    fetch(`${API_BASE}/alerts/rules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rules }),
    }).then(r => r.json()) as Promise<{ status: string; rules: AlertRules }>,
  getReviewQueue: (limit = 50, sentiment?: string, range?: string, offset = 0) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (sentiment) params.set('sentiment', sentiment);
    if (range) params.set('range', range);
    return fetchJSON<{ queue: ReviewItem[]; total: number; offset: number; has_more: boolean }>(`/review?${params}`);
  },
  getReviewed: (limit = 50, sentiment?: string, range?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (sentiment) params.set('sentiment', sentiment);
    if (range) params.set('range', range);
    return fetchJSON<{ queue: ReviewItem[]; total: number }>(`/review/reviewed?${params}`);
  },
  closeReview: (postId: string, subreddit?: string, closeType?: 'no_reply' | 'issue_fixed' | 'reply_sent', actionNote?: string) =>
    fetch(`${API_BASE}/review/${encodeURIComponent(postId)}/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subreddit, close_type: closeType || 'no_reply', action_note: actionNote || '' }),
    }).then(r => r.json()) as Promise<{ status: string; post_id?: string; lifecycle_state?: string; reason?: string }>,
  confirmReview: (postId: string, subreddit?: string) =>
    fetch(`${API_BASE}/review/${encodeURIComponent(postId)}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subreddit }),
    }).then(r => r.json()) as Promise<{ status: string; post_id?: string }>,
  generateAction: (postId: string, subreddit?: string) =>
    fetch(`${API_BASE}/review/${encodeURIComponent(postId)}/generate-action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subreddit }),
    }).then(r => r.json()) as Promise<{ status: string; action: string }>,
  getReviewStats: () => fetchJSON<ReviewStats>('/review/stats'),
  getFeedbackHistory: (limit = 50) =>
    fetchJSON<{ items: FeedbackHistoryItem[]; total: number }>(`/review/feedback-history?limit=${limit}`),
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
      gateway_available?: boolean | null;
      ollama_available?: boolean | null;
      gateway_reason?: 'no_gateway_key' | 'no_consumer_id' | 'no_openai_key' | 'network_unreachable' | null;
      action_draft?: string;
    }>,
  draftAll: (postId: string, subreddit?: string) => {
    return fetch(`${API_BASE}/review/${encodeURIComponent(postId)}/draft-all`, {
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
      }>;
      reply?: string;
      action_draft?: string;
      action_model?: string;
      examples_used?: number;
      reason?: string;
      gateway_available?: boolean | null;
      gateway_reason?: string | null;
    }>;
  },
  getPosts: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') qs.set(k, String(v)); });
    // Tell the API the browser's timezone so "today" anchors on local midnight.
    if (!qs.has('tz_offset')) qs.set('tz_offset', String(new Date().getTimezoneOffset()));
    // `count` = returned page size, `total` = true match count in the window.
    return fetchJSON<{ posts: ExplorerPost[]; count: number; total: number }>(`/posts?${qs}`);
  },
  getTrustStats: (limit = 2000, examples = 15) =>
    fetchJSON<TrustStats>(`/trust-stats?limit=${limit}&examples=${examples}`),
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

  // ─── Data-freshness / gap-fill ─────────────────────────────────────────
  getPipelineGaps: (gapHours: number = 1) =>
    fetchJSON<GapReport>(`/pipeline/gaps?gap_hours=${gapHours}`),
  fillGaps: (opts: { since?: string; gapHours?: number; dryRun?: boolean } = {}) => {
    const qs = new URLSearchParams();
    if (opts.since) qs.set('since', opts.since);
    if (opts.gapHours !== undefined) qs.set('gap_hours', String(opts.gapHours));
    if (opts.dryRun) qs.set('dry_run', 'true');
    return fetch(`${API_BASE}/pipeline/fill-gaps?${qs}`, { method: 'POST' })
      .then(r => r.json()) as Promise<FillGapsResponse>;
  },
  getAnalysisBacklog: () => fetchJSON<AnalysisBacklog>('/pipeline/analysis-backlog'),
  analyzePending: (maxBatches?: number) => {
    const qs = maxBatches ? `?max_batches=${maxBatches}` : '';
    return fetch(`${API_BASE}/pipeline/analyze-pending${qs}`, { method: 'POST' })
      .then(r => r.json()) as Promise<{ started: boolean; reason?: string; state: PipelineStatus }>;
  },
  getImageFailures: (limit: number = 50) =>
    fetchJSON<ImageFailuresReport>(`/ingestion/image-failures?limit=${limit}`),

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
  getCompetitorTrend: (days = 14, topN = 4) =>
    fetchJSON<CompetitorTrend>(`/competitor-trend?days=${days}&top_n=${topN}`),

  // ─── Notification Groups ─────────────────────────────────────────────
  getNotificationConfig: () =>
    fetchJSON<{ sender_email: string; groups: NotificationGroup[] }>('/notifications/config'),
  getNotificationGroups: () =>
    fetchJSON<{ groups: NotificationGroup[] }>('/notifications/groups'),
  createNotificationGroup: (group: Partial<NotificationGroup>) =>
    fetch(`${API_BASE}/notifications/groups`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(group),
    }).then(r => r.json()) as Promise<{ ok: boolean; group: NotificationGroup }>,
  updateNotificationGroup: (groupId: string, group: Partial<NotificationGroup>) =>
    fetch(`${API_BASE}/notifications/groups/${groupId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(group),
    }).then(r => r.json()) as Promise<{ ok: boolean; group: NotificationGroup }>,
  deleteNotificationGroup: (groupId: string) =>
    fetch(`${API_BASE}/notifications/groups/${groupId}`, { method: 'DELETE' })
      .then(r => r.json()) as Promise<{ ok: boolean }>,
  testNotificationGroup: (groupId: string) =>
    fetch(`${API_BASE}/notifications/test/${groupId}`, { method: 'POST' })
      .then(r => r.json()) as Promise<{ ok: boolean; results: Record<string, any> }>,
  getNotificationLog: (limit = 50) =>
    fetchJSON<{ log: NotificationLogEntry[] }>(`/notifications/log?limit=${limit}`),
  getAvailableSubreddits: () =>
    fetchJSON<{ subreddits: Array<{ subreddit: string; group: string; macro_group: string }> }>('/notifications/subreddits'),
};
