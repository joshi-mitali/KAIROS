"""Schemas for live and latest available Indian equities quotes."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from kairos.schemas.common import QuoteDelayClassification


class LiveQuote(BaseModel):
    """Snapshot of the latest price and session data for an Indian equity."""

    symbol: str = Field(..., description="NSE or BSE stock symbol (e.g. RELIANCE)")
    last_price: float = Field(..., gt=0.0, description="Last traded price in INR")
    quote_timestamp: str = Field(..., description="Timestamp of the exchange quote")
    volume: Optional[int] = Field(default=None, ge=0, description="Cumulative day volume")
    day_open: Optional[float] = Field(default=None, gt=0.0, description="Day opening price", alias="open")
    day_high: Optional[float] = Field(default=None, gt=0.0, description="Day high price")
    day_low: Optional[float] = Field(default=None, gt=0.0, description="Day low price")
    previous_close: Optional[float] = Field(default=None, gt=0.0, description="Previous session closing price")
    provider_name: str = Field(default="nse_mcp", description="Source MCP server provider")
    quote_delay: QuoteDelayClassification = Field(
        default=QuoteDelayClassification.DELAYED_15_MIN,
        description="Whether the quote is real-time, 15-min delayed, or end-of-day"
    )
    provenance: str = Field(
        default="LIVE_MCP",
        description="Data provenance (LIVE_MCP, REAL_TIME, SYNTHETIC_FIXTURE)"
    )
    retrieval_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp when ingested"
    )

    model_config = {"populate_by_name": True}

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()


class LiveQuotePayload(BaseModel):
    """Payload encapsulating a quote and session market status."""

    symbol: str
    quote: LiveQuote
    is_market_open: Optional[bool] = None

