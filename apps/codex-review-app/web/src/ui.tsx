import type { ReactNode } from 'react';
import { verdictLabel } from './types';

const paths: Record<string, ReactNode> = {
  chart: <><path d="M3 3v18h18M7 14v3m0-9v3m5-4v10m5-13v11"/><path d="M5 11h4v3H5zm5-1h4v4h-4zm5-3h4v4h-4z"/></>,
  expand: <path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  arrow: <path d="m9 5 7 7-7 7" />,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1"/></>,
  panel: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></>,
  layers: <><path d="m12 3 10 5-10 5L2 8zm-10 9 10 5 10-5M2 16l10 5 10-5"/></>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v1"/></>,
};
export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.chart}</svg>;
}
export function Badge({ value }: { value: string }) {
  return <span className={`badge ${value}`}>{verdictLabel(value)}</span>;
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty"><Icon name="layers" size={22} /><p>{children}</p></div>;
}
