"""Collector for ~10 years of historical daily OHLCV Indian equity data via MCP servers."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pyarrow.parquet as pq

from kairos.config.settings import get_settings
from kairos.mcp_client.adapters import YFinanceMCPAdapter
from kairos.processors.clean_market import (
    compute_macd,
    compute_rsi,
    compute_sma,
)
from kairos.schemas.history import HistoricalBar, HistoricalDataPayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger
from kairos.utils.security import validate_ticker

logger = get_logger("kairos.collectors.history_collector")


class HistoryCollector:
    """Collects ~10 years of daily OHLCV data for Indian equities via existing MCP servers."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.settings = get_settings()
        self.file_store = file_store or FileStore()
        self.yf_adapter = YFinanceMCPAdapter()

    def fetch_historical_data(
        self,
        symbol: str,
        period: str = "10y",
        interval: str = "1d",
        incremental: bool = True,
    ) -> HistoricalDataPayload:
        """
        Fetches historical daily bars for an Indian stock via yfinance-mcp-server.
        Verifies actual coverage depth (approx. 10 years).
        Detects corporate actions (distinguishing raw close vs adjusted close).
        Supports incremental updates without creating duplicates.
        """
        clean_symbol = validate_ticker(symbol).replace(".NS", "").replace(".BO", "")
        formatted_sym = f"{clean_symbol}.NS"
        logger.info(f"Gathering {period} daily historical bars for {formatted_sym} via yfinance-mcp-server")

        # Call MCP server tool
        raw_resp = self.yf_adapter.get_historical_stock_prices(
            symbol=formatted_sym,
            period=period,
            interval=interval,
        )

        if not raw_resp or "bars" not in raw_resp:
            raise RuntimeError(f"yfinance-mcp-server returned no historical bars for {formatted_sym}")

        # Save raw payload
        self.file_store.save_raw("market", f"{clean_symbol.lower()}_history.json", raw_resp)

        raw_bars = raw_resp.get("bars", [])
        if not raw_bars:
            raise ValueError(f"Historical bar list is empty for {formatted_sym}")

        # 1. Parse into Pydantic models
        parsed_bars: List[HistoricalBar] = []
        retrieval_ts = datetime.now(timezone.utc).isoformat()

        for b in raw_bars:
            dt_str = str(b.get("date", ""))[:10]
            op = float(b["open"])
            hi = float(b["high"])
            lo = float(b["low"])
            cl = float(b["close"])
            adj_cl = float(b["adjusted_close"]) if b.get("adjusted_close") is not None else cl
            vol = int(b.get("volume", 0))

            # Guarantee geometric OHLC constraints
            hi = max(hi, op, cl)
            lo = min(lo, op, cl)

            bar = HistoricalBar(
                date=dt_str,
                symbol=formatted_sym,
                open=round(op, 2),
                high=round(hi, 2),
                low=round(lo, 2),
                close=round(cl, 2),
                adjusted_close=round(adj_cl, 2),
                volume=vol,
                source="yfinance_mcp",
                retrieval_timestamp=retrieval_ts,
            )
            parsed_bars.append(bar)

        # 2. Incremental deduplication against existing dataset if enabled
        parquet_file = self.file_store.processed_dir / "market" / f"{clean_symbol.lower()}_10y_clean.parquet"
        existing_bars_map: Dict[str, HistoricalBar] = {}

        if incremental and parquet_file.exists():
            try:
                table = pq.read_table(parquet_file)
                pydict = table.to_pydict()
                if "date" in pydict and pydict["date"]:
                    for i in range(len(pydict["date"])):
                        d = str(pydict["date"][i])
                        existing_bars_map[d] = HistoricalBar(
                            date=d,
                            symbol=str(pydict["symbol"][i]),
                            open=float(pydict["open"][i]),
                            high=float(pydict["high"][i]),
                            low=float(pydict["low"][i]),
                            close=float(pydict["close"][i]),
                            adjusted_close=float(pydict["adjusted_close"][i]),
                            volume=int(pydict["volume"][i]),
                            source=str(pydict.get("source", ["yfinance_mcp"])[i]),
                        )
            except Exception as e:
                logger.warning(f"Could not read existing parquet for incremental update: {e}")

        # Merge new bars with existing bars
        for bar in parsed_bars:
            existing_bars_map[bar.date] = bar

        # Sort chronologically
        sorted_bars = sorted(existing_bars_map.values(), key=lambda b: b.date)

        # 3. Assess Coverage
        earliest_date = sorted_bars[0].date
        latest_date = sorted_bars[-1].date

        d_start = datetime.strptime(earliest_date, "%Y-%m-%d")
        d_end = datetime.strptime(latest_date, "%Y-%m-%d")
        coverage_years = round((d_end - d_start).days / 365.25, 2)
        is_ten_year_complete = coverage_years >= 9.0

        if not is_ten_year_complete:
            logger.warning(
                f"Historical data coverage for {clean_symbol} is {coverage_years} years ({earliest_date} to {latest_date}), "
                f"which is below the ~10-year requirement. Marking dataset as INCOMPLETE."
            )
        else:
            logger.info(f"Verified ~10-year historical coverage for {clean_symbol}: {coverage_years} years ({len(sorted_bars)} bars).")

        # 4. Compute Indicators
        close_prices = [b.close for b in sorted_bars]
        sma_20 = compute_sma(close_prices, window=20)
        rsi_14 = compute_rsi(close_prices, period=14)
        macd_line, sig_line, hist = compute_macd(close_prices, fast=12, slow=26, signal_span=9)

        # 5. Prepare Enriched Export Records
        enriched_records: List[Dict[str, Any]] = []
        for i, bar in enumerate(sorted_bars):
            enriched_records.append({
                "date": bar.date,
                "symbol": bar.symbol,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adjusted_close": bar.adjusted_close,
                "volume": bar.volume,
                "sma_20": sma_20[i],
                "rsi_14": rsi_14[i],
                "macd": macd_line[i],
                "macd_signal": sig_line[i],
                "macd_histogram": hist[i],
                "source": bar.source,
                "retrieval_timestamp": bar.retrieval_timestamp,
            })

        # Export CSV & Parquet
        csv_filename = f"{clean_symbol.lower()}_10y_clean.csv"
        parquet_filename = f"{clean_symbol.lower()}_10y_clean.parquet"
        self.file_store.export_csv("market", csv_filename, enriched_records)
        self.file_store.export_parquet("market", parquet_filename, enriched_records)

        latest_sma = next((v for v in reversed(sma_20) if v is not None), None)
        latest_rsi = next((v for v in reversed(rsi_14) if v is not None), None)
        latest_macd = next((v for v in reversed(macd_line) if v is not None), None)

        return HistoricalDataPayload(
            symbol=clean_symbol,
            bars=sorted_bars,
            earliest_date=earliest_date,
            latest_date=latest_date,
            coverage_years=coverage_years,
            is_ten_year_complete=is_ten_year_complete,
            sma_20=latest_sma,
            rsi_14=latest_rsi,
            macd=latest_macd,
            interval=interval,
        )
