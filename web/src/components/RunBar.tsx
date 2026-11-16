import { AlertTriangle, Download, FileText, RotateCcw } from 'lucide-react';
import type { Run } from '../types';
import { duration, humanError } from '../lib/format';
import { agents, phases, type Derived } from '../lib/run';
import { Pill, stockNames } from './Decision';

const TONE: Record<string, string> = { COMPLETED: 'green', FAILED: 'red', INTERRUPTED: 'red', RUNNING: 'blue', QUEUED: 'blue' };
const WORD: Record<string, string> = { COMPLETED: 'Complete', FAILED: 'Failed', INTERRUPTED: 'Interrupted', RUNNING: 'Running', QUEUED: 'Queued' };

export default function RunBar({ run, d, elapsed }: { run: Run; d: Derived; elapsed: number }) {
  const live = ['RUNNING', 'QUEUED'].includes(run.status);
  const gap = d.gaps.length ? `${d.gaps.length} data gap${d.gaps.length === 1 ? '' : 's'}: ${d.gaps.slice(0, 2).join(', ')}${d.gaps.length > 2 ? '…' : ''}` : '';
  return <div className="run-bar" role="region" aria-label="Run summary">
    <div className="run-bar-id"><strong>{run.ticker}</strong><span className="run-name">{stockNames[run.ticker] || ''}</span><Pill tone={TONE[run.status] || 'neutral'}>{WORD[run.status] || run.status}</Pill></div>
    <dl className="run-bar-stats">
      <div><dt>{live ? 'Elapsed' : 'Duration'}</dt><dd>{duration(live ? elapsed : d.totalSeconds)}</dd></div>
      <div><dt>Agents</dt><dd>{d.done}/{agents.length}</dd></div>
    </dl>
    {gap && <Pill tone="amber"><AlertTriangle size={12} aria-hidden="true" /> {gap}</Pill>}
    {!live && <div className="run-bar-actions">
      <a className="secondary-button" href={`/api/runs/${run.id}/report`} download><Download size={15} aria-hidden="true" /> Download report</a>
      <span className="pdf-wrap"><a className="secondary-button" href={`/api/runs/${run.id}/report?print=1`} target="_blank" rel="noopener" aria-describedby="pdf-hint"><FileText size={15} aria-hidden="true" /> Save as PDF</a>
        <span id="pdf-hint" role="tooltip" className="pdf-hint">Opens your browser’s print dialog</span></span>
    </div>}
  </div>;
}

export function FailureCard({ run, d, onRetry, busy }: { run: Run; d: Derived; onRetry: () => void; busy: boolean }) {
  const stage = d.failedPhase ? phases.find(p => p.key === d.failedPhase)!.name : 'Start';
  const agent = d.failedAgent ? agents.find(a => a.key === d.failedAgent)?.label : '';
  const reason = humanError(run.error || d.failure);
  return <section className="alert error failure-card" role="alert">
    <AlertTriangle size={20} aria-hidden="true" />
    <div><strong>{run.status === 'INTERRUPTED' ? 'Run interrupted' : 'Run failed'} at {stage}{agent ? ` · ${agent}` : ''}</strong><p>{reason}</p></div>
    <button type="button" className="primary-button" onClick={onRetry} disabled={busy}><RotateCcw size={15} aria-hidden="true" /> Retry {run.ticker}</button>
  </section>;
}
