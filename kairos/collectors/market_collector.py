"""Market collector coordinating historical 10-year and live quote collection."""

from typing import Optional
from kairos.collectors.history_collector import HistoryCollector
from kairos.collectors.live_quote_collector import LiveQuoteCollector
from kairos.schemas.history import HistoricalDataPayload
from kairos.schemas.live_quote import LiveQuotePayload
from kairos.storage.file_store import FileStore


class MarketCollector:
    """Unified coordinator for Indian stock market live quotes and ~10 years history."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.file_store = file_store or FileStore()
        self.history_collector = HistoryCollector(file_store=self.file_store)
        self.live_collector = LiveQuoteCollector(file_store=self.file_store)

    def fetch_ticker_data(self, ticker: str, range_str: str = "10y", interval: str = "1d") -> HistoricalDataPayload:
        """Fetches historical OHLCV data."""
        return self.history_collector.fetch_historical_data(symbol=ticker, period=range_str, interval=interval)

    def fetch_live_quote(self, ticker: str) -> LiveQuotePayload:
        """Fetches live/latest market quote."""
        return self.live_collector.fetch_live_quote(symbol=ticker)
