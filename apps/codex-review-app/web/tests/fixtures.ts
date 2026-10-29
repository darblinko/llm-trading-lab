import type { Agent, Catalog, Decision, Scenario, Session } from '../src/types';

export const days = ['2026-09-24', '2026-09-23', '2026-09-22', '2026-09-21', '2026-09-18', '2026-09-17'];
const time = (day: string, clock: string) => Date.parse(`${day}T${clock}:00-04:00`) / 1000;

function scenario(day: string, revision: number): Scenario {
  return {
    id: `${day}-setup-${revision}`, date: day, instance: 'claude', label: 'Support reclaim',
    direction: 'call', setup_type: 'mean_reversion', confidence: 'high',
    zone: { low: 99, high: 101 }, target: revision === 1 ? 104 : 110,
    start: time(day, revision === 1 ? '09:29' : '10:05'), end: time(day, revision === 1 ? '10:05' : '16:00'),
    origin: 'fixture', source: `claude/scenarios/scenarios_${day}.jsonl:${revision}`,
    status: revision === 1 ? 'triggered' : 'created',
    events: [{ time: time(day, revision === 1 ? '09:29' : '10:05'), status: 'created', source: 'fixture:1' }],
    trigger_conditions: ['rsi > 30'], invalidation_conditions: ['price < 98'],
    price_invalidations: [{ operator: '<', price: 98, condition: 'price < 98' }],
    decisions: [], fill_ids: [], warnings: [],
    outcome: { label: 'Target not touched', detail: 'Complete candles within the recorded lifetime.' },
  };
}

function agent(day: string, name: string): Agent {
  const decision = name === 'opus' ? 'enter_now' : 'wait';
  const reasoning = name === 'opus' ? 'Support holds with improving momentum.' : 'Wait for volume confirmation.';
  return {
    name, model: `${name}-fixture`, decision, reasoning,
    case_for: 'Support holds', case_against: 'Volume fades', verdict: '', wait_for: null,
    key_factors: [], raw: JSON.stringify({ decision, reasoning }),
    source: `claude/traces/trace_${day}.md:12`, time: time(day, '09:35'),
  };
}

function session(day: string, index: number): Session {
  const open = time(day, '09:30');
  const setups = [scenario(day, 1), scenario(day, 2)];
  const decisions: Decision[] = [
    {
      id: `${day}-decision-1`, label: 'Support reclaim', time: time(day, '09:35'),
      scenario_id: setups[0].id, agents: { opus: agent(day, 'opus'), astra: agent(day, 'astra') },
      consensus: 'wait', source: `claude/traces/trace_${day}.md:12`, link_status: 'recorded reasoning + time',
    },
    {
      id: `${day}-decision-2`, label: 'Support reclaim', time: time(day, '09:38'),
      scenario_id: setups[0].id, agents: { opus: agent(day, 'opus') },
      consensus: 'enter_now', source: `claude/traces/trace_${day}.md:25`, link_status: 'label + time',
    },
  ];
  setups[0].decisions = decisions.map(d => d.id);
  const candles = index === 1 ? [] : Array.from({ length: 130 }, (_, i) => ({
    time: open + i * 180, open: 100 + Math.sin(i / 9), close: 100 + Math.sin((i + 1) / 9),
    high: 102, low: 99, volume: 1000,
  }));
  const fills = index === 0 ? [{
    id: `${day}-entry`, order_id: 'buy-1', symbol: 'QQQ260924C00100000', side: 'buy',
    qty: 2, price: 1.2, time: time(day, '09:39'), time_basis: 'Recorded fill-detection time',
    reason: 'Entry confirmed', source: `claude/orders/orders_${day}.jsonl:3`,
    scenario_id: setups[0].id, decision_id: decisions[1].id, pnl: null, warnings: [], direction: 'call',
  }] : [];
  setups[0].fill_ids = fills.map(f => f.id);
  const points = candles.map(c => ({ time: c.time, value: c.close }));
  return {
    date: day, open, close: time(day, '16:00'), calendar_verified: true,
    instance: 'claude', symbol: 'QQQ', candles,
    prices: points.length ? points : [{ time: open, value: 100 }, { time: open + 360, value: 101 }],
    price_source: candles.length ? 'Browser fixture candles' : 'Recorded tick prices',
    indicators: Object.fromEntries(['rsi', 'stochrsi_k', 'stochrsi_d', 'macd_hist', 'rvol', 'cvd_21', 'vwap', 'ema_9', 'ema_21']
      .map(name => [name, points.map(p => ({ ...p, value: name === 'rsi' ? 50 : p.value }))])),
    scenarios: setups, decisions, fills,
    positions: fills.length ? [{ symbol: fills[0].symbol, qty: 2, average_price: 1.2, scenario_ids: [setups[0].id] }] : [],
    warnings: candles.length ? [] : ['Candles unavailable for this day. Showing recorded price observations.'],
    thesis: '# Recorded thesis\nSupport remains in focus.', thesis_source: `claude/daily_thesis/thesis_${day}.md`,
    last_updated: open + 387 * 60,
    stats: { last: 101, change: 1, entries: fills.length, exits: 0, realized_pnl: 0, pnl_complete: true, observations: 130 },
    indicator_basis: 'Logged observations at tick time; gaps are preserved.',
  };
}

export const sessions = days.map(session);
export const catalog: Catalog = {
  sessions: sessions.map(({ date, open, close, calendar_verified }) => ({ date, open, close, calendar_verified })),
  instances: ['claude'], instance: 'claude', sync_status: 'Browser fixtures', today: days[0],
};
