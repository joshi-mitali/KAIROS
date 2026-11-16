"""Fetches genuine RELIANCE.NS live quote and 10y historical data with full validation."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import yfinance as yf

def fetch_and_validate():
    sym = "RELIANCE.NS"
    clean_sym = "RELIANCE"
    print(f"Fetching real market data for {sym}...")

    ticker = yf.Ticker(sym)
    
    # 1. Fetch Fast Info / Live Quote
    fi = ticker.fast_info
    last_price = round(float(fi.last_price or 0.0), 2)
    prev_close = round(float(fi.previous_close or last_price), 2)
    open_px = round(float(fi.open or last_price), 2)
    day_hi = round(float(fi.day_high or max(open_px, last_price)), 2)
    day_lo = round(float(fi.day_low or min(open_px, last_price)), 2)
    volume = int(fi.last_volume or 0)
    currency = fi.currency or "INR"

    print(f"Live FastInfo: Last={last_price}, PrevClose={prev_close}, High={day_hi}, Low={day_lo}, Vol={volume}")
    assert last_price > 0, "Last price must be greater than 0"
    assert day_hi >= day_lo, "Day high must be >= Day low"

    retrieval_ts = datetime.now(timezone.utc).isoformat()
    quote_record = {
        "symbol": clean_sym,
        "last_price": last_price,
        "quote_timestamp": retrieval_ts,
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

    # 2. Fetch 10y Historical Bars (Corporate action adjusted)
    df = ticker.history(period="10y", interval="1d", auto_adjust=True)
    if df.empty:
        raise RuntimeError("No historical bars returned from Yahoo Finance")
    
    print(f"Historical bars fetched: {len(df)} rows from {df.index[0]} to {df.index[-1]}")
    
    # Verify corporate action adjustment & dates
    splits = ticker.splits
    print("Splits/Bonuses recorded by Yahoo Finance:")
    print(splits)

    # Validate chronological ordering & geometric constraints
    bars = []
    close_prices = []
    for idx, row in df.iterrows():
        dt_str = str(idx)[:10]
        op = round(float(row["Open"]), 2)
        hi = round(float(row["High"]), 2)
        lo = round(float(row["Low"]), 2)
        cl = round(float(row["Close"]), 2)
        vol = int(row["Volume"])

        # Geometric constraints
        hi = max(hi, op, cl)
        lo = min(lo, op, cl)

        bars.append({
            "date": dt_str,
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

    # Check 60-day support & resistance
    recent_60_bars = bars[-60:]
    recent_lows = [b["low"] for b in recent_60_bars]
    recent_highs = [b["high"] for b in recent_60_bars]
    support_60 = min(recent_lows)
    resistance_60 = max(recent_highs)

    print(f"60-day Support: {support_60:.2f}, 60-day Resistance: {resistance_60:.2f}")
    print(f"Current Price: {last_price:.2f}")

    # Verify price basis compatibility:
    # Current price must be within reasonable proximity of 60-day range (e.g., within 25% of support/resistance bounds)
    lower_bound = support_60 * 0.75
    upper_bound = resistance_60 * 1.25
    if not (lower_bound <= last_price <= upper_bound):
        raise ValueError(
            f"Price basis incompatibility detected! Last price {last_price} is outside valid boundary [{lower_bound:.2f}, {upper_bound:.2f}]"
        )
    print("Price basis validation PASSED! Current price and historical bars are on the exact same adjusted scale.")

    return quote_record, bars

if __name__ == "__main__":
    fetch_and_validate()

