import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, ReviewItem, ReviewStats, DateRange } from '../api';
import Card from '../components/Card';
import Button from '../components/Button';

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
  const [sentiment, setSentiment] = useState(urlSentiment);
  const [range, setRange] = useState(urlRange);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const load = (s?: string, r?: string) => {
    const sen = s ?? urlSentiment;
    const ran = r ?? urlRange;
    setLoading(true);
    Promise.all([
      api.getReviewQueue(50, sen || undefined, ran || undefined),
      api.getReviewStats().catch(() => null),
    ])
      .then(([q, st]) => { setItems(q.queue); if (st) setStats(st); })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    setSentiment(urlSentiment);
    setRange(urlRange);
    load(urlSentiment, urlRange);
  }, [urlSentiment, urlRange]);

  const applyFilters = () => {
    const next = new URLSearchParams();
    if (sentiment) next.set('sentiment', sentiment);
    if (range) next.set('range', range);
    setSearchParams(next);
  };

  const clearFilters = () => {
    setSentiment('');
    setRange('');
    setSearchParams({});
  };

  const handleCorrection = async (item: ReviewItem, correctedSentiment: string) => {
    setBusyId(item.id);
    setErrorMsg(null);
    try {
      const res = await api.submitReview(item.post_id || item.id, {
        original_sentiment: item.sentiment,
        corrected_sentiment: correctedSentiment,
        original_aspects: item.aspects,
        subreddit: item.subreddit,
        notes: 'Dashboard correction',
      });
      if (res.status === 'saved') {
        setItems(prev => prev.filter(p => p.id !== item.id));
        // Refresh stats so the "learning" counter updates
        api.getReviewStats().then(setStats).catch(() => undefined);
      } else {
        setErrorMsg('Could not save correction');
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
          <span className="px-3 py-1 rounded-pill bg-walmart-navy/5 text-walmart-navy border border-walmart-navy/15 font-medium">
            {items.length} items pending
          </span>
          {stats && (
            <>
              <span className="px-3 py-1 rounded-pill bg-walmart-blue/10 text-walmart-blue border border-walmart-blue/20 font-medium" title="Total human corrections recorded">
                ✓ {stats.total_corrections} corrections
              </span>
              <span className="px-3 py-1 rounded-pill bg-sentiment-positive/10 text-sentiment-positive border border-sentiment-positive/20 font-medium" title="Auto-replies saved">
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
          <Button onClick={applyFilters} disabled={loading} variant="primary">
            {loading ? 'Loading…' : 'Apply'}
          </Button>
          {(urlSentiment || urlRange) && (
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

      {items.length === 0 ? (
        <Card className="text-center py-12 text-gray-500">
          <p className="text-lg font-semibold text-walmart-navy">All caught up!</p>
          <p className="text-sm">No posts need review right now.</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {items.map(item => (
            <ReviewCard
              key={item.id}
              item={item}
              busy={busyId === item.id}
              onCorrect={handleCorrection}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ReviewCard({
  item,
  busy,
  onCorrect,
}: {
  item: ReviewItem;
  busy: boolean;
  onCorrect: (item: ReviewItem, sentiment: string) => void;
}) {
  type Draft = {
    reply: string;
    model_used: string;
    source: string;
    label?: string;
  };
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selectedIdx, setSelectedIdx] = useState<number>(0);
  const [reply, setReply] = useState<string>(item.reply_text || '');
  const [posting, setPosting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [postedAt, setPostedAt] = useState<string | null>(item.reply_posted_at);
  const [postErr, setPostErr] = useState<string | null>(null);
  const [examplesUsed, setExamplesUsed] = useState<number>(0);
  const [postToReddit, setPostToReddit] = useState(true);
  const [redditStatus, setRedditStatus] = useState<{ kind: 'dry_run' | 'live' | 'error'; msg: string } | null>(null);

  const isNegative = item.sentiment === 'negative';

  const handleGenerate = async () => {
    setPostErr(null);
    setGenerating(true);
    try {
      const res = await api.generateReply(item.post_id || item.id, item.subreddit);
      if (res.status === 'ok') {
        const incoming = (res.drafts && res.drafts.length
          ? res.drafts
          : (res.reply
            ? [{ reply: res.reply, model_used: res.model_used || 'unknown', source: res.source || 'unknown' }]
            : [])) as Draft[];
        if (!incoming.length) {
          setPostErr('No drafts returned');
        } else {
          setDrafts(incoming);
          setSelectedIdx(0);
          setReply(incoming[0].reply);
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
            setRedditStatus({ kind: 'dry_run', msg: 'Reddit OAuth in dry-run — reply was logged, not posted live.' });
          } else if (res.reddit.ok) {
            setRedditStatus({ kind: 'live', msg: `Posted to Reddit (${res.reddit.posted_id || 'ok'}).` });
          } else if (res.reddit.error === 'rate_limited') {
            setRedditStatus({ kind: 'error', msg: `Rate-limited — try again in ${res.reddit.retry_after_seconds || '?'}s.` });
          } else {
            setRedditStatus({ kind: 'error', msg: `Reddit post failed: ${res.reddit.error}` });
          }
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

  return (
    <Card>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <SentimentBadge sentiment={item.sentiment} />
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
          <span className="text-xs text-gray-400 text-center mb-1">Correct to:</span>
          <button
            onClick={() => onCorrect(item, 'positive')}
            disabled={busy}
            className="px-3 py-1.5 text-xs rounded-pill bg-sentiment-positive/10 text-sentiment-positive hover:bg-sentiment-positive/20 border border-sentiment-positive/20 disabled:opacity-50 font-medium"
          >
            ✓ Positive
          </button>
          <button
            onClick={() => onCorrect(item, 'neutral')}
            disabled={busy}
            className="px-3 py-1.5 text-xs rounded-pill bg-walmart-navy/5 text-walmart-navy hover:bg-walmart-navy/10 border border-walmart-navy/15 disabled:opacity-50 font-medium"
          >
            — Neutral
          </button>
          <button
            onClick={() => onCorrect(item, 'negative')}
            disabled={busy}
            className="px-3 py-1.5 text-xs rounded-pill bg-sentiment-negative/10 text-sentiment-negative hover:bg-sentiment-negative/20 border border-sentiment-negative/20 disabled:opacity-50 font-medium"
          >
            ✗ Negative
          </button>
        </div>
      </div>

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
            <button
              onClick={handlePostReply}
              disabled={posting || generating || !reply.trim()}
              className="px-4 py-1.5 text-xs rounded-pill bg-walmart-blue text-white hover:bg-walmart-blue/90 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed shadow-sm font-semibold"
              title="Saves the reply to the audit log. Also posts to Reddit if the toggle is on (and OAuth is live; otherwise it's logged as dry-run)."
            >
              {posting ? 'Posting…' : (postedAt ? 'Re-Post Reply' : 'Post Reply')}
            </button>
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
