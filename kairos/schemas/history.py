"""Schemas for multi-year historical daily OHLCV bars for Indian equities."""

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class HistoricalBar(BaseModel):
    """Represents a single daily OHLCV bar with split/dividend adjustment support."""

    date: str = Field(..., description="Trading date YYYY-MM-DD", alias="timestamp")
    symbol: str = Field(default="NSE_EQUITY", description="NSE or BSE stock symbol (e.g. RELIANCE.NS)", alias="ticker")
    open: float = Field(..., gt=0.0, description="Opening price in INR")
    high: float = Field(..., gt=0.0, description="Session high price in INR")
    low: float = Field(..., gt=0.0, description="Session low price in INR")
    close: float = Field(..., gt=0.0, description="Unadjusted closing price in INR")
    adjusted_close: Optional[float] = Field(default=None, gt=0.0, description="Corporate-action adjusted close")
    volume: int = Field(..., ge=0, description="Trading volume")
    source: str = Field(default="yfinance_mcp", description="Source MCP server provider")
    provenance: str = Field(default="LIVE_YAHOO_FINANCE_MCP", description="Data provenance classification")
    retrieval_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    class Config:
        populate_by_name = True

    @model_validator(mode="after")
    def validate_ohlc_relationships(self) -> "HistoricalBar":
        """Deterministic sanity checks for OHLC integrity."""
        if self.high < self.low:
            raise ValueError(f"High price ({self.high}) cannot be lower than Low price ({self.low})")
        if self.high < self.open:
            raise ValueError(f"High price ({self.high}) cannot be lower than Open price ({self.open})")
        if self.high < self.close:
            raise ValueError(f"High price ({self.high}) cannot be lower than Close price ({self.close})")
        if self.low > self.open:
            raise ValueError(f"Low price ({self.low}) cannot be greater than Open price ({self.open})")
        if self.low > self.close:
            raise ValueError(f"Low price ({self.low}) cannot be greater than Close price ({self.close})")
        return self


class HistoricalDataPayload(BaseModel):
    """Payload encapsulating multi-year daily bars, coverage analysis, and indicators."""

    symbol: str = Field(..., description="Target stock symbol", alias="ticker")
    bars: List[HistoricalBar] = Field(..., min_length=1, description="List of historical daily bars")
    earliest_date: Optional[str] = Field(default=None, description="Earliest recorded date")
    latest_date: Optional[str] = Field(default=None, description="Latest recorded date")
    coverage_years: Optional[float] = Field(default=None, description="Actual historical coverage in years")
    is_ten_year_complete: bool = Field(default=False, description="True if ~10-year coverage is fulfilled")
    target_years: int = Field(default=10, description="Requested target horizon in years")
    sma_20: Optional[float] = Field(default=None, description="20-day Simple Moving Average")
    rsi_14: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="14-day RSI")
    macd: Optional[float] = Field(default=None, description="MACD value")
    interval: str = Field(default="1d", description="Data interval")

    class Config:
        populate_by_name = True

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()
