import { useEffect, useState } from 'react';
import { api, Alert } from '../api';
import { useAlertSocket } from '../useAlertSocket';

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'border-l-red-600 bg-red-50',
  high: 'border-l-orange-500 bg-orange-50',
  medium: 'border-l-yellow-500 bg-yellow-50',
  low: 'border-l-blue-400 bg-blue-50',
};

export default function AlertFeed() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const realtimeAlerts = useAlertSocket();

  useEffect(() => {
    api.getAlerts().then(d => setAlerts(d.alerts)).catch(console.error).finally(() => setLoading(false));
  }, []);

  // Merge realtime alerts
  const allAlerts = [...realtimeAlerts, ...alerts];

  if (loading) return <div className="text-gray-500">Loading alerts...</div>;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Alert Feed</h2>

      {allAlerts.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p className="text-lg">No alerts</p>
          <p className="text-sm">System is running normally.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {allAlerts.map(alert => (
            <div key={alert.id} className={`border-l-4 rounded-r-lg p-4 ${SEVERITY_COLORS[alert.severity] || SEVERITY_COLORS.medium}`}>
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs uppercase font-bold tracking-wide text-gray-500">{alert.type.replace('_', ' ')}</span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      alert.severity === 'critical' ? 'bg-red-200 text-red-900' :
                      alert.severity === 'high' ? 'bg-orange-200 text-orange-900' :
                      'bg-yellow-200 text-yellow-900'
                    }`}>{alert.severity}</span>
                  </div>
                  <p className="text-sm font-medium mt-1">{alert.title}</p>
                </div>
                <span className="text-xs text-gray-400 whitespace-nowrap">{alert.time_window}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
