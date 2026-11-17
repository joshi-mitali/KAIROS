import sys, types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

import kairos.pipeline.live_research as lr

NOW = datetime.now(timezone.utc)


def _rss(*items):
    body = "".join(f"<item><title>{t}</title><link>{l}</link><pubDate>{d.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
                   f"<description>&lt;a&gt;{t}&lt;/a&gt;</description></item>" for t, l, d in items)
    return SimpleNamespace(content=f"<rss><channel>{body}</channel></rss>".encode(), status_code=200)


def _yahoo(days_old, n):
    return [{"content": {"title": f"Y{i}", "pubDate": (NOW - timedelta(days=days_old)).isoformat().replace("+00:00", "Z"),
                         "canonicalUrl": {"url": f"http://y/{i}"}}} for i in range(n)]


def test_helper_filters_window_dupes_and_strips_publisher(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    feed = _rss(("Fresh - Mint", "https://g/1", NOW - timedelta(days=1)), ("Fresh - Mint", "https://g/2", NOW - timedelta(days=1)),
                ("Old - ET", "https://g/3", NOW - timedelta(days=9)), ("Future - ET", "https://g/4", NOW + timedelta(days=2)),
                ("Bad link - ET", "ftp://g/5", NOW), ("No suffix", "https://g/6", NOW))
    urls = []
    out, notes = lr.fallback_news_articles("Tata Consultancy Services Limited", NOW, fetch=lambda url, **k: urls.append(url) or feed)
    assert [(p, a["headline"], a["source"]) for p, a in out] == [("GOOGLE_NEWS_RSS", "Fresh", "Mint"), ("GOOGLE_NEWS_RSS", "No suffix", "Google News")]
    assert out[0][1]["summary"] == "Fresh - Mint" and set(out[0][1]) == {"headline", "summary", "url", "datetime", "source", "retrieved_at"}
    assert len(urls) == 2 and notes[0] == "Google News RSS: 2 fresh items"  # 2 of 3 wanted, so Bing was asked too (same titles: deduped)
    assert "%22Tata+Consultancy+Services%22" in urls[0] and "Limited" not in urls[0]


def test_suffix_stripping_variants(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    for name in ("Infosys Ltd.", "Infosys Ltd", "Infosys Limited", "Infosys"):
        urls = []
        lr.fallback_news_articles(name, NOW, fetch=lambda url, **k: urls.append(url) or _rss(), limit=1)
        assert "%22Infosys%22" in urls[0], name


def test_google_fails_bing_supplies(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    def fetch(url, **k):
        if "google" in url:
            raise lr.SourceError("HTTP 429")
        return _rss(*[(f"B{i} - Mint", f"https://b/{i}", NOW - timedelta(days=1)) for i in range(5)])
    out, notes = lr.fallback_news_articles("X Limited", NOW, fetch=fetch)
    assert [p for p, _ in out] == ["BING_NEWS_RSS"] * 3
    assert notes[0] == "Google News RSS: HTTP 429" and len(notes) == 2


def test_stops_once_limit_reached(monkeypatch):
    urls = []
    out, notes = lr.fallback_news_articles("X", NOW, fetch=lambda url, **k: urls.append(url) or _rss(
        *[(f"G{i} - Mint", f"https://g/{i}", NOW) for i in range(5)]))
    assert len(out) == 3 and len(urls) == 1 and len(notes) == 1


def _run(monkeypatch, tmp_path, yahoo, google):
    calls = []
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    fake = SimpleNamespace(income_stmt=pd.DataFrame({"2025-03-31": [100.0, 10.0]}, index=["Total Revenue", "Net Income"]),
                           balance_sheet=pd.DataFrame({"2025-03-31": [200.0, 50.0]}, index=["Total Assets", "Total Liabilities Net Minority Interest"]),
                           cash_flow=pd.DataFrame({"2025-03-31": [20.0]}, index=["Operating Cash Flow"]),
                           get_info=lambda: {"longName": "Tata Consultancy Services Limited", "financialCurrency": "INR"},
                           get_news=lambda **k: yahoo)
    monkeypatch.setattr(lr.yf, "Ticker", lambda s: fake)
    monkeypatch.setattr(lr.requests, "get", lambda *a, **k: SimpleNamespace(status_code=200))
    monkeypatch.setattr(lr, "fetch_reddit_evidence", lambda *a, **k: ([], {"source": "REDDIT", "method": "rss_search", "status": "NO_RECENT_DISCUSSION",
                                                                          "posts": 0, "latest_post": None, "attempts": []}))
    monkeypatch.setitem(sys.modules, "kairos.sources", types.SimpleNamespace(collect_supplementary=lambda *a, **k: []))
    monkeypatch.setattr(lr.time, "sleep", lambda s: None)
    def fake_get(url, **k):
        calls.append(url)
        if isinstance(google, Exception):
            raise google
        return google
    monkeypatch.setattr(lr, "get", fake_get)
    return lambda: lr.refresh_research_evidence("TCS.NS", tmp_path, lambda k, p: None), calls


def test_stale_yahoo_falls_back_to_google(monkeypatch, tmp_path):
    feed = _rss(*[(f"Story {i} - Mint", f"https://g/{i}", NOW - timedelta(days=i)) for i in range(1, 5)])
    run, calls = _run(monkeypatch, tmp_path, _yahoo(30, 3), feed)
    news = run()["sources"]["news"]
    assert news["source"] == "GOOGLE_NEWS_RSS" and news["articles"] == 3
    assert "Tata+Consultancy+Services%22" in calls[0] and "ceid=IN:en" in calls[0]
    assert len(pd.read_parquet(tmp_path / "processed" / "news" / "tcs.ns_news_clean.parquet")) == 3


def test_three_fresh_yahoo_skips_google(monkeypatch, tmp_path):
    run, calls = _run(monkeypatch, tmp_path, _yahoo(1, 3), _rss())
    assert run()["sources"]["news"]["source"] == "YAHOO_FINANCE" and calls == []


def test_partial_yahoo_is_topped_up(monkeypatch, tmp_path):
    feed = _rss(*[(f"Story {i} - Mint", f"https://g/{i}", NOW - timedelta(days=1)) for i in range(5)])
    run, _ = _run(monkeypatch, tmp_path, _yahoo(1, 1), feed)
    news = run()["sources"]["news"]
    assert news["source"] == "YAHOO_FINANCE+GOOGLE_NEWS_RSS" and news["articles"] == 3


def test_both_empty_raises(monkeypatch, tmp_path):
    run, _ = _run(monkeypatch, tmp_path, _yahoo(30, 3), _rss())
    with pytest.raises(ValueError, match="No fresh, reachable news articles"):
        run()


def test_all_fail_error_lists_each_reason(monkeypatch, tmp_path):
    run, _ = _run(monkeypatch, tmp_path, _yahoo(30, 3), lr.SourceError("HTTP 429"))
    with pytest.raises(ValueError, match="No fresh, reachable news articles") as e:
        run()
    msg = str(e.value)
    assert "Checked: Yahoo Finance: 3 items, none within 7 days" in msg
    assert "Google News RSS: HTTP 429" in msg and "Bing News RSS: HTTP 429" in msg
