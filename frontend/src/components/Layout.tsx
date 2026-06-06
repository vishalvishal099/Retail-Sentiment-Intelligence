import { Outlet, Link, useLocation } from 'react-router-dom';
import { BarChart3, Shield, Bell, Search, CheckSquare } from 'lucide-react';

const navItems = [
  { path: '/', label: 'Brand Health', icon: BarChart3 },
  { path: '/review', label: 'Review', icon: CheckSquare },
  { path: '/alerts', label: 'Alerts', icon: Bell },
  { path: '/posts', label: 'Posts', icon: Search },
];

export default function Layout() {
  const location = useLocation();

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <nav className="w-56 bg-white border-r border-gray-200 p-4 flex flex-col gap-1">
        <div className="mb-6">
          <h1 className="text-lg font-bold text-brand-700">RSI Dashboard</h1>
          <p className="text-xs text-gray-500">Retail Sentiment Intelligence</p>
        </div>
        {navItems.map(({ path, label, icon: Icon }) => (
          <Link
            key={path}
            to={path}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm ${
              location.pathname === path
                ? 'bg-brand-50 text-brand-700 font-medium'
                : 'text-gray-600 hover:bg-gray-50'
            }`}
          >
            <Icon size={18} />
            {label}
          </Link>
        ))}
      </nav>

      {/* Main Content */}
      <main className="flex-1 p-6 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
