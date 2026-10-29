import { useState } from 'react';
import type { Fill, Scenario, Session } from './types';
import { money, timeLabel } from './types';
import { Empty } from './ui';

type Props = { session: Session; selected?: Scenario; selectedFill?: Fill; onScenario: (id: string) => void; onFill: (fill: Fill) => void };

function SetupDetails({ scenario }: { scenario?: Scenario }) {
  if (!scenario) return <Empty>Select a scenario to see its conditions and recorded lifecycle.</Empty>;
  return <div className="setup-details"><div><h3>{scenario.label}</h3><p className="outcome">{scenario.outcome.label}</p><p className="muted">{scenario.outcome.detail}</p>
    <p className="source">{scenario.source}</p>{scenario.warnings.map(w => <p key={w} className="warning-text">{w}</p>)}</div>
    <div><h4>Trigger conditions</h4><ul>{scenario.trigger_conditions.map((c, i) => <li key={i}>{c}</li>)}</ul></div>
    <div><h4>Invalidation conditions</h4><ul>{scenario.invalidation_conditions.map((c, i) => <li key={i}>{c}</li>)}</ul></div>
    <div><h4>Lifecycle</h4>{scenario.events.map((event, i) => <p className="lifecycle" key={i}><time>{timeLabel(event.time)}</time><span>{(event.decision || event.status).replaceAll('_', ' ')}{event.reason && ` · ${event.reason}`}</span></p>)}</div>
  </div>;
}

export default function Activity({ session, selected, selectedFill, onScenario, onFill }: Props) {
  const [tab, setTab] = useState('setups');
  const fills = session.fills.filter(f => !selected || f.scenario_id === selected.id);
  return <section className="activity-panel" aria-label="Session activity">
    <header className="activity-tabs"><button className={tab === 'setups' ? 'active' : ''} onClick={() => setTab('setups')}>Setups <span>{session.scenarios.length}</span></button>
      <button className={tab === 'trades' ? 'active' : ''} onClick={() => setTab('trades')}>Executions <span>{fills.length}</span></button>
      <button className={tab === 'details' ? 'active' : ''} onClick={() => setTab('details')}>Setup details</button>
      <span className="activity-note">{selected ? 'Selected revision' : 'Entire session'}</span></header>
    <div className="activity-content">
      {tab === 'setups' && (session.scenarios.length ? <table><thead><tr><th>Created · ET</th><th>Setup</th><th>Zone</th><th>Target</th><th>Recorded state</th><th>Evaluations</th></tr></thead><tbody>{session.scenarios.map(s => <tr key={s.id} className={selected?.id === s.id ? 'selected' : ''}>
        <td>{timeLabel(s.start)}</td><td><button className="setup-link" onClick={() => onScenario(s.id)}><span className={`direction ${s.direction}`}>{s.direction.toUpperCase()}</span>{s.label}</button></td>
        <td className="numeric">{s.zone.low?.toFixed(2) ?? '—'}–{s.zone.high?.toFixed(2) ?? '—'}</td><td className="numeric">{s.target?.toFixed(2) ?? '—'}</td><td><span className={`state ${s.status}`}>{s.status.replaceAll('_', ' ')}</span></td><td>{s.decisions.length}</td>
      </tr>)}</tbody></table> : <Empty>No scenarios recorded for this session.</Empty>)}
      {tab === 'trades' && <>
        {selectedFill && <div className="fill-detail"><b>{selectedFill.symbol} · {selectedFill.side.toUpperCase()} {selectedFill.qty} @ {money(selectedFill.price)}</b><span>{timeLabel(selectedFill.time)} ET · {selectedFill.time_basis}</span><span>{selectedFill.reason}</span><span className="source">{selectedFill.source}</span>{selectedFill.warnings.map(w => <span className="warning-text" key={w}>{w}</span>)}</div>}
        {fills.length ? <table><thead><tr><th>Time · ET</th><th>Side</th><th>Contract</th><th>Qty</th><th>Option fill</th><th>Realized · pre-fees</th></tr></thead><tbody>{fills.map(f => <tr key={f.id} className={selectedFill?.id === f.id ? 'selected' : ''}><td>{timeLabel(f.time)}</td><td><button className={`trade-link ${f.side}`} onClick={() => onFill(f)}>{f.side === 'buy' ? '↗ Entry' : '↘ Exit'}</button></td><td>{f.symbol}</td><td>{f.qty}</td><td>{money(f.price)}</td><td className={(f.pnl || 0) >= 0 ? 'positive' : 'negative'}>{money(f.pnl)}</td></tr>)}</tbody></table> : <Empty>No confirmed fills {selected ? 'for this setup' : 'in this session'}.</Empty>}
        {session.positions.length > 0 && <p className="open-positions">Open in the recorded ledger: {session.positions.map(p => `${p.qty} × ${p.symbol} @ ${money(p.average_price)}`).join(' · ')}</p>}
      </>}
      {tab === 'details' && <SetupDetails scenario={selected} />}
    </div>
  </section>;
}
