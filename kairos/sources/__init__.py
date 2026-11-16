"""Supplementary research sources. Entry point: collect_supplementary(symbol, company_name, now)."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone

from . import feeds, ir, mcp, world
from ._http import SourceError, base_symbol

log = logging.getLogger(__name__)
PER_SOURCE_TIMEOUT, OVERALL_TIMEOUT = 12, 35
SOURCE_TIMEOUTS = {"gdelt": 30}  # GDELT routinely needs ~15 s per request; everything else gets 12 s

# id -> (fn, name, category, url, usage_note)
SOURCES = {
    "nse_announcements": (feeds.nse_announcements, "NSE corporate RSS feeds", "disclosure", "https://www.nseindia.com/static/rss-feed",
        "Latest ~20-30 entries per feed, company-name match only, 30-day window; linked PDFs are not extracted; informational use per NSE terms."),
    "company_ir": (ir.company_ir, "Company investor-relations pages", "company_documents", "https://www.ril.com/investors",
        "Link discovery only (title and URL from the official page); documents are not downloaded or read; registry covers RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK."),
    "rbi": (feeds.rbi, "RBI press releases and notifications RSS", "macro", "https://www.rbi.org.in/Scripts/rss.aspx",
        "Market-wide context, 30-day window; DBIE (https://data.rbi.org.in) is a reference for time series, not queried here."),
    "sebi": (feeds.sebi, "SEBI RSS feed", "regulatory", "https://www.sebi.gov.in/rss.html",
        "Entity-matched items are ticker-specific; at most 3 general items; 30-day window; feed may be empty."),
    "mospi_mcp": (mcp.mospi_mcp, "MoSPI eSankhyiki MCP (beta)", "macro", "https://mcp.mospi.gov.in/",
        "Official statistics via beta MCP server, keyless; latest CPI, IIP and computed GDP growth; revisions and release lags apply."),
    "nse_mcp": (mcp.nse_mcp, "NSE MCP (cash market live data)", "market_reference", "https://www.nseindia.com/nse-mcp",
        "Informational/noncommercial use only; data delayed 1-3 minutes; unadjusted history; not for execution or investment advice."),
    "gdelt": (world.gdelt, "GDELT DOC 2.0 news discovery", "news_discovery", "https://api.gdeltproject.org/api/v2/doc/doc",
        "Discovery only, not fact verification; headlines/links may not be republished; rate limit about 1 request per 5 seconds."),
    "world_bank": (world.world_bank, "World Bank Indicators API", "macro", "https://data.worldbank.org/country/india",
        "Annual structural context (latest year available), not a trading signal; keyless."),
}


def _result(sid, now, out=None, status=None, reason=None):
    _, name, cat, url, note = SOURCES[sid]
    out = out or {}
    status = status or out.get("status", "unavailable")
    return {"id": sid, "name": name, "category": cat, "status": status,
            "reason": reason if reason is not None else out.get("reason"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "as_of": out.get("as_of") if status == "ok" else None,
            "url": out.get("url", url), "usage_note": note, "items": (out.get("items") or [])[:10] if status == "ok" else []}


def collect_supplementary(symbol: str, company_name: str, now: datetime) -> list[dict]:
    """Run all sources concurrently; never raises. One result dict per source."""
    try:
        sym, name = base_symbol(symbol), (company_name or "").strip()
        now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        ex = ThreadPoolExecutor(len(SOURCES))
        start = time.monotonic()
        futs = {sid: ex.submit(SOURCES[sid][0], sym, name, now) for sid in SOURCES}
        results = []
        for sid, f in futs.items():
            budget = min(SOURCE_TIMEOUTS.get(sid, PER_SOURCE_TIMEOUT), OVERALL_TIMEOUT)
            try:
                results.append(_result(sid, now, f.result(timeout=max(0.0, start + budget - time.monotonic()))))
            except FutureTimeout:
                results.append(_result(sid, now, status="unavailable", reason="timed out"))
            except SourceError as e:
                results.append(_result(sid, now, status="unavailable", reason=str(e)))
            except Exception as e:  # a source bug must not break the pipeline
                log.warning("source %s failed: %r", sid, e)
                results.append(_result(sid, now, status="unavailable", reason=f"{type(e).__name__}: {str(e)[:100]}"))
        ex.shutdown(wait=False, cancel_futures=True)  # stragglers are abandoned, not awaited
        return results
    except Exception as e:  # pragma: no cover - last-resort guard of the contract
        log.error("collect_supplementary failed: %r", e)
        return []
