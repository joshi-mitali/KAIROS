import json
import time
from unittest.mock import Mock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from kairos.web.app import create_app

XSS = "<script>alert(1)</script>"


def result(rationale="Balanced."):
    market = {"ticker": "TCS", "as_of_date": "2026-11-13", "last_price": 100.0, "indicators": {"sma_20": 99.5, "rsi_14": 55.0},
              "execution_mode": "LIVE_ADK_MODEL", "generated_at": "2026-11-16T10:00:00+00:00", "key_observations": [XSS]}
    news = {"ticker": "TCS", "news_sentiment": "NEUTRAL", "top_verified_articles": [
        {"headline": "Good <b>news</b>", "url": "javascript:alert(1)", "source": "S", "published_at": "2026-11-13"}]}
    fund = {"ticker": "TCS", "company_name": "Tata Consultancy Services", "reporting_currency": "INR", "fiscal_period_end": "2026-03-31",
            "revenue": 2.4e12, "net_income": 4.6e11, "total_assets": 1.5e12, "total_liabilities": 5e11, "operating_cash_flow": 5e11}
    rounds = [{"round": 1, "bull_argument": {"primary_arguments": [XSS], "conviction_level": "STRONG"},
               "bear_counterargument": {"primary_arguments": ["x"], "conviction_level": "WEAK"}}]
    return {"analyst_reports": {"market": market, "news": news, "fundamentals": fund, "sentiment": {"ticker": "TCS", "overall_sentiment": "NEUTRAL"}},
            "verdict": {"recommendation": "BUY", "conviction": "STRONG", "synthesis_rationale": rationale, "bull_summary": "b", "bear_summary": "r", "limitations": ["Delayed quote"]},
            "trading_proposal": {"direction": "BUY", "entry_price": 100.0, "stop_loss": 90.0, "target": 120.0, "risk_reward_ratio": 2.0, "time_horizon": "4 weeks", "rationale": "r"},
            "provenance": {"retrieved_at": "2026-11-16T09:59:00+00:00", "sources": {"sentiment": {"status": "UNAVAILABLE", "reason": "403 from Reddit", "attempts": []},
                "supplementary": [{"id": "a", "name": "Src A", "status": "ok", "url": "https://example.com", "item_count": 1}, {"id": "b", "name": "Src B", "status": "unavailable", "reason": "down"}]}}}, rounds


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("KAIROS_WEB_PASSWORD", raising=False)
    app = create_app(data_dir=tmp_path, runtime_dir=tmp_path / "runtime", paper_client=Mock())
    app.state.runs.worker.submit = Mock()
    with TestClient(app) as client:
        client.post("/api/session", json={})
        yield client, app.state.runs, tmp_path / "runtime"


def seed(client, runs, status="COMPLETED", res=None, rounds=None, error=None):
    run_id = "ab12cd34ef56" + "0" * 20
    runs.db.query("INSERT INTO research_runs VALUES(?,?,?,?,?,?,?,?,?)", (run_id, client.cookies.get("kairos_session").split(".")[0], "TCS", "NEUTRAL", "live", status, time.time(), json.dumps(res) if res else None, error))
    t = time.time()
    runs.emit(run_id, "run-started", {})
    runs.emit(run_id, "agent-started", {"agent": "google_adk.market_analyst"})
    runs.emit(run_id, "agent-completed", {"agent": "google_adk.market_analyst", "report": {"ticker": "TCS", "as_of_date": "2026-11-13", "last_price": 100.0}})
    runs.emit(run_id, "guardrail-result", {"result": {"status": "PASSED", "source": "news_analyst", "max_attack_score": 0.01, "model": "m", "chunks": 2}})
    if rounds:
        runs.emit(run_id, "debate-completed", {"rounds": rounds})
    runs.emit(run_id, "run-completed" if status == "COMPLETED" else "run-failed", {})
    return run_id


def test_completed_report_attachment_charts_and_escaping(env):
    client, runs, _ = env
    res, rounds = result()
    run_id = seed(client, runs, res=res, rounds=rounds)
    ev = env[2] / "evidence" / run_id / "processed" / "market"
    ev.mkdir(parents=True)
    pd.DataFrame({"date": [f"2026-11-{d:02d}" for d in range(1, 11)], "close": range(90, 100), "sma_20": [None] * 9 + [95.0], "sma_50": [None] * 10}).to_parquet(ev / "tcs_price_history.parquet")
    response = client.get(f"/api/runs/{run_id}/report")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith('attachment; filename="KAIROS_TCS_') and response.headers["content-disposition"].endswith(f'_{run_id[:8]}.html"')
    body = response.text
    assert "<script" not in body and XSS not in body and "&lt;script&gt;" in body
    assert 'href="javascript' not in body
    assert "Good &lt;b&gt;news&lt;/b&gt;" in body
    assert body.count("<svg") >= 4 and "Tata Consultancy Services" in body
    assert "Sentiment unavailable" in body and "Price history not recorded" not in body
    assert "PASSED" in body and "Src B" in body and "Paper-research only" in body


def test_print_mode_inline_with_script(env):
    client, runs, _ = env
    res, rounds = result()
    run_id = seed(client, runs, res=res, rounds=rounds)
    response = client.get(f"/api/runs/{run_id}/report?print=1")
    assert "content-disposition" not in response.headers and "print()" in response.text and "<script>" in response.text


def test_failed_run_and_missing_price(env):
    client, runs, _ = env
    run_id = seed(client, runs, status="FAILED", error="Yahoo down")
    body = client.get(f"/api/runs/{run_id}/report").text
    assert "did not complete" in body and "Yahoo down" in body
    assert "Price history not recorded for this run" in body and "Not recorded for this run" in body
    assert "market analyst" in body  # stage still shown from events
    assert "<script" not in body


def test_unfinished_unknown_and_foreign_owner(env):
    client, runs, _ = env
    run_id = seed(client, runs, status="RUNNING")
    assert client.get(f"/api/runs/{run_id}/report").status_code == 409
    assert client.get("/api/runs/nope/report").status_code == 404
    client.cookies.clear()
    assert client.get(f"/api/runs/{run_id}/report").status_code == 401
    client.post("/api/session", json={})
    assert client.get(f"/api/runs/{run_id}/report").status_code == 404
