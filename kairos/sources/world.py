"""GDELT DOC 2.0 (news discovery) and World Bank indicators (annual macro)."""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone

from ._http import SourceError, base_symbol, get, iso, norm_name, parse_date, strip_html

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
WB_INDICATORS = {
    "NY.GDP.MKTP.KD.ZG": ("GDP growth (annual %)", "%"),
    "FP.CPI.TOTL.ZG": ("Inflation, consumer prices (annual %)", "%"),
    "BN.CAB.XOKA.GD.ZS": ("Current account balance (% of GDP)", "% of GDP"),
    "BX.KLT.DINV.WD.GD.ZS": ("Foreign direct investment, net inflows (% of GDP)", "% of GDP"),
}
_gdelt_lock, _gdelt_last = threading.Lock(), [0.0]


def gdelt(symbol, company_name, now):
    name = norm_name(company_name) or base_symbol(symbol).lower()
    with _gdelt_lock:  # GDELT allows ~1 request / 5 s
        time.sleep(max(0.0, _gdelt_last[0] + 5.2 - time.monotonic()))
        _gdelt_last[0] = time.monotonic()
        try:
            r = get(GDELT_URL, params={"query": f'"{name}" sourcecountry:IN', "mode": "artlist", "format": "json", "maxrecords": 25,
                                       "timespan": "7d", "sort": "datedesc"}, timeout=24, retries=0)
        except SourceError as e:
            raise SourceError("rate limited by GDELT (HTTP 429)" if "429" in str(e) else str(e)) from e
    text = r.text.strip()
    if not text:
        arts = []
    else:
        try:
            arts = json.loads(text).get("articles") or []
        except ValueError as e:
            raise SourceError(f"GDELT returned non-JSON: {strip_html(text, 120)}") from e
    items = []
    for a in arts:
        if not a.get("url") or not a.get("title"):
            continue
        d = parse_date(a.get("seendate"))
        items.append({"title": strip_html(a["title"], 300), "url": a["url"], "published_at": iso(d),
                      "summary": f"Published by {a.get('domain', 'unknown')} ({a.get('language', '?')}); headline found by GDELT keyword match, not verified.",
                      "relevance": "TICKER_SPECIFIC"})
        if len(items) == 10:
            break
    return {"status": "ok" if items else "empty", "items": items, "as_of": items[0]["published_at"] if items else None,
            "reason": None if items else "no GDELT articles for the query in the last 7 days"}


def _wb_one(code):
    label, unit = WB_INDICATORS[code]
    data = get(f"https://api.worldbank.org/v2/country/IND/indicator/{code}", params={"format": "json", "per_page": 8, "mrnev": 1}, timeout=4).json()
    if not (isinstance(data, list) and len(data) > 1 and data[1]):
        raise SourceError(f"{code}: no data")
    row = next((r for r in data[1] if r.get("value") is not None), None)
    if not row:
        raise SourceError(f"{code}: no data")
    v, yr = round(float(row["value"]), 2), row["date"]
    return {"title": f"India {label}, {yr}: {v}", "url": f"https://data.worldbank.org/indicator/{code}?locations=IN", "published_at": None,
            "summary": f"World Bank annual series {code}; latest available year {yr}.", "relevance": "MARKET_CONTEXT",
            "value": v, "unit": unit, "period": yr, "indicator": label}


def world_bank(symbol, company_name, now):
    def safe(code):
        try:
            return _wb_one(code), None
        except (SourceError, ValueError, KeyError, TypeError) as e:
            return None, f"{code}: {e}"
    with ThreadPoolExecutor(len(WB_INDICATORS)) as ex:
        res = list(ex.map(safe, WB_INDICATORS))
    items = [i for i, _ in res if i]
    errs = [e for _, e in res if e]
    if not items:
        raise SourceError("; ".join(errs))
    return {"status": "ok", "items": items, "as_of": max(i["period"] for i in items),
            "reason": ("partial: " + "; ".join(errs)) if errs else None}
