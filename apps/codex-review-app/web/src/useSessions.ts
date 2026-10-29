import { useCallback, useEffect, useRef, useState } from 'react';
import type { Catalog, Session } from './types';

async function get<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`Unable to load session data (${response.status}).`);
  return response.json() as Promise<T>;
}

export function useSessions(instance: string) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    controller.current?.abort();
    const next = new AbortController(); controller.current = next;
    setLoading(true);
    try {
      const data = await get<Catalog>(`/api/sessions?instance=${instance}`, next.signal);
      const days = await Promise.all(data.sessions.map(s => get<Session>(`/api/sessions/${s.date}?instance=${instance}`, next.signal)));
      if (!next.signal.aborted) { setCatalog(data); setSessions(days); setError(''); }
    } catch (err) {
      if (!next.signal.aborted) setError(err instanceof Error ? err.message : 'Unable to read local data.');
    } finally { if (!next.signal.aborted) setLoading(false); }
  }, [instance]);
  useEffect(() => {
    setSessions([]); setCatalog(null); void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 60000);
    return () => { clearInterval(timer); controller.current?.abort(); };
  }, [refresh]);
  return { catalog, sessions, loading, error, refresh };
}
