/**
 * Pipeline — Data Operations page
 * ================================
 * Single place for analysts to see what the ingestion + analysis pipeline is
 * doing right now, what it pulled recently, and to manage the subreddit
 * registry (incl. one-off backfills).
 *
 * Sections:
 *   A) Live status strip      — scheduler on/off (6h), next run, last run, Run Now with timeframe
 *   B) Funnel + media         — clickable stages with detail panel + vision failure breakdown
 *   C) Per-subreddit sources  — collapsible, shows summary when closed
 *   D) Registry editor        — collapsible, shows summary when closed
 *   E) Recent jobs            — shows last 5, expandable to 20
 */

import { useEffect, useMemo, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, LabelList,
} from 'recharts';
import {
  Activity, AlertCircle, CheckCircle2, Clock, Loader2, Play, Plus, RefreshCw,
  Square, Trash2, X, ChevronDown, ChevronRight, Eye, EyeOff, Info,
} from 'lucide-react';
import {
  api, DateRange, FunnelData, IngestionSource, IngestProgress, PipelineCursor, PipelineJob, PipelineStatus,
  SubredditRegistryEntry,
  AnalysisBacklog, GapReport, FillGapsPlanEntry,
  ImageFailuresReport,
} from '../api';

const RANGE_OPTIONS: { value: DateRange; label: string }[] = [
  { value: '24h',       label: 'Last 24 hours' },
  { value: 'today',     label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'week',      label: 'Last 7 days' },
  { value: 'month',     label: 'Last 30 days' },
  { value: '60d',       label: 'Last 60 days' },
  { value: '90d',       label: 'Last 90 days' },
];

/** Lookback options for manual pipeline trigger (hours) */
const LOOKBACK_OPTIONS = [
  { value: 1,    label: '1 hour' },
  { value: 6,    label: '6 hours' },
  { value: 24,   label: '24 hours' },
  { value: 168,  label: '7 days' },
  { value: 720,  label: '30 days' },
  { value: 2160, label: '90 days' },
  { value: 4320, label: '6 months' },
];

/** Pipeline stages for progress visualization (matches src/pipeline.py order).
 *  counterKey  → live per-cycle count (resets every run) from status.last_counters
 */
const PIPELINE_STAGES: {
  key: string; label: string; counterKey?: string;
}[] = [
  { key: 'ingest',    label: 'Ingest',      counterKey: 'ingested'  },
  { key: 'vision',    label: 'Vision',      counterKey: 'captioned' },
  { key: 'trust',     label: 'Trust Score', counterKey: 'trusted'   },
  { key: 'analyze',   label: 'Analyze',     counterKey: 'analyzed'  },
  { key: 'aggregate', label: 'Aggregate' },
];

/** Map backend `current_stage` strings onto PIPELINE_STAGES indices. */
const STAGE_TO_IDX: Record<string, number> = {
  ingest: 0,
  vision: 1,
  trust: 2,
  analyze: 3,
  aggregate: 4,
};

const STAGE_COLORS: Record<string, string> = {
  fetched: '#0071DC',
  english: '#4DBDF5',
  long_enough: '#3A93E8',
  analyzed: '#005FB8',
  trusted: '#00865A',
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
  const [cursors, setCursors] = useState<PipelineCursor[]>([]);
  const [overlapSeconds, setOverlapSeconds] = useState<number>(300);
  const [gaps, setGaps] = useState<GapReport | null>(null);
  const [backlog, setBacklog] = useState<AnalysisBacklog | null>(null);
  const [imageFailures, setImageFailures] = useState<ImageFailuresReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionInfo, setActionInfo] = useState<string | null>(null);
  const [showBackfill, setShowBackfill] = useState(false);
  const [showFlush, setShowFlush] = useState(false);
  // Req 6: collapsible sections
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [registryOpen, setRegistryOpen] = useState(false);
  const [coverageOpen, setCoverageOpen] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  // Req 3: jobs show 5 by default
  const [showAllJobs, setShowAllJobs] = useState(false);

  const loadAll = async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const [s, f, src, reg, j, c, g, bl, imgs] = await Promise.all([
        api.getPipelineStatus(),
        api.getIngestionFunnel(range),
        api.getIngestionSources(range),
        api.getSubredditRegistry(),
        api.getRecentJobs(20),
        api.getPipelineCursors(),
        api.getPipelineGaps(6),
        api.getAnalysisBacklog(),
        api.getImageFailures(50),
      ]);
      setStatus(s);
      setFunnel(f);
      setSources(src.sources);
      setRegistry(reg.subreddits);
      setJobs(j.jobs);
      setCursors(c.cursors);
      setOverlapSeconds(c.overlap_seconds);
      setGaps(g);
      setBacklog(bl);
      setImageFailures(imgs);
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

  const runNow = async (lookbackHours?: number) => {
    setActionError(null);
    setActionInfo(null);
    try {
      const r = await api.runPipeline(lookbackHours);
      if (!r.started) {
        setActionError(`Could not start: ${r.reason ?? 'unknown'}`);
      } else {
        const label = lookbackHours ? LOOKBACK_OPTIONS.find(o => o.value === lookbackHours)?.label : 'default';
        setActionInfo(`Pipeline run started (${label} lookback) — refreshing every 15s.`);
        loadAll(false);
      }
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Run failed');
    }
  };

  const stopNow = async () => {
    setActionError(null);
    setActionInfo(null);
    try {
      const r = await api.stopPipeline();
      if (!r.stopped) {
        setActionError(`Could not stop: ${r.reason ?? 'unknown'}`);
      } else {
        setActionInfo('Pipeline run stopped.');
        loadAll(false);
      }
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Stop failed');
    }
  };

  // Req 3: visible jobs (5 default, expandable to 20)
  const visibleJobs = showAllJobs ? jobs : jobs.slice(0, 5);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-2 text-walmart-navy">
            <Activity className="text-walmart-blue" size={24} />
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
            className="border border-walmart-navy/15 rounded-pill px-4 py-1.5 text-sm bg-white shadow-sm text-walmart-navy focus:outline-none focus:ring-2 focus:ring-walmart-blue"
          >
            {RANGE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <button
            onClick={() => loadAll(true)}
            className="px-4 py-1.5 text-sm rounded-pill border border-walmart-navy/15 bg-white hover:bg-walmart-blue/5 text-walmart-navy flex items-center gap-1"
            title="Refresh all data"
          >
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      {actionError && (
        <div className="bg-sentiment-negative/5 border border-sentiment-negative/20 text-sentiment-negative px-4 py-2 rounded-xl text-sm flex items-center justify-between">
          <span><AlertCircle size={14} className="inline mr-1" />{actionError}</span>
          <button onClick={() => setActionError(null)}><X size={14} /></button>
        </div>
      )}
      {actionInfo && (
        <div className="bg-walmart-blue/5 border border-walmart-blue/20 text-walmart-blue px-4 py-2 rounded-xl text-sm flex items-center justify-between">
          <span>{actionInfo}</span>
          <button onClick={() => setActionInfo(null)}><X size={14} /></button>
        </div>
      )}

      {/* A) Live status strip — Req 1: shows 6h interval; Req 2: timeframe dropdown + progress */}
      <StatusStrip status={status} onRun={runNow} onStop={stopNow} loading={loading} />

      {/* A2) Data health — gaps + analysis backlog + one-click fill */}
      <DataHealthPanel
        gaps={gaps}
        backlog={backlog}
        pipelineRunning={status?.running ?? false}
        onError={setActionError}
        onInfo={(msg) => { setActionInfo(msg); loadAll(false); }}
        onReload={() => loadAll(false)}
      />

      {/* A3) Image availability — outcome of every image fetch attempt */}
      <ImageFailuresPanel report={imageFailures} />

      {/* B) Funnel + media breakdown — Req 4: clickable; Req 5: vision failure categories */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-surface border border-walmart-navy/10 rounded-2xl shadow-card p-5">
          <h3 className="text-base font-semibold text-walmart-navy mb-3 flex items-center gap-2">
            <span className="inline-block w-1 h-5 rounded-full bg-walmart-spark" />
            Ingestion funnel — {RANGE_OPTIONS.find(o => o.value === range)?.label}
          </h3>
          {funnel ? <FunnelChart data={funnel} /> : <div className="text-gray-400 text-sm">Loading…</div>}
        </div>
        <div className="bg-surface border border-walmart-navy/10 rounded-2xl shadow-card p-5">
          <h3 className="text-base font-semibold text-walmart-navy mb-3 flex items-center gap-2">
            <span className="inline-block w-1 h-5 rounded-full bg-walmart-spark" />
            Media types
          </h3>
          {funnel ? <MediaBreakdown data={funnel} /> : <div className="text-gray-400 text-sm">Loading…</div>}
        </div>
      </div>

      {/* C) Sources table */}
      <div className="bg-surface border border-walmart-navy/10 rounded-2xl shadow-card">
        <button
          onClick={() => setSourcesOpen(!sourcesOpen)}
          className="w-full p-5 flex items-center justify-between hover:bg-walmart-blue/5 rounded-2xl"
        >
          <div className="flex items-center gap-2">
            {sourcesOpen ? <ChevronDown size={16} className="text-walmart-navy" /> : <ChevronRight size={16} className="text-walmart-navy" />}
            <h3 className="text-base font-semibold text-walmart-navy">Sources ({sources.length})</h3>
            {!sourcesOpen && (
              <span className="text-xs text-gray-400 ml-2">
                {sources.filter(s => s.enabled).length} enabled · {sources.reduce((a, s) => a + s.fetched, 0).toLocaleString()} fetched · {sources.reduce((a, s) => a + s.pending, 0)} pending
              </span>
            )}
          </div>
          <span className="text-xs text-gray-400">{RANGE_OPTIONS.find(o => o.value === range)?.label}</span>
        </button>
        {sourcesOpen && (
          <div className="px-5 pb-5">
            <SourcesTable sources={sources} />
          </div>
        )}
      </div>

      {/* D) Registry editor */}
      <div className="bg-surface border border-walmart-navy/10 rounded-2xl shadow-card">
        <button
          onClick={() => setRegistryOpen(!registryOpen)}
          className="w-full p-5 flex items-center justify-between hover:bg-walmart-blue/5 rounded-2xl"
        >
          <div className="flex items-center gap-2">
            {registryOpen ? <ChevronDown size={16} className="text-walmart-navy" /> : <ChevronRight size={16} className="text-walmart-navy" />}
            <h3 className="text-base font-semibold text-walmart-navy">
              Subreddit registry ({registry.filter(r => r.enabled).length} / {registry.length} enabled)
            </h3>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); setShowBackfill(true); }}
            className="px-4 py-1.5 text-sm rounded-pill bg-walmart-spark text-walmart-navy hover:bg-walmart-spark-dark flex items-center gap-1 shadow-sm font-semibold"
            title="Run a one-off historical backfill for selected subreddits"
          >
            <Clock size={14} /> Backfill…
          </button>
        </button>
        {registryOpen && (
          <div className="px-5 pb-5">
            <RegistryEditor
              registry={registry}
              onMutated={() => loadAll(false)}
              onError={setActionError}
              onInfo={setActionInfo}
            />
          </div>
        )}
      </div>

      {/* E) Recent jobs */}
      <div className="bg-surface border border-walmart-navy/10 rounded-2xl shadow-card p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-walmart-navy flex items-center gap-2">
            <span className="inline-block w-1 h-5 rounded-full bg-walmart-spark" />
            Recent jobs ({jobs.length})
          </h3>
          {jobs.length > 5 && (
            <button
              onClick={() => setShowAllJobs(!showAllJobs)}
              className="text-xs text-walmart-blue hover:underline flex items-center gap-1"
            >
              {showAllJobs ? <><EyeOff size={12} /> Show less</> : <><Eye size={12} /> Show all {jobs.length}</>}
            </button>
          )}
        </div>
        <JobsList jobs={visibleJobs} />
        {!showAllJobs && jobs.length > 5 && (
          <div className="text-center mt-3">
            <button
              onClick={() => setShowAllJobs(true)}
              className="text-xs text-gray-500 hover:text-walmart-blue"
            >
              + {jobs.length - 5} more runs hidden
            </button>
          </div>
        )}
      </div>

      {/* X) Coverage panel — moved to bottom: low-frequency reference data.
              Shows the watermark per subreddit, the most recent fetch window,
              and the overlap buffer used to avoid losing delta between
              scheduled runs. */}
      <CoveragePanel
        cursors={cursors}
        overlapSeconds={overlapSeconds}
        intervalMinutes={status?.interval_minutes ?? 360}
        nextScheduledRunAt={status?.next_scheduled_run_at ?? null}
        open={coverageOpen}
        onToggle={() => setCoverageOpen(!coverageOpen)}
      />

      {/* Y) Live backfill / ingest progress — only when a run is in-flight.
              Collapsed by default so it doesn't push other panels around;
              open to see per-sub timeline coverage and ETA. */}
      {status?.ingest_progress && (
        <BackfillProgressPanel
          progress={status.ingest_progress}
          open={progressOpen}
          onToggle={() => setProgressOpen(!progressOpen)}
        />
      )}

      {/* F) Danger zone — destructive operations */}
      <div className="bg-surface border border-sentiment-negative/30 rounded-2xl shadow-card p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <h3 className="text-base font-semibold text-sentiment-negative flex items-center gap-2">
              <AlertCircle size={16} /> Danger zone
            </h3>
            <p className="text-xs text-gray-600 mt-1">
              Wipe all local SQLite data (raw posts, analyses, aggregates, alerts, jobs, cursors)
              and start fresh. The current <code className="px-1 rounded bg-gray-100">data/local.db</code>
              {' '}file is backed up first. Typically followed by a 90-day backfill.
            </p>
          </div>
          <button
            onClick={() => setShowFlush(true)}
            className="shrink-0 px-4 py-2 text-sm rounded-pill bg-sentiment-negative text-white hover:bg-sentiment-negative/90 flex items-center gap-1.5 shadow-sm font-semibold"
            title="Wipe all local data and reset cursors"
          >
            <Trash2 size={14} /> Flush all data…
          </button>
        </div>
      </div>

      {showBackfill && (
        <BackfillModal
          registry={registry}
          onClose={() => setShowBackfill(false)}
          onError={setActionError}
          onInfo={(msg) => { setActionInfo(msg); loadAll(false); }}
        />
      )}
      {showFlush && (
        <FlushModal
          onClose={() => setShowFlush(false)}
          onError={setActionError}
          onInfo={(msg) => { setActionInfo(msg); loadAll(false); }}
        />
      )}
    </div>
  );
}

// ─── Section A: Live status strip ───────────────────────────────────────────
// Req 1: Displays interval in human-readable form (6h instead of 360m)
// Req 2: Includes a timeframe dropdown for manual trigger + pipeline progress viz

function StatusStrip({ status, onRun, onStop, loading }: {
  status: PipelineStatus | null;
  onRun: (lookbackHours?: number) => void;
  onStop: () => void;
  loading: boolean;
}) {
  const [lookback, setLookback] = useState<number>(24);
  const running = status?.running ?? false;
  const last = status?.last_status;
  const lastFinished = status?.last_finished_at;
  const interval = status?.interval_minutes ?? 360;
  const nextRun = status?.next_scheduled_run_at;

  const fmtInterval = (m: number) => {
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    const rem = m % 60;
    return rem ? `${h}h ${rem}m` : `${h}h`;
  };

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

  // Req 2: Determine which pipeline stage is active.
  // Prefer the backend-reported `current_stage` (parsed live from
  // pipeline stdout); fall back to a time-based estimate when the
  // backend hasn't published one yet. Returns -1 when not running so
  // all stages render in their idle state.
  const runningStageIdx = useMemo(() => {
    if (!running) return -1;
    const stage = (status as any)?.current_stage as string | null | undefined;
    if (stage && stage in STAGE_TO_IDX) return STAGE_TO_IDX[stage];
    if (!status?.last_started_at) return 0;
    const elapsed = Date.now() - new Date(status.last_started_at).getTime();
    if (elapsed < 5000) return 0;   // Ingest
    if (elapsed < 15000) return 1;  // Vision
    if (elapsed < 25000) return 2;  // Trust
    if (elapsed < 45000) return 3;  // Analyze
    return 0; // long cycles are ingest-bound; default back to Ingest
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, status?.last_started_at, (status as any)?.current_stage]);

  return (
    <div className="bg-surface border border-walmart-navy/10 rounded-2xl shadow-card p-5 space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
            running ? 'bg-walmart-blue/15 text-walmart-blue' :
            last === 'failed' ? 'bg-sentiment-negative/15 text-sentiment-negative' :
            last === 'success' ? 'bg-sentiment-positive/15 text-sentiment-positive' :
            'bg-walmart-navy/10 text-walmart-navy/60'
          }`}>
            {running ? <Loader2 className="animate-spin" size={20} /> :
             last === 'failed' ? <AlertCircle size={20} /> :
             last === 'success' ? <CheckCircle2 size={20} /> :
             <Activity size={20} />}
          </div>
          <div>
            <div className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold">Last run</div>
            <div className="text-sm font-semibold text-walmart-navy">
              {running ? 'Running now' : (last ?? 'never')}
              {!running && lastFinished && (
                <span className="text-gray-400 font-normal"> · {ago(lastFinished)}</span>
              )}
            </div>
          </div>
        </div>

        <div>
          <div className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold">Scheduler</div>
          <div className="text-sm">
            {status?.scheduler_enabled
              ? <span className="text-sentiment-positive font-semibold">on</span>
              : <span className="text-gray-400">off</span>}
            <span className="text-gray-500"> · every {fmtInterval(interval)}</span>
          </div>
        </div>

        <div>
          <div className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold">Next scheduled</div>
          <div className="text-sm font-medium text-walmart-navy">
            {ttl(nextRun) || '—'}
          </div>
        </div>

        <div className="flex items-center gap-2 justify-end">
          <select
            value={lookback}
            onChange={(e) => setLookback(Number(e.target.value))}
            className="border border-walmart-navy/15 rounded-pill px-3 py-1.5 text-sm bg-white shadow-sm text-walmart-navy focus:outline-none focus:ring-2 focus:ring-walmart-blue"
            title="Lookback window for manual run"
            disabled={running}
          >
            {LOOKBACK_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {running ? (
            <button
              onClick={onStop}
              disabled={loading}
              className="px-4 py-2 rounded-pill bg-sentiment-negative text-white hover:bg-sentiment-negative/90 disabled:bg-gray-300 disabled:cursor-not-allowed shadow-sm flex items-center gap-2 font-semibold"
              title="Cancel the in-flight pipeline run"
            >
              <Square size={14} className="fill-current" />
              Stop
            </button>
          ) : (
            <button
              onClick={() => onRun(lookback)}
              disabled={loading}
              className="px-4 py-2 rounded-pill bg-walmart-blue text-white hover:bg-walmart-blue/90 disabled:bg-gray-300 disabled:cursor-not-allowed shadow-sm flex items-center gap-2 font-semibold"
            >
              <Play size={16} />
              Run Now
            </button>
          )}
        </div>
      </div>

      {/* Pipeline progress visualization — always visible, dims when idle */}
      <div className="border-t border-walmart-navy/10 pt-3">
        <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
          <div className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold">
            Pipeline stages
          </div>
          <div className="text-[11px] text-gray-400">
            {running
              ? <span className="text-walmart-blue font-semibold">live — {PIPELINE_STAGES[runningStageIdx]?.label ?? '—'}</span>
              : last === 'success'   ? <span className="text-sentiment-positive">last run completed all stages</span>
              : last === 'failed'    ? <span className="text-sentiment-negative">last run failed</span>
              : last === 'stopped'   ? <span className="text-gray-500">last run stopped</span>
              :                        <span>idle</span>}
          </div>
        </div>

        {/* Run details: lookback window + delta + duration */}
        <RunDetails status={status} running={running} />

        {/* Overall progress bar */}
        <div className="mb-2 mt-2">
          <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1">
            <span>
              {running
                ? `Stage ${Math.max(runningStageIdx, 0) + 1} of ${PIPELINE_STAGES.length}`
                : last
                  ? `Completed ${PIPELINE_STAGES.length} of ${PIPELINE_STAGES.length} stages`
                  : 'No run yet'}
            </span>
            <span className="font-mono">
              {running
                ? `${Math.round(((runningStageIdx + 0.5) / PIPELINE_STAGES.length) * 100)}%`
                : last === 'success' ? '100%' : '0%'}
            </span>
          </div>
          <div className="w-full h-2 bg-walmart-navy/5 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                last === 'failed' ? 'bg-sentiment-negative' :
                running ? 'bg-walmart-blue' : 'bg-sentiment-positive'
              }`}
              style={{
                width: running
                  ? `${Math.round(((runningStageIdx + 0.5) / PIPELINE_STAGES.length) * 100)}%`
                  : last === 'success' ? '100%' : '0%',
              }}
            />
          </div>
        </div>

        <div className="flex items-center gap-1 flex-wrap">
          {PIPELINE_STAGES.map((stage, i) => {
            const isActive   = running && i === runningStageIdx;
            const isComplete = running && i < runningStageIdx;
            const isDone     = !running && last === 'success';
            const count      = stage.counterKey ? status?.last_counters?.[stage.counterKey] : undefined;
            const showCount  = (isComplete || isActive || isDone) && typeof count === 'number';
            return (
              <div key={stage.key} className="flex items-center">
                <div
                  className={`flex items-center gap-1 px-2 py-1 rounded-pill text-xs font-medium ${
                    isComplete             ? 'bg-sentiment-positive/15 text-sentiment-positive' :
                    isActive               ? 'bg-walmart-blue/15 text-walmart-blue ring-2 ring-walmart-blue/40' :
                    isDone                 ? 'bg-sentiment-positive/10 text-sentiment-positive/80' :
                                              'bg-walmart-navy/5 text-gray-400'
                  }`}>
                  {(isComplete || isDone) && <CheckCircle2 size={12} />}
                  {isActive && <Loader2 size={12} className="animate-spin" />}
                  {stage.label}
                  {showCount && (
                    <span className="ml-1 px-1.5 py-0.5 rounded-full bg-white/60 text-[10px] font-mono tabular-nums">
                      +{count}
                    </span>
                  )}
                </div>
                {i < PIPELINE_STAGES.length - 1 && (
                  <div className={`w-4 h-0.5 mx-0.5 ${
                    (isComplete || isDone) ? 'bg-sentiment-positive/40' : 'bg-walmart-navy/10'
                  }`} />
                )}
              </div>
            );
          })}
        </div>

        {/* Live log tail — default-closed; auto-opens nothing, user toggles
            to see subprocess activity even when counters stay at 0 (useful
            when ingestion network is slow or down). */}
        <LogTailPanel
          lines={status?.last_log_tail ?? []}
          running={running}
        />
      </div>
    </div>
  );
}

/**
 * LogTailPanel — collapsible viewer of the most recent subprocess log lines.
 *
 * Default-closed. When open, shows the last ~25 lines from
 * `pipeline_status.last_log_tail` (already captured by the API as the
 * subprocess streams stdout). Auto-scrolls to the bottom while running so
 * new lines appear without manual scrolling.
 */
function LogTailPanel({
  lines, running,
}: {
  lines: string[];
  running: boolean;
}) {
  const [open, setOpen] = useState(false);
  const count = lines.length;
  const onToggle = () => setOpen(!open);
  return (
    <div className="mt-3 border border-walmart-navy/10 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-3 py-2 flex items-center justify-between hover:bg-walmart-blue/5 text-left"
      >
        <div className="flex items-center gap-2">
          {open ? <ChevronDown size={14} className="text-gray-500" /> : <ChevronRight size={14} className="text-gray-500" />}
          <span className="text-[11px] font-semibold uppercase tracking-wider text-walmart-navy">
            Live log
          </span>
          {running && (
            <span className="flex items-center gap-1 text-[10px] text-walmart-blue">
              <span className="w-1.5 h-1.5 bg-walmart-blue rounded-full animate-pulse" />
              streaming
            </span>
          )}
        </div>
        <span className="text-[10px] text-gray-500 font-mono">
          {count} {count === 1 ? 'line' : 'lines'}
        </span>
      </button>
      {open && (
        <div className="bg-walmart-navy text-green-300 font-mono text-[10.5px] leading-relaxed px-3 py-2 max-h-64 overflow-auto">
          {count === 0 ? (
            <div className="text-gray-500 italic">
              {running ? 'Waiting for first output…' : 'No log yet — click Run Now to start a cycle.'}
            </div>
          ) : (
            lines.map((ln, i) => (
              <div key={i} className="whitespace-pre-wrap break-words">{ln}</div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/**
 * RunDetails — small info row under the stage pills.
 *
 * Shows the lookback window the current/last run was triggered for
 * (e.g. "24h"), the actual time delta being covered (from → to),
 * and the live duration (ticking while running) or final duration.
 */
function RunDetails({ status, running }: { status: PipelineStatus | null; running: boolean }) {
  // Tick once a second while running so the duration label updates live.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, [running]);

  if (!status?.last_started_at) {
    return (
      <div className="text-[11px] text-gray-400 italic">
        No runs yet — click Run Now to start a cycle.
      </div>
    );
  }
  const lookback = status.last_params?.lookback_hours;
  const startedMs = new Date(status.last_started_at).getTime();
  const endMs = running
    ? Date.now()
    : status.last_finished_at ? new Date(status.last_finished_at).getTime() : Date.now();
  const fromMs = lookback ? startedMs - lookback * 3_600_000 : null;

  const fmtDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return `${m}m ${rem}s`;
  };
  const fmtAbs = (ms: number) => {
    const d = new Date(ms);
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  };
  const fmtLookback = (h: number) => {
    if (h < 24) return `${h}h`;
    if (h % 24 === 0) return `${h / 24}d`;
    return `${Math.floor(h / 24)}d ${h % 24}h`;
  };

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-gray-600 bg-walmart-navy/[0.03] rounded-lg px-3 py-2">
      <span className="flex items-center gap-1">
        <Clock size={11} className="text-walmart-blue" />
        <span className="text-gray-500">Triggered for:</span>
        <span className="font-semibold text-walmart-navy">
          {lookback ? fmtLookback(lookback) : 'default window'}
        </span>
      </span>
      {fromMs && (
        <span className="flex items-center gap-1">
          <span className="text-gray-500">Window:</span>
          <span className="font-mono text-walmart-navy">{fmtAbs(fromMs)}</span>
          <span className="text-gray-400">→</span>
          <span className="font-mono text-walmart-navy">{fmtAbs(startedMs)}</span>
        </span>
      )}
      <span className="flex items-center gap-1">
        <span className="text-gray-500">{running ? 'Running for:' : 'Duration:'}</span>
        <span className="font-mono text-walmart-navy">{fmtDuration(endMs - startedMs)}</span>
      </span>
      {status.last_trigger && (
        <span className="flex items-center gap-1">
          <span className="text-gray-500">via</span>
          <span className="font-semibold text-walmart-navy capitalize">{status.last_trigger}</span>
        </span>
      )}
    </div>
  );
}

/**
 * CoveragePanel — per-subreddit ingestion watermark + last fetch window.
 *
 * Each row shows:
 *   - "Last post seen": newest created_utc successfully ingested
 *   - "Last window":    [since → until] the previous run actually asked
 *                       the fetcher for (already includes the overlap buffer)
 *   - "Next coverage":  what window the next scheduled run will cover
 *   - "Gap":            ⚠ red badge if more time has passed since
 *                       last_fetched_utc than the cron interval × 1.5
 *                       (signals we're falling behind)
 */
function CoveragePanel({
  cursors, overlapSeconds, intervalMinutes, nextScheduledRunAt, open, onToggle,
}: {
  cursors: PipelineCursor[];
  overlapSeconds: number;
  intervalMinutes: number;
  nextScheduledRunAt: string | null;
  open: boolean;
  onToggle: () => void;
}) {
  const fmtAbs = (sec: number | null | undefined) => {
    if (!sec) return '—';
    return new Date(sec * 1000).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  };
  const fmtAbsIso = (iso: string | null | undefined) => {
    if (!iso) return '—';
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  };
  const ago = (sec: number | null | undefined) => {
    if (!sec) return 'never';
    const m = Math.floor((Date.now() / 1000 - sec) / 60);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  };
  const fmtSecs = (s: number) => {
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.round(s / 60)}m`;
    return `${(s / 3600).toFixed(1)}h`;
  };

  const stalenessLimitMs = intervalMinutes * 60 * 1000 * 1.5;
  const nextSinceMs = nextScheduledRunAt
    ? new Date(nextScheduledRunAt).getTime() - intervalMinutes * 60 * 1000 - overlapSeconds * 1000
    : null;

  // Freshness = "how long since we ingested a real post for this sub", based
  // on the actual MAX(created_timestamp), NOT the cursor. Cursor can be
  // rewound behind the data (e.g. by --fill-gaps) which would make the
  // sub look freshly-fetched even though no new posts have arrived.
  const freshnessTs = (c: PipelineCursor): number | null =>
    c.newest_post_utc ?? c.last_fetched_utc ?? null;

  const sorted = [...cursors].sort((a, b) => {
    // worst-staleness first — subs with no data at all sink to the top.
    const aTs = freshnessTs(a) ?? 0;
    const bTs = freshnessTs(b) ?? 0;
    return aTs - bTs;
  });

  const stale = sorted.filter(c => {
    const ts = freshnessTs(c);
    if (!ts) return true;
    return Date.now() - ts * 1000 > stalenessLimitMs;
  }).length;

  return (
    <div className="bg-surface border border-walmart-navy/10 rounded-2xl shadow-card">
      <button
        onClick={onToggle}
        className="w-full p-5 flex items-center justify-between hover:bg-walmart-blue/5 rounded-2xl"
      >
        <div className="flex items-center gap-2 text-left">
          {open ? <ChevronDown size={16} className="text-walmart-navy" /> : <ChevronRight size={16} className="text-walmart-navy" />}
          <h3 className="text-base font-semibold text-walmart-navy">
            Coverage &amp; watermarks
          </h3>
          <span className="text-xs text-gray-400 ml-1">
            {cursors.length} subreddit{cursors.length === 1 ? '' : 's'}
          </span>
          {stale > 0 && (
            <span className="text-[10px] font-bold uppercase tracking-wider bg-sentiment-negative/10 text-sentiment-negative px-2 py-0.5 rounded-full">
              {stale} stale
            </span>
          )}
        </div>
        <div className="text-xs text-gray-500 flex items-center gap-3">
          <span><span className="text-gray-400">Overlap buffer:</span> <span className="font-mono text-walmart-navy">{fmtSecs(overlapSeconds)}</span></span>
          <span><span className="text-gray-400">Cron:</span> <span className="font-mono text-walmart-navy">{intervalMinutes}m</span></span>
        </div>
      </button>
      {open && (
        <div className="px-5 pb-5 space-y-3">
          <div className="text-[11px] text-gray-500 bg-walmart-blue/[0.04] border border-walmart-blue/15 rounded-lg px-3 py-2 flex items-start gap-2">
            <Info size={12} className="text-walmart-blue mt-0.5 shrink-0" />
            <span>
              Each run fetches <span className="font-semibold text-walmart-navy">posts created after (cursor − {fmtSecs(overlapSeconds)})</span> so
              posts on the boundary or indexed late by Arctic Shift are not lost. Duplicates are
              dedup'd at the storage layer. The cursor only advances after the raw posts table is
              successfully written, so a killed run replays the same window cleanly on the next try.
            </span>
          </div>

          {sorted.length === 0 ? (
            <div className="text-gray-400 text-sm italic">No cursors yet — run the pipeline at least once.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-walmart-navy/[0.03] text-gray-500 uppercase tracking-wider">
                  <tr>
                    <th className="px-3 py-2 text-left font-semibold">Subreddit</th>
                    <th className="px-3 py-2 text-left font-semibold" title="MAX(created_timestamp) from raw_posts — the newest post we've actually ingested">Last post seen</th>
                    <th className="px-3 py-2 text-left font-semibold" title="The cursor value passed as `since` to the next fetcher call. Can differ from Last post seen if a lookback rewind put it behind.">Cursor</th>
                    <th className="px-3 py-2 text-left font-semibold">Last fetch window</th>
                    <th className="px-3 py-2 text-right font-semibold">Fetched</th>
                    <th className="px-3 py-2 text-left font-semibold">Next coverage</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(c => {
                    const newestPost = c.newest_post_utc ?? null;
                    const cursorUtc = c.last_fetched_utc ?? null;
                    const freshness = newestPost ?? cursorUtc;
                    const isStale = !freshness || Date.now() - freshness * 1000 > stalenessLimitMs;
                    // Drift = cursor is ahead of the newest actual post by
                    // more than 1 hour (a lookback rewind that upstream
                    // returned 0 for, OR a bootstrap value never realized).
                    const drift = (newestPost && cursorUtc)
                      ? (cursorUtc - newestPost)
                      : 0;
                    const hasDrift = Math.abs(drift) > 3600;
                    const w = c.last_window;
                    return (
                      <tr key={c.subreddit} className="border-t border-walmart-navy/5">
                        <td className="px-3 py-2 font-mono text-walmart-navy">r/{c.subreddit}</td>
                        <td className="px-3 py-2">
                          <div className="text-walmart-navy">{fmtAbs(newestPost)}</div>
                          <div className={isStale ? 'text-sentiment-negative font-semibold' : 'text-gray-400'}>
                            {ago(newestPost)} {isStale && '⚠'}
                          </div>
                        </td>
                        <td className="px-3 py-2">
                          <div className="text-gray-600 font-mono text-[11px]">{fmtAbs(cursorUtc)}</div>
                          {hasDrift && (
                            <div className="text-[10px] font-semibold text-walmart-blue mt-0.5"
                                 title={`Cursor is ${(drift/3600).toFixed(1)}h ${drift > 0 ? 'ahead of' : 'behind'} newest post`}>
                              drift {drift > 0 ? '+' : ''}{(drift/3600).toFixed(1)}h
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {w ? (
                            <div className="font-mono text-[11px]">
                              <span className="text-walmart-navy">{fmtAbs(w.since_utc)}</span>
                              <span className="text-gray-400"> → </span>
                              <span className="text-walmart-navy">{fmtAbs(w.until_utc)}</span>
                              {w.overlap_seconds > 0 && (
                                <span className="ml-1 text-[10px] text-walmart-blue/70">
                                  (+{fmtSecs(w.overlap_seconds)})
                                </span>
                              )}
                            </div>
                          ) : <span className="text-gray-400">—</span>}
                        </td>
                        <td className="px-3 py-2 text-right font-mono tabular-nums">
                          {w ? (
                            <span className={
                              w.status === 'failed' ? 'text-sentiment-negative font-semibold' :
                              w.fetched === 0 ? 'text-gray-400' : 'text-sentiment-positive font-semibold'
                            }>
                              {w.status === 'failed' ? 'failed' : w.fetched}
                            </span>
                          ) : <span className="text-gray-400">—</span>}
                        </td>
                        <td className="px-3 py-2 font-mono text-[11px]">
                          {nextSinceMs && cursorUtc ? (
                            <>
                              <span className="text-walmart-navy">{fmtAbs(cursorUtc - overlapSeconds)}</span>
                              <span className="text-gray-400"> → </span>
                              <span className="text-walmart-navy">{fmtAbsIso(nextScheduledRunAt)}</span>
                            </>
                          ) : (
                            <span className="text-gray-400">on next run</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Section B: Funnel + media ──────────────────────────────────────────────
// Req 4: Funnel bars are clickable to show detail breakdown
// Req 5: Vision captions show failure categorization

function FunnelChart({ data }: { data: FunnelData }) {
  const [selectedStage, setSelectedStage] = useState<string | null>(null);

  const chartData = data.funnel.map(f => ({
    name: STAGE_LABEL[f.stage] ?? f.stage,
    stage: f.stage,
    count: f.count,
    drop: f.drop_from_prev,
    color: STAGE_COLORS[f.stage] ?? '#94a3b8',
  }));
  const maxCount = Math.max(...chartData.map(d => d.count), 1);

  const detail = data.funnel_detail;
  const selected = data.funnel.find(f => f.stage === selectedStage);

  const stageExplanation: Record<string, string> = {
    fetched: 'Total posts retrieved from Reddit in this window. Matches Brand Health → Analyzed Posts card, "Fetched (ingested)" row.',
    english: 'Posts kept after language detection (non-English dropped).',
    long_enough: 'Posts with enough content for meaningful analysis (≥10 chars or has image).',
    analyzed: 'Posts successfully processed by the LLM sentiment analyzer. Matches Brand Health → Analyzed Posts headline number.',
    trusted: 'Posts passing trust scoring thresholds (not spam, not astroturf).',
  };

  return (
    <div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} layout="vertical" margin={{ left: 10, right: 60 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" domain={[0, maxCount * 1.1]} hide />
          <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 12 }} />
          <Tooltip formatter={(v: number, _n, p) => [`${v} posts`, p.payload.name]} />
          <Bar
            dataKey="count"
            radius={[0, 4, 4, 0]}
            onClick={(_data, idx) => {
              const stage = chartData[idx]?.stage;
              setSelectedStage(stage === selectedStage ? null : stage);
            }}
            className="cursor-pointer"
          >
            <LabelList dataKey="count" position="right" fill="#374151" fontSize={12} />
            {chartData.map((c, i) => (
              <Cell
                key={i}
                fill={c.color}
                opacity={selectedStage && c.stage !== selectedStage ? 0.4 : 1}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Req 4: Detail panel when a stage is clicked */}
      {selectedStage && selected && (
        <div className="mt-3 p-3 bg-gray-50 border rounded-lg text-sm animate-in fade-in">
          <div className="flex items-center justify-between mb-2">
            <div className="font-semibold text-gray-700 flex items-center gap-1">
              <Info size={14} />
              {STAGE_LABEL[selectedStage]} — Detail
            </div>
            <button onClick={() => setSelectedStage(null)} className="text-gray-400 hover:text-gray-600">
              <X size={14} />
            </button>
          </div>
          <p className="text-xs text-gray-500 mb-2">{stageExplanation[selectedStage]}</p>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="bg-white p-2 rounded border">
              <div className="text-gray-500">Count</div>
              <div className="font-bold text-lg">{selected.count.toLocaleString()}</div>
            </div>
            <div className="bg-white p-2 rounded border">
              <div className="text-gray-500">Dropped from prev</div>
              <div className="font-bold text-lg text-amber-600">{selected.drop_from_prev.toLocaleString()}</div>
              {selected.drop_from_prev > 0 && (
                <div className="text-gray-500 mt-1">
                  {selectedStage === 'english' && 'Non-English posts filtered out'}
                  {selectedStage === 'long_enough' && 'Posts too short for meaningful analysis (<10 chars and no image)'}
                  {selectedStage === 'analyzed' && 'Posts not yet processed by sentiment analyzer (pending in queue)'}
                  {selectedStage === 'trusted' && 'Posts failed trust scoring (spam, astroturf, or low-quality)'}
                </div>
              )}
            </div>
            {detail && selectedStage === 'analyzed' && (
              <div className="bg-white p-2 rounded border col-span-2">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-gray-500">Analysis coverage</div>
                    <div className="font-bold text-lg">{detail.analysis_coverage}%</div>
                  </div>
                  <div className="text-right text-gray-500">
                    {detail.not_yet_analyzed > 0 && <div>{detail.not_yet_analyzed.toLocaleString()} posts awaiting analysis</div>}
                  </div>
                </div>
              </div>
            )}
            {detail && selectedStage === 'trusted' && (
              <div className="bg-white p-2 rounded border col-span-2">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-gray-500">Trust rate (of analyzed)</div>
                    <div className="font-bold text-lg">{detail.trust_rate}%</div>
                  </div>
                  <div className="text-right text-gray-500">
                    {detail.low_trust > 0 && <div>{detail.low_trust.toLocaleString()} posts flagged as low-trust</div>}
                  </div>
                </div>
              </div>
            )}
            {detail && selectedStage === 'english' && detail.not_english > 0 && (
              <div className="bg-white p-2 rounded border col-span-2">
                <div className="text-gray-500">Non-English removed</div>
                <div className="font-bold text-lg">{detail.not_english.toLocaleString()}</div>
                <div className="text-gray-400 mt-0.5">Posts in other languages excluded by language detection filter</div>
              </div>
            )}
            {detail && selectedStage === 'long_enough' && detail.too_short > 0 && (
              <div className="bg-white p-2 rounded border col-span-2">
                <div className="text-gray-500">Too short</div>
                <div className="font-bold text-lg">{detail.too_short.toLocaleString()}</div>
                <div className="text-gray-400 mt-0.5">Posts with &lt;10 characters and no image — insufficient content for sentiment analysis</div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="text-xs text-gray-500 mt-2">
        Window: {new Date(data.window_start).toLocaleString()} → {new Date(data.window_end).toLocaleString()}
        <span className="ml-2 text-gray-400">(click bars for details)</span>
      </div>
    </div>
  );
}

function MediaBreakdown({ data }: { data: FunnelData }) {
  const m = data.media_breakdown;
  const [showVisionDetail, setShowVisionDetail] = useState(false);
  const items = [
    { label: 'Text only',    value: m.text_only,        color: 'bg-blue-100 text-blue-700' },
    { label: 'Image only',   value: m.image_only,       color: 'bg-purple-100 text-purple-700' },
    { label: 'Text + image', value: m.text_plus_image,  color: 'bg-indigo-100 text-indigo-700' },
    { label: 'Video',        value: m.video,            color: 'bg-rose-100 text-rose-700' },
    { label: 'Link only',    value: m.link_only,        color: 'bg-gray-100 text-gray-600' },
  ];

  const failures = m.vision_failures;
  const totalFailures = failures
    ? failures.timeout + failures.fetch_failed + failures.ollama_unavailable + failures.no_content + failures.other
    : m.images_total - m.captioned;

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
          <span>{m.captioned} / {m.images_total} captionable</span>
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

        {/* Caption failures — visible summary line, drill-down below. */}
        {totalFailures > 0 && (
          <div className="mt-3">
            <div
              role="button"
              tabIndex={0}
              onClick={() => setShowVisionDetail(!showVisionDetail)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setShowVisionDetail(!showVisionDetail); } }}
              className="w-full flex items-center justify-between text-xs text-gray-700 hover:text-walmart-blue rounded-lg px-2 py-1.5 hover:bg-walmart-blue/5 cursor-pointer"
              title="Show / hide per-category breakdown"
            >
              <span className="flex items-center gap-1.5">
                {showVisionDetail ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <span className="font-medium">Caption failures</span>
                <span className="text-gray-500">({totalFailures.toLocaleString()} images)</span>
              </span>
              <button
                onClick={async (e) => {
                  e.stopPropagation();
                  try {
                    const r = await api.retryVision();
                    if (!r.started) {
                      alert(`Could not start retry: ${r.reason ?? 'unknown'}`);
                    } else {
                      alert('Vision retry started — watch the Live log on the Pipeline status strip.');
                    }
                  } catch (err) {
                    alert(`Retry failed: ${err instanceof Error ? err.message : String(err)}`);
                  }
                }}
                className="px-2.5 py-1 text-[11px] rounded-pill bg-walmart-blue text-white hover:bg-walmart-blue/90 flex items-center gap-1 font-semibold"
                title="Re-caption all stored posts that have images but no caption (e.g. after Ollama outage)"
              >
                <RefreshCw size={11} /> Retry vision
              </button>
            </div>

            {/* Req 5: Vision failure categorization — appears BELOW the summary. */}
            {showVisionDetail && failures && (
              <div className="mt-2 space-y-1.5 text-xs">
                {[
                  { key: 'ollama_unavailable', label: 'Ollama unavailable', value: failures.ollama_unavailable, color: 'bg-red-200',
                    reason: 'Vision model server (Ollama) was not running or unreachable when caption was attempted' },
                  { key: 'timeout', label: 'Timeout', value: failures.timeout, color: 'bg-amber-200',
                    reason: 'Vision model took too long to respond — image may be too large or model overloaded' },
                  { key: 'fetch_failed', label: 'Image fetch failed', value: failures.fetch_failed, color: 'bg-orange-200',
                    reason: 'Could not download image from Reddit — URL expired, deleted, or blocked' },
                  { key: 'no_content', label: 'No content detected', value: failures.no_content, color: 'bg-gray-200',
                    reason: 'Vision model returned empty caption — image may be blank, blurry, or unrecognizable' },
                  { key: 'other', label: 'Other', value: failures.other, color: 'bg-gray-200',
                    reason: 'Miscellaneous failures — check API logs for details' },
                ].filter(f => f.value > 0).map(f => (
                  <div key={f.key} className="flex items-center gap-2">
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-gray-600">{f.label}</span>
                        <span className="tabular-nums">{f.value.toLocaleString()}</span>
                      </div>
                      <div className="w-full bg-gray-100 rounded h-1.5">
                        <div
                          className={`${f.color} h-1.5 rounded`}
                          style={{ width: `${Math.min(100, (f.value / totalFailures) * 100)}%` }}
                        />
                      </div>
                      <div className="text-[10px] text-gray-400 mt-0.5">{f.reason}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
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

// ─── Flush modal — destructive ─────────────────────────────────────────────
// Requires the user to type the literal string YES_DELETE_ALL before the
// confirm button enables. After flush, optionally kicks off a 90-day backfill.

function FlushModal({
  onClose, onError, onInfo,
}: {
  onClose: () => void;
  onError: (msg: string) => void;
  onInfo: (msg: string) => void;
}) {
  const REQUIRED = 'YES_DELETE_ALL';
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [autoBackfill, setAutoBackfill] = useState(true);
  const [result, setResult] = useState<{
    deleted_tables?: Record<string, number>;
    deleted_cursors?: number;
    backup_path?: string | null;
  } | null>(null);

  const enabled = typed.trim() === REQUIRED && !busy;

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.flushAllData(REQUIRED);
      if (!r.flushed) {
        onError(`Flush failed: ${r.reason ?? 'unknown'}`);
        setBusy(false);
        return;
      }
      setResult({
        deleted_tables: r.deleted_tables,
        deleted_cursors: r.deleted_cursors,
        backup_path: r.backup_path,
      });
      const tableTotal = Object.values(r.deleted_tables ?? {}).reduce((a, b) => a + b, 0);
      onInfo(
        `Flushed ${tableTotal.toLocaleString()} rows across ${
          Object.keys(r.deleted_tables ?? {}).length
        } table(s). Backup: ${r.backup_path ?? 'none'}.`,
      );

      if (autoBackfill) {
        const to = new Date();
        const from = new Date(to.getTime() - 90 * 24 * 60 * 60 * 1000);
        const br = await api.triggerBackfill({
          from: from.toISOString(),
          to: to.toISOString(),
        });
        if (br.started) {
          onInfo(`Flush complete. 90-day backfill started across all enabled subreddits.`);
        } else {
          onError(`Flush done but backfill not started: ${br.reason ?? 'unknown'}`);
        }
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Flush failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full">
        <div className="px-5 py-4 border-b border-walmart-navy/10 flex items-center justify-between">
          <h3 className="text-base font-semibold text-sentiment-negative flex items-center gap-2">
            <Trash2 size={18} /> Flush all data
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-walmart-navy">
            <X size={18} />
          </button>
        </div>

        {!result ? (
          <>
            <div className="p-5 space-y-4">
              <div className="rounded-xl border border-sentiment-negative/30 bg-sentiment-negative/5 p-3">
                <div className="flex items-start gap-2">
                  <AlertCircle size={16} className="text-sentiment-negative shrink-0 mt-0.5" />
                  <div className="text-sm text-gray-800">
                    <strong className="text-sentiment-negative">This is destructive.</strong>{' '}
                    All raw posts, analyses, aggregates, alerts, jobs, and ingestion cursors will
                    be deleted. The current <code className="px-1 bg-white rounded">data/local.db</code>{' '}
                    is automatically backed up first.
                  </div>
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-gray-700 block mb-1">
                  Type <code className="px-1 bg-gray-100 rounded font-mono">{REQUIRED}</code> to confirm
                </label>
                <input
                  type="text"
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  autoFocus
                  spellCheck={false}
                  placeholder={REQUIRED}
                  className="w-full px-3 py-2 text-sm border border-walmart-navy/20 rounded-pill focus:outline-none focus:ring-2 focus:ring-sentiment-negative/40 font-mono"
                />
              </div>

              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={autoBackfill}
                  onChange={(e) => setAutoBackfill(e.target.checked)}
                  className="accent-walmart-blue"
                />
                After flush, automatically start a 90-day backfill across enabled subreddits
              </label>
            </div>

            <div className="px-5 py-4 border-t border-walmart-navy/10 flex items-center justify-end gap-2 bg-bg-base rounded-b-2xl">
              <button
                onClick={onClose}
                disabled={busy}
                className="px-4 py-1.5 text-sm rounded-pill border border-walmart-navy/20 bg-white hover:bg-gray-100"
              >Cancel</button>
              <button
                onClick={submit}
                disabled={!enabled}
                className="px-4 py-1.5 text-sm rounded-pill bg-sentiment-negative text-white hover:bg-sentiment-negative/90 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-1.5 font-semibold"
              >
                {busy ? <><Loader2 size={14} className="animate-spin" /> Flushing…</> :
                  <><Trash2 size={14} /> Flush now</>}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="p-5 space-y-3 text-sm">
              <div className="flex items-center gap-2 text-sentiment-positive font-semibold">
                <CheckCircle2 size={16} /> Flush complete
              </div>
              {result.backup_path && (
                <div className="text-xs text-gray-600">
                  Backup saved to{' '}
                  <code className="px-1 bg-gray-100 rounded">{result.backup_path}</code>
                </div>
              )}
              <div className="rounded-xl border border-walmart-navy/10 overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-bg-base text-walmart-navy">
                    <tr>
                      <th className="text-left px-3 py-2">Table</th>
                      <th className="text-right px-3 py-2">Rows deleted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(result.deleted_tables ?? {}).map(([t, n]) => (
                      <tr key={t} className="border-t border-walmart-navy/10">
                        <td className="px-3 py-1.5 font-mono">{t}</td>
                        <td className="px-3 py-1.5 text-right">{n.toLocaleString()}</td>
                      </tr>
                    ))}
                    <tr className="border-t border-walmart-navy/10 bg-bg-base">
                      <td className="px-3 py-1.5 font-mono">cursors</td>
                      <td className="px-3 py-1.5 text-right">
                        {(result.deleted_cursors ?? 0).toLocaleString()}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div className="px-5 py-4 border-t border-walmart-navy/10 flex items-center justify-end bg-bg-base rounded-b-2xl">
              <button
                onClick={onClose}
                className="px-4 py-1.5 text-sm rounded-pill bg-walmart-blue text-white hover:bg-walmart-navy font-semibold"
              >Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * BackfillProgressPanel — live, per-subreddit ingest timeline.
 *
 * Renders only while a pipeline run is in flight. Solves the "how far along
 * is my 90-day backfill?" question: shows overall % covered, ETA, and per-sub
 * progress bars with the actual UTC date reached so analysts can see exactly
 * how much of the requested window is left.
 */
function BackfillProgressPanel({ progress, open, onToggle }: {
  progress: IngestProgress;
  open: boolean;
  onToggle: () => void;
}) {
  const overall = Math.max(0, Math.min(100, progress.overall_pct ?? 0));
  const subsTotal = progress.subs_total || progress.subreddits.length;
  const fmtDate = (ts: number | null | undefined) =>
    ts && ts > 0 ? new Date(ts * 1000).toISOString().slice(0, 10) : '—';
  const fmtEta = (sec: number | null) => {
    if (sec == null || sec <= 0) return '—';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (h >= 1) return `${h}h ${m}m`;
    return `${m}m`;
  };
  const totalFetched = progress.subreddits.reduce(
    (s, r) => s + (r.total_fetched || 0), 0,
  );

  return (
    <div className="bg-surface border border-walmart-blue/30 rounded-2xl shadow-card">
      <button
        onClick={onToggle}
        className="w-full p-5 flex items-center justify-between hover:bg-walmart-blue/5 rounded-2xl"
      >
        <div className="flex items-center gap-2">
          {open ? <ChevronDown size={16} className="text-walmart-navy" /> : <ChevronRight size={16} className="text-walmart-navy" />}
          <span className="inline-block w-1 h-5 rounded-full bg-walmart-blue animate-pulse" />
          <h3 className="text-base font-semibold text-walmart-navy">
            Ingest in progress — {overall.toFixed(1)}% covered
          </h3>
        </div>
        <div className="text-xs text-gray-500 flex items-center gap-3">
          <span>{progress.subs_done} / {subsTotal} subs done</span>
          <span>{totalFetched.toLocaleString()} posts fetched</span>
          <span>ETA {fmtEta(progress.eta_seconds)}</span>
        </div>
      </button>
      {!open && (
        <div className="px-5 pb-4">
          <div className="h-2 bg-walmart-navy/10 rounded-full overflow-hidden">
            <div
              className="h-full bg-walmart-blue transition-all"
              style={{ width: `${overall}%` }}
            />
          </div>
        </div>
      )}
      {open && (
        <div className="px-5 pb-5">
          {/* Overall progress bar */}
          <div className="mb-4">
            <div className="h-2 bg-walmart-navy/10 rounded-full overflow-hidden">
              <div
                className="h-full bg-walmart-blue transition-all"
                style={{ width: `${overall}%` }}
              />
            </div>
          </div>

          {/* Per-subreddit list */}
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {progress.subreddits.map((s) => {
          const pct = Math.max(0, Math.min(100, s.coverage_pct ?? 0));
          const sinceLabel = fmtDate(s.since_utc);
          const oldestLabel = fmtDate(s.oldest_utc);
          const untilLabel = fmtDate(s.until_utc);
          // "Days reached" = how much of the requested window has been walked.
          const daysTotal = s.window_days ?? null;
          const daysReached = (s.since_utc && s.until_utc && s.oldest_utc)
            ? Math.max(0, (s.until_utc - s.oldest_utc) / 86400)
            : 0;
          const daysRemaining = (daysTotal != null)
            ? Math.max(0, daysTotal - daysReached)
            : null;
          const statusColor =
            s.status === 'ok' ? 'bg-sentiment-positive' :
            s.status === 'failed' ? 'bg-red-500' :
            s.status === 'running' ? 'bg-walmart-blue' :
            'bg-gray-300';
          return (
            <div key={s.subreddit} className="border border-walmart-navy/10 rounded-lg p-3">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <span className={`inline-block w-2 h-2 rounded-full ${statusColor} ${s.status === 'running' ? 'animate-pulse' : ''}`} />
                  <span className="font-mono text-sm font-semibold text-walmart-navy">r/{s.subreddit}</span>
                  {s.position != null && s.total_subs != null && (
                    <span className="text-xs text-gray-400">({s.position}/{s.total_subs})</span>
                  )}
                </div>
                <div className="text-xs text-gray-500 flex items-center gap-3">
                  <span>{(s.total_fetched || 0).toLocaleString()} posts</span>
                  <span className="font-semibold text-walmart-navy">{pct.toFixed(0)}%</span>
                </div>
              </div>
              <div className="h-1.5 bg-walmart-navy/10 rounded-full overflow-hidden mb-1.5">
                <div
                  className={`h-full transition-all ${s.status === 'failed' ? 'bg-red-500' : 'bg-walmart-blue'}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="text-xs text-gray-500 grid grid-cols-2 md:grid-cols-4 gap-x-3 gap-y-0.5">
                <div>Window: <span className="font-mono">{sinceLabel} → {untilLabel}</span></div>
                <div>Reached: <span className="font-mono">{oldestLabel}</span></div>
                <div>
                  Days reached: <span className="font-mono">{daysReached.toFixed(1)}</span>
                  {daysTotal != null && <span className="text-gray-400"> / {daysTotal.toFixed(0)}</span>}
                </div>
                <div>
                  Days remaining: <span className="font-mono">
                    {daysRemaining != null ? daysRemaining.toFixed(1) : '—'}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Section A2: Data Health Panel ─────────────────────────────────────────
// Single "Catch up from last run" primary action + analyze-pending secondary.
// Advanced controls (auto vs since-anchor modes, per-sub table, plan preview)
// live behind a collapsed "Advanced" section so the default view stays simple.

function DataHealthPanel({ gaps, backlog, pipelineRunning, onError, onInfo, onReload }: {
  gaps: GapReport | null;
  backlog: AnalysisBacklog | null;
  pipelineRunning: boolean;
  onError: (msg: string) => void;
  onInfo: (msg: string) => void;
  onReload: () => void;
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [showPlan, setShowPlan] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [applying, setApplying] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [plan, setPlan] = useState<FillGapsPlanEntry[] | null>(null);
  const [planMode, setPlanMode] = useState<'auto' | 'since'>('since');
  const [gapHours, setGapHours] = useState<number>(6);

  const lastRun = gaps?.last_successful_ingest ?? null;
  const totals = gaps?.totals ?? { subreddits: 0, stale: 0, drifted: 0, fresh: 0 };
  const pending = backlog?.pending ?? 0;

  // Custom-since editor defaults to the last successful run's finish time so
  // "Catch up from last run" and the Advanced picker start pointing at the
  // same sensible timestamp.
  const defaultSince = useMemo(() => {
    const iso = lastRun?.finished_at;
    if (iso) {
      // Convert to local wall-clock for the <input type="datetime-local">.
      const d = new Date(iso);
      const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
      return local.toISOString().slice(0, 16);
    }
    const d = new Date();
    d.setUTCHours(0, 0, 0, 0);
    d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 16);
  }, [lastRun?.finished_at]);
  const [since, setSince] = useState<string>(defaultSince);
  // Reset the picker when a fresh lastRun arrives.
  useEffect(() => { setSince(defaultSince); }, [defaultSince]);

  const fmtRelative = (hoursAgo: number | null | undefined): string => {
    if (hoursAgo == null) return '—';
    if (hoursAgo < 1) return `${Math.round(hoursAgo * 60)} min ago`;
    if (hoursAgo < 24) return `${hoursAgo.toFixed(1)} h ago`;
    return `${(hoursAgo / 24).toFixed(1)} days ago`;
  };
  const fmtAbs = (iso: string | null | undefined): string => {
    if (!iso) return '—';
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  };

  // ── Actions ────────────────────────────────────────────────────────────
  const catchUp = async () => {
    if (pipelineRunning) {
      onError('A pipeline run is already in progress. Wait for it to finish or stop it first.');
      return;
    }
    if (!lastRun?.finished_at) {
      onError('No previous successful ingest found. Trigger a normal run first.');
      return;
    }
    setApplying(true);
    try {
      const r = await api.fillGaps({ since: lastRun.finished_at });
      if (r.started) {
        onInfo(`Catch-up started — fetching everything after ${fmtAbs(lastRun.finished_at)} UTC.`);
      } else {
        onError(`Could not start: ${r.reason ?? 'unknown'}`);
      }
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Catch-up failed');
    } finally {
      setApplying(false);
    }
  };

  const dryRun = async () => {
    setPlanning(true);
    setPlan(null);
    try {
      const opts: { since?: string; gapHours?: number; dryRun: boolean } = { dryRun: true };
      if (planMode === 'since' && since) opts.since = new Date(since).toISOString();
      else opts.gapHours = gapHours;
      const r = await api.fillGaps(opts);
      if (r.plan) { setPlan(r.plan.plan); setShowPlan(true); }
      else onError(`Dry-run failed: ${r.reason ?? r.detail ?? 'unknown'}`);
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Dry-run failed');
    } finally {
      setPlanning(false);
    }
  };

  const applyAdvanced = async () => {
    if (pipelineRunning) {
      onError('A pipeline run is already in progress. Wait for it to finish or stop it first.');
      return;
    }
    setApplying(true);
    try {
      const opts: { since?: string; gapHours?: number } = {};
      if (planMode === 'since' && since) opts.since = new Date(since).toISOString();
      else opts.gapHours = gapHours;
      const r = await api.fillGaps(opts);
      if (r.started) {
        onInfo(
          planMode === 'since'
            ? `Fill-gaps started (since ${since} local time).`
            : `Fill-gaps started (auto mode, gap threshold ${gapHours}h).`
        );
        setShowPlan(false); setPlan(null);
      } else onError(`Could not start: ${r.reason ?? 'unknown'}`);
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Fill-gaps failed');
    } finally {
      setApplying(false);
    }
  };

  const runAnalyzePending = async () => {
    if (pipelineRunning) {
      onError('A pipeline run is already in progress. Wait for it to finish or stop it first.');
      return;
    }
    setAnalyzing(true);
    try {
      const r = await api.analyzePending();
      if (r.started) {
        onInfo(`Analyze started — processing ${pending.toLocaleString()} un-analyzed posts. No upstream fetches.`);
        onReload();
      } else {
        onError(`Could not start: ${r.reason ?? 'unknown'}`);
      }
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Analyze failed');
    } finally {
      setAnalyzing(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────
  const hoursSinceRun = lastRun?.hours_ago ?? null;
  const isStale = hoursSinceRun == null || hoursSinceRun > 3; // more than 3h = "catch up" recommended
  const statusIcon = pipelineRunning
    ? <Loader2 size={16} className="text-walmart-blue animate-spin" />
    : isStale
      ? <AlertCircle size={16} className="text-sentiment-negative" />
      : <CheckCircle2 size={16} className="text-sentiment-positive" />;

  return (
    <div className="bg-surface border border-walmart-navy/10 rounded-2xl shadow-card p-5 space-y-4">
      {/* Header: what happened, when */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold text-walmart-navy flex items-center gap-2">
            {statusIcon}
            Data health
          </h3>
          <p className="text-xs text-gray-500 mt-1">
            Last successful ingest was <span className="font-semibold text-walmart-navy">{fmtRelative(hoursSinceRun)}</span>
            {lastRun && <> at <span className="font-mono text-walmart-navy">{fmtAbs(lastRun.finished_at)}</span></>}
            {lastRun && <> · pulled <span className="font-semibold text-walmart-navy">{lastRun.ingested.toLocaleString()}</span> new posts</>}.
          </p>
          {pending > 0 && (
            <p className="text-xs text-gray-500 mt-0.5">
              <span className="font-semibold text-walmart-navy">{pending.toLocaleString()}</span> posts are ingested but not yet analyzed.
            </p>
          )}
        </div>
        {pipelineRunning && (
          <span className="text-xs bg-walmart-blue/10 text-walmart-blue px-2.5 py-1 rounded-pill font-semibold">
            Pipeline is running…
          </span>
        )}
      </div>

      {/* Primary actions — one clear "catch up" + one "analyze what's here" */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="border border-walmart-blue/25 rounded-xl p-4 bg-walmart-blue/[0.03]">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <div className="text-sm font-semibold text-walmart-navy flex items-center gap-1.5">
                <RefreshCw size={14} className="text-walmart-blue" /> Catch up from last run
              </div>
              <div className="text-xs text-gray-600 mt-0.5">
                Fetches every post created after
                {' '}
                <span className="font-mono text-walmart-navy">
                  {lastRun ? fmtAbs(lastRun.finished_at) : '—'}
                </span>
                {lastRun && <> ({fmtRelative(hoursSinceRun)})</>} across all 25 subreddits.
              </div>
            </div>
          </div>
          <button
            onClick={catchUp}
            disabled={applying || pipelineRunning || !lastRun}
            className="w-full px-3 py-2 text-sm rounded-pill bg-walmart-blue text-white hover:bg-walmart-blue/90 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center gap-1.5 font-semibold shadow-sm"
            title={!lastRun ? 'Need at least one successful ingest first' : pipelineRunning ? 'Wait for the current run to finish' : 'Fill everything since the last run'}
          >
            {applying ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {!lastRun ? 'No previous run to catch up from' : `Catch up now (~${fmtRelative(hoursSinceRun)} of data)`}
          </button>
        </div>

        <div className="border border-walmart-spark/40 rounded-xl p-4 bg-walmart-spark/[0.05]">
          <div className="text-sm font-semibold text-walmart-navy flex items-center gap-1.5">
            <Activity size={14} className="text-walmart-spark-dark" /> Analyze pending posts
          </div>
          <div className="text-xs text-gray-600 mt-0.5 mb-2">
            Runs sentiment + aspect analysis on posts already ingested that never got a sentiment row. No upstream fetches.
          </div>
          <div className="mb-3">
            <div className="text-xl font-bold text-walmart-navy">
              {pending.toLocaleString()}
              <span className="text-xs font-normal text-gray-500 ml-2">
                of {backlog?.raw_posts.toLocaleString() ?? '—'} total posts
              </span>
            </div>
          </div>
          <button
            onClick={runAnalyzePending}
            disabled={analyzing || pipelineRunning || pending === 0}
            className="w-full px-3 py-2 text-sm rounded-pill bg-walmart-spark text-walmart-navy hover:bg-walmart-spark-dark disabled:bg-gray-200 disabled:text-gray-500 disabled:cursor-not-allowed flex items-center justify-center gap-1.5 font-semibold shadow-sm"
            title={pipelineRunning ? 'Wait for the current run to finish' : pending === 0 ? 'Nothing to analyze' : 'Process the backlog'}
          >
            {analyzing ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {pending === 0 ? 'Nothing to analyze' : `Analyze ${pending.toLocaleString()} posts`}
          </button>
        </div>
      </div>

      {/* Freshness summary strip */}
      <div className="text-xs text-gray-500 flex items-center gap-3 flex-wrap px-1">
        <span>
          <span className="font-semibold text-sentiment-positive">{totals.fresh}</span> fresh
          {' · '}
          <span className="font-semibold text-walmart-navy">{totals.stale}</span> stale
          {' · '}
          <span className="font-semibold text-walmart-navy">{totals.drifted}</span> drifted
          {' / '}
          {totals.subreddits} subs tracked
        </span>
        {gaps?.generated_at && (
          <>
            <span>·</span>
            <span className="font-mono">as of {new Date(gaps.generated_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</span>
          </>
        )}
      </div>

      {/* Advanced — everything power users need, hidden by default */}
      <div className="border-t border-walmart-navy/5 pt-3">
        <button
          onClick={() => setAdvancedOpen(!advancedOpen)}
          className="text-xs text-gray-600 hover:text-walmart-blue flex items-center gap-1 font-medium"
        >
          {advancedOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          Advanced &mdash; custom time range, per-sub gap detail, plan preview
        </button>

        {advancedOpen && (
          <div className="mt-3 space-y-3">
            {/* Mode selector */}
            <div className="flex gap-1 p-0.5 bg-white border border-walmart-navy/10 rounded-pill w-fit">
              {(['since', 'auto'] as const).map(m => (
                <button
                  key={m}
                  onClick={() => setPlanMode(m)}
                  className={`px-3 py-1 text-xs rounded-pill font-medium transition-colors ${
                    planMode === m ? 'bg-walmart-blue text-white shadow-sm' : 'text-gray-600 hover:bg-walmart-blue/5'
                  }`}
                >
                  {m === 'since' ? 'Rewind since date' : 'Auto per-subreddit'}
                </button>
              ))}
            </div>

            {planMode === 'since' ? (
              <div className="text-xs text-gray-600 flex items-center gap-2 flex-wrap">
                <span>Rewind every subreddit whose cursor is more recent than</span>
                <input
                  type="datetime-local"
                  value={since}
                  onChange={(e) => setSince(e.target.value)}
                  className="px-2 py-0.5 border border-walmart-navy/15 rounded font-mono text-walmart-navy"
                />
                <span className="text-gray-400">(local time)</span>
              </div>
            ) : (
              <div className="text-xs text-gray-600 flex items-center gap-2">
                <span>Skip subreddits whose gap is smaller than</span>
                <input
                  type="number" min={0} max={720} step={1}
                  value={gapHours}
                  onChange={(e) => setGapHours(Number(e.target.value) || 0)}
                  className="w-16 px-2 py-0.5 border border-walmart-navy/15 rounded text-center font-mono text-walmart-navy"
                />
                <span>hours</span>
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={dryRun}
                disabled={planning}
                className="px-3 py-1.5 text-xs rounded-pill border border-walmart-navy/15 bg-white hover:bg-walmart-blue/5 text-walmart-navy disabled:opacity-50 flex items-center gap-1"
              >
                {planning ? <Loader2 size={12} className="animate-spin" /> : <Info size={12} />}
                Preview plan
              </button>
              <button
                onClick={applyAdvanced}
                disabled={applying || pipelineRunning}
                className="px-3 py-1.5 text-xs rounded-pill bg-walmart-navy text-white hover:bg-walmart-navy/90 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-1 font-semibold"
              >
                {applying ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
                Run with these options
              </button>
            </div>

            {/* Plan preview */}
            {showPlan && plan && (
              <div className="border border-walmart-navy/10 rounded-xl overflow-hidden">
                <div className="px-4 py-2 bg-walmart-navy/[0.03] flex items-center justify-between">
                  <div className="text-xs font-semibold text-walmart-navy">
                    Plan &mdash; {plan.length} subreddit{plan.length === 1 ? '' : 's'} would be rewound
                  </div>
                  <button onClick={() => setShowPlan(false)} className="text-gray-400 hover:text-walmart-navy">
                    <X size={13} />
                  </button>
                </div>
                {plan.length === 0 ? (
                  <div className="p-4 text-xs text-gray-500">Everything is already caught up for the selected criteria.</div>
                ) : (
                  <div className="max-h-64 overflow-y-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-white sticky top-0 border-b border-walmart-navy/10">
                        <tr className="text-gray-500 text-left">
                          <th className="px-4 py-2 font-medium">Subreddit</th>
                          <th className="px-4 py-2 font-medium text-right">Rewind (h)</th>
                          <th className="px-4 py-2 font-medium">New cursor (UTC)</th>
                          <th className="px-4 py-2 font-medium">Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...plan].sort((a, b) => (b.rewind_hours ?? 0) - (a.rewind_hours ?? 0)).map(e => {
                          const rewind = e.rewind_hours ?? 0;
                          const newIso = e.new_cursor_utc
                            ? new Date(e.new_cursor_utc * 1000).toISOString().replace('T', ' ').slice(0, 16)
                            : '—';
                          return (
                            <tr key={e.subreddit} className="border-t border-walmart-navy/5 hover:bg-walmart-blue/[0.02]">
                              <td className="px-4 py-1.5 font-mono text-walmart-navy">{e.subreddit}</td>
                              <td className={`px-4 py-1.5 text-right font-mono ${rewind < 0 ? 'text-walmart-blue' : 'text-walmart-navy'}`}>{rewind.toFixed(1)}</td>
                              <td className="px-4 py-1.5 font-mono text-gray-600">{newIso}</td>
                              <td className="px-4 py-1.5">
                                <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                                  e.reason === 'cursor_ahead_of_data' ? 'bg-walmart-blue/10 text-walmart-blue'
                                    : e.reason === 'never_fetched' ? 'bg-gray-100 text-gray-600'
                                    : 'bg-sentiment-negative/10 text-sentiment-negative'
                                }`}>{e.reason}</span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Per-sub gap detail */}
            {gaps && gaps.subreddits.length > 0 && (
              <details className="border border-walmart-navy/10 rounded-xl">
                <summary className="px-4 py-2 cursor-pointer text-xs font-semibold text-walmart-navy bg-walmart-navy/[0.03] hover:bg-walmart-blue/[0.05] rounded-t-xl">
                  Per-subreddit freshness ({gaps.subreddits.length} subs)
                </summary>
                <div className="max-h-64 overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-white sticky top-0 border-b border-walmart-navy/10">
                      <tr className="text-gray-500 text-left">
                        <th className="px-4 py-2 font-medium">Subreddit</th>
                        <th className="px-4 py-2 font-medium text-right">Posts</th>
                        <th className="px-4 py-2 font-medium text-right">Gap (h)</th>
                        <th className="px-4 py-2 font-medium text-right">Cursor drift (h)</th>
                        <th className="px-4 py-2 font-medium">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...gaps.subreddits].sort((a, b) => (b.gap_hours ?? 0) - (a.gap_hours ?? 0)).map(s => (
                        <tr key={s.subreddit} className="border-t border-walmart-navy/5">
                          <td className="px-4 py-1.5 font-mono text-walmart-navy">{s.subreddit}</td>
                          <td className="px-4 py-1.5 text-right font-mono">{s.post_count.toLocaleString()}</td>
                          <td className="px-4 py-1.5 text-right font-mono">{s.gap_hours == null ? '∞' : s.gap_hours.toFixed(1)}</td>
                          <td className={`px-4 py-1.5 text-right font-mono ${s.cursor_drift_hours < -1 ? 'text-sentiment-negative' : 'text-gray-500'}`}>{s.cursor_drift_hours.toFixed(1)}</td>
                          <td className="px-4 py-1.5">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                              s.reason === 'fresh' ? 'bg-sentiment-positive/10 text-sentiment-positive'
                                : s.reason === 'cursor_ahead_of_data' ? 'bg-walmart-blue/10 text-walmart-blue'
                                : s.reason === 'never_fetched' ? 'bg-gray-100 text-gray-600'
                                : 'bg-sentiment-negative/10 text-sentiment-negative'
                            }`}>{s.reason}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Section A3: Image Availability Panel ─────────────────────────────────
// Shows the outcome of every image fetch attempt: how many succeeded, how
// many were dead (404 = user deleted the post, 429 = imgur throttled, 403 =
// private, etc.). Lets analysts confirm they're not silently losing image
// context from removed content.

const IMG_STATUS_STYLE: Record<string, { label: string; className: string }> = {
  fetched:          { label: 'Fetched',          className: 'bg-sentiment-positive/10 text-sentiment-positive' },
  deleted:          { label: 'Deleted (404)',    className: 'bg-sentiment-negative/10 text-sentiment-negative' },
  gone:             { label: 'Gone (410)',       className: 'bg-sentiment-negative/10 text-sentiment-negative' },
  forbidden:        { label: 'Forbidden (403)',  className: 'bg-amber-100 text-amber-800' },
  throttled:        { label: 'Throttled (429)',  className: 'bg-amber-100 text-amber-800' },
  too_large:        { label: 'Too large',        className: 'bg-gray-100 text-gray-700' },
  not_image:        { label: 'Not an image',     className: 'bg-gray-100 text-gray-700' },
  server_error:     { label: 'Server error',     className: 'bg-sentiment-negative/10 text-sentiment-negative' },
  connection_error: { label: 'Connection error', className: 'bg-amber-100 text-amber-800' },
  decode_error:     { label: 'Decode error',     className: 'bg-gray-100 text-gray-700' },
  client_error:     { label: 'Client error',     className: 'bg-sentiment-negative/10 text-sentiment-negative' },
};

function ImageFailuresPanel({ report }: { report: ImageFailuresReport | null }) {
  const [open, setOpen] = useState(false);

  if (!report || report.total_checked === 0) {
    return null; // Nothing to show until at least one image has been checked.
  }

  const failedPct = report.total_checked > 0
    ? (100 * report.total_failed / report.total_checked)
    : 0;
  const totals = report.totals_by_status || {};
  const sortedStatuses = Object.entries(totals)
    .filter(([k]) => k !== 'fetched')
    .sort((a, b) => b[1] - a[1]);

  const fmtWhen = (iso: string | null) => {
    if (!iso) return '—';
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  };

  return (
    <div className="bg-surface border border-walmart-navy/10 rounded-2xl shadow-card">
      <button
        onClick={() => setOpen(!open)}
        className="w-full p-5 flex items-center justify-between hover:bg-walmart-blue/5 rounded-2xl text-left"
      >
        <div className="flex items-center gap-3">
          {open ? <ChevronDown size={16} className="text-walmart-navy" /> : <ChevronRight size={16} className="text-walmart-navy" />}
          <div>
            <h3 className="text-base font-semibold text-walmart-navy flex items-center gap-2">
              <AlertCircle size={16} className={report.total_failed > 0 ? 'text-sentiment-negative' : 'text-sentiment-positive'} />
              Image availability
            </h3>
            <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-3 flex-wrap">
              <span>
                <span className="font-semibold text-walmart-navy">{report.total_fetched.toLocaleString()}</span> fetched
                {' · '}
                <span className="font-semibold text-sentiment-negative">{report.total_failed.toLocaleString()}</span> unavailable
                {' · '}
                <span className="font-mono">{failedPct.toFixed(1)}%</span> failure rate
                {' / '}
                {report.total_checked.toLocaleString()} attempts
              </span>
            </div>
          </div>
        </div>
      </button>

      {open && (
        <div className="px-5 pb-5 space-y-4">
          {/* Status breakdown bar chart */}
          <div>
            <div className="text-xs font-semibold text-walmart-navy mb-2">Failure breakdown</div>
            <div className="space-y-1.5">
              {sortedStatuses.length === 0 ? (
                <div className="text-xs text-gray-500">No failures recorded.</div>
              ) : (
                sortedStatuses.map(([status, count]) => {
                  const style = IMG_STATUS_STYLE[status] ?? { label: status, className: 'bg-gray-100 text-gray-700' };
                  const pct = report.total_checked > 0 ? (100 * count / report.total_checked) : 0;
                  return (
                    <div key={status} className="flex items-center gap-3 text-xs">
                      <span className={`px-2 py-0.5 rounded font-medium min-w-[110px] text-center ${style.className}`}>
                        {style.label}
                      </span>
                      <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                        <div
                          className="h-full bg-sentiment-negative/60"
                          style={{ width: `${Math.min(100, pct * 5)}%` }}
                          title={`${count} of ${report.total_checked} attempts (${pct.toFixed(1)}%)`}
                        />
                      </div>
                      <span className="font-mono text-walmart-navy min-w-[50px] text-right">
                        {count.toLocaleString()}
                      </span>
                      <span className="text-gray-400 font-mono min-w-[45px] text-right">
                        {pct.toFixed(1)}%
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Recent failures table */}
          {report.samples.length > 0 && (
            <div className="border border-walmart-navy/10 rounded-xl overflow-hidden">
              <div className="px-4 py-2 bg-walmart-navy/[0.03] text-xs font-semibold text-walmart-navy">
                Recent unavailable images ({report.samples.length} shown)
              </div>
              <div className="max-h-80 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="bg-white sticky top-0 border-b border-walmart-navy/10">
                    <tr className="text-gray-500 text-left">
                      <th className="px-4 py-2 font-medium">Post</th>
                      <th className="px-4 py-2 font-medium">Sub</th>
                      <th className="px-4 py-2 font-medium">Status</th>
                      <th className="px-4 py-2 font-medium">URL</th>
                      <th className="px-4 py-2 font-medium">Checked</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.samples.map(s => {
                      const style = IMG_STATUS_STYLE[s.status] ?? { label: s.status, className: 'bg-gray-100 text-gray-700' };
                      const permalink = s.permalink ? `https://reddit.com${s.permalink}` : null;
                      return (
                        <tr key={s.post_id} className="border-t border-walmart-navy/5 hover:bg-walmart-blue/[0.02]">
                          <td className="px-4 py-1.5 max-w-[280px]">
                            {permalink ? (
                              <a href={permalink} target="_blank" rel="noreferrer" className="text-walmart-blue hover:underline truncate block" title={s.title}>
                                {s.title || s.post_id}
                              </a>
                            ) : (
                              <span className="truncate block" title={s.title}>{s.title || s.post_id}</span>
                            )}
                            <span className="font-mono text-[10px] text-gray-400">{s.post_id}</span>
                          </td>
                          <td className="px-4 py-1.5 font-mono text-walmart-navy">{s.subreddit}</td>
                          <td className="px-4 py-1.5">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${style.className}`}>
                              {style.label}
                            </span>
                          </td>
                          <td className="px-4 py-1.5 max-w-[280px]">
                            <a href={s.url} target="_blank" rel="noreferrer" className="text-gray-500 hover:text-walmart-blue truncate block font-mono text-[10px]" title={s.url}>
                              {s.url.replace(/^https?:\/\//, '')}
                            </a>
                          </td>
                          <td className="px-4 py-1.5 font-mono text-gray-500">{fmtWhen(s.checked_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
