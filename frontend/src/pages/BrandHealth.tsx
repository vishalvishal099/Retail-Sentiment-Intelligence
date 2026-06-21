import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { PieChart, Pie, Cell, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid } from 'recharts';
import { api, BrandHealthData, DateRange, SegmentInfo, MacroSegment, PriorityNegativePost } from '../api';
import Card, { CardHeader } from '../components/Card';
import Button from '../components/Button';

const COLORS = { positive: '#00865A', negative: '#DE1C24', neutral: '#74767C' };

const selectClass =
  'border border-walmart-navy/15 rounded-pill px-4 py-1.5 text-sm bg-white shadow-sm text-walmart-navy focus:outline-none focus:ring-2 focus:ring-walmart-blue focus:border-walmart-blue';

const RANGE_OPTIONS: { value: DateRange; label: string }[] = [
  { value: '1h', label: 'Last 1 hour' },
  { value: '2h', label: 'Last 2 hours' },
  { value: '3h', label: 'Last 3 hours' },
  { value: '6h', label: 'Last 6 hours' },
  { value: '12h', label: 'Last 12 hours' },
  { value: '24h', label: 'Last 24 hours' },
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'week', label: 'Last 7 Days' },
  { value: 'month', label: 'Last 30 Days' },
  { value: '90d', label: 'Last 90 Days' },
];

export default function BrandHealth() {
  const [data, setData] = useState<BrandHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [range, setRange] = useState<DateRange>('today');
  const [segment, setSegment] = useState<string>(''); // '' = all segments
  const [segments, setSegments] = useState<SegmentInfo[]>([]);
  const [macroSegment, setMacroSegment] = useState<MacroSegment | ''>('');
  const [priorityLimit, setPriorityLimit] = useState<number>(20);
  const [priorityData, setPriorityData] = useState<{
    posts: PriorityNegativePost[];
    tiers: { P1: number; P2: number };
    loading: boolean;
    error: string | null;
  }>({ posts: [], tiers: { P1: 0, P2: 0 }, loading: false, error: null });
  const navigate = useNavigate();

  const loadData = () => {
    setLoading(true);
    api.getBrandHealth(range, segment || null, macroSegment || null)
      .then(setData).catch(console.error).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, [range, segment, macroSegment]);
  useEffect(() => {
    api.getSegments().then(r => setSegments(r.segments)).catch(console.error);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setPriorityData(p => ({ ...p, loading: true, error: null }));
    api.getPriorityNegatives(range, priorityLimit, segment || null, macroSegment || null)
      .then((res) => {
        if (cancelled) return;
        if (res.error) {
          setPriorityData({ posts: [], tiers: { P1: 0, P2: 0 }, loading: false, error: res.error });
        } else {
          setPriorityData({
            posts: res.posts || [],
            tiers: res.tiers || { P1: 0, P2: 0 },
            loading: false,
            error: null,
          });
        }
      })
      .catch((e) => { if (!cancelled) setPriorityData({ posts: [], tiers: { P1: 0, P2: 0 }, loading: false, error: String(e) }); });
    return () => { cancelled = true; };
  }, [range, segment, macroSegment, priorityLimit]);

  const sd = data?.sentiment_distribution;
  const sPos = sd?.positive ?? 0;
  const sNeg = sd?.negative ?? 0;
  const sNeu = sd?.neutral ?? 0;
  const total = sd ? sPos + sNeg + sNeu : 0;
  const pctPositive = total > 0 ? ((sPos / total) * 100).toFixed(1) : '0';
  const pctNegative = total > 0 ? ((sNeg / total) * 100).toFixed(1) : '0';
  const pctNeutral = total > 0 ? ((sNeu / total) * 100).toFixed(1) : '0';

  const goToPosts = (sentiment?: 'positive' | 'negative' | 'neutral') => {
    const qs = new URLSearchParams();
    if (sentiment) qs.set('sentiment', sentiment);
    qs.set('range', range);
    navigate(`/posts?${qs.toString()}`);
  };

  const scrollToPriority = () => {
    const el = document.getElementById('priority-negatives');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const sentimentPie = sd ? [
    { name: 'Positive', key: 'positive' as const, value: sPos, color: COLORS.positive },
    { name: 'Negative', key: 'negative' as const, value: sNeg, color: COLORS.negative },
    { name: 'Neutral', key: 'neutral' as const, value: sNeu, color: COLORS.neutral },
  ] : [];

  // Sort aspects by count descending
  const sortedAspects = data?.aspect_breakdown
    ? Object.entries(data.aspect_breakdown).sort(([, a], [, b]) => b - a)
    : [];
  const maxAspectCount = sortedAspects.length > 0 ? sortedAspects[0][1] : 0;

  return (
    <div className="space-y-6">
      {data?.fallback_note && (
        <div className="bg-walmart-spark/15 border border-walmart-spark/40 text-walmart-navy text-sm rounded-xl px-4 py-2.5">
          {data.fallback_note}
        </div>
      )}
      {data && !data.fallback_note && data.days_requested && data.days_with_data !== undefined &&
        data.days_requested > 1 && data.days_with_data < data.days_requested && (
        <div className="bg-walmart-spark/15 border border-walmart-spark/40 text-walmart-navy text-sm rounded-xl px-4 py-2.5">
          Only {data.days_with_data} of the last {data.days_requested} days have data — longer ranges will look similar until older history is ingested.
        </div>
      )}

      {/* Header with Date Range Selector */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-walmart-navy">Brand Health Overview</h2>
          <p className="text-xs text-gray-500 mt-1">Sentiment, volume and aspect signals across tracked communities.</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {data && <span className="text-sm text-gray-500">{data.date}</span>}
          {/* Macro toggle: All · Walmart · Competitors */}
          <div className="inline-flex rounded-pill bg-white border border-walmart-navy/15 shadow-sm overflow-hidden" role="group" aria-label="Macro segment">
            {([
              { v: '' as const,           label: 'All' },
              { v: 'walmart' as const,    label: 'Walmart' },
              { v: 'competitor' as const, label: 'Competitors' },
            ]).map(opt => {
              const active = macroSegment === opt.v;
              return (
                <button
                  key={opt.label}
                  onClick={() => setMacroSegment(opt.v)}
                  className={
                    'px-3.5 py-1.5 text-sm font-semibold transition-colors ' +
                    (active
                      ? 'bg-walmart-navy text-white'
                      : 'text-walmart-navy hover:bg-walmart-blue/5')
                  }
                  title={
                    opt.v === 'walmart' ? 'Walmart-owned + employee subreddits' :
                    opt.v === 'competitor' ? 'Competitor + general retail subreddits' :
                    'All tracked subreddits'
                  }
                  aria-pressed={active}
                >{opt.label}</button>
              );
            })}
          </div>
          <select
            value={segment}
            onChange={(e) => setSegment(e.target.value)}
            className={selectClass}
            title="Filter by subreddit segment"
          >
            <option value="">All segments</option>
            {segments.map(s => (
              <option key={s.slug} value={s.slug}>{s.label}</option>
            ))}
          </select>
          <select
            value={range}
            onChange={(e) => setRange(e.target.value as DateRange)}
            className={selectClass}
          >
            {RANGE_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <Link to="/pipeline">
            <Button variant="outline" size="sm">Pipeline →</Button>
          </Link>
        </div>
      </div>

      {loading && <div className="text-gray-500 p-8">Loading...</div>}
      {!loading && (!data || !data.sentiment_distribution) && (
        <Card className="text-center text-gray-500">
          No data available for this range.
          <div className="text-xs mt-2 text-gray-400">
            Try a wider range, or click <span className="font-semibold text-walmart-navy">Run Now</span> to fetch fresh data.
          </div>
        </Card>
      )}
      {!loading && data && data.sentiment_distribution && (
      <>
      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <KPICard label="Total Posts" value={data.total_posts} onClick={() => goToPosts()} hint="View all posts" />
        <KPICard
          label="Trusted"
          value={data.trusted_posts}
          sub={
            data.trust_gate?.formula === 'score_x_confidence' && data.trust_gate?.tau != null
              ? `trust × confidence ≥ ${data.trust_gate.tau}`
              : `trust_score ≥ ${data.trust_gate?.threshold ?? 0.5}`
          }
          hint="Posts that passed the trust gate"
        />
        <KPICard
          label="Positive"
          value={`${pctPositive}%`}
          sub={`${sPos} posts`}
          tone="positive"
          onClick={() => goToPosts('positive')}
          hint="Click to see positive posts"
        />
        <KPICard
          label="Negative"
          value={`${pctNegative}%`}
          sub={`${sNeg} posts`}
          tone="negative"
          onClick={() => goToPosts('negative')}
          hint="Click to see negative posts"
        />
        <KPICard
          label="P1 Negatives"
          value={priorityData.tiers.P1}
          sub="trust ≥ 0.70 · conf ≥ 0.80"
          tone="negative"
          onClick={scrollToPriority}
          hint="Jump to the priority negatives list (P1)"
        />
        <KPICard
          label="P2 Negatives"
          value={priorityData.tiers.P2}
          sub="trust ≥ 0.50 · conf ≥ 0.60"
          tone="neutral"
          onClick={scrollToPriority}
          hint="Jump to the priority negatives list (P2)"
        />
      </div>
      <button
        onClick={() => goToPosts('neutral')}
        className="text-xs text-gray-500 hover:text-walmart-navy hover:underline text-left"
        title="Click to see neutral posts"
      >
        ↳ Neutral: {pctNeutral}% · {sNeu} posts
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader
            title="Sentiment Distribution"
            subtitle="Click a slice to drill into the post list"
            accent
          />
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie
                data={sentimentPie}
                cx="50%"
                cy="50%"
                outerRadius={85}
                dataKey="value"
                onClick={(e: { key?: 'positive' | 'negative' | 'neutral' }) => e?.key && goToPosts(e.key)}
                label={({ name, value }) => `${name}: ${value} (${total > 0 ? ((value / total) * 100).toFixed(0) : 0}%)`}
                style={{ cursor: 'pointer' }}
              >
                {sentimentPie.map((entry, i) => <Cell key={i} fill={entry.color} />)}
              </Pie>
              <Tooltip formatter={(v: number) => [`${v} posts (${total > 0 ? ((v / total) * 100).toFixed(1) : 0}%)`, 'Count']} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <CardHeader
            title="Volume Trend"
            subtitle={data.trend_granularity === 'hour' ? 'Per hour, selected window' : 'Per day'}
            accent
          />
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={data.trend_7d}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5EDF7" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#74767C' }} />
              <YAxis tick={{ fontSize: 11, fill: '#74767C' }} />
              <Tooltip />
              <Line type="monotone" dataKey="total_posts" stroke="#0071DC" strokeWidth={2.5} name="Posts" dot={{ r: 3, fill: '#0071DC' }} activeDot={{ r: 5, fill: '#FFC220', stroke: '#0071DC' }} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Aspect Breakdown"
          subtitle="Click for drill-down"
          accent
        />
        {sortedAspects.length === 0 ? (
          <p className="text-sm text-gray-500">No aspects detected for this range.</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {sortedAspects.map(([name, count]) => {
              const pctOfMax = maxAspectCount > 0 ? (count / maxAspectCount) * 100 : 0;
              return (
                <Link
                  key={name}
                  to={`/aspects/${encodeURIComponent(name)}?range=${range}`}
                  className="flex flex-col p-3 border border-walmart-navy/10 rounded-xl hover:border-walmart-blue hover:bg-walmart-blue/5 transition-colors min-h-[110px]"
                  title={`${name} — ${count} mentions`}
                >
                  <div className="text-sm font-medium text-walmart-navy capitalize truncate" title={name}>
                    {name.replace(/_/g, ' ')}
                  </div>
                  <div className="flex items-baseline gap-1 mt-auto">
                    <span className="text-xl font-bold text-walmart-navy">{count}</span>
                    <span className="text-xs text-gray-500">mentions</span>
                  </div>
                  <div className="mt-2 w-full bg-walmart-navy/10 rounded-full h-1.5 overflow-hidden">
                    <div
                      className="bg-walmart-blue h-1.5 rounded-full"
                      style={{ width: `${Math.min(100, Math.max(2, pctOfMax)).toFixed(1)}%` }}
                    />
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Subreddit Distribution" accent />
        <div className="flex gap-2 flex-wrap">
          {Object.entries(data.subreddit_distribution)
            .sort(([, a], [, b]) => b - a)
            .map(([name, count]) => (
              <div key={name} className="px-3 py-1.5 bg-walmart-navy/5 border border-walmart-navy/10 rounded-pill text-sm">
                <span className="font-semibold text-walmart-navy">r/{name}</span>
                <span className="ml-2 text-gray-600">{count}</span>
              </div>
            ))}
        </div>
      </Card>

      {data.segment_distribution && Object.keys(data.segment_distribution).length > 0 && (
        <Card>
          <CardHeader title="Segment Distribution" subtitle="Click to filter" accent />
          <div className="flex gap-2 flex-wrap">
            {Object.entries(data.segment_distribution)
              .sort(([, a], [, b]) => b - a)
              .map(([slug, count]) => {
                const label = segments.find(s => s.slug === slug)?.label
                  ?? slug.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                const active = segment === slug;
                return (
                  <button
                    key={slug}
                    onClick={() => setSegment(active ? '' : slug)}
                    className={`px-3 py-1.5 border rounded-pill text-xs transition-colors ${
                      active
                        ? 'bg-walmart-blue text-white border-walmart-blue'
                        : 'bg-white hover:bg-walmart-blue/5 hover:border-walmart-blue/40 border-walmart-navy/15 text-walmart-navy'
                    }`}
                    title={active ? 'Click to clear segment filter' : `Filter to ${label}`}
                  >
                    {label} <span className={active ? 'text-white/80' : 'text-gray-500'}>{count}</span>
                  </button>
                );
              })}
          </div>
        </Card>
      )}

      {data.top_issues.length > 0 && (
        <Card>
          <CardHeader title="Top Issues" accent />
          <div className="space-y-2">
            {data.top_issues.map((issue) => (
              <div key={issue.aspect} className="flex items-center justify-between p-3 bg-sentiment-negative/5 border border-sentiment-negative/15 rounded-xl">
                <span className="text-sm font-semibold text-walmart-navy capitalize">{issue.aspect.replace(/_/g, ' ')}</span>
                <div className="flex items-center gap-4 text-xs text-gray-600">
                  <span>{issue.count} mentions</span>
                  <span className="text-sentiment-negative font-medium">{(issue.negative_ratio * 100).toFixed(0)}% negative</span>
                  <span className="font-mono bg-sentiment-negative/10 text-sentiment-negative px-2 py-0.5 rounded-pill">severity: {issue.severity_score}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <PriorityNegativesSection
        posts={priorityData.posts}
        tiers={priorityData.tiers}
        loading={priorityData.loading}
        error={priorityData.error}
        limit={priorityLimit}
        onLimitChange={setPriorityLimit}
      />
      </>
      )}
    </div>
  );
}

function KPICard({
  label,
  value,
  sub,
  tone,
  onClick,
  hint,
}: {
  label: string;
  value: string | number;
  sub?: string;
  tone?: 'positive' | 'negative' | 'neutral';
  onClick?: () => void;
  hint?: string;
}) {
  const interactive = !!onClick;
  const toneColor =
    tone === 'positive' ? 'text-sentiment-positive'
    : tone === 'negative' ? 'text-sentiment-negative'
    : 'text-walmart-navy';
  const Component = interactive ? 'button' : 'div';
  return (
    <Component
      onClick={onClick}
      title={hint}
      className={`bg-surface rounded-2xl p-4 border border-walmart-navy/10 shadow-card text-left w-full ${
        interactive ? 'hover:border-walmart-blue hover:shadow-card-hover cursor-pointer transition-all' : ''
      }`}
    >
      <div className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold flex items-center justify-between">
        <span>{label}</span>
        {interactive && <span className="text-walmart-blue/60">→</span>}
      </div>
      <div className={`text-2xl font-bold mt-1 ${toneColor}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </Component>
  );
}

/**
 * PriorityNegativesSection — top-N negative posts ranked by trust × confidence.
 *
 * P1 = trusted + high-confidence (urgent action needed)
 * P2 = medium-trust + medium-confidence
 *
 * Click any row → navigates to /review with a focus param so the social
 * team lands directly on the card they need to action.
 */
const TOP_N_OPTIONS = [10, 15, 20, 30, 50, 100] as const;

function PriorityNegativesSection({
  posts,
  tiers,
  loading,
  error: err,
  limit,
  onLimitChange,
}: {
  posts: PriorityNegativePost[];
  tiers: { P1: number; P2: number };
  loading: boolean;
  error: string | null;
  limit: number;
  onLimitChange: (n: number) => void;
}) {
  const navigate = useNavigate();

  const openPost = (p: PriorityNegativePost) => {
    if (p.reddit_url) {
      window.open(p.reddit_url, '_blank', 'noopener,noreferrer');
      return;
    }
    const qs = new URLSearchParams({ focus: p.post_id });
    navigate(`/review?${qs.toString()}`);
  };

  const fmtTime = (ts: number) => {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  };

  const truncate = (s: string, n = 180) =>
    s.length > n ? s.slice(0, n) + '…' : s;

  return (
    <Card id="priority-negatives">
      <div className="flex items-start justify-between gap-4 mb-3 flex-wrap">
        <div>
          <CardHeader
            title="Priority negative posts (P1 / P2)"
            subtitle="Ranked by trust × confidence — click to open on Reddit"
            accent
          />
          <div className="flex items-center gap-2 text-xs mt-1 flex-wrap">
            <span
              className="px-2 py-0.5 rounded-pill bg-sentiment-negative/10 text-sentiment-negative font-semibold"
              title="P1: trust score ≥ 0.70 AND sentiment confidence ≥ 0.80"
            >
              P1 {tiers.P1}
            </span>
            <span
              className="px-2 py-0.5 rounded-pill bg-walmart-spark/20 text-walmart-navy font-semibold"
              title="P2: trust score ≥ 0.50 AND sentiment confidence ≥ 0.60 (and not P1)"
            >
              P2 {tiers.P2}
            </span>
            <span className="text-gray-500">in current window</span>
          </div>
          <div className="text-[11px] text-gray-500 mt-1.5 leading-relaxed">
            <span className="font-semibold text-sentiment-negative">P1</span>
            <span> = trust ≥ 0.70 &amp; confidence ≥ 0.80 · </span>
            <span className="font-semibold text-walmart-navy">P2</span>
            <span> = trust ≥ 0.50 &amp; confidence ≥ 0.60</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-600 font-semibold uppercase tracking-wider">
            Top
          </label>
          <select
            value={limit}
            onChange={(e) => onLimitChange(Number(e.target.value))}
            className={selectClass}
          >
            {TOP_N_OPTIONS.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
      </div>

      {err && (
        <div className="text-sm text-sentiment-negative bg-sentiment-negative/5 border border-sentiment-negative/20 rounded-xl px-3 py-2">
          {err}
        </div>
      )}
      {loading && posts.length === 0 && (
        <div className="text-sm text-gray-400 py-4 text-center">Loading…</div>
      )}
      {!loading && !err && posts.length === 0 && (
        <div className="text-sm text-gray-500 py-6 text-center">
          No P1/P2 negative posts in this window.
        </div>
      )}

      <div className="space-y-2 max-h-[600px] overflow-y-auto">
        {posts.map((p, idx) => {
          const tierClass = p.priority_tier === 'P1'
            ? 'bg-sentiment-negative text-white'
            : 'bg-walmart-spark text-walmart-navy';
          return (
            <button
              key={p.post_id || idx}
              onClick={() => openPost(p)}
              className="w-full text-left p-3 rounded-xl border border-walmart-navy/10 bg-white hover:border-walmart-blue hover:shadow-card-hover transition-all"
              title="Click to open the original post on Reddit"
            >
              <div className="flex items-start justify-between gap-3 mb-1.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`px-2 py-0.5 rounded-pill text-[11px] font-bold shrink-0 ${tierClass}`}>
                    {p.priority_tier}
                  </span>
                  <span className="text-xs text-gray-500 font-mono shrink-0">
                    r/{p.subreddit}
                  </span>
                  <span className="text-xs text-gray-400 shrink-0">
                    {fmtTime(p.created_timestamp)}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-[11px] text-gray-500 shrink-0">
                  <span title="Trust score">T {p.trust_score.toFixed(2)}</span>
                  <span title="Sentiment confidence">C {p.sentiment_confidence.toFixed(2)}</span>
                  <span
                    className="font-mono bg-walmart-navy/5 text-walmart-navy px-1.5 py-0.5 rounded"
                    title="priority_score = trust × confidence"
                  >
                    {p.priority_score.toFixed(3)}
                  </span>
                </div>
              </div>
              {p.title && (
                <div className="text-sm font-semibold text-walmart-navy line-clamp-2 mb-0.5">
                  {p.title}
                </div>
              )}
              {p.text && p.text !== p.title && (
                <div className="text-xs text-gray-600 line-clamp-2">
                  {truncate(p.text)}
                </div>
              )}
              {Array.isArray(p.aspects) && p.aspects.length > 0 && (
                <div className="flex gap-1 flex-wrap mt-1.5">
                  {(p.aspects as string[]).slice(0, 4).map((a) => (
                    <span
                      key={a}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-walmart-blue/10 text-walmart-blue capitalize"
                    >
                      {String(a).replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>
              )}
            </button>
          );
        })}
      </div>
    </Card>
  );
}
