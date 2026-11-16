"""Official investor-relations pages -> links to results, transcripts, presentations, annual reports."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from ._http import SourceError, base_symbol, get, iso, parse_date, strip_html

# URLs verified 17 Nov 2026. TCS/INFY answer 403 to automated clients; kept so the failure is reported honestly.
IR_PAGES = {
    "RELIANCE": "https://www.ril.com/investors/financial-reporting",
    "TCS": "https://www.tcs.com/investor-relations",
    "INFY": "https://www.infosys.com/investors/reports-filings.html",
    "HDFCBANK": "https://www.hdfc.bank.in/about-us/investor-relations",
    "ICICIBANK": "https://www.icici.bank.in/about-us/qfr",
}
_KEYWORDS = re.compile(r"result|transcript|presentation|annual report|earnings|concall|factsheet", re.I)
_DATED = re.compile(r"\.pdf|/pdf/|Q[1-4]|FY\s?\d{2}|20\d\d", re.I)
_DATE_IN_TEXT = re.compile(r"\b\d{1,2}[ -](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[ ,-]+\d{4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}\b")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._text = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, strip_html(" ".join(self._text), 200)))
            self._href = None


def extract_links(page_html: str, page_url: str, cap: int = 10) -> list[dict]:
    p = _Links()
    p.feed(page_html)
    seen, items = set(), []
    for href, text in p.links:
        if len(text) < 8 or not _KEYWORDS.search(text) or not _DATED.search(href + " " + text):
            continue  # skips navigation links such as "Reports, Results & Presentations"
        url = urljoin(page_url, href)
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        m = _DATE_IN_TEXT.search(text)
        d = parse_date(m.group(0)) if m else None
        items.append({"title": text, "url": url, "published_at": iso(d), "summary": "Link text only; document content not read.",
                      "relevance": "TICKER_SPECIFIC"})
        if len(items) == cap:
            break
    return items


def company_ir(symbol, company_name, now):
    page = IR_PAGES.get(base_symbol(symbol))
    if not page:
        return {"status": "not_configured", "reason": "no verified investor-relations page registered for this ticker"}
    r = get(page, timeout=10)
    items = extract_links(r.text, r.url)
    dated = [i["published_at"] for i in items if i["published_at"]]
    return {"status": "ok" if items else "empty", "items": items, "as_of": max(dated) if dated else None, "url": page,
            "reason": None if items else "page reachable but no report/transcript/presentation links found"}
