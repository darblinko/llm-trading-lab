import { useEffect, useRef, useState } from 'react';
import type { Scenario, Session } from './types';
import { dayLabel, timeLabel } from './types';

export default function ScenarioPicker({ sessions, selected, day, onSelect }: {
  sessions: Session[]; selected?: Scenario; day: string; onSelect: (day: string, id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const outside = (event: MouseEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', outside);
    return () => document.removeEventListener('mousedown', outside);
  }, []);
  useEffect(() => { if (open) input.current?.focus(); }, [open]);
  const choose = (date: string, id: string) => { onSelect(date, id); setOpen(false); setSearch(''); };
  const matches = sessions.map(session => ({ ...session, scenarios: session.scenarios.filter(s =>
    `${s.label} ${s.direction} ${s.date} ${s.setup_type}`.toLowerCase().includes(search.toLowerCase())) }));
  return <div className="field scenario-picker" ref={ref} onKeyDown={e => {
    if (e.key === 'Escape') { setOpen(false); ref.current?.querySelector('button')?.focus(); }
  }}><span>Scenario</span><button className="picker-button" aria-expanded={open} aria-label="Choose scenario" onClick={() => setOpen(!open)}>
    <span>{selected ? selected.label : 'All scenarios for selected day'}</span><span className="chevron">⌄</span>
  </button>
    {open && <div className="picker-menu"><input ref={input} aria-label="Search scenarios" placeholder="Search setups across all six sessions..." value={search} onChange={e => setSearch(e.target.value)} />
      <div className="picker-options"><button onClick={() => choose(day, '')} className={!selected ? 'active' : ''}>All scenarios for selected day</button>
        {matches.map(session => session.scenarios.length > 0 && <div key={session.date}><h4>{dayLabel(session.date)} <span>{session.scenarios.length} setups</span></h4>
          {session.scenarios.map(s => <button key={s.id} className={selected?.id === s.id ? 'active' : ''} onClick={() => choose(s.date, s.id)}><span className={`direction ${s.direction}`}>{s.direction.toUpperCase()}</span><span>{s.label}<small>{timeLabel(s.start)} ET · {s.confidence} · {s.status.replaceAll('_', ' ')}</small></span></button>)}
        </div>)}
        {!matches.some(s => s.scenarios.length) && <p className="muted">No matching setups.</p>}
      </div>
    </div>}
  </div>;
}
