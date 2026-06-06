import { useEffect, useRef, useState, useCallback } from 'react';
import type { Alert } from './api';

/**
 * WebSocket hook for real-time alerts.
 */
export function useAlertSocket() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/alerts`);

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'alert') {
        setAlerts((prev) => [msg.data, ...prev].slice(0, 50));
      }
    };

    ws.onclose = () => {
      // Auto-reconnect after 5s
      setTimeout(connect, 5000);
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  return alerts;
}
