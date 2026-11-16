import { useId, useState } from 'react';
import { ChevronDown, Database, ExternalLink } from 'lucide-react';
import type { Data } from '../types';
import type { Chip } from '../lib/run';
import { duration, human, ist, safeUrl } from '../lib/format';
import { sourceState } from './Pipeline';

type Row = { id: string; name: string; group: string; status: string; items?: number; asOf?: string; elapsedMs?: number; reason?: string; url?: unknown; usage?: string; attempts?: Data[]; method?: string };

const methods: Record<string, string> = { oauth_search: 'Reddit API search', rss_search: 'Reddit RSS search', rss_subreddit_new: 'Subreddit new-posts RSS' };
const SUMMARY_ORDER = ['empty', 'no_recent_discussion', 'unavailable', 'failed', 'not_configured'];

export function sourceRows(prov: Data | undefined, chips: Chip[]): Row[] {
  const src = prov?.sources as Data | undefined;
  if (!src) return chips.map(c => ({ id: c.id, name: c.name, group: c.group, status: c.state, items: c.items, elapsedMs: c.elapsedMs, reason: c.reason, asOf: c.asOf }));
  const rows: Row[] = [];
  if (src.fundamentals) rows.push({ id: 'fundamentals', name: 'Company financials', group: 'required', status: 'ok', asOf: src.fundamentals.fiscal_period_end, reason: human(String(src.fundamentals.source || '').toLowerCase()) });
  if (src.news) rows.push({ id: 'news', name: 'Company news', group: 'required', status: src.news.articles > 0 ? 'ok' : 'empty', items: src.news.articles, asOf: src.news.latest_publication, reason: human(String(src.news.source || '').toLowerCase()) });
  const s = src.sentiment as Data | undefined;
  if (s) {
    const raw = String(s.status || '').toLowerCase();
    rows.push({
      id: 'sentiment', name: 'Reddit discussion', group: 'sentiment',
      status: raw === 'unavailable' ? 'unavailable' : raw === 'no_recent_discussion' ? 'no_recent_discussion' : raw && raw !== 'ok' ? raw : s.posts === 0 ? 'no_recent_discussion' : 'ok',
      items: typeof s.posts === 'number' ? s.posts : undefined, asOf: s.latest_post, elapsedMs: s.elapsed_ms,
      reason: raw === 'unavailable' ? `Reddit unreachable. Sentiment was not assessed and is not treated as neutral. ${s.reason || ''}`.trim() : raw === 'no_recent_discussion' ? 'No recent posts, so sentiment is not backed by a retail-discussion sample.' : undefined,
      attempts: Array.isArray(s.attempts) ? s.attempts : undefined, method: s.method ? methods[s.method] || human(String(s.method)) : s.source === 'REDDIT_RSS' ? 'Reddit RSS (older run, method not recorded)' : undefined,
    });
  }
  for (const x of Array.isArray(src.supplementary) ? src.supplementary : []) rows.push({ id: String(x.id ?? x.name), name: x.name || human(String(x.id)), group: x.group || 'supplementary', status: String(x.status || 'unknown'), items: x.item_count, asOf: x.as_of, elapsedMs: x.elapsed_ms, reason: x.reason, url: x.url, usage: x.usage_note });
  return rows;
}

export function sourceSummary(rows: Row[]) {
  if (!rows.length) return '';
  const ok = rows.filter(r => r.status === 'ok').length;
  const extra = SUMMARY_ORDER.map(k => [k, rows.filter(r => r.status === k).length] as const).filter(([, n]) => n).map(([k, n]) => `${n} ${sourceState(k).label.toLowerCase()}`);
  return [`${ok} of ${rows.length} sources returned data`, ...extra].join(' · ');
}

function SourceRow({ row }: { row: Row }) {
  const [open, setOpen] = useState(false), id = useId(), s = sourceState(row.status);
  const meta = [row.items !== undefined && `${row.items} item${row.items === 1 ? '' : 's'}`, row.asOf && `as of ${ist(row.asOf)}`, row.elapsedMs !== undefined && duration(row.elapsedMs / 1000), row.method].filter(Boolean).join(' · ');
  const href = safeUrl(row.url);
  return <li className="source-row">
    <span className={`pill source-status ${s.tone}`}><s.Icon size={13} aria-hidden="true" />{s.label}</span>
    <div className="source-main"><strong>{row.name}</strong>{meta && <span className="source-meta">{meta}</span>}{row.reason && <span className="source-reason">{row.reason}</span>}</div>
    <div className="source-actions">
      {href && <a className="source-link" href={href} target="_blank" rel="noreferrer" aria-label={`Open ${row.name}`}><ExternalLink size={14} /></a>}
      {(row.usage || row.attempts?.length) && <button type="button" className="text-button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>{row.usage ? 'How it is used' : `Attempts (${row.attempts!.length})`} <ChevronDown size={13} className={open ? 'rotated' : ''} /></button>}
    </div>
    {open && <div id={id} className="source-more">
      {row.usage && <p>{row.usage}</p>}
      {row.attempts?.length ? <ol>{row.attempts.map((a, i) => <li key={i}><span>{methods[a.method] || human(String(a.method ?? 'Attempt'))}</span><span>{a.status ?? 'No status'}</span>{safeUrl(a.url) && <a href={safeUrl(a.url)} target="_blank" rel="noreferrer">{String(a.url)}</a>}</li>)}</ol> : null}
    </div>}
  </li>;
}

export default function SourceProvenance({ rows, retrievedAt }: { rows: Row[]; retrievedAt?: string }) {
  if (!rows.length) return <div className="report-pending"><Database size={30} /><h3>No source detail recorded.</h3><p>Runs saved before provenance was recorded do not have it.</p></div>;
  const groups: [string, string][] = [['required', 'Required'], ['sentiment', 'Sentiment'], ['supplementary', 'Supplementary']];
  return <div className="source-provenance">
    <p className="source-summary"><strong>{sourceSummary(rows)}</strong>{retrievedAt ? ` · Retrieved ${ist(retrievedAt)}` : ''}. Status shows what arrived, not whether it supports the recommendation.</p>
    {groups.map(([g, title]) => { const list = rows.filter(r => r.group === g || (!groups.some(x => x[0] === r.group) && g === 'supplementary')); return list.length ? <section key={g}><h4>{title}</h4><ul className="source-list">{list.map(r => <SourceRow key={r.id} row={r} />)}</ul></section> : null; })}
  </div>;
}
