import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { PieChart, Pie, Cell, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { api, BrandHealthData, DateRange, PipelineStatus } from '../api';

const COLORS = { positive: '#10b981', negative: '#ef4444', neutral: '#6b7280' };

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
  { value: '60d', label: 'Last 60 Days' },
  { value: '90d', label: 'Last 90 Days' },
];

export default function BrandHealth() {
  const [data, setData] = useState<BrandHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [range, setRange] = useState<DateRange>('today');
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const navigate = useNavigate();

  const loadData = () => {
    setLoading(true);
    api.getBrandHealth(range).then(setData).catch(console.error).finally(() => setLoading(false));
  };

  const loadStatus = () => {
    api.getPipelineStatus().then(setPipelineStatus).catch(console.error);
  };

  useEffect(() => { loadData(); }, [range]);
  useEffect(() => {
    loadStatus();
    const t = setInterval(loadStatus, 5000);
    return () => clearInterval(t);
  }, []);

  // When a pipeline run finishes, refresh the data automatically.
  const prevRunning = pipelineStatus?.running;
  useEffect(() => {
    if (prevRunning === true && pipelineStatus?.running === false) {
      loadData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipelineStatus?.running]);

  const runNow = async () => {
    setRunError(null);
    const res = await api.runPipeline();
    if (!res.started) {
      setRunError(res.reason || 'Could not start pipeline');
    }
    loadStatus();
  };

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
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm rounded-md px-3 py-2">
          {data.fallback_note}
        </div>
      )}
      {data && !data.fallback_note && data.days_requested && data.days_with_data !== undefined &&
        data.days_requested > 1 && data.days_with_data < data.days_requested && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm rounded-md px-3 py-2">
          Only {data.days_with_data} of the last {data.days_requested} days have data — longer ranges will look similar until older history is ingested.
        </div>
      )}
      {runError && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm rounded-md px-3 py-2">
          Run failed: {runError}
        </div>
      )}

      {/* Header with Date Range Selector + Run Now */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-2xl font-bold">Brand Health Overview</h2>
        <div className="flex items-center gap-3 flex-wrap">
          {data && <span className="text-sm text-gray-500">{data.date}</span>}
          <select
            value={range}
            onChange={(e) => setRange(e.target.value as DateRange)}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            {RANGE_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <PipelineButton status={pipelineStatus} onRun={runNow} />
        </div>
      </div>

      {loading && <div className="text-gray-500 p-8">Loading...</div>}
      {!loading && (!data || !data.sentiment_distribution) && (
        <div className="text-gray-500 p-8 bg-white border rounded-lg text-center">
          No data available for this range.
          <div className="text-xs mt-2 text-gray-400">
            Try a wider range, or click <span className="font-semibold">Run Now</span> to fetch fresh data.
          </div>
        </div>
      )}
      {!loading && data && data.sentiment_distribution && (
      <>
      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard label="Total Posts" value={data.total_posts} onClick={() => goToPosts()} hint="View all posts" />
        <KPICard label="Trusted" value={data.trusted_posts} hint="Posts that passed trust filter" />
        <KPICard
          label="Positive"
          value={`${pctPositive}%`}
          sub={`${sPos} posts`}
          color="text-green-600"
          onClick={() => goToPosts('positive')}
          hint="Click to see positive posts"
        />
        <KPICard
          label="Negative"
          value={`${pctNegative}%`}
          sub={`${sNeg} posts`}
          color="text-red-600"
          onClick={() => goToPosts('negative')}
          hint="Click to see negative posts"
        />
      </div>
      {/* Neutral row (less prominent) */}
      <div className="grid grid-cols-1">
        <button
          onClick={() => goToPosts('neutral')}
          className="text-xs text-gray-500 hover:text-gray-800 hover:underline text-left"
          title="Click to see neutral posts"
        >
          ↳ Neutral: {pctNeutral}% · {sNeu} posts
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Sentiment Distribution Pie */}
        <div className="bg-white rounded-lg p-4 border">
          <h3 className="text-sm font-medium text-gray-700 mb-3">Sentiment Distribution <span className="text-xs text-gray-400 font-normal">(click a slice to drill in)</span></h3>
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
        </div>

        {/* Trend */}
        <div className="bg-white rounded-lg p-4 border">
          <h3 className="text-sm font-medium text-gray-700 mb-3">
            Volume Trend{' '}
            <span className="text-xs text-gray-400 font-normal">
              ({data.trend_granularity === 'hour' ? 'per hour, selected window' : 'per day'})
            </span>
          </h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={data.trend_7d}>
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="total_posts" stroke="#3b82f6" strokeWidth={2} name="Posts" dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Aspect Breakdown — fixed-height cards in a responsive grid so labels never overlap */}
      <div className="bg-white rounded-lg p-4 border">
        <h3 className="text-sm font-medium text-gray-700 mb-3">
          Aspect Breakdown <span className="text-xs text-gray-400 font-normal">(click for drill-down)</span>
        </h3>
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
                  className="flex flex-col p-3 border rounded-lg hover:border-blue-500 hover:bg-blue-50 transition-colors min-h-[110px]"
                  title={`${name} — ${count} mentions`}
                >
                  <div className="text-sm font-medium capitalize truncate" title={name}>
                    {name.replace(/_/g, ' ')}
                  </div>
                  <div className="flex items-baseline gap-1 mt-auto">
                    <span className="text-xl font-bold text-gray-800">{count}</span>
                    <span className="text-xs text-gray-500">mentions</span>
                  </div>
                  <div className="mt-2 w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
                    <div
                      className="bg-blue-500 h-1.5 rounded-full"
                      style={{ width: `${Math.min(100, Math.max(2, pctOfMax)).toFixed(1)}%` }}
                    />
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>

      {/* Subreddit Distribution */}
      <div className="bg-white rounded-lg p-4 border">
        <h3 className="text-sm font-medium text-gray-700 mb-3">Subreddit Distribution</h3>
        <div className="flex gap-3 flex-wrap">
          {Object.entries(data.subreddit_distribution)
            .sort(([, a], [, b]) => b - a)
            .map(([name, count]) => (
              <div key={name} className="px-3 py-2 bg-gray-50 border rounded-lg text-sm">
                <span className="font-medium">r/{name}</span>
                <span className="ml-2 text-gray-600">{count} posts</span>
              </div>
            ))}
        </div>
      </div>

      {/* Top Issues */}
      {data.top_issues.length > 0 && (
        <div className="bg-white rounded-lg p-4 border">
          <h3 className="text-sm font-medium text-gray-700 mb-3">Top Issues</h3>
          <div className="space-y-2">
            {data.top_issues.map((issue) => (
              <div key={issue.aspect} className="flex items-center justify-between p-2 bg-red-50 rounded">
                <span className="text-sm font-medium capitalize">{issue.aspect.replace(/_/g, ' ')}</span>
                <div className="flex items-center gap-4 text-xs text-gray-600">
                  <span>{issue.count} mentions</span>
                  <span className="text-red-600">{(issue.negative_ratio * 100).toFixed(0)}% negative</span>
                  <span className="font-mono bg-red-100 px-1.5 py-0.5 rounded">severity: {issue.severity_score}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      </>
      )}
    </div>
  );
}

function PipelineButton({ status, onRun }: { status: PipelineStatus | null; onRun: () => void }) {
  const running = status?.running ?? false;
  const lastFinished = status?.last_finished_at;
  const lastStatus = status?.last_status;
  const interval = status?.interval_minutes ?? 60;
  const nextRun = status?.next_scheduled_run_at;

  const fmtAgo = (iso?: string | null) => {
    if (!iso) return '';
    const ageMs = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(ageMs / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    return `${Math.floor(mins / 60)}h ago`;
  };
  const fmtIn = (iso?: string | null) => {
    if (!iso) return '';
    const ms = new Date(iso).getTime() - Date.now();
    if (ms <= 0) return 'due now';
    const mins = Math.ceil(ms / 60000);
    if (mins < 60) return `in ${mins}m`;
    return `in ${Math.floor(mins / 60)}h ${mins % 60}m`;
  };
  const agoText = fmtAgo(lastFinished);
  const nextText = fmtIn(nextRun);
  const fmtLocal = (iso?: string | null) =>
    iso ? new Date(iso).toLocaleString() : '—';

  const statusColor =
    running ? 'bg-blue-100 text-blue-700 border-blue-200' :
    lastStatus === 'failed' ? 'bg-red-100 text-red-700 border-red-200' :
    lastStatus === 'success' ? 'bg-green-100 text-green-700 border-green-200' :
    'bg-gray-100 text-gray-600 border-gray-200';

  const tooltip =
    `Last run: ${fmtLocal(lastFinished)} (${lastStatus ?? 'never'})\n` +
    `Next scheduled: ${fmtLocal(nextRun)}\n` +
    `Auto-runs every ${interval}m`;

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className={`px-2 py-1 rounded border text-xs leading-tight ${statusColor}`} title={tooltip}>
        {running ? (
          <span>Pipeline running…</span>
        ) : (
          <span>
            <span className="font-semibold">Last:</span> {lastStatus ?? 'never'}
            {agoText && <span className="text-gray-500"> · {agoText}</span>}
            {nextText && (
              <span className="ml-2"><span className="font-semibold">Next:</span> {nextText}</span>
            )}
          </span>
        )}
      </div>
      <button
        onClick={onRun}
        disabled={running}
        className="px-3 py-1.5 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed shadow-sm"
        title={`Trigger a fresh fetch + analysis cycle. Auto-runs every ${interval}m.`}
      >
        {running ? 'Running…' : 'Run Now'}
      </button>
    </div>
  );
}

function KPICard({
  label,
  value,
  color,
  sub,
  onClick,
  hint,
}: {
  label: string;
  value: string | number;
  color?: string;
  sub?: string;
  onClick?: () => void;
  hint?: string;
}) {
  const interactive = !!onClick;
  const Component = interactive ? 'button' : 'div';
  return (
    <Component
      onClick={onClick}
      title={hint}
      className={`bg-white rounded-lg p-4 border text-left w-full ${
        interactive ? 'hover:border-blue-500 hover:bg-blue-50 cursor-pointer transition-colors' : ''
      }`}
    >
      <div className="text-xs text-gray-500 uppercase tracking-wide flex items-center justify-between">
        <span>{label}</span>
        {interactive && <span className="text-gray-300 group-hover:text-blue-500">→</span>}
      </div>
      <div className={`text-2xl font-bold mt-1 ${color || 'text-gray-900'}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-0.5">{sub}</div>}
    </Component>
  );
}
