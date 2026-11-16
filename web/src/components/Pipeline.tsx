import { useState } from 'react';
import { AlertTriangle, ArrowRight, Check, ChevronDown, CircleDashed, CircleSlash, Circle, Loader2 } from 'lucide-react';
import type { Run, RunEvent } from '../types';
import { agents, debateRounds, phases, type Chip, type Derived, type PhaseKey, type StepState } from '../lib/run';
import { duration } from '../lib/format';
import AgentOutput from './AgentOutput';

const STEP_LABEL: Record<StepState, string> = { complete: 'Complete', working: 'Working', nodata: 'No data', failed: 'Failed', blocked: 'Not reached', waiting: 'Waiting' };

export function StateMark({ state, size = 15 }: { state: StepState; size?: number }) {
  if (state === 'working') return <Loader2 className="spin" size={size} aria-hidden="true" />;
  if (state === 'complete') return <Check size={size} aria-hidden="true" />;
  if (state === 'nodata') return <CircleDashed size={size} aria-hidden="true" />;
  if (state === 'failed') return <AlertTriangle size={size} aria-hidden="true" />;
  return <Circle size={size - 5} aria-hidden="true" />;
}

const SOURCE_STATE: Record<string, { label: string; tone: string; Icon: typeof Check }> = {
  working: { label: 'Fetching', tone: 'working', Icon: Loader2 },
  ok: { label: 'Data', tone: 'green', Icon: Check },
  empty: { label: 'Empty', tone: 'blue', Icon: CircleDashed },
  unavailable: { label: 'Unavailable', tone: 'red', Icon: AlertTriangle },
  failed: { label: 'Failed', tone: 'red', Icon: AlertTriangle },
  not_configured: { label: 'Not set up', tone: 'amber', Icon: CircleSlash },
  no_recent_discussion: { label: 'No recent posts', tone: 'amber', Icon: CircleDashed },
};
export const sourceState = (state: string) => SOURCE_STATE[state] || { label: state, tone: 'neutral', Icon: CircleDashed };
const GROUPS: [string, string][] = [['required', 'Required'], ['sentiment', 'Sentiment'], ['supplementary', 'Supplementary']];

function SourceChip({ chip, now, open, toggle }: { chip: Chip; now: number; open: boolean; toggle: () => void }) {
  const s = sourceState(chip.state), working = chip.state === 'working';
  const seconds = working ? Math.max(0, now / 1000 - chip.start) : (chip.elapsedMs ?? 0) / 1000;
  const detail = chip.reason || (chip.items !== undefined ? `${chip.items} items` : s.label);
  return <button type="button" className={`source-chip ${s.tone}`} aria-expanded={open} title={detail} onClick={toggle}>
    <s.Icon className={working ? 'spin' : ''} size={14} aria-hidden="true" />
    <span className="chip-name">{chip.name}</span>
    <span className="chip-state">{s.label}</span>
    {(working || chip.elapsedMs !== undefined) && <span className="chip-time">{seconds.toFixed(working ? 0 : 1)}s</span>}
    {working && <span className="chip-bar" aria-hidden="true" />}
  </button>;
}

export function EvidenceChips({ chips, now, running }: { chips: Chip[]; now: number; running: boolean }) {
  const [openId, setOpenId] = useState('');
  const picked = chips.find(c => c.id === openId);
  if (!chips.length) return <p className="step-note">{running ? 'Connecting to data providers. Each source appears here as it is contacted.' : 'No per-source events were recorded for this run.'}</p>;
  return <div className="evidence-chips">
    {GROUPS.map(([group, title]) => {
      const list = chips.filter(c => c.group === group || (!GROUPS.some(g => g[0] === c.group) && group === 'required'));
      return list.length ? <div className="chip-group" key={group}><h4>{title}</h4><div>{list.map(c => <SourceChip key={c.id} chip={c} now={now} open={openId === c.id} toggle={() => setOpenId(openId === c.id ? '' : c.id)} />)}</div></div> : null;
    })}
    {picked && <p className="chip-detail" role="status"><strong>{picked.name}</strong> — {sourceState(picked.state).label}{picked.items !== undefined ? ` · ${picked.items} items` : ''}{picked.reason ? `. ${picked.reason}` : '.'}</p>}
  </div>;
}

const phaseSpan = (d: Derived, key: PhaseKey) => {
  const t = d.timing[key];
  return t.start !== undefined && t.end !== undefined ? t.end - t.start : undefined;
};

/** One-line summary of a phase for the strip and collapsed stepper headers. */
export function phaseDetail(key: PhaseKey, d: Derived, events: RunEvent[]) {
  if (key === 'evidence') {
    const done = d.chips.filter(c => c.state !== 'working');
    if (!d.chips.length) return 'Fresh data';
    return `${done.filter(c => c.state === 'ok').length} of ${d.chips.length} sources returned data`;
  }
  if (key === 'analysts') return d.sentimentNoData && d.status.sentiment === 'complete' ? `${agents.filter(a => a.phase === 'analysts' && d.status[a.key] === 'complete').length} reports · Sentiment: no data` : `${agents.filter(a => a.phase === 'analysts' && d.status[a.key] === 'complete').length} of 4 reports`;
  if (key === 'debate') { const n = debateRounds(events).length; return `${n} round${n === 1 ? '' : 's'}${d.outputs.manager?.recommendation ? ' · ' + d.outputs.manager.recommendation : ''}`; }
  return d.outputs.trader?.direction ? String(d.outputs.trader.direction) : 'Proposal';
}

export function PipelineStrip({ d, events, onOpen }: { d: Derived; events: RunEvent[]; onOpen: (key: PhaseKey) => void }) {
  return <nav className="pipeline-strip" aria-label="Research pipeline">
    <ol>{phases.map(p => {
      const state = d.phaseStates[p.key], secs = phaseSpan(d, p.key), Icon = p.icon;
      return <li key={p.key}><button type="button" className={`strip-step ${state}`} onClick={() => onOpen(p.key)} aria-label={`${p.name}: ${STEP_LABEL[state]}. Open its output.`}>
        <span className="strip-mark"><StateMark state={state} /></span>
        <span className="strip-text"><strong><Icon size={14} aria-hidden="true" /> {p.name}</strong><span className="strip-state">{STEP_LABEL[state]}{secs !== undefined ? ` · ${duration(secs)}` : ''}</span><small>{phaseDetail(p.key, d, events)}</small></span>
        <ArrowRight className="strip-arrow" size={14} aria-hidden="true" />
      </button></li>;
    })}</ol></nav>;
}

function AgentRow({ agent, d, now, onOpen }: { agent: (typeof agents)[number]; d: Derived; now: number; onOpen?: () => void }) {
  const [open, setOpen] = useState(false);
  const state: StepState = d.status[agent.key] === 'complete' && agent.key === 'sentiment' && d.sentimentNoData ? 'nodata' : (d.status[agent.key] as StepState) || 'waiting';
  const t = d.times[agent.key], Icon = agent.icon;
  const secs = t?.start !== undefined ? (t.end ?? now / 1000) - t.start : undefined;
  return <li className={`agent-row ${state}`}>
    <div className="agent-row-head">
      <span className="agent-icon"><Icon size={16} aria-hidden="true" /></span>
      <div><strong>{agent.label}</strong><small>{agent.framework}</small></div>
      <span className="agent-state"><StateMark state={state} size={14} /> {STEP_LABEL[state]}{secs !== undefined && state !== 'waiting' ? ` · ${duration(secs)}` : ''}</span>
      {d.outputs[agent.key] && <button type="button" className="text-button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Hide output' : 'View output'}</button>}
    </div>
    {state === 'working' && <p className="step-note">{agent.job}</p>}
    {open && <div className="agent-row-body"><AgentOutput kind={agent.key === 'bull' || agent.key === 'bear' || agent.key === 'manager' || agent.key === 'trader' ? agent.key : 'analyst'} data={d.outputs[agent.key]} /></div>}
  </li>;
}

/** In-progress view: the stepper leads, the current phase is open, concurrent work shows at once. */
export function LivePipeline({ run, events, d, now, draft }: { run: Run; events: RunEvent[]; d: Derived; now: number; draft: string }) {
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const elapsed = Math.max(0, Math.floor(now / 1000 - run.created));
  const rounds = debateRounds(events);
  return <section className="panel live-pipeline" aria-label="Research in progress">
    <div className="live-head"><div><h2>Research in progress</h2><p>Every state below comes from a real execution event.</p></div><span className="elapsed-timer" role="timer" aria-label={`Elapsed ${elapsed} seconds`}><strong>{duration(elapsed)}</strong><small>elapsed</small></span></div>
    <ol className="stepper">{phases.map(p => {
      const state = d.phaseStates[p.key], current = state === 'working';
      const open = toggled[p.key] ?? current, secs = phaseSpan(d, p.key), Icon = p.icon;
      const startedAt = d.timing[p.key].start;
      const live = current && startedAt !== undefined ? now / 1000 - startedAt : secs;
      return <li key={p.key} className={`phase-block ${state}`}>
        <button type="button" className="phase-head" aria-expanded={open} onClick={() => setToggled({ ...toggled, [p.key]: !open })}>
          <span className="strip-mark"><StateMark state={state} /></span>
          <span className="phase-title"><strong><Icon size={15} aria-hidden="true" /> {p.name}</strong><small>{state === 'waiting' ? p.detail : phaseDetail(p.key, d, events)}</small></span>
          <span className="phase-time">{STEP_LABEL[state]}{live !== undefined && state !== 'waiting' ? ` · ${duration(live)}` : ''}</span>
          <ChevronDown className={open ? 'rotated' : ''} size={16} aria-hidden="true" />
        </button>
        {open && <div className="phase-body">
          {p.key === 'evidence' && <EvidenceChips chips={d.chips} now={now} running />}
          {p.key === 'analysts' && <ul className="agent-list">{agents.filter(a => a.phase === 'analysts').map(a => <AgentRow key={a.key} agent={a} d={d} now={now} />)}</ul>}
          {p.key === 'debate' && <>
            <ul className="agent-list">{agents.filter(a => a.phase === 'debate').map(a => <AgentRow key={a.key} agent={a} d={d} now={now} />)}</ul>
            {rounds.length > 0 && <p className="step-note">{rounds.length} round{rounds.length === 1 ? '' : 's'} of Bull and Bear contributions received.</p>}
            {draft && <div className="draft" aria-live="polite"><strong>Draft in progress, not yet validated</strong><p>{draft.slice(-420)}</p></div>}
          </>}
          {p.key === 'trader' && <ul className="agent-list">{agents.filter(a => a.phase === 'trader').map(a => <AgentRow key={a.key} agent={a} d={d} now={now} />)}</ul>}
        </div>}
      </li>;
    })}</ol>
  </section>;
}
