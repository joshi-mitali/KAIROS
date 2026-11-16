import { ExternalLink, TrendingDown, TrendingUp } from 'lucide-react';
import type { ReactNode } from 'react';
import type { Data } from '../types';
import { formatField, human, isIso, isMissing, ist, safeUrl } from '../lib/format';

/** Fields shown in the header or too technical for a reader; they remain in the raw data. */
const HIDDEN = new Set(['ticker', 'trace_id', 'analyst_name', 'researcher_name', 'manager_name', 'execution_mode', 'generated_at', 'generation_timestamp', 'deliberation_timestamp', 'debate_round', 'disclaimer', 'research_only_disclaimer', 'status']);
const LABELS: Record<string, string> = {
  primary_arguments: 'Primary arguments', counter_arguments: 'Responses to the other side', rebuttals: 'Responses to the other side', acknowledged_risks: 'Risks it acknowledges',
  catalysts: 'Catalysts', vulnerabilities: 'Vulnerabilities', trigger_events: 'What would trigger the downside', key_decision_factors: 'What decided it', limitations: 'Limitations',
  source_references: 'Evidence considered', key_observations: 'Key observations', key_themes: 'Key themes', key_catalysts: 'Catalysts', regulatory_and_litigation_risks: 'Regulatory and legal risks',
  risk_warnings: 'Risk warnings', top_verified_articles: 'Source articles', conviction_level: 'Conviction', sma_20: '20-day average', rsi_14: 'RSI (14)', macd_line: 'MACD line',
  macd_signal: 'MACD signal', macd_histogram: 'MACD histogram', fifty_two_week_high: '52-week high', fifty_two_week_low: '52-week low', as_of_date: 'Data as of', bars_analyzed: 'Price bars analysed',
  sample_size_posts: 'Posts sampled', stop_loss: 'Stop-loss', entry_price: 'Entry', layman_summary: 'In plain words', total_articles_verified: 'Articles verified',
};
const label = (key: string) => LABELS[key] || human(key);

/** Where each agent's own story starts; everything else follows in the generic order. */
const LEAD: Record<string, string[]> = {
  bull: ['primary_arguments', 'counter_arguments', 'rebuttals', 'catalysts', 'acknowledged_risks'],
  bear: ['primary_arguments', 'counter_arguments', 'rebuttals', 'vulnerabilities', 'trigger_events'],
  manager: ['synthesis_rationale', 'key_decision_factors', 'bull_summary', 'bear_summary', 'limitations'],
  trader: ['rationale', 'risk_warnings'],
};

function Scalar({ k, v, context }: { k: string; v: unknown; context: Data }) {
  return isMissing(v) ? <span className="muted">Not reported</span> : <>{formatField(k, v, context)}</>;
}

function Bullets({ items }: { items: unknown[] }) {
  return <ul className="out-bullets">{items.map((item, i) => <li key={i}>{typeof item === 'object' && item ? <Nested data={item as Data} /> : isIso(item) ? ist(item) : String(item)}</li>)}</ul>;
}

function Article({ a }: { a: Data }) {
  const href = safeUrl(a.url);
  return <article className="out-article">
    <div><span className="muted">{[a.source, a.published_at && ist(a.published_at)].filter(Boolean).join(' · ')}</span><h5>{a.headline}</h5>{a.summary && <p>{a.summary}</p>}</div>
    {href ? <a href={href} target="_blank" rel="noreferrer">Read source <ExternalLink size={13} /></a> : <span className="muted">No link</span>}
  </article>;
}

function Nested({ data }: { data: Data }) {
  const entries = Object.entries(data).filter(([, v]) => !isMissing(v));
  return <dl className="out-nested">{entries.map(([k, v]) => <div key={k}><dt>{label(k)}</dt><dd>{typeof v === 'object' ? <Nested data={v as Data} /> : <Scalar k={k} v={v} context={data} />}</dd></div>)}</dl>;
}

function Field({ k, v, context }: { k: string; v: unknown; context: Data }) {
  if (Array.isArray(v)) {
    if (!v.length) return null;
    if (k === 'top_verified_articles' || v.every(i => i && typeof i === 'object' && 'headline' in i)) return <section className="out-section"><h4>{label(k)}</h4>{v.map((a, i) => <Article key={i} a={a as Data} />)}</section>;
    return <section className="out-section"><h4>{label(k)}</h4><Bullets items={v} /></section>;
  }
  if (v && typeof v === 'object') return <section className="out-section"><h4>{label(k)}</h4><Nested data={v as Data} /></section>;
  return <section className="out-section"><h4>{label(k)}</h4><p><Scalar k={k} v={v} context={context} /></p></section>;
}

/** Headline figures that matter most for each kind of agent. */
function Lead({ kind, data }: { kind: string; data: Data }) {
  const tone = (n: number | undefined) => (typeof n === 'number' ? `${n.toLocaleString('en-IN', { maximumFractionDigits: 1 })}%` : 'Not estimated');
  if (kind === 'bull' || kind === 'bear') {
    const up = kind === 'bull', pct = up ? data.upside_potential_pct : data.downside_risk_pct;
    return <div className={`out-lead ${kind}`}>{up ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
      <div><strong>{up ? 'Upside' : 'Downside'} {tone(pct)}</strong><span>{data.target_horizon_months ? `over ${data.target_horizon_months} months` : 'Horizon not stated'}{data.conviction_level ? ` · ${String(data.conviction_level).toLowerCase()} conviction` : ''}</span></div></div>;
  }
  if (kind === 'manager') return <div className="out-lead manager"><div><strong>{data.recommendation || 'No recommendation'}</strong><span>{data.conviction ? `${String(data.conviction).toLowerCase()} conviction` : 'Conviction not stated'}{data.debate_rounds ? ` · ${data.debate_rounds} debate rounds` : ''}</span></div></div>;
  return null;
}

const LEAD_HIDDEN: Record<string, string[]> = {
  bull: ['upside_potential_pct', 'target_horizon_months', 'conviction_level'],
  bear: ['downside_risk_pct', 'target_horizon_months', 'conviction_level'],
  manager: ['recommendation', 'conviction', 'debate_rounds'],
};

export default function AgentOutput({ kind, data, raw = true, omit = [] }: { kind: string; data?: Data; raw?: boolean; omit?: string[] }) {
  if (!data || typeof data !== 'object') return <p className="muted">No output recorded for this agent yet.</p>;
  const skip = new Set([...omit, ...HIDDEN, ...(LEAD_HIDDEN[kind] || [])]);
  const entries = Object.entries(data).filter(([k]) => !skip.has(k));
  const lead = LEAD[kind] || [];
  const ordered = [...lead.map(k => entries.find(([key]) => key === k)).filter(Boolean) as [string, unknown][], ...entries.filter(([k]) => !lead.includes(k))];
  const isShort = (v: unknown) => typeof v !== 'object' && !(typeof v === 'string' && v.length > 70);
  const scalars = ordered.filter(([, v]) => isShort(v) || v === null);
  const rest = ordered.filter(([, v]) => !(isShort(v) || v === null));
  const metrics = kind === 'trader' ? scalars.filter(([k]) => !['entry_price', 'stop_loss', 'target', 'direction'].includes(k)) : scalars;
  const stamp = data.generated_at || data.generation_timestamp;
  return <div className="agent-output">
    {(data.execution_mode || stamp) && <p className="out-meta">{String(data.execution_mode || '').includes('FALLBACK') ? 'Rule-based fallback' : data.execution_mode ? 'Model-generated' : ''}{stamp ? `${data.execution_mode ? ' · ' : ''}Generated ${ist(stamp)}` : ''}</p>}
    <Lead kind={kind} data={data} />
    {kind === 'trader' && <div className="out-levels">{(['entry_price', 'stop_loss', 'target'] as const).map(k => <div key={k}><span>{label(k)}</span><strong>{formatField(k, data[k])}</strong></div>)}</div>}
    {metrics.length > 0 && <dl className="out-metrics">{metrics.map(([k, v]) => <div key={k}><dt>{label(k)}</dt><dd><Scalar k={k} v={v} context={data} /></dd></div>)}</dl>}
    {rest.map(([k, v]) => <Field key={k} k={k} v={v} context={data} />)}
    {raw && <RawData data={data} />}
  </div>;
}

export function RawData({ data, children }: { data: unknown; children?: ReactNode }) {
  return <details className="raw-data"><summary>Show raw data</summary>{children}<pre>{JSON.stringify(data, null, 2)}</pre></details>;
}
