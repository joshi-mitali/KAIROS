"""Pydantic schemas and data models for KAIROS Persistent Memory."""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class RecordType(str, Enum):
    """Categorization of records stored in KAIROS Memory."""
    COMPLETED_TRADE = "COMPLETED_TRADE"
    HYPOTHETICAL_PROPOSAL = "HYPOTHETICAL_PROPOSAL"
    RESEARCH_RUN = "RESEARCH_RUN"


class TradeOutcome(str, Enum):
    """Execution outcome for trade records."""
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    PENDING = "PENDING"


class MemoryRecord(BaseModel):
    """Structured memory record representing an executed trade, a trading proposal,
    or a multi-agent research run.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    record_type: RecordType
    ticker: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    date: str  # Format: YYYY-MM-DD
    strategy: str = "QUANTITATIVE_EQUITY"
    market_conditions: str = "NORMAL"
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    outcome: TradeOutcome = TradeOutcome.PENDING
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    rationale: str = ""
    lessons_learned: str = ""
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_proposal_integrity(self) -> "MemoryRecord":
        """Strictly ensures hypothetical proposals never invent trade outcomes or P&L."""
        if self.record_type == RecordType.HYPOTHETICAL_PROPOSAL:
            if self.outcome != TradeOutcome.PENDING:
                raise ValueError(
                    f"Hypothetical proposals must have outcome='PENDING', got '{self.outcome}'."
                )
            if self.pnl is not None:
                raise ValueError("Hypothetical proposals cannot have real P&L amount.")
            if self.pnl_pct is not None:
                raise ValueError("Hypothetical proposals cannot have real P&L percentage.")
            if self.exit_price is not None:
                raise ValueError("Hypothetical proposals cannot have an exit price.")
        elif self.record_type == RecordType.COMPLETED_TRADE:
            if self.outcome == TradeOutcome.PENDING:
                raise ValueError(
                    "Completed trades must have a definite outcome ('WIN', 'LOSS', 'BREAKEVEN'), not 'PENDING'."
                )
        return self


class MemorySearchResult(BaseModel):
    """Result of a memory retrieval query with computed recency, relevance, and composite scores."""
    record: MemoryRecord
    recency_weight: float = Field(ge=0.0, le=1.0)
    relevance_score: float = Field(ge=0.0, le=1.0)
    composite_score: float = Field(ge=0.0, le=1.0)

