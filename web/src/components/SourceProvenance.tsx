import { useId, useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleDashed, CircleSlash, ChevronDown, ExternalLink, Database } from 'lucide-react';
import type { Data, RunEvent } from '../types';
const human = (s: string) => s.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
function safeUrl(url: unknown) { try { const u = new URL(String(url)); return ['https:', 'http:'].includes(u.protocol) ? u.href : undefined; } catch { return undefined; } }
const when = (v: unknown) => { if (!v) return undefined; const d = new Date(String(v)); return Number.isNaN(d.getTime()) ? String(v) : /[T ]\d/.test(String(v)) ? d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }); };
const states: Record<string, { label: string; tone: string; icon: typeof CheckCircle2; note: string }> = {
  ok: { label: 'Available', tone: 'green', icon: CheckCircle2, note: '' },
  empty: { label: 'Empty', tone: 'blue', icon: CircleDashed, note: 'Reached, nothing to report.' },
  unavailable: { label: 'Unavailable', tone: 'red', icon: AlertTriangle, note: 'Could not be reached.' },
  not_configured: { label: 'Not configured', tone: 'amber', icon: CircleSlash, note: 'Not set up on this server.' },
};
const methods: Record<string, string> = { oauth_search: 'Reddit API search', rss_search: 'Reddit RSS search', rss_subreddit_new: 'Subreddit new-posts RSS' };
function Status({ status }: { status: unknown }) {
  const s = states[String(status)] || { label: status ? human(String(status)) : 'Status not supplied', tone: 'neutral', icon: CircleDashed, note: '' }, Icon = s.icon;
  return <span className={`pill source-status ${s.tone}`}><Icon size={13} aria-hidden="true" />{s.label}</span>;
}
function Meta({ items }: { items: [string, unknown][] }) {
  const shown = items.filter(([, v]) => v !== undefined && v !== null && v !== '');
  return shown.length ? <dl className="source-meta">{shown.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl> : null;
}
function Link({ url }: { url: unknown }) { const href = safeUrl(url); return href ? <a className="source-link" href={href} target="_blank" rel="noreferrer">Open source <ExternalLink size={13} /></a> : url ? <span className="muted">Source link unavailable</span> : null; }
function SentimentSource({ s }: { s: Data }) {
  const [open, setOpen] = useState(false), attempts: Data[] = Array.isArray(s.attempts) ? s.attempts : [];
  const quiet = s.status === 'NO_RECENT_DISCUSSION', down = s.status === 'UNAVAILABLE', legacy = s.source === 'REDDIT_RSS' && !s.method;
  return <li className="source-row"><div className="source-head"><div><strong>Reddit discussion</strong><small>Sentiment analyst input</small></div>{down ? <Status status="unavailable" /> : quiet ? <span className="pill source-status amber"><CircleDashed size={13} aria-hidden="true" />No recent discussion</span> : <Status status="ok" />}</div>
    <Meta items={[['Method', legacy ? 'Reddit RSS (older run, method not recorded)' : methods[s.method] || (s.method && human(s.method))], ['Posts used', typeof s.posts === 'number' ? s.posts : undefined], ['Latest post', when(s.latest_post)]]} />
    {down && <p className="source-reason">Sentiment unavailable — Reddit unreachable. Sentiment was not assessed and is not treated as neutral. {s.reason}</p>}
    {quiet && <p className="source-reason">No recent posts were found, so the sentiment report is not backed by a retail-discussion sample.</p>}
    {attempts.length > 0 && <><button className="text-button" onClick={() => setOpen(!open)} aria-expanded={open}>Fetch attempts ({attempts.length}) <ChevronDown size={14} className={open ? 'rotated' : ''} /></button>{open && <ol className="source-attempts">{attempts.map((a, i) => <li key={i}><span>{methods[a.method] || human(String(a.method ?? 'Attempt'))}</span><span>{a.status ?? 'No status'}</span>{safeUrl(a.url) ? <a href={safeUrl(a.url)} target="_blank" rel="noreferrer">{String(a.url)}</a> : <span>{a.url ? 'Link unavailable' : ''}</span>}</li>)}</ol>}</>}
  </li>;
}
function Supplementary({ s }: { s: Data }) {
  const [open, setOpen] = useState(false), id = useId();
  return <li className="source-row"><div className="source-head"><div><strong>{s.name || (s.id ? human(String(s.id)) : 'Unnamed source')}</strong>{s.category && <small>{human(String(s.category))}</small>}</div><Status status={s.status} /></div>
    {(s.reason || states[String(s.status)]?.note) && <p className="source-reason">{s.reason || states[String(s.status)].note}</p>}
    <Meta items={[['As of', when(s.as_of)], ['Retrieved', when(s.retrieved_at)], ['Items', typeof s.item_count === 'number' ? s.item_count : undefined]]} />
    <div className="source-actions"><Link url={s.url} />{s.usage_note && <button className="text-button" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls={id}>How it is used <ChevronDown size={14} className={open ? 'rotated' : ''} /></button>}</div>
    {open && s.usage_note && <p id={id} className="source-usage">{String(s.usage_note)}</p>}
  </li>;
}
export default function SourceProvenance({ sources, events }: { sources?: Data; events: RunEvent[] }) {
  const sentiment = sources?.sentiment as Data | undefined, supplementary: Data[] = Array.isArray(sources?.supplementary) ? sources!.supplementary : [];
  const refreshed = events.filter(e => e.type === 'evidence-refreshed' && typeof e.payload.total === 'number').at(-1)?.payload;
  const okCount = supplementary.filter(s => s.status === 'ok').length;
  if (!sentiment && !supplementary.length) return <div className="report-pending"><Database size={32} /><h3>{refreshed ? `Supplementary sources: ${refreshed.available} of ${refreshed.total} available` : 'No source provenance recorded.'}</h3><p>{refreshed ? 'Per-source detail appears here when the run finishes.' : 'Source details appear here after a run completes. Runs saved before provenance was recorded do not have them.'}</p></div>;
  return <div className="source-provenance"><p className="source-summary">{supplementary.length ? `${okCount} of ${supplementary.length} supplementary sources returned data.` : 'No supplementary sources recorded for this run.'} Status shows what arrived, not whether it supports the recommendation.</p>
    <ul className="source-list">{sentiment && <SentimentSource s={sentiment} />}{supplementary.map((s, i) => <Supplementary key={String(s.id ?? i)} s={s} />)}</ul></div>;
}
