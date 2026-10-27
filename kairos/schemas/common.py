"""Common data schema definitions and metadata models."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DataProvenance(str, Enum):
    LIVE_API = "LIVE_API"
    SEC_EDGAR = "SEC_EDGAR"
    LICENSED_SAMPLE = "LICENSED_SAMPLE"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"


class SourceAttribution(BaseModel):
    """Metadata detailing source, licensing, run context and reproducibility."""

    provider: str
    license_or_permission: str
    provenance: DataProvenance
    is_live_data: bool = True
    is_synthetic: bool = False
    retrieval_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_id: str = "default_run"
    additional_metadata: Dict[str, Any] = Field(default_factory=dict)


class DatasetManifest(BaseModel):
    """Comprehensive manifest describing a collected or processed dataset."""

    manifest_id: str
    run_id: str
    domain: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_provider: str
    provenance: DataProvenance
    permission_status: str
    record_count: int
    tickers: List[str] = Field(default_factory=list)
    raw_files: List[str] = Field(default_factory=list)
    processed_csv: Optional[str] = None
    processed_parquet: Optional[str] = None
    sha256_checksums: Dict[str, str] = Field(default_factory=dict)
    summary_statistics: Dict[str, Any] = Field(default_factory=dict)
