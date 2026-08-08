import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  PieChart, Pie, Cell, LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid, BarChart, Bar,
  RadialBarChart, RadialBar, PolarAngleAxis,
} from 'recharts';
import { api, BrandHealthData, DateRange, SegmentInfo, MacroSegment, PriorityNegativePost, AspectPost } from '../api';
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
  const [priorityData, setPriorityData] = useState<{
    posts: PriorityNegativePost[];
    tiers: { P1: number; P2: number };
    loading: boolean;
    error: string | null;
  }>({ posts: [], tiers: { P1: 0, P2: 0 }, loading: false, error: null });
  const [lifecycleCounts, setLifecycleCounts] = useState<Record<string, number>>({});
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
    api.getLifecycle().then(r => setLifecycleCounts(r.counts || {})).catch(console.error);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setPriorityData(p => ({ ...p, loading: true, error: null }));
    api.getPriorityNegatives(range, 20, segment || null, macroSegment || null)
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
  }, [range, segment, macroSegment]);

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
      {/* KPI Cards — each shows total + replied + pending breakdown */}
      {(() => {
        const lcTotal = Object.values(lifecycleCounts).reduce((a, b) => a + b, 0);
        const lcReplied = (lifecycleCounts.reply_sent || 0) + (lifecycleCounts.issue_fixed || 0) + (lifecycleCounts.resolved || 0);
        const lcPending = (lifecycleCounts.reply_sent || 0) + (lifecycleCounts.issue_fixed || 0);
        const lcResolved = lifecycleCounts.resolved || 0;
        // Ingested-vs-analyzed reconciliation. `data.total_posts` is the
        // number with sentiment (matches downstream %s); `fetched_count` is
        // the number the ingestion pipeline pulled in. They differ by the
        // per-window analysis backlog and this used to look like a bug when
        // compared against the Pipeline page's "Fetched" number.
        const fetched = data.fetched_count ?? data.total_posts;
        const pendingAnalysis = data.pending_analysis ?? Math.max(0, fetched - data.total_posts);
        const analyzedRows: Array<{ label: string; value: number | string; color?: string }> = [
          { label: 'Fetched (ingested)', value: fetched, color: 'text-walmart-navy' },
        ];
        if (pendingAnalysis > 0) {
          analyzedRows.push({ label: 'Pending analysis', value: pendingAnalysis, color: 'text-walmart-spark-dark' });
        }
        analyzedRows.push(
          { label: 'Tracked in lifecycle', value: lcTotal, color: 'text-walmart-navy' },
          { label: 'Addressed & replied', value: lcReplied, color: 'text-sentiment-positive' },
          { label: 'Awaiting action', value: lcPending, color: 'text-walmart-spark-dark' },
        );
        const macroQs = macroSegment ? `&macro=${macroSegment}` : '';
        return (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            <KPICardRich
              label="Analyzed Posts"
              value={data.total_posts}
              rows={analyzedRows}
              onExplore={() => goToPosts()}
              onReview={() => navigate(`/review?range=${range}${macroQs}`)}
              hint={pendingAnalysis > 0
                ? `Posts with sentiment analysis · ${pendingAnalysis.toLocaleString()} still pending (matches Pipeline → Fetched of ${fetched.toLocaleString()})`
                : "Posts with sentiment analysis (matches Pipeline → Fetched)"}
            />
            <KPICardRich
              label="Negative"
              value={`${pctNegative}%`}
              valueSub={`${sNeg} posts`}
              tone="negative"
              rows={[
                { label: 'Reviewed & replied', value: lcReplied, color: 'text-sentiment-positive' },
                { label: 'Pending reply', value: sNeg - lcTotal > 0 ? sNeg - lcTotal : 0, color: 'text-walmart-spark-dark' },
                { label: 'Resolved', value: lcResolved, color: 'text-walmart-blue' },
              ]}
              onExplore={() => goToPosts('negative')}
              onReview={() => navigate(`/review?sentiment=negative&range=${range}${macroQs}`)}
              hint="Negative sentiment posts"
            />
            <KPICardRich
              label="Priority (P1+P2)"
              value={priorityData.tiers.P1 + priorityData.tiers.P2}
              tone="negative"
              rows={[
                { label: 'P1 — urgent', value: priorityData.tiers.P1, color: 'text-sentiment-negative' },
                { label: 'P2 — moderate', value: priorityData.tiers.P2, color: 'text-walmart-spark-dark' },
                { label: 'Resolved', value: lcResolved, color: 'text-sentiment-positive' },
              ]}
              onExplore={() => goToPosts('negative')}
              onReview={() => navigate(`/review?sentiment=negative&range=${range}${macroQs}`)}
              hint="Priority negative posts"
            />
            <KPICardRich
              label="Positive"
              value={`${pctPositive}%`}
              valueSub={`${sPos} posts`}
              tone="positive"
              rows={[
                { label: 'Trusted', value: data.trusted_posts, color: 'text-walmart-navy' },
              ]}
              onExplore={() => goToPosts('positive')}
              onReview={() => navigate(`/review?sentiment=positive&range=${range}${macroQs}`)}
              hint="Positive sentiment posts"
            />
            <KPICardRich
              label="Lifecycle"
              value={lcTotal}
              rows={[
                { label: 'Replied & in progress', value: lcPending, color: 'text-walmart-spark-dark' },
                { label: 'Resolved & closed', value: lcResolved, color: 'text-sentiment-positive' },
                { label: 'Remaining', value: lcTotal - lcResolved > 0 ? lcTotal - lcResolved : 0, color: 'text-walmart-blue' },
              ]}
              onClick={() => navigate('/lifecycle')}
              hint="Open Post Lifecycle"
            />
          </div>
        );
      })()}
      <button
        onClick={() => goToPosts('neutral')}
        className="text-xs text-gray-500 hover:text-walmart-navy hover:underline text-left"
        title="Click to see neutral posts"
      >
        ↳ Neutral: {pctNeutral}% · {sNeu} posts
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <SentimentGauge positive={sPos} negative={sNeg} neutral={sNeu} total={total} />

        <Card>
          <CardHeader
            title="Sentiment Distribution"
            subtitle="Click a slice to drill into the post list"
            accent
          />
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={sentimentPie}
                cx="50%"
                cy="50%"
                outerRadius={80}
                innerRadius={35}
                dataKey="value"
                onClick={(e: { key?: 'positive' | 'negative' | 'neutral' }) => e?.key && goToPosts(e.key)}
                label={({ name, value, x, y, textAnchor }) => (
                  <text x={x} y={y} textAnchor={textAnchor} dominantBaseline="central" fontSize={12} fill="#041E42">
                    {`${name} ${value} (${total > 0 ? ((value / total) * 100).toFixed(0) : 0}%)`}
                  </text>
                )}
                labelLine={{ strokeWidth: 1, stroke: '#74767C' }}
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
        <CardHeader title="Subreddit Distribution" subtitle="Top 10 communities by post volume" accent />
        {(() => {
          const rows = Object.entries(data.subreddit_distribution)
            .sort(([, a], [, b]) => b - a)
            .slice(0, 10)
            .map(([name, count]) => ({ name: `r/${name}`, count }));
          if (rows.length === 0) return <p className="text-xs text-gray-500">No subreddit data.</p>;
          return (
            <ResponsiveContainer width="100%" height={Math.max(220, rows.length * 28)}>
              <BarChart data={rows} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5EDF7" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11, fill: '#74767C' }} />
                <YAxis
                  dataKey="name"
                  type="category"
                  tick={{ fontSize: 11, fill: '#74767C' }}
                  width={140}
                />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #E5EDF7' }} />
                <Bar dataKey="count" fill="#0071DC" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          );
        })()}
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
          <CardHeader
            title="Top Issues"
            subtitle="ranked by number of negative posts — click a row to expand"
            accent
          />
          <div className="space-y-2">
            {data.top_issues.map((issue) => (
              <TopIssueRow key={issue.aspect} issue={issue} range={range} macroSegment={macroSegment || null} />
            ))}
          </div>
        </Card>
      )}

      </>
      )}
    </div>
  );
}

// ─── Sentiment Gauge ──────────────────────────────────────────────────────
// Radial gauge showing the composite sentiment score in [-100, +100]:
//   score = (positive - negative) / total * 100
// Recharts RadialBar renders on a semicircle scaled to [0, 100] percent-filled.
function SentimentGauge({
  positive, negative, neutral, total,
}: { positive: number; negative: number; neutral: number; total: number }) {
  if (total === 0) {
    return (
      <Card>
        <CardHeader title="Sentiment Score" subtitle="No data in window" accent />
        <div className="flex items-center justify-center h-[220px] text-gray-400 text-sm">—</div>
      </Card>
    );
  }
  // Score in -100..+100.
  const raw = ((positive - negative) / total) * 100;
  const score = Math.round(raw * 10) / 10;
  // Map to 0..100 for the RadialBar fill.
  const filled = Math.round(((score + 100) / 2));
  const color = score > 20 ? '#00865A' : score < -20 ? '#DE1C24' : '#F0932B';
  const label = score > 20 ? 'Healthy' : score < -20 ? 'At risk' : 'Neutral';
  const gaugeData = [{ name: 'score', value: filled, fill: color }];
  return (
    <Card>
      <CardHeader
        title="Sentiment Score"
        subtitle={`Weighted −100…+100 across ${total.toLocaleString()} posts`}
        accent
      />
      <div style={{ width: '100%', height: 220 }} className="relative">
        <ResponsiveContainer>
          <RadialBarChart
            cx="50%"
            cy="70%"
            innerRadius="80%"
            outerRadius="130%"
            startAngle={180}
            endAngle={0}
            barSize={22}
            data={gaugeData}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar background={{ fill: '#E5EDF7' }} dataKey="value" cornerRadius={12} />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <div className="text-4xl font-bold" style={{ color }}>{score > 0 ? '+' : ''}{score.toFixed(1)}</div>
          <div className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{label}</div>
        </div>
      </div>
      <div className="flex items-center justify-around text-[11px] text-gray-600 mt-1">
        <span><span className="inline-block w-2 h-2 rounded-full bg-sentiment-negative mr-1" />Neg {negative}</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-gray-400 mr-1" />Neu {neutral}</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-sentiment-positive mr-1" />Pos {positive}</span>
      </div>
    </Card>
  );
}

// ─── Aspect × Day Heatmap ─────────────────────────────────────────────────
/** KPI Card with mini breakdown rows — shows total + sub-stats in one tile */
function KPICardRich({
  label,
  value,
  valueSub,
  tone,
  rows,
  onClick,
  onExplore,
  onReview,
  hint,
}: {
  label: string;
  value: string | number;
  valueSub?: string;
  tone?: 'positive' | 'negative' | 'neutral';
  rows: Array<{ label: string; value: string | number; color?: string }>;
  onClick?: () => void;
  onExplore?: () => void;
  onReview?: () => void;
  hint?: string;
}) {
  const hasDual = !!onExplore && !!onReview;
  const toneColor =
    tone === 'positive' ? 'text-sentiment-positive'
    : tone === 'negative' ? 'text-sentiment-negative'
    : 'text-walmart-navy';
  const handlePrimary = () => {
    if (onExplore) onExplore();
    else if (onClick) onClick();
  };
  return (
    <div className="relative">
      <button
        onClick={handlePrimary}
        title={hint}
        className="bg-surface rounded-2xl p-4 border border-walmart-navy/10 shadow-card text-left w-full hover:border-walmart-blue hover:shadow-card-hover cursor-pointer transition-all"
      >
        <div className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold flex items-center justify-between">
          <span>{label}</span>
          <span className="text-walmart-blue/60">→</span>
        </div>
        <div className={`text-2xl font-bold mt-1 ${toneColor}`}>{value}</div>
        {valueSub && <div className="text-xs text-gray-500 mt-0.5">{valueSub}</div>}
        {rows.length > 0 && (
          <div className="mt-2 pt-2 border-t border-dashed border-walmart-navy/10 space-y-1">
            {rows.map((r) => (
              <div key={r.label} className="flex items-center justify-between text-[11px]">
                <span className="text-gray-500">{r.label}</span>
                <span className={`font-bold ${r.color || 'text-walmart-navy'}`}>{r.value}</span>
              </div>
            ))}
          </div>
        )}
      </button>
      {hasDual && onReview && (
        <button
          onClick={(e) => { e.stopPropagation(); onReview(); }}
          className="absolute right-3 bottom-3 text-[11px] px-2 py-0.5 rounded-pill border border-walmart-navy/15 text-walmart-navy/70 bg-white hover:bg-walmart-blue/5 hover:text-walmart-navy"
          title="Review & Reply"
        >
          💬 Review
        </button>
      )}
    </div>
  );
}

/* ── Expandable Top Issue row ─────────────────────────────────────────────── */

const SENTIMENT_DOT: Record<string, string> = {
  positive: 'bg-sentiment-positive',
  negative: 'bg-sentiment-negative',
  neutral: 'bg-gray-400',
};

function TopIssueRow({
  issue,
  range,
  macroSegment,
}: {
  issue: { aspect: string; count: number; negative_ratio: number; severity_score: number };
  range: DateRange;
  macroSegment: MacroSegment | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const [posts, setPosts] = useState<AspectPost[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetched, setFetched] = useState(false);

  const toggle = () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !fetched) {
      setLoading(true);
      api.getAspectDetail(issue.aspect, 14, 10, range, macroSegment)
        .then((res) => {
          setPosts(res.posts || []);
          setFetched(true);
        })
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  };

  const fmtTime = (ts: number) => {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  const negCount = Math.round(issue.count * issue.negative_ratio);

  return (
    <div className="border border-sentiment-negative/15 rounded-xl overflow-hidden">
      <button
        onClick={toggle}
        className="w-full text-left p-3 bg-sentiment-negative/5 hover:bg-sentiment-negative/10 transition-colors flex items-center justify-between gap-3"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className={`text-base transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`}>▸</span>
          <span className="text-sm font-semibold text-walmart-navy capitalize">{issue.aspect.replace(/_/g, ' ')}</span>
        </div>
        <div className="flex items-center gap-4 text-xs text-gray-600 shrink-0 flex-wrap justify-end">
          <span>{issue.count} mentions</span>
          <span className="text-sentiment-negative font-medium">{(issue.negative_ratio * 100).toFixed(0)}% negative</span>
          <span
            className="font-mono bg-sentiment-negative/10 text-sentiment-negative px-2 py-0.5 rounded-pill cursor-help"
            title={`${issue.count} mentions × ${(issue.negative_ratio * 100).toFixed(0)}% negative = ${issue.severity_score} negative posts about "${issue.aspect}"`}
          >
            {issue.severity_score} negative
          </span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-sentiment-negative/10 bg-white">
          {/* Formula explanation */}
          <div className="px-4 py-2 bg-walmart-navy/[0.02] border-b border-walmart-navy/5 text-[11px] text-gray-500">
            <span className="font-semibold text-sentiment-negative">{negCount}</span> of {issue.count} posts mentioning
            <span className="font-mono mx-1">{issue.aspect}</span>
            are negative
            <span className="mx-2">·</span>
            <span className="text-gray-400">rank = negative posts ({issue.count} × {(issue.negative_ratio * 100).toFixed(0)}%)</span>
          </div>

          {loading && (
            <div className="text-xs text-gray-400 py-4 text-center">Loading posts…</div>
          )}
          {!loading && posts.length === 0 && fetched && (
            <div className="text-xs text-gray-400 py-4 text-center">No posts found for this aspect in the current window.</div>
          )}
          {posts.length > 0 && (
            <div className="divide-y divide-walmart-navy/5 max-h-[400px] overflow-y-auto">
              {posts.map((p) => (
                <a
                  key={p.post_id}
                  href={p.reddit_url || '#'}
                  target={p.reddit_url ? '_blank' : undefined}
                  rel="noopener noreferrer"
                  className="block px-4 py-2.5 hover:bg-walmart-blue/5 transition-colors"
                >
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${SENTIMENT_DOT[p.sentiment] || SENTIMENT_DOT.neutral}`} title={p.sentiment} />
                    <span className="text-xs text-gray-500 font-mono">r/{p.subreddit}</span>
                    <span className="text-xs text-gray-400">{fmtTime(p.created_timestamp)}</span>
                    <span className="text-[10px] text-gray-400 ml-auto shrink-0">
                      T {p.trust_score.toFixed(2)} · C {p.sentiment_confidence.toFixed(2)}
                    </span>
                  </div>
                  {p.title && (
                    <div className="text-sm font-medium text-walmart-navy line-clamp-1">{p.title}</div>
                  )}
                  {p.text && p.text !== p.title && (
                    <div className="text-xs text-gray-600 line-clamp-2 mt-0.5">
                      {p.text.length > 200 ? p.text.slice(0, 200) + '…' : p.text}
                    </div>
                  )}
                </a>
              ))}
            </div>
          )}
          {fetched && posts.length > 0 && (
            <div className="px-4 py-2 border-t border-walmart-navy/5 text-center">
              <Link
                to={`/aspects/${encodeURIComponent(issue.aspect)}?range=${range}`}
                className="text-xs text-walmart-blue hover:underline font-medium"
              >
                View all {issue.aspect.replace(/_/g, ' ')} posts →
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
