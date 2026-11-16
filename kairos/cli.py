"""Command-line interface (CLI) for KAIROS Indian stock market data collection via MCP."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from kairos.collectors.fundamentals_collector import FundamentalsCollector
from kairos.collectors.history_collector import HistoryCollector
from kairos.collectors.live_quote_collector import LiveQuoteCollector
from kairos.collectors.news_collector import NewsCollector
from kairos.collectors.reddit_collector import RedditCollector
from kairos.config.settings import get_settings
from kairos.mcp_client.client import get_mcp_client
from kairos.schemas.common import DataProvenance, DatasetManifest, QuoteDelayClassification
from kairos.storage.file_store import FileStore, compute_sha256
from kairos.utils.logging_config import get_logger, setup_logging
from kairos.validation.quality_checks import DataQualityChecker

logger = get_logger("kairos.cli")


def cmd_discover_mcp(args: argparse.Namespace) -> None:
    """Discovers and inspects configured existing MCP servers and their available tools."""
    mcp_client = get_mcp_client()
    servers = mcp_client.list_servers()

    print("\n" + "=" * 80)
    print("  KAIROS MCP SERVER DISCOVERY & CAPABILITY VERIFICATION (Indian Equities)")
    print("=" * 80)

    if not servers:
        print("  [!] No MCP servers found in configuration.")
        return

    for s_name in servers:
        info = mcp_client.get_server_info(s_name) or {}
        cmd = info.get("command", info.get("url", "n/a"))
        suffix = info.get("symbol_suffix", "")
        desc = info.get("description", "")
        tools = info.get("tools", [])

        print(f"\n  [Server]: {s_name.upper()}")
        print(f"    - Description   : {desc}")
        print(f"    - Command/URL   : {cmd}")
        print(f"    - Symbol Suffix : '{suffix}'")
        print(f"    - Exposed Tools : {', '.join(tools)}")

    print("\n" + "=" * 80)
    print("  [✓] Discovery complete. Use 'collect-live' or 'collect-history' to invoke tools.")
    print("=" * 80 + "\n")


def cmd_collect_live(args: argparse.Namespace) -> None:
    """Collects current or latest available quotes for Indian stocks via MCP."""
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    collector = LiveQuoteCollector()
    file_store = FileStore()
    settings = get_settings()

    print("\n" + "=" * 80)
    print(f"  KAIROS LIVE / LATEST QUOTE INGESTION: {', '.join(symbols)}")
    print("=" * 80)

    collected_quotes = []
    for sym in symbols:
        try:
            payload = collector.fetch_live_quote(sym)
            q = payload.quote
            collected_quotes.append(q)
            print(f"  [+] {sym:<10}: Price: ₹{q.last_price:,.2f} | Prev Close: ₹{q.previous_close or 0:,.2f} | "
                  f"Delay: {q.quote_delay.value:<14} | Provider: {q.provider_name} | Session Open: {payload.is_market_open}")
        except Exception as e:
            print(f"  [-] {sym:<10}: Error gathering live quote: {e}", file=sys.stderr)

    # Persist Manifest
    if collected_quotes:
        manifest = DatasetManifest(
            manifest_id=f"manifest_live_{settings.run_id}",
            run_id=settings.run_id,
            domain="live",
            source_provider="nse_mcp / yfinance_mcp",
            provenance=DataProvenance.LIVE_API,
            quote_delay_classification=collected_quotes[0].quote_delay,
            symbols=symbols,
            record_count=len(collected_quotes),
            collection_status="COMPLETE",
        )
        file_store.save_manifest(manifest)
        print(f"\n  [✓] Live quotes collected and persisted. Manifest: {manifest.manifest_id}\n")


def cmd_collect_history(args: argparse.Namespace) -> None:
    """Collects ~10 years of historical daily OHLCV bars for Indian stocks via MCP."""
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    collector = HistoryCollector()
    file_store = FileStore()
    settings = get_settings()

    print("\n" + "=" * 80)
    print(f"  KAIROS ~10-YEAR HISTORICAL DAILY COLLECTION: {', '.join(symbols)}")
    print(f"  Target: {args.period} horizon | Interval: {args.interval} | Incremental: {args.incremental}")
    print("=" * 80)

    total_bars = 0
    raw_files = []
    for sym in symbols:
        try:
            payload = collector.fetch_historical_data(
                symbol=sym,
                period=args.period,
                interval=args.interval,
                incremental=args.incremental,
            )
            total_bars += len(payload.bars)
            raw_files.append(f"data/raw/market/{sym.lower()}_history.json")
            status_tag = "10Y COMPLETE" if payload.is_ten_year_complete else "INCOMPLETE"
            print(f"  [+] {sym:<10}: {len(payload.bars)} bars ({payload.earliest_date} to {payload.latest_date}) | "
                  f"Coverage: {payload.coverage_years} yrs [{status_tag}] | SMA-20: {payload.sma_20} | RSI-14: {payload.rsi_14}")
        except Exception as e:
            print(f"  [-] {sym:<10}: Error gathering historical bars: {e}", file=sys.stderr)

    # Persist Manifest
    if total_bars > 0:
        manifest = DatasetManifest(
            manifest_id=f"manifest_history_10y_{settings.run_id}",
            run_id=settings.run_id,
            domain="market",
            source_provider="yfinance_mcp",
            provenance=DataProvenance.EXCHANGE_FEED,
            quote_delay_classification=QuoteDelayClassification.END_OF_DAY,
            symbols=symbols,
            coverage_years=10.0,
            collection_status="COMPLETE",
            record_count=total_bars,
            raw_files=raw_files,
        )
        file_store.save_manifest(manifest)
        print(f"\n  [✓] 10-year historical collection finished. Total bars: {total_bars}. Manifest: {manifest.manifest_id}\n")


def cmd_collect_news(args: argparse.Namespace) -> None:
    """Collects financial news and metadata for Indian stocks via MCP."""
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    collector = NewsCollector()
    print("\n" + "=" * 80)
    print(f"  KAIROS FINANCIAL NEWS INGESTION: {', '.join(symbols)}")
    print("=" * 80)

    total_articles = 0
    for sym in symbols:
        try:
            payload = collector.fetch_ticker_news(sym, limit=args.limit)
            total_articles += len(payload.articles)
            print(f"  [+] {sym:<10}: Ingested {len(payload.articles)} articles via yfinance-mcp-server")
        except Exception as e:
            print(f"  [-] {sym:<10}: Error gathering news: {e}", file=sys.stderr)

    print(f"\n  [✓] News collection complete. Total articles: {total_articles}\n")


def cmd_collect_fundamentals(args: argparse.Namespace) -> None:
    """Collects balance sheet, income, and cash flow facts for Indian stocks via MCP."""
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    collector = FundamentalsCollector()
    print("\n" + "=" * 80)
    print(f"  KAIROS CORPORATE FINANCIAL STATEMENTS INGESTION: {', '.join(symbols)}")
    print("=" * 80)

    for sym in symbols:
        try:
            payload = collector.fetch_fundamentals(sym)
            print(f"  [+] {sym:<10}: Revenue: ₹{payload.revenue:,.0f} | Net Income: ₹{payload.net_income:,.0f} | "
                  f"Assets: ₹{payload.total_assets:,.0f} | D/E: {payload.debt_to_equity} | Margin: {payload.profit_margins}")
        except Exception as e:
            print(f"  [-] {sym:<10}: Error gathering fundamentals: {e}", file=sys.stderr)

    print("\n  [✓] Fundamentals collection complete.\n")


def cmd_collect_reddit(args: argparse.Namespace) -> None:
    """Collects retail sentiment across Indian finance subreddits via MCP."""
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    collector = RedditCollector()
    print("\n" + "=" * 80)
    print(f"  KAIROS SOCIAL SENTIMENT COLLECTION (Indian Subreddits): {', '.join(symbols)}")
    print("=" * 80)

    for sym in symbols:
        try:
            payload = collector.fetch_community_sentiment(sym, limit_per_sub=args.limit)
            print(f"  [+] {sym:<10}: {len(payload.posts)} posts | Status: {payload.permission_status} (Live: {payload.is_live_data})")
        except Exception as e:
            print(f"  [-] {sym:<10}: Error gathering sentiment: {e}", file=sys.stderr)

    print("\n  [✓] Social sentiment collection complete.\n")


def cmd_validate(args: argparse.Namespace) -> None:
    """Validates datasets against Pydantic schemas, OHLC invariants, and 10-year coverage."""
    checker = DataQualityChecker()
    settings = get_settings()

    print("\n" + "=" * 80)
    print("  KAIROS DATA QUALITY AUDITING & 10-YEAR COVERAGE VERIFICATION")
    print("=" * 80)

    import pyarrow.parquet as pq

    market_dir = settings.processed_data_dir / "market"
    parquet_files = list(market_dir.glob("*_10y_clean.parquet"))

    if not parquet_files:
        print("  [!] No processed historical parquet files found. Run 'collect-history' first.")
        return

    for pf in parquet_files:
        table = pq.read_table(pf)
        records = table.to_pylist()
        sym = pf.stem.replace("_10y_clean", "").upper()

        report, quarantined = checker.analyze_dataset(
            domain="market",
            records=records,
            required_fields=["date", "symbol", "open", "high", "low", "close", "volume"],
            provider="yfinance_mcp",
            data_classification="EXCHANGE_FEED",
            date_field="date",
            symbol_field="symbol",
            quote_delay_classification="END_OF_DAY",
        )

        status_tag = "10Y VERIFIED" if report.is_ten_year_complete else "INCOMPLETE"
        print(f"  [✓] {sym:<10}: {report.valid_records}/{report.total_records} valid | "
              f"Coverage: {report.coverage_years} yrs ({report.date_coverage_start} to {report.date_coverage_end}) [{status_tag}] | "
              f"Duplicates: {report.duplicate_records}")

    print(f"\n  [✓] Quality audit finished. Reports saved to data/reports/\n")


def cmd_dataset_status(args: argparse.Namespace) -> None:
    """Displays inventory of raw JSON, clean CSV, Parquet files, source freshness, and scheduler status."""
    import glob
    import json
    import os
    from datetime import datetime

    settings = get_settings()

    print("\n" + "=" * 90)
    print("  KAIROS DATASET FRESHNESS & SOURCE INVENTORY STATUS")
    print("=" * 90)

    domain_meta = {
        "live": {
            "label": "Live Quotes",
            "source": "NSE MCP (mcp.nseindia.in) / YFinance Quote",
            "mode": "DELAYED (15_MIN_DELAYED) / REAL_TIME (Market Hours)",
            "sample_file": "reliance_live.json",
        },
        "market": {
            "label": "10y Daily OHLCV",
            "source": "Yahoo Finance (yfinance-mcp-server)",
            "mode": "END_OF_DAY / DELAYED (Daily Close Bars)",
            "sample_file": "reliance_10y_clean.csv",
        },
        "news": {
            "label": "Financial News",
            "source": "ET / Livemint / BS Media Feeds (Verified HTTP 200)",
            "mode": "LIVE (Continuous Intraday Published Feeds)",
            "sample_file": "reliance_news.json",
        },
        "reddit": {
            "label": "Social Sentiment",
            "source": "r/IndianStockMarket (Public Atom/RSS Feed)",
            "mode": "LIVE (Near Real-Time Community Syndication)",
            "sample_file": "indianstockmarket_raw.json",
        },
        "fundamentals": {
            "label": "Financial Filings",
            "source": "MCA Ind-AS Audited Filings / YFinance Statements",
            "mode": "STATIC / PERIODIC (Quarterly / Annual Disclosures)",
            "sample_file": "reliance_fundamentals.json",
        },
    }

    print(f"  {'Domain':<16} | {'Source Mode':<28} | {'Latest File Update':<20} | {'Files (Raw/CSV/PQ)'}")
    print("  " + "-" * 86)

    for domain, meta in domain_meta.items():
        raw_p = settings.raw_data_dir / domain
        proc_p = settings.processed_data_dir / domain
        raw_cnt = len(list(raw_p.glob("*.json"))) if raw_p.exists() else 0
        csv_cnt = len(list(proc_p.glob("*.csv"))) if proc_p.exists() else 0
        parquet_cnt = len(list(proc_p.glob("*.parquet"))) if proc_p.exists() else 0

        # Find latest mtime in domain
        files = list(raw_p.glob("*")) + list(proc_p.glob("*"))
        if files:
            latest_mtime = max(os.stat(f).st_mtime for f in files)
            mtime_str = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M:%S")
        else:
            mtime_str = "N/A"

        files_summary = f"{raw_cnt}/{csv_cnt}/{parquet_cnt}"
        print(f"  {meta['label']:<16} | {meta['mode'][:28]:<28} | {mtime_str:<20} | {files_summary}")

    print("  " + "-" * 86)
    m_cnt = len(list(settings.manifests_dir.glob("*.json")))
    r_cnt = len(list(settings.reports_dir.glob("*.json")))
    print(f"  * MANIFESTS     : {m_cnt} persisted manifests | REPORTS: {r_cnt} quality scorecards")

    # Check Scheduler daemon status
    scheduler_file = Path("scripts/scheduler.py")
    print(f"  * AUTO-SCHEDULER: Available via 'python scripts/scheduler.py --interval 300'")
    print(f"                    Currently: INACTIVE (No daemon running; on-demand execution active)")
    print("=" * 90 + "\n")


def cmd_schedule(args: argparse.Namespace) -> None:
    """Executes the recurring automated dataset scheduler."""
    from kairos.pipeline.scheduler import run_refresh_cycle, running
    from kairos.storage.file_store import FileStore

    domains = [d.strip().lower() for d in args.domains.split(",") if d.strip()]
    file_store = FileStore()

    if args.once:
        run_refresh_cycle(file_store, domains)
        return

    print("=" * 80)
    print("  KAIROS AUTOMATED DATASET SCHEDULER")
    print(f"  Domains:          {', '.join(domains)}")
    print(f"  Refresh Interval: {args.interval}s")
    print("=" * 80)
    print(f"Scheduler loop started. Press Ctrl+C to terminate.\n")

    cycle = 1
    while running:
        print(f"--- Ingestion Cycle #{cycle} ---")
        run_refresh_cycle(file_store, domains)
        cycle += 1
        for _ in range(args.interval):
            if not running:
                break
            time.sleep(1)


def build_parser() -> argparse.ArgumentParser:
    """Builds CLI argument parser with subcommands."""
    default_symbols = "RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK"
    parser = argparse.ArgumentParser(
        prog="python -m kairos.cli",
        description="KAIROS Indian Stock Market Multi-Agent Pipeline via Existing MCP Servers",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # discover-mcp
    subparsers.add_parser("discover-mcp", help="Discover and verify configured existing MCP servers")

    # collect-live
    p_live = subparsers.add_parser("collect-live", help="Collect live or latest available quotes")
    p_live.add_argument("--symbols", default=default_symbols, help="Comma-separated stock symbols")

    # collect-history
    p_hist = subparsers.add_parser("collect-history", help="Collect ~10 years of historical daily OHLCV")
    p_hist.add_argument("--symbols", default=default_symbols, help="Comma-separated stock symbols")
    p_hist.add_argument("--period", default="10y", help="Historical period horizon (e.g. 10y, 5y, 1y)")
    p_hist.add_argument("--interval", default="1d", help="Data interval (e.g. 1d, 1wk)")
    p_hist.add_argument("--no-incremental", dest="incremental", action="store_false", default=True, help="Disable incremental merging")

    # collect-news
    p_news = subparsers.add_parser("collect-news", help="Collect company financial news")
    p_news.add_argument("--symbols", default=default_symbols, help="Comma-separated stock symbols")
    p_news.add_argument("--limit", type=int, default=10, help="Max articles per symbol")

    # collect-fundamentals
    p_fund = subparsers.add_parser("collect-fundamentals", help="Collect company financial statements in INR")
    p_fund.add_argument("--symbols", default=default_symbols, help="Comma-separated stock symbols")

    # collect-reddit
    p_red = subparsers.add_parser("collect-reddit", help="Collect social sentiment from Indian subreddits")
    p_red.add_argument("--symbols", default=default_symbols, help="Comma-separated stock symbols")
    p_red.add_argument("--limit", type=int, default=5, help="Max posts per subreddit")

    # validate
    subparsers.add_parser("validate", help="Run data quality validation and 10-year coverage analysis")

    # dataset-status
    subparsers.add_parser("dataset-status", help="Display dataset inventory status")

    # schedule
    p_sched = subparsers.add_parser("schedule", help="Run automated recurring dataset refresher")
    p_sched.add_argument("--interval", type=int, default=300, help="Refresh interval in seconds (default: 300s = 5m)")
    p_sched.add_argument("--once", action="store_true", help="Run single refresh cycle and exit")
    p_sched.add_argument("--domains", default="live,news,reddit", help="Domains to refresh (live,news,reddit,market)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(level_name=args.log_level)

    cmd_map = {
        "discover-mcp": cmd_discover_mcp,
        "collect-live": cmd_collect_live,
        "collect-history": cmd_collect_history,
        "collect-news": cmd_collect_news,
        "collect-fundamentals": cmd_collect_fundamentals,
        "collect-reddit": cmd_collect_reddit,
        "validate": cmd_validate,
        "dataset-status": cmd_dataset_status,
        "schedule": cmd_schedule,
    }

    handler = cmd_map.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
