import { useEffect, useState } from 'react';
import { api, Alert } from '../api';
import { useAlertSocket } from '../useAlertSocket';
import Card from '../components/Card';

const SEVERITY_STYLES: Record<string, { border: string; bg: string; pill: string }> = {
  critical: { border: 'border-l-sentiment-negative', bg: 'bg-sentiment-negative/5', pill: 'bg-sentiment-negative/15 text-sentiment-negative' },
  high:     { border: 'border-l-walmart-spark-dark', bg: 'bg-walmart-spark/10', pill: 'bg-walmart-spark/30 text-walmart-navy' },
  medium:   { border: 'border-l-walmart-spark', bg: 'bg-walmart-spark/5', pill: 'bg-walmart-spark/20 text-walmart-navy' },
  low:      { border: 'border-l-walmart-blue', bg: 'bg-walmart-blue/5', pill: 'bg-walmart-blue/15 text-walmart-blue' },
};

export default function AlertFeed() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const realtimeAlerts = useAlertSocket();

  useEffect(() => {
    api.getAlerts().then(d => setAlerts(d.alerts)).catch(console.error).finally(() => setLoading(false));
  }, []);

  const allAlerts = [...realtimeAlerts, ...alerts];

  if (loading) return <div className="text-gray-500">Loading alerts...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-walmart-navy">Alert Feed</h2>
        <p className="text-xs text-gray-500 mt-1">Severity-graded signals from the alerting engine and live websocket.</p>
      </div>

      {allAlerts.length === 0 ? (
        <Card className="text-center py-12 text-gray-500">
          <p className="text-lg font-semibold text-walmart-navy">No alerts</p>
          <p className="text-sm">System is running normally.</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {allAlerts.map(alert => {
            const style = SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.medium;
            return (
              <div key={alert.id} className={`bg-surface shadow-card border border-walmart-navy/10 border-l-4 ${style.border} rounded-r-2xl p-4`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[11px] uppercase font-bold tracking-wider text-gray-500">{alert.type.replace('_', ' ')}</span>
                      <span className={`px-2 py-0.5 rounded-pill text-[11px] font-semibold ${style.pill}`}>{alert.severity}</span>
                    </div>
                    <p className="text-sm font-medium text-walmart-navy mt-1">{alert.message}</p>
                  </div>
                  <span className="text-xs text-gray-400 whitespace-nowrap">{alert.time_window}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
