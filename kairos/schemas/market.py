"""Market data schemas mapping between legacy and Indian equity models."""

from kairos.schemas.history import HistoricalBar, HistoricalDataPayload
from kairos.schemas.live_quote import LiveQuote, LiveQuotePayload

# Backwards compatibility aliases
MarketBar = HistoricalBar
MarketDataPayload = HistoricalDataPayload

__all__ = [
    "HistoricalBar",
    "HistoricalDataPayload",
    "LiveQuote",
    "LiveQuotePayload",
    "MarketBar",
    "MarketDataPayload",
]
