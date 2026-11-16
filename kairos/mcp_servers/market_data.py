"""Two bounded MCP market tools. Saved and live data are explicitly distinguished."""

import json
import os
from pathlib import Path

import pandas as pd
from fastmcp import FastMCP
from kairos.providers.yahoo import fetch_yahoo

from kairos.processors.clean_market import compute_macd, compute_rsi, compute_sma
from kairos.utils.security import validate_ticker
from kairos.trading.market import normalize_symbol

server = FastMCP("KAIROS Market Evidence")


def _read(domain: str, filename: str):
    path = Path(os.environ.get("KAIROS_DATA_DIR", "data")) / "processed" / domain / filename
    if path.with_suffix(".parquet").exists():
        return pd.read_parquet(path.with_suffix(".parquet"))
    if path.with_suffix(".csv").exists():
        return pd.read_csv(path.with_suffix(".csv"))
    raise ValueError(f"Missing {domain} data. Refresh datasets before running research.")


@server.tool()
def get_price_history(ticker: str) -> dict:
    """Read historical daily price evidence and calculate bounded technical indicators."""
    ticker = validate_ticker(ticker).removesuffix(".NS")
    live = os.environ.get("KAIROS_MARKET_TOOL_SOURCE", "saved") == "live"
    if live:
        import yfinance as yf
        data = fetch_yahoo("historical prices", lambda: yf.Ticker(normalize_symbol(ticker)).history(period="10y", auto_adjust=True, timeout=8), valid=lambda frame:not frame.empty)
        if data.empty:
            raise ValueError("Live historical price provider returned no bars.")
        data = data.reset_index().rename(columns=str.lower)
        data["date"] = data["date"].astype(str).str[:10]
    else:
        data = _read("market", ticker.lower() + "_10y_clean")
    data = data.dropna(subset=["open", "high", "low", "close"])  # Yahoo can return a NaN bar for the current session
    if data.empty:
        raise ValueError("Historical data is empty.")
    close = data["close"].astype(float).tolist()
    sma, rsi = compute_sma(close), compute_rsi(close)
    macd, signal, histogram = compute_macd(close)
    last = data.iloc[-1]
    if live:  # persist the bars the analyst saw so the report can chart them; never block analysis
        try:
            path = Path(os.environ.get("KAIROS_DATA_DIR", "data")) / "processed" / "market" / (ticker.lower() + "_price_history.parquet")
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"date": data["date"].astype(str).str[:10], "close": data["close"].astype(float),
                          "sma_20": sma, "sma_50": compute_sma(close, 50)}).tail(260).to_parquet(path, index=False)
        except Exception:
            pass
    def number(value, fallback):
        return float(value) if value is not None and pd.notna(value) else fallback
    result = {
        "ticker": ticker, "as_of_date": str(last["date"])[:10], "bars_analyzed": len(data),
        "last_close": float(last["close"]),
        "support_level": float(data["low"].tail(60).min()),
        "resistance_level": float(data["high"].tail(60).max()),
        "fifty_two_week_high": float(data["high"].tail(250).max()),
        "fifty_two_week_low": float(data["low"].tail(250).min()),
        "indicators": {"sma_20": number(sma[-1], close[-1]), "rsi_14": number(rsi[-1], 50),
                       "macd_line": number(macd[-1], 0), "macd_signal": number(signal[-1], 0),
                       "macd_histogram": number(histogram[-1], 0)},
        "provenance": "LIVE_YAHOO_FINANCE" if live else "SAVED_DATA",
    }
    return json.loads(json.dumps(result, allow_nan=False))


@server.tool()
def get_live_quote(ticker: str) -> dict:
    """Fetch a current quote or load a saved quote; always report its actual provenance."""
    ticker = validate_ticker(ticker).removesuffix(".NS")
    live = os.environ.get("KAIROS_MARKET_TOOL_SOURCE", "saved") == "live"
    if live:
        import yfinance as yf
        price = fetch_yahoo("quote", lambda: float(yf.Ticker(normalize_symbol(ticker)).fast_info.last_price), valid=lambda value: 0 < value < float("inf"))
        from datetime import datetime, timezone
        return {"ticker": ticker, "last_price": price, "quote_delay": "15_MIN_DELAYED",
                "retrieved_at": datetime.now(timezone.utc).isoformat(), "provenance": "LIVE_YAHOO_FINANCE"}
    data = _read("live", ticker.lower() + "_live")
    if data.empty:
        raise ValueError("Saved quote dataset is empty.")
    row = data.iloc[-1]
    return {"ticker": ticker, "last_price": float(row["last_price"]),
            "quote_delay": str(row.get("quote_delay", "UNKNOWN")),
            "retrieved_at": str(row.get("retrieved_at", row.get("quote_timestamp", "UNKNOWN"))),
            "provenance": "SAVED_DATA"}


if __name__ == "__main__":
    server.run(transport="stdio", show_banner=False)
