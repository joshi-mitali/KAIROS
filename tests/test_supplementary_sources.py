"""Offline tests for kairos.sources (mocked HTTP, no network)."""
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import kairos.sources as src
from kairos.sources import feeds, ir, world
from kairos.sources._http import SourceError, matches_entity, parse_date, parse_feed

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Reliance Industries Limited</title><link>https://x/1</link>
 <description><![CDATA[<p>Q2 <b>results</b></p>]]></description><pubDate>16-Nov-2026 10:00:00</pubDate></item>
<item><title>Other Co Ltd</title><link>https://x/2</link><description>d</description><pubDate>16-Nov-2026 09:00:00</pubDate></item>
<item><title>Reliance Industries Limited</title><link>https://x/old</link><description>old</description><pubDate>01-Sep-2026 09:00:00</pubDate></item>
</channel></rss>"""
ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>TCS wins deal</title>
<link href="https://a/1"/><summary>s</summary><updated>2026-11-15T10:00:00+05:30</updated></entry></feed>"""


def resp(content=b"", text=None, status=200):
    m = MagicMock(status_code=status, content=content, text=text if text is not None else content.decode())
    m.json.side_effect = lambda: __import__("json").loads(m.text)
    return m


def test_parse_rss_and_atom():
    e = parse_feed(RSS)
    assert [x["link"] for x in e][:2] == ["https://x/1", "https://x/2"]
    assert e[0]["summary"] == "Q2 results" and e[0]["published"].year == 2026
    a = parse_feed(ATOM)[0]
    assert a["link"] == "https://a/1" and a["published"].day == 15


def test_parse_date_formats_and_bad_xml():
    assert parse_date("Mon, 16 Nov 2026 19:25:00").hour == 19
    assert parse_date("16 Nov 2026 22:00:06") and parse_date("20261116T120000Z") and parse_date("nope") is None
    with pytest.raises(SourceError):
        parse_feed(b"<html><b></html>")


def test_matching():
    assert matches_entity("Reliance Industries Limited", "RELIANCE", "Reliance Industries Ltd")
    assert not matches_entity("Reliance Power Limited", "RELIANCE", "Reliance Industries Limited")
    assert matches_entity("Order for TCS", "TCS", "") and not matches_entity("Tcs tax", "TCS", "")


def test_nse_ticker_match_and_window():
    with patch.object(feeds, "get", return_value=resp(RSS)):
        out = feeds.nse_announcements("RELIANCE", "Reliance Industries Limited", NOW)
    assert out["status"] == "ok" and len(out["items"]) == len(feeds.NSE_FEEDS)  # one match per mocked feed; old + other company dropped
    assert out["items"][0]["relevance"] == "TICKER_SPECIFIC" and out["items"][0]["summary"] == "Q2 results"
    with patch.object(feeds, "get", return_value=resp(RSS)):
        assert feeds.nse_announcements("INFY", "Infosys Limited", NOW)["status"] == "empty"


def test_rbi_market_context_and_all_feeds_failing():
    with patch.object(feeds, "get", return_value=resp(RSS)):
        out = feeds.rbi("X", "", NOW)
    assert {i["relevance"] for i in out["items"]} == {"MARKET_CONTEXT"}
    with patch.object(feeds, "get", side_effect=SourceError("HTTP 403")), pytest.raises(SourceError):
        feeds.rbi("X", "", NOW)


def test_sebi_limits_general_items():
    many = b"<rss><channel>" + b"".join(
        b"<item><title>Circular %d</title><link>https://s/%d</link><pubDate>16 Nov 2026 10:00:00 +0530</pubDate></item>" % (i, i) for i in range(8)
    ) + b"</channel></rss>"
    with patch.object(feeds, "get", return_value=resp(many)):
        assert len(feeds.sebi("INFY", "Infosys Limited", NOW)["items"]) == 3


def test_ir_links_and_unknown_ticker():
    page = ('<a href="/nav">Reports, Results &amp; Presentations</a>'
            '<a href="/q2.pdf">Q2 FY27 Earnings Presentation</a><a href="/x.pdf">Call transcript 14 Oct 2026</a>')
    got = ir.extract_links(page, "https://co.example/ir")
    assert [i["url"] for i in got] == ["https://co.example/q2.pdf", "https://co.example/x.pdf"]
    assert got[1]["published_at"].startswith("2026-10-14")
    assert ir.company_ir("ZOMATO.NS", "", NOW)["status"] == "not_configured"


WB = '[{"page":1},[{"indicator":{"id":"X"},"date":"2025","value":7.5666}]]'


def test_world_bank_parsing():
    with patch.object(world, "get", return_value=resp(text=WB)):
        out = world.world_bank("X", "", NOW)
    assert out["as_of"] == "2025" and len(out["items"]) == 4
    it = out["items"][0]
    assert it["value"] == 7.57 and it["period"] == "2025" and it["published_at"] is None and it["url"].startswith("https://data.worldbank.org/")
    with patch.object(world, "get", return_value=resp(text='[{"message":[{"id":"120"}]}]')), pytest.raises(SourceError):
        world.world_bank("X", "", NOW)


def test_gdelt_ok_and_error_text():
    world._gdelt_last[0] = time.monotonic() - 10
    ok = '{"articles":[{"url":"https://n/1","title":"Reliance <b>up</b>","seendate":"20261116T120000Z","domain":"n","language":"English"}]}'
    with patch.object(world, "get", return_value=resp(text=ok)):
        out = world.gdelt("RELIANCE.NS", "Reliance Industries Limited", NOW)
    assert out["items"][0]["title"] == "Reliance up" and out["items"][0]["published_at"].startswith("2026-11-16")
    world._gdelt_last[0] = time.monotonic() - 10
    with patch.object(world, "get", return_value=resp(text="Please limit requests to one every 5 seconds")), pytest.raises(SourceError, match="non-JSON"):
        world.gdelt("RELIANCE.NS", "Reliance", NOW)


def test_collect_never_raises_and_flags_failures():
    boom = MagicMock(side_effect=RuntimeError("boom"))
    ok = MagicMock(return_value={"status": "ok", "items": [{"title": "t", "url": "u"}] * 15, "as_of": "2026-11-16"})
    patched = {k: (ok if k == "rbi" else boom, *v[1:]) for k, v in src.SOURCES.items()}
    with patch.dict(src.SOURCES, patched):
        res = src.collect_supplementary("RELIANCE.NS", "Reliance Industries Limited", NOW)
    assert len(res) == 8 and {r["id"] for r in res} == set(src.SOURCES)
    by = {r["id"]: r for r in res}
    assert by["rbi"]["status"] == "ok" and len(by["rbi"]["items"]) == 10  # capped
    assert by["sebi"]["status"] == "unavailable" and "boom" in by["sebi"]["reason"] and by["sebi"]["items"] == []
    assert all(r["usage_note"] and r["retrieved_at"] and r["category"] for r in res)


def test_collect_timeout():
    def slow(*a):
        time.sleep(1.0)
        return {"status": "ok", "items": []}
    patched = {k: (slow if k == "rbi" else v[0], *v[1:]) for k, v in src.SOURCES.items()}
    with patch.dict(src.SOURCES, patched), patch.object(src, "PER_SOURCE_TIMEOUT", 0.2), \
            patch.object(src, "SOURCE_TIMEOUTS", {}), patch.object(src.feeds, "get", side_effect=SourceError("HTTP 500")):
        res = {r["id"]: r for r in src.collect_supplementary("X.NS", "", NOW)}
    assert res["rbi"]["status"] == "unavailable" and res["rbi"]["reason"] == "timed out"


def test_supplementary_context_handles_missing_cells(tmp_path):
    import pandas as pd
    from kairos.agents.adk_analysts.base_analyst import BaseADKAnalyst

    d = tmp_path / "processed" / "supplementary"
    d.mkdir(parents=True)
    cols = ["source_id", "source_name", "category", "title", "summary", "url", "published_at", "period", "indicator", "value", "unit"]
    rows = [
        ["nse_rss", "NSE", "filings", "Result", "Q2", "https://x/1", "2026-11-16", None, None, None, None],
        ["world_bank", "World Bank", "macro", "GDP growth", None, "https://w/1", None, "2024", "GDP", 6.5, "%"],
    ]
    pd.DataFrame(rows, columns=cols).to_parquet(d / "reliance.ns_evidence.parquet")
    text = BaseADKAnalyst(data_dir=str(tmp_path)).supplementary_context("RELIANCE.NS", ["filings"])
    assert "nan" not in text.lower() and "None" not in text
    assert "undated" in text and "data year 2024" in text and "GDP 6.5 %" in text
