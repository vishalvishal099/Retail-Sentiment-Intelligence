import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, ExplorerPost, DateRange } from '../api';

const SENTIMENTS = ['', 'positive', 'negative', 'neutral'] as const;

const RANGE_LABELS: Record<DateRange | '', string> = {
  '': 'All time',
  '1h': 'Last 1h',
  '2h': 'Last 2h',
  '3h': 'Last 3h',
  '6h': 'Last 6h',
  '12h': 'Last 12h',
  '24h': 'Last 24h',
  today: 'Today',
  yesterday: 'Yesterday',
  week: 'Last 7 Days',
  month: 'Last 30 Days',
  '60d': 'Last 60 Days',
  '90d': 'Last 90 Days',
};

export default function PostExplorer() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [posts, setPosts] = useState<ExplorerPost[]>([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({
    subreddit: searchParams.get('subreddit') || '',
    sentiment: searchParams.get('sentiment') || '',
    aspect: searchParams.get('aspect') || '',
    trust_min: searchParams.get('trust_min') || '',
    range: searchParams.get('range') || '',
    limit: searchParams.get('limit') || '50',
  });

  const runSearch = useCallback(async (f: typeof filters) => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { limit: parseInt(f.limit) || 50 };
      if (f.subreddit) params.subreddit = f.subreddit;
      if (f.sentiment) params.sentiment = f.sentiment;
      if (f.aspect) params.aspect = f.aspect;
      if (f.trust_min) params.trust_min = parseFloat(f.trust_min);
      if (f.range) params.range = f.range;
      const result = await api.getPosts(params);
      setPosts(result.posts);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-search when URL params change (e.g., navigated from BrandHealth)
  useEffect(() => {
    runSearch(filters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearch = () => {
    // Sync to URL so the search is shareable
    const next = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => { if (v) next.set(k, v); });
    setSearchParams(next);
    runSearch(filters);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-2xl font-bold">Post Explorer</h2>
        <div className="flex items-center gap-2 flex-wrap text-xs">
          {filters.sentiment && (
            <span className="px-2 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
              Sentiment: {filters.sentiment}
            </span>
          )}
          {filters.range && (
            <span className="px-2 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
              Range: {RANGE_LABELS[filters.range as DateRange] || filters.range}
            </span>
          )}
          {filters.aspect && (
            <span className="px-2 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
              Aspect: {filters.aspect}
            </span>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white border rounded-lg p-4 flex gap-4 items-end flex-wrap">
        <FilterInput label="Subreddit" value={filters.subreddit} onChange={v => setFilters(f => ({ ...f, subreddit: v }))} placeholder="e.g. walmart" />
        <FilterSelect label="Sentiment" value={filters.sentiment} onChange={v => setFilters(f => ({ ...f, sentiment: v }))} options={[...SENTIMENTS]} />
        <FilterInput label="Aspect" value={filters.aspect} onChange={v => setFilters(f => ({ ...f, aspect: v }))} placeholder="e.g. pricing" />
        <FilterSelect
          label="Range"
          value={filters.range}
          onChange={v => setFilters(f => ({ ...f, range: v }))}
          options={['', '1h', '6h', '24h', 'today', 'yesterday', 'week', 'month', '60d', '90d']}
        />
        <FilterInput label="Min Trust" value={filters.trust_min} onChange={v => setFilters(f => ({ ...f, trust_min: v }))} placeholder="0.0-1.0" />
        <FilterInput label="Limit" value={filters.limit} onChange={v => setFilters(f => ({ ...f, limit: v }))} placeholder="50" />
        <button
          onClick={handleSearch}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>

      {/* Results */}
      <div className="text-xs text-gray-500">
        {loading ? 'Loading…' : `${posts.length} result${posts.length === 1 ? '' : 's'}`}
      </div>
      <div className="space-y-2">
        {posts.length === 0 && !loading && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-900">
            <p className="font-medium">No posts match these filters.</p>
            <p className="text-xs text-amber-800 mt-1">
              Filters use the post's <strong>created time</strong> (when the Redditor wrote it), not when our
              pipeline analyzed it. If "Today" is empty, no posts with this sentiment were written today yet —
              try widening to <strong>Last 24h</strong>, <strong>This week</strong>, or removing the sentiment filter.
            </p>
          </div>
        )}
        {posts.map((post, i) => (
          <article key={post.id || i} className="bg-white border rounded-lg p-3 text-sm hover:border-blue-300 transition-colors">
            <div className="flex items-center gap-2 mb-1 flex-wrap text-xs">
              <SentimentBadge sentiment={post.sentiment} />
              {post.human_validated && (
                <span className="px-2 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200" title="Human-validated">
                  ✓ Validated
                </span>
              )}
              <span className="text-gray-500">r/{post.subreddit}</span>
              {post.author && <span className="text-gray-500">u/{post.author}</span>}
              {post.score !== undefined && <span className="text-gray-500">⬆ {post.score}</span>}
              {post.created_timestamp > 0 && (
                <span className="text-gray-400">{new Date(post.created_timestamp * 1000).toLocaleString()}</span>
              )}
              {typeof post.trust_score === 'number' && (
                <span className="text-gray-400">trust {post.trust_score.toFixed(2)}</span>
              )}
            </div>
            {post.title && <div className="font-semibold text-gray-900 mb-1">{post.title}</div>}
            {post.text && post.text !== post.title && (
              <p className="text-gray-700 line-clamp-3">{post.text}</p>
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
    </div>
  );
}

function FilterInput({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div>
      <label className="text-xs text-gray-500 block mb-1">{label}</label>
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} className="border rounded px-3 py-1.5 text-sm w-32" />
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: readonly string[] }) {
  return (
    <div>
      <label className="text-xs text-gray-500 block mb-1">{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)} className="border rounded px-3 py-1.5 text-sm">
        {options.map(o => <option key={o} value={o}>{o || 'All'}</option>)}
      </select>
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
