"""Self-contained HTML research report for one stored run (inline CSS + inline SVG, no scripts, no network).

Only data stored for the run is used: the run result, its events and its evidence directory.
Everything is escaped by Jinja autoescape; SVG helpers escape their own text via `esc`.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from html import escape as esc
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from jinja2 import Environment
from markupsafe import Markup

INK, MUTED, LINE, BLUE, POS, NEG, WARN = "#172945", "#596b83", "#e1e7f0", "#294e96", "#167357", "#b43847", "#94610f"
IST = timezone(timedelta(hours=5, minutes=30))
NA = "Not recorded for this run"
AGENTS = {  # event agent name -> result section
    "google_adk.market_analyst": "market", "google_adk.sentiment_analyst": "sentiment",
    "google_adk.news_analyst": "news", "google_adk.fundamentals_analyst": "fundamentals"}
LEVEL = {"WEAK": 1, "MODERATE": 2, "STRONG": 3}


# ---------- formatting helpers ----------
def safe_url(value):
    parsed = urlparse(str(value or "").strip())
    return str(value).strip() if parsed.scheme in ("http", "https") and parsed.netloc else ""


def label(key):
    return str(key).replace("_", " ").capitalize()


def fmt(value):
    if value is None:
        return NA
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4f}"
    return str(value)


def when(value):
    """Epoch seconds or ISO string -> 'UTC / IST' text."""
    try:
        dt = datetime.fromtimestamp(value, timezone.utc) if isinstance(value, (int, float)) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OSError):
        return NA if value in (None, "") else str(value)
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return f"{dt:%Y-%m-%d %H:%M} UTC / {dt.astimezone(IST):%Y-%m-%d %H:%M} IST"


# ---------- SVG helpers ----------
def _svg(title, desc, w, h, body):
    return Markup(f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="t d" xmlns="http://www.w3.org/2000/svg">'
                  f'<title id="t">{esc(title)}</title><desc id="d">{esc(desc)}</desc>{body}</svg>')


def _text(x, y, s, size=10, fill=MUTED, anchor="start", weight=400):
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{esc(str(s))}</text>'


def _ticks(lo, hi, n=5):
    step = (hi - lo) / n or 1
    return [lo + step * i for i in range(n + 1)]


def _axes(w, h, left, right, top, bottom, lo, hi, ylabel, xlabel, ytick=lambda v: f"{v:,.0f}", yticks=None):
    """Frame, horizontal grid + y labels, axis titles. Returns (svg, y(v) mapper)."""
    y = lambda v: top + (hi - v) / ((hi - lo) or 1) * (h - top - bottom)
    out = []
    for v in yticks or _ticks(lo, hi):
        yy = y(v)
        out.append(f'<line x1="{left}" x2="{w - right}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="{LINE}"/>' + _text(left - 6, yy + 3, ytick(v) if not yticks else yticks[v], anchor="end"))
    out.append(_text(12, (top + h - bottom) / 2, ylabel, anchor="middle").replace("<text", f'<text transform="rotate(-90 12 {(top + h - bottom) / 2:.1f})"', 1))
    out.append(_text((left + w - right) / 2, h - 6, xlabel, anchor="middle"))
    return "".join(out), y


def line_chart(title, desc, labels, series, hlines, ylabel, xlabel):
    """series: [(name, values-with-None, color, dash)], hlines: [(name, value, color)]."""
    w, h, left, right, top, bottom = 720, 280, 58, 16, 26, 40
    values = [v for _, ys, _, _ in series for v in ys if v is not None] + [v for _, v, _ in hlines]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * .05 or 1
    frame, y = _axes(w, h, left, right, top, bottom, lo - pad, hi + pad, ylabel, xlabel)
    n = max(len(labels) - 1, 1)
    x = lambda i: left + i / n * (w - left - right)
    body = [frame]
    for i in sorted({round(k * n / 5) for k in range(6)}):
        body.append(_text(x(i), h - bottom + 14, labels[i], anchor="end" if i == n else "start" if i == 0 else "middle"))
    for name, ys, color, dash in series:
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(ys) if v is not None)
        body.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6"' + (f' stroke-dasharray="{dash}"' if dash else "") + "/>")
    for name, v, color in hlines:
        body.append(f'<line x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{color}" stroke-dasharray="6 3"/>' + _text(w - right - 2, y(v) - 3, f"{name} {v:,.2f}", 10, color, "end", 700))
    for k, (name, _, color, _) in enumerate(series):
        body.append(f'<rect x="{left + k * 110}" y="8" width="10" height="3" fill="{color}"/>' + _text(left + k * 110 + 14, 13, name))
    return _svg(title, desc, w, h, "".join(body))


def bar_chart(title, desc, bars, ylabel, xlabel, ytick=lambda v: f"{v:,.0f}", yticks=None, vfmt=None):
    """bars: [(label, value, color)]; negative values drop below the zero line."""
    w, h, left, right, top, bottom = 720, 260, 58, 16, 16, 52
    vals = [v for _, v, _ in bars]
    lo, hi = min(0, min(vals)), max(0, max(vals))
    hi = hi * 1.12 or 1
    frame, y = _axes(w, h, left, right, top, bottom, lo, hi, ylabel, xlabel, ytick, yticks)
    slot = (w - left - right) / len(bars)
    body = [frame]
    for i, (name, v, color) in enumerate(bars):
        bx, top_y, base = left + i * slot + slot * .2, y(max(v, 0)), y(0)
        body.append(f'<rect x="{bx:.1f}" y="{top_y:.1f}" width="{slot * .6:.1f}" height="{max(abs(y(v) - base), 1):.1f}" fill="{color}" rx="2"/>')
        body.append(_text(bx + slot * .3, (top_y if v >= 0 else y(v)) + (-4 if v >= 0 else 12), (vfmt or fmt)(v), 10, INK, "middle", 700))
        body.append(_text(bx + slot * .3, h - bottom + 14, name, 10, MUTED, "middle"))
    return _svg(title, desc, w, h, "".join(body))


def timeline(title, desc, items, xlabel):
    """items: [(label, start_s, end_s, color)] in seconds from run start."""
    row, left, right, top = 22, 230, 70, 8
    w, h = 720, top + row * len(items) + 40
    total = max(e for _, _, e, _ in items) or 1
    x = lambda s: left + s / total * (w - left - right)
    body = []
    for v in _ticks(0, total):
        body.append(f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{top}" y2="{h - 32}" stroke="{LINE}"/>' + _text(x(v), h - 20, f"{v:.0f}s", anchor="middle"))
    body.append(_text((left + w - right) / 2, h - 6, xlabel, anchor="middle"))
    for i, (name, s, e, color) in enumerate(items):
        yy = top + i * row
        body.append(_text(left - 8, yy + 14, name[:38], 10, INK, "end"))
        body.append(f'<rect x="{x(s):.1f}" y="{yy + 3}" width="{max(x(e) - x(s), 2):.1f}" height="15" fill="{color}" rx="2"/>')
        body.append(_text(x(e) + 4, yy + 14, f"{e - s:.1f}s", 10))
    return _svg(title, desc, w, h, "".join(body))


# ---------- data assembly ----------
def _parquet(directory, domain):
    for path in sorted((directory / "processed" / domain).glob("*.parquet")) if (directory / "processed" / domain).is_dir() else []:
        try:
            return pd.read_parquet(path).astype(object).where(lambda f: f.notna(), None).to_dict("records")
        except Exception:
            return []
    return None  # directory/file not recorded


def _stages(events):
    """Pair start/end events into (label, start, end, color) seconds-from-run-start."""
    if not events:
        return []
    t0, last = events[0]["created"], events[-1]["created"]
    out, seen = [], {}
    for i, ev in enumerate(events):
        kind, p = ev["type"], ev["payload"]
        if kind == "evidence-refresh-started":
            end = next((e for e in events[i + 1:] if e["type"] in ("evidence-refreshed", "evidence-unavailable", "evidence-refresh-started")), None)
            name = (end["payload"].get("source") if end and end["type"] != "evidence-refresh-started" else None) or p.get("source", "Evidence")
            out.append(("Evidence: " + name, ev["created"], end["created"] if end else last, BLUE if end and end["type"] == "evidence-refreshed" else WARN))
        elif kind == "agent-started":
            agent = p.get("agent", "agent")
            end = next((e for e in events[i + 1:] if e["payload"].get("agent") == agent and e["type"] in ("agent-completed", "agent-failed", "debate-argument")
                        or agent == "crewai.research_crew" and e["type"] == "debate-completed"), None)
            seen[agent] = seen.get(agent, 0) + 1
            name = agent.removeprefix("google_adk.").removeprefix("crewai.").removeprefix("Institutional ").replace("_", " ")
            out.append((name + (f" #{seen[agent]}" if agent.startswith("Institutional") else ""), ev["created"], end["created"] if end else last, NEG if end and end["type"] == "agent-failed" or not end else POS))
    return [(n, s - t0, e - t0, c) for n, s, e, c in out]


def collect(run, events, directory):
    """Everything the template needs, taken only from stored data."""
    result = run.get("result") or {}
    reports = dict(result.get("analyst_reports") or {})
    verdict, proposal = result.get("verdict"), result.get("trading_proposal")
    rounds, guards = None, []
    for ev in events:  # a failed run has no result row: rebuild what completed from its events
        p = ev["payload"]
        if ev["type"] == "agent-completed" and isinstance(p.get("report"), dict):
            if p.get("agent") in AGENTS:
                reports.setdefault(AGENTS[p["agent"]], p["report"])
            elif p.get("agent") == "trader_agent":
                proposal = proposal or p["report"]
            elif p.get("agent") == "crewai.research_manager":
                verdict = verdict or p["report"]
        elif ev["type"] == "debate-completed":
            rounds = p.get("rounds")
        elif ev["type"] == "guardrail-result":
            guards.append(p.get("result") or {})
    provenance = result.get("provenance")
    if provenance is None and (directory / "provenance.json").exists():
        provenance = json.loads((directory / "provenance.json").read_text())
    sources = (provenance or {}).get("sources", {})
    fund_rows = _parquet(directory, "fundamentals")
    return {"run": run, "result": result, "reports": reports, "verdict": verdict, "proposal": proposal, "rounds": rounds, "guards": guards,
            "provenance": provenance, "sources": sources, "stages": _stages(events),
            "news": _parquet(directory, "news") or [], "posts": _parquet(directory, "reddit") or [],
            "supp_items": _parquet(directory, "supplementary") or [], "prices": _parquet(directory, "market"),
            "fund": reports.get("fundamentals") or (fund_rows[0] if fund_rows else None)}


def charts(d):
    """Return dict of name -> (svg Markup or None, caption/placeholder)."""
    out, prop, sources = {}, d["proposal"] or {}, d["sources"]
    # a. price
    prices = d["prices"]
    if prices:
        asof = prices[-1]["date"]
        hl = [(n, prop[k], c) for n, k, c in (("Entry", "entry_price", BLUE), ("Stop", "stop_loss", NEG), ("Target", "target", POS)) if prop.get(k)]
        out["price"] = (line_chart(f"{d['run']['ticker']} daily close", f"Closing price through {asof} with 20 and 50 day averages and the trader's entry, stop and target.",
                                   [r["date"] for r in prices],
                                   [("Close", [r["close"] for r in prices], INK, ""), ("SMA 20", [r.get("sma_20") for r in prices], BLUE, ""), ("SMA 50", [r.get("sma_50") for r in prices], WARN, "4 2")],
                                   hl, "Price (INR)", "Date"), f"Source: Yahoo Finance daily bars (last {len(prices)}) seen by the market analyst; as of {asof}.")
    else:
        out["price"] = (None, "Price history not recorded for this run")
    # b. fundamentals
    f = d["fund"]
    if f:
        keys = [("Revenue", "revenue", BLUE), ("Net income", "net_income", POS), ("Operating cash flow", "operating_cash_flow", BLUE), ("Total assets", "total_assets", MUTED), ("Total liabilities", "total_liabilities", WARN)]
        keys = [k for k in keys if isinstance(f.get(k[1]), (int, float))]
        cur = f.get("reporting_currency") or f.get("currency") or "currency not recorded"
        scale, unit = next(((s, u) for s, u in ((1e12, "trillion"), (1e9, "billion")) if max(abs(f[k[1]]) for k in keys) >= s), (1, ""))
        if keys:
            out["fund"] = (bar_chart("Reported financials", f"Revenue, net income, operating cash flow, assets and liabilities for the period ending {f.get('fiscal_period_end')}.",
                                     [(n, f[k] / scale, c) for n, k, c in keys], f"{cur} {unit}".strip(), "Measure", ytick=lambda v: f"{v:,.1f}", vfmt=lambda v: f"{v:,.2f}"),
                           f"Source: {d['sources'].get('fundamentals', {}).get('source', 'Yahoo Finance reported financials')}; fiscal period ending {f.get('fiscal_period_end', 'not recorded')}; currency {cur}.")
    out.setdefault("fund", (None, NA))
    # c. sentiment
    posts, s = d["posts"], sources.get("sentiment")
    if posts:
        counts = {k: sum(p.get("sentiment_label") == k for p in posts) for k in ("POSITIVE", "NEUTRAL", "NEGATIVE")}
        out["sent"] = (bar_chart("Reddit post sentiment", f"{len(posts)} posts: " + ", ".join(f"{v} {k.lower()}" for k, v in counts.items()),
                                 [(k.capitalize(), v, c) for (k, v), c in zip(counts.items(), (POS, MUTED, NEG))], "Posts", "Sentiment label",
                                 ytick=lambda v: f"{v:.0f}"), f"Source: Reddit public feeds ({s.get('method', 'method not recorded')}); latest post {s.get('latest_post') or 'not recorded'}.")
    elif s and s.get("status") == "UNAVAILABLE":
        out["sent"] = (None, "Sentiment unavailable — Reddit unreachable. " + str(s.get("reason") or ""))
    elif s and s.get("status") == "NO_RECENT_DISCUSSION":
        out["sent"] = (None, "No recent discussion about this stock on Reddit in the last 7 days.")
    else:
        out["sent"] = (None, NA)
    # d. debate
    rounds = d["rounds"]
    if rounds:
        bars = []
        for r in rounds:
            for side, key, c in (("Bull", "bull_argument", POS), ("Bear", "bear_counterargument", NEG)):
                lvl = LEVEL.get(str((r.get(key) or {}).get("conviction_level", "")).upper())
                if lvl:
                    bars.append((f"R{r.get('round')} {side}", lvl, c))
        out["debate"] = (bar_chart("Debate conviction by round", "Bull and bear self-reported conviction level for each round (1 weak, 2 moderate, 3 strong).", bars, "Conviction", "Round and side",
                                   yticks={0: "", 1: "Weak", 2: "Moderate", 3: "Strong"}, vfmt=lambda v: {1: "Weak", 2: "Moderate", 3: "Strong"}[v]) if bars else None,
                         "Source: CrewAI bull/bear researchers; levels are model-stated, not calibrated." if bars else NA)
    else:
        out["debate"] = (None, NA)
    # e. timeline
    st = d["stages"]
    out["timeline"] = (timeline("Agent timeline", "Start and end of each evidence step and agent, in seconds from run start.", st, "Seconds since run start"), "Source: stored run events (server timestamps).") if st else (None, NA)
    # f. supplementary
    sup = sources.get("supplementary")
    if sup:
        order = ["ok", "empty", "unavailable", "not_configured"]
        counts = {k: sum(x.get("status") == k for x in sup) for k in order}
        extra = sum(counts.values()) != len(sup)
        bars = [(k.replace("_", " "), v, {"ok": POS, "empty": MUTED, "unavailable": NEG, "not_configured": WARN}[k]) for k, v in counts.items()]
        out["supp"] = (bar_chart("Supplementary source status", f"{len(sup)} sources: " + ", ".join(f"{v} {k}" for k, v in counts.items()), bars, "Sources", "Status", ytick=lambda v: f"{v:.0f}"),
                       f"Source: per-run provenance; retrieved {when((d['provenance'] or {}).get('retrieved_at'))}." + (" Some sources carry a status outside these four." if extra else ""))
    else:
        out["supp"] = (None, NA)
    return out


# ---------- template ----------
CSS = """
:root{--ink:#172945;--muted:#596b83;--line:#e1e7f0;--blue:#294e96;--shell:#192d53;--pos:#167357;--neg:#b43847;--warn:#94610f;--canvas:#f3f6fb;--soft:#eef3fc}
*{box-sizing:border-box}html{color-scheme:light;print-color-adjust:exact;-webkit-print-color-adjust:exact}
body{margin:0;background:var(--canvas);color:var(--ink);font:13px/1.7 Manrope,"Segoe UI",system-ui,sans-serif}
main{max-width:900px;margin:0 auto;background:#fff;padding:0 32px 32px}
header.cover{background:var(--shell);color:#fff;margin:0 -32px 24px;padding:28px 32px}
.brand{letter-spacing:.2em;font-weight:750;font-size:12px;color:#bbc9e0}h1{font-size:30px;line-height:1.3;letter-spacing:-.03em;margin:6px 0}
header.cover p{margin:2px 0;color:#bbc9e0}h2{font-size:18px;letter-spacing:-.02em;margin:30px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--blue)}
h3{font-size:14px;margin:18px 0 6px}section{break-inside:auto}.chart,.card,table,li{break-inside:avoid}
.notice{border:1px solid var(--line);background:var(--soft);border-radius:8px;padding:8px 12px;margin:10px 0;font-size:12px}
.notice.bad{background:#fbedef;border-color:var(--neg);color:#9f3043}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.tile{border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:11px;color:var(--muted);font-weight:700}.tile span{font-size:17px;font-weight:750}
table{border-collapse:collapse;width:100%;margin:6px 0;font-size:12px}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
table.kv th{width:30%;color:var(--muted);font-weight:700}table.kv table{margin:0}thead th{background:var(--soft)}
figure.chart{margin:14px 0;border:1px solid var(--line);border-radius:10px;padding:10px}.chart svg{width:100%;height:auto;display:block}
figcaption{font-size:11px;color:var(--muted)}.na,.empty{color:var(--muted);font-style:italic}.empty{border:1px dashed var(--line);border-radius:10px;padding:14px;margin:10px 0}
.pos{color:var(--pos);font-weight:700}.neg{color:var(--neg);font-weight:700}.warn{color:var(--warn);font-weight:700}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}.card{border:1px solid var(--line);border-radius:10px;padding:8px 14px}
ul{margin:4px 0;padding-left:18px}a{color:var(--blue);overflow-wrap:anywhere}.meta{color:var(--muted);font-size:11px}
.turn{border-left:3px solid var(--line);padding:2px 12px;margin:10px 0}.turn.bull{border-color:var(--pos)}.turn.bear{border-color:var(--neg)}
@media print{@page{size:A4;margin:14mm}body{background:#fff;font-size:11px}main{max-width:none;padding:0}header.cover{margin:0 0 16px}h2{break-after:avoid}h3{break-after:avoid}
h2.pb{break-before:page}.tiles{grid-template-columns:repeat(4,1fr)}tr{break-inside:avoid}}
@media(max-width:700px){.tiles,.cols{grid-template-columns:1fr 1fr}main{padding:0 16px 24px}header.cover{margin:0 -16px 20px;padding:20px 16px}}
"""

TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KAIROS research report: {{ run.ticker }}</title><style>{{ css }}</style></head><body><main>
{% macro val(v) -%}
{%- if v is none %}<span class="na">{{ na }}</span>
{%- elif v is mapping %}<table class="kv">{% for k, x in v.items() %}<tr><th>{{ k|label }}</th><td>{{ val(x) }}</td></tr>{% endfor %}</table>
{%- elif v is string %}{% if v|safe_url %}<a href="{{ v|safe_url }}" rel="noopener noreferrer" target="_blank">{{ v }}</a>{% else %}{{ v }}{% endif %}
{%- elif v is iterable %}{% if not v %}<span class="na">None</span>{% else %}<ul>{% for x in v %}<li>{{ val(x) }}</li>{% endfor %}</ul>{% endif %}
{%- else %}{{ v|fmt }}{% endif %}
{%- endmacro %}
{% macro fig(c) -%}{% if c[0] %}<figure class="chart">{{ c[0] }}<figcaption>{{ c[1] }}</figcaption></figure>{% else %}<div class="empty">{{ c[1] }}</div>{% endif %}{%- endmacro %}
{% macro link(url, text) -%}{% if url|safe_url %}<a href="{{ url|safe_url }}" rel="noopener noreferrer" target="_blank">{{ text or url }}</a>{% else %}{{ text or url or na }}{% endif %}{%- endmacro %}
{% macro report(name, key, skip=()) %}<h3>{{ name }}</h3>{% set r = reports.get(key) %}{% if r %}
<p class="meta">Generated {{ (r.generated_at or none)|when }} &middot; as of {{ r.as_of_date or r.fiscal_period_end or na }} &middot; {{ r.analyst_name or '' }} &middot; mode {{ r.execution_mode or na }}</p>
<table class="kv">{% for k, x in r.items() if k not in ('ticker', 'analyst_name', 'generated_at') %}<tr><th>{{ k|label }}</th><td>{{ val(x) }}</td></tr>{% endfor %}</table>
{% else %}<div class="empty">{{ na }}</div>{% endif %}{% endmacro %}

<header class="cover"><div class="brand">KAIROS &middot; EVIDENCE ATLAS</div>
<h1>{{ run.ticker }}{% if company %} &mdash; {{ company }}{% endif %}</h1>
<p>Research report &middot; run {{ run.id }} &middot; risk preference {{ run.risk }} &middot; source {{ run.source }}</p>
<p>Created {{ run.created|when }}{% if finished %} &middot; Finished {{ finished|when }}{% endif %}</p>
<p>Status <b>{{ run.status }}</b> &middot; Execution modes: {{ modes|join(', ') or na }}</p></header>
<div class="notice"><b>Paper-research only &mdash; not investment advice.</b> Conviction is an uncalibrated research signal. No order was placed.</div>
{% if run.status != 'COMPLETED' %}<div class="notice bad"><b>This run did not complete ({{ run.status }}).</b> {{ run.error or na }}<br>
This report shows only what was recorded before it stopped; missing sections say so.</div>{% endif %}

<h2>1. Executive summary</h2>
{% if verdict or proposal %}<div class="tiles">
<div class="tile"><b>Verdict</b><span>{{ (verdict or {}).get('recommendation') or na }}</span></div>
<div class="tile"><b>Conviction</b><span>{{ (verdict or {}).get('conviction') or na }}</span></div>
<div class="tile"><b>Trader direction</b><span>{{ (proposal or {}).get('direction') or na }}</span></div>
<div class="tile"><b>Time horizon</b><span>{{ (proposal or {}).get('time_horizon') or na }}</span></div>
<div class="tile"><b>Entry</b><span>{{ (proposal or {}).get('entry_price')|fmt }}</span></div>
<div class="tile"><b>Stop</b><span class="neg">{{ (proposal or {}).get('stop_loss')|fmt }}</span></div>
<div class="tile"><b>Target</b><span class="pos">{{ (proposal or {}).get('target')|fmt }}</span></div>
<div class="tile"><b>Risk / reward</b><span>{{ (proposal or {}).get('risk_reward_ratio')|fmt }}</span></div></div>
{% if proposal and proposal.rationale %}<h3>Trader rationale</h3><p>{{ proposal.rationale }}</p>{% endif %}
{% if verdict %}<h3>Manager rationale</h3><p>{{ verdict.synthesis_rationale or na }}</p>
<div class="cols"><div class="card"><h3 class="pos">Bull case</h3><p>{{ verdict.bull_summary or na }}</p></div><div class="card"><h3 class="neg">Bear case</h3><p>{{ verdict.bear_summary or na }}</p></div></div>
{% if verdict.key_decision_factors %}<h3>Key decision factors</h3>{{ val(verdict.key_decision_factors) }}{% endif %}{% endif %}
{% else %}<div class="empty">No verdict or trading proposal was recorded for this run.</div>{% endif %}

<h2 class="pb">2. Charts</h2>
<h3>Price history and trade levels</h3>{{ fig(ch.price) }}
<h3>Fundamentals</h3>{{ fig(ch.fund) }}
<h3>Sentiment</h3>{{ fig(ch.sent) }}
<h3>Debate</h3>{{ fig(ch.debate) }}
<h3>Agent timeline</h3>{{ fig(ch.timeline) }}
<h3>Supplementary sources</h3>{{ fig(ch.supp) }}
{% if sup %}<table><thead><tr><th>Source</th><th>Category</th><th>Status</th><th>Items</th><th>As of</th><th>Reason</th></tr></thead>{% for s in sup %}
<tr><td>{{ link(s.url, s.name or s.id) }}</td><td>{{ s.category or na }}</td><td>{{ s.status or na }}</td><td>{{ s.item_count if s.item_count is not none else na }}</td><td>{{ s.as_of or na }}</td><td>{{ s.reason or '' }}</td></tr>{% endfor %}</table>{% endif %}

<h2 class="pb">3. Analyst reports</h2>
{{ report('Market analyst', 'market') }}{{ report('Sentiment analyst', 'sentiment') }}{{ report('News analyst', 'news') }}{{ report('Fundamentals analyst', 'fundamentals') }}
{% if proposal %}<h3>Trader proposal (full)</h3><table class="kv">{% for k, x in proposal.items() if k not in ('ticker',) %}<tr><th>{{ k|label }}</th><td>{{ val(x) }}</td></tr>{% endfor %}</table>{% endif %}

<h2 class="pb">4. Debate, synthesis and guardrails</h2>
{% if rounds %}{% for r in rounds %}<h3>Round {{ r.round }}</h3>
<div class="turn bull"><b class="pos">Bull</b> &middot; conviction {{ (r.bull_argument or {}).get('conviction_level') or na }}{{ val(r.bull_argument or none) }}</div>
<div class="turn bear"><b class="neg">Bear</b> &middot; conviction {{ (r.bear_counterargument or {}).get('conviction_level') or na }}{{ val(r.bear_counterargument or none) }}</div>{% endfor %}
{% else %}<div class="empty">Debate transcript: {{ na }}</div>{% endif %}
<h3>Research manager synthesis</h3>{% if verdict %}<table class="kv">{% for k, x in verdict.items() if k not in ('ticker',) %}<tr><th>{{ k|label }}</th><td>{{ val(x) }}</td></tr>{% endfor %}</table>{% else %}<div class="empty">{{ na }}</div>{% endif %}
<h3>Guardrail results</h3>{% if guards %}<table><thead><tr><th>Check source</th><th>Result</th><th>Max attack score</th><th>Model</th><th>Chunks</th></tr></thead>{% for g in guards %}
<tr><td>{{ g.source or na }}</td><td class="{{ 'pos' if g.status == 'PASSED' else 'neg' }}">{{ g.status or na }}</td><td>{{ g.max_attack_score|fmt }}</td><td>{{ g.model or na }}</td><td>{{ g.chunks|fmt }}</td></tr>{% endfor %}</table>
{% else %}<div class="empty">No guardrail results recorded for this run.</div>{% endif %}

<h2 class="pb">5. Evidence and provenance</h2>
<h3>News articles</h3>{% if news %}<table><thead><tr><th>Headline</th><th>Source</th><th>Published</th></tr></thead>{% for a in news %}<tr><td>{{ link(a.url, a.headline) }}{% if a.summary %}<br><span class="meta">{{ a.summary }}</span>{% endif %}</td><td>{{ a.source }}</td><td>{{ a.datetime }}</td></tr>{% endfor %}</table>
{% else %}<div class="empty">{{ na }}</div>{% endif %}
<h3>Reddit posts</h3>{% set s = sources.get('sentiment') %}
{% if posts %}<table><thead><tr><th>Post</th><th>Subreddit</th><th>Date</th><th>Label</th></tr></thead>{% for p in posts %}<tr><td>{{ link(p.url, p.title) }}</td><td>{{ p.subreddit }}</td><td>{{ p.created_iso }}</td><td>{{ p.sentiment_label }}</td></tr>{% endfor %}</table>
{% elif s %}<div class="empty">No posts used. Status {{ s.status }}{% if s.reason %}: {{ s.reason }}{% endif %}.</div>{% else %}<div class="empty">{{ na }}</div>{% endif %}
{% if s and s.attempts %}<p class="meta">Fetch attempts</p><table><thead><tr><th>Method</th><th>Status / error</th><th>URL</th></tr></thead>{% for a in s.attempts %}<tr><td>{{ a.method }}</td><td>{{ a.status if a.status is not none else a.error or na }}</td><td>{{ link(a.url, a.url) }}</td></tr>{% endfor %}</table>{% endif %}
<h3>Supplementary items</h3>{% if supp_groups %}{% for name, items in supp_groups.items() %}<p><b>{{ name }}</b>{% set meta = sup_by_name.get(name) %}{% if meta and meta.usage_note %}<br><span class="meta">Usage: {{ meta.usage_note }}</span>{% endif %}</p>
<table><thead><tr><th>Item</th><th>Date / period</th><th>Detail</th></tr></thead>{% for i in items %}<tr><td>{{ link(i.url, i.title or i.indicator) }}</td><td>{{ i.published_at or i.period or '' }}</td><td>{{ i.summary or '' }}{% if i.value %} {{ i.indicator }} {{ i.value }} {{ i.unit or '' }}{% endif %}</td></tr>{% endfor %}</table>{% endfor %}
{% else %}<div class="empty">No supplementary items recorded for this run.</div>{% endif %}
<h3>Fundamentals source</h3><p>{{ (sources.get('fundamentals') or {}).get('source') or na }}; fiscal period ending {{ (sources.get('fundamentals') or {}).get('fiscal_period_end') or na }}.</p>
<p class="meta">Evidence retrieved {{ (provenance or {}).get('retrieved_at')|when }}</p>

<h2>6. Limitations and disclaimers</h2>
<ul>{% for l in limits %}<li>{{ l }}</li>{% endfor %}</ul>
<p class="meta">Generated by KAIROS from data stored for run {{ run.id }}. Nothing was re-fetched when this report was produced.</p>
</main>{% if print_mode %}<script>addEventListener('load',function(){setTimeout(function(){print()},300)})</script>{% endif %}</body></html>"""

env = Environment(autoescape=True)
env.filters.update(label=label, fmt=fmt, when=when, safe_url=safe_url)
_template = env.from_string(TEMPLATE)


def limitations(d):
    run, out = d["run"], ["Paper research only. Nothing here is investment advice and no real order was placed.",
                          "Conviction levels are model-stated and uncalibrated; they are not probabilities."]
    if run["status"] != "COMPLETED":
        out.append(f"The run ended as {run['status']}; later stages did not run.")
    modes = {r.get("execution_mode") for r in d["reports"].values() if isinstance(r, dict)}
    out += [f"{k.capitalize()} analyst ran in {r['execution_mode']} mode (a fallback, not a live model)." for k, r in d["reports"].items() if "FALLBACK" in str(r.get("execution_mode"))]
    if d["prices"] is None:
        out.append("Price history was not recorded for this run, so no price chart is shown.")
    s = d["sources"].get("sentiment")
    if s and s.get("status") != "OK":
        out.append(f"Reddit sentiment: {s.get('status')}{' - ' + str(s['reason']) if s.get('reason') else ''}.")
    out += [f"Supplementary source '{x.get('name')}' was {x.get('status')}: {x.get('reason')}." for x in d["sources"].get("supplementary") or [] if x.get("status") in ("unavailable", "not_configured")]
    out += list((d["verdict"] or {}).get("limitations") or [])
    q = (d["proposal"] or {}).get("quote_delay") or d["reports"].get("market", {}).get("quote_delay")
    out.append(f"Market quote delay: {q or 'not recorded'}. Prices are as of the stated dates, not live.")
    return out


def render(run, events, directory, print_mode=False):
    d = collect(run, events, Path(directory))
    fund = d["fund"] or {}
    modes = sorted({r["execution_mode"] for r in [*d["reports"].values(), d["verdict"] or {}, d["proposal"] or {}] if r.get("execution_mode")})
    end = next((e["created"] for e in reversed(events) if e["type"] in ("run-completed", "run-failed")), None)
    sup = d["sources"].get("supplementary") or []
    groups = {}
    for item in d["supp_items"]:
        groups.setdefault(item.get("source_name") or item.get("source_id") or "Unknown source", []).append(item)
    return _template.render(css=Markup(CSS), na=NA, company=fund.get("company_name"), finished=end, modes=modes, ch=_Obj(charts(d)),
                            limits=limitations(d), sup=sup, sup_by_name={x.get("name"): x for x in sup}, supp_groups=groups, print_mode=print_mode, **d)


class _Obj(dict):
    __getattr__ = dict.__getitem__


def all_events(runs, run_id):
    cursor, out = 0, []
    while batch := runs.events(run_id, cursor):
        out += batch
        cursor = batch[-1]["id"]
    return out


def filename(run):
    day = datetime.fromtimestamp(run["created"], IST).strftime("%Y-%m-%d")
    return f"KAIROS_{re.sub(r'[^A-Za-z0-9_-]', '', run['ticker'])}_{day}_{run['id'][:8]}.html"
