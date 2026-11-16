import type { Data } from '../types';

const IST = 'Asia/Kolkata';
const ISO = /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/;

export const currency = (value: unknown) =>
  typeof value === 'number'
    ? new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value)
    : '—';

/** Large rupee amounts in lakh crore / crore, as Indian readers expect. */
export function rupees(value: number) {
  const abs = Math.abs(value);
  if (abs >= 1e12) return `₹${(value / 1e12).toFixed(2)} lakh cr`;
  if (abs >= 1e7) return `₹${(value / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 0 })} cr`;
  return currency(value);
}

export const isIso = (value: unknown): value is string => typeof value === 'string' && ISO.test(value);

/** "17 Nov 2026, 12:53 IST" for epoch seconds or an ISO string; date-only strings omit the time. */
export function ist(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === '') return '—';
  const dateOnly = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(dateOnly ? value + 'T00:00:00+05:30' : value);
  if (Number.isNaN(date.getTime())) return String(value);
  const parts: Intl.DateTimeFormatOptions = { timeZone: IST, day: 'numeric', month: 'short', year: 'numeric' };
  if (dateOnly) return date.toLocaleDateString('en-GB', parts);
  return date.toLocaleString('en-GB', { ...parts, hour: '2-digit', minute: '2-digit', hour12: false }) + ' IST';
}

export const istTime = (seconds: number) =>
  new Date(seconds * 1000).toLocaleTimeString('en-GB', { timeZone: IST, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

/** 94 -> "1m 34s". */
export function duration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
}

export const human = (key: string) => {
  const text = key.replaceAll('_', ' ').trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
};

export function safeUrl(url: unknown) {
  try {
    const u = new URL(String(url));
    return ['https:', 'http:'].includes(u.protocol) ? u.href : undefined;
  } catch {
    return undefined;
  }
}

/** Turn stored failure text (often a Python repr) into a sentence a person can read. */
export function humanError(raw: unknown) {
  let text = String(raw ?? '').trim();
  if (!text) return 'The run stopped without a recorded reason.';
  const inner = text.match(/'text':\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')/);
  if (inner) text = text.replace(/\[\{[\s\S]*\}\]/, (inner[1] ?? inner[2]).replace(/\\'/g, "'"));
  text = text.replace(/^\*+\s*|\s*\*+$/g, '').replace(/Error calling tool '([^']+)':\s*/, 'Tool $1 failed: ');
  text = text.replace(/\bnan\b/gi, 'not-a-number').replace(/\s+/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const isMissing = (value: unknown) => value === null || value === undefined || value === '';

/** Tell a ratio from a plain number by name so 0.0764 reads "7.64%". */
export function formatField(key: string, value: unknown, context: Data = {}): string {
  if (isMissing(value)) return 'Not reported';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') {
    const inr = !context.reporting_currency || context.reporting_currency === 'INR';
    if (/_pct$|percent/.test(key)) return `${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}%`;
    if (/margin|ratio$|_rate$|yield|growth/.test(key) && Math.abs(value) <= 1.5) return `${(value * 100).toFixed(2)}%`;
    if (/_ms$/.test(key)) return `${Math.round(value).toLocaleString('en-IN')} ms`;
    if (/months?$/.test(key)) return `${value} months`;
    if (inr && /(price|level|stop_loss|target|high|low)$|^last_price/.test(key)) return currency(value);
    if (inr && !key.includes('_to_') && /revenue|income|assets|liabilities|cash_flow|debt$|equity$|market_cap/.test(key)) return rupees(value);
    return value.toLocaleString('en-IN', { maximumFractionDigits: 4 });
  }
  if (isIso(value)) return ist(value);
  if (typeof value === 'string' && /^[A-Z0-9_ ().:-]{4,}$/.test(value) && /[A-Z]{3}/.test(value)) return human(value.toLowerCase());
  return String(value);
}
