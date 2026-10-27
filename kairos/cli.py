"""Command-line interface (CLI) for KAIROS data acquisition, validation, and MCP service."""

import argparse
import sys
from datetime import datetime, timezone
from typing import List

from kairos.collectors.fundamentals_collector import FundamentalsCollector
from kairos.collectors.market_collector import MarketCollector
from kairos.collectors.news_collector import NewsCollector
from kairos.collectors.reddit_collector import RedditCollector
from kairos.config.settings import get_settings
from kairos.mcp_server.server import start_server
from kairos.mcp_server.tools import MCPToolRegistry
from kairos.schemas.common import DataProvenance, DatasetManifest
from kairos.storage.file_store import FileStore, compute_sha256
from kairos.utils.logging_config import get_logger, setup_logging
from kairos.validation.quality_checks import DataQualityChecker

logger = get_logger("kairos.cli")


def cmd_collect_market(args: argparse.Namespace) -> None:
    """Collects historical price bars for tickers."""
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    collector = MarketCollector()
    file_store = FileStore()
    settings = get_settings()

    collected_records = []
    raw_files = []

    print(f"\n=======================================================")
    print(f"  KAIROS Market Data Collection: {', '.join(tickers)}")
    print(f"=======================================================")

    for ticker in tickers:
        try:
            payload = collector.fetch_ticker_data(ticker)
            raw_file = f"data/raw/market/{ticker.lower()}_market.json"
            raw_files.append(raw_file)
            collected_records.extend([b.model_dump() for b in payload.bars])
            print(f"  [+] {ticker}: Collected {len(payload.bars)} bars (Live: {payload.is_live_data}, SMA-20: {payload.sma_20}, RSI-14: {payload.rsi_14})")
        except Exception as e:
            print(f"  [-] {ticker}: Error collecting market data: {e}", file=sys.stderr)

    # Generate Manifest
    if collected_records:
        csv_file = f"data/processed/market/{tickers[0].lower()}_market_clean.csv"
        parquet_file = f"data/processed/market/{tickers[0].lower()}_market_clean.parquet"
        checksums = {}
        for p in [csv_file, parquet_file]:
            if (settings.data_dir.parent / p).exists():
                checksums[p] = compute_sha256(settings.data_dir.parent / p)

        manifest = DatasetManifest(
            manifest_id=f"manifest_market_{settings.run_id}",
            run_id=settings.run_id,
            domain="market",
            source_provider="yahoo_finance",
            provenance=DataProvenance.LIVE_API if any(payload.is_live_data for _ in [1]) else DataProvenance.LICENSED_SAMPLE,
            permission_status="PERMITTED",
            record_count=len(collected_records),
            tickers=tickers,
            raw_files=raw_files,
            processed_csv=csv_file,
            processed_parquet=parquet_file,
            sha256_checksums=checksums,
        )
        file_store.save_manifest(manifest)
        print(f"  [✓] Market collection complete. Manifest: {manifest.manifest_id}\n")


def cmd_collect_news(args: argparse.Namespace) -> None:
    """Collects financial news and metadata for tickers."""
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    collector = NewsCollector()
    file_store = FileStore()
    settings = get_settings()

    total_articles = 0
    print(f"\n=======================================================")
    print(f"  KAIROS Financial News Collection: {', '.join(tickers)}")
    print(f"=======================================================")

    for ticker in tickers:
        try:
            payload = collector.fetch_ticker_news(ticker, query=args.query, max_records=args.limit)
            total_articles += len(payload.articles)
            print(f"  [+] {ticker}: Collected {len(payload.articles)} articles via {payload.provider} (Live: {payload.is_live_data})")
        except Exception as e:
            print(f"  [-] {ticker}: Error collecting news: {e}", file=sys.stderr)

    print(f"  [✓] News collection complete. Total articles: {total_articles}\n")


def cmd_collect_fundamentals(args: argparse.Namespace) -> None:
    """Collects SEC EDGAR financial fundamentals."""
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    collector = FundamentalsCollector()
    print(f"\n=======================================================")
    print(f"  KAIROS Fundamentals Collection (SEC EDGAR): {', '.join(tickers)}")
    print(f"=======================================================")

    for ticker in tickers:
        try:
            payload = collector.fetch_fundamentals(ticker)
            print(f"  [+] {ticker} (CIK: {payload.cik}): {len(payload.facts)} facts (Rev: ${payload.revenue:,.0f} | Net Inc: ${payload.net_income:,.0f} | D/E: {payload.debt_to_equity})")
        except Exception as e:
            print(f"  [-] {ticker}: Error collecting fundamentals: {e}", file=sys.stderr)

    print(f"  [✓] Fundamentals collection complete.\n")


def cmd_collect_reddit(args: argparse.Namespace) -> None:
    """Collects Reddit sentiment and posts."""
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    collector = RedditCollector()
    print(f"\n=======================================================")
    print(f"  KAIROS Reddit Sentiment Collection: {', '.join(tickers)}")
    print(f"=======================================================")

    for ticker in tickers:
        try:
            payload = collector.fetch_community_sentiment(ticker, limit_per_sub=args.limit)
            print(f"  [+] {ticker}: Gathered {len(payload.posts)} posts | Status: {payload.permission_status} (Live: {payload.is_live_data})")
        except Exception as e:
            print(f"  [-] {ticker}: Error collecting sentiment: {e}", file=sys.stderr)

    print(f"  [✓] Reddit collection complete.\n")


def cmd_validate(args: argparse.Namespace) -> None:
    """Runs data quality verification and builds scorecards."""
    checker = DataQualityChecker()
    file_store = FileStore()
    settings = get_settings()

    print(f"\n=======================================================")
    print(f"  KAIROS Data Quality Verification & Auditing")
    print(f"=======================================================")

    # Audit market data
    market_raw_files = list((settings.raw_data_dir / "market").glob("*.json"))
    if market_raw_files:
        for mf in market_raw_files:
            import json
            with open(mf, "r", encoding="utf-8") as f:
                data = json.load(f)
            collector = MarketCollector(file_store=file_store)
            ticker = mf.stem.split("_")[0].upper()
            bars = collector._parse_chart_json(ticker, data)
            report, quarantined = checker.analyze_dataset(
                domain="market",
                records=[b.model_dump() for b in bars],
                required_fields=["timestamp", "open", "high", "low", "close", "volume"],
                provider="yahoo_finance",
                data_classification="LIVE_API" if bars and bars[0].source != "calibrated_fixture" else "LICENSED_SAMPLE",
                date_field="timestamp",
            )
            print(f"  [✓] Market ({ticker}): {report.valid_records}/{report.total_records} valid records | Missing: {report.missing_value_percentages}")
    else:
        print("  [!] No market raw data found. Run 'collect-market' first.")

    print(f"  [✓] Quality audit finished. Reports saved to data/reports/\n")


def cmd_collect_all(args: argparse.Namespace) -> None:
    """Executes full Phase 1 ingestion pipeline for configured tickers."""
    print(f"\n>>> Launching Full KAIROS Phase 1 Pipeline for {args.tickers} <<<")
    cmd_collect_market(args)
    cmd_collect_news(args)
    cmd_collect_fundamentals(args)
    cmd_collect_reddit(args)
    cmd_validate(args)
    print(">>> Full Ingestion Pipeline Successfully Executed <<<\n")


def cmd_dataset_status(args: argparse.Namespace) -> None:
    """Prints status of local dataset inventory."""
    registry = MCPToolRegistry()
    status = registry.get_dataset_status(source=args.source)
    print(f"\n=======================================================")
    print(f"  KAIROS Dataset Inventory Status")
    print(f"=======================================================")
    for domain, info in status.get("domains", {}).items():
        print(f"  * {domain.upper():<14}: {info['raw_count']} raw files, {info['processed_count']} processed CSV/Parquet")
    print(f"  * Manifests   : {status.get('manifest_count', 0)}")
    print(f"  * Reports     : {status.get('report_count', 0)}\n")


def cmd_serve_mcp(args: argparse.Namespace) -> None:
    """Starts the Model Context Protocol (MCP) server."""
    start_server()


def build_parser() -> argparse.ArgumentParser:
    """Builds CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m kairos.cli",
        description="KAIROS Institutional Multi-Agent Trading System - Phase 1 CLI",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # collect-market
    p_market = subparsers.add_parser("collect-market", help="Collect historical market OHLCV bars")
    p_market.add_argument("--tickers", default="NVDA,AAPL,MSFT", help="Comma-separated ticker list")

    # collect-news
    p_news = subparsers.add_parser("collect-news", help="Collect financial news and metadata")
    p_news.add_argument("--tickers", default="NVDA,AAPL,MSFT", help="Comma-separated ticker list")
    p_news.add_argument("--query", default=None, help="Optional search query filter")
    p_news.add_argument("--limit", type=int, default=10, help="Max records per ticker")

    # collect-fundamentals
    p_fund = subparsers.add_parser("collect-fundamentals", help="Collect SEC EDGAR financial fundamentals")
    p_fund.add_argument("--tickers", default="NVDA,AAPL,MSFT", help="Comma-separated ticker list")

    # collect-reddit
    p_red = subparsers.add_parser("collect-reddit", help="Collect Reddit sentiment and posts")
    p_red.add_argument("--tickers", default="NVDA,AAPL,MSFT", help="Comma-separated ticker list")
    p_red.add_argument("--limit", type=int, default=5, help="Max posts per subreddit")

    # validate
    subparsers.add_parser("validate", help="Run data quality validation and reporting")

    # collect-all
    p_all = subparsers.add_parser("collect-all", help="Execute complete data ingestion pipeline")
    p_all.add_argument("--tickers", default="NVDA,AAPL,MSFT", help="Comma-separated ticker list")
    p_all.add_argument("--query", default=None, help="News query filter")
    p_all.add_argument("--limit", type=int, default=10, help="Record limits")

    # dataset-status
    p_status = subparsers.add_parser("dataset-status", help="Display dataset inventory status")
    p_status.add_argument("--source", default=None, help="Filter by domain source")

    # serve-mcp
    subparsers.add_parser("serve-mcp", help="Start the Model Context Protocol (MCP) server")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(level_name=args.log_level)

    cmd_map = {
        "collect-market": cmd_collect_market,
        "collect-news": cmd_collect_news,
        "collect-fundamentals": cmd_collect_fundamentals,
        "collect-reddit": cmd_collect_reddit,
        "validate": cmd_validate,
        "collect-all": cmd_collect_all,
        "dataset-status": cmd_dataset_status,
        "serve-mcp": cmd_serve_mcp,
    }

    handler = cmd_map.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
