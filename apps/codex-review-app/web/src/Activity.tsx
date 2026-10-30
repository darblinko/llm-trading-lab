import { useState } from 'react';
import type { ReactNode } from 'react';
import type { Fill, Scenario, Session } from './types';
import { money, timeLabel } from './types';
import { Empty } from './ui';

type Props = {
  session: Session;
  selected?: Scenario;
  selectedFill?: Fill;
  onScenario: (id: string) => void;
  onFill: (fill: Fill) => void;
};

function SetupDetails({ scenario }: { scenario?: Scenario }) {
  if (!scenario) return <Empty>Select a scenario to see its conditions and recorded lifecycle.</Empty>;
  return (
    <div className="setup-details">
      <div>
        <h3>{scenario.label}</h3>
        <p className="outcome">{scenario.outcome.label}</p>
        <p className="muted">{scenario.outcome.detail}</p>
        <p className="source">{scenario.source}</p>
        {scenario.warnings.map(w => <p key={w} className="warning-text">{w}</p>)}
      </div>
      <div>
        <h4>Trigger conditions</h4>
        <ul>{scenario.trigger_conditions.map((c, i) => <li key={i}>{c}</li>)}</ul>
      </div>
      <div>
        <h4>Invalidation conditions</h4>
        <ul>{scenario.invalidation_conditions.map((c, i) => <li key={i}>{c}</li>)}</ul>
      </div>
      <div>
        <h4>Lifecycle</h4>
        {scenario.events.map((event, i) => (
          <p className="lifecycle" key={i}>
            <time>{timeLabel(event.time)}</time>
            <span>
              {(event.decision || event.status).replaceAll('_', ' ')}
              {event.reason && ` · ${event.reason}`}
            </span>
          </p>
        ))}
      </div>
    </div>
  );
}

type SetupsProps = { scenarios: Scenario[]; selected?: Scenario; onScenario: (id: string) => void };

function SetupsTable({ scenarios, selected, onScenario }: SetupsProps) {
  if (!scenarios.length) return <Empty>No scenarios recorded for this session.</Empty>;
  return (
    <table>
      <thead>
        <tr>
          <th>Created · ET</th><th>Setup</th><th>Zone</th><th>Target</th><th>Recorded state</th><th>Evaluations</th>
        </tr>
      </thead>
      <tbody>
        {scenarios.map(s => (
          <tr key={s.id} className={selected?.id === s.id ? 'selected' : ''}>
            <td>{timeLabel(s.start)}</td>
            <td>
              <button className="setup-link" onClick={() => onScenario(s.id)}>
                <span className={`direction ${s.direction}`}>{s.direction.toUpperCase()}</span>
                {s.label}
              </button>
            </td>
            <td className="numeric">{s.zone.low?.toFixed(2) ?? '—'}–{s.zone.high?.toFixed(2) ?? '—'}</td>
            <td className="numeric">{s.target?.toFixed(2) ?? '—'}</td>
            <td><span className={`state ${s.status}`}>{s.status.replaceAll('_', ' ')}</span></td>
            <td>{s.decisions.length}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FillDetail({ fill }: { fill: Fill }) {
  return (
    <div className="fill-detail">
      <b>{fill.symbol} · {fill.side.toUpperCase()} {fill.qty} @ {money(fill.price)}</b>
      <span>{timeLabel(fill.time)} ET · {fill.time_basis}</span>
      <span>{fill.reason}</span>
      <span className="source">{fill.source}</span>
      {fill.warnings.map(w => <span className="warning-text" key={w}>{w}</span>)}
    </div>
  );
}

type ExecutionsProps = { fills: Fill[]; selectedFill?: Fill; onFill: (fill: Fill) => void };

function ExecutionsTable({ fills, selectedFill, onFill }: ExecutionsProps) {
  return (
    <table>
      <thead>
        <tr>
          <th>Time · ET</th><th>Side</th><th>Contract</th><th>Qty</th><th>Option fill</th><th>Realized · pre-fees</th>
        </tr>
      </thead>
      <tbody>
        {fills.map(f => (
          <tr key={f.id} className={selectedFill?.id === f.id ? 'selected' : ''}>
            <td>{timeLabel(f.time)}</td>
            <td>
              <button className={`trade-link ${f.side}`} onClick={() => onFill(f)}>
                {f.side === 'buy' ? '↗ Entry' : '↘ Exit'}
              </button>
            </td>
            <td>{f.symbol}</td>
            <td>{f.qty}</td>
            <td>{money(f.price)}</td>
            <td className={(f.pnl || 0) >= 0 ? 'positive' : 'negative'}>{money(f.pnl)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OpenPositions({ session }: { session: Session }) {
  if (!session.positions.length) return null;
  const text = session.positions.map(p => `${p.qty} × ${p.symbol} @ ${money(p.average_price)}`).join(' · ');
  return <p className="open-positions">Open in the recorded ledger: {text}</p>;
}

function TabButton({ id, tab, setTab, children }: {
  id: string; tab: string; setTab: (id: string) => void; children: ReactNode;
}) {
  return <button className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{children}</button>;
}

export default function Activity({ session, selected, selectedFill, onScenario, onFill }: Props) {
  const [tab, setTab] = useState('setups');
  const fills = session.fills.filter(f => !selected || f.scenario_id === selected.id);
  return (
    <section className="activity-panel" aria-label="Session activity">
      <header className="activity-tabs">
        <TabButton id="setups" tab={tab} setTab={setTab}>Setups <span>{session.scenarios.length}</span></TabButton>
        <TabButton id="trades" tab={tab} setTab={setTab}>Executions <span>{fills.length}</span></TabButton>
        <TabButton id="details" tab={tab} setTab={setTab}>Setup details</TabButton>
        <span className="activity-note">{selected ? 'Selected revision' : 'Entire session'}</span>
      </header>
      <div className="activity-content">
        {tab === 'setups' && <SetupsTable scenarios={session.scenarios} selected={selected} onScenario={onScenario} />}
        {tab === 'trades' && (
          <>
            {selectedFill && <FillDetail fill={selectedFill} />}
            {fills.length
              ? <ExecutionsTable fills={fills} selectedFill={selectedFill} onFill={onFill} />
              : <Empty>No confirmed fills {selected ? 'for this setup' : 'in this session'}.</Empty>}
            <OpenPositions session={session} />
          </>
        )}
        {tab === 'details' && <SetupDetails scenario={selected} />}
      </div>
    </section>
  );
}
