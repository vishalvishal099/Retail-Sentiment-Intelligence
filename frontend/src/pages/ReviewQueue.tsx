import { useEffect, useState } from 'react';
import { api, ReviewItem, ReviewStats } from '../api';

export default function ReviewQueue() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([api.getReviewQueue(50), api.getReviewStats().catch(() => null)])
      .then(([q, s]) => { setItems(q.queue); if (s) setStats(s); })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

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
          <h2 className="text-2xl font-bold">Review &amp; Validate</h2>
          <p className="text-xs text-gray-500 mt-1">
            Corrections are saved to the analyses table and feed back into all dashboards.
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap text-xs">
          <span className="px-2 py-1 rounded bg-gray-100 text-gray-700 border border-gray-200">
            {items.length} items pending
          </span>
          {stats && (
            <>
              <span className="px-2 py-1 rounded bg-blue-50 text-blue-700 border border-blue-200" title="Total human corrections recorded">
                ✓ {stats.total_corrections} corrections applied
              </span>
              <span className="px-2 py-1 rounded bg-green-50 text-green-700 border border-green-200" title="Auto-replies saved">
                ✉ {stats.total_replies_posted} replies posted
              </span>
            </>
          )}
        </div>
      </div>

      {errorMsg && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm rounded-md px-3 py-2">
          {errorMsg}
        </div>
      )}

      {items.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p className="text-lg">All caught up!</p>
          <p className="text-sm">No posts need review right now.</p>
        </div>
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
    if (!reply.trim()) {
      setPostErr('Reply is empty');
      return;
    }
    setPosting(true);
    try {
      const res = await api.postReply(item.post_id || item.id, reply, item.subreddit);
      if (res.status === 'saved') {
        setPostedAt(res.reply_posted_at || new Date().toISOString());
        try { await navigator.clipboard.writeText(reply); } catch { /* noop */ }
        if (item.reddit_url) window.open(item.reddit_url, '_blank', 'noopener');
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
    <div className="bg-white border rounded-lg p-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <SentimentBadge sentiment={item.sentiment} />
            <span className="text-xs text-gray-500">r/{item.subreddit}</span>
            <span className="text-xs text-gray-400">
              Confidence:{' '}
              <span className={item.sentiment_confidence < 0.75 ? 'text-orange-600 font-medium' : ''}>
                {((item.sentiment_confidence || 0) * 100).toFixed(0)}%
              </span>
            </span>
            <span className="text-xs text-gray-400">
              Trust:{' '}
              <span className={item.trust_score < 0.5 ? 'text-red-600' : 'text-green-600'}>
                {item.trust_score?.toFixed(2)}
              </span>
            </span>
            {item.model && <span className="text-xs text-gray-300">{item.model.split('/').pop()}</span>}
          </div>

          {item.title && <h4 className="text-sm font-semibold text-gray-900 mb-1">{item.title}</h4>}
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
                className="text-blue-600 hover:text-blue-800 hover:underline font-medium"
              >
                View on Reddit ↗
              </a>
            )}
          </div>

          {item.aspects && item.aspects.length > 0 && (
            <div className="flex gap-1 mt-2 flex-wrap">
              {item.aspects.map((asp, i) => (
                <span key={i} className="px-2 py-0.5 rounded bg-blue-50 text-blue-700 text-xs">
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
            className="px-3 py-1.5 text-xs rounded bg-green-50 text-green-700 hover:bg-green-100 border border-green-200 disabled:opacity-50"
          >
            ✓ Positive
          </button>
          <button
            onClick={() => onCorrect(item, 'neutral')}
            disabled={busy}
            className="px-3 py-1.5 text-xs rounded bg-gray-50 text-gray-700 hover:bg-gray-100 border border-gray-200 disabled:opacity-50"
          >
            — Neutral
          </button>
          <button
            onClick={() => onCorrect(item, 'negative')}
            disabled={busy}
            className="px-3 py-1.5 text-xs rounded bg-red-50 text-red-700 hover:bg-red-100 border border-red-200 disabled:opacity-50"
          >
            ✗ Negative
          </button>
        </div>
      </div>

      {/* LLM Reply Draft — two side-by-side candidates */}
      {isNegative && (
        <div className="mt-4 pt-4 border-t border-dashed border-gray-200">
          <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
            <h5 className="text-xs font-medium text-gray-700 uppercase tracking-wide">
              LLM Reply Drafts
              <span className="ml-2 text-gray-400 normal-case font-normal">
                (pick the one that sounds better · edit before posting)
              </span>
            </h5>
            {postedAt && (
              <span className="text-xs text-green-700 bg-green-50 border border-green-200 rounded px-2 py-0.5">
                ✓ Posted {new Date(postedAt).toLocaleString()}
              </span>
            )}
          </div>

          {drafts.length === 0 && !generating && (
            <div className="bg-gray-50 border border-dashed border-gray-300 rounded-md p-3 text-center text-xs text-gray-500">
              No drafts yet. Click <span className="font-semibold">Generate Drafts</span> below — we'll build
              two reply candidates (one content-aware composer + one neural model) so you can pick the better one.
            </div>
          )}
          {generating && (
            <div className="bg-blue-50 border border-blue-200 rounded-md p-3 text-center text-xs text-blue-700">
              ⏳ Generating two drafts… (first call loads the neural model — this may take a few seconds)
            </div>
          )}

          {drafts.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-2">
              {drafts.map((d, i) => {
                const isSelected = i === selectedIdx;
                const sourceColor =
                  d.source === 'llm' ? 'text-green-700' :
                  d.source === 'smart-template' ? 'text-blue-700' : 'text-orange-700';
                const sourceLabel =
                  d.source === 'llm' ? 'LLM-generated' :
                  d.source === 'smart-template' ? 'Smart composer (varies every call)' :
                  d.source;
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => handleSelectDraft(i)}
                    className={`text-left rounded-md border-2 p-3 transition-all ${
                      isSelected
                        ? 'border-indigo-500 bg-indigo-50 shadow-sm'
                        : 'border-gray-200 bg-white hover:border-indigo-300'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] uppercase tracking-wide font-semibold text-gray-600">
                        Draft {String.fromCharCode(65 + i)} · {d.label || d.model_used}
                      </span>
                      {isSelected && (
                        <span className="text-[10px] font-bold text-indigo-700 bg-indigo-100 rounded px-1.5 py-0.5">
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
              <label className="block text-[11px] uppercase tracking-wide font-semibold text-gray-600 mb-1">
                Your reply (edit before posting)
              </label>
              <textarea
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                rows={4}
                className="w-full text-sm border border-gray-300 rounded-md p-2 font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                placeholder="Edit the selected draft before posting…"
              />
              <div className="text-xs text-gray-500 mt-1">
                Few-shot examples used: <span className="font-medium">{examplesUsed}</span>
                {examplesUsed === 0 && (
                  <span className="text-amber-600"> (post your first reply to start the learning loop)</span>
                )}
              </div>
            </>
          )}

          {postErr && <div className="text-xs text-red-600 mt-1">{postErr}</div>}

          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <button
              onClick={handleGenerate}
              disabled={generating || posting}
              className="px-3 py-1.5 text-xs rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed shadow-sm"
              title="Generates two reply candidates: one from the content-aware smart composer (varies every call), one from the neural model. Past analyst-posted replies are used as training context for both."
            >
              {generating ? 'Generating…' : (drafts.length ? '↻ Regenerate Both' : '✨ Generate Drafts')}
            </button>
            <button
              onClick={handlePostReply}
              disabled={posting || generating || !reply.trim()}
              className="px-3 py-1.5 text-xs rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed shadow-sm"
              title="Saves the reply to the audit log, copies it to your clipboard, and opens the Reddit thread."
            >
              {posting ? 'Posting…' : (postedAt ? 'Re-Post Reply' : 'Post Reply to Reddit')}
            </button>
            <span className="text-xs text-gray-500">
              Posted replies become future training examples.
            </span>
          </div>
        </div>
      )}
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
