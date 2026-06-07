/**
 * Pipeline — Data Operations page
 * ================================
 * Single place for analysts to see what the ingestion + analysis pipeline is
 * doing right now, what it pulled recently, and to manage the subreddit
 * registry (incl. one-off backfills).
 *
 * Sections:
 *   A) Live status strip      — scheduler on/off, next run, last run, Run Now
 *   B) Funnel + media         — fetched → english → long → analyzed → trusted
 *                               and a text/image/video breakdown with caption %
 *   C) Per-subreddit sources  — last 7d volume + last fetch lag
 *   D) Registry editor        — toggle enabled, add, remove, backfill
 *   E) Recent jobs            — last 25 runs with counters + expandable log
 */

import { useEffect, useMemo, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, LabelList,
} from 'recharts';
import {
  Activity, AlertCircle, CheckCircle2, Clock, Loader2, Play, Plus, RefreshCw,
  Trash2, X, ChevronDown, ChevronRight,
} from 'lucide-react';
import {
  api, DateRange, FunnelData, IngestionSource, PipelineJob, PipelineStatus,
  SubredditRegistryEntry,
} from '../api';

const RANGE_OPTIONS: { value: DateRange; label: string }[] = [
  { value: 'today',  label: 'Today' },
  { value: 'week',   label: 'Last 7 days' },
  { value: 'month',  label: 'Last 30 days' },
  { value: '60d',    label: 'Last 60 days' },
  { value: '90d',    label: 'Last 90 days' },
];

const STAGE_COLORS: Record<string, string> = {
  fetched: '#3b82f6',     // blue
  english: '#0ea5e9',     // sky
  long_enough: '#06b6d4', // cyan
  analyzed: '#14b8a6',    // teal
  trusted: '#22c55e',     // green
};

const STAGE_LABEL: Record<string, string> = {
  fetched: 'Fetched',
  english: 'English',
  long_enough: 'Long enough',
  analyzed: 'Analyzed',
  trusted: 'Trusted',
};

export default function Pipeline() {
  const [range, setRange] = useState<DateRange>('week');
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [funnel, setFunnel] = useState<FunnelData | null>(null);
  const [sources, setSources] = useState<IngestionSource[]>([]);
  const [registry, setRegistry] = useState<SubredditRegistryEntry[]>([]);
  const [jobs, setJobs] = useState<PipelineJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionInfo, setActionInfo] = useState<string | null>(null);
  const [showBackfill, setShowBackfill] = useState(false);

  const loadAll = async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const [s, f, src, reg, j] = await Promise.all([
        api.getPipelineStatus(),
        api.getIngestionFunnel(range),
        api.getIngestionSources(range),
        api.getSubredditRegistry(),
        api.getRecentJobs(25),
      ]);
      setStatus(s);
      setFunnel(f);
      setSources(src.sources);
      setRegistry(reg.subreddits);
      setJobs(j.jobs);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Failed to load pipeline data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(true); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [range]);
  useEffect(() => {
    const id = setInterval(() => loadAll(false), 15_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range]);

  const runNow = async () => {
    setActionError(null);
    setActionInfo(null);
    try {
      const r = await api.runPipeline();
      if (!r.started) {
        setActionError(`Could not start: ${r.reason ?? 'unknown'}`);
      } else {
        setActionInfo('Pipeline run started — refreshing every 15s.');
        loadAll(false);
      }
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Run failed');
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-2">
            <Activity className="text-brand-700" size={24} />
            Pipeline
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Ingestion lifecycle, data sources, and run history.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={range}
            onChange={(e) => setRange(e.target.value as DateRange)}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white shadow-sm"
          >
            {RANGE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <button
            onClick={() => loadAll(true)}
            className="px-3 py-1.5 text-sm rounded-md border border-gray-300 bg-white hover:bg-gray-50 flex items-center gap-1"
            title="Refresh all data"
          >
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      {actionError && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm flex items-center justify-between">
          <span><AlertCircle size={14} className="inline mr-1" />{actionError}</span>
          <button onClick={() => setActionError(null)}><X size={14} /></button>
        </div>
      )}
      {actionInfo && (
        <div className="bg-blue-50 border border-blue-200 text-blue-700 px-3 py-2 rounded text-sm flex items-center justify-between">
          <span>{actionInfo}</span>
          <button onClick={() => setActionInfo(null)}><X size={14} /></button>
        </div>
      )}

      {/* A) Live status strip */}
      <StatusStrip status={status} onRun={runNow} loading={loading} />

      {/* B) Funnel + media breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white border rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">
            Ingestion funnel — {RANGE_OPTIONS.find(o => o.value === range)?.label}
          </h3>
          {funnel ? <FunnelChart data={funnel} /> : <div className="text-gray-400 text-sm">Loading…</div>}
        </div>
        <div className="bg-white border rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Media types</h3>
          {funnel ? <MediaBreakdown data={funnel} /> : <div className="text-gray-400 text-sm">Loading…</div>}
        </div>
      </div>

      {/* C) Sources table */}
      <div className="bg-white border rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-700">Sources ({sources.length})</h3>
          <span className="text-xs text-gray-400">Window: {RANGE_OPTIONS.find(o => o.value === range)?.label}</span>
        </div>
        <SourcesTable sources={sources} />
      </div>

      {/* D) Registry editor */}
      <div className="bg-white border rounded-lg p-4">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h3 className="text-sm font-semibold text-gray-700">
            Subreddit registry ({registry.filter(r => r.enabled).length} / {registry.length} enabled)
          </h3>
          <button
            onClick={() => setShowBackfill(true)}
            className="px-3 py-1.5 text-sm rounded-md bg-amber-600 text-white hover:bg-amber-700 flex items-center gap-1 shadow-sm"
            title="Run a one-off historical backfill for selected subreddits"
          >
            <Clock size={14} /> Backfill…
          </button>
        </div>
        <RegistryEditor
          registry={registry}
          onMutated={() => loadAll(false)}
          onError={setActionError}
          onInfo={setActionInfo}
        />
      </div>

      {/* E) Recent jobs */}
      <div className="bg-white border rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Recent jobs ({jobs.length})</h3>
        <JobsList jobs={jobs} />
      </div>

      {showBackfill && (
        <BackfillModal
          registry={registry}
          onClose={() => setShowBackfill(false)}
          onError={setActionError}
          onInfo={(msg) => { setActionInfo(msg); loadAll(false); }}
        />
      )}
    </div>
  );
}

// ─── Section A: Live status strip ───────────────────────────────────────────

function StatusStrip({ status, onRun, loading }: {
  status: PipelineStatus | null; onRun: () => void; loading: boolean;
}) {
  const running = status?.running ?? false;
  const last = status?.last_status;
  const lastFinished = status?.last_finished_at;
  const interval = status?.interval_minutes ?? 60;
  const nextRun = status?.next_scheduled_run_at;
  const fmt = (iso?: string | null) => iso ? new Date(iso).toLocaleString() : '—';
  const ago = (iso?: string | null) => {
    if (!iso) return '';
    const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    return `${Math.floor(m / 60)}h ago`;
  };
  const ttl = (iso?: string | null) => {
    if (!iso) return '';
    const ms = new Date(iso).getTime() - Date.now();
    if (ms <= 0) return 'due now';
    const m = Math.ceil(ms / 60000);
    if (m < 60) return `in ${m}m`;
    return `in ${Math.floor(m / 60)}h ${m % 60}m`;
  };

  return (
    <div className="bg-white border rounded-lg p-4 grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
          running ? 'bg-blue-100 text-blue-700' :
          last === 'failed' ? 'bg-red-100 text-red-700' :
          last === 'success' ? 'bg-green-100 text-green-700' :
          'bg-gray-100 text-gray-500'
        }`}>
          {running ? <Loader2 className="animate-spin" size={20} /> :
           last === 'failed' ? <AlertCircle size={20} /> :
           last === 'success' ? <CheckCircle2 size={20} /> :
           <Activity size={20} />}
        </div>
        <div>
          <div className="text-xs text-gray-500">Last run</div>
          <div className="text-sm font-semibold">
            {running ? 'Running now' : (last ?? 'never')}
            {!running && lastFinished && (
              <span className="text-gray-400 font-normal"> · {ago(lastFinished)}</span>
            )}
          </div>
        </div>
      </div>

      <div>
        <div className="text-xs text-gray-500">Scheduler</div>
        <div className="text-sm">
          {status?.scheduler_enabled
            ? <span className="text-green-600 font-medium">on</span>
            : <span className="text-gray-400">off</span>}
          <span className="text-gray-500"> · every {interval}m</span>
        </div>
      </div>

      <div>
        <div className="text-xs text-gray-500">Next scheduled</div>
        <div className="text-sm font-medium" title={fmt(nextRun)}>
          {ttl(nextRun) || '—'}
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={onRun}
          disabled={running || loading}
          className="px-4 py-2 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed shadow-sm flex items-center gap-2"
        >
          <Play size={16} />
          {running ? 'Running…' : 'Run Now'}
        </button>
      </div>
    </div>
  );
}

// ─── Section B: Funnel + media ──────────────────────────────────────────────

function FunnelChart({ data }: { data: FunnelData }) {
  const chartData = data.funnel.map(f => ({
    name: STAGE_LABEL[f.stage] ?? f.stage,
    count: f.count,
    drop: f.drop_from_prev,
    color: STAGE_COLORS[f.stage] ?? '#94a3b8',
  }));
  const maxCount = Math.max(...chartData.map(d => d.count), 1);
  return (
    <div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} layout="vertical" margin={{ left: 10, right: 60 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" domain={[0, maxCount * 1.1]} hide />
          <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 12 }} />
          <Tooltip formatter={(v: number, _n, p) => [`${v} posts`, p.payload.name]} />
          <Bar dataKey="count" radius={[0, 4, 4, 0]}>
            <LabelList dataKey="count" position="right" fill="#374151" fontSize={12} />
            {chartData.map((c, i) => <Cell key={i} fill={c.color} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="text-xs text-gray-500 mt-2">
        Window: {new Date(data.window_start).toLocaleString()} → {new Date(data.window_end).toLocaleString()}
      </div>
    </div>
  );
}

function MediaBreakdown({ data }: { data: FunnelData }) {
  const m = data.media_breakdown;
  const items = [
    { label: 'Text only',    value: m.text_only,        color: 'bg-blue-100 text-blue-700' },
    { label: 'Image only',   value: m.image_only,       color: 'bg-purple-100 text-purple-700' },
    { label: 'Text + image', value: m.text_plus_image,  color: 'bg-indigo-100 text-indigo-700' },
    { label: 'Video',        value: m.video,            color: 'bg-rose-100 text-rose-700' },
    { label: 'Link only',    value: m.link_only,        color: 'bg-gray-100 text-gray-600' },
  ];
  return (
    <div className="space-y-2">
      {items.map(it => (
        <div key={it.label} className="flex items-center justify-between text-sm">
          <span className={`px-2 py-0.5 rounded text-xs ${it.color}`}>{it.label}</span>
          <span className="font-semibold">{it.value.toLocaleString()}</span>
        </div>
      ))}
      <div className="border-t pt-3 mt-3">
        <div className="text-xs text-gray-500 mb-1">Vision captions</div>
        <div className="flex items-center justify-between text-sm">
          <span>{m.captioned} / {m.images_total} images</span>
          <span className={`font-semibold ${
            m.pct_captioned >= 80 ? 'text-green-600' :
            m.pct_captioned >= 30 ? 'text-amber-600' :
            'text-red-600'
          }`}>{m.pct_captioned}%</span>
        </div>
        <div className="w-full bg-gray-100 rounded h-2 mt-1.5">
          <div
            className="bg-green-500 h-2 rounded"
            style={{ width: `${Math.min(100, m.pct_captioned)}%` }}
          />
        </div>
      </div>
    </div>
  );
}

// ─── Section C: Per-subreddit sources table ─────────────────────────────────

function SourcesTable({ sources }: { sources: IngestionSource[] }) {
  if (sources.length === 0) return <div className="text-sm text-gray-400">No sources configured.</div>;
  const fmtAgo = (ts?: number | null, iso?: string | null) => {
    const t = ts ? ts * 1000 : iso ? new Date(iso).getTime() : null;
    if (!t) return <span className="text-gray-400">never</span>;
    const m = Math.floor((Date.now() - t) / 60000);
    const color = m < 120 ? 'text-green-600' : m < 60 * 24 ? 'text-amber-600' : 'text-red-600';
    const label = m < 60 ? `${m}m ago` :
                  m < 60 * 24 ? `${Math.floor(m / 60)}h ago` :
                  `${Math.floor(m / 1440)}d ago`;
    return <span className={color}>{label}</span>;
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 uppercase border-b">
            <th className="py-2 pr-3">Subreddit</th>
            <th className="py-2 pr-3">Segment</th>
            <th className="py-2 pr-3 text-right">Fetched</th>
            <th className="py-2 pr-3 text-right">Analyzed</th>
            <th className="py-2 pr-3 text-right">Pending</th>
            <th className="py-2 pr-3">Last fetch</th>
            <th className="py-2 pr-3">Status</th>
          </tr>
        </thead>
        <tbody>
          {sources.map(s => (
            <tr key={s.subreddit} className={`border-b last:border-0 ${s.enabled ? '' : 'opacity-50'}`}>
              <td className="py-2 pr-3 font-medium">r/{s.subreddit}</td>
              <td className="py-2 pr-3">
                <span className="text-xs px-1.5 py-0.5 bg-gray-100 rounded">{s.segment}</span>
              </td>
              <td className="py-2 pr-3 text-right tabular-nums">{s.fetched.toLocaleString()}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{s.analyzed.toLocaleString()}</td>
              <td className="py-2 pr-3 text-right tabular-nums">
                {s.pending > 0 ? <span className="text-amber-600">{s.pending}</span> : 0}
              </td>
              <td className="py-2 pr-3 text-xs">{fmtAgo(s.last_fetched_utc, s.last_fetched_at)}</td>
              <td className="py-2 pr-3 text-xs">
                {s.enabled
                  ? <span className="text-green-600">enabled</span>
                  : <span className="text-gray-400">disabled</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Section D: Registry editor + add/remove ────────────────────────────────

function RegistryEditor({
  registry, onMutated, onError, onInfo,
}: {
  registry: SubredditRegistryEntry[];
  onMutated: () => void;
  onError: (s: string) => void;
  onInfo: (s: string) => void;
}) {
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState('');
  const [newGroup, setNewGroup] = useState('Walmart core');
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  // Distinct groups for the "add" dropdown
  const knownGroups = useMemo(() => {
    const set = new Set(registry.map(r => r.group).filter(Boolean));
    return Array.from(set).sort();
  }, [registry]);

  const dirty = Object.keys(pending).length > 0;

  const toggle = (sub: string, current: boolean) => {
    setPending(p => {
      const next = { ...p };
      if (next[sub] !== undefined) {
        // toggling back to original — drop the entry
        delete next[sub];
      } else {
        next[sub] = !current;
      }
      return next;
    });
  };

  const saveToggles = async () => {
    try {
      const r = await api.toggleSubreddits(pending);
      onInfo(`Saved ${r.updated} subreddit change(s).`);
      setPending({});
      onMutated();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Save failed');
    }
  };

  const addNew = async () => {
    if (!newName.trim()) return;
    try {
      const r = await api.addSubreddit(newName.trim(), newGroup, true);
      if (r.error) { onError(r.error); return; }
      onInfo(`Added r/${r.added}.`);
      setNewName('');
      setAdding(false);
      onMutated();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Add failed');
    }
  };

  const doRemove = async (name: string) => {
    try {
      const r = await api.removeSubreddit(name);
      if (r.removed) onInfo(`Removed r/${name}.`);
      else onError(`r/${name} not found in registry.`);
      setConfirmDelete(null);
      onMutated();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Remove failed');
    }
  };

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase border-b">
              <th className="py-2 pr-3 w-16">Enabled</th>
              <th className="py-2 pr-3">Subreddit</th>
              <th className="py-2 pr-3">Group</th>
              <th className="py-2 pr-3">Segment</th>
              <th className="py-2 pr-3 text-right">Subs</th>
              <th className="py-2 pr-3 w-12"></th>
            </tr>
          </thead>
          <tbody>
            {registry.map(r => {
              const effective = pending[r.subreddit] !== undefined ? pending[r.subreddit] : r.enabled;
              const isDirty = pending[r.subreddit] !== undefined;
              return (
                <tr key={r.subreddit} className={`border-b last:border-0 ${isDirty ? 'bg-yellow-50' : ''}`}>
                  <td className="py-2 pr-3">
                    <input
                      type="checkbox"
                      checked={effective}
                      onChange={() => toggle(r.subreddit, r.enabled)}
                      className="w-4 h-4 accent-blue-600 cursor-pointer"
                    />
                  </td>
                  <td className="py-2 pr-3 font-medium">r/{r.subreddit}</td>
                  <td className="py-2 pr-3 text-gray-600">{r.group || '—'}</td>
                  <td className="py-2 pr-3">
                    <span className="text-xs px-1.5 py-0.5 bg-gray-100 rounded">{r.segment}</span>
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums text-gray-500">
                    {r.subscribers ? r.subscribers.toLocaleString() : '—'}
                  </td>
                  <td className="py-2 pr-3">
                    <button
                      onClick={() => setConfirmDelete(r.subreddit)}
                      className="text-red-600 hover:text-red-800"
                      title="Remove from registry"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-4 gap-3 flex-wrap">
        {!adding ? (
          <button
            onClick={() => setAdding(true)}
            className="px-3 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-50 flex items-center gap-1"
          >
            <Plus size={14} /> Add subreddit
          </button>
        ) : (
          <div className="flex items-center gap-2 flex-wrap">
            <input
              type="text"
              placeholder="subreddit name (without r/)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-sm"
              autoFocus
            />
            <select
              value={newGroup}
              onChange={(e) => setNewGroup(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-sm bg-white"
            >
              {knownGroups.map(g => <option key={g} value={g}>{g}</option>)}
            </select>
            <button
              onClick={addNew}
              className="px-3 py-1 text-sm rounded bg-blue-600 text-white hover:bg-blue-700"
            >
              Add
            </button>
            <button
              onClick={() => { setAdding(false); setNewName(''); }}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Cancel
            </button>
          </div>
        )}

        <button
          onClick={saveToggles}
          disabled={!dirty}
          className="px-3 py-1.5 text-sm rounded-md bg-green-600 text-white hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {dirty ? `Save ${Object.keys(pending).length} change(s)` : 'No changes'}
        </button>
      </div>

      {confirmDelete && (
        <ConfirmModal
          title={`Remove r/${confirmDelete}?`}
          body="This hard-deletes the subreddit from the registry. Existing posts already in the database are kept; future runs will simply not pull this subreddit."
          confirmLabel="Remove"
          danger
          onConfirm={() => doRemove(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  );
}

// ─── Section E: Jobs list ───────────────────────────────────────────────────

function JobsList({ jobs }: { jobs: PipelineJob[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  if (jobs.length === 0) return <div className="text-sm text-gray-400">No runs yet.</div>;
  const fmt = (iso?: string | null) => iso ? new Date(iso).toLocaleString() : '—';
  const dur = (ms?: number | null) => {
    if (!ms) return '—';
    if (ms < 1000) return `${ms}ms`;
    const s = ms / 1000;
    if (s < 60) return `${s.toFixed(1)}s`;
    return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  };
  return (
    <div className="space-y-1">
      {jobs.map(j => {
        const isOpen = expanded === j.id;
        const counters = j.counters as Record<string, number | string>;
        const counterChips = Object.entries(counters)
          .filter(([k]) => ['ingested', 'processed', 'trusted', 'analyzed', 'flagged', 'captioned'].includes(k))
          .map(([k, v]) => (
            <span key={k} className="text-xs px-1.5 py-0.5 bg-gray-100 rounded text-gray-700">
              {k}:{String(v)}
            </span>
          ));
        return (
          <div key={j.id} className="border border-gray-100 rounded">
            <button
              onClick={() => setExpanded(isOpen ? null : j.id)}
              className="w-full text-left p-2 hover:bg-gray-50 flex items-center gap-2 flex-wrap"
            >
              {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <span className="text-xs font-mono text-gray-400">{j.id}</span>
              <StatusPill status={j.status} />
              <TriggerPill trigger={j.trigger} />
              <span className="text-xs text-gray-500">{fmt(j.started_at)}</span>
              <span className="text-xs text-gray-400">· {dur(j.duration_ms)}</span>
              <span className="flex items-center gap-1 ml-auto flex-wrap">{counterChips}</span>
            </button>
            {isOpen && (
              <div className="px-3 py-2 border-t bg-gray-50 text-xs">
                {j.error && (
                  <div className="text-red-700 mb-2">
                    <strong>error:</strong> {j.error}
                  </div>
                )}
                {Object.keys(j.params).length > 0 && (
                  <div className="mb-2">
                    <strong className="text-gray-600">params:</strong>{' '}
                    <code className="text-gray-700">{JSON.stringify(j.params)}</code>
                  </div>
                )}
                <strong className="text-gray-600">log tail ({j.log_tail.length} lines):</strong>
                <pre className="bg-white border rounded p-2 mt-1 text-[11px] leading-tight overflow-x-auto whitespace-pre-wrap max-h-64 text-gray-700">
                  {j.log_tail.join('\n') || '(empty)'}
                </pre>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const cls =
    status === 'success' ? 'bg-green-100 text-green-700' :
    status === 'failed' ? 'bg-red-100 text-red-700' :
    status === 'running' ? 'bg-blue-100 text-blue-700' :
    'bg-gray-100 text-gray-600';
  return <span className={`text-xs px-1.5 py-0.5 rounded ${cls}`}>{status}</span>;
}
function TriggerPill({ trigger }: { trigger: string }) {
  const cls =
    trigger === 'manual' ? 'bg-blue-50 text-blue-600' :
    trigger === 'scheduled' ? 'bg-gray-50 text-gray-500' :
    trigger === 'backfill' ? 'bg-amber-50 text-amber-700' :
    'bg-gray-50 text-gray-500';
  return <span className={`text-xs px-1.5 py-0.5 rounded border border-current/20 ${cls}`}>{trigger}</span>;
}

// ─── Backfill modal ─────────────────────────────────────────────────────────

function BackfillModal({
  registry, onClose, onError, onInfo,
}: {
  registry: SubredditRegistryEntry[];
  onClose: () => void;
  onError: (s: string) => void;
  onInfo: (s: string) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 30 * 86400_000).toISOString().slice(0, 10);
  const [from, setFrom] = useState(monthAgo);
  const [to, setTo] = useState(today);
  const [selected, setSelected] = useState<Set<string>>(
    new Set(registry.filter(r => r.enabled).map(r => r.subreddit)),
  );
  const [confirming, setConfirming] = useState(false);

  const toggleSub = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const days = Math.ceil(
    (new Date(to).getTime() - new Date(from).getTime()) / 86400_000,
  );
  const tooBig = days > 366;
  const invalid = !from || !to || days <= 0;

  const submit = async () => {
    try {
      const r = await api.triggerBackfill({
        from: new Date(from).toISOString(),
        to: new Date(to).toISOString(),
        subreddits: Array.from(selected),
      });
      if (!r.started) {
        onError(`Backfill not started: ${r.reason ?? 'unknown'}`);
      } else {
        onInfo(`Backfill started for ${Array.isArray(r.subreddits) ? r.subreddits.length : 'all'} subreddit(s).`);
        onClose();
      }
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Backfill failed');
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-4 border-b flex items-center justify-between">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Clock size={18} /> Backfill
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
        </div>

        <div className="p-4 space-y-4">
          <p className="text-sm text-gray-600">
            One-off historical pull for the selected window and subreddits. The
            current enabled-set is restored automatically when the run finishes.
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 uppercase">From</label>
              <input
                type="date"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm mt-1"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 uppercase">To</label>
              <input
                type="date"
                value={to}
                onChange={(e) => setTo(e.target.value)}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm mt-1"
              />
            </div>
          </div>

          <div className="text-sm">
            Window:{' '}
            {invalid ? <span className="text-red-600">invalid range</span> :
             tooBig ? <span className="text-red-600">{days} days — max is 366</span> :
             <span className="text-gray-700">{days} day{days === 1 ? '' : 's'}</span>}
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs text-gray-500 uppercase">
                Subreddits ({selected.size} selected)
              </label>
              <div className="flex gap-2 text-xs">
                <button
                  onClick={() => setSelected(new Set(registry.map(r => r.subreddit)))}
                  className="text-blue-600 hover:underline"
                >All</button>
                <button
                  onClick={() => setSelected(new Set())}
                  className="text-gray-500 hover:underline"
                >None</button>
                <button
                  onClick={() => setSelected(new Set(registry.filter(r => r.enabled).map(r => r.subreddit)))}
                  className="text-gray-500 hover:underline"
                >Currently enabled</button>
              </div>
            </div>
            <div className="border rounded max-h-48 overflow-y-auto p-2 grid grid-cols-2 gap-1">
              {registry.map(r => (
                <label key={r.subreddit} className="flex items-center gap-2 text-sm hover:bg-gray-50 px-1 py-0.5 rounded cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected.has(r.subreddit)}
                    onChange={() => toggleSub(r.subreddit)}
                    className="accent-blue-600"
                  />
                  <span className={selected.has(r.subreddit) ? '' : 'text-gray-400'}>
                    r/{r.subreddit}
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="p-4 border-t flex items-center justify-end gap-2 bg-gray-50">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded border border-gray-300 bg-white hover:bg-gray-100"
          >Cancel</button>
          <button
            onClick={() => setConfirming(true)}
            disabled={invalid || tooBig || selected.size === 0}
            className="px-4 py-1.5 text-sm rounded bg-amber-600 text-white hover:bg-amber-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >Run backfill</button>
        </div>
      </div>

      {confirming && (
        <ConfirmModal
          title="Confirm backfill"
          body={`This will fetch ${days} day(s) of posts from ${selected.size} subreddit(s) and run them through the full analysis pipeline. The scheduled run will be blocked while it executes. Continue?`}
          confirmLabel="Confirm and run"
          danger={false}
          onConfirm={() => { setConfirming(false); submit(); }}
          onCancel={() => setConfirming(false)}
        />
      )}
    </div>
  );
}

// ─── Generic confirm modal ──────────────────────────────────────────────────

function ConfirmModal({
  title, body, confirmLabel, danger, onConfirm, onCancel,
}: {
  title: string; body: string; confirmLabel: string; danger?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-[60] p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
        <div className="p-4">
          <h3 className="text-lg font-semibold">{title}</h3>
          <p className="text-sm text-gray-600 mt-2">{body}</p>
        </div>
        <div className="p-3 border-t flex items-center justify-end gap-2 bg-gray-50">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-sm rounded border border-gray-300 bg-white hover:bg-gray-100"
          >Cancel</button>
          <button
            onClick={onConfirm}
            className={`px-3 py-1.5 text-sm rounded text-white ${
              danger ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'
            }`}
          >{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
