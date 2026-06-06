import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { api, AspectPost, DateRange } from '../api';

const LIMIT_OPTIONS = [10, 25, 50, 100, 200];

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

const VALID_RANGES = new Set(RANGE_OPTIONS.map(r => r.value));

export default function AspectDrilldown() {
  const { aspect } = useParams<{ aspect: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialRange = (searchParams.get('range') as DateRange | null);
  const [range, setRange] = useState<DateRange>(
    initialRange && VALID_RANGES.has(initialRange) ? initialRange : 'today'
  );
  const [data, setData] = useState<{
    trend: unknown[];
    posts: AspectPost[];
    returned: number;
    limit: number;
    window_start?: string | null;
    window_end?: string | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState<number>(25);

  useEffect(() => {
    if (!aspect) return;
    setLoading(true);
    api.getAspectDetail(aspect, 14, limit, range)
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [aspect, limit, range]);

  // Keep the URL in sync so the chosen range is shareable / bookmarkable.
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    next.set('range', range);
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range]);

  if (!aspect) return <div className="text-gray-500">No aspect selected.</div>;

  const currentLabel = RANGE_OPTIONS.find(r => r.value === range)?.label ?? range;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-2xl font-bold capitalize">{aspect.replace(/_/g, ' ')} — Aspect Drilldown</h2>
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="aspect-range" className="text-gray-600">Range:</label>
          <select
            id="aspect-range"
            value={range}
            onChange={(e) => setRange(e.target.value as DateRange)}
            className="border border-gray-300 rounded-md px-3 py-1.5 bg-white shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            {RANGE_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Trend */}
      <div className="bg-white rounded-lg p-4 border">
        <h3 className="text-sm font-medium text-gray-700 mb-3">14-Day Trend</h3>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={(data?.trend as Record<string, unknown>[]) || []}>
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Line type="monotone" dataKey="total_posts" stroke="#3b82f6" strokeWidth={2} name="Posts" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Posts */}
      <div className="bg-white rounded-lg p-4 border">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h3 className="text-sm font-medium text-gray-700">
            Posts mentioning <span className="capitalize">{aspect.replace(/_/g, ' ')}</span>
            <span className="ml-2 text-gray-500">· {currentLabel}</span>
            {data && <span className="ml-2 text-gray-500">({data.returned} of up to {data.limit})</span>}
          </h3>
          <div className="flex items-center gap-2 text-sm">
            <label htmlFor="page-size" className="text-gray-600">Show:</label>
            <select
              id="page-size"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="border border-gray-300 rounded-md px-2 py-1 bg-white shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              {LIMIT_OPTIONS.map(n => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>
        </div>

        {loading && <div className="text-gray-500 text-sm py-6">Loading posts…</div>}
        {!loading && data && data.posts.length === 0 && (
          <div className="text-gray-500 text-sm py-6">No posts found for this aspect.</div>
        )}
        {!loading && data && data.posts.length > 0 && (
          <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
            {data.posts.map((post) => (
              <article key={post.id || post.post_id} className="p-3 border rounded-lg hover:border-blue-300 transition-colors">
                <div className="flex items-center gap-2 mb-1 flex-wrap text-xs">
                  <SentimentBadge sentiment={post.sentiment} />
                  <span className="text-gray-500">r/{post.subreddit}</span>
                  {post.author && <span className="text-gray-500">u/{post.author}</span>}
                  {typeof post.score === 'number' && <span className="text-gray-500">⬆ {post.score}</span>}
                  {post.created_timestamp > 0 && (
                    <span className="text-gray-400">
                      {new Date(post.created_timestamp * 1000).toLocaleString()}
                    </span>
                  )}
                  {typeof post.trust_score === 'number' && post.trust_score > 0 && (
                    <span className="text-gray-400">trust {post.trust_score.toFixed(2)}</span>
                  )}
                </div>
                {post.title && (
                  <div className="font-semibold text-gray-900 text-sm mb-1">{post.title}</div>
                )}
                {post.text && post.text !== post.title && (
                  <p className="text-sm text-gray-700 leading-relaxed line-clamp-3">{post.text}</p>
                )}
                {post.reddit_url && (
                  <a
                    href={post.reddit_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-block mt-2 text-xs text-blue-600 hover:text-blue-800 hover:underline font-medium"
                  >
                    View on Reddit ↗
                  </a>
                )}
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SentimentBadge({ sentiment }: { sentiment: string }) {
  const colors: Record<string, string> = {
    positive: 'bg-green-100 text-green-800',
    negative: 'bg-red-100 text-red-800',
    neutral: 'bg-gray-100 text-gray-600',
  };
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[sentiment] || colors.neutral}`}>{sentiment}</span>;
}
