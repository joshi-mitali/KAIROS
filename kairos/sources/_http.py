"""Shared HTTP, feed parsing, date and text helpers for supplementary sources."""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

UA = "KAIROS equity research (informational, noncommercial)"
IST = timezone(timedelta(hours=5, minutes=30))
_DATE_FORMATS = (
    "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%d %b %Y %H:%M:%S",
    "%d %b %Y", "%b %d, %Y", "%d %B %Y", "%d %b, %Y", "%Y%m%dT%H%M%SZ",
)


class SourceError(Exception):
    """A source is unreachable or returned something unusable; message becomes the reason."""


def request(method: str, url: str, *, timeout: float = 8, retries: int = 1, **kw) -> requests.Response:
    headers = {"User-Agent": UA, **kw.pop("headers", {})}
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, url, headers=headers, timeout=timeout, **kw)
        except requests.RequestException as e:
            if attempt == retries or isinstance(e, requests.Timeout):  # a hung host will hang again; fail fast
                raise SourceError(f"{type(e).__name__}: {str(e)[:100]}") from e
            time.sleep(1)
            continue
        if r.status_code in (500, 502, 503, 504) and attempt < retries:  # 429 is not retried: the wait outlasts any source budget
            time.sleep(1)
            continue
        if r.status_code >= 400:
            raise SourceError(f"HTTP {r.status_code}")
        return r
    raise SourceError("unreachable")  # pragma: no cover


def get(url: str, **kw) -> requests.Response:
    return request("GET", url, **kw)


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)  # shortcut: naive source dates are IST


def parse_date(s: str | None) -> datetime | None:
    """RFC 822, ISO 8601 or common Indian-site formats -> aware datetime, else None."""
    s = (s or "").strip()
    if not s:
        return None
    for fn in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            return aware(fn(s))
        except (TypeError, ValueError):
            pass
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc) if fmt.endswith("Z") else aware(dt)
        except ValueError:
            pass
    return None


def strip_html(s: str | None, limit: int = 400) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()[:limit]


def parse_feed(content: bytes | str) -> list[dict]:
    """RSS 2.0 <item> and Atom <entry> -> [{title, link, summary, published(datetime|None)}]."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    try:
        root = ET.fromstring(content.lstrip(b"\xef\xbb\xbf \r\n\t"))
    except ET.ParseError as e:
        raise SourceError(f"unparseable feed: {e}") from e
    out = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] not in ("item", "entry"):
            continue
        f = {}
        for ch in el:
            name = ch.tag.rsplit("}", 1)[-1]
            if name == "link":
                f.setdefault("link", (ch.text or ch.get("href") or "").strip())
            elif name in ("title", "description", "summary", "content", "pubDate", "published", "updated"):
                f.setdefault(name, ch.text or "")
        out.append({
            "title": strip_html(f.get("title"), 300),
            "link": f.get("link", ""),
            "summary": strip_html(f.get("description") or f.get("summary") or f.get("content")),
            "published": parse_date(f.get("pubDate") or f.get("published") or f.get("updated")),
        })
    return out


_SUFFIX = re.compile(r"\b(limited|ltd|pvt|private|corporation|corp|inc|company|co)\b\.?", re.I)


def norm_name(s: str) -> str:
    s = _SUFFIX.sub(" ", (s or "").lower().replace("&", " and "))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def matches_entity(text: str, base_symbol: str, company_name: str) -> bool:
    """Company name (suffix-insensitive) or exact upper-case ticker as a whole word."""
    name = norm_name(company_name)
    if len(name) >= 4 and f" {name} " in f" {norm_name(text)} ":
        return True
    return len(base_symbol) >= 3 and re.search(rf"(?<![A-Za-z0-9]){re.escape(base_symbol)}(?![A-Za-z0-9])", text) is not None


def base_symbol(symbol: str) -> str:
    return re.sub(r"\.(NS|BO)$", "", (symbol or "").upper().strip())


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
