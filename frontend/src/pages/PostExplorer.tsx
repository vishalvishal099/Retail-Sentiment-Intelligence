import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, ExplorerPost, DateRange } from '../api';
import Card from '../components/Card';
import Button from '../components/Button';

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
        <div>
          <h2 className="text-2xl font-bold text-walmart-navy">Post Explorer</h2>
          <p className="text-xs text-gray-500 mt-1">Search the analyzed-post archive by subreddit, sentiment, aspect or trust score.</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap text-xs">
          {filters.sentiment && (
            <span className="px-3 py-1 rounded-pill bg-walmart-blue/10 text-walmart-blue border border-walmart-blue/20">
              Sentiment: {filters.sentiment}
            </span>
          )}
          {filters.range && (
            <span className="px-3 py-1 rounded-pill bg-walmart-blue/10 text-walmart-blue border border-walmart-blue/20">
              Range: {RANGE_LABELS[filters.range as DateRange] || filters.range}
            </span>
          )}
          {filters.aspect && (
            <span className="px-3 py-1 rounded-pill bg-walmart-blue/10 text-walmart-blue border border-walmart-blue/20">
              Aspect: {filters.aspect}
            </span>
          )}
        </div>
      </div>

      {/* Filters */}
      <Card>
        <div className="flex gap-4 items-end flex-wrap">
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
          <Button onClick={handleSearch} disabled={loading} variant="primary">
            {loading ? 'Searching…' : 'Search'}
          </Button>
        </div>
      </Card>

      <div className="text-xs text-gray-500">
        {loading ? 'Loading…' : `${posts.length} result${posts.length === 1 ? '' : 's'}`}
      </div>
      <div className="space-y-2">
        {posts.length === 0 && !loading && (
          <div className="bg-walmart-spark/10 border border-walmart-spark/40 rounded-xl p-4 text-sm text-walmart-navy">
            <p className="font-semibold">No posts match these filters.</p>
            <p className="text-xs mt-1 text-walmart-navy/80">
              Filters use the post's <strong>created time</strong> (when the Redditor wrote it), not when our
              pipeline analyzed it. If "Today" is empty, no posts with this sentiment were written today yet —
              try widening to <strong>Last 24h</strong>, <strong>This week</strong>, or removing the sentiment filter.
            </p>
          </div>
        )}
        {posts.map((post, i) => (
          <article key={post.id || i} className="bg-surface border border-walmart-navy/10 rounded-2xl shadow-card p-3 text-sm hover:border-walmart-blue/40 transition-colors">
            <div className="flex items-center gap-2 mb-1 flex-wrap text-xs">
              <SentimentBadge sentiment={post.sentiment} />
              {post.human_validated && (
                <span className="px-2 py-0.5 rounded-pill bg-walmart-spark/20 text-walmart-navy border border-walmart-spark/40" title="Human-validated">
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
            {post.title && <div className="font-semibold text-walmart-navy mb-1">{post.title}</div>}
            {post.text && post.text !== post.title && (
              <p className="text-gray-700 line-clamp-3">{post.text}</p>
            )}
            {post.reddit_url && (
              <a
                href={post.reddit_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block mt-2 text-xs text-walmart-blue hover:underline font-medium"
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
      <label className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold block mb-1">{label}</label>
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} className="border border-walmart-navy/15 rounded-pill px-3 py-1.5 text-sm w-32 focus:outline-none focus:ring-2 focus:ring-walmart-blue focus:border-walmart-blue" />
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: readonly string[] }) {
  return (
    <div>
      <label className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold block mb-1">{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)} className="border border-walmart-navy/15 rounded-pill px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-walmart-blue focus:border-walmart-blue">
        {options.map(o => <option key={o} value={o}>{o || 'All'}</option>)}
      </select>
    </div>
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
