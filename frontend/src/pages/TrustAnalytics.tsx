import { useEffect, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import { api, TrustStats } from '../api';
import Card from '../components/Card';

const BUCKET_COLORS: Record<string, string> = {
  '0.0-0.2': '#DC3545',
  '0.2-0.4': '#F0932B',
  '0.4-0.6': '#FFC220',
  '0.6-0.8': '#8CC63F',
  '0.8-1.0': '#00865A',
};

export default function TrustAnalytics() {
  const [stats, setStats] = useState<TrustStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [sampleSize, setSampleSize] = useState(2000);
  const [error, setError] = useState<string | null>(null);

  const load = (limit: number) => {
    setLoading(true);
    setError(null);
    api.getTrustStats(limit, 15)
      .then(setStats)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(sampleSize); }, [sampleSize]);

  if (loading && !stats) return <div className="text-gray-500 p-8">Loading trust analytics…</div>;
  if (error) return <div className="text-sentiment-negative p-8">Failed to load: {error}</div>;
  if (!stats) return null;

  const distributionData = Object.entries(stats.distribution).map(([bucket, count]) => ({
    bucket, count, color: BUCKET_COLORS[bucket] || '#999',
  }));
  const filterPieData = [
    { name: 'Trusted', value: stats.trusted, color: '#00865A' },
    { name: 'Flagged', value: stats.flagged, color: '#DC3545' },
  ];
  const flagBreakdownData = Object.entries(stats.flag_breakdown)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 10)
    .map(([flag, count]) => ({ flag, count }));
  const componentData = Object.entries(stats.component_avg)
    .filter(([, v]) => v !== null)
    .map(([k, v]) => ({ component: k, value: v as number }));

  const trustPct = (stats.trust_rate * 100).toFixed(1);
  const botRatePct = ((stats.flagged / Math.max(stats.total, 1)) * 100).toFixed(1);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-walmart-navy">Trust Analytics</h2>
          <p className="text-xs text-gray-500 mt-1">
            How the credibility filter is behaving — distribution, filter rate, low-trust drivers,
            and analyst-reviewable examples. Sampled from the most recent {stats.total.toLocaleString()} posts.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-gray-500">Sample size:</span>
          <select
            value={sampleSize}
            onChange={e => setSampleSize(Number(e.target.value))}
            className="border border-walmart-navy/15 rounded-pill px-3 py-1 text-xs bg-white text-walmart-navy"
          >
            {[500, 1000, 2000, 5000, 10000].map(n => (
              <option key={n} value={n}>{n.toLocaleString()}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total sampled" value={stats.total.toLocaleString()} sub="Recent raw posts" />
        <StatCard
          label="Trust rate"
          value={`${trustPct}%`}
          sub={`≥ ${stats.threshold.toFixed(2)} threshold`}
          tone="positive"
        />
        <StatCard
          label="Filtered out"
          value={stats.flagged.toLocaleString()}
          sub={`${botRatePct}% of sample`}
          tone="negative"
        />
        <StatCard
          label="Threshold"
          value={stats.threshold.toFixed(2)}
          sub="config/pipeline_config.yaml"
          tone="neutral"
        />
      </div>

      {/* Distribution histogram + filter pie */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <h3 className="text-sm font-semibold text-walmart-navy uppercase tracking-wider mb-3">
            Trust score distribution
          </h3>
          <div style={{ width: '100%', height: 260 }}>
            <ResponsiveContainer>
              <BarChart data={distributionData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="bucket" tick={{ fontSize: 11, fill: '#6b7280' }} />
                <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {distributionData.map((d, i) => (
                    <Cell key={i} fill={d.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[11px] text-gray-500 mt-2">
            Green buckets (≥ 0.6) get analyzed. Red/orange buckets (&lt; 0.4) are flagged for analyst review before entering aggregates.
          </p>
        </Card>

        <Card>
          <h3 className="text-sm font-semibold text-walmart-navy uppercase tracking-wider mb-3">
            Filtered vs Kept
          </h3>
          <div style={{ width: '100%', height: 220 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie
                  data={filterPieData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={45}
                  outerRadius={80}
                  paddingAngle={2}
                >
                  {filterPieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Pie>
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* Component averages + flag breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <h3 className="text-sm font-semibold text-walmart-navy uppercase tracking-wider mb-3">
            Trust component averages
          </h3>
          <p className="text-[11px] text-gray-500 mb-3">
            Which sub-scorer is dragging trust down? Combined = 0.4·metadata + 0.3·dedup + 0.3·llm.
          </p>
          {componentData.length === 0 ? (
            <p className="text-xs text-gray-500">No component data recorded on sampled posts.</p>
          ) : (
            <div className="space-y-3">
              {componentData.map(({ component, value }) => (
                <div key={component}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-walmart-navy font-medium capitalize">{component}</span>
                    <span className="text-gray-600 font-mono">{value.toFixed(3)}</span>
                  </div>
                  <div className="w-full h-2 bg-walmart-navy/10 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-walmart-blue"
                      style={{ width: `${value * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <h3 className="text-sm font-semibold text-walmart-navy uppercase tracking-wider mb-3">
            Flag breakdown (why posts were filtered)
          </h3>
          {flagBreakdownData.length === 0 ? (
            <p className="text-xs text-gray-500">No flags recorded — either nothing filtered or LLM check was skipped.</p>
          ) : (
            <div style={{ width: '100%', height: 220 }}>
              <ResponsiveContainer>
                <BarChart data={flagBreakdownData} layout="vertical" margin={{ top: 5, right: 20, left: 60, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: '#6b7280' }} />
                  <YAxis dataKey="flag" type="category" tick={{ fontSize: 11, fill: '#6b7280' }} width={140} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
                  <Bar dataKey="count" fill="#0071ce" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      {/* Low-trust examples for analyst review */}
      <Card>
        <div className="flex items-baseline justify-between mb-3 flex-wrap gap-2">
          <div>
            <h3 className="text-sm font-semibold text-walmart-navy uppercase tracking-wider">
              Low-trust examples (analyst review)
            </h3>
            <p className="text-[11px] text-gray-500 mt-1">
              The lowest-scoring posts from the sample. Analyst can spot false positives (real feedback wrongly filtered) here.
            </p>
          </div>
        </div>
        {stats.low_trust_examples.length === 0 ? (
          <p className="text-xs text-gray-500">No flagged examples in sample.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-gray-500 border-b border-walmart-navy/10">
                  <th className="py-2 pr-3">Trust</th>
                  <th className="py-2 pr-3">Subreddit</th>
                  <th className="py-2 pr-3">Content</th>
                  <th className="py-2 pr-3">Components</th>
                  <th className="py-2 pr-3">Flags</th>
                  <th className="py-2">Link</th>
                </tr>
              </thead>
              <tbody>
                {stats.low_trust_examples.map(ex => (
                  <tr key={ex.id} className="border-b border-walmart-navy/5 hover:bg-walmart-blue/[0.02] align-top">
                    <td className="py-2 pr-3">
                      <span className="font-mono font-semibold text-sentiment-negative">
                        {ex.trust_score.toFixed(2)}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-gray-600 whitespace-nowrap">r/{ex.subreddit}</td>
                    <td className="py-2 pr-3 max-w-md">
                      {ex.title && <div className="font-semibold text-walmart-navy line-clamp-1">{ex.title}</div>}
                      {ex.text && <div className="text-gray-700 leading-snug line-clamp-3">{ex.text}</div>}
                      <div className="text-[10px] text-gray-400 mt-0.5">
                        u/{ex.author || 'unknown'} · ⬆ {ex.score}
                      </div>
                    </td>
                    <td className="py-2 pr-3 font-mono text-[10px] text-gray-600 whitespace-nowrap">
                      {typeof ex.trust_components?.metadata === 'number' && <div>m {ex.trust_components.metadata.toFixed(2)}</div>}
                      {typeof ex.trust_components?.dedup === 'number' && <div>d {ex.trust_components.dedup.toFixed(2)}</div>}
                      {typeof ex.trust_components?.llm === 'number' && <div>l {ex.trust_components.llm.toFixed(2)}</div>}
                    </td>
                    <td className="py-2 pr-3">
                      {(ex.trust_flags && ex.trust_flags.length > 0) ? (
                        <div className="flex flex-wrap gap-1">
                          {ex.trust_flags.slice(0, 3).map((f, i) => (
                            <span key={i} className="px-1.5 py-0.5 rounded text-[10px] bg-walmart-spark/25 text-walmart-navy">
                              {f}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </td>
                    <td className="py-2">
                      {ex.url ? (
                        <a href={ex.url} target="_blank" rel="noopener noreferrer" className="text-walmart-blue hover:underline">
                          ↗
                        </a>
                      ) : <span className="text-gray-300">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'positive' | 'negative' | 'neutral';
}) {
  const valueClass = tone === 'positive' ? 'text-sentiment-positive' :
    tone === 'negative' ? 'text-sentiment-negative' :
    'text-walmart-navy';
  return (
    <Card>
      <div className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{label}</div>
      <div className={`text-2xl font-bold ${valueClass} mt-1`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-500 mt-1">{sub}</div>}
    </Card>
  );
}
