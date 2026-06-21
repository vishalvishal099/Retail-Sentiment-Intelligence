import { useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCw, ExternalLink, ChevronRight, Bell } from 'lucide-react';
import { api, LifecycleRow, LifecycleState } from '../api';

type ColumnDef = { state: LifecycleState; label: string; tint: string };

const COLUMNS: ColumnDef[] = [
  { state: 'new',          label: 'New',           tint: 'bg-sentiment-negative/10 border-sentiment-negative/30' },
  { state: 'acknowledged', label: 'Acknowledged',  tint: 'bg-walmart-spark/15 border-walmart-spark/40' },
  { state: 'reply_sent',   label: 'Reply sent',    tint: 'bg-walmart-blue/10 border-walmart-blue/30' },
  { state: 'issue_fixed',  label: 'Issue fixed',   tint: 'bg-walmart-sky/10 border-walmart-sky/30' },
  { state: 'resolved',     label: 'Resolved',      tint: 'bg-sentiment-positive/10 border-sentiment-positive/30' },
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

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
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
                <button
                  key={row.post_id}
                  onClick={() => setSelected(row)}
                  className="w-full text-left bg-white rounded-xl shadow-card hover:shadow-card-hover p-3 border border-walmart-navy/5 transition-shadow"
                >
                  <div className="flex items-start justify-between gap-2 mb-1">
                    <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-pill ${PRIORITY_COLOR[row.priority] || PRIORITY_COLOR.medium}`}>
                      {row.priority}
                    </span>
                    <span className="text-[10px] text-gray-500">{relTime(row.created_at)}</span>
                  </div>
                  <div className="text-sm font-medium text-walmart-navy line-clamp-2">{row.title || '(untitled)'}</div>
                  <div className="flex items-center justify-between mt-2 text-[11px] text-gray-600">
                    <span>r/{row.subreddit}</span>
                    {row.top_aspect && <span className="text-walmart-blue">{row.top_aspect}</span>}
                  </div>
                </button>
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
            <Field label="State" value={row.state} />
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
                    {s.replace('_', ' ')} <ChevronRight size={12} />
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
