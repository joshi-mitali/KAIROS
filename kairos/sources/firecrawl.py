"""Firecrawl web/news search (third-party discovery) with a short markdown evidence summary for the top results."""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlparse

from ._http import SourceError, base_symbol, iso, matches_entity, parse_date, request, strip_html

API = "https://api.firecrawl.dev/v2"
SEARCH_LIMIT = 8   # per search (credits scale with results)
SCRAPE_TOP = 3     # pages scraped in total
BUDGET_S = 11      # whole-source wall budget (collector caps at 12 s); scraping only uses what search left
NEWS_DAYS = 7
_ERRORS = {401: "Firecrawl rejected the API key (HTTP 401)", 402: "Firecrawl credits exhausted (HTTP 402)",
           403: "Firecrawl access denied (HTTP 403)", 429: "Firecrawl rate limited (HTTP 429)"}


def _post(path, body, timeout):
    key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    try:
        r = request("POST", f"{API}/{path}", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=timeout, retries=0)
        data = r.json()
    except SourceError as e:
        m = re.search(r"HTTP (\d+)", str(e))
        code = int(m.group(1)) if m else 0
        raise SourceError(_ERRORS.get(code) or (f"Firecrawl server error (HTTP {code})" if code >= 500 else "Firecrawl request failed")) from None
    except ValueError:
        raise SourceError("Firecrawl returned non-JSON") from None
    if not isinstance(data, dict) or data.get("success") is False:
        raise SourceError("Firecrawl reported failure")
    return data


def _summary(markdown, limit=400):
    """First substantive paragraph of scraped markdown, stripped of links/images/headings/boilerplate."""
    for para in re.split(r"\n\s*\n", markdown or ""):
        t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", para)
        t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
        t = re.sub(r"https?://\S+|[#*_`>|]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) >= 80 and len(t.split()) >= 12 and not re.match(r"(?i)(skip to|sign in|subscribe|cookie|menu|home\b)", t):
            return t[:limit]
    return ""


def _scrape(url, timeout):
    try:
        d = _post("scrape", {"url": url, "formats": ["markdown"], "onlyMainContent": True, "timeout": int(timeout * 1000)}, timeout + 2)
        return _summary((d.get("data") or {}).get("markdown"))
    except SourceError:
        return ""


def firecrawl(symbol, company_name, now):
    if not os.environ.get("FIRECRAWL_API_KEY", "").strip():
        return {"status": "not_configured", "reason": "FIRECRAWL_API_KEY not set", "items": []}
    start = time.monotonic()
    sym, name = base_symbol(symbol), (company_name or "").strip()
    label = re.sub(r"\s+(limited|ltd\.?)$", "", name, flags=re.I) or sym
    searches = [  # (query, source, time filter)
        (f'"{label}" OR {sym} stock', "news", "qdr:w"),
        (f"{label} results OR earnings OR guidance OR order OR acquisition", "web", "qdr:m"),
    ]

    def run(q):
        body = {"query": q[0], "limit": SEARCH_LIMIT, "sources": [q[1]], "tbs": q[2], "country": "IN", "location": "India", "timeout": 8000}
        return q[1], _post("search", body, 9)

    with ThreadPoolExecutor(2) as ex:
        futs = [ex.submit(run, q) for q in searches]
        outs, errs = [], []
        for f in futs:
            try:
                outs.append(f.result())
            except SourceError as e:
                errs.append(str(e))
    if not outs:
        raise SourceError(errs[0])
    items, seen = [], set()
    for kind, d in outs:
        for r in ((d.get("data") or {}).get(kind) or []):
            url = (r.get("url") or "").strip()
            p = urlparse(url)
            host = (p.hostname or "").lower()
            if p.scheme not in ("http", "https") or not host or host == "reddit.com" or host.endswith(".reddit.com") or url in seen:
                continue
            title = strip_html(r.get("title"), 300)
            if not title:
                continue
            snippet = strip_html(r.get("snippet") or r.get("description"), 400)
            d_ = parse_date(r.get("date"))
            if kind == "news" and d_ and d_ < now - timedelta(days=NEWS_DAYS):
                continue
            seen.add(url)
            hit = matches_entity(f"{title} {snippet}", sym, name)
            items.append({"title": title, "url": url, "published_at": iso(d_), "relevance": "TICKER_SPECIFIC" if hit else "MARKET_CONTEXT",
                          "summary": snippet or f"Result from {host}; discovered via Firecrawl, not verified."})
    items.sort(key=lambda i: i["relevance"] != "TICKER_SPECIFIC")  # stable: ticker-specific first
    items = items[:10]
    left = BUDGET_S - (time.monotonic() - start)
    top = items[:SCRAPE_TOP] if left >= 3 else []  # otherwise keep the search snippets
    if top:
        with ThreadPoolExecutor(len(top)) as ex:
            for it, s in zip(top, ex.map(lambda i: _scrape(i["url"], left - 2.5), top)):
                if s:
                    it["summary"] = s
    dates = [i["published_at"] for i in items if i["published_at"]]
    return {"status": "ok" if items else "empty", "items": items, "as_of": max(dates) if dates else None,
            "reason": None if items else "no Firecrawl results for the queries"}
