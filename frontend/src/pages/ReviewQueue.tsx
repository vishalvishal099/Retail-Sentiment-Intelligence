import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { api, ReviewItem, ReviewStats, DateRange, FeedbackHistoryItem } from '../api';
import Card from '../components/Card';
import Button from '../components/Button';

const ASPECT_OPTIONS_CUSTOMER = [
  'store_experience',
  'online_app',
  'delivery_pickup',
  'product_quality',
  'returns',
  'customer_support',
  'pricing',
] as const;

const ASPECT_OPTIONS_EMPLOYEE = [
  'workforce_hr',
  'pay_benefits',
  'management',
  'safety_policy',
  'workload',
] as const;

// Combined list kept for reference
const _ASPECT_OPTIONS_ALL = [...ASPECT_OPTIONS_CUSTOMER, ...ASPECT_OPTIONS_EMPLOYEE] as const;
void _ASPECT_OPTIONS_ALL;

const SENTIMENTS = ['', 'positive', 'negative', 'neutral'] as const;
const RANGE_OPTIONS: { value: DateRange | ''; label: string }[] = [
  { value: '', label: 'All time' },
  { value: '1h', label: 'Last 1h' },
  { value: '6h', label: 'Last 6h' },
  { value: '12h', label: 'Last 12h' },
  { value: '24h', label: 'Last 24h' },
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'week', label: 'Last 7 Days' },
  { value: 'month', label: 'Last 30 Days' },
  { value: '90d', label: 'Last 90 Days' },
];

export default function ReviewQueue() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSentiment = searchParams.get('sentiment') || '';
  const urlRange = searchParams.get('range') || '';
  const urlMacro = searchParams.get('macro') || '';
  const [tab, setTab] = useState<'pending' | 'reviewed'>('pending');
  const [sentiment, setSentiment] = useState(urlSentiment);
  const [range, setRange] = useState(urlRange);
  const [macroSegment, setMacroSegment] = useState(urlMacro);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [reviewedItems, setReviewedItems] = useState<ReviewItem[]>([]);
  const [totalPending, setTotalPending] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reviewedLoading, setReviewedLoading] = useState(false);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const load = (s?: string, r?: string, m?: string) => {
    const sen = s ?? urlSentiment;
    const ran = r ?? urlRange;
    const mac = m ?? urlMacro;
    setLoading(true);
    Promise.all([
      api.getReviewQueue(50, sen || undefined, ran || undefined, 0, mac || undefined),
      api.getReviewStats().catch(() => null),
      api.getReviewed(50, sen || undefined, ran || undefined, mac || undefined),
    ])
      .then(([q, st, rv]) => {
        setItems(q.queue);
        setTotalPending(q.total);
        setHasMore(q.has_more);
        setReviewedItems(rv.queue);
        if (st) setStats(st);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  const loadMore = () => {
    setLoadingMore(true);
    api.getReviewQueue(50, sentiment || undefined, range || undefined, items.length, macroSegment || undefined)
      .then(q => {
        setItems(prev => [...prev, ...q.queue]);
        setTotalPending(q.total);
        setHasMore(q.has_more);
      })
      .catch(console.error)
      .finally(() => setLoadingMore(false));
  };

  const loadReviewed = (s?: string, r?: string, m?: string) => {
    setReviewedLoading(true);
    api.getReviewed(50, s || undefined, r || undefined, m || undefined)
      .then(r => setReviewedItems(r.queue))
      .catch(console.error)
      .finally(() => setReviewedLoading(false));
  };

  useEffect(() => {
    setSentiment(urlSentiment);
    setRange(urlRange);
    setMacroSegment(urlMacro);
    load(urlSentiment, urlRange, urlMacro);
  }, [urlSentiment, urlRange, urlMacro]);

  useEffect(() => {
    if (tab === 'reviewed' && reviewedItems.length === 0 && !reviewedLoading && !loading) {
      loadReviewed(sentiment || undefined, range || undefined, macroSegment || undefined);
    }
  }, [tab]);

  const applyFilters = () => {
    const next = new URLSearchParams();
    if (sentiment) next.set('sentiment', sentiment);
    if (range) next.set('range', range);
    if (macroSegment) next.set('macro', macroSegment);
    setSearchParams(next);
    if (tab === 'reviewed') loadReviewed(sentiment || undefined, range || undefined, macroSegment || undefined);
  };

  const clearFilters = () => {
    setSentiment('');
    setRange('');
    setMacroSegment('');
    setSearchParams({});
  };

  // Move item from pending to reviewed in local state
  const promoteToReviewed = (item: ReviewItem, updatedItem?: Partial<ReviewItem>) => {
    setItems(prev => prev.filter(p => p.id !== item.id));
    setTotalPending(prev => Math.max(0, prev - 1));
    setReviewedItems(prev => [{ ...item, ...updatedItem, needs_review: false }, ...prev]);
    api.getReviewStats().then(setStats).catch(() => undefined);
  };

  const handleCorrection = async (
    item: ReviewItem,
    correctedSentiment: string,
    correctedAspects?: string[],
    trustOverride?: number | null,
  ) => {
    setBusyId(item.id);
    setErrorMsg(null);
    try {
      const payload: Record<string, unknown> = {
        original_sentiment: item.sentiment,
        corrected_sentiment: correctedSentiment,
        original_aspects: item.aspects,
        subreddit: item.subreddit,
        notes: correctedSentiment === item.sentiment ? 'Dashboard confirmation' : 'Dashboard correction',
      };
      if (correctedAspects !== undefined) payload.corrected_aspects = correctedAspects;
      if (trustOverride !== undefined && trustOverride !== null) payload.trust_override = trustOverride;
      const res = await api.submitReview(item.post_id || item.id, payload);
      if (res.status === 'saved') {
        promoteToReviewed(item, { sentiment: correctedSentiment });
      } else {
        setErrorMsg('Could not save correction');
      }
    } catch (e) {
      setErrorMsg(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const handleClose = async (item: ReviewItem, closeType: 'no_reply' | 'issue_fixed' | 'reply_sent', actionNote?: string) => {
    setBusyId(item.id);
    setErrorMsg(null);
    try {
      const res = await api.closeReview(item.post_id || item.id, item.subreddit, closeType, actionNote);
      if (res.status === 'closed') {
        promoteToReviewed(item, { close_reason: closeType });
      } else {
        setErrorMsg(res.reason || 'Could not close post');
      }
    } catch (e) {
      setErrorMsg(String(e));
    } finally {
      setBusyId(null);
    }
  };

  if (loading) return <div className="text-gray-500 p-8">Loading review queue...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-walmart-navy">Review &amp; Validate</h2>
          <p className="text-xs text-gray-500 mt-1">
            Corrections are saved to the analyses table and feed back into all dashboards.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap text-xs">
          {urlSentiment && (
            <span className="px-3 py-1 rounded-pill bg-walmart-blue/10 text-walmart-blue border border-walmart-blue/20 font-medium">
              Sentiment: {urlSentiment}
            </span>
          )}
          {urlRange && (
            <span className="px-3 py-1 rounded-pill bg-walmart-blue/10 text-walmart-blue border border-walmart-blue/20 font-medium">
              Range: {RANGE_OPTIONS.find(o => o.value === urlRange)?.label || urlRange}
            </span>
          )}
          {urlMacro && (
            <span className="px-3 py-1 rounded-pill bg-walmart-blue/10 text-walmart-blue border border-walmart-blue/20 font-medium">
              Group: {urlMacro === 'walmart' ? 'Walmart' : 'Competitors'}
            </span>
          )}
          <span className="px-3 py-1 rounded-pill bg-walmart-navy/5 text-walmart-navy border border-walmart-navy/15 font-medium">
            {totalPending} pending {items.length < totalPending ? `(${items.length} shown)` : ''}
          </span>
          {stats && (
            <>
              <span className="px-3 py-1 rounded-pill bg-walmart-blue/10 text-walmart-blue border border-walmart-blue/20 font-medium" title="Sentiment overrides where analyst disagreed with the model">
                ✎ {stats.total_corrections} corrections
              </span>
              <span
                className="px-3 py-1 rounded-pill bg-sentiment-positive/10 text-sentiment-positive border border-sentiment-positive/20 font-medium"
                title={`Human confirmations of the model's prediction (${stats.total_confirmations}/${stats.total_reviewed} reviewed)`}
              >
                ✓ {(stats.agreement_rate * 100).toFixed(1)}% agreement
              </span>
              <span className="px-3 py-1 rounded-pill bg-walmart-spark/15 text-walmart-navy border border-walmart-spark/40 font-medium" title="Auto-replies saved">
                ✉ {stats.total_replies_posted} replies
              </span>
            </>
          )}
        </div>
      </div>

      {/* Filter Bar */}
      <Card>
        <div className="flex gap-4 items-end flex-wrap">
          <div className="flex flex-col gap-1">
            <label className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Sentiment</label>
            <select
              value={sentiment}
              onChange={e => setSentiment(e.target.value)}
              className="border border-walmart-navy/15 rounded-pill px-4 py-1.5 text-sm bg-white shadow-sm text-walmart-navy focus:outline-none focus:ring-2 focus:ring-walmart-blue"
            >
              {SENTIMENTS.map(s => (
                <option key={s} value={s}>{s ? s.charAt(0).toUpperCase() + s.slice(1) : 'All'}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Time Range</label>
            <select
              value={range}
              onChange={e => setRange(e.target.value)}
              className="border border-walmart-navy/15 rounded-pill px-4 py-1.5 text-sm bg-white shadow-sm text-walmart-navy focus:outline-none focus:ring-2 focus:ring-walmart-blue"
            >
              {RANGE_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Group</label>
            <select
              value={macroSegment}
              onChange={e => setMacroSegment(e.target.value)}
              className="border border-walmart-navy/15 rounded-pill px-4 py-1.5 text-sm bg-white shadow-sm text-walmart-navy focus:outline-none focus:ring-2 focus:ring-walmart-blue"
            >
              <option value="">All</option>
              <option value="walmart">Walmart</option>
              <option value="competitor">Competitors</option>
            </select>
          </div>
          <Button onClick={applyFilters} disabled={loading} variant="primary">
            {loading ? 'Loading…' : 'Apply'}
          </Button>
          {(urlSentiment || urlRange || urlMacro) && (
            <button onClick={clearFilters} className="text-xs text-gray-500 hover:text-sentiment-negative underline">
              Clear filters
            </button>
          )}
        </div>
      </Card>

      {errorMsg && (
        <div className="bg-sentiment-negative/5 border border-sentiment-negative/20 text-sentiment-negative text-sm rounded-xl px-4 py-2.5">
          {errorMsg}
        </div>
      )}

      {/* Accuracy Tracker */}
      {stats && stats.daily_accuracy && stats.daily_accuracy.length > 0 && (
        <AccuracyTracker stats={stats} />
      )}

      {/* Pending / Reviewed tabs */}
      <div className="flex items-center gap-0 border-b border-walmart-navy/10">
        {([
          { key: 'pending' as const, label: 'Pending Review', count: totalPending },
          { key: 'reviewed' as const, label: 'Reviewed', count: reviewedItems.length },
        ]).map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-5 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
              tab === t.key
                ? 'border-walmart-blue text-walmart-blue'
                : 'border-transparent text-gray-500 hover:text-walmart-navy'
            }`}
          >
            {t.label}
            <span className={`ml-2 px-1.5 py-0.5 rounded-pill text-[11px] ${
              tab === t.key ? 'bg-walmart-blue/10 text-walmart-blue' : 'bg-gray-100 text-gray-500'
            }`}>{t.count}</span>
          </button>
        ))}
      </div>

      {/* Pending tab */}
      {tab === 'pending' && (
        items.length === 0 ? (
          <Card className="text-center py-12 text-gray-500">
            <p className="text-lg font-semibold text-walmart-navy">All caught up!</p>
            <p className="text-sm">No posts need review right now.</p>
          </Card>
        ) : (
          <>
            <div className="space-y-3">
              {items.map(item => (
                <ReviewCard
                  key={item.id}
                  item={item}
                  busy={busyId === item.id}
                  onCorrect={handleCorrection}
                  onClose={handleClose}
                />
              ))}
            </div>
            {hasMore && (
              <div className="flex justify-center pt-2">
                <button
                  onClick={loadMore}
                  disabled={loadingMore}
                  className="px-6 py-2 text-sm font-semibold rounded-pill bg-white border border-walmart-navy/20 text-walmart-navy hover:bg-walmart-blue/5 disabled:opacity-50"
                >
                  {loadingMore ? 'Loading…' : `Load more (${totalPending - items.length} remaining)`}
                </button>
              </div>
            )}
            {!hasMore && items.length > 0 && (
              <p className="text-center text-xs text-gray-400 pt-1">All {totalPending} posts loaded</p>
            )}
          </>
        )
      )}

      {/* Reviewed tab */}
      {tab === 'reviewed' && (
        reviewedLoading ? (
          <div className="text-gray-500 p-8">Loading reviewed posts…</div>
        ) : reviewedItems.length === 0 ? (
          <Card className="text-center py-12 text-gray-500">
            <p className="text-sm">No reviewed posts yet — validate some from the Pending tab.</p>
          </Card>
        ) : (
          <div className="space-y-3">
            {reviewedItems.map(item => (
              <ReviewCard
                key={item.id}
                item={item}
                busy={busyId === item.id}
                onCorrect={() => {}}
                onClose={handleClose}
                readOnly={!!(item.close_reason || item.reply_posted_at)}
              />
            ))}
          </div>
        )
      )}

      {/* Feedback History */}
      <FeedbackHistory />
    </div>
  );
}

// ─── Model Accuracy Tracker ──────────────────────────────────────────────────
// Line chart of daily agreement rate as analysts confirm/override predictions.
// This is the HITL feedback-loop story: as the queue is worked through, we get
// an out-of-sample estimate of how the deployed model is doing right now.
function AccuracyTracker({ stats }: { stats: ReviewStats }) {
  const rows = stats.daily_accuracy.map(d => ({
    date: d.date,
    agreement: Math.round(d.agreement_rate * 100),
    reviewed: d.reviewed,
  }));
  const overallPct = (stats.agreement_rate * 100).toFixed(1);
  return (
    <Card>
      <div className="flex items-baseline justify-between mb-3 flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold text-walmart-navy uppercase tracking-wider">
            Model Accuracy Tracker
          </h3>
          <p className="text-xs text-gray-500 mt-1">
            Daily human-agreement rate. Each point = % of reviews on that day where the analyst
            confirmed the model's sentiment (didn't override it). {stats.total_reviewed} reviewed to date.
          </p>
        </div>
        <div className="text-right">
          <div className="text-3xl font-bold text-walmart-navy">{overallPct}%</div>
          <div className="text-[11px] uppercase tracking-wider text-gray-500">overall agreement</div>
        </div>
      </div>
      <div style={{ width: '100%', height: 220 }}>
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#6b7280' }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#6b7280' }} label={{ value: '% agreement', angle: -90, position: 'insideLeft', style: { fontSize: 11, fill: '#6b7280' } }} />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
              formatter={(value: number, name: string) => {
                if (name === 'agreement') return [`${value}%`, 'Agreement'];
                return [value, name];
              }}
            />
            <Line type="monotone" dataKey="agreement" stroke="#0071ce" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

// ─── Feedback History ────────────────────────────────────────────────────────
// Collapsible audit table of every past correction — post id, from→to,
// aspects that changed, trust override, analyst, timestamp. Powers thesis
// claim that the HITL loop generates retraining data.
function FeedbackHistory() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<FeedbackHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open && items.length === 0 && !loading) {
      setLoading(true);
      api.getFeedbackHistory(50)
        .then(res => setItems(res.items))
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [open, items.length, loading]);

  return (
    <Card>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between text-left"
      >
        <div>
          <h3 className="text-sm font-semibold text-walmart-navy uppercase tracking-wider">
            Feedback History
          </h3>
          <p className="text-xs text-gray-500 mt-1">
            Audit trail of every past correction — retraining data for the next model iteration.
          </p>
        </div>
        <span className="text-walmart-blue text-sm font-semibold">{open ? 'Hide ▲' : 'Show ▼'}</span>
      </button>
      {open && (
        <div className="mt-4">
          {loading && <p className="text-xs text-gray-500">Loading…</p>}
          {!loading && items.length === 0 && (
            <p className="text-xs text-gray-500">No feedback recorded yet.</p>
          )}
          {!loading && items.length > 0 && (
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-gray-500 border-b border-walmart-navy/10">
                    <th className="py-2 pr-3">When</th>
                    <th className="py-2 pr-3">Post</th>
                    <th className="py-2 pr-3">Sentiment</th>
                    <th className="py-2 pr-3">Aspects Δ</th>
                    <th className="py-2 pr-3">Trust</th>
                    <th className="py-2">Analyst</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map(row => (
                    <tr key={row.id} className="border-b border-walmart-navy/5 hover:bg-walmart-blue/[0.02]">
                      <td className="py-2 pr-3 text-gray-600 whitespace-nowrap">{row.created_at ? new Date(row.created_at).toLocaleString() : '—'}</td>
                      <td className="py-2 pr-3 font-mono text-[10px] text-walmart-navy/70">{row.post_id?.slice(0, 12) || '—'}</td>
                      <td className="py-2 pr-3">
                        {row.changed ? (
                          <span className="text-walmart-blue font-medium">
                            {row.original_sentiment} → <span className="font-semibold">{row.corrected_sentiment}</span>
                          </span>
                        ) : (
                          <span className="text-sentiment-positive">✓ confirmed {row.original_sentiment}</span>
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        {row.aspects_changed && row.aspects_changed.length > 0 ? (
                          <span className="text-walmart-spark-dark">{row.aspects_changed.join(', ')}</span>
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        {row.trust_override !== null && row.trust_override !== undefined ? (
                          <span className="text-walmart-blue font-medium">{Number(row.trust_override).toFixed(2)}</span>
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>
                      <td className="py-2 text-gray-600">{row.analyst_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function ReviewCard({
  item,
  busy,
  onCorrect,
  onClose,
  readOnly = false,
}: {
  item: ReviewItem;
  busy: boolean;
  onCorrect: (item: ReviewItem, sentiment: string, aspects?: string[], trust?: number | null) => void;
  onClose: (item: ReviewItem, closeType: 'no_reply' | 'issue_fixed' | 'reply_sent', actionNote?: string) => void;
  readOnly?: boolean;
}) {
  type Draft = {
    reply: string;
    model_used: string;
    source: string;
    label?: string;
  };
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selectedIdx, setSelectedIdx] = useState<number>(0);
  const [gatewayAvailable, setGatewayAvailable] = useState<boolean | null>(null);
  const [gatewayReason, setGatewayReason] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState('');
  const [actionDraft, setActionDraft] = useState('');
  const [actionModel, setActionModel] = useState('');
  const [actionDrafts, setActionDrafts] = useState<Array<{ model: string; source: string; note: string }>>([]);
  const [selectedActionIdx, setSelectedActionIdx] = useState<number>(0);
  const [reply, setReply] = useState<string>(item.reply_text || '');
  const [posting, setPosting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genActionNote, setGenActionNote] = useState(true);
  const [postedAt, setPostedAt] = useState<string | null>(item.reply_posted_at);
  const [postErr, setPostErr] = useState<string | null>(null);
  const [examplesUsed, setExamplesUsed] = useState<number>(0);
  const [postToReddit, setPostToReddit] = useState(true);
  const [redditStatus, setRedditStatus] = useState<{ kind: 'dry_run' | 'live' | 'error'; msg: string } | null>(null);

  // Advanced correction state (aspect + trust override). null = leave model
  // output untouched; any change (add/remove aspect, drag slider) causes the
  // panel to open and its values to be sent along with the sentiment button click.
  const initialAspects = (item.aspects || []).map(a =>
    typeof a === 'string' ? a : (a as { aspect?: string }).aspect || String(a),
  );
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [aspects, setAspects] = useState<string[]>(initialAspects);
  const [trustOverride, setTrustOverride] = useState<number | null>(null);
  const aspectsDirty =
    aspects.length !== initialAspects.length ||
    aspects.some(a => !initialAspects.includes(a)) ||
    initialAspects.some(a => !aspects.includes(a));

  const toggleAspect = (a: string) => {
    setAspects(prev => prev.includes(a) ? prev.filter(x => x !== a) : [...prev, a]);
  };

  const isNegative = item.sentiment === 'negative';

  const handleGenerate = async () => {
    setPostErr(null);
    setGenerating(true);
    try {
      const res = await api.draftAll(item.post_id || item.id, item.subreddit);
      if (res.status === 'ok') {
        setGatewayAvailable(res.gateway_available ?? null);
        setGatewayReason(res.gateway_reason ?? null);
        const incomingActionDrafts = genActionNote
          ? (res.action_drafts && res.action_drafts.length
            ? res.action_drafts
            : (res.action_draft
              ? [{ model: res.action_model || 'template', source: 'template', note: res.action_draft }]
              : []))
          : [];
        setActionDrafts(incomingActionDrafts);
        setSelectedActionIdx(0);
        setActionDraft(incomingActionDrafts[0]?.note || '');
        setActionModel(incomingActionDrafts[0]?.model || '');
        const incoming = (res.drafts && res.drafts.length
          ? res.drafts
          : (res.reply
            ? [{ reply: res.reply, model_used: 'unknown', source: 'unknown' as const }]
            : [])) as Draft[];
        const realDrafts = incoming.filter(d => !(
          d.source === 'smart-template' && d.label?.includes('offline fallback')
        ));
        const toShow = realDrafts.length > 0 ? realDrafts : incoming;
        if (!toShow.length) {
          setPostErr('No drafts returned');
        } else {
          setDrafts(toShow);
          setSelectedIdx(0);
          setReply(toShow[0].reply);
          setExamplesUsed(res.examples_used ?? 0);
        }
      } else {
        setPostErr(res.reason || 'Could not generate reply');
      }
    } catch (e) {
      setPostErr(String(e));
    } finally {
      setGenerating(false);
    }
  };

  const handleSelectDraft = (idx: number) => {
    setSelectedIdx(idx);
    setReply(drafts[idx]?.reply || '');
  };

  const handlePostReply = async () => {
    setPostErr(null);
    setRedditStatus(null);
    if (!reply.trim()) {
      setPostErr('Reply is empty');
      return;
    }
    setPosting(true);
    try {
      const res = await api.postReply(item.post_id || item.id, reply, item.subreddit, postToReddit);
      if (res.status === 'saved') {
        setPostedAt(res.reply_posted_at || new Date().toISOString());
        try { await navigator.clipboard.writeText(reply); } catch { /* noop */ }
        if (res.reddit) {
          if (res.reddit.ok && res.reddit.dry_run) {
            setRedditStatus({ kind: 'dry_run', msg: 'Reddit OAuth in dry-run — reply was logged, not posted live. Click “Mark as Posted” after you post it manually.' });
          } else if (res.reddit.ok) {
            setRedditStatus({ kind: 'live', msg: `Posted to Reddit (${res.reddit.posted_id || 'ok'}). Click “Mark as Posted” to move this post to Reviewed.` });
          } else if (res.reddit.error === 'rate_limited') {
            setRedditStatus({ kind: 'error', msg: `Rate-limited — try again in ${res.reddit.retry_after_seconds || '?'}s.` });
          } else {
            setRedditStatus({ kind: 'error', msg: `Reddit post failed: ${res.reddit.error}` });
          }
        } else {
          setRedditStatus({ kind: 'dry_run', msg: 'Reply saved. Click “Mark as Posted” after you post it manually.' });
        }
        if (item.reddit_url && (!res.reddit || res.reddit.dry_run)) {
          window.open(item.reddit_url, '_blank', 'noopener');
        }
      } else {
        setPostErr(res.reason || 'Could not save reply');
      }
    } catch (e) {
      setPostErr(String(e));
    } finally {
      setPosting(false);
    }
  };

  const handleMarkPosted = () => {
    const note = actionNote.trim();
    onClose(item, note ? 'issue_fixed' : 'reply_sent', note || undefined);
  };

  return (
    <Card>
      {/* Follow-up alert */}
      {item.follow_up_needed && (
        <div className="flex items-center gap-2 mb-2 bg-walmart-spark/10 border border-walmart-spark/40 rounded-lg px-3 py-1.5 text-xs text-walmart-navy">
          <span>⚠️</span>
          <span><span className="font-semibold">Follow-up needed</span> — reply was sent 3+ days ago with no resolution. Check the Lifecycle page.</span>
        </div>
      )}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <SentimentBadge sentiment={item.sentiment} />
            {item.priority_tier === 'P1' && (
              <span className="px-2 py-0.5 rounded-pill text-[11px] font-bold bg-sentiment-negative text-white" title="P1 — trust ≥ 0.7 AND confidence ≥ 0.8">
                P1
              </span>
            )}
            {item.priority_tier === 'P2' && (
              <span className="px-2 py-0.5 rounded-pill text-[11px] font-bold bg-walmart-spark-dark text-white" title="P2 — trust ≥ 0.5 AND confidence ≥ 0.6">
                P2
              </span>
            )}
            <span className="text-xs text-gray-500">r/{item.subreddit}</span>
            <span className="text-xs text-gray-400">
              Confidence:{' '}
              <span className={item.sentiment_confidence < 0.75 ? 'text-walmart-spark-dark font-medium' : ''}>
                {((item.sentiment_confidence || 0) * 100).toFixed(0)}%
              </span>
            </span>
            <span className="text-xs text-gray-400">
              Trust:{' '}
              <span className={item.trust_score < 0.5 ? 'text-sentiment-negative' : 'text-sentiment-positive'}>
                {item.trust_score?.toFixed(2)}
              </span>
            </span>
            {item.model && <span className="text-xs text-gray-300">{item.model.split('/').pop()}</span>}
          </div>

          {item.title && <h4 className="text-sm font-semibold text-walmart-navy mb-1">{item.title}</h4>}
          {item.text && <p className="text-sm text-gray-700 leading-relaxed line-clamp-4">{item.text}</p>}

          <div className="flex items-center gap-3 mt-2 text-xs text-gray-500 flex-wrap">
            {item.author && <span>by u/{item.author}</span>}
            {item.score !== undefined && <span>⬆ {item.score}</span>}
            {item.created_timestamp > 0 && (
              <span>{new Date(item.created_timestamp * 1000).toLocaleString()}</span>
            )}
            {item.reddit_url && (
              <a
                href={item.reddit_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-walmart-blue hover:underline font-medium"
              >
                View on Reddit ↗
              </a>
            )}
          </div>

          {item.aspects && item.aspects.length > 0 && (
            <div className="flex gap-1 mt-2 flex-wrap">
              {item.aspects.map((asp, i) => (
                <span key={i} className="px-2 py-0.5 rounded-pill bg-walmart-blue/10 text-walmart-blue text-xs">
                  {typeof asp === 'string' ? asp : (asp as { aspect?: string }).aspect || String(asp)}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-1 flex-shrink-0">
          {readOnly ? (
            /* Reviewed state badge */
            <div className="flex flex-col items-center gap-1.5">
              <span className="px-3 py-1.5 text-xs rounded-pill bg-sentiment-positive/10 text-sentiment-positive border border-sentiment-positive/20 font-medium text-center">
                ✓ Reviewed
              </span>
              {item.close_reason && (
                <span className="text-[11px] text-gray-400 text-center">No reply sent</span>
              )}
              {item.reply_posted_at && (
                <span className="text-[11px] text-walmart-blue text-center">Reply sent</span>
              )}
              {item.validated_at && (
                <span className="text-[10px] text-gray-400 text-center whitespace-nowrap">
                  {new Date(item.validated_at).toLocaleDateString()}
                </span>
              )}
            </div>
          ) : (
            <>
              {/* Sentiment correction group */}
              <div className="flex flex-col gap-1 pb-2 border-b border-gray-100">
                <span className="text-xs text-gray-400 text-center mb-1">Correct to:</span>
                {item.sentiment !== 'positive' && (
                  <button
                    onClick={() => onCorrect(item, 'positive', aspectsDirty ? aspects : undefined, trustOverride)}
                    disabled={busy}
                    className="px-3 py-1.5 text-xs rounded-pill bg-sentiment-positive/10 text-sentiment-positive hover:bg-sentiment-positive/20 border border-sentiment-positive/20 disabled:opacity-50 font-medium"
                  >
                    ✓ Positive
                  </button>
                )}
                {item.sentiment !== 'neutral' && (
                  <button
                    onClick={() => onCorrect(item, 'neutral', aspectsDirty ? aspects : undefined, trustOverride)}
                    disabled={busy}
                    className="px-3 py-1.5 text-xs rounded-pill bg-walmart-navy/5 text-walmart-navy hover:bg-walmart-navy/10 border border-walmart-navy/15 disabled:opacity-50 font-medium"
                  >
                    — Neutral
                  </button>
                )}
                {item.sentiment !== 'negative' && (
                  <button
                    onClick={() => onCorrect(item, 'negative', aspectsDirty ? aspects : undefined, trustOverride)}
                    disabled={busy}
                    className="px-3 py-1.5 text-xs rounded-pill bg-sentiment-negative/10 text-sentiment-negative hover:bg-sentiment-negative/20 border border-sentiment-negative/20 disabled:opacity-50 font-medium"
                  >
                    ✗ Negative
                  </button>
                )}
              </div>

              {/* Close section — always visible */}
              <button
                type="button"
                onClick={() => onClose(item, 'no_reply')}
                disabled={busy}
                className="w-full mt-1 px-2 py-1.5 text-xs rounded-lg bg-gray-100 text-gray-500 hover:bg-gray-200 border border-gray-200 disabled:opacity-50 font-medium"
              >
                ✕ Close
              </button>
              <button
                type="button"
                onClick={() => setAdvancedOpen(o => !o)}
                className="text-[11px] text-walmart-blue hover:underline mt-1"
              >
                {advancedOpen ? 'Hide advanced ▲' : 'Advanced ▾'}
                {(aspectsDirty || trustOverride !== null) && (
                  <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-walmart-spark" title="Unsent aspect/trust changes" />
                )}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Advanced override: aspects + trust score */}
      {!readOnly && advancedOpen && (
        <div className="mt-3 pt-3 border-t border-dashed border-walmart-navy/15 space-y-3">
          <div>
            {/* Header row */}
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[11px] uppercase tracking-wider font-semibold text-gray-600">
                Aspect override
                {aspectsDirty && <span className="ml-2 text-walmart-spark-dark normal-case font-normal">(will be saved on next correction click)</span>}
              </label>
              {aspects.length > 0 && (
                <button type="button" onClick={() => setAspects([])}
                  className="text-[11px] text-sentiment-negative hover:underline" title="Remove all aspects">
                  ✕ Clear all
                </button>
              )}
            </div>

            {/* Currently tagged — always shown, covers legacy names like "store experience" */}
            {aspects.length > 0 && (
              <div className="mb-2 p-2 rounded-lg bg-walmart-navy/5 border border-walmart-navy/10">
                <span className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Currently tagged — click to remove</span>
                <div className="flex flex-wrap gap-1.5 mt-1.5">
                  {aspects.map(a => (
                    <button key={a} type="button" onClick={() => toggleAspect(a)} title={`Remove "${a}"`}
                      className="px-2.5 py-1 rounded-pill text-[11px] border transition-colors bg-walmart-blue text-white border-walmart-blue hover:bg-sentiment-negative hover:border-sentiment-negative">
                      ✕ {a}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Taxonomy picker — only shows aspects not already tagged */}
            <div className="space-y-2">
              <span className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold">Add from taxonomy</span>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-gray-400 ml-0">Customer</span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {ASPECT_OPTIONS_CUSTOMER.filter(a => !aspects.includes(a)).map(a => (
                    <button key={a} type="button" onClick={() => toggleAspect(a)} title={`Add "${a}"`}
                      className="px-2.5 py-1 rounded-pill text-[11px] border transition-colors bg-white text-walmart-navy border-walmart-navy/20 hover:border-walmart-blue">
                      + {a}
                    </button>
                  ))}
                  {ASPECT_OPTIONS_CUSTOMER.every(a => aspects.includes(a)) && (
                    <span className="text-[11px] text-gray-400 italic">all tagged</span>
                  )}
                </div>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-gray-400">Employee</span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {ASPECT_OPTIONS_EMPLOYEE.filter(a => !aspects.includes(a)).map(a => (
                    <button key={a} type="button" onClick={() => toggleAspect(a)} title={`Add "${a}"`}
                      className="px-2.5 py-1 rounded-pill text-[11px] border transition-colors bg-white text-walmart-navy border-walmart-navy/20 hover:border-walmart-blue">
                      + {a}
                    </button>
                  ))}
                  {ASPECT_OPTIONS_EMPLOYEE.every(a => aspects.includes(a)) && (
                    <span className="text-[11px] text-gray-400 italic">all tagged</span>
                  )}
                </div>
              </div>
            </div>
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-wider font-semibold text-gray-600 flex items-center gap-2">
              Trust override
              {trustOverride === null ? (
                <span className="text-gray-400 normal-case font-normal">(unchanged: {item.trust_score?.toFixed(2)})</span>
              ) : (
                <span className="text-walmart-spark-dark normal-case font-normal">→ {trustOverride.toFixed(2)}</span>
              )}
              {trustOverride !== null && (
                <button
                  type="button"
                  onClick={() => setTrustOverride(null)}
                  className="text-[10px] text-gray-500 hover:text-sentiment-negative underline ml-auto"
                >
                  reset
                </button>
              )}
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={trustOverride ?? item.trust_score ?? 0.5}
              onChange={e => setTrustOverride(parseFloat(e.target.value))}
              className="w-full mt-1 accent-walmart-blue"
            />
          </div>
        </div>
      )}

      {/* LLM Reply Draft — two side-by-side candidates */}
      {isNegative && (
        <div className="mt-4 pt-4 border-t border-dashed border-walmart-navy/15">
          <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
            <h5 className="text-xs font-semibold text-walmart-navy uppercase tracking-wider">
              LLM Reply Drafts
              <span className="ml-2 text-gray-400 normal-case font-normal">
                (pick the one that sounds better · edit before posting)
              </span>
            </h5>
            {postedAt && (
              <span className="text-xs text-sentiment-positive bg-sentiment-positive/10 border border-sentiment-positive/20 rounded-pill px-2.5 py-0.5 font-medium">
                ✓ Posted {new Date(postedAt).toLocaleString()}
              </span>
            )}
          </div>

          {drafts.length === 0 && !generating && (
            <div className="bg-walmart-navy/5 border border-dashed border-walmart-navy/20 rounded-xl p-3 text-center text-xs text-gray-500">
              No drafts yet. Click <span className="font-semibold text-walmart-navy">Generate Drafts</span> below — we'll generate
              up to 3 reply candidates (GPT, Mistral, Smart Composer) so you can pick the best one.
            </div>
          )}
          {generating && (
            <div className="bg-walmart-blue/5 border border-walmart-blue/20 rounded-xl p-3 text-center text-xs text-walmart-blue">
              ⏳ Generating drafts from GPT, Mistral & Smart Composer… (first call may take a few seconds)
            </div>
          )}

          {/* Network / config warning — shown when GPT is unavailable */}
          {gatewayAvailable === false && (() => {
            const msgs: Record<string, { title: string; detail: string }> = {
              no_gateway_key: {
                title: 'Walmart gateway key not configured.',
                detail: 'Add WMT_LLM_GATEWAY_KEY to .env and restart the server.',
              },
              no_consumer_id: {
                title: 'WM_CONSUMER.ID not set.',
                detail: 'Add WMT_CONSUMER_ID=<your-uuid> to .env. Find it in the LLM Gateway APIM portal under use case UC08708, then restart the server.',
              },
              no_openai_key: {
                title: 'WM_CONSUMER.ID not configured.',
                detail: 'The gateway URL and JWT key are correct, but the WM_CONSUMER.ID routing header is missing. Get your Consumer UUID from the LLM Gateway APIM portal (the UUID registered when use case UC08708 was created), then add WMT_CONSUMER_ID=<uuid> to .env and restart.',
              },
              network_unreachable: {
                title: 'GPT unreachable on this network.',
                detail: 'The gateway is temporarily unreachable. Try again in a moment.',
              },
            };
            const m = msgs[gatewayReason ?? ''] ?? {
              title: 'GPT drafts unavailable.',
              detail: 'Smart Composer drafts are shown instead.',
            };
            return (
              <div className="flex items-start gap-2 bg-walmart-spark/10 border border-walmart-spark/40 rounded-xl px-3 py-2.5 text-xs text-walmart-navy">
                <span className="text-base leading-none mt-0.5">⚠️</span>
                <div>
                  <span className="font-semibold">{m.title}</span>{' '}{m.detail}
                  {' '}Smart Composer drafts are shown instead.
                </div>
              </div>
            );
          })()}

          {drafts.length > 0 && (
            <div className={`grid grid-cols-1 ${drafts.length >= 3 ? 'md:grid-cols-3' : 'md:grid-cols-2'} gap-3 mb-2`}>
              {drafts.map((d, i) => {
                const isSelected = i === selectedIdx;
                const sourceColor =
                  d.source === 'llm' ? 'text-sentiment-positive' :
                  d.source === 'smart-template' ? 'text-walmart-blue' : 'text-walmart-spark-dark';
                const sourceLabel =
                  d.source === 'llm' ? 'LLM-generated' :
                  d.source === 'smart-template' ? 'Smart composer (varies every call)' :
                  d.source;
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => handleSelectDraft(i)}
                    className={`text-left rounded-xl border-2 p-3 transition-all ${
                      isSelected
                        ? 'border-walmart-blue bg-walmart-blue/5 shadow-card'
                        : 'border-walmart-navy/10 bg-white hover:border-walmart-blue/40'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] uppercase tracking-wider font-semibold text-gray-600">
                        Draft {String.fromCharCode(65 + i)} · {d.label || d.model_used}
                      </span>
                      {isSelected && (
                        <span className="text-[10px] font-bold text-walmart-navy bg-walmart-spark rounded-pill px-2 py-0.5">
                          ✓ SELECTED
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-800 leading-snug whitespace-pre-wrap">{d.reply}</p>
                    <p className={`text-[10px] mt-1 ${sourceColor}`}>{sourceLabel}</p>
                  </button>
                );
              })}
            </div>
          )}

          {drafts.length > 0 && (
            <>
              <label className="block text-[11px] uppercase tracking-wider font-semibold text-gray-600 mb-1">
                Your reply (edit before posting)
              </label>
              <textarea
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                rows={4}
                className="w-full text-sm border border-walmart-navy/15 rounded-xl p-2 font-mono focus:ring-2 focus:ring-walmart-blue focus:border-walmart-blue"
                placeholder="Edit the selected draft before posting…"
              />
              <div className="text-xs text-gray-500 mt-1">
                Few-shot examples used: <span className="font-medium">{examplesUsed}</span>
                {examplesUsed === 0 && (
                  <span className="text-walmart-spark-dark"> (post your first reply to start the learning loop)</span>
                )}
              </div>

              {/* Internal action note — generated alongside reply drafts */}
              <div className="mt-3 p-3 rounded-xl bg-walmart-spark/8 border border-walmart-spark/30">
                <label className="block text-[11px] uppercase tracking-wider font-semibold text-walmart-navy mb-1">
                  ⚡ Internal Action Note
                  <span className="ml-2 normal-case font-normal text-gray-500">— shown in Lifecycle → Actionable Items</span>
                </label>
                {actionDrafts.length > 1 && (
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {actionDrafts.map((d, i) => {
                      const isGpt = d.model.toLowerCase().includes('gpt');
                      const active = i === selectedActionIdx;
                      return (
                        <button
                          key={i}
                          type="button"
                          onClick={() => {
                            setSelectedActionIdx(i);
                            setActionDraft(d.note);
                            setActionModel(d.model);
                            setActionNote('');
                          }}
                          className={`text-[11px] px-2.5 py-1 rounded-pill border font-medium transition-colors ${
                            active
                              ? (isGpt
                                ? 'bg-sentiment-positive text-white border-sentiment-positive'
                                : 'bg-walmart-blue text-white border-walmart-blue')
                              : (isGpt
                                ? 'bg-white text-sentiment-positive border-sentiment-positive/40 hover:bg-sentiment-positive/5'
                                : 'bg-white text-walmart-blue border-walmart-blue/40 hover:bg-walmart-blue/5')
                          }`}
                          title={d.note}
                        >
                          {isGpt ? '🤖' : '🦙'} {d.model}
                        </button>
                      );
                    })}
                  </div>
                )}
                {actionDrafts.length === 1 && actionModel && (
                  <div className={`text-[11px] font-medium mb-1 ${actionModel.toLowerCase().includes('gpt') ? 'text-sentiment-positive' : 'text-walmart-blue'}`}>
                    · {actionModel}
                  </div>
                )}
                <textarea
                  value={actionNote}
                  onChange={e => setActionNote(e.target.value)}
                  rows={2}
                  className="w-full text-xs border border-walmart-spark/40 rounded-lg px-2 py-1.5 resize-none focus:outline-none focus:ring-1 focus:ring-walmart-spark bg-white"
                  placeholder={actionDraft ? actionDraft : "Describe the internal action to take (auto-generated when GPT is available)…"}
                />
                {actionDraft && !actionNote && (
                  <button type="button" onClick={() => setActionNote(actionDraft)}
                    className="text-[11px] text-walmart-spark-dark hover:underline mt-0.5">
                    ↑ Use suggested action
                  </button>
                )}
              </div>
            </>
          )}

          {postErr && <div className="text-xs text-sentiment-negative mt-1">{postErr}</div>}
          {redditStatus && (
            <div className={`text-xs mt-1 px-2 py-1 rounded ${
              redditStatus.kind === 'dry_run' ? 'bg-walmart-spark/15 text-walmart-navy border border-walmart-spark/40'
              : redditStatus.kind === 'live' ? 'bg-sentiment-positive/10 text-sentiment-positive border border-sentiment-positive/30'
              : 'bg-sentiment-negative/10 text-sentiment-negative border border-sentiment-negative/30'
            }`}>
              {redditStatus.msg}
            </div>
          )}

          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <button
              onClick={handleGenerate}
              disabled={generating || posting}
              className="px-4 py-1.5 text-xs rounded-pill bg-walmart-spark text-walmart-navy hover:bg-walmart-spark-dark disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed shadow-sm font-semibold"
              title="Generates two reply candidates: one from the content-aware smart composer (varies every call), one from the neural model. Past analyst-posted replies are used as training context for both."
            >
              {generating ? 'Generating…' : (drafts.length ? '↻ Regenerate Both' : '✨ Generate Drafts')}
            </button>
            <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer select-none" title="When checked, also generates an internal action note alongside the customer reply draft">
              <input
                type="checkbox"
                checked={genActionNote}
                onChange={e => setGenActionNote(e.target.checked)}
                className="accent-walmart-blue"
              />
              Internal Action Note
            </label>
            <button
              onClick={handlePostReply}
              disabled={posting || generating || !reply.trim()}
              className="px-4 py-1.5 text-xs rounded-pill bg-walmart-blue text-white hover:bg-walmart-blue/90 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed shadow-sm font-semibold"
              title="Saves the reply to the audit log. Also posts to Reddit if the toggle is on (and OAuth is live; otherwise it's logged as dry-run)."
            >
              {posting ? 'Posting…' : (postedAt ? 'Re-Post Reply' : 'Post Reply')}
            </button>
            {postedAt && (
              <button
                onClick={handleMarkPosted}
                disabled={posting || generating}
                className="px-4 py-1.5 text-xs rounded-pill bg-sentiment-positive text-white hover:bg-sentiment-positive/90 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed shadow-sm font-semibold"
                title={actionNote.trim()
                  ? 'Confirm the reply was posted. Moves this post to Reviewed and Lifecycle → Actionable Items (issue_fixed).'
                  : 'Confirm the reply was posted. Moves this post to Reviewed and Lifecycle → Ack & Reply Sent.'}
              >
                ✓ Mark as Posted {actionNote.trim() ? '→ Actionable' : '→ Ack'}
              </button>
            )}
            <label className="flex items-center gap-1.5 text-xs text-walmart-navy cursor-pointer select-none">
              <input
                type="checkbox"
                checked={postToReddit}
                onChange={(e) => setPostToReddit(e.target.checked)}
                className="rounded border-walmart-navy/30 text-walmart-blue focus:ring-walmart-blue"
              />
              Post to Reddit
            </label>
            <span className="text-xs text-gray-500">
              Posted replies become future training examples.
            </span>
          </div>
        </div>
      )}
    </Card>
  );
}

function SentimentBadge({ sentiment }: { sentiment: string }) {
  const colors: Record<string, string> = {
    positive: 'bg-sentiment-positive/10 text-sentiment-positive border border-sentiment-positive/20',
    negative: 'bg-sentiment-negative/10 text-sentiment-negative border border-sentiment-negative/20',
    neutral: 'bg-walmart-navy/5 text-gray-600 border border-walmart-navy/10',
  };
  return <span className={`px-2 py-0.5 rounded-pill text-xs font-medium ${colors[sentiment] || colors.neutral}`}>{sentiment}</span>;
}
