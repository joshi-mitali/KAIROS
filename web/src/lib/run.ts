import { Activity, BarChart3, BookOpen, FileSearch, GitBranch, MessageSquareText, TrendingDown, TrendingUp, Wallet } from 'lucide-react';
import type { Data, Run, RunEvent } from '../types';

export const agents = [
  { key: 'market', label: 'Market analyst', framework: 'Google ADK', icon: BarChart3, phase: 'analysts', job: 'Reads price history and quotes through two MCP tools and calculates indicators.' },
  { key: 'sentiment', label: 'Sentiment analyst', framework: 'Specialist', icon: MessageSquareText, phase: 'analysts', job: 'Reviews retail discussion, its sample size and source provenance.' },
  { key: 'news', label: 'News analyst', framework: 'Specialist', icon: FileSearch, phase: 'analysts', job: 'Screens article text and explains catalysts and regulatory risks.' },
  { key: 'fundamentals', label: 'Fundamentals', framework: 'Specialist', icon: BookOpen, phase: 'analysts', job: 'Assesses reported financials, profitability and solvency.' },
  { key: 'bull', label: 'Bull researcher', framework: 'CrewAI', icon: TrendingUp, phase: 'debate', job: 'Builds the upside case and answers the Bear’s evidence.' },
  { key: 'bear', label: 'Bear researcher', framework: 'CrewAI', icon: TrendingDown, phase: 'debate', job: 'Challenges the upside case and identifies downside risk.' },
  { key: 'manager', label: 'Research manager', framework: 'CrewAI', icon: GitBranch, phase: 'debate', job: 'Weighs both arguments and returns a typed research verdict.' },
  { key: 'trader', label: 'Trader', framework: 'Proposal', icon: Wallet, phase: 'trader', job: 'Combines verdict, risk preference and memory into an explained simulated proposal.' },
] as const;
export type AgentKey = (typeof agents)[number]['key'];

export const phases = [
  { key: 'evidence', name: 'Evidence', icon: Activity, detail: 'Fresh data from live sources' },
  { key: 'analysts', name: 'Analysts', icon: BarChart3, detail: 'Four specialist reports' },
  { key: 'debate', name: 'Debate', icon: GitBranch, detail: 'Bull and Bear, then the manager' },
  { key: 'trader', name: 'Trader', icon: Wallet, detail: 'Proposal for your review' },
] as const;
export type PhaseKey = (typeof phases)[number]['key'];
export type StepState = 'waiting' | 'working' | 'complete' | 'nodata' | 'failed' | 'blocked';

export const agentKey = (name: unknown): AgentKey | undefined => {
  const value = String(name || '').toLowerCase();
  return agents.find(a => value.includes(a.key) || (a.key === 'manager' && value.includes('chief investment')))?.key;
};

const NO_DATA = ['UNAVAILABLE', 'NO_RECENT_DISCUSSION', 'SOURCE_UNAVAILABLE'];

export type Chip = {
  id: string; name: string; group: string; state: string; start: number; elapsedMs?: number; items?: number; reason?: string; asOf?: string;
};
export type Timing = { start?: number; end?: number };

const legacyGroup = (name: string) => (/reddit|sentiment/i.test(name) ? 'sentiment' : /supplementary/i.test(name) ? 'supplementary' : 'required');

/** Per-source evidence chips from the new contract, with older runs mapped from the legacy events. */
function evidenceChips(events: RunEvent[]): Chip[] {
  const chips: Chip[] = [];
  for (const e of events) {
    const p = e.payload;
    if (e.type === 'evidence-source-started') {
      chips.push({ id: p.source_id, name: p.name, group: p.group || 'required', state: 'working', start: e.created });
    } else if (e.type === 'evidence-source-done') {
      const open = chips.find(c => c.id === p.source_id && c.state === 'working');
      const done = { state: p.status || 'ok', elapsedMs: p.elapsed_ms, items: p.items, reason: p.reason };
      if (open) Object.assign(open, done);
      else chips.push({ id: p.source_id, name: p.name, group: p.group || 'required', start: e.created, ...done });
    } else if (e.type === 'evidence-refresh-started') {
      chips.push({ id: 'legacy:' + p.source, name: String(p.source), group: legacyGroup(String(p.source)), state: 'working', start: e.created });
    } else if (e.type === 'evidence-refreshed' || e.type === 'evidence-unavailable') {
      const open = chips.find(c => c.state === 'working' && c.id.startsWith('legacy:'));
      if (!open) continue;
      const status = String(p.status || '').toLowerCase();
      open.state = e.type === 'evidence-unavailable' ? 'unavailable' : status === 'no_recent_discussion' ? 'no_recent_discussion' : p.count === 0 || p.available === 0 ? 'empty' : 'ok';
      open.elapsedMs = (e.created - open.start) * 1000;
      open.items = p.count ?? p.available;
      open.asOf = p.as_of;
      open.reason = p.total ? `${p.available} of ${p.total} supplementary sources returned data` : p.reason;
    }
  }
  return chips;
}

export function deriveRun(run: Run | null, events: RunEvent[]) {
  const failedRun = ['FAILED', 'INTERRUPTED'].includes(run?.status || '');
  const status: Partial<Record<AgentKey, 'working' | 'complete' | 'failed'>> = {};
  const outputs: Partial<Record<AgentKey, Data>> = {};
  const times: Partial<Record<AgentKey, Timing>> = {};
  let failedAgent: AgentKey | undefined;
  let crew: Timing = {};
  let failure = '';
  for (const e of events) {
    const key = agentKey(e.payload.agent);
    if (e.payload.agent === 'crewai.research_crew' && e.type === 'agent-started') crew = { start: e.created };
    if (!key) continue;
    const t = (times[key] ??= {});
    if (e.type === 'agent-started') { status[key] = 'working'; t.start = t.start ?? e.created; }
    if (e.type === 'agent-completed' || e.type === 'debate-argument') {
      status[key] = 'complete';
      t.end = e.created;
      outputs[key] = e.payload.report || e.payload.thesis;
    }
    if (e.type === 'agent-failed') { status[key] = 'failed'; failedAgent = key; failure = String(e.payload.message || ''); }
  }
  for (const k of agents.map(a => a.key)) {
    if (!outputs[k] && k === 'manager') outputs[k] = run?.result?.verdict;
    if (!outputs[k] && k === 'trader') outputs[k] = run?.result?.trading_proposal;
    if (!outputs[k] && run?.result?.analyst_reports?.[k]) { outputs[k] = run.result.analyst_reports[k]; status[k] ??= 'complete'; }
    if (outputs[k] && !status[k]) status[k] = 'complete';
  }
  // A run that has stopped never leaves a step "working".
  if (failedRun) for (const k of Object.keys(status) as AgentKey[]) if (status[k] === 'working') { status[k] = 'failed'; failedAgent ??= k; }

  const chips = evidenceChips(events);
  const sourcesDone = chips.length > 0 && chips.every(c => c.state !== 'working');
  const firstEvent = events[0]?.created ?? run?.created;
  const firstAgent = events.find(e => e.type === 'agent-started')?.created;
  const evidence: Timing = { start: events.find(e => e.type === 'run-started')?.created ?? firstEvent, end: firstAgent ?? (sourcesDone && failedRun ? chips.reduce((m, c) => Math.max(m, c.start + (c.elapsedMs || 0) / 1000), 0) : undefined) };
  const span = (keys: AgentKey[]): Timing => {
    const s = keys.map(k => times[k]?.start).filter((v): v is number => v !== undefined);
    const en = keys.map(k => times[k]?.end).filter((v): v is number => v !== undefined);
    return { start: s.length ? Math.min(...s) : undefined, end: en.length === keys.length ? Math.max(...en) : undefined };
  };
  const timing: Record<PhaseKey, Timing> = {
    evidence,
    analysts: span(['market', 'sentiment', 'news', 'fundamentals']),
    debate: { start: crew.start, end: events.find(e => e.type === 'debate-completed')?.created },
    trader: times.trader || {},
  };

  const sentiment = run?.result?.analyst_reports?.sentiment ?? outputs.sentiment;
  const prov = run?.result?.provenance?.sources;
  const sentimentNoData = NO_DATA.includes(String(prov?.sentiment?.status)) || NO_DATA.includes(String(sentiment?.data_source))
    || chips.some(c => c.group === 'sentiment' && ['unavailable', 'no_recent_discussion', 'failed'].includes(c.state));
  const gaps: string[] = [];
  if (sentimentNoData) gaps.push('Sentiment');
  for (const s of Array.isArray(prov?.supplementary) ? prov.supplementary : []) if (['unavailable', 'failed'].includes(String(s.status))) gaps.push(String(s.name || s.id));

  const phaseState = (key: PhaseKey): StepState => {
    const keys = agents.filter(a => a.phase === key).map(a => a.key);
    if (key === 'evidence') {
      if (chips.some(c => c.state === 'working')) return failedRun ? 'failed' : 'working';
      if (firstAgent || sourcesDone || events.some(e => e.type === 'evidence-refreshed') || (run?.status === 'COMPLETED' && !failedAgent)) return 'complete';
      return failedRun ? 'failed' : run && events.some(e => e.type === 'run-started') ? 'working' : failedRun ? 'failed' : 'waiting';
    }
    if (keys.some(k => status[k] === 'failed')) return 'failed';
    if (keys.every(k => status[k] === 'complete')) return key === 'analysts' && sentimentNoData ? 'nodata' : 'complete';
    if (keys.some(k => status[k] === 'working' || status[k] === 'complete')) return failedRun ? 'failed' : 'working';
    return failedRun ? 'blocked' : 'waiting';
  };
  const phaseStates = Object.fromEntries(phases.map(p => [p.key, phaseState(p.key)])) as Record<PhaseKey, StepState>;
  // Mark the first unfinished phase of a failed run as the failure point.
  let failedPhase: PhaseKey | undefined;
  if (failedRun) failedPhase = failedAgent ? agents.find(a => a.key === failedAgent)!.phase as PhaseKey : phases.find(p => !['complete', 'nodata'].includes(phaseStates[p.key]))?.key;
  if (failedPhase) phaseStates[failedPhase] = 'failed';

  const done = agents.filter(a => status[a.key] === 'complete').length;
  const end = events.find(e => ['run-completed', 'run-failed'].includes(e.type))?.created ?? (failedRun ? events.at(-1)?.created : undefined);
  const totalSeconds = end !== undefined && run ? end - (events[0]?.created ?? run.created) : run?.result?.latency_ms && run.status === 'COMPLETED' ? run.result.latency_ms / 1000 : undefined;
  return { status, outputs, times, chips, timing, phaseStates, failedPhase, failedAgent, failure, done, gaps, sentimentNoData, totalSeconds, evidenceStarted: events.some(e => e.type.startsWith('evidence-')) };
}
export type Derived = ReturnType<typeof deriveRun>;

/** Bull/Bear pairs by round; the debate-completed event is authoritative, live arguments fill in until then. */
export function debateRounds(events: RunEvent[]): { round: number; bull?: Data; bear?: Data }[] {
  const finished = events.find(e => e.type === 'debate-completed')?.payload.rounds;
  if (Array.isArray(finished) && finished.length) return finished.map((r: Data, i: number) => ({ round: r.round ?? i + 1, bull: r.bull_argument, bear: r.bear_counterargument }));
  const bull: Data[] = [], bear: Data[] = [];
  for (const e of events) if (e.type === 'debate-argument') {
    const key = agentKey(e.payload.agent);
    if (key === 'bull') bull.push(e.payload.thesis); else if (key === 'bear') bear.push(e.payload.thesis);
  }
  return Array.from({ length: Math.max(bull.length, bear.length) }, (_, i) => ({ round: i + 1, bull: bull[i], bear: bear[i] }));
}
