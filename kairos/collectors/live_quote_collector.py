"""Collector for live and latest available Indian equities quotes via MCP servers."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from kairos.config.settings import get_settings
from kairos.mcp_client.adapters import NSEMCPAdapter, YFinanceMCPAdapter
from kairos.schemas.common import QuoteDelayClassification
from kairos.schemas.live_quote import LiveQuote, LiveQuotePayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger
from kairos.utils.security import validate_ticker

logger = get_logger("kairos.collectors.live_quote_collector")


class LiveQuoteCollector:
    """Collects current or latest available quotes for NSE/BSE stocks via existing MCP servers."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.settings = get_settings()
        self.file_store = file_store or FileStore()
        self.nse_adapter = NSEMCPAdapter()
        self.yf_adapter = YFinanceMCPAdapter()

    def fetch_live_quote(self, symbol: str) -> LiveQuotePayload:
        """
        Gathers latest quote for an Indian equity.
        Queries nse-mcp first for real-time/latest session data; falls back to yfinance-mcp-server.
        Classifies whether data is REAL_TIME, 15_MIN_DELAYED, or END_OF_DAY.
        """
        clean_symbol = validate_ticker(symbol).replace(".NS", "").replace(".BO", "")
        logger.info(f"Gathering latest quote for Indian stock {clean_symbol} via MCP servers")

        quote_data = None
        provider_name = "nse_mcp"
        delay_class = QuoteDelayClassification.REAL_TIME
        is_market_open = None

        # 1. Attempt NSE MCP server (stock_quote)
        try:
            raw_nse = self.nse_adapter.stock_quote(clean_symbol)
            if raw_nse and "lastPrice" in raw_nse:
                quote_data = raw_nse
                provider_name = "nse_mcp"
                is_open = str(raw_nse.get("marketStatus", "")).lower() == "open"
                is_market_open = is_open
                delay_class = QuoteDelayClassification.REAL_TIME if is_open else QuoteDelayClassification.END_OF_DAY
        except Exception as e:
            logger.warning(f"nse-mcp tool call failed for {clean_symbol}: {e}")

        # 2. Fallback to yfinance-mcp-server (get_stock_info)
        if not quote_data:
            try:
                raw_yf = self.yf_adapter.get_stock_info(clean_symbol)
                if raw_yf and "currentPrice" in raw_yf:
                    quote_data = {
                        "symbol": clean_symbol,
                        "lastPrice": raw_yf.get("currentPrice"),
                        "previousClose": raw_yf.get("regularMarketPreviousClose"),
                        "open": raw_yf.get("regularMarketOpen"),
                        "dayHigh": raw_yf.get("regularMarketDayHigh"),
                        "dayLow": raw_yf.get("regularMarketDayLow"),
                        "totalTradedVolume": raw_yf.get("regularMarketVolume"),
                        "timestamp": datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M:%S"),
                    }
                    provider_name = "yfinance_mcp"
                    delay_class = QuoteDelayClassification.DELAYED_15_MIN
            except Exception as e:
                logger.error(f"yfinance-mcp tool call failed for {clean_symbol}: {e}")

        if not quote_data:
            raise RuntimeError(f"Could not retrieve quotes for {clean_symbol} from any configured MCP server.")

        # Save raw payload
        self.file_store.save_raw("live", f"{clean_symbol.lower()}_live.json", quote_data)

        # Normalize to Pydantic model
        quote = LiveQuote(
            symbol=clean_symbol,
            last_price=float(quote_data["lastPrice"]),
            quote_timestamp=str(quote_data.get("timestamp", datetime.now(timezone.utc).isoformat())),
            volume=int(quote_data.get("totalTradedVolume", 0)) if quote_data.get("totalTradedVolume") else None,
            day_open=float(quote_data["open"]) if quote_data.get("open") else None,
            day_high=float(quote_data["dayHigh"]) if quote_data.get("dayHigh") else None,
            day_low=float(quote_data["dayLow"]) if quote_data.get("dayLow") else None,
            previous_close=float(quote_data["previousClose"]) if quote_data.get("previousClose") else None,
            provider_name=provider_name,
            quote_delay=delay_class,
        )

        payload = LiveQuotePayload(
            symbol=clean_symbol,
            quote=quote,
            is_market_open=is_market_open,
        )

        # Export clean CSV & Parquet
        record = [quote.model_dump()]
        self.file_store.export_csv("live", f"{clean_symbol.lower()}_live.csv", record)
        self.file_store.export_parquet("live", f"{clean_symbol.lower()}_live.parquet", record)

        return payload
