"""KAIROS Automated Dataset Scheduler.
Periodically refreshes live quotes, financial news, and social sentiment datasets
across target Indian equities (RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK).
"""

import argparse
import signal
import time
from datetime import datetime, timezone


from kairos.pipeline.refresh import (
    fetch_genuine_reddit_data,
    refresh_financial_news,
    refresh_historical_market_data,
    refresh_live_quotes,
)
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.scheduler")

running = True


def handle_shutdown(signum, frame):
    global running
    print("\n[Scheduler] Shutdown signal received. Exiting gracefully...", flush=True)
    running = False


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


def run_refresh_cycle(file_store: FileStore, domains: list[str]) -> dict:
    """Executes a single data refresh cycle across requested domains."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{now_str}] Starting KAIROS Dataset Refresh Cycle...", flush=True)
    summary = {}

    # 1. Live Quotes
    if "live" in domains:
        try:
            print("  -> Refreshing Live NSE Quotes...", flush=True)
            quotes = refresh_live_quotes(file_store)
            summary["live_quotes"] = len(quotes)
            print(f"     [✓] Updated {len(quotes)} live quotes.", flush=True)
        except Exception as e:
            logger.error(f"Live quote refresh error: {e}")
            summary["live_quotes_error"] = str(e)

    # 2. Financial News
    if "news" in domains:
        try:
            print("  -> Refreshing Financial News...", flush=True)
            articles = refresh_financial_news(file_store)
            summary["news_articles"] = len(articles)
            print(f"     [✓] Ingested & verified {len(articles)} news articles.", flush=True)
        except Exception as e:
            logger.error(f"Financial news refresh error: {e}")
            summary["news_error"] = str(e)

    # 3. Reddit Sentiment
    if "reddit" in domains:
        try:
            print("  -> Refreshing Reddit Sentiment (r/IndianStockMarket)...", flush=True)
            reddit_res = fetch_genuine_reddit_data(file_store)
            cnt = reddit_res.get("total_genuine_posts", 0)
            summary["reddit_posts"] = cnt
            print(f"     [✓] Ingested {cnt} genuine posts from public syndication stream.", flush=True)
        except Exception as e:
            logger.error(f"Reddit refresh error: {e}")
            summary["reddit_error"] = str(e)

    # 4. Historical Daily OHLCV (Optional, typically end-of-day)
    if "market" in domains:
        try:
            print("  -> Refreshing Historical OHLCV Bars...", flush=True)
            hist = refresh_historical_market_data(file_store)
            summary["market_tickers"] = len(hist)
            print(f"     [✓] Refreshed daily bars for {len(hist)} tickers.", flush=True)
        except Exception as e:
            logger.error(f"Historical market refresh error: {e}")
            summary["market_error"] = str(e)

    end_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{end_str}] Refresh cycle completed successfully.\n", flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description="KAIROS Automated Dataset Scheduler")
    parser.add_argument("--interval", type=int, default=300, help="Refresh interval in seconds (default: 300s = 5m)")
    parser.add_argument("--once", action="store_true", help="Execute single refresh cycle and exit")
    parser.add_argument(
        "--domains",
        type=str,
        default="live,news,reddit",
        help="Comma-separated domains to refresh (live,news,reddit,market)",
    )
    args = parser.parse_args()

    domains = [d.strip().lower() for d in args.domains.split(",") if d.strip()]
    file_store = FileStore()

    print("=" * 76)
    print("  KAIROS AUTOMATED DATASET SCHEDULER")
    print(f"  Target Domains:    {', '.join(domains)}")
    print(f"  Refresh Interval:  {args.interval}s" if not args.once else "  Mode:              Single Run (--once)")
    print("=" * 76)

    if args.once:
        run_refresh_cycle(file_store, domains)
        return

    print(f"Scheduler active. Press Ctrl+C to stop. Sleeping for {args.interval}s between cycles...")
    cycle_num = 1
    while running:
        print(f"\n--- Cycle #{cycle_num} ---")
        run_refresh_cycle(file_store, domains)
        cycle_num += 1

        for _ in range(args.interval):
            if not running:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()

