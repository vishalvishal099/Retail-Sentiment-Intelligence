import { useEffect, useState } from 'react';
import { Loader2, Plus, Trash2, TestTube, Mail, ToggleLeft, ToggleRight, ChevronDown, ChevronUp, Bell } from 'lucide-react';
import { api, NotificationGroup, NotificationLogEntry } from '../api';

export default function Notifications() {
  const [groups, setGroups] = useState<NotificationGroup[]>([]);
  const [log, setLog] = useState<NotificationLogEntry[]>([]);
  const [senderEmail, setSenderEmail] = useState('');
  const [subreddits, setSubreddits] = useState<Array<{ subreddit: string; group: string; macro_group: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const [configRes, logRes, subsRes] = await Promise.all([
        api.getNotificationConfig(),
        api.getNotificationLog(50),
        api.getAvailableSubreddits(),
      ]);
      setGroups(configRes.groups);
      setSenderEmail(configRes.sender_email);
      setLog(logRes.log);
      setSubreddits(subsRes.subreddits);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this notification group?')) return;
    await api.deleteNotificationGroup(id);
    await refresh();
  };

  const handleToggle = async (g: NotificationGroup) => {
    await api.updateNotificationGroup(g.id, { enabled: !g.enabled });
    await refresh();
  };

  const handleTest = async (id: string) => {
    const res = await api.testNotificationGroup(id);
    alert(res.ok ? 'Test notification sent (dry-run)' : 'Test failed');
    await refresh();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-walmart-navy">Notification Configuration</h1>
          <p className="text-sm text-gray-600 mt-1">
            Configure which subreddit groups receive alerts for P1/P2 negative posts.
          </p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-pill bg-walmart-blue text-white text-sm font-semibold hover:bg-walmart-blue/90"
        >
          <Plus size={14} /> Add Group
        </button>
      </div>

      {/* Sender info */}
      <div className="bg-surface rounded-2xl border border-walmart-navy/10 p-4 shadow-card">
        <div className="flex items-center gap-3">
          <Mail size={16} className="text-walmart-blue" />
          <div>
            <div className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">Sender Email</div>
            <div className="text-sm font-medium text-walmart-navy">{senderEmail || '—'}</div>
          </div>
        </div>
      </div>

      {loading && <div className="text-gray-500 p-8 text-center">Loading...</div>}

      {/* Groups list */}
      {!loading && groups.length === 0 && (
        <div className="bg-surface rounded-2xl border border-dashed border-walmart-navy/20 p-8 text-center text-gray-500">
          No notification groups configured yet. Click "Add Group" to create one.
        </div>
      )}

      <div className="space-y-3">
        {groups.map((g) => (
          <GroupCard
            key={g.id}
            group={g}
            isEditing={editingId === g.id}
            onEdit={() => setEditingId(editingId === g.id ? null : g.id)}
            onToggle={() => handleToggle(g)}
            onDelete={() => handleDelete(g.id)}
            onTest={() => handleTest(g.id)}
            onSave={async (updated) => {
              await api.updateNotificationGroup(g.id, updated);
              setEditingId(null);
              await refresh();
            }}
            subreddits={subreddits}
          />
        ))}
      </div>

      {/* Add Group Modal */}
      {showAdd && (
        <AddGroupModal
          subreddits={subreddits}
          onClose={() => setShowAdd(false)}
          onCreated={async () => { setShowAdd(false); await refresh(); }}
        />
      )}

      {/* Notification Log */}
      <div className="bg-surface rounded-2xl border border-walmart-navy/10 shadow-card overflow-hidden">
        <div className="px-5 py-3 border-b border-walmart-navy/10">
          <h3 className="text-sm font-semibold text-walmart-navy flex items-center gap-2">
            <Bell size={14} /> Recent Notification Log
          </h3>
        </div>
        {log.length === 0 ? (
          <div className="p-6 text-center text-sm text-gray-500">No notifications sent yet.</div>
        ) : (
          <div className="max-h-[300px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase text-gray-500 bg-gray-50 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-2">Time</th>
                  <th className="text-left px-4 py-2">Group</th>
                  <th className="text-left px-4 py-2">Channel</th>
                  <th className="text-left px-4 py-2">Post</th>
                  <th className="text-left px-4 py-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {log.map((entry) => (
                  <tr key={entry.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-xs text-gray-600">
                      {new Date(entry.sent_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </td>
                    <td className="px-4 py-2 text-xs font-medium text-walmart-navy">{entry.group_name || entry.group_id}</td>
                    <td className="px-4 py-2 text-xs">{entry.channel}</td>
                    <td className="px-4 py-2 text-xs font-mono text-gray-600 truncate max-w-[120px]">{entry.post_id}</td>
                    <td className="px-4 py-2">
                      <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-pill ${
                        entry.status === 'sent' ? 'bg-sentiment-positive/15 text-sentiment-positive' :
                        entry.status === 'dry_run' ? 'bg-walmart-blue/15 text-walmart-blue' :
                        'bg-sentiment-negative/15 text-sentiment-negative'
                      }`}>
                        {entry.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function GroupCard({
  group, isEditing, onEdit, onToggle, onDelete, onTest, onSave, subreddits,
}: {
  group: NotificationGroup;
  isEditing: boolean;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
  onTest: () => void;
  onSave: (updated: Partial<NotificationGroup>) => Promise<void>;
  subreddits: Array<{ subreddit: string; group: string; macro_group: string }>;
}) {
  const [form, setForm] = useState({
    group_name: group.group_name,
    subreddits: group.subreddits,
    email_dl: group.email_dl,
    slack_channel: group.slack_channel || '',
    priority_filter: group.priority_filter,
  });
  const [saving, setSaving] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [newSub, setNewSub] = useState('');

  const handleSave = async () => {
    setSaving(true);
    await onSave(form);
    setSaving(false);
  };

  return (
    <div className={`bg-surface rounded-2xl border shadow-card transition-all ${group.enabled ? 'border-walmart-navy/10' : 'border-dashed border-gray-300 opacity-70'}`}>
      {/* Header row */}
      <div className="flex items-center justify-between px-5 py-3">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={onToggle} title={group.enabled ? 'Disable' : 'Enable'}>
            {group.enabled
              ? <ToggleRight size={22} className="text-sentiment-positive" />
              : <ToggleLeft size={22} className="text-gray-400" />}
          </button>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-walmart-navy truncate">{group.group_name}</div>
            <div className="text-[11px] text-gray-500">
              {group.subreddits.length} subreddit{group.subreddits.length !== 1 ? 's' : ''} · {group.email_dl.length} recipient{group.email_dl.length !== 1 ? 's' : ''}
              {group.slack_channel ? ` · ${group.slack_channel}` : ''}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] px-2 py-0.5 rounded-pill bg-walmart-navy/10 text-walmart-navy font-semibold">
            {group.priority_filter.join(' + ')}
          </span>
          <button onClick={onTest} className="p-1.5 rounded-lg hover:bg-walmart-blue/10 text-walmart-blue" title="Send test">
            <TestTube size={14} />
          </button>
          <button onClick={onEdit} className="p-1.5 rounded-lg hover:bg-walmart-navy/10 text-walmart-navy" title="Edit">
            {isEditing ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          <button onClick={onDelete} className="p-1.5 rounded-lg hover:bg-sentiment-negative/10 text-sentiment-negative" title="Delete">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Subreddits preview */}
      {!isEditing && (
        <div className="px-5 pb-3 flex gap-1.5 flex-wrap">
          {group.subreddits.slice(0, 8).map(s => (
            <span key={s} className="text-[10px] px-2 py-0.5 rounded-pill bg-walmart-blue/10 text-walmart-blue">r/{s}</span>
          ))}
          {group.subreddits.length > 8 && <span className="text-[10px] text-gray-500">+{group.subreddits.length - 8} more</span>}
        </div>
      )}

      {/* Edit form */}
      {isEditing && (
        <div className="border-t border-walmart-navy/10 px-5 py-4 space-y-4">
          {/* Group name */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1">Group Name</label>
            <input
              value={form.group_name}
              onChange={e => setForm(f => ({ ...f, group_name: e.target.value }))}
              className="w-full text-sm border border-walmart-navy/15 rounded-xl px-3 py-2 focus:ring-2 focus:ring-walmart-blue"
            />
          </div>

          {/* Subreddits */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1">Subreddits</label>
            <div className="flex gap-1.5 flex-wrap mb-2">
              {form.subreddits.map(s => (
                <span key={s} className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-pill bg-walmart-blue/10 text-walmart-blue">
                  r/{s}
                  <button onClick={() => setForm(f => ({ ...f, subreddits: f.subreddits.filter(x => x !== s) }))} className="text-walmart-blue/60 hover:text-sentiment-negative">×</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <select
                value={newSub}
                onChange={e => setNewSub(e.target.value)}
                className="flex-1 text-xs border border-walmart-navy/15 rounded-xl px-3 py-1.5"
              >
                <option value="">Select subreddit...</option>
                {subreddits.filter(s => !form.subreddits.includes(s.subreddit)).map(s => (
                  <option key={s.subreddit} value={s.subreddit}>r/{s.subreddit} ({s.group})</option>
                ))}
              </select>
              <button
                onClick={() => { if (newSub) { setForm(f => ({ ...f, subreddits: [...f.subreddits, newSub] })); setNewSub(''); } }}
                className="px-3 py-1.5 text-xs bg-walmart-blue text-white rounded-xl font-semibold hover:bg-walmart-blue/90"
              >Add</button>
            </div>
          </div>

          {/* Email DL */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1">Email Distribution List</label>
            <div className="flex gap-1.5 flex-wrap mb-2">
              {form.email_dl.map(e => (
                <span key={e} className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-pill bg-walmart-navy/10 text-walmart-navy">
                  {e}
                  <button onClick={() => setForm(f => ({ ...f, email_dl: f.email_dl.filter(x => x !== e) }))} className="text-walmart-navy/60 hover:text-sentiment-negative">×</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                value={newEmail}
                onChange={e => setNewEmail(e.target.value)}
                placeholder="email@walmart.com"
                className="flex-1 text-xs border border-walmart-navy/15 rounded-xl px-3 py-1.5"
              />
              <button
                onClick={() => { if (newEmail.includes('@')) { setForm(f => ({ ...f, email_dl: [...f.email_dl, newEmail] })); setNewEmail(''); } }}
                className="px-3 py-1.5 text-xs bg-walmart-blue text-white rounded-xl font-semibold hover:bg-walmart-blue/90"
              >Add</button>
            </div>
          </div>

          {/* Slack channel */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1">Slack Channel (optional)</label>
            <input
              value={form.slack_channel}
              onChange={e => setForm(f => ({ ...f, slack_channel: e.target.value }))}
              placeholder="#channel-name"
              className="w-full text-xs border border-walmart-navy/15 rounded-xl px-3 py-2"
            />
          </div>

          {/* Priority filter */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1">Trigger on Priority</label>
            <div className="flex gap-3">
              {['P1', 'P2'].map(p => (
                <label key={p} className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.priority_filter.includes(p)}
                    onChange={(e) => {
                      setForm(f => ({
                        ...f,
                        priority_filter: e.target.checked
                          ? [...f.priority_filter, p]
                          : f.priority_filter.filter(x => x !== p),
                      }));
                    }}
                    className="rounded"
                  />
                  <span className="font-semibold text-walmart-navy">{p}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 rounded-pill bg-walmart-blue text-white text-sm font-semibold hover:bg-walmart-blue/90 disabled:opacity-60"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : 'Save Changes'}
            </button>
            <button onClick={onEdit} className="px-4 py-2 rounded-pill border border-walmart-navy/20 text-walmart-navy text-sm font-semibold">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function AddGroupModal({
  subreddits, onClose, onCreated,
}: {
  subreddits: Array<{ subreddit: string; group: string; macro_group: string }>;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [form, setForm] = useState({
    group_name: '',
    subreddits: [] as string[],
    email_dl: [] as string[],
    slack_channel: '',
    priority_filter: ['P1', 'P2'],
  });
  const [newEmail, setNewEmail] = useState('');
  const [newSub, setNewSub] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleCreate = async () => {
    if (!form.group_name.trim()) { setError('Group name required'); return; }
    if (form.subreddits.length === 0) { setError('Add at least one subreddit'); return; }
    if (form.email_dl.length === 0 && !form.slack_channel) { setError('Add at least one email or Slack channel'); return; }
    setSaving(true);
    try {
      await api.createNotificationGroup(form);
      await onCreated();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  // Group subreddits by their group for easier selection
  const subsByGroup = subreddits.reduce<Record<string, typeof subreddits>>((acc, s) => {
    (acc[s.group] ??= []).push(s);
    return acc;
  }, {});

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-walmart-navy/40 backdrop-blur-sm" onClick={onClose}>
      <div onClick={e => e.stopPropagation()} className="bg-surface rounded-2xl shadow-card-hover w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-walmart-navy/10">
          <h2 className="text-base font-bold text-walmart-navy">Add Notification Group</h2>
          <p className="text-xs text-gray-500 mt-1">Configure which subreddits trigger notifications and who receives them.</p>
        </div>
        <div className="p-6 space-y-4">
          {/* Group name */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1">Group Name *</label>
            <input
              value={form.group_name}
              onChange={e => setForm(f => ({ ...f, group_name: e.target.value }))}
              placeholder="e.g. W+ Membership, Spark Delivery..."
              className="w-full text-sm border border-walmart-navy/15 rounded-xl px-3 py-2 focus:ring-2 focus:ring-walmart-blue"
            />
          </div>

          {/* Quick-add by reddit group */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1">Subreddits *</label>
            <div className="flex gap-1.5 flex-wrap mb-2">
              {Object.keys(subsByGroup).map(grp => (
                <button
                  key={grp}
                  type="button"
                  onClick={() => {
                    const subs = subsByGroup[grp].map(s => s.subreddit);
                    setForm(f => ({ ...f, subreddits: [...new Set([...f.subreddits, ...subs])] }));
                  }}
                  className="text-[10px] px-2 py-0.5 rounded-pill border border-walmart-navy/15 hover:bg-walmart-blue/10 text-walmart-navy"
                >
                  + {grp}
                </button>
              ))}
            </div>
            <div className="flex gap-1.5 flex-wrap mb-2">
              {form.subreddits.map(s => (
                <span key={s} className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-pill bg-walmart-blue/10 text-walmart-blue">
                  r/{s}
                  <button onClick={() => setForm(f => ({ ...f, subreddits: f.subreddits.filter(x => x !== s) }))} className="hover:text-sentiment-negative">×</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <select value={newSub} onChange={e => setNewSub(e.target.value)} className="flex-1 text-xs border border-walmart-navy/15 rounded-xl px-3 py-1.5">
                <option value="">Select subreddit...</option>
                {subreddits.filter(s => !form.subreddits.includes(s.subreddit)).map(s => (
                  <option key={s.subreddit} value={s.subreddit}>r/{s.subreddit}</option>
                ))}
              </select>
              <button
                onClick={() => { if (newSub) { setForm(f => ({ ...f, subreddits: [...f.subreddits, newSub] })); setNewSub(''); } }}
                className="px-3 py-1.5 text-xs bg-walmart-blue text-white rounded-xl font-semibold"
              >Add</button>
            </div>
          </div>

          {/* Email DL */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1">Email Distribution List *</label>
            <div className="flex gap-1.5 flex-wrap mb-2">
              {form.email_dl.map(e => (
                <span key={e} className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-pill bg-walmart-navy/10 text-walmart-navy">
                  {e}
                  <button onClick={() => setForm(f => ({ ...f, email_dl: f.email_dl.filter(x => x !== e) }))} className="hover:text-sentiment-negative">×</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="dl-name@walmart.com" className="flex-1 text-xs border border-walmart-navy/15 rounded-xl px-3 py-1.5" />
              <button
                onClick={() => { if (newEmail.includes('@')) { setForm(f => ({ ...f, email_dl: [...f.email_dl, newEmail] })); setNewEmail(''); } }}
                className="px-3 py-1.5 text-xs bg-walmart-blue text-white rounded-xl font-semibold"
              >Add</button>
            </div>
          </div>

          {/* Slack */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1">Slack Channel (optional)</label>
            <input value={form.slack_channel} onChange={e => setForm(f => ({ ...f, slack_channel: e.target.value }))} placeholder="#walmart-alerts" className="w-full text-xs border border-walmart-navy/15 rounded-xl px-3 py-2" />
          </div>

          {/* Priority */}
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-1">Trigger on Priority</label>
            <div className="flex gap-3">
              {['P1', 'P2'].map(p => (
                <label key={p} className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.priority_filter.includes(p)}
                    onChange={e => setForm(f => ({ ...f, priority_filter: e.target.checked ? [...f.priority_filter, p] : f.priority_filter.filter(x => x !== p) }))}
                    className="rounded"
                  />
                  <span className="font-semibold text-walmart-navy">{p}</span>
                </label>
              ))}
            </div>
          </div>

          {error && (
            <div className="text-xs text-sentiment-negative bg-sentiment-negative/5 border border-sentiment-negative/20 rounded-xl px-3 py-2">{error}</div>
          )}

          <div className="flex gap-3 pt-2">
            <button
              onClick={handleCreate}
              disabled={saving}
              className="flex-1 px-4 py-2.5 rounded-pill bg-walmart-blue text-white text-sm font-semibold hover:bg-walmart-blue/90 disabled:opacity-60 flex items-center justify-center gap-2"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Create Group
            </button>
            <button onClick={onClose} className="px-4 py-2.5 rounded-pill border border-walmart-navy/20 text-walmart-navy text-sm font-semibold">
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
