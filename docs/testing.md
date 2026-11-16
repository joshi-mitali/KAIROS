# Verification record — 16 November 2026

Production React/TypeScript build passes. The final isolated regression passed 99 tests with 7 skips, including API, market feed, approval, pool, guard, agent/debate/trader/memory and report configuration coverage. The focused API and safeguard subset passed 33 tests. Populated streaming-debate browser states remain unverified because fresh sentiment acquisition is blocked. Four broader data-quality expectations were reproduced on the original baseline and are not claimed resolved.

Browser checks used the shared T3 browser at desktop and mobile widths: research, source refresh events, click-to-inspect pipeline, reports tabs, paper account, live candles and quote reception. The layout had no horizontal overflow at 390 and 1440 CSS pixels. Mobile hidden navigation is removed from keyboard traversal. Search listboxes have unique IDs. Source failures are visible. No paper orders were submitted.

Live Groq Prompt Guard passed a benign financial statement and blocked an injection example. Real ADK Runner made two MCP calls; standard a2a-sdk transport carried the validated market report and CrewAI request. Live CrewAI debate completed during a saved-evidence diagnostic, but its final proposal was blocked by Prompt Guard; this is not a completed successful live-only run.

After enforcing fresh-only research, financials and news refreshed, then Reddit returned HTTP 403. The run stopped instead of using curated sentiment. Full successful live-only end-to-end research remains unverified until that source is accessible or an explicitly approved suitable sentiment provider is configured. A guard false-positive also remains possible and must be evaluated, not silently bypassed.

Langfuse observations were fetched from US Cloud using the official skill CLI. A diagnostic research trace contains real generations, guardrail checks, ADK/CrewAI work and memory retrieval: https://us.cloud.langfuse.com/project/cmwjh9m87011aad0g0ndjn6jq/traces/15cfa7a09651b7976576761e994eebe8 . Remote export experienced intermittent timeouts. Returned zero costs are not a verified free run: provider/model pricing is not fully mapped. Do not claim investment accuracy or calibrated confidence from these tests.

Render deployment remains deferred by the owner. Docker/Render configuration has been prepared; no cloud deployment is claimed.

## Yahoo outage hardening

A direct probe returned live Yahoo search, chart and news data. The yfinance outage banner was therefore not evidence of a continuous global outage. Shared Yahoo calls now make at most two attempts, validate empty results, and return operation-specific errors. Stock search falls back to exchange-verified MegaBull instruments. When historical chart fetches fail, paper trading switches to actual observed MegaBull quotes with an explicit history-unavailable notice. Research does not invent missing history, news or financials.

Outage/provider/API/approval regression: 29 passed. Production frontend build passed. Live verification returned 2 Yahoo search results and 74 chart bars. A forced Yahoo search outage successfully used the real MegaBull instrument/quote fallback; a separate MegaBull quote request timed out, so provider connectivity remains intermittent. The changed outage display was build-checked; no new browser automation was run for this fix.

## Reddit acquisition and supplementary sources (17 Nov 2026)

`tests/test_reddit_acquisition.py` (mocked HTTP) covers 429 retry with capped Retry-After, no retry on 403, search 429 falling back to per-subreddit `new/.rss` with alias filtering, all-403 raising, reachable-but-empty giving `NO_RECENT_DISCUSSION` and a neutral sentiment report, OAuth used when credentials are set, and a failing `collect_supplementary` not stopping a run.

Live check (RELIANCE.NS, no LLM calls, no Reddit credentials): Reddit was NOT reachable. `search.rss` returned HTTP 403 and all three `new/.rss` feeds returned HTTP 429 after retries, so the function raised the "Fresh Reddit evidence is unavailable" error and no posts were obtained. Earlier probes the same day got 200 from `r/IndianStockMarket/new/.rss`, so availability is intermittent and IP rate-limit dependent. Setting `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` enables the OAuth path, which was not exercised live.

Full suite: 157 passed, 13 failed, 7 skipped, 2 errors. The failures and errors are in the live MCP, market collector, phase 1 audit and MCP tool tests (missing `mcp-server-reddit` command, network and data dependencies, a broken fixture in `kairos/verification/live_mcp.py`), not in the Reddit or research-evidence code.

## 17 November 2026 — sources, Reddit, UI

Fixes: `supplementary_context` no longer renders pandas NaN as "nan" (new test with mixed RSS/World Bank rows); the evidence tab strip scrolls the selected tab (Sources) into view; `HistoryCollector` skips non-finite (NaN) provider bars; test-only fixes: `test_live_*` helpers in `kairos/verification/live_mcp.py` are imported as a module so pytest no longer collects them as fixture-requiring tests, the yfinance stdio test skips when the venv launcher is not executable (its shebang points at another machine), the Alpha Vantage no-credential test passes an explicit empty key, the mock-transport test forces the live call to fail, and live-service MCP tests skip with a reason when NSE (HTTP 400), `mcp-server-reddit` or Alpha Vantage entitlement is unavailable.

Offline suite: 173 passed, 3 failed, 11 skipped. The 3 remaining failures are in `tests/test_phase1_data_quality_audit.py` (fundamentals, 10y bar count/last date, news count) and all concern RELIANCE: its processed files in `data/` were rewritten on 1–2 Nov by an earlier pipeline run (placeholder-looking fundamentals, 3 template news items, bars ending 2026-10-30) while the other four tickers still match the 27 Oct audit snapshot. `data/` was not modified; these are genuine data-quality findings, unresolved. Frontend build passes.

Live supplementary sources (RELIANCE.NS): company_ir ok (10), rbi ok (10), mospi_mcp ok (3), nse_mcp ok (2), world_bank ok (4), nse_announcements empty, sebi empty, gdelt unavailable (HTTP 429).

Real research run (RELIANCE, NEUTRAL, id 00a5a30ba884467b9e33e1655c64d6c4): fundamentals and news refreshed, then FAILED at Reddit by design: rss_search HTTP 403, rss_subreddit_new HTTP 429 x3; no sentiment substituted. The run never reached supplementary collection or analysts, so `provenance.sources.supplementary` and supplementary prompt content are unverified live (covered only by unit tests). OAuth path not exercised (no credentials).

Browser (T3 preview, 1440 and 390 px): research, stock search, pipeline, Sources tab (390 px: now scrolled into view and selected), run history (empty for the browser session), paper trading (quote and virtual balance shown); no console errors, no horizontal overflow. No paper order submitted or approved. Populated Sources/evidence tabs from a completed run remain unverified.

## 17 November 2026 — pipeline without Reddit

Change: when every Reddit method fails, the run now continues (provenance `sentiment.status` `UNAVAILABLE` with attempts and reason, an `evidence-unavailable` event, no posts written, analyst report `data_source` `SOURCE_UNAVAILABLE`). Debate (bull, bear), research manager and trader prompts receive an explicit "sentiment NOT assessed, do not treat as neutral" line; zero-post `NO_RECENT_DISCUSSION` gets a similar "no sentiment evidence" line. Yahoo fundamentals and news stay fail-closed. Anonymous `.json` probing was removed from the CLI collector. New tests cover unavailable provenance, the analyst report, and the debate/manager/trader prompt text.

Offline suite: 171 passed, 3 failed (the same 3 RELIANCE `test_phase1_data_quality_audit` tests), 12 skipped (one more live-service skip than before, network dependent). `npm run build` passes.

Real runs (RELIANCE, NEUTRAL, via the API from the browser session): run 21cbd377... FAILED in the market analyst because Yahoo returned a NaN bar and the market MCP tool raised "Out of range float values"; fixed in `kairos/mcp_servers/market_data.py` (drop non-finite OHLC rows, test added). Run d7273b07... COMPLETED: fundamentals and news refreshed (1 verified article); Reddit was reachable this time (rss_search 403, first subreddit feed 200, two more 429) with 0 matching posts, so `NO_RECENT_DISCUSSION`, not `UNAVAILABLE`; supplementary 5 of 8 ok (company_ir 10, rbi 10, mospi_mcp 3, nse_mcp 2, world_bank 4; nse_announcements and sebi empty; gdelt HTTP 429); all four analysts, two debate rounds, manager verdict NEUTRAL/MODERATE, Prompt Guard PASSED on every check (max score 0.0037), trader proposal HOLD (no order created, nothing approved). The live `UNAVAILABLE` path was not hit; it is covered by unit tests and by a Sources-tab render with a patched API response.

Browser (T3 preview): Sources tab populated from the real run, all evidence tabs, proposal panel, paper trading view and run history render with no horizontal overflow at 1440 and 390 px (document width 383 at 390 px). The preview ignores freeform sizes above 1280 wide for its reported viewport, but the page measured 1440.
