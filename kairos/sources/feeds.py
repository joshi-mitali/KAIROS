"""RSS-based sources: NSE corporate feeds, RBI, SEBI."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from datetime import timedelta

from ._http import SourceError, base_symbol, get, iso, matches_entity, parse_feed

WINDOW = timedelta(days=30)
FEED_WAIT_S = 6  # shared wait for all feeds of one source; slow feeds are reported as partial
NSE_FEEDS = {  # all verified live 17 Nov 2026; unlisted names 404
    "Announcements": "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",
    "Financial results": "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml",
    "Corporate actions": "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",
    "Insider trading": "https://nsearchives.nseindia.com/content/RSS/Insider_Trading.xml",
    "Shareholding pattern": "https://nsearchives.nseindia.com/content/RSS/Shareholding_Pattern.xml",
}
RBI_FEEDS = {
    "Press release": "https://rbi.org.in/pressreleases_rss.xml",
    "Notification": "https://rbi.org.in/notifications_rss.xml",
}
SEBI_FEEDS = {"SEBI": "https://www.sebi.gov.in/sebirss.xml"}


def _fetch_all(feeds: dict) -> tuple[list[tuple[str, dict]], list[str]]:
    """Fetch feeds concurrently -> ([(label, entry)], failure notes). Raises only if all fail."""
    def one(label_url):
        label, url = label_url
        try:
            return label, parse_feed(get(url).content), None
        except SourceError as e:
            return label, [], f"{label}: {e}"
    ex = ThreadPoolExecutor(len(feeds))
    futs = {label: ex.submit(one, (label, url)) for label, url in feeds.items()}
    wait(futs.values(), timeout=FEED_WAIT_S)
    ex.shutdown(wait=False, cancel_futures=True)  # one hung feed must not hold the rest back
    res = [f.result() if f.done() else (label, [], f"{label}: timed out") for label, f in futs.items()]
    errs = [r[2] for r in res if r[2]]
    if len(errs) == len(res):
        raise SourceError("; ".join(errs))
    return [(label, e) for label, entries, _ in res for e in entries], errs


def _collect(feeds, now, keep, cap=10, max_context=None):
    """keep(entry) -> relevance or None. Applies the 30-day window, newest first, caps."""
    entries, errs = _fetch_all(feeds)
    items, context = [], 0
    for label, e in sorted(entries, key=lambda x: x[1]["published"] or now - WINDOW * 9, reverse=True):
        pub = e["published"]
        if not pub or not (now - WINDOW <= pub <= now + timedelta(days=1)):
            continue
        rel = keep(e)
        if not rel:
            continue
        if rel == "MARKET_CONTEXT":
            if max_context is not None and context >= max_context:
                continue
            context += 1
        items.append({"title": f"[{label}] {e['title']}", "url": e["link"], "published_at": iso(pub),
                      "summary": e["summary"], "relevance": rel})
    items = items[:cap]
    reason = ("partial: " + "; ".join(errs)) if errs else None
    return {"status": "ok" if items else "empty", "items": items, "as_of": items[0]["published_at"] if items else None,
            "reason": reason or (None if items else "no matching items in the last 30 days")}


def nse_announcements(symbol, company_name, now):
    sym = base_symbol(symbol)
    return _collect(NSE_FEEDS, now, lambda e: "TICKER_SPECIFIC" if matches_entity(e["title"], sym, company_name) else None)


def rbi(symbol, company_name, now):
    return _collect(RBI_FEEDS, now, lambda e: "MARKET_CONTEXT")


def sebi(symbol, company_name, now):
    sym = base_symbol(symbol)
    return _collect(
        SEBI_FEEDS, now,
        lambda e: "TICKER_SPECIFIC" if matches_entity(e["title"] + " " + e["summary"], sym, company_name) else "MARKET_CONTEXT",
        max_context=3,
    )
