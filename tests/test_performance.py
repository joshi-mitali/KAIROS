"""Concurrent evidence, Reddit time budget, parallel analysts, Groq 429 retry and deterministic trader levels (all offline)."""
import asyncio
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from kairos.collectors import reddit_collector as rc
from kairos.schemas.trading_proposal import TradeDirection, TradingProposal
from tests.test_reddit_acquisition import DOWN, QUIET, SETTINGS, NOW, _fake_run, resp, session


def _events(tmp_path, monkeypatch, meta=QUIET, supplementary=None):
    lr = _fake_run(monkeypatch, meta)
    if supplementary:
        import sys
        monkeypatch.setitem(sys.modules, "kairos.sources", SimpleNamespace(collect_supplementary=supplementary))
    events = []
    return lr, events, lambda k, p: events.append((k, p))


def test_sources_emit_started_and_done_with_elapsed(tmp_path, monkeypatch):
    def supp(symbol, name, now, on_event=None):
        on_event("evidence-source-started", {"source_id": "rbi", "name": "RBI", "group": "supplementary"})
        on_event("evidence-source-done", {"source_id": "rbi", "name": "RBI", "group": "supplementary", "status": "ok",
                                          "elapsed_ms": 5, "items": 2, "reason": None})
        return [{"id": "rbi", "name": "RBI", "category": "macro", "status": "ok", "items": [{"title": "t"}], "elapsed_ms": 5}]
    lr, events, emit = _events(tmp_path, monkeypatch, supplementary=supp)
    prov = lr.refresh_research_evidence("RELIANCE.NS", tmp_path, emit)
    done = {p["source_id"]: p for k, p in events if k == "evidence-source-done"}
    assert {s for k, p in events if k == "evidence-source-started" for s in [p["source_id"]]} == {"fundamentals", "news", "reddit", "rbi"}
    assert {i: (p["group"], p["status"]) for i, p in done.items()} == {
        "fundamentals": ("required", "ok"), "news": ("required", "ok"), "reddit": ("sentiment", "no_recent_discussion"), "rbi": ("supplementary", "ok")}
    assert all(isinstance(p["elapsed_ms"], int) and {"name", "items", "reason"} <= p.keys() for p in done.values())
    assert prov["sources"]["supplementary"][0]["elapsed_ms"] == 5
    assert any(k == "evidence-refreshed" and p["source"] == "News" for k, p in events)  # legacy events kept


def test_reddit_unavailable_is_reported_not_fatal(tmp_path, monkeypatch):
    lr, events, emit = _events(tmp_path, monkeypatch, DOWN)
    lr.refresh_research_evidence("RELIANCE.NS", tmp_path, emit)
    reddit = next(p for k, p in events if k == "evidence-source-done" and p["source_id"] == "reddit")
    assert reddit["status"] == "unavailable" and reddit["reason"] == DOWN["reason"]


def test_required_source_failure_fails_the_run(tmp_path, monkeypatch):
    lr, events, emit = _events(tmp_path, monkeypatch)
    monkeypatch.setattr(lr.yf, "Ticker", lambda s: SimpleNamespace(
        get_info=lambda: {"longName": "X", "financialCurrency": "INR"}, income_stmt=None, balance_sheet=None, cash_flow=None,
        get_news=lambda **k: []))
    with pytest.raises(ValueError, match="temporarily unavailable"):
        lr.refresh_research_evidence("RELIANCE.NS", tmp_path, emit)
    failed = {p["source_id"] for k, p in events if k == "evidence-source-done" and p["status"] == "failed"}
    assert failed and failed <= {"news", "fundamentals"}


def test_evidence_sources_overlap(tmp_path, monkeypatch):
    lr, events, emit = _events(tmp_path, monkeypatch)
    slow = lambda *a, **k: (time.sleep(0.3), ([], QUIET))[1]
    monkeypatch.setattr(lr, "fetch_reddit_evidence", slow)
    real_get = lr.requests.get
    monkeypatch.setattr(lr.requests, "get", lambda *a, **k: (time.sleep(0.3), real_get(*a, **k))[1])
    t = time.monotonic()
    lr.refresh_research_evidence("RELIANCE.NS", tmp_path, emit)
    assert time.monotonic() - t < 0.55  # reddit and news verification (0.3 s each) ran side by side


def test_reddit_budget_stops_after_429_without_sleeping_past_it(monkeypatch):
    clock = [0.0]
    sleeps = []
    monkeypatch.setattr(rc, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s))))
    s = MagicMock()
    s.get.side_effect = lambda *a, **k: resp(429, headers={"Retry-After": "5"})
    posts, meta = rc.fetch_reddit_evidence("RELIANCE.NS", "Reliance Industries Limited", NOW, s, SETTINGS, budget=4.0)
    assert posts == [] and meta["status"] == "UNAVAILABLE"
    assert sum(sleeps) == 0 and s.get.call_count == 3  # search + two subreddit feeds, none retried or slept on
    clock[0] = 10.0  # budget gone: no request at all
    s.get.reset_mock()
    posts, meta = rc.fetch_reddit_evidence("RELIANCE.NS", "Reliance Industries Limited", NOW, s, SETTINGS, budget=0)
    assert s.get.call_count == 0 and meta["status"] == "UNAVAILABLE"


def test_collect_supplementary_reports_each_source_and_elapsed():
    from kairos import sources as src
    events = []
    ok = lambda *a: {"status": "ok", "items": [{"title": "t"}], "as_of": None}
    slow = lambda *a: time.sleep(2) or {"status": "ok", "items": []}
    patched = {k: (slow if k == "sebi" else ok, *v[1:]) for k, v in src.SOURCES.items()}
    with patch.dict(src.SOURCES, patched), patch.object(src, "PER_SOURCE_TIMEOUT", 0.3), patch.object(src, "SOURCE_TIMEOUTS", {}):
        res = src.collect_supplementary("X.NS", "X", NOW, on_event=lambda k, p: events.append((k, p)))
    assert [r["id"] for r in res] == list(src.SOURCES) and all(isinstance(r["elapsed_ms"], int) for r in res)
    done = {p["source_id"]: p for k, p in events if k == "evidence-source-done"}
    assert len(done) == len(src.SOURCES) and done["sebi"]["status"] == "unavailable" and done["sebi"]["reason"] == "timed out"
    assert done["rbi"]["status"] == "ok" and done["rbi"]["items"] == 1 and done["rbi"]["group"] == "supplementary"
    assert sum(k == "evidence-source-started" for k, _ in events) == len(src.SOURCES)


def test_analysts_run_concurrently():
    import kairos.phase2_orchestrator as po

    class Slow:
        def analyze(self, ticker, trace_id=None):
            time.sleep(0.2)
            return MagicMock()

    async def market(*a, **k):
        await asyncio.sleep(0.2)
        return {}

    class Stop(Exception):
        pass

    orch = po.Phase2Orchestrator.__new__(po.Phase2Orchestrator)
    orch.sentiment_analyst = orch.news_analyst = orch.fundamentals_analyst = Slow()
    orch.standard_a2a = None
    with patch.object(po, "call_agent", market), patch("kairos.schemas.analyst_reports.MarketAnalysisReport.model_validate", lambda d: MagicMock()), \
            patch.object(po, "A2ATaskEnvelope", side_effect=Stop):
        t = time.monotonic()
        with pytest.raises(Stop):
            orch.analyze_ticker("RELIANCE")
    assert time.monotonic() - t < 0.5  # four 0.2 s analysts


def test_groq_429_gets_one_short_jittered_retry(monkeypatch):
    from kairos.providers import groq
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEYS", "")
    groq.get_key_pool.cache_clear()
    sleeps = []
    monkeypatch.setattr(groq.time, "sleep", sleeps.append)
    limited = type("E", (Exception,), {"status_code": 429, "response": SimpleNamespace(headers={"retry-after": "2"})})()
    calls = MagicMock(side_effect=[limited, "ok"])
    client = groq.GroqPoolClient()
    client.clients["k"] = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=calls)))
    clock = [0.0]
    monkeypatch.setattr(groq.time, "monotonic", lambda: clock[0] + sum(sleeps))
    assert client.create(model="m") == "ok" and calls.call_count == 2
    assert 2 <= sleeps[0] <= 2.5
    # a long Retry-After is not waited for
    groq.get_key_pool.cache_clear()
    long = type("E", (Exception,), {"status_code": 429, "response": SimpleNamespace(headers={"retry-after": "60"})})()
    client.clients["k"] = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=MagicMock(side_effect=long))))
    with pytest.raises(groq.GroqCooldownError):
        client.create(model="m")
    assert len(sleeps) == 1
    groq.get_key_pool.cache_clear()


def _proposal(direction, entry, stop, target, **kw):
    return TradingProposal(ticker="X", direction=direction, entry_price=entry, stop_loss=stop, target=target, time_horizon="1M",
                           confidence=0.6, rationale="r", data_freshness="f", risk_warnings=["w"], risk_reward_ratio=9.9, **kw)


def test_risk_reward_is_computed_from_levels_not_the_model():
    buy = _proposal(TradeDirection.BUY, 100, 90, 120)
    assert buy.risk_reward_ratio == 2.0 and not buy.levels_reference_only and buy.level_adjustments == []
    sell = _proposal(TradeDirection.SELL, 100, 110, 85)
    assert sell.risk_reward_ratio == 1.5


def test_hold_levels_are_reference_only_with_no_risk_reward():
    hold = _proposal(TradeDirection.HOLD, 1344.80, 1094.59, 1418.23)
    assert hold.levels_reference_only and hold.risk_reward_ratio == 0.0
    assert (hold.entry_price, hold.stop_loss, hold.target) == (1344.8, 1094.59, 1418.23)


def test_inconsistent_levels_are_repaired_and_flagged():
    p = _proposal(TradeDirection.BUY, 100, 105, 95)
    assert p.stop_loss < p.entry_price < p.target and len(p.level_adjustments) == 2
    assert all(note in p.risk_warnings for note in p.level_adjustments)
    again = TradingProposal.model_validate(p.model_dump())  # re-validation neither repairs nor warns twice
    assert again.level_adjustments == p.level_adjustments and again.risk_warnings == p.risk_warnings


def test_run_list_summarises_result_and_gaps(tmp_path):
    from kairos.web.runs import RunStore, encode
    store = RunStore(tmp_path / "runs.db", tmp_path)
    store.worker.submit = MagicMock()
    run_id = store.create("o", "RELIANCE.NS", "NEUTRAL", "live")
    prov = {"sources": {"sentiment": {"status": "UNAVAILABLE"}, "supplementary": [{"name": "GDELT", "status": "unavailable"}, {"name": "RBI", "status": "ok"}]}}
    store.db.query("UPDATE research_runs SET status='COMPLETED',result=? WHERE id=?",
                   (encode({"verdict": {"recommendation": "NEUTRAL"}, "trading_proposal": {"direction": "HOLD"}, "provenance": prov}), run_id))
    store.emit(run_id, "run-completed", {})
    row = store.list("o")[0]
    assert (row["recommendation"], row["direction"], row["data_gaps"]) == ("NEUTRAL", "HOLD", ["Sentiment", "GDELT"])
    assert row["duration_s"] >= 0 and "result" not in row


def _provider(fast_currency="INR", info=None):
    p = MagicMock()
    p.get_history_metadata.side_effect = TimeoutError("chart")
    p.fast_info = {"currency": fast_currency} if fast_currency else {}
    if isinstance(info, Exception):
        p.get_info.side_effect = info
    else:
        p.get_info.return_value = info or {}
    return p


def _search(quotes):
    return patch("kairos.pipeline.live_research.yf.Search", return_value=SimpleNamespace(quotes=quotes))


def test_company_identity_skips_slow_get_info():
    from kairos.pipeline.live_research import company_identity
    provider = _provider(info=TimeoutError("crumb"))
    with _search([{"symbol": "OTHER.NS", "longname": "Wrong"}, {"symbol": "RELIANCE.NS", "longname": "Reliance Industries Limited"}]):
        got = company_identity("RELIANCE.NS", provider)
    assert got["longName"] == "Reliance Industries Limited" and got["currency"] == "INR"
    assert got["origin"]["currency"].startswith("yfinance fast_info")
    provider.get_info.assert_not_called()


def test_company_identity_falls_back_to_get_info_and_fails_closed():
    from kairos.pipeline.live_research import company_identity
    with _search([]):
        got = company_identity("RELIANCE.NS", _provider(fast_currency=None, info={"longName": "Reliance", "financialCurrency": "INR"}))
        assert got["origin"] == {"company_name": "yfinance get_info", "currency": "yfinance get_info (financialCurrency)"}
        with patch("kairos.providers.yahoo.time.sleep"), pytest.raises(Exception):
            company_identity("RELIANCE.NS", _provider(fast_currency=None, info=TimeoutError("down")))
