"""Market data Pydantic v2 validation models."""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class MarketBar(BaseModel):
    """Represents a single OHLCV market price bar with deterministic validation."""

    timestamp: str = Field(..., description="ISO 8601 UTC timestamp or date string")
    open: float = Field(..., gt=0.0, description="Opening price, strictly positive")
    high: float = Field(..., gt=0.0, description="Highest price, strictly positive")
    low: float = Field(..., gt=0.0, description="Lowest price, strictly positive")
    close: float = Field(..., gt=0.0, description="Closing price, strictly positive")
    volume: int = Field(..., ge=0, description="Trading volume, non-negative integer")
    ticker: Optional[str] = Field(default=None, description="Ticker symbol")
    adjusted_close: Optional[float] = Field(default=None, gt=0.0, description="Adjusted closing price")
    source: Optional[str] = Field(default="market_provider", description="Data source name")
    retrieval_timestamp: Optional[str] = Field(default=None, description="ISO timestamp when ingested")

    @model_validator(mode="after")
    def validate_ohlc_relationships(self) -> "MarketBar":
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


class MarketDataPayload(BaseModel):
    """Payload encapsulating market bars and calculated technical indicators."""

    ticker: str = Field(..., description="Stock ticker symbol")
    bars: List[MarketBar] = Field(..., min_length=1, description="List of OHLCV bars, min length 1")
    sma_20: Optional[float] = Field(default=None, description="20-day Simple Moving Average")
    rsi_14: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="14-day RSI (0-100)")
    macd: Optional[float] = Field(default=None, description="MACD indicator value")
    start_date: Optional[str] = Field(default=None, description="Requested start date")
    end_date: Optional[str] = Field(default=None, description="Requested end date")
    interval: str = Field(default="1d", description="Data interval (e.g. 1d, 1h)")
    is_live_data: bool = Field(default=True, description="True if pulled from live endpoint")

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper()
