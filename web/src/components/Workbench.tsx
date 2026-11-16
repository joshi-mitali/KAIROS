import { useEffect } from 'react';
import { Activity, AlertTriangle, Check, ChevronDown, Database, FileSearch, Scale, TrendingDown, TrendingUp } from 'lucide-react';
import type { Run, RunEvent } from '../types';
import { agentKey, agents, debateRounds, type AgentKey, type Derived } from '../lib/run';
import { humanError, istTime } from '../lib/format';
import AgentOutput from './AgentOutput';
import SourceProvenance, { sourceRows } from './SourceProvenance';

export type BenchTab = 'debate' | 'reports' | 'sources' | 'log';
export type ReportKey = 'market' | 'sentiment' | 'news' | 'fundamentals' | 'trader';

const REPORTS: { key: ReportKey; name: string }[] = [
  { key: 'market', name: 'Market' }, { key: 'sentiment', name: 'Sentiment' }, { key: 'news', name: 'News' }, { key: 'fundamentals', name: 'Financials' }, { key: 'trader', name: 'Trader proposal' },
];

function describe(e: RunEvent): { title: string; detail: string; bad?: boolean } {
  const p = e.payload, who = agents.find(a => a.key === agentKey(p.agent))?.label || (p.agent === 'crewai.research_crew' ? 'Research crew' : String(p.agent || ''));
  switch (e.type) {
    case 'run-queued': return { title: 'Run queued', detail: `${p.ticker} · ${p.risk} risk` };
    case 'run-started': return { title: 'Run started', detail: String(p.ticker || '') };
    case 'evidence-source-started': return { title: 'Source requested', detail: p.name };
    case 'evidence-source-done': return { title: p.status === 'ok' ? 'Source returned data' : `Source ${String(p.status).replaceAll('_', ' ')}`, detail: `${p.name}${typeof p.elapsed_ms === 'number' ? ` · ${(p.elapsed_ms / 1000).toFixed(1)}s` : ''}${p.reason ? ` · ${p.reason}` : ''}`, bad: ['unavailable', 'failed'].includes(p.status) };
    case 'evidence-refresh-started': return { title: 'Source requested', detail: String(p.source) };
    case 'evidence-refreshed': return { title: 'Source returned', detail: `${p.source}${typeof p.total === 'number' ? ` · ${p.available} of ${p.total} available` : p.status ? ` · ${String(p.status).replaceAll('_', ' ').toLowerCase()}` : ''}` };
    case 'evidence-unavailable': return { title: 'Source unavailable', detail: `${p.source}${p.reason ? ` · ${p.reason}` : ''}`, bad: true };
    case 'agent-started': return { title: 'Agent started', detail: who };
    case 'agent-completed': return { title: 'Agent completed', detail: who };
    case 'agent-failed': return { title: 'Agent failed', detail: `${who}${p.message ? ` · ${humanError(p.message).slice(0, 160)}` : ''}`, bad: true };
    case 'agent-state': return { title: 'Tool or state update', detail: who };
    case 'debate-argument': return { title: 'Contribution received', detail: who };
    case 'debate-completed': return { title: 'Debate completed', detail: `${(p.rounds || []).length} rounds` };
    case 'guardrail-result': return { title: 'Prompt-injection check', detail: `${String(p.result?.source || '').replaceAll('_', ' ')} · ${String(p.result?.status || '').toLowerCase()}`, bad: p.result?.status !== 'PASSED' };
    case 'run-completed': return { title: 'Run completed', detail: String(p.ticker || '') };
    case 'run-failed': return { title: 'Run failed', detail: humanError(p.message).slice(0, 180), bad: true };
    default: return { title: e.type.replaceAll('-', ' '), detail: '' };
  }
}

export function ExecutionLog({ events, limit, newestFirst = false, showAssurance = true }: { events: RunEvent[]; limit?: number; newestFirst?: boolean; showAssurance?: boolean }) {
  const shown = events.filter(e => e.type !== 'debate-stream' && (limit ? e.type !== 'agent-state' : true));
  const list = newestFirst ? [...shown].reverse() : shown;
  const rows = limit ? list.slice(0, limit) : list;
  return <div className="exec-log">
    {showAssurance && <p className="log-assurance">Every row is an actual callback from this run. Progress is never simulated.</p>}
    {rows.length ? <ol aria-live={newestFirst ? 'polite' : undefined}>{rows.map(e => { const d = describe(e); return <li key={e.id} className={d.bad ? 'bad' : ''}><time dateTime={new Date(e.created * 1000).toISOString()}>{istTime(e.created)}</time><div><strong>{d.title}</strong>{d.detail && <span>{d.detail}</span>}</div>{e.type.endsWith('completed') && <Check size={14} aria-hidden="true" />}</li>; })}</ol> : <p className="muted">No execution events recorded.</p>}
  </div>;
}

function Side({ kind, data }: { kind: 'bull' | 'bear'; data?: Record<string, any> }) {
  const up = kind === 'bull';
  return <article className={`side ${kind}`}>
    <header>{up ? <TrendingUp size={16} aria-hidden="true" /> : <TrendingDown size={16} aria-hidden="true" />}<h4>{up ? 'Bull researcher' : 'Bear researcher'}</h4></header>
    {data ? <AgentOutput kind={kind} data={data} /> : <p className="muted">No contribution received for this round.</p>}
  </article>;
}

function DebateView({ events, d }: { events: RunEvent[]; d: Derived }) {
  const rounds = debateRounds(events), verdict = d.outputs.manager;
  return <div className="debate-view">
    {verdict && <section className="verdict-card"><header><Scale size={17} aria-hidden="true" /><h3>Manager’s verdict</h3></header><AgentOutput kind="manager" data={verdict} omit={['bull_summary', 'bear_summary', 'source_references']} /></section>}
    {rounds.map((r, i) => <details key={r.round} className="round" open={i === 0}><summary>Round {r.round}<span>{[r.bull && `Bull upside ${r.bull.upside_potential_pct ?? '?'}%`, r.bear && `Bear downside ${r.bear.downside_risk_pct ?? '?'}%`].filter(Boolean).join(' · ')}</span><ChevronDown size={15} aria-hidden="true" /></summary><div className="sides"><Side kind="bull" data={r.bull} /><Side kind="bear" data={r.bear} /></div></details>)}
  </div>;
}

function ReportsView({ d, sel, setSel }: { d: Derived; sel: ReportKey; setSel: (k: ReportKey) => void }) {
  const data = d.outputs[sel as AgentKey];
  const stale = sel === 'sentiment' && d.sentimentNoData;
  return <div className="reports-view">
    <div className="segmented" role="group" aria-label="Agent report">
      {REPORTS.map(r => <button key={r.key} type="button" aria-pressed={sel === r.key} className={r.key === 'sentiment' && d.sentimentNoData ? 'warn' : ''} onClick={() => setSel(r.key)}>{r.name}{r.key === 'sentiment' && d.sentimentNoData && <span className="tab-flag">No data</span>}{!d.outputs[r.key as AgentKey] && <span className="tab-flag muted">{d.status[r.key as AgentKey] === 'failed' ? 'Failed' : 'Pending'}</span>}</button>)}
    </div>
    {stale && <p className="quiet-note warn" role="status"><AlertTriangle size={16} aria-hidden="true" /><span>No data: Sentiment was not assessed from a real discussion sample. The figures below are placeholders, not a neutral reading.</span></p>}
    <AgentOutput kind={sel === 'trader' ? 'trader' : 'analyst'} data={data} />
  </div>;
}

export default function Workbench({ run, events, d, tab, setTab, report, setReport }: { run: Run; events: RunEvent[]; d: Derived; tab: BenchTab; setTab: (t: BenchTab) => void; report: ReportKey; setReport: (k: ReportKey) => void }) {
  const failed = ['FAILED', 'INTERRUPTED'].includes(run.status);
  const rounds = debateRounds(events), rows = sourceRows(run.result?.provenance, d.chips);
  const reportsReady = REPORTS.filter(r => d.outputs[r.key as AgentKey]).length;
  const tabs = ([
    { key: 'debate', long: 'Debate', short: 'Debate', icon: Scale, badge: rounds.length ? `${rounds.length} round${rounds.length === 1 ? '' : 's'}` : '', show: !failed || rounds.length > 0 },
    { key: 'reports', long: 'Analyst reports', short: 'Reports', icon: FileSearch, badge: `${reportsReady}/5`, show: !failed || reportsReady > 0 },
    { key: 'sources', long: 'Sources & gaps', short: 'Sources', icon: Database, badge: d.gaps.length ? `${d.gaps.length} gap${d.gaps.length === 1 ? '' : 's'}` : '', warn: d.gaps.length > 0, show: !failed || rows.length > 0 },
    { key: 'log', long: 'Execution log', short: 'Log', icon: Activity, badge: '', show: true },
  ] as const).filter(t => t.show);
  useEffect(() => { if (!tabs.some(t => t.key === tab)) setTab(tabs[0].key); });
  const move = (e: React.KeyboardEvent, i: number) => {
    const n = e.key === 'ArrowRight' ? (i + 1) % tabs.length : e.key === 'ArrowLeft' ? (i + tabs.length - 1) % tabs.length : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : -1;
    if (n < 0) return;
    e.preventDefault(); setTab(tabs[n].key); document.getElementById('bench-tab-' + tabs[n].key)?.focus();
  };
  return <section className="panel workbench" id="workbench" aria-label="Research evidence">
    <div className="bench-tabs" role="tablist" aria-label="Evidence">
      {tabs.map((t, i) => <button key={t.key} type="button" role="tab" id={'bench-tab-' + t.key} aria-selected={tab === t.key} aria-controls={'bench-panel-' + t.key} tabIndex={tab === t.key ? 0 : -1} onKeyDown={e => move(e, i)} onClick={() => setTab(t.key)}>
        <t.icon size={16} aria-hidden="true" /><span className="long">{t.long}</span><span className="short">{t.short}</span>{t.badge && <span className={`tab-badge ${'warn' in t && t.warn ? 'warn' : ''}`}>{t.badge}</span>}
      </button>)}
    </div>
    <div role="tabpanel" id={'bench-panel-' + tab} aria-labelledby={'bench-tab-' + tab} className="bench-panel" tabIndex={0}>
      {tab === 'debate' && <DebateView events={events} d={d} />}
      {tab === 'reports' && <ReportsView d={d} sel={report} setSel={setReport} />}
      {tab === 'sources' && <SourceProvenance rows={rows} retrievedAt={run.result?.provenance?.retrieved_at} />}
      {tab === 'log' && <ExecutionLog events={events} />}
    </div>
  </section>;
}
