import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ArrowRight, ArrowUpRight, BarChart3, ChevronRight, GitBranch, History, Layers3, Loader2, LockKeyhole, Menu, Play, RefreshCw, ShieldCheck, Wallet, X, Activity } from 'lucide-react';
import { api, post } from './lib/api';
import { duration, humanError, ist } from './lib/format';
import { deriveRun, type PhaseKey } from './lib/run';
import { DecisionCard, EmptyDecision, Pill, PriceCard, stockNames } from './components/Decision';
import { ExecutionLog } from './components/Workbench';
import { LivePipeline, PipelineStrip } from './components/Pipeline';
import PaperTrading from './components/PaperTrading';
import RunBar, { FailureCard } from './components/RunBar';
import StockSearch from './components/StockSearch';
import Workbench, { type BenchTab, type ReportKey } from './components/Workbench';
import type { Data, Run, RunEvent } from './types';

type Pane = 'Research' | 'Paper trading' | 'Run history';
const NAV = [{ name: 'Research', icon: BarChart3 }, { name: 'Paper trading', icon: Wallet }, { name: 'Run history', icon: History }] as const;
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Run-list rows may carry verdict, duration and gaps once the backend provides them; columns appear only when some row has data. */
const rowVerdict = (r: Data) => r.recommendation ?? r.direction ?? r.verdict?.recommendation ?? (typeof r.verdict === 'string' ? r.verdict : undefined);
const rowDuration = (r: Data) => r.duration_s ?? r.duration_seconds ?? (typeof r.duration_ms === 'number' ? r.duration_ms / 1000 : undefined);
const rowGaps = (r: Data): string[] | undefined => { const g = r.data_gaps ?? r.gaps; return Array.isArray(g) ? g.map(String) : typeof g === 'number' ? Array(g).fill('') : undefined; };

function RunHistory({ runs, onOpen, onRefresh, onStart }: { runs: Run[]; onOpen: (id: string) => void; onRefresh: () => void; onStart: () => void }) {
  const rows = runs as Data[];
  const showVerdict = rows.some(r => rowVerdict(r)), showDuration = rows.some(r => rowDuration(r) !== undefined), showGaps = rows.some(r => rowGaps(r) !== undefined), showSource = rows.some(r => r.source !== 'live');
  return <>
    <div className="page-intro"><h1>Run history</h1><button type="button" className="secondary-button" onClick={onRefresh}><RefreshCw size={15} aria-hidden="true" /> Refresh</button></div>
    <section className="panel">{rows.length
      ? <div className="table-scroll"><table><thead><tr><th>Stock</th><th>Started</th><th>Risk</th>{showSource && <th>Source</th>}<th>Status</th>{showVerdict && <th>Verdict</th>}{showDuration && <th>Duration</th>}{showGaps && <th>Data gaps</th>}<th><span className="sr-only">Open run</span></th></tr></thead>
        <tbody>{rows.map(r => { const gaps = rowGaps(r), verdict = rowVerdict(r); return <tr key={r.id}>
          <td><strong>{r.ticker}</strong><small>{stockNames[r.ticker]}</small></td>
          <td>{ist(r.created)}</td><td>{r.risk}</td>
          {showSource && <td>{r.source === 'live' ? 'Live market tools' : 'Saved evidence'}</td>}
          <td><Pill tone={r.status === 'COMPLETED' ? 'green' : r.status === 'FAILED' || r.status === 'INTERRUPTED' ? 'red' : 'neutral'}>{r.status}</Pill>{r.error && <small className="row-error">{humanError(r.error).slice(0, 80)}</small>}</td>
          {showVerdict && <td>{verdict ?? '—'}</td>}
          {showDuration && <td>{rowDuration(r) !== undefined ? duration(rowDuration(r)) : '—'}</td>}
          {showGaps && <td>{gaps === undefined ? '—' : gaps.length ? <Pill tone="amber">{gaps.length} gap{gaps.length === 1 ? '' : 's'}{gaps.filter(Boolean).length ? `: ${gaps.filter(Boolean).join(', ')}` : ''}</Pill> : 'None'}</td>}
          <td><button type="button" className="text-button" onClick={() => onOpen(r.id)}>Open <ArrowUpRight size={14} aria-hidden="true" /></button></td>
        </tr>; })}</tbody></table></div>
      : <div className="large-empty"><History size={32} aria-hidden="true" /><h2>A clear record of your research.</h2><p>Completed, failed and interrupted runs will appear here.</p><button type="button" className="primary-button" onClick={onStart}>Start research <ArrowRight size={15} /></button></div>}</section>
  </>;
}

export default function App() {
  const [boot, setBoot] = useState('loading'), [password, setPassword] = useState(''), [bootError, setBootError] = useState('');
  const [pane, setPane] = useState<Pane>('Research'), [navOpen, setNavOpen] = useState(false);
  const [config, setConfig] = useState<Data | null>(null), [ticker, setTicker] = useState('RELIANCE'), [risk, setRisk] = useState('NEUTRAL'), source = 'live';
  const [chart, setChart] = useState<Data | null>(null), [chartError, setChartError] = useState('');
  const [runs, setRuns] = useState<Run[]>([]), [run, setRun] = useState<Run | null>(null), [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [streamStatus, setStreamStatus] = useState('idle'), [clock, setClock] = useState(Date.now());
  const [bench, setBench] = useState<BenchTab>('debate'), [report, setReport] = useState<ReportKey>('market');
  const stream = useRef<EventSource | null>(null);
  const running = !!run && ['RUNNING', 'QUEUED'].includes(run.status);
  const d = useMemo(() => deriveRun(run, events), [run, events]);

  async function openSession() {
    setBoot('loading'); setBootError('');
    try { await post('/session', { password }); setConfig(await api('/config')); setRuns(await api('/runs')); setBoot('ready'); }
    catch (e) { setBootError((e as Error).message); setBoot('login'); }
  }
  useEffect(() => { void openSession(); return () => stream.current?.close(); }, []);
  useEffect(() => {
    if (boot !== 'ready') return;
    setChartError(''); setChart(null);
    let active = true;
    api('/market/' + ticker).then(data => { if (active) setChart(data); }).catch(e => { if (active) setChartError(e.message); });
    return () => { active = false; };
  }, [ticker, boot]);
  useEffect(() => {
    if (!running) return;
    setClock(Date.now());
    const id = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  async function selectRun(id: string) {
    setError(''); stream.current?.close(); setEvents([]);
    try {
      const detail = await api('/runs/' + id);
      setRun(detail); setTicker(detail.ticker); setRisk(detail.risk); setBench('debate'); setReport('market');
      connect(id);
    } catch (e) { setError((e as Error).message); }
  }
  function connect(id: string) {
    stream.current?.close();
    const feed = new EventSource('/api/runs/' + id + '/events');
    stream.current = feed; setStreamStatus('connecting');
    feed.onopen = () => setStreamStatus('connected');
    feed.onmessage = event => {
      const item = JSON.parse(event.data) as RunEvent;
      setEvents(old => (old.some(e => e.id === item.id) ? old : [...old, item]));
      if (['run-completed', 'run-failed'].includes(item.type)) {
        feed.close(); setStreamStatus('complete');
        api('/runs/' + id).then(setRun).catch(e => setError(e.message));
        api('/runs').then(setRuns).catch(() => {});
      } else if (item.type === 'run-started') setRun(old => (old ? { ...old, status: 'RUNNING' } : old));
    };
    feed.onerror = () => {
      setStreamStatus('reconnecting');
      api('/runs/' + id).then(detail => { if (['COMPLETED', 'FAILED', 'INTERRUPTED'].includes(detail.status)) { setRun(detail); feed.close(); setStreamStatus('complete'); } }).catch(() => {});
    };
  }
  async function start(t = ticker, r = risk) {
    setBusy(true); setError('');
    try { const item = await post('/runs', { ticker: t, risk: r, source }); await selectRun(item.id); setRuns(await api('/runs')); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function navigate(next: Pane) { setPane(next); setNavOpen(false); }

  /** A pipeline step opens the matching workbench tab and scrolls to it. */
  function openStep(phase: PhaseKey) {
    if (phase === 'trader') { setBench('reports'); setReport('trader'); } else setBench(phase === 'evidence' ? 'sources' : phase === 'analysts' ? 'reports' : 'debate');
    if (phase === 'analysts') setReport('market');
    requestAnimationFrame(() => document.getElementById('workbench')?.scrollIntoView({ behavior: reducedMotion() ? 'instant' : 'smooth', block: 'start' }));
  }

  if (boot !== 'ready') return <main className="login-shell"><div className="login-brand"><span className="brand-symbol">K</span>KAIROS</div><section className="login-panel"><ShieldCheck size={30} aria-hidden="true" /><h1>Your research workspace.</h1><p>Evidence-led analysis. Visible agent decisions. Paper trading with your approval.</p>
    {boot === 'loading' ? <div className="loading-inline"><Loader2 className="spin" size={20} /> Opening secure session…</div>
      : <form onSubmit={e => { e.preventDefault(); void openSession(); }}><label>Workspace password<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>{bootError && <p className="form-error" role="alert">{bootError}</p>}<button className="primary-button full">Open workspace <ArrowRight size={16} /></button></form>}
  </section><span className="login-footer">KAIROS · Research and virtual execution</span></main>;

  const tickers = config?.tickers || Object.keys(stockNames);
  const finished = !!run && !running;
  const failed = !!run && ['FAILED', 'INTERRUPTED'].includes(run.status);
  const draft = (() => {
    const lastStart = events.filter(e => e.type === 'agent-started').at(-1);
    return events.filter(e => e.type === 'debate-stream' && (!lastStart || e.id > lastStart.id)).map(e => e.payload.text).join('');
  })();
  const elapsed = run ? Math.max(0, Math.floor(clock / 1000 - run.created)) : 0;

  return <div className="app-shell"><a href="#main-content" className="skip-link">Skip to workspace</a>
    <aside className={`sidebar ${navOpen ? 'open' : ''}`}>
      <a className="brand" href="/" aria-label="KAIROS home"><span className="brand-symbol">K</span><strong>KAIROS</strong></a>
      <div className="workspace-label"><span className="workspace-icon"><Layers3 size={16} aria-hidden="true" /></span><div>Equity research<span>Personal workspace</span></div><LockKeyhole size={13} aria-hidden="true" /></div>
      <nav id="workspace-navigation" aria-label="Main navigation">{NAV.map(item => <button type="button" key={item.name} className={`nav-item ${pane === item.name ? 'selected' : ''}`} aria-current={pane === item.name ? 'page' : undefined} onClick={() => navigate(item.name)}><item.icon size={18} aria-hidden="true" /><span>{item.name}</span>{pane === item.name && <ChevronRight size={14} aria-hidden="true" />}</button>)}</nav>
      <div className="sidebar-bottom">
        <div className="integration-row"><span className="connection-dot" /> Langfuse<span>{config?.langfuse_configured ? 'Configured' : 'Not set'}</span></div>
        <div className="integration-row"><ShieldCheck size={13} aria-hidden="true" /> Order environment<span>Paper only</span></div>
        <div className="sidebar-note"><GitBranch size={18} aria-hidden="true" /><p>Understand the decision.<br />Keep the final say.</p></div>
        <div className="profile"><span>KR</span><div>Researcher<small>Individual workspace</small></div><LockKeyhole size={14} aria-hidden="true" /></div>
      </div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div className="breadcrumbs"><button type="button" className="icon-button mobile-menu" onClick={() => setNavOpen(v => !v)} aria-label="Toggle navigation" aria-expanded={navOpen} aria-controls="workspace-navigation">{navOpen ? <X size={19} /> : <Menu size={19} />}</button><span>Workspace</span><ChevronRight size={13} aria-hidden="true" /><strong>{pane}</strong></div>
        <div className="topbar-right"><span className="small muted"><span className={`connection-dot ${streamStatus === 'connected' ? 'active' : ''}`} />{running ? (streamStatus === 'connected' ? 'Live event stream' : 'Connecting stream') : 'Research workspace'}</span><span className="avatar" aria-hidden="true">KR</span></div></header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        {pane === 'Research' ? <>
          <div className="page-intro"><h1>Research</h1><button type="button" className="secondary-button" onClick={() => navigate('Run history')}><History size={16} aria-hidden="true" /> Past research</button></div>
          <section className="command-bar" aria-label="Research settings">
            <div className="stock-select field-label">Stock<StockSearch value={ticker} onChange={setTicker} disabled={running} /></div>
            <label>Risk preference<select value={risk} onChange={e => setRisk(e.target.value)} disabled={running}><option value="CONSERVATIVE">Conservative</option><option value="NEUTRAL">Balanced</option><option value="AGGRESSIVE">Aggressive</option></select></label>
            <p className="live-source-label"><Activity size={15} aria-hidden="true" /> Live data only. Fresh fetch every run.</p>
            <button type="button" className="primary-button" onClick={() => void start()} disabled={busy || running}>{busy || running ? <Loader2 className="spin" size={17} /> : <Play size={16} />} {running ? 'Analysis running' : 'Run analysis'}</button>
          </section>
          {error && <div className="alert error" role="alert"><AlertTriangle size={18} aria-hidden="true" /><div><strong>Analysis needs attention</strong><p>{error}</p></div></div>}

          {!run && <div className="decision-row"><EmptyDecision working={false} /><PriceCard ticker={ticker} data={chart} error={chartError} /></div>}
          {run && <>
            <RunBar run={run} d={d} elapsed={elapsed} />
            {streamStatus === 'reconnecting' && running && <p className="quiet-note warn" role="status"><AlertTriangle size={16} aria-hidden="true" /><span>Event stream interrupted. Reconnecting; the last known state is shown.</span></p>}
            {running && <div className="live-grid"><LivePipeline run={run} events={events} d={d} now={clock} draft={draft} />
              <aside className="panel live-log" aria-label="Live execution log"><div className="section-heading"><h2>Live log</h2></div><ExecutionLog events={events} limit={14} newestFirst showAssurance={false} /></aside></div>}
            {failed && <FailureCard run={run} d={d} onRetry={() => void start(run.ticker, run.risk)} busy={busy} />}
            {finished && !failed && <div className="decision-row"><DecisionCard run={run} onTrade={() => navigate('Paper trading')} /><PriceCard ticker={ticker} data={chart} error={chartError} /></div>}
            {finished && <>
              <PipelineStrip d={d} events={events} onOpen={openStep} />
              <Workbench run={run} events={events} d={d} tab={bench} setTab={setBench} report={report} setReport={setReport} />
            </>}
          </>}
        </>
        : pane === 'Paper trading' ? <PaperTrading key={run?.id || ticker} ticker={run?.ticker || ticker} tickers={tickers} proposal={run?.result?.trading_proposal} />
        : <RunHistory runs={runs} onOpen={id => { void selectRun(id); navigate('Research'); }} onRefresh={() => api('/runs').then(setRuns).catch(e => setError(e.message))} onStart={() => navigate('Research')} />}
        <footer className="workspace-footer"><span>Research signals are not guaranteed returns. Paper trading uses virtual funds.</span></footer>
      </main>
    </div>
  </div>;
}
