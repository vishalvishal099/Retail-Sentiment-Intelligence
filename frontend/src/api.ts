const API_BASE = '/api';

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
  days_requested?: number;
  days_with_data?: number;
  total_posts: number;
  trusted_posts: number;
  trust_gate?: TrustGateInfo;
  sentiment_distribution: { positive: number; negative: number; neutral: number };
  aspect_breakdown: Record<string, number>;
  subreddit_distribution: Record<string, number>;
  segment_distribution?: Record<string, number>;
  trend_7d: Array<{ date: string; total_posts: number; sentiment_distribution: Record<string, number> }>;
  trend_granularity?: 'hour' | 'day';
  top_issues: Array<{ aspect: string; count: number; negative_ratio: number; severity_score: number }>;
  fallback_note?: string;
}

export interface SegmentInfo {
  slug: string;
  label: string;
}

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
  last_trigger: 'manual' | 'scheduled' | null;
  last_log_tail: string[];
  interval_minutes: number;
  scheduler_enabled: boolean;
  scheduler_started_at?: string | null;
  next_scheduled_run_at?: string | null;
}

export const api = {
  getBrandHealth: (range: DateRange = 'today', segment?: string | null) => {
    const qs = new URLSearchParams({ range });
    if (segment) qs.set('segment', segment);
    return fetchJSON<BrandHealthData>(`/brand-health?${qs.toString()}`);
  },
  getSegments: () => fetchJSON<{ segments: SegmentInfo[] }>(`/segments`),
  getAspects: () => fetchJSON<{ aspects: string[]; breakdown: Record<string, unknown> }>('/aspects'),
  getAspectDetail: (aspect: string, days = 14, limit = 25, range?: DateRange) => {
    const qs = new URLSearchParams({ days: String(days), limit: String(limit) });
    if (range) qs.set('range', range);
    return fetchJSON<{
      aspect: string;
      range?: string | null;
      window_start?: string | null;
      window_end?: string | null;
      trend: unknown[];
      posts: AspectPost[];
      limit: number;
      returned: number;
    }>(`/aspects/${aspect}?${qs.toString()}`);
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
  postReply: (postId: string, replyText: string, subreddit?: string) =>
    fetch(`${API_BASE}/review/${postId}/reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reply_text: replyText, subreddit }),
    }).then(r => r.json()) as Promise<{ status: string; feedback_id?: string; reply_posted_at?: string; reason?: string }>,
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
  runPipeline: () =>
    fetch(`${API_BASE}/pipeline/run`, { method: 'POST' }).then(r => r.json()) as Promise<{
      started: boolean;
      reason?: string;
      state: PipelineStatus;
    }>,
};
