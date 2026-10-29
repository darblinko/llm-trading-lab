export type Point = { time: number; value?: number; source?: string };
export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
export type SessionWindow = { date: string; open: number; close: number; calendar_verified: boolean; has_data?: boolean; has_candles?: boolean };
export type Catalog = { sessions: SessionWindow[]; instances: string[]; instance: string; sync_status: string; today: string };
export type ScenarioEvent = { time: number; status: string; decision?: string; reason?: string; source: string };
export type Scenario = {
  id: string; date: string; instance: string; label: string; direction: string; setup_type: string;
  confidence: string; zone: { low?: number; high?: number }; target: number | null; start: number; end: number;
  origin: string; source: string; status: string; events: ScenarioEvent[]; trigger_conditions: string[];
  invalidation_conditions: string[]; price_invalidations: { operator: string; price: number; condition: string }[];
  decisions: string[]; fill_ids: string[]; warnings: string[];
  outcome: { label: string; detail: string; target_time?: number; price_change?: number };
};
export type Agent = {
  name: string; model: string; decision: string; reasoning: string; case_for: string;
  case_against: string; verdict: string; wait_for: string | null; key_factors: string[];
  raw: string; source: string; time: number;
};
export type Decision = {
  id: string; label: string; time: number; scenario_id: string | null; agents: Record<string, Agent>;
  consensus: string; source: string; event_source?: string; link_status: string; recorded_reasoning?: string;
};
export type Fill = {
  id: string; order_id: string; symbol: string; side: string; qty: number; price: number;
  time: number; time_basis: string; reason: string; source: string; scenario_id: string | null;
  decision_id: string | null; pnl: number | null; warnings: string[]; direction: string;
};
export type Session = SessionWindow & {
  instance: string; symbol: string; candles: Candle[]; prices: Point[]; price_source: string;
  indicators: Record<string, Point[]>; scenarios: Scenario[]; decisions: Decision[]; fills: Fill[];
  positions: { symbol: string; qty: number; average_price: number | null; scenario_ids: string[] }[];
  warnings: string[]; thesis: string; thesis_source: string; last_updated: number | null;
  stats: { last: number | null; change: number | null; entries: number; exits: number; realized_pnl: number; pnl_complete: boolean; observations: number };
  indicator_basis: string;
};
export type Indicator = 'none' | 'rsi' | 'stochrsi' | 'macd_hist' | 'rvol' | 'cvd_21';

export const indicators: { value: Indicator; label: string }[] = [
  { value: 'none', label: 'Indicators hidden' }, { value: 'rsi', label: 'RSI' },
  { value: 'stochrsi', label: 'Stochastic RSI' }, { value: 'macd_hist', label: 'MACD histogram' },
  { value: 'rvol', label: 'Relative volume' }, { value: 'cvd_21', label: 'Cumulative volume delta' },
];

export const timeLabel = (time?: number | null) => time == null ? '—' : new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false,
}).format(new Date(time * 1000));
export const dayLabel = (day: string) => new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric',
}).format(new Date(`${day}T12:00:00Z`));
export const money = (value: number | null | undefined) => value == null ? '—' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 2,
}).format(value);
export const verdictLabel = (decision: string) => ({ enter_now: 'Enter', pass: 'Pass', wait: 'Wait' }[decision] || 'Unavailable');
