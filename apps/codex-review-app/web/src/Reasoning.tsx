import { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Agent, Decision, Scenario, Session } from './types';
import { timeLabel } from './types';
import { Badge, Empty, Icon } from './ui';

function AgentCard({ name, agent }: { name: string; agent?: Agent }) {
  return <article className={`agent-card ${name}`}>
    <div className="agent-heading"><span className="agent-monogram">{name === 'opus' ? 'O' : 'A'}</span>
      <div><h3>{name === 'opus' ? 'Claude Opus' : 'OpenAI Astra'}</h3><span className="model-name">{agent?.model || 'No recorded response'}</span></div>
      {agent && <Badge value={agent.decision} />}
    </div>
    {!agent ? <p className="muted">This agent's response was not recorded for this evaluation.</p> : <>
      <div className="agent-summary"><ReactMarkdown>{agent.reasoning}</ReactMarkdown></div>
      {agent.case_for && <details><summary><span className="dot green" />Case for entry</summary><ReactMarkdown>{agent.case_for}</ReactMarkdown></details>}
      {agent.case_against && <details><summary><span className="dot red" />Case against entry</summary><ReactMarkdown>{agent.case_against}</ReactMarkdown></details>}
      {agent.verdict && <details><summary>Verdict</summary><ReactMarkdown>{agent.verdict}</ReactMarkdown></details>}
      {agent.wait_for && <p className="wait-for"><b>Waiting for</b> {agent.wait_for}</p>}
      {Array.isArray(agent.key_factors) && agent.key_factors.length > 0 && <details><summary>Key factors</summary><ul>{agent.key_factors.map((factor, i) => <li key={i}>{factor}</li>)}</ul></details>}
      <details className="raw"><summary>Original response & source</summary><p className="source">{agent.source} · {timeLabel(agent.time)} ET</p><pre>{agent.raw}</pre></details>
    </>}
  </article>;
}

type Props = {
  session: Session; scenario?: Scenario; decisions: Decision[]; decision?: Decision;
  expanded: boolean; onExpand: () => void; onClose: () => void; onDecision: (id: string) => void;
};

export default function Reasoning(props: Props) {
  const { session, scenario, decisions, decision, expanded, onExpand, onClose, onDecision } = props;
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (expanded) dialog.current?.showModal(); else dialog.current?.close();
  }, [expanded]);
  const contents = <>
    <header className="reasoning-heading"><div><span className="eyebrow">Decision journal</span><h2>Inside the setup</h2></div>
      <button className="icon-button" aria-label={expanded ? 'Close expanded reasoning' : 'Expand reasoning'} onClick={expanded ? onClose : onExpand}><Icon name={expanded ? 'close' : 'expand'} /></button>
    </header>
    <div className="reasoning-content">
      {scenario && <div className="reasoning-context"><span className={`direction ${scenario.direction}`}>{scenario.direction.toUpperCase()}</span><h3>{scenario.label}</h3><p>{timeLabel(scenario.start)}–{timeLabel(scenario.end)} ET · {scenario.confidence} confidence</p></div>}
      {decisions.length > 0 && <label className="field decision-select"><span>Evaluation</span><select value={decision?.id || ''} onChange={e => onDecision(e.target.value)} aria-label="Evaluation">
        {decisions.map(d => <option key={d.id} value={d.id}>{timeLabel(d.time)} · {d.label}</option>)}
      </select></label>}
      {decision ? <>
        <div className="consensus"><div><span className="eyebrow">Recorded consensus</span><span className="consensus-time">{timeLabel(decision.time)} ET</span></div><Badge value={decision.consensus} /></div>
        <div className="agent-grid"><AgentCard name="opus" agent={decision.agents.opus} /><AgentCard name="astra" agent={decision.agents.astra} /></div>
        {decision.recorded_reasoning && <div className="recorded-summary"><ReactMarkdown>{decision.recorded_reasoning}</ReactMarkdown></div>}
        <p className="source">Attribution: {decision.link_status}<br />{decision.event_source || decision.source}</p>
      </> : <Empty>{scenario ? 'No agent evaluation was recorded for this scenario. Its conditions and lifecycle are available below the chart.' : "Select a setup or fill to inspect both agents' recorded assessments."}</Empty>}
      {session.thesis && <details className="thesis"><summary>Session thesis & refreshes</summary><div className="markdown"><ReactMarkdown>{session.thesis}</ReactMarkdown></div><p className="source">{session.thesis_source}</p></details>}
    </div>
  </>;
  return <>
    <aside className="reasoning-panel" aria-label="Agent reasoning">{!expanded && contents}</aside>
    <dialog ref={dialog} className="reasoning-dialog" onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      {expanded && <div className="dialog-body">{contents}</div>}
    </dialog>
  </>;
}
