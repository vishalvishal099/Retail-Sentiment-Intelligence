import { useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCw, ExternalLink, ChevronRight, Bell, MessageSquare } from 'lucide-react';
import { api, LifecycleRow, LifecycleState } from '../api';

type ColumnDef = { state: LifecycleState; label: string; tint: string };

const COLUMNS: ColumnDef[] = [
  { state: 'reply_sent',   label: 'Ack & Reply Sent', tint: 'bg-walmart-blue/10 border-walmart-blue/30' },
  { state: 'issue_fixed',  label: 'Actionable Items', tint: 'bg-walmart-sky/10 border-walmart-sky/30' },
  { state: 'resolved',     label: 'Resolved',         tint: 'bg-sentiment-positive/10 border-sentiment-positive/30' },
];

const PRIORITY_COLOR: Record<string, string> = {
  high:   'bg-sentiment-negative/15 text-sentiment-negative',
  medium: 'bg-walmart-spark/20 text-walmart-navy',
  low:    'bg-gray-100 text-gray-600',
};

const NEXT_STATES: Record<LifecycleState, LifecycleState[]> = {
  new:           ['acknowledged'],
  acknowledged:  ['reply_sent', 'resolved'],
  reply_sent:    ['issue_fixed', 'resolved'],
  issue_fixed:   ['resolved'],
  resolved:      [],
};

const STATE_LABELS: Record<string, string> = {
  new: 'New',
  acknowledged: 'Acknowledged',
  reply_sent: 'Ack & Reply Sent',
  issue_fixed: 'Actionable Items',
  resolved: 'Resolved',
};

function relTime(iso?: string | null): string {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'just now';
  const mins = Math.floor(ms / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function PostLifecycle() {
  const [data, setData] = useState<{ counts: Record<string, number>; rows: LifecycleRow[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<LifecycleRow | null>(null);
  const [acting, setActing] = useState(false);
  const [resolveTarget, setResolveTarget] = useState<LifecycleRow | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const res = await api.getLifecycle();
      setData({ counts: res.counts, rows: res.rows });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const byState = useMemo(() => {
    const map: Record<LifecycleState, LifecycleRow[]> = {
      new: [], acknowledged: [], reply_sent: [], issue_fixed: [], resolved: [],
    };
    (data?.rows || []).forEach((r) => {
      if (map[r.state]) map[r.state].push(r);
    });
    return map;
  }, [data]);

  const handleTransition = async (postId: string, to: LifecycleState) => {
    setActing(true);
    try {
      const res = await api.transitionLifecycle(postId, to);
      if (res.ok && res.lifecycle) {
        setSelected(res.lifecycle);
      } else if (res.error) {
        alert(res.error);
      }
      await refresh();
    } finally {
      setActing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-walmart-navy">Post Lifecycle</h1>
          <p className="text-sm text-gray-600 mt-1">
            Auto-created from confidently-negative posts. Slack and email notifications fire on entry (dry-run by default).
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-pill bg-walmart-navy text-white text-sm font-semibold hover:bg-walmart-navy/90 disabled:opacity-60"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {COLUMNS.map((col) => (
          <div key={col.state} className={`rounded-2xl border ${col.tint} p-3 min-h-[420px]`}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-walmart-navy">{col.label}</h3>
              <span className="text-xs font-bold text-walmart-navy bg-white/60 rounded-pill px-2 py-0.5">
                {data?.counts[col.state] ?? 0}
              </span>
            </div>
            <div className="space-y-2">
              {byState[col.state].length === 0 && (
                <div className="text-xs text-gray-500 italic px-1">No posts</div>
              )}
              {byState[col.state].map((row) => (
                <div key={row.post_id} className="bg-white rounded-xl shadow-card hover:shadow-card-hover border border-walmart-navy/5 transition-shadow">
                  <button
                    onClick={() => setSelected(row)}
                    className="w-full text-left p-3"
                  >
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-pill ${PRIORITY_COLOR[row.priority] || PRIORITY_COLOR.medium}`}>
                        {row.priority}
                      </span>
                      <span className="text-[10px] text-gray-500">{relTime(row.created_at)}</span>
                    </div>
                    <div className="text-sm font-medium text-walmart-navy line-clamp-2">{row.title || '(untitled)'}</div>
                    {row.image_caption && (
                      <div className="mt-1.5 flex items-start gap-1.5 bg-walmart-blue/5 border border-walmart-blue/20 rounded-lg p-1.5">
                        {row.image_url && (
                          <img
                            src={row.image_url}
                            alt=""
                            className="w-8 h-8 object-cover rounded shrink-0"
                            loading="lazy"
                            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                          />
                        )}
                        <p className="text-[10px] text-walmart-navy leading-snug line-clamp-2" title={row.image_caption}>
                          <span className="uppercase font-semibold text-walmart-blue tracking-wider">Vision:</span> {row.image_caption}
                        </p>
                      </div>
                    )}
                    <div className="flex items-center justify-between mt-2 text-[11px] text-gray-600">
                      <span>r/{row.subreddit}</span>
                      {row.top_aspect && <span className="text-walmart-blue">{row.top_aspect}</span>}
                    </div>
                  </button>
                  {col.state === 'reply_sent' && (
                    <div className="flex border-t border-walmart-navy/5">
                      <button
                        onClick={() => handleTransition(row.post_id, 'issue_fixed')}
                        disabled={acting}
                        className="flex-1 text-[11px] font-semibold text-walmart-navy py-2 hover:bg-walmart-spark/10 transition-colors disabled:opacity-50 border-r border-walmart-navy/5"
                        title="Needs further action — move to Actionable Items"
                      >
                        ⚡ Action needed
                      </button>
                      <button
                        onClick={() => handleTransition(row.post_id, 'resolved')}
                        disabled={acting}
                        className="flex-1 text-[11px] font-semibold text-sentiment-positive py-2 hover:bg-sentiment-positive/10 transition-colors disabled:opacity-50"
                        title="No further action — close this thread"
                      >
                        ✓ Close
                      </button>
                    </div>
                  )}
                  {col.state === 'issue_fixed' && (
                    <div className="flex border-t border-walmart-navy/5">
                      <button
                        onClick={() => setResolveTarget(row)}
                        disabled={acting}
                        className="flex-1 text-[11px] font-semibold text-walmart-navy py-2 hover:bg-walmart-blue/10 transition-colors disabled:opacity-50 flex items-center justify-center gap-1"
                        title="Resolve — add action notes and optionally notify user"
                      >
                        <MessageSquare size={11} /> Resolve
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <DetailPanel
          row={selected}
          onClose={() => setSelected(null)}
          onTransition={handleTransition}
          acting={acting}
        />
      )}

      {resolveTarget && (
        <ResolveModal
          row={resolveTarget}
          onClose={() => setResolveTarget(null)}
          onResolved={async () => { setResolveTarget(null); await refresh(); }}
        />
      )}
    </div>
  );
}

function ResolveModal({
  row, onClose, onResolved,
}: {
  row: LifecycleRow;
  onClose: () => void;
  onResolved: () => Promise<void>;
}) {
  const [actionNote, setActionNote] = useState('');
  const [replyText, setReplyText] = useState('');
  const [generating, setGenerating] = useState(false);
  const [drafts, setDrafts] = useState<Array<{ reply: string; label?: string; source?: string }>>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  // Two-step flow: after saving reply, show "copied + open Reddit" before final resolve
  const [replySaved, setReplySaved] = useState(false);
  const [copiedToClipboard, setCopiedToClipboard] = useState(false);

  const handleGenerate = async () => {
    setGenerating(true);
    setError('');
    try {
      const res = await api.generateReply(row.post_id, row.subreddit);
      if (res.status === 'ok' && res.drafts && res.drafts.length > 0) {
        setDrafts(res.drafts);
        setReplyText(res.drafts[0].reply);
      } else {
        setError(res.reason || 'Failed to generate drafts');
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setGenerating(false);
    }
  };

  const handleSaveReply = async () => {
    if (!actionNote.trim()) {
      setError('Please describe what action was taken.');
      return;
    }
    if (!replyText.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      await api.postReply(row.post_id, replyText.trim(), row.subreddit);
      // Copy to clipboard so reviewer can paste on Reddit
      try { await navigator.clipboard.writeText(replyText.trim()); setCopiedToClipboard(true); } catch { /* noop */ }
      setReplySaved(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleOpenReddit = () => {
    const url = row.reddit_url || `https://www.reddit.com/r/${row.subreddit}/comments/${row.post_id}`;
    window.open(url, '_blank', 'noopener');
  };

  const handleFinalResolve = async () => {
    if (!actionNote.trim()) {
      setError('Please describe what action was taken.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const res = await api.transitionLifecycle(row.post_id, 'resolved');
      if (res.ok) {
        await onResolved();
      } else {
        setError(res.error || 'Failed to resolve');
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-walmart-navy/40 backdrop-blur-sm" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-surface rounded-2xl shadow-card-hover w-full max-w-xl max-h-[90vh] overflow-y-auto"
      >
        <div className="px-6 py-4 border-b border-walmart-navy/10">
          <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">Resolve Actionable Item</div>
          <h2 className="text-base font-bold text-walmart-navy line-clamp-2">{row.title || row.post_id}</h2>
          <div className="text-xs text-gray-500 mt-1">r/{row.subreddit} · {row.top_aspect || 'general'}</div>
        </div>

        <div className="p-6 space-y-4">
          {/* Action taken (required) */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1.5">
              Action taken <span className="text-sentiment-negative">*</span>
            </label>
            <textarea
              value={actionNote}
              onChange={(e) => setActionNote(e.target.value)}
              rows={2}
              placeholder="e.g. Escalated to store manager, refund issued, contacted customer via DM..."
              className="w-full text-sm border border-walmart-navy/15 rounded-xl p-3 focus:ring-2 focus:ring-walmart-blue focus:border-walmart-blue"
            />
          </div>

          {/* LLM response section */}
          <div className="border-t border-dashed border-walmart-navy/15 pt-4">
            <div className="flex items-center justify-between mb-2">
              <label className="text-[11px] uppercase tracking-wider text-gray-600 font-semibold">
                Reply to user (optional)
              </label>
              <button
                onClick={handleGenerate}
                disabled={generating}
                className="text-xs font-semibold text-walmart-blue hover:text-walmart-blue/80 disabled:opacity-50 flex items-center gap-1"
              >
                {generating ? <Loader2 size={12} className="animate-spin" /> : <MessageSquare size={12} />}
                {generating ? 'Generating...' : 'Generate "issue fixed" response'}
              </button>
            </div>

            {drafts.length > 0 && (
              <div className="grid grid-cols-1 gap-2 mb-3">
                {drafts.map((d, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setReplyText(d.reply)}
                    className={`text-left rounded-xl border-2 p-3 transition-all ${
                      replyText === d.reply
                        ? 'border-walmart-blue bg-walmart-blue/5'
                        : 'border-walmart-navy/10 bg-white hover:border-walmart-blue/40'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] uppercase tracking-wider font-semibold text-gray-500">
                        {d.label || `Draft ${String.fromCharCode(65 + i)}`}
                      </span>
                      {replyText === d.reply && (
                        <span className="text-[9px] font-bold text-walmart-navy bg-walmart-spark rounded-pill px-2 py-0.5">✓</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-800 leading-snug whitespace-pre-wrap line-clamp-3">{d.reply}</p>
                  </button>
                ))}
              </div>
            )}

            <textarea
              value={replyText}
              onChange={(e) => setReplyText(e.target.value)}
              rows={3}
              placeholder="Leave empty to resolve without notifying the user, or generate/write a response above..."
              className="w-full text-sm border border-walmart-navy/15 rounded-xl p-3 focus:ring-2 focus:ring-walmart-blue focus:border-walmart-blue"
            />
          </div>

          {error && (
            <div className="text-xs text-sentiment-negative bg-sentiment-negative/5 border border-sentiment-negative/20 rounded-xl px-3 py-2">
              {error}
            </div>
          )}

          {/* Step 2: After reply saved — open Reddit + finalize */}
          {replySaved ? (
            <div className="space-y-3 pt-2">
              <div className="flex items-center gap-2 text-sm text-sentiment-positive font-semibold">
                <ChevronRight size={14} />
                Reply saved{copiedToClipboard ? ' & copied to clipboard' : ''}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={handleOpenReddit}
                  className="flex-1 px-4 py-2.5 rounded-pill bg-walmart-blue text-white text-sm font-semibold hover:bg-walmart-blue/90 flex items-center justify-center gap-2"
                >
                  <ExternalLink size={14} />
                  Open on Reddit & paste reply
                </button>
                <button
                  onClick={handleFinalResolve}
                  disabled={submitting}
                  className="flex-1 px-4 py-2.5 rounded-pill bg-sentiment-positive text-white text-sm font-semibold hover:bg-sentiment-positive/90 disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {submitting ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} />}
                  Mark Resolved
                </button>
              </div>
              <button
                onClick={onClose}
                className="w-full text-center text-xs text-gray-500 hover:text-walmart-navy py-1"
              >
                Cancel (reply already saved)
              </button>
            </div>
          ) : (
            /* Step 1: Write action note + optionally generate reply */
            <div className="flex gap-3 pt-2">
              {replyText.trim() ? (
                <button
                  onClick={handleSaveReply}
                  disabled={submitting}
                  className="flex-1 px-4 py-2.5 rounded-pill bg-walmart-blue text-white text-sm font-semibold hover:bg-walmart-blue/90 disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {submitting ? <Loader2 size={14} className="animate-spin" /> : <MessageSquare size={14} />}
                  Save reply & open Reddit
                </button>
              ) : (
                <button
                  onClick={handleFinalResolve}
                  disabled={submitting}
                  className="flex-1 px-4 py-2.5 rounded-pill bg-sentiment-positive text-white text-sm font-semibold hover:bg-sentiment-positive/90 disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {submitting ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} />}
                  Resolve (no reply needed)
                </button>
              )}
              <button
                onClick={onClose}
                className="px-4 py-2.5 rounded-pill border border-walmart-navy/20 text-walmart-navy text-sm font-semibold hover:bg-walmart-navy/5"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DetailPanel({
  row, onClose, onTransition, acting,
}: {
  row: LifecycleRow;
  onClose: () => void;
  onTransition: (postId: string, to: LifecycleState) => Promise<void>;
  acting: boolean;
}) {
  const next = NEXT_STATES[row.state] || [];
  return (
    <div className="fixed inset-0 z-30 flex items-end md:items-center justify-center bg-walmart-navy/40 backdrop-blur-sm" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-surface rounded-t-2xl md:rounded-2xl shadow-card-hover w-full md:max-w-2xl max-h-[90vh] overflow-y-auto"
      >
        <div className="px-6 py-4 border-b border-walmart-navy/10 flex items-center justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">Lifecycle detail</div>
            <h2 className="text-lg font-bold text-walmart-navy line-clamp-2">{row.title || row.post_id}</h2>
          </div>
          <button onClick={onClose} className="text-walmart-navy/60 hover:text-walmart-navy text-xl leading-none">×</button>
        </div>

        <div className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Field label="State" value={STATE_LABELS[row.state] || row.state} />
            <Field label="Priority" value={row.priority} />
            <Field label="Subreddit" value={`r/${row.subreddit}`} />
            <Field label="Top aspect" value={row.top_aspect || '—'} />
            <Field label="Sentiment" value={`${row.sentiment_score.toFixed(2)} · ${(row.sentiment_confidence * 100).toFixed(0)}% conf`} />
            <Field label="Created" value={relTime(row.created_at)} />
          </div>

          {row.reddit_url && (
            <a
              href={row.reddit_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-walmart-blue text-sm hover:underline"
            >
              Open on Reddit <ExternalLink size={12} />
            </a>
          )}

          {next.length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-2 font-semibold">Move to</div>
              <div className="flex flex-wrap gap-2">
                {next.map((s) => (
                  <button
                    key={s}
                    onClick={() => onTransition(row.post_id, s)}
                    disabled={acting}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-pill bg-walmart-blue text-white text-xs font-semibold hover:bg-walmart-blue/90 disabled:opacity-60"
                  >
                    {STATE_LABELS[s] || s.replace('_', ' ')} <ChevronRight size={12} />
                  </button>
                ))}
              </div>
            </div>
          )}

          <div>
            <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-2 font-semibold flex items-center gap-1.5">
              <Bell size={12} /> History
            </div>
            <div className="space-y-1.5">
              {(row.history || []).map((h, i) => (
                <div key={i} className="text-xs flex items-start gap-2">
                  <span className="text-gray-500 font-mono whitespace-nowrap">{relTime(h.at)}</span>
                  <span className="text-walmart-navy">
                    {h.from_state ? `${h.from_state} → ` : ''}<strong>{h.to_state}</strong>
                    <span className="text-gray-500"> · {h.by}</span>
                    {h.note && <span className="text-gray-700"> — {h.note}</span>}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">{label}</div>
      <div className="text-sm text-walmart-navy mt-0.5">{value}</div>
    </div>
  );
}
