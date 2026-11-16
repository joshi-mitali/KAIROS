import { useState } from 'react';
import { ArrowRight, BarChart3, Database, Lock, Maximize2, Minimize2, ShieldCheck, TrendingDown, TrendingUp } from 'lucide-react';
import type { Data, Run } from '../types';
import { currency } from '../lib/format';

export const stockNames: Record<string, string> = { RELIANCE: 'Reliance Industries', TCS: 'Tata Consultancy Services', INFY: 'Infosys', HDFCBANK: 'HDFC Bank', ICICIBANK: 'ICICI Bank' };

export function Pill({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: string }) { return <span className={`pill ${tone}`}>{children}</span>; }

const firstSentence = (text: unknown) => String(text || '').split(/(?<=[.!?])\s/)[0];

export function DecisionCard({ run, onTrade }: { run: Run; onTrade: () => void }) {
  const proposal = run.result?.trading_proposal as Data | undefined, verdict = run.result?.verdict as Data | undefined;
  if (!proposal) return null;
  const direction = String(proposal.direction), hold = direction === 'HOLD';
  const reference = hold || proposal.levels_reference_only === true;
  const fallback = String(proposal.execution_mode).includes('FALLBACK');
  const tone = direction === 'BUY' ? 'buy' : direction === 'SELL' ? 'sell' : 'hold';
  return <section className="panel decision-card" aria-labelledby="decision-title">
    <div className="decision-head">
      <div><span className="eyebrow" id="decision-title">Decision · {run.ticker}</span>
        <p className="decision-direction"><span className={`direction ${tone}`}>{direction}</span><span className="decision-verdict">{verdict?.recommendation ? `Research verdict ${String(verdict.recommendation).toLowerCase()}` : ''}{verdict?.conviction ? `, ${String(verdict.conviction).toLowerCase()} conviction` : ''}</span></p></div>
      {fallback && <Pill tone="amber">Rule-based fallback</Pill>}
    </div>
    <p className="decision-why">{firstSentence(proposal.rationale)}</p>
    {verdict && <ul className="decision-sides">
      <li className="bull"><TrendingUp size={15} aria-hidden="true" /><span><strong>Bull</strong>{verdict.bull_summary}</span></li>
      <li className="bear"><TrendingDown size={15} aria-hidden="true" /><span><strong>Bear</strong>{verdict.bear_summary}</span></li>
    </ul>}
    <div className="levels" role="group" aria-label={reference ? 'Reference levels, no order' : 'Trade levels'}>
      <h3>{reference ? 'Reference levels (no order)' : 'Levels'}</h3>
      <div><span>Entry</span><strong>{currency(proposal.entry_price)}</strong></div>
      <div><span>Stop-loss</span><strong>{currency(proposal.stop_loss)}</strong></div>
      <div><span>Target</span><strong>{currency(proposal.target)}</strong></div>
    </div>
    <p className="decision-meta">{proposal.time_horizon && <span>Horizon {proposal.time_horizon}</span>}{!reference && typeof proposal.risk_reward_ratio === 'number' && <span>Risk / reward {proposal.risk_reward_ratio.toFixed(2)}:1</span>}<span>{fallback ? 'Rule-based fallback' : 'Model-generated'}</span></p>
    {hold
      ? <p className="no-order" role="status"><Lock size={15} aria-hidden="true" /> HOLD — no order to place</p>
      : <button type="button" className="primary-button full" onClick={onTrade}>Review paper order <ArrowRight size={16} /></button>}
    <p className="fine-print"><ShieldCheck size={13} aria-hidden="true" /> Conviction is an uncalibrated research signal, not a probability of profit. Paper orders need your separate approval.</p>
  </section>;
}

export function EmptyDecision({ working }: { working: boolean }) {
  return <section className="panel decision-card empty" aria-label="Decision">
    <span className="eyebrow">Decision</span>
    <h3>{working ? 'Evidence is taking shape' : 'A considered decision starts here.'}</h3>
    <p>{working ? 'The verdict and proposal appear once the debate and trader finish.' : 'Run an analysis to bring price action, fundamentals, news and sentiment into one explained proposal.'}</p>
    <p className="fine-print"><ShieldCheck size={13} aria-hidden="true" /> Research first. Paper orders need your separate approval.</p>
  </section>;
}

export function PriceCard({ ticker, data, error }: { ticker: string; data: Data | null; error: string }) {
  const [expanded, setExpanded] = useState(false);
  const points = (data?.points || []) as { date: string; close: number }[];
  const head = <div className="chart-title"><span className="stock-monogram">{ticker.slice(0, 2)}</span><div><h2>{stockNames[ticker] || ticker}</h2><span>{ticker} · {ticker.endsWith('.BO') ? 'BSE' : 'NSE'} · INR</span></div></div>;
  if (!points.length) return <section className="panel chart-card"><div className="chart-head">{head}</div><div className="chart-empty"><BarChart3 size={26} aria-hidden="true" /><p>{error || 'Live chart unavailable.'}</p><span>Retry when the market-data provider is available.</span></div></section>;
  const min = Math.min(...points.map(p => p.close)), max = Math.max(...points.map(p => p.close));
  const pad = (max - min) * .12 || 1, lo = min - pad, hi = max + pad;
  const coords = points.map((p, i) => `${12 + i / (points.length - 1 || 1) * 586},${14 + (hi - p.close) / (hi - lo) * 120}`);
  const last = points.at(-1)!, first = points[0], change = (last.close / first.close - 1) * 100;
  return <section className={`panel chart-card ${expanded ? 'expanded' : ''}`}>
    <div className="chart-head">{head}
      <div className="chart-price"><strong>{currency(last.close)}</strong><span className={change >= 0 ? 'positive' : 'negative'}>{change >= 0 ? <TrendingUp size={14} aria-hidden="true" /> : <TrendingDown size={14} aria-hidden="true" />} {change >= 0 ? '+' : ''}{change.toFixed(2)}% <small>over period</small></span></div>
    </div>
    <svg className="price-chart" viewBox="0 0 660 168" role="img" aria-label={`${data!.ticker} closing prices from ${first.date} to ${last.date}. Latest ${currency(last.close)}.`}>
      {[0, .5, 1].map(n => <g key={n}><line x1="12" x2="598" y1={14 + n * 120} y2={14 + n * 120} stroke="var(--line)" strokeDasharray="3 5" /><text x="610" y={18 + n * 120}>{Math.round(hi - (hi - lo) * n).toLocaleString('en-IN')}</text></g>)}
      <path d={`M${coords.join(' L')} L598 134 L12 134Z`} fill="var(--positive-soft)" />
      <polyline points={coords.join(' ')} fill="none" stroke="var(--positive)" strokeWidth="2.3" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      <circle className="last-dot" cx="598" cy={coords.at(-1)!.split(',')[1]} r="4" fill="var(--positive)" stroke="var(--surface)" strokeWidth="2" />
      {[0, .33, .66, 1].map(n => <text key={n} x={12 + n * 586} y="160" textAnchor={n === 0 ? 'start' : n === 1 ? 'end' : 'middle'}>{points[Math.round(n * (points.length - 1))].date.slice(5)}</text>)}
    </svg>
    <div className="chart-foot"><span><Database size={13} aria-hidden="true" /> Live-fetched through {data!.as_of} · {points.length} sessions</span>
      <button type="button" className="text-button chart-toggle" aria-pressed={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? <><Minimize2 size={13} aria-hidden="true" /> Hide price scale</> : <><Maximize2 size={13} aria-hidden="true" /> Show price scale</>}</button></div>
  </section>;
}
