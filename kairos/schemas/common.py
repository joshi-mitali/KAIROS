"""Common data schema definitions, provenance types, and manifest models."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DataProvenance(str, Enum):
    LIVE_API = "LIVE_API"
    EXCHANGE_FEED = "EXCHANGE_FEED"
    LICENSED_SAMPLE = "LICENSED_SAMPLE"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"


class QuoteDelayClassification(str, Enum):
    REAL_TIME = "REAL_TIME"
    DELAYED_15_MIN = "15_MIN_DELAYED"
    END_OF_DAY = "END_OF_DAY"


class DatasetManifest(BaseModel):
    """Manifest describing a collected or processed dataset for reproducibility."""

    manifest_id: str
    run_id: str
    domain: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_provider: str
    provenance: DataProvenance
    quote_delay_classification: QuoteDelayClassification
    symbols: List[str] = Field(default_factory=list)
    earliest_date: Optional[str] = None
    latest_date: Optional[str] = None
    coverage_years: Optional[float] = None
    collection_status: str = "COMPLETE"  # "COMPLETE" or "INCOMPLETE"
    record_count: int
    raw_files: List[str] = Field(default_factory=list)
    processed_csv: Optional[str] = None
    processed_parquet: Optional[str] = None
    sha256_checksums: Dict[str, str] = Field(default_factory=dict)
    summary_statistics: Dict[str, Any] = Field(default_factory=dict)
