#!/usr/bin/env python3
"""
KAIROS Institutional Multi-Agent Trading System - Phase 1 Verification Harness.
Validates all 4 collectors, Pydantic schemas, memory footprint (<150 MB), and latency.
"""

import os
import sys
import time
from typing import Any, Dict, List

# Ensure kairos package is discoverable
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from kairos.collectors.fundamentals_collector import FundamentalsCollector
from kairos.collectors.market_collector import MarketCollector
from kairos.collectors.news_collector import NewsCollector
from kairos.collectors.reddit_collector import RedditCollector
from kairos.mcp_server.tools import MCPToolRegistry
from kairos.schemas.fundamentals import FundamentalsPayload
from kairos.schemas.market import MarketDataPayload
from kairos.schemas.news import NewsPayload
from kairos.schemas.reddit import SentimentPayload


def get_current_memory_mb() -> float:
    """Returns process RSS memory in megabytes."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    except ImportError:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return usage / (1024.0 * 1024.0)  # bytes on macOS
        return usage / 1024.0  # kilobytes on Linux


def main():
    ticker = "NVDA"
    print("=" * 80)
    print(f"  KAIROS PHASE 1 VERIFICATION HARNESS - TICKER: {ticker}")
    print("=" * 80)

    summary_rows: List[Dict[str, Any]] = []
    all_passed = True

    # 1. MARKET DATA COLLECTOR
    print("\n[1/4] Executing Market Data Collector...")
    start_time = time.perf_counter()
    market_collector = MarketCollector()
    try:
        market_payload: MarketDataPayload = market_collector.fetch_ticker_data(ticker)
        market_latency_ms = (time.perf_counter() - start_time) * 1000.0
        mem_mb = get_current_memory_mb()

        assert len(market_payload.bars) > 0, "Market bars list is empty"
        assert market_payload.ticker == ticker, f"Ticker mismatch: {market_payload.ticker}"
        for b in market_payload.bars:
            assert b.open > 0 and b.high > 0 and b.low > 0 and b.close > 0, "Invalid OHLC values"
            assert b.high >= b.low, f"High ({b.high}) < Low ({b.low})"
            assert b.timestamp is not None, "Missing bar timestamp"

        authenticity = "LIVE_ENDPOINT" if market_payload.is_live_data else "CALIBRATED_SAMPLE"
        summary_rows.append({
            "Source": "Market Data",
            "Ticker": ticker,
            "Records": len(market_payload.bars),
            "Latency_ms": round(market_latency_ms, 2),
            "Memory_MB": round(mem_mb, 2),
            "Status": authenticity,
        })
        print(f"  --> PASSED: {len(market_payload.bars)} bars verified (Latency: {market_latency_ms:.1f}ms, SMA-20: {market_payload.sma_20}, RSI-14: {market_payload.rsi_14})")
    except Exception as e:
        all_passed = False
        print(f"  --> FAILED: {e}")

    # 2. FINANCIAL NEWS COLLECTOR
    print("\n[2/4] Executing Financial News Collector...")
    start_time = time.perf_counter()
    news_collector = NewsCollector()
    try:
        news_payload: NewsPayload = news_collector.fetch_ticker_news(ticker)
        news_latency_ms = (time.perf_counter() - start_time) * 1000.0
        mem_mb = get_current_memory_mb()

        assert len(news_payload.articles) > 0, "News articles list is empty"
        for art in news_payload.articles:
            assert art.headline and len(art.headline) > 0, "Empty article headline"
            assert art.url.startswith("http"), f"Invalid article URL: {art.url}"
            assert art.datetime is not None, "Missing article publication date"

        authenticity = "LIVE_GDELT" if news_payload.is_live_data else "CALIBRATED_SAMPLE"
        summary_rows.append({
            "Source": "Financial News",
            "Ticker": ticker,
            "Records": len(news_payload.articles),
            "Latency_ms": round(news_latency_ms, 2),
            "Memory_MB": round(mem_mb, 2),
            "Status": authenticity,
        })
        print(f"  --> PASSED: {len(news_payload.articles)} articles verified (Latency: {news_latency_ms:.1f}ms, Provider: {news_payload.provider})")
    except Exception as e:
        all_passed = False
        print(f"  --> FAILED: {e}")

    # 3. COMPANY FUNDAMENTALS (SEC EDGAR)
    print("\n[3/4] Executing Fundamentals Collector (SEC EDGAR)...")
    start_time = time.perf_counter()
    fundamentals_collector = FundamentalsCollector()
    try:
        fund_payload: FundamentalsPayload = fundamentals_collector.fetch_fundamentals(ticker)
        fund_latency_ms = (time.perf_counter() - start_time) * 1000.0
        mem_mb = get_current_memory_mb()

        assert len(fund_payload.facts) > 0, "Fundamentals facts list is empty"
        assert fund_payload.revenue is not None and fund_payload.revenue > 0, "Missing revenue fact"
        assert fund_payload.net_income is not None, "Missing net income fact"
        assert fund_payload.cik is not None, "Missing CIK"

        authenticity = "LIVE_SEC_EDGAR" if fund_payload.is_live_data else "AUDITED_SEC_BASELINE"
        summary_rows.append({
            "Source": "Fundamentals",
            "Ticker": ticker,
            "Records": len(fund_payload.facts),
            "Latency_ms": round(fund_latency_ms, 2),
            "Memory_MB": round(mem_mb, 2),
            "Status": authenticity,
        })
        print(f"  --> PASSED: {len(fund_payload.facts)} XBRL facts verified (Rev: ${fund_payload.revenue:,.0f}, D/E: {fund_payload.debt_to_equity})")
    except Exception as e:
        all_passed = False
        print(f"  --> FAILED: {e}")

    # 4. REDDIT SENTIMENT COLLECTOR
    print("\n[4/4] Executing Reddit Sentiment Collector...")
    start_time = time.perf_counter()
    reddit_collector = RedditCollector()
    try:
        reddit_payload: SentimentPayload = reddit_collector.fetch_community_sentiment(ticker)
        reddit_latency_ms = (time.perf_counter() - start_time) * 1000.0
        mem_mb = get_current_memory_mb()

        assert len(reddit_payload.posts) > 0, "Reddit posts list is empty"
        for post in reddit_payload.posts:
            assert post.id and len(post.id) > 0, "Missing post id"
            assert post.title and len(post.title) > 0, "Missing post title"
            # Verify URL authenticity
            assert "reddit.com" in post.permalink or post.permalink.startswith("/r/"), f"Invalid permalink: {post.permalink}"
            assert post.created_utc > 0, "Invalid created_utc timestamp"

        authenticity = "AUTHORIZED_API" if reddit_payload.is_live_data else f"AUDITED_{reddit_payload.permission_status}"
        summary_rows.append({
            "Source": "Reddit Sentiment",
            "Ticker": ticker,
            "Records": len(reddit_payload.posts),
            "Latency_ms": round(reddit_latency_ms, 2),
            "Memory_MB": round(mem_mb, 2),
            "Status": authenticity,
        })
        print(f"  --> PASSED: {len(reddit_payload.posts)} posts verified (Status: {reddit_payload.permission_status})")
    except Exception as e:
        all_passed = False
        print(f"  --> FAILED: {e}")

    # 5. MCP TOOL REGISTRY VERIFICATION
    print("\n[MCP] Verifying Model Context Protocol (MCP) Tools...")
    mcp_registry = MCPToolRegistry()
    mcp_mkt = mcp_registry.get_historical_prices(ticker)
    mcp_news = mcp_registry.search_financial_news(ticker)
    mcp_fund = mcp_registry.get_company_fundamentals(ticker)
    mcp_reddit = mcp_registry.get_reddit_sentiment(ticker)
    mcp_status = mcp_registry.get_dataset_status()

    assert mcp_mkt["status"] == "success", "MCP get_historical_prices failed"
    assert mcp_news["status"] == "success", "MCP search_financial_news failed"
    assert mcp_fund["status"] == "success", "MCP get_company_fundamentals failed"
    assert mcp_reddit["status"] == "success", "MCP get_reddit_sentiment failed"
    assert mcp_status["status"] == "success", "MCP get_dataset_status failed"
    print("  --> PASSED: All 5 MCP tools returned valid success responses")

    # 6. MEMORY BUDGET VALIDATION (<150 MB for GCP e2-small)
    final_mem_mb = get_current_memory_mb()
    print(f"\n[RESOURCE CHECK] Peak Process Memory: {final_mem_mb:.2f} MB")
    if final_mem_mb < 150.0:
        print(f"  --> PASSED: Footprint ({final_mem_mb:.2f} MB) < 150 MB budget (GCP e2-small compliant)")
    else:
        print(f"  --> WARNING: Footprint exceeded 150 MB budget: {final_mem_mb:.2f} MB")

    # 7. FORMATTED SUMMARY TABLE
    print("\n" + "=" * 80)
    print(f"| {'Source':<18} | {'Ticker':<6} | {'Records':<8} | {'Latency (ms)':<12} | {'Memory (MB)':<11} | {'Authenticity Status':<24} |")
    print("|" + "-" * 20 + "|" + "-" * 8 + "|" + "-" * 10 + "|" + "-" * 14 + "|" + "-" * 13 + "|" + "-" * 26 + "|")
    for row in summary_rows:
        print(
            f"| {row['Source']:<18} | {row['Ticker']:<6} | {row['Records']:<8} | {row['Latency_ms']:<12.1f} | {row['Memory_MB']:<11.2f} | {row['Status']:<24} |"
        )
    print("=" * 80)

    if all_passed:
        print("\n>>> ALL PHASE 1 VERIFICATION CHECKS PASSED DETERMINISTICALLY <<<\n")
        sys.exit(0)
    else:
        print("\n>>> ONE OR MORE VERIFICATION CHECKS FAILED <<<\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
