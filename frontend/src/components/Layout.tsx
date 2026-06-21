import { Outlet, Link, useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { BarChart3, Bell, Search, CheckSquare, Activity, LogIn, LogOut, Layers, Lightbulb } from 'lucide-react';
import SparkIcon from './SparkIcon';
import { api } from '../api';

const navItems = [
  { path: '/', label: 'Brand Health', icon: BarChart3 },
  { path: '/lifecycle', label: 'Lifecycle', icon: Layers },
  { path: '/insights', label: 'Insights', icon: Lightbulb },
  { path: '/review', label: 'Review', icon: CheckSquare },
  { path: '/alerts', label: 'Alerts', icon: Bell },
  { path: '/posts', label: 'Posts', icon: Search },
  { path: '/pipeline', label: 'Pipeline', icon: Activity },
];

interface AuthStatus {
  enabled: boolean;
  dry_run: boolean;
  logged_in: boolean;
  username: string;
  client_configured: boolean;
}

function RedditAuthPill() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    api.authStatus().then(setStatus).catch(() => setStatus(null));
  };
  useEffect(() => { refresh(); }, []);

  const handleLogin = async () => {
    setBusy(true);
    try {
      const res = await api.authLogin();
      if (res.dry_run) {
        alert('Reddit OAuth is in dry-run mode. Replies are logged locally; no live login needed. Toggle reddit_oauth.dry_run in pipeline_config.yaml and set REDDIT_OAUTH_CLIENT_ID/SECRET to enable.');
      } else if (res.authorize_url) {
        window.location.href = res.authorize_url;
      } else if (res.error) {
        alert(`Reddit login unavailable: ${res.error}`);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleLogout = async () => {
    setBusy(true);
    try {
      await api.authLogout();
      refresh();
    } finally {
      setBusy(false);
    }
  };

  if (!status) return null;

  if (status.dry_run) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-pill bg-walmart-spark/15 border border-walmart-spark/40 text-xs font-semibold text-walmart-navy">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-walmart-spark-dark" />
        Reddit · Dry-run
      </div>
    );
  }

  if (status.logged_in) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-pill bg-walmart-blue/10 border border-walmart-blue/30 text-xs font-semibold text-walmart-navy">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-sentiment-positive" />
          u/{status.username || 'reddit'}
        </div>
        <button
          onClick={handleLogout}
          disabled={busy}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-pill border border-walmart-navy/20 text-xs font-semibold text-walmart-navy hover:bg-walmart-navy/5 disabled:opacity-50"
        >
          <LogOut size={12} />
          Logout
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={handleLogin}
      disabled={busy || !status.client_configured}
      title={!status.client_configured ? 'Set REDDIT_OAUTH_CLIENT_ID/CLIENT_SECRET to enable login' : 'Log in to Reddit to post replies'}
      className="flex items-center gap-2 px-3 py-1.5 rounded-pill bg-walmart-blue text-white text-xs font-semibold hover:bg-walmart-blue-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
    >
      <LogIn size={12} />
      {status.client_configured ? 'Log in to Reddit' : 'Reddit login (not configured)'}
    </button>
  );
}

export default function Layout() {
  const location = useLocation();
  const currentLabel = navItems.find((n) => n.path === location.pathname)?.label ?? 'Dashboard';

  return (
    <div className="min-h-screen flex bg-bg-base">
      {/* Sidebar */}
      <nav className="w-60 bg-walmart-navy text-white flex flex-col shrink-0">
        {/* Brand block */}
        <div className="px-5 pt-6 pb-5 border-b border-white/10">
          <div className="flex items-center gap-3">
            <SparkIcon size={32} color="#FFC220" />
            <div>
              <h1 className="text-base font-bold leading-tight tracking-tight">
                Retail Sentiment
              </h1>
              <p className="text-[11px] uppercase tracking-wider text-walmart-spark/90 font-semibold">
                Intelligence
              </p>
            </div>
          </div>
        </div>

        {/* Nav links */}
        <div className="flex-1 px-3 py-4 flex flex-col gap-1">
          {navItems.map(({ path, label, icon: Icon }) => {
            const active = location.pathname === path;
            return (
              <Link
                key={path}
                to={path}
                className={`relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  active
                    ? 'bg-white/10 text-white font-semibold'
                    : 'text-white/70 hover:text-white hover:bg-white/5'
                }`}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 rounded-r bg-walmart-spark" />
                )}
                <Icon size={18} />
                {label}
              </Link>
            );
          })}
        </div>

        {/* Footer disclaimer */}
        <div className="px-5 py-4 border-t border-white/10">
          <p className="text-[10px] leading-snug text-white/50">
            Internal analytics demo. Not affiliated with Walmart Inc. branding.
          </p>
        </div>
      </nav>

      {/* Main Content */}
      <main className="flex-1 overflow-auto">
        {/* Top bar */}
        <header className="bg-surface border-b border-walmart-navy/10 px-8 py-4 flex items-center justify-between sticky top-0 z-10">
          <h2 className="text-lg font-semibold text-walmart-navy">{currentLabel}</h2>
          {/* Reserved for Reddit login pill (Wave 2 Phase 3) */}
          <div id="topbar-actions" className="flex items-center gap-3">
            <RedditAuthPill />
          </div>
        </header>

        <div className="p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
