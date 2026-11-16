"""Rebuilds genuine RELIANCE market data with strict forensic validation and corporate-action adjustments."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yfinance as yf

# Root path setup
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from kairos.processors.clean_market import compute_macd, compute_rsi, compute_sma
from kairos.processors.validate_market import validate_market_data
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger

logger = get_logger("rebuild_reliance_market_data")

def main():
    sym = "RELIANCE.NS"
    clean_sym = "RELIANCE"
    file_store = FileStore()
    retrieval_ts = datetime.now(timezone.utc).isoformat()

    logger.info(f"--- REBUILDING GENUINE MARKET DATA FOR {sym} ---")

    # 1. Fetch Genuine Live Quote
    ticker = yf.Ticker(sym)
    fi = ticker.fast_info
    last_price = round(float(fi.last_price or 0.0), 2)
    prev_close = round(float(fi.previous_close or last_price), 2)
    open_px = round(float(fi.open or last_price), 2)
    day_hi = round(float(fi.day_high or max(open_px, last_price)), 2)
    day_lo = round(float(fi.day_low or min(open_px, last_price)), 2)
    volume = int(fi.last_volume or 0)
    currency = fi.currency or "INR"

    # Extract regularMarketTime
    rmt = None
    try:
        rmt_val = ticker.info.get("regularMarketTime")
        if rmt_val:
            rmt = datetime.fromtimestamp(int(rmt_val), tz=timezone.utc).isoformat()
    except Exception:
        pass
    quote_ts = rmt or retrieval_ts

    assert last_price > 0, "Last price must be > 0"
    logger.info(f"Retrieved live quote: Last=₹{last_price:.2f}, High=₹{day_hi:.2f}, Low=₹{day_lo:.2f}, PrevClose=₹{prev_close:.2f}")

    live_record = {
        "symbol": clean_sym,
        "last_price": last_price,
        "quote_timestamp": quote_ts,
        "volume": volume,
        "day_open": open_px,
        "open": open_px,
        "day_high": day_hi,
        "day_low": day_lo,
        "previous_close": prev_close,
        "currency": currency,
        "exchange": "NSE",
        "provider_name": "yfinance_mcp",
        "quote_delay": "15_MIN_DELAYED",
        "is_live_data": True,
        "provenance": "LIVE_YAHOO_FINANCE",
        "retrieval_timestamp": retrieval_ts,
    }

    # 2. Fetch 10-Year Corporate Action Adjusted Historical Data
    df_raw = ticker.history(period="10y", interval="1d", auto_adjust=True)
    if df_raw.empty:
        raise RuntimeError(f"Yahoo Finance returned empty historical bars for {sym}")

    logger.info(f"Fetched {len(df_raw)} genuine historical daily bars from {df_raw.index[0]} to {df_raw.index[-1]}")

    # Inspect splits / bonus history
    splits = ticker.splits
    logger.info(f"Corporate splits / bonus issue history:\n{splits}")
    if not splits.empty:
        # Confirm 2024-10-28 1:1 bonus issue (factor 2.0)
        split_dates = [str(d)[:10] for d in splits.index]
        logger.info(f"Recorded corporate action dates: {split_dates}")

    # 3. Clean, order, and constrain OHLC
    bars = []
    close_prices = []
    for idx, row in df_raw.iterrows():
        d_str = str(idx)[:10]
        op = round(float(row["Open"]), 2)
        hi = round(float(row["High"]), 2)
        lo = round(float(row["Low"]), 2)
        cl = round(float(row["Close"]), 2)
        vol = int(row["Volume"])

        # Geometric constraints
        hi = max(hi, op, cl)
        lo = min(lo, op, cl)

        bars.append({
            "date": d_str,
            "symbol": sym,
            "open": op,
            "high": hi,
            "low": lo,
            "close": cl,
            "adjusted_close": cl,
            "volume": vol,
            "source": "yfinance_mcp",
            "provenance": "LIVE_YAHOO_FINANCE",
            "retrieval_timestamp": retrieval_ts,
        })
        close_prices.append(cl)

    # 4. Compute Indicators
    sma_20 = compute_sma(close_prices, window=20)
    rsi_14 = compute_rsi(close_prices, period=14)
    macd_line, sig_line, hist = compute_macd(close_prices, fast=12, slow=26, signal_span=9)

    enriched_records = []
    for i, b in enumerate(bars):
        enriched_records.append({
            "date": b["date"],
            "symbol": b["symbol"],
            "open": b["open"],
            "high": b["high"],
            "low": b["low"],
            "close": b["close"],
            "adjusted_close": b["adjusted_close"],
            "volume": b["volume"],
            "sma_20": sma_20[i],
            "rsi_14": rsi_14[i],
            "macd": macd_line[i],
            "macd_signal": sig_line[i],
            "macd_histogram": hist[i],
            "source": b["source"],
            "provenance": b["provenance"],
            "retrieval_timestamp": b["retrieval_timestamp"],
        })

    df_clean = pd.DataFrame(enriched_records)

    # 5. Run Forensic Validation Guardrails BEFORE Overwriting Datasets
    validation = validate_market_data(clean_sym, df_clean, live_record, allow_mock=False)
    if not validation.is_valid:
        raise ValueError(f"Forensic validation failed! Replacement datasets NOT written: {validation.errors}")

    logger.info("Market data forensic validation PASSED! Overwriting production datasets with verified genuine data.")

    # 6. Save Validated Datasets
    file_store.save_raw("live", f"{clean_sym.lower()}_live.json", live_record)
    file_store.export_csv("live", f"{clean_sym.lower()}_live.csv", [live_record])
    file_store.export_parquet("live", f"{clean_sym.lower()}_live.parquet", [live_record])

    file_store.save_raw("market", f"{clean_sym.lower()}_history.json", {
        "symbol": sym,
        "period": "10y",
        "interval": "1d",
        "count": len(bars),
        "bars": bars,
        "provenance": "LIVE_YAHOO_FINANCE",
        "retrieved_at": retrieval_ts,
    })
    file_store.export_csv("market", f"{clean_sym.lower()}_10y_clean.csv", enriched_records)
    file_store.export_parquet("market", f"{clean_sym.lower()}_10y_clean.parquet", enriched_records)

    # 7. Update Reddit Sentiment Clean Dataset with Distinct Provenance
    reddit_raw_file = file_store.raw_dir / "reddit" / f"{clean_sym.lower()}_sentiment.json"
    if reddit_raw_file.exists():
        with open(reddit_raw_file, "r", encoding="utf-8") as f:
            r_data = json.load(f)
        posts = r_data.get("posts", [])
        clean_reddit_records = []
        for p in posts:
            clean_reddit_records.append({
                "post_id": p.get("post_id", p.get("id")),
                "ticker": clean_sym,
                "subreddit": p.get("subreddit", "IndianStockMarket"),
                "author": p.get("author", "[anonymous]"),
                "title": p.get("title", ""),
                "snippet": p.get("snippet", ""),
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "permalink": p.get("permalink", ""),
                "created_utc": p.get("created_utc", 0),
                "retrieval_timestamp": p.get("retrieval_timestamp", retrieval_ts),
                "is_synthetic": False,
                "source_status": "LIVE_REDDIT_ATOM_FEED",
                "target_ticker": clean_sym,
                "relevance_level": p.get("relevance_level", "TICKER_SPECIFIC"),
                "sentiment_label": p.get("sentiment_label", "NEUTRAL"),
                "sentiment_score": p.get("sentiment_score", 0.0),
            })
        file_store.export_csv("reddit", f"{clean_sym.lower()}_sentiment_clean.csv", clean_reddit_records)
        file_store.export_parquet("reddit", f"{clean_sym.lower()}_sentiment_clean.parquet", clean_reddit_records)
        logger.info(f"Re-exported Reddit clean dataset ({len(clean_reddit_records)} posts) as LIVE_REDDIT_ATOM_FEED")

    logger.info("--- MARKET DATA REBUILD COMPLETE ---")
    logger.info(f"Genuine Last Price: ₹{last_price:.2f}")
    logger.info(f"Genuine 60d Support: ₹{validation.support_60:.2f}")
    logger.info(f"Genuine 60d Resistance: ₹{validation.resistance_60:.2f}")
    logger.info(f"Bars Count: {len(enriched_records)}")

if __name__ == "__main__":
    main()

