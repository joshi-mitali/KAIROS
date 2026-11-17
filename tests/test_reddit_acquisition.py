"""Reddit acquisition order, retry, outcomes and supplementary-source isolation (HTTP mocked)."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from kairos.collectors.reddit_collector import fetch_reddit_evidence, reddit_get

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
SETTINGS = SimpleNamespace(reddit_subreddits=["A", "B"], reddit_authorized=False, reddit_client_id=None, reddit_client_secret=None)


def atom(*entries):
    body = "".join(
        f'<entry><id>{i}</id><title>{t}</title><updated>{d}</updated><link href="https://www.reddit.com/r/A/comments/{i}/"/>'
        f'<author><name>/u/x</name></author><category term="A"/><content type="html">&lt;p&gt;{c}&lt;/p&gt;</content></entry>'
        for i, t, d, c in entries)
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'.encode()


def resp(status, content=b"", headers=None, data=None):
    return MagicMock(status_code=status, content=content, headers=headers or {}, json=lambda: data)


FRESH = ("t3_1", "Is RIL a buy?", "2026-11-16T10:00:00+00:00", "Jio results")
OLD = ("t3_2", "Reliance old", "2026-10-01T10:00:00+00:00", "")
OTHER = ("t3_3", "Nifty today", "2026-11-16T10:00:00+00:00", "nothing")


def session(*responses):
    s = MagicMock()
    s.get.side_effect = list(responses)
    return s


@patch("kairos.collectors.reddit_collector.time.sleep")
def test_429_retries_then_succeeds(sleep):
    s = session(resp(429, headers={"Retry-After": "99"}), resp(200))
    assert reddit_get("u", s).status_code == 200
    sleep.assert_called_once_with(5.0)


@patch("kairos.collectors.reddit_collector.time.sleep")
def test_403_not_retried(sleep):
    s = session(resp(403))
    assert reddit_get("u", s).status_code == 403 and s.get.call_count == 1


@patch("kairos.collectors.reddit_collector.time.sleep")
def test_search_429_falls_back_to_subreddit_feeds_with_alias_filter(sleep):
    s = session(resp(429), resp(429), resp(429), resp(200, atom(FRESH, OLD, OTHER)), resp(403))
    posts, meta = fetch_reddit_evidence("RELIANCE.NS", "Reliance Industries Limited", NOW, s, SETTINGS)
    assert meta["method"] == "rss_subreddit_new" and meta["status"] == "OK"
    assert [p["id"] for p in posts] == ["t3_1"]  # alias RIL matched; stale and unrelated dropped
    assert posts[0]["subreddit"] == "A" and posts[0]["text"] == "Jio results"
    assert [a["status"] for a in meta["attempts"]] == [429, 200, 403]


@patch("kairos.collectors.reddit_collector.time.sleep")
def test_all_403_is_unavailable_with_statuses(sleep):
    s = session(*[resp(403)] * 3)
    posts, meta = fetch_reddit_evidence("TCS.NS", "Tata Consultancy Services Limited", NOW, s, SETTINGS)
    assert posts == [] and meta["status"] == "UNAVAILABLE" and "HTTP 403" in meta["reason"]
    assert [a["status"] for a in meta["attempts"]] == [403, 403, 403]


@patch("kairos.collectors.reddit_collector.time.sleep")
def test_reachable_but_empty_is_no_recent_discussion(sleep):
    s = session(resp(200, atom(OTHER)), resp(200, atom(OTHER)), resp(200, atom(OTHER)))
    posts, meta = fetch_reddit_evidence("RELIANCE.NS", "Reliance Industries Limited", NOW, s, SETTINGS)
    assert posts == [] and meta["status"] == "NO_RECENT_DISCUSSION" and meta["posts"] == 0


@patch("kairos.collectors.reddit_collector.time.sleep")
def test_oauth_used_when_credentials_set(sleep):
    cfg = SimpleNamespace(**{**SETTINGS.__dict__, "reddit_authorized": True, "reddit_client_id": "id", "reddit_client_secret": "sekret"})
    child = {"data": {"name": "t3_9", "title": "RELIANCE rally", "created_utc": NOW.timestamp() - 3600, "permalink": "/r/A/comments/9/",
                      "subreddit": "A", "author": "u", "selftext": ""}}
    s = session(resp(200, data={"data": {"children": [child]}}))
    s.post.return_value = resp(200, data={"access_token": "TOKEN123"})
    posts, meta = fetch_reddit_evidence("RELIANCE.NS", "Reliance Industries Limited", NOW, s, cfg)
    assert meta["method"] == "oauth_search" and len(posts) == 1
    assert "sekret" not in str(meta) and "TOKEN123" not in str(meta)


def test_sentiment_analyst_reports_no_discussion(tmp_path):
    from kairos.agents.adk_analysts.sentiment_analyst import SentimentAnalyst
    path = tmp_path / "processed" / "reddit"
    path.mkdir(parents=True)
    pd.DataFrame([]).to_parquet(path / "reliance_sentiment_clean.parquet", index=False)
    report = SentimentAnalyst(data_dir=str(tmp_path)).run_analysis("RELIANCE")
    assert report.sample_size_posts == 0 and report.data_source == "NO_RECENT_DISCUSSION"
    assert report.overall_sentiment.value == "NEUTRAL" and "No recent retail discussion" in report.key_themes[0]


def _fake_run(monkeypatch, reddit_meta):
    import kairos.pipeline.live_research as lr
    monkeypatch.setattr(lr, "fallback_news_articles", lambda *a, **k: ([], []))  # no live Google News in tests
    frame = lambda: pd.DataFrame({"2025-03-31": [1.0]}, index=["Total Revenue"])
    fake = SimpleNamespace(income_stmt=pd.DataFrame({"2025-03-31": [100.0, 10.0]}, index=["Total Revenue", "Net Income"]),
                           balance_sheet=pd.DataFrame({"2025-03-31": [200.0, 50.0]}, index=["Total Assets", "Total Liabilities Net Minority Interest"]),
                           cash_flow=pd.DataFrame({"2025-03-31": [20.0]}, index=["Operating Cash Flow"]),
                           get_info=lambda: {"longName": "Reliance Industries Limited", "financialCurrency": "INR"},
                           get_news=lambda **k: [{"content": {"title": "t", "pubDate": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                                              "canonicalUrl": {"url": "http://x"}}}])
    monkeypatch.setattr(lr.yf, "Ticker", lambda s: fake)
    monkeypatch.setattr(lr.requests, "get", lambda *a, **k: SimpleNamespace(status_code=200))
    monkeypatch.setattr(lr, "fetch_reddit_evidence", lambda *a, **k: ([], reddit_meta))
    import sys, types
    def boom(*a):
        raise RuntimeError("boom")
    monkeypatch.setitem(sys.modules, "kairos.sources", types.SimpleNamespace(collect_supplementary=boom))
    return lr


QUIET = {"source": "REDDIT", "method": "rss_search", "status": "NO_RECENT_DISCUSSION", "posts": 0, "latest_post": None, "attempts": []}
DOWN = {"source": "REDDIT", "method": None, "status": "UNAVAILABLE", "posts": 0, "latest_post": None,
        "attempts": [{"method": "rss_search", "status": 403}], "reason": "Fresh Reddit evidence is unavailable (rss_search HTTP 403)."}


def test_supplementary_failure_does_not_stop_run(tmp_path, monkeypatch):
    lr = _fake_run(monkeypatch, QUIET)
    prov = lr.refresh_research_evidence("RELIANCE.NS", tmp_path, lambda k, p: None)
    assert prov["sources"]["sentiment"]["status"] == "NO_RECENT_DISCUSSION"
    assert prov["sources"]["supplementary"][0]["status"] == "unavailable"
    assert (tmp_path / "processed" / "supplementary" / "reliance.ns_evidence.parquet").exists()


def test_reddit_unreachable_continues_and_downstream_is_told(tmp_path, monkeypatch):
    from kairos.agents.adk_analysts.sentiment_analyst import SentimentAnalyst
    from kairos.agents.crewai_research.bull_researcher import BullResearcher
    from kairos.agents.crewai_research.bear_researcher import BearResearcher
    from kairos.agents.crewai_research.research_manager import ResearchManager
    from kairos.config.agent_definitions import render_task
    from kairos.schemas.analyst_reports import SENTIMENT_UNAVAILABLE_NOTE, sentiment_prompt_line
    lr = _fake_run(monkeypatch, DOWN)
    events = []
    prov = lr.refresh_research_evidence("RELIANCE.NS", tmp_path, lambda k, p: events.append((k, p)))
    assert prov["sources"]["sentiment"]["status"] == "UNAVAILABLE" and prov["sources"]["sentiment"]["posts"] == 0
    assert ("evidence-unavailable", {"source": "Sentiment", "reason": DOWN["reason"]}) in events
    assert not (tmp_path / "processed" / "reddit").exists()  # nothing curated or archived is written
    assert prov["sources"]["supplementary"][0]["status"] == "unavailable"  # run went on to later sources
    report = SentimentAnalyst(data_dir=str(tmp_path)).run_analysis("RELIANCE").model_dump()
    assert report["data_source"] == "SOURCE_UNAVAILABLE" and report["sample_size_posts"] == 0
    assert "NOT assessed" in report["community_source"] and "not a neutral" in report["key_themes"][0]
    reports = {"market": {}, "fundamentals": {}, "news": {}, "sentiment": report}
    assert sentiment_prompt_line(report) == SENTIMENT_UNAVAILABLE_NOTE
    for task in (BullResearcher().create_task("RELIANCE", reports), BearResearcher().create_task("RELIANCE", reports),
                 ResearchManager().create_task("RELIANCE", reports)):
        assert "NOT assessed" in task.description and "not treat this as neutral" in task.description.lower()
    assert "NOT assessed" in render_task("trading_proposal", ticker="X", risk_preference="NEUTRAL", recommendation="NEUTRAL", conviction="WEAK",
        rationale_snippet="", last_price=1, support=1, resistance=1, sma_20=1, rsi_14=1, profit_margins=1, solvency_health="OK",
        sentiment=sentiment_prompt_line(report), catalysts="", risks="", memory_context="")["description"]


def test_price_history_skips_nan_bars(monkeypatch):
    import numpy as np
    from kairos.mcp_servers import market_data
    days = pd.date_range("2026-01-01", periods=40, freq="D")
    frame = pd.DataFrame({"date": days.astype(str), "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5})
    frame.loc[39, ["open", "high", "low", "close"]] = np.nan
    monkeypatch.setattr(market_data, "_read", lambda *a: frame)
    result = market_data.get_price_history("RELIANCE")
    assert result["bars_analyzed"] == 39 and result["last_close"] == 1.5


def test_no_recent_discussion_is_not_shown_as_neutral():
    from kairos.schemas.analyst_reports import sentiment_prompt_line
    assert "no sentiment evidence" in sentiment_prompt_line({"data_source": "NO_RECENT_DISCUSSION", "retail_bull_ratio": 0.5})
