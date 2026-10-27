"""Market data processing, deduplication, indicator calculation, and export."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from kairos.schemas.market import MarketBar, MarketDataPayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.processors.clean_market")


def compute_sma(values: List[float], window: int = 20) -> List[Optional[float]]:
    """Calculates Simple Moving Average over a sliding window."""
    sma_series: List[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < window:
            sma_series.append(None)
        else:
            window_slice = values[i + 1 - window : i + 1]
            sma_series.append(round(sum(window_slice) / window, 4))
    return sma_series


def compute_ema(values: List[float], window: int) -> List[Optional[float]]:
    """Calculates Exponential Moving Average (EMA)."""
    if not values:
        return []
    ema_series: List[Optional[float]] = [None] * len(values)
    if len(values) < window:
        return ema_series

    # Initial seed is the SMA of the first window
    initial_sma = sum(values[:window]) / window
    ema_series[window - 1] = initial_sma
    multiplier = 2.0 / (window + 1.0)

    for i in range(window, len(values)):
        prev_ema = ema_series[i - 1]
        if prev_ema is not None:
            curr_ema = (values[i] - prev_ema) * multiplier + prev_ema
            ema_series[i] = curr_ema

    return ema_series


def compute_rsi(close_prices: List[float], period: int = 14) -> List[Optional[float]]:
    """Calculates Relative Strength Index (RSI) using standard Wilder's smoothing."""
    n = len(close_prices)
    rsi_series: List[Optional[float]] = [None] * n
    if n <= period:
        return rsi_series

    gains = []
    losses = []
    for i in range(1, n):
        change = close_prices[i] - close_prices[i - 1]
        gains.append(max(0.0, change))
        losses.append(max(0.0, -change))

    # Initial average gain and loss
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0.0:
        rsi_series[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi_series[period] = round(100.0 - (100.0 / (1.0 + rs)), 4)

    # Wilder's smoothing for subsequent periods
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0.0:
            rsi_val = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_val = 100.0 - (100.0 / (1.0 + rs))
        rsi_series[i + 1] = round(rsi_val, 4)

    return rsi_series


def compute_macd(
    close_prices: List[float], fast: int = 12, slow: int = 26, signal_span: int = 9
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """Calculates MACD Line, Signal Line, and MACD Histogram."""
    n = len(close_prices)
    macd_line: List[Optional[float]] = [None] * n
    signal_line: List[Optional[float]] = [None] * n
    histogram: List[Optional[float]] = [None] * n

    ema_fast = compute_ema(close_prices, fast)
    ema_slow = compute_ema(close_prices, slow)

    valid_macd_indices: List[int] = []
    valid_macd_values: List[float] = []

    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            val = round(ema_fast[i] - ema_slow[i], 4)
            macd_line[i] = val
            valid_macd_indices.append(i)
            valid_macd_values.append(val)

    # Calculate Signal line on MACD values
    if len(valid_macd_values) >= signal_span:
        sig_ema = compute_ema(valid_macd_values, signal_span)
        for idx_in_valid, orig_idx in enumerate(valid_macd_indices):
            s_val = sig_ema[idx_in_valid]
            if s_val is not None:
                signal_line[orig_idx] = round(s_val, 4)
                if macd_line[orig_idx] is not None:
                    histogram[orig_idx] = round(macd_line[orig_idx] - s_val, 4)

    return macd_line, signal_line, histogram


class CleanMarketProcessor:
    """Cleans, normalizes, deduplicates, and enriches raw market bars."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.file_store = file_store or FileStore()

    def process_and_export(self, payload: MarketDataPayload) -> Dict[str, Any]:
        """
        Processes a MarketDataPayload:
        - Deduplicates and sorts chronologically
        - Calculates SMA-20, RSI-14, and MACD
        - Exports to CSV and Parquet
        """
        ticker = payload.ticker.upper()
        raw_bars = payload.bars

        # 1. Deduplicate by timestamp (retain latest entry)
        seen_timestamps = set()
        deduped_bars: List[MarketBar] = []
        duplicate_count = 0

        # Sort chronologically
        sorted_bars = sorted(raw_bars, key=lambda b: str(b.timestamp))

        for bar in sorted_bars:
            ts_key = str(bar.timestamp)
            if ts_key in seen_timestamps:
                duplicate_count += 1
                continue
            seen_timestamps.add(ts_key)
            deduped_bars.append(bar)

        if duplicate_count > 0:
            logger.warning(f"Detected and dropped {duplicate_count} duplicate timestamp records for {ticker}.")

        close_prices = [b.close for b in deduped_bars]

        # 2. Compute indicators
        sma_20 = compute_sma(close_prices, window=20)
        rsi_14 = compute_rsi(close_prices, period=14)
        macd_line, signal_line, hist = compute_macd(close_prices, fast=12, slow=26, signal_span=9)

        # 3. Build enriched records
        enriched_records: List[Dict[str, Any]] = []
        for i, bar in enumerate(deduped_bars):
            enriched_records.append({
                "ticker": ticker,
                "timestamp": str(bar.timestamp),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adjusted_close": bar.adjusted_close if bar.adjusted_close is not None else bar.close,
                "volume": bar.volume,
                "sma_20": sma_20[i],
                "rsi_14": rsi_14[i],
                "macd": macd_line[i],
                "macd_signal": signal_line[i],
                "macd_histogram": hist[i],
                "source": bar.source or "market_provider",
                "retrieval_timestamp": bar.retrieval_timestamp or datetime.now(timezone.utc).isoformat(),
            })

        # Latest indicator values for payload update
        latest_sma = next((v for v in reversed(sma_20) if v is not None), None)
        latest_rsi = next((v for v in reversed(rsi_14) if v is not None), None)
        latest_macd = next((v for v in reversed(macd_line) if v is not None), None)

        payload.sma_20 = latest_sma
        payload.rsi_14 = latest_rsi
        payload.macd = latest_macd

        # 4. Export to CSV & Parquet
        csv_filename = f"{ticker.lower()}_market_clean.csv"
        parquet_filename = f"{ticker.lower()}_market_clean.parquet"

        csv_path = self.file_store.export_csv("market", csv_filename, enriched_records)
        parquet_path = self.file_store.export_parquet("market", parquet_filename, enriched_records)

        return {
            "ticker": ticker,
            "total_bars": len(raw_bars),
            "clean_bars": len(enriched_records),
            "duplicates_removed": duplicate_count,
            "latest_sma_20": latest_sma,
            "latest_rsi_14": latest_rsi,
            "latest_macd": latest_macd,
            "csv_path": str(csv_path),
            "parquet_path": str(parquet_path),
            "records": enriched_records,
        }
