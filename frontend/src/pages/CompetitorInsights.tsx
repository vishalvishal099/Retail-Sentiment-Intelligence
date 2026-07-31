import { useEffect, useState } from 'react';
import { Loader2, RefreshCw, TrendingUp, Lightbulb, Users } from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
  BarChart, Bar, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
} from 'recharts';
import { api, InsightsPayload, CompetitorTrend } from '../api';

const PRIORITY_STYLE: Record<string, string> = {
  high:   'bg-walmart-spark text-walmart-navy border-walmart-spark-dark',
  medium: 'bg-walmart-sky/20 text-walmart-navy border-walmart-sky',
  low:    'bg-gray-100 text-gray-600 border-gray-200',
};

export default function CompetitorInsights() {
  const [payload, setPayload] = useState<InsightsPayload | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [windowDays, setWindowDays] = useState(7);
  const [trend, setTrend] = useState<CompetitorTrend | null>(null);

  const loadLatest = async () => {
    setLoading(true);
    try {
      // Prefer the on-demand bundle if it exists; fall back to daily.
      const onDemand = await api.getInsightsLatest('competitor_on_demand');
      if (onDemand.available && onDemand.payload) {
        setPayload(onDemand.payload);
        setGeneratedAt(onDemand.generated_at || null);
        return;
      }
      const daily = await api.getInsightsLatest('competitor_daily');
      if (daily.available && daily.payload) {
        setPayload(daily.payload);
        setGeneratedAt(daily.generated_at || null);
      }
    } finally {
      setLoading(false);
    }
  };

  const regenerate = async () => {
    setLoading(true);
    try {
      const res = await api.generateInsights(windowDays);
      setPayload(res.payload);
      setGeneratedAt(res.generated_at);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadLatest(); }, []);
  useEffect(() => {
    api.getCompetitorTrend(Math.max(7, windowDays), 4).then(setTrend).catch(console.error);
  }, [windowDays]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-walmart-navy">Competitor Insights</h1>
          <p className="text-sm text-gray-600 mt-1">
            Pain points and learnings synthesised from competitor subreddit chatter.
            {generatedAt && <span className="ml-2 text-gray-500">· Generated {new Date(generatedAt).toLocaleString()}</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-walmart-navy font-semibold">Window</label>
          <select
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
            className="text-sm border border-walmart-navy/20 rounded-lg px-2 py-1.5 bg-white"
          >
            {[1, 3, 7, 14, 30, 60, 90].map((d) => (
              <option key={d} value={d}>{d} days</option>
            ))}
          </select>
          <button
            onClick={regenerate}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 rounded-pill bg-walmart-blue text-white text-sm font-semibold hover:bg-walmart-blue/90 disabled:opacity-60"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Regenerate
          </button>
        </div>
      </div>

      {!payload && !loading && (
        <div className="bg-surface rounded-2xl shadow-card p-8 text-center text-gray-600">
          No insights generated yet. Click <strong>Regenerate</strong> to compute the first bundle.
        </div>
      )}

      {payload && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <SummaryCard label="Analyses in window" value={String(payload.analyses_count)} />
            <SummaryCard label="Pain points found" value={String(payload.pain_points.length)} />
            <SummaryCard label="Recommendations" value={String(payload.recommendations.length)} />
          </div>

          {/* Multi-line sentiment trend: Walmart vs top competitors */}
          {trend && trend.series.length > 0 && (
            <CompetitorTrendChart trend={trend} />
          )}

          {/* Radar: aspect-level negative-ratio Walmart vs competitors */}
          {payload.walmart_comparison && payload.walmart_comparison.length > 0 && (
            <CompetitorRadar comparison={payload.walmart_comparison} />
          )}

          {/* Share of voice */}
          {trend && trend.share_of_voice.length > 0 && (
            <ShareOfVoice data={trend.share_of_voice} />
          )}

          <div className="bg-surface rounded-2xl shadow-card p-6">
            <h2 className="text-lg font-semibold text-walmart-navy mb-4 flex items-center gap-2">
              <Lightbulb size={18} className="text-walmart-spark-dark" /> What Walmart can learn
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {payload.recommendations.map((rec) => (
                <div
                  key={rec.aspect}
                  className={`border rounded-xl p-4 ${PRIORITY_STYLE[rec.priority] || PRIORITY_STYLE.low}`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-bold uppercase tracking-wider">{rec.aspect}</span>
                    <span className="text-[10px] font-bold uppercase bg-white/50 rounded-pill px-2 py-0.5">{rec.priority}</span>
                  </div>
                  <p className="text-sm leading-snug">{rec.headline}</p>
                  <div className="text-xs mt-2 opacity-80">
                    Competitor neg: {(rec.competitor_negative_ratio * 100).toFixed(0)}% · Walmart neg: {(rec.walmart_negative_ratio * 100).toFixed(0)}% · {rec.supporting_count} posts
                  </div>
                </div>
              ))}
              {payload.recommendations.length === 0 && (
                <div className="text-sm text-gray-500 italic">Not enough signal in this window yet.</div>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-surface rounded-2xl shadow-card p-6">
              <h2 className="text-lg font-semibold text-walmart-navy mb-4 flex items-center gap-2">
                <TrendingUp size={18} className="text-sentiment-negative" /> Top competitor pain points
              </h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] uppercase tracking-wider text-gray-500 text-left border-b border-walmart-navy/10">
                    <th className="py-2">Aspect</th>
                    <th className="py-2 text-right">Posts</th>
                    <th className="py-2 text-right">Neg %</th>
                    <th className="py-2 text-right">vs Walmart</th>
                  </tr>
                </thead>
                <tbody>
                  {payload.pain_points.map((pp) => {
                    const cmp = payload.walmart_comparison.find((c) => c.aspect === pp.aspect);
                    const delta = cmp?.delta || 0;
                    return (
                      <tr key={pp.aspect} className="border-b border-walmart-navy/5 last:border-b-0">
                        <td className="py-2 font-medium text-walmart-navy">{pp.aspect}</td>
                        <td className="py-2 text-right">{pp.total}</td>
                        <td className="py-2 text-right text-sentiment-negative font-semibold">
                          {(pp.negative_ratio * 100).toFixed(0)}%
                        </td>
                        <td className={`py-2 text-right font-semibold ${delta > 0 ? 'text-sentiment-positive' : delta < 0 ? 'text-sentiment-negative' : 'text-gray-500'}`}>
                          {delta > 0 ? '+' : ''}{(delta * 100).toFixed(0)}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="bg-surface rounded-2xl shadow-card p-6">
              <h2 className="text-lg font-semibold text-walmart-navy mb-4 flex items-center gap-2">
                <Users size={18} className="text-walmart-blue" /> Top competitor communities
              </h2>
              <div className="space-y-2">
                {payload.top_competitor_subreddits.map((s, i) => (
                  <div key={s.subreddit} className="flex items-center gap-3">
                    <span className="text-xs font-bold text-gray-400 w-5">#{i + 1}</span>
                    <span className="flex-1 text-sm font-medium text-walmart-navy">r/{s.subreddit}</span>
                    <span className="text-xs text-gray-600">{s.post_count.toLocaleString()} posts</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface rounded-2xl shadow-card px-5 py-4 border border-walmart-navy/5">
      <div className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{label}</div>
      <div className="text-2xl font-bold text-walmart-navy mt-1">{value}</div>
    </div>
  );
}

// ─── Multi-line competitor trend ─────────────────────────────────────────
// One line per series (Walmart baseline + top-N competitors), daily
// sentiment score in [-1, +1].
const SERIES_COLORS = ['#0071DC', '#DE1C24', '#00865A', '#F0932B', '#A020F0', '#4B7BEC'];

function CompetitorTrendChart({ trend }: { trend: CompetitorTrend }) {
  // Recharts wants a single flat array keyed by date, with one column per
  // series. Reshape from series[].points[] into rows[].
  const rows = trend.days.map(date => {
    const row: Record<string, string | number | null> = { date };
    trend.series.forEach(s => {
      const p = s.points.find(pt => pt.date === date);
      row[s.label] = p ? p.score : null;
    });
    return row;
  });
  return (
    <div className="bg-surface rounded-2xl shadow-card p-6">
      <h2 className="text-lg font-semibold text-walmart-navy mb-1 flex items-center gap-2">
        <TrendingUp size={18} className="text-walmart-blue" /> Sentiment trend — Walmart vs top competitors
      </h2>
      <p className="text-xs text-gray-500 mb-3">
        Daily score = (positive − negative) / total, in [−1, +1]. Days with no posts are gapped.
      </p>
      <div style={{ width: '100%', height: 260 }}>
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 5, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#6b7280' }} />
            <YAxis domain={[-1, 1]} tick={{ fontSize: 11, fill: '#6b7280' }} />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {trend.series.map((s, i) => (
              <Line
                key={s.label}
                type="monotone"
                dataKey={s.label}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                strokeWidth={s.label === 'Walmart' ? 2.5 : 1.6}
                dot={{ r: 2 }}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ─── Aspect radar: Walmart vs Competitor negative-ratio per aspect ─────────
function CompetitorRadar({ comparison }: { comparison: InsightsPayload['walmart_comparison'] }) {
  const data = comparison.map(c => ({
    aspect: c.aspect,
    Walmart: Math.round(c.walmart_negative_ratio * 100),
    Competitors: Math.round(c.competitor_negative_ratio * 100),
  }));
  return (
    <div className="bg-surface rounded-2xl shadow-card p-6">
      <h2 className="text-lg font-semibold text-walmart-navy mb-1 flex items-center gap-2">
        <Users size={18} className="text-walmart-blue" /> Aspect radar — negative-ratio comparison
      </h2>
      <p className="text-xs text-gray-500 mb-3">
        Higher = more negative sentiment on that aspect. Lower is better.
      </p>
      <div style={{ width: '100%', height: 320 }}>
        <ResponsiveContainer>
          <RadarChart data={data} outerRadius="75%">
            <PolarGrid stroke="#e5e7eb" />
            <PolarAngleAxis dataKey="aspect" tick={{ fontSize: 11, fill: '#041E42' }} />
            <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fontSize: 10, fill: '#6b7280' }} />
            <Radar name="Walmart" dataKey="Walmart" stroke="#0071DC" fill="#0071DC" fillOpacity={0.35} />
            <Radar name="Competitors" dataKey="Competitors" stroke="#DE1C24" fill="#DE1C24" fillOpacity={0.28} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ─── Share of voice: post volume Walmart vs each competitor ─────────────
function ShareOfVoice({ data }: { data: Array<{ label: string; posts: number }> }) {
  return (
    <div className="bg-surface rounded-2xl shadow-card p-6">
      <h2 className="text-lg font-semibold text-walmart-navy mb-1 flex items-center gap-2">
        <Users size={18} className="text-walmart-blue" /> Share of voice — post volume
      </h2>
      <p className="text-xs text-gray-500 mb-3">
        Total post count across the selected window (Walmart aggregate vs each competitor subreddit).
      </p>
      <div style={{ width: '100%', height: Math.max(200, data.length * 34) }}>
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ top: 5, right: 30, left: 30, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11, fill: '#6b7280' }} />
            <YAxis dataKey="label" type="category" tick={{ fontSize: 11, fill: '#041E42' }} width={120} />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
            <Bar dataKey="posts" fill="#0071DC" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
