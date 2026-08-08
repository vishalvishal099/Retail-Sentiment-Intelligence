import { useEffect, useMemo, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts';
import { api, Alert, AlertRules, AlertRule, AlertTimelineBucket } from '../api';
import { useAlertSocket } from '../useAlertSocket';
import Card from '../components/Card';
import Button from '../components/Button';

const SEVERITY_STYLES: Record<string, { border: string; bg: string; pill: string }> = {
  critical: { border: 'border-l-sentiment-negative', bg: 'bg-sentiment-negative/5', pill: 'bg-sentiment-negative/15 text-sentiment-negative' },
  high:     { border: 'border-l-sentiment-negative', bg: 'bg-sentiment-negative/5', pill: 'bg-sentiment-negative/15 text-sentiment-negative' },
  medium:   { border: 'border-l-walmart-spark-dark', bg: 'bg-walmart-spark/10', pill: 'bg-walmart-spark/30 text-walmart-navy' },
  low:      { border: 'border-l-walmart-blue', bg: 'bg-walmart-blue/5', pill: 'bg-walmart-blue/15 text-walmart-blue' },
};

const STATE_LABELS: Record<string, { label: string; color: string; next: Array<'acknowledged' | 'investigating' | 'resolved'> }> = {
  new:           { label: 'New', color: 'bg-sentiment-negative/15 text-sentiment-negative border-sentiment-negative/25', next: ['acknowledged', 'investigating', 'resolved'] },
  acknowledged:  { label: 'Acknowledged', color: 'bg-walmart-spark/30 text-walmart-navy border-walmart-spark/40', next: ['investigating', 'resolved'] },
  investigating: { label: 'Investigating', color: 'bg-walmart-blue/15 text-walmart-blue border-walmart-blue/25', next: ['resolved'] },
  resolved:      { label: 'Resolved', color: 'bg-sentiment-positive/15 text-sentiment-positive border-sentiment-positive/25', next: [] },
};

const TYPE_OPTIONS = ['', 'volume_spike', 'sentiment_crash', 'emerging_topic', 'competitor_negative'] as const;
const SEVERITY_OPTIONS = ['', 'high', 'medium', 'low'] as const;
const STATE_OPTIONS = ['', 'new', 'acknowledged', 'investigating', 'resolved'] as const;
const RANGE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'week', label: 'Last 7 Days' },
  { value: 'month', label: 'Last 30 Days' },
  { value: '90d', label: 'Last 90 Days' },
];

export default function AlertFeed() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [range, setRange] = useState('week');
  const [severity, setSeverity] = useState<string>('');
  const [type, setType] = useState<string>('');
  const [state, setState] = useState<string>('');
  const [timeline, setTimeline] = useState<AlertTimelineBucket[]>([]);
  const [rules, setRules] = useState<AlertRules | null>(null);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [savingRules, setSavingRules] = useState(false);
  const [savingState, setSavingState] = useState<string | null>(null);
  const realtimeAlerts = useAlertSocket();

  const load = () => {
    setLoading(true);
    api.getAlerts({
      range,
      severity: severity || undefined,
      type: type || undefined,
      state: state || undefined,
      limit: 200,
    })
      .then(d => setAlerts(d.alerts))
      .catch(console.error)
      .finally(() => setLoading(false));
  };
  useEffect(load, [range, severity, type, state]);
  useEffect(() => { api.getAlertsTimeline(30).then(t => setTimeline(t.buckets)).catch(console.error); }, [range, severity, type, state]);
  useEffect(() => { api.getAlertRules().then(r => setRules(r.rules)).catch(console.error); }, []);

  // Merge: realtime alerts on top, then stored (dedup by id).
  const allAlerts: Alert[] = useMemo(() => {
    const map = new Map<string, Alert>();
    realtimeAlerts.forEach(a => map.set(a.id, { ...a, state: (a as Alert).state || 'new' }));
    alerts.forEach(a => { if (!map.has(a.id)) map.set(a.id, { ...a, state: a.state || 'new' }); });
    return Array.from(map.values());
  }, [alerts, realtimeAlerts]);

  const handleStateChange = async (alertId: string, next: 'acknowledged' | 'investigating' | 'resolved') => {
    setSavingState(alertId);
    try {
      const res = await api.updateAlertState(alertId, next);
      if (res.status === 'saved' && res.alert) {
        setAlerts(prev => prev.map(a => a.id === alertId ? { ...a, ...res.alert! } : a));
      }
    } finally {
      setSavingState(null);
    }
  };

  const handleRuleChange = (ruleKey: string, patch: Partial<AlertRule>) => {
    if (!rules) return;
    setRules({ ...rules, [ruleKey]: { ...rules[ruleKey], ...patch } });
  };
  const saveRules = async () => {
    if (!rules) return;
    setSavingRules(true);
    try {
      const res = await api.updateAlertRules(rules);
      if (res.rules) setRules(res.rules);
    } finally {
      setSavingRules(false);
    }
  };

  const counts = useMemo(() => {
    const total = allAlerts.length;
    const byState: Record<string, number> = { new: 0, acknowledged: 0, investigating: 0, resolved: 0 };
    allAlerts.forEach(a => { const s = a.state || 'new'; if (s in byState) byState[s]++; });
    return {
      total,
      new: byState.new,
      acknowledged: byState.acknowledged,
      investigating: byState.investigating,
      resolved: byState.resolved,
    };
  }, [allAlerts]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-2xl font-bold text-walmart-navy">Alert Feed</h2>
          <p className="text-xs text-gray-500 mt-1">Severity-graded signals from the alerting engine and live websocket.</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap text-xs">
          <StatPill label="Total" value={counts.total} />
          <StatPill label="New" value={counts.new} tone="negative" />
          <StatPill label="Acknowledged" value={counts.acknowledged} tone="warning" />
          <StatPill label="Investigating" value={counts.investigating} tone="blue" />
          <StatPill label="Resolved" value={counts.resolved} tone="positive" />
        </div>
      </div>

      {/* Timeline chart */}
      {timeline.length > 0 && (
        <Card>
          <h3 className="text-sm font-semibold text-walmart-navy uppercase tracking-wider mb-3">
            Alert timeline (last 30 days)
          </h3>
          <div style={{ width: '100%', height: 220 }}>
            <ResponsiveContainer>
              <BarChart data={timeline} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#6b7280' }} />
                <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} allowDecimals={false} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="high" stackId="a" fill="#DE1C24" name="High" />
                <Bar dataKey="medium" stackId="a" fill="#F0932B" name="Medium" />
                <Bar dataKey="low" stackId="a" fill="#0071DC" name="Low" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* Filters */}
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <SelectField label="Range" value={range} onChange={setRange} options={RANGE_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
          <SelectField label="Severity" value={severity} onChange={setSeverity} options={SEVERITY_OPTIONS.map(v => ({ value: v, label: v || 'All' }))} />
          <SelectField label="Type" value={type} onChange={setType} options={TYPE_OPTIONS.map(v => ({ value: v, label: (v || 'All').replace(/_/g, ' ') }))} />
          <SelectField label="State" value={state} onChange={setState} options={STATE_OPTIONS.map(v => ({ value: v, label: v || 'All' }))} />
          <div className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" onClick={load} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</Button>
            <Button variant="outline" size="sm" onClick={() => setRulesOpen(o => !o)}>
              {rulesOpen ? 'Hide rules ▲' : 'Rules ⚙︎'}
            </Button>
          </div>
        </div>
      </Card>

      {/* Rules panel */}
      {rulesOpen && rules && (
        <AlertRulesPanel rules={rules} onChange={handleRuleChange} onSave={saveRules} saving={savingRules} />
      )}

      {/* Alerts */}
      {loading && alerts.length === 0 ? (
        <div className="text-gray-500 p-4">Loading alerts…</div>
      ) : allAlerts.length === 0 ? (
        <Card className="text-center py-12 text-gray-500">
          <p className="text-lg font-semibold text-walmart-navy">No alerts</p>
          <p className="text-sm">Nothing matched the current filter.</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {allAlerts.map(alert => {
            const style = SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.medium;
            const st = alert.state || 'new';
            const stateStyle = STATE_LABELS[st] || STATE_LABELS.new;
            const saving = savingState === alert.id;
            const affectedMacro = alert.type === 'sentiment_crash'
              ? String((alert.details as Record<string, unknown> | undefined)?.affected_macro_group || '')
              : '';
            const topSubs = alert.type === 'sentiment_crash'
              ? String((alert.details as Record<string, unknown> | undefined)?.top_subreddits_today || '')
              : '';
            const topSub = topSubs
              ? topSubs.includes(' | ')
                ? topSubs.split(' | ')[0].trim()
                : topSubs.includes('), ')
                  ? `${topSubs.split('), ')[0].trim()})`
                  : topSubs.split(',')[0].trim()
              : '';
            const macroLabel = affectedMacro === 'competitor'
              ? 'Competitors'
              : affectedMacro === 'walmart'
                ? 'Walmart'
                : '';
            const rawTitle = alert.title || alert.message;
            const withMacro = macroLabel && !rawTitle.includes('Sentiment crash (')
              ? rawTitle.replace('Sentiment crash', `Sentiment crash (${macroLabel})`)
              : rawTitle;
            const displayTitle = topSub && !withMacro.includes('r/')
              ? `${withMacro} [${topSub}]`
              : withMacro;
            return (
              <div key={alert.id} className={`bg-surface shadow-card border border-walmart-navy/10 border-l-4 ${style.border} rounded-r-2xl p-4`}>
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className="text-[11px] uppercase font-bold tracking-wider text-gray-500">{alert.type.replace(/_/g, ' ')}</span>
                      <span className={`px-2 py-0.5 rounded-pill text-[11px] font-semibold ${style.pill}`}>{alert.severity}</span>
                      <span className={`px-2 py-0.5 rounded-pill text-[11px] font-semibold border ${stateStyle.color}`}>{stateStyle.label}</span>
                      {alert.state_updated_by && (
                        <span className="text-[10px] text-gray-400">by {alert.state_updated_by} · {alert.state_updated_at ? new Date(alert.state_updated_at).toLocaleString() : ''}</span>
                      )}
                    </div>
                    <p className="text-sm font-medium text-walmart-navy">{displayTitle}</p>
                    {Object.keys(alert.details || {}).length > 0 && (
                      <div className="flex flex-wrap gap-3 mt-1 text-[11px] text-gray-500">
                        {Object.entries(alert.details).slice(0, 4).map(([k, v]) => (
                          <span key={k}><span className="font-mono">{k}</span>: {String(v)}</span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col gap-1 items-end shrink-0">
                    <span className="text-xs text-gray-400 whitespace-nowrap">{alert.time_window}</span>
                    <div className="flex gap-1 flex-wrap">
                      {stateStyle.next.map(nx => (
                        <button
                          key={nx}
                          onClick={() => handleStateChange(alert.id, nx)}
                          disabled={saving}
                          className="text-[11px] px-2 py-0.5 rounded-pill border border-walmart-navy/20 text-walmart-navy hover:bg-walmart-blue/5 disabled:opacity-40"
                        >
                          → {nx}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function StatPill({ label, value, tone = 'neutral' }: { label: string; value: number; tone?: 'neutral' | 'positive' | 'negative' | 'warning' | 'blue' }) {
  const cls = tone === 'positive' ? 'bg-sentiment-positive/10 text-sentiment-positive border-sentiment-positive/20'
    : tone === 'negative' ? 'bg-sentiment-negative/10 text-sentiment-negative border-sentiment-negative/20'
    : tone === 'warning' ? 'bg-walmart-spark/25 text-walmart-navy border-walmart-spark/40'
    : tone === 'blue' ? 'bg-walmart-blue/10 text-walmart-blue border-walmart-blue/20'
    : 'bg-walmart-navy/5 text-walmart-navy border-walmart-navy/15';
  return (
    <span className={`px-3 py-1 rounded-pill text-xs font-medium border ${cls}`}>
      {label}: {value}
    </span>
  );
}

function SelectField({
  label, value, onChange, options,
}: { label: string; value: string; onChange: (v: string) => void; options: Array<{ value: string; label: string }> }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{label}</label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="border border-walmart-navy/15 rounded-pill px-4 py-1.5 text-sm bg-white shadow-sm text-walmart-navy focus:outline-none focus:ring-2 focus:ring-walmart-blue"
      >
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

function AlertRulesPanel({
  rules, onChange, onSave, saving,
}: {
  rules: AlertRules;
  onChange: (ruleKey: string, patch: Partial<AlertRule>) => void;
  onSave: () => void;
  saving: boolean;
}) {
  return (
    <Card>
      <div className="flex items-baseline justify-between mb-3 flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold text-walmart-navy uppercase tracking-wider">Alert rules</h3>
          <p className="text-xs text-gray-500 mt-1">Adjust thresholds and enable/disable detectors. Saved to <span className="font-mono">data/alert_rules.json</span> — next pipeline cycle picks them up.</p>
        </div>
        <Button variant="primary" size="sm" onClick={onSave} disabled={saving}>{saving ? 'Saving…' : 'Save rules'}</Button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Object.entries(rules).map(([key, rule]) => (
          <div key={key} className="border border-walmart-navy/10 rounded-xl p-3">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-semibold text-walmart-navy capitalize">{key.replace(/_/g, ' ')}</span>
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!rule.enabled}
                  onChange={e => onChange(key, { enabled: e.target.checked })}
                  className="rounded border-walmart-navy/30 text-walmart-blue focus:ring-walmart-blue"
                />
                Enabled
              </label>
            </div>
            <p className="text-[11px] text-gray-500 mb-2 leading-snug">{rule.description}</p>
            <div className="flex flex-wrap gap-3">
              {typeof rule.sigma_threshold === 'number' && (
                <NumberField label="σ threshold" value={rule.sigma_threshold} step={0.1} min={0.5} max={5} onChange={v => onChange(key, { sigma_threshold: v })} />
              )}
              {typeof rule.drop_threshold === 'number' && (
                <NumberField label="Drop threshold" value={rule.drop_threshold} step={0.05} min={0.05} max={1} onChange={v => onChange(key, { drop_threshold: v })} />
              )}
              {typeof rule.min_posts === 'number' && (
                <NumberField label="Min posts" value={rule.min_posts} step={1} min={2} max={50} onChange={v => onChange(key, { min_posts: v })} />
              )}
              {typeof rule.window_hours === 'number' && (
                <NumberField label="Window (h)" value={rule.window_hours} step={1} min={1} max={24} onChange={v => onChange(key, { window_hours: v })} />
              )}
              {typeof rule.delta_threshold === 'number' && (
                <NumberField label="WoW delta" value={rule.delta_threshold} step={0.01} min={0.01} max={1} onChange={v => onChange(key, { delta_threshold: v })} />
              )}
              {typeof rule.min_posts_per_window === 'number' && (
                <NumberField label="Min posts / 7d" value={rule.min_posts_per_window} step={1} min={1} max={500} onChange={v => onChange(key, { min_posts_per_window: v })} />
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function NumberField({
  label, value, onChange, step, min, max,
}: { label: string; value: number; onChange: (v: number) => void; step: number; min: number; max: number }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">{label}</label>
      <input
        type="number"
        step={step}
        min={min}
        max={max}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-24 border border-walmart-navy/15 rounded-lg px-2 py-1 text-sm font-mono text-walmart-navy focus:outline-none focus:ring-2 focus:ring-walmart-blue"
      />
    </div>
  );
}
