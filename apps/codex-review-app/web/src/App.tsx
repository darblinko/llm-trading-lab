import { useEffect, useState } from 'react';
import Chart from './Chart';
import Reasoning from './Reasoning';
import ScenarioPicker from './ScenarioPicker';
import Activity from './Activity';
import { useSessions } from './useSessions';
import { dayLabel, indicators, money, timeLabel, type Fill, type Indicator } from './types';
import { Empty, Icon } from './ui';

export default function App() {
  const [instance, setInstance] = useState('claude');
  const { catalog, sessions, loading, error, refresh } = useSessions(instance);
  const [day, setDay] = useState('');
  const [scenarioId, setScenarioId] = useState('');
  const [decisionId, setDecisionId] = useState('');
  const [fillId, setFillId] = useState('');
  const [indicator, setIndicator] = useState<Indicator>('none');
  const [overlays, setOverlays] = useState<string[]>(['vwap']);
  const [reasoningVisible, setReasoningVisible] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [qualityOpen, setQualityOpen] = useState(false);
  const session = sessions.find(s => s.date === day) || sessions[0];
  const selected = session?.scenarios.find(s => s.id === scenarioId);
  const selectedFill = session?.fills.find(f => f.id === fillId);
  const decisions = session?.decisions.filter(d => !selected || d.scenario_id === selected.id) || [];
  const decision = decisions.find(d => d.id === decisionId) || decisions[0];
  useEffect(() => { if (session && day !== session.date) setDay(session.date); }, [session, day]);
  const chooseScenario = (nextDay: string, id: string) => { setDay(nextDay); setScenarioId(id); setDecisionId(''); setFillId(''); };
  const chooseFill = (fill: Fill) => {
    setFillId(fill.id); setScenarioId(fill.scenario_id || ''); setDecisionId(fill.decision_id || ''); setReasoningVisible(true);
  };
  const toggleOverlay = (name: string) => setOverlays(previous => previous.includes(name) ? previous.filter(x => x !== name) : [...previous, name]);

  return <div className="app-shell">
    <header className="app-header"><a href="/" className="brand"><span className="brand-mark"><Icon name="chart" size={24} /></span><div><h1>Codex <span>Review App</span></h1><p>SESSION RESEARCH</p></div></a>
      <div className="header-right"><span className="read-only"><span className="status-light" />REVIEW WORKSPACE</span><span className="header-divider" /><span className="session-window">6 trading sessions</span>
        <button className={`icon-button ${loading ? 'spinning' : ''}`} onClick={() => void refresh()} aria-label="Refresh data" disabled={loading}><Icon name="refresh" /></button></div>
    </header>
    <section className="toolbar" aria-label="Review controls"><label className="field day-picker"><span>Trading day</span><select aria-label="Trading day" value={session?.date || ''} onChange={e => chooseScenario(e.target.value, '')} disabled={!sessions.length}>
      {!sessions.length && <option>Loading sessions...</option>}{sessions.map(s => <option key={s.date} value={s.date}>{dayLabel(s.date)}{s.date === catalog?.today ? ' · Today' : ''}</option>)}
    </select></label>
      <ScenarioPicker sessions={sessions} selected={selected} day={session?.date || ''} onSelect={chooseScenario} />
      <label className="field indicator-picker"><span>Lower chart</span><select aria-label="Technical indicator" value={indicator} onChange={e => setIndicator(e.target.value as Indicator)}>{indicators.map(i => <option key={i.value} value={i.value}>{i.label}</option>)}</select></label>
      {catalog && catalog.instances.length > 1 && <label className="field instance-picker"><span>Trading instance</span><select value={instance} aria-label="Trading instance" onChange={e => { setInstance(e.target.value); chooseScenario('', ''); }}>{catalog.instances.map(i => <option value={i} key={i}>{i}</option>)}</select></label>}
      <div className="toolbar-divider" /><div className="overlay-toggles"><span>Price overlays</span><div>{[['vwap', 'VWAP'], ['ema_9', 'EMA 9'], ['ema_21', 'EMA 21']].map(([name, label]) => <button key={name} aria-pressed={overlays.includes(name)} className={overlays.includes(name) ? 'active' : ''} onClick={() => toggleOverlay(name)}>{label}</button>)}</div></div>
      <button className={`panel-toggle ${reasoningVisible ? 'active' : ''}`} aria-label="Toggle agent reasoning" aria-pressed={reasoningVisible} onClick={() => setReasoningVisible(!reasoningVisible)}><Icon name="panel" /><span>Reasoning</span></button>
    </section>
    {error && <div className="error-banner" role="alert">{error} <button onClick={() => void refresh()}>Retry</button></div>}
    {session ? <>
      <div className="session-summary"><span><b>{dayLabel(session.date)}</b> <span className="muted">/ {instance} instance</span></span><div><span>{session.scenarios.length} setups</span><span>{session.stats.entries} entries · {session.stats.exits} exits</span><span>Realized <b className={session.stats.realized_pnl >= 0 ? 'positive' : 'negative'}>{money(session.stats.realized_pnl)}{!session.stats.pnl_complete && '*'}</b> <small>pre-fees</small></span></div>
        <button className="quality-button" onClick={() => setQualityOpen(!qualityOpen)} aria-expanded={qualityOpen}><Icon name="info" size={13} />{session.warnings.length ? `${session.warnings.length} data notes` : 'Data sources'}</button></div>
      {qualityOpen && <div className="quality-notes"><p>{catalog?.sync_status}</p>{session.warnings.map(w => <p key={w}>{w}</p>)}<p>{session.indicator_basis}</p><p>Fill arrows use recorded detection times unless an execution timestamp exists. Realized profit or loss uses the recorded position's weighted average cost and excludes fees; * indicates incomplete entry history.</p><p>All timestamps are America/New_York. Each detail view identifies the source log record.</p></div>}
      <main className={`workspace ${reasoningVisible ? '' : 'wide'}`}><div className="chart-column"><Chart session={session} selected={selected} indicator={indicator} overlays={overlays} onIndicator={setIndicator} onFill={chooseFill} onScenario={id => chooseScenario(session.date, id)} />
        <Activity session={session} selected={selected} selectedFill={selectedFill} onScenario={id => chooseScenario(session.date, id)} onFill={chooseFill} />
      </div>{reasoningVisible && <Reasoning session={session} scenario={selected} decisions={decisions} decision={decision} expanded={expanded} onExpand={() => setExpanded(true)} onClose={() => setExpanded(false)} onDecision={setDecisionId} />}</main>
      <footer className="app-footer"><span><span className="status-light" />LOCAL RECORDS <span className="muted">· {session.stats.observations} observations</span></span><span>Last recorded {timeLabel(session.last_updated)} ET · Refreshes every 60s</span></footer>
    </> : loading ? <div className="loading-screen"><span className="loading-orbit" /><h2>Opening the session journal</h2><p>Reading local scenarios, fills, and agent assessments...</p></div> : <Empty>No recorded sessions found. Point the app at logs/claude/ticks with --ticks-dir.</Empty>}
  </div>;
}
