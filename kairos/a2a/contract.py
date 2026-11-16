"""A2A (Agent-to-Agent) Protocol Contract Specification.
Implements standardized inter-framework messaging between Google ADK and CrewAI.
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator


class A2AMessageType(str, Enum):
    MARKET_REPORT = "A2A.ANALYST.MARKET_REPORT"
    SENTIMENT_REPORT = "A2A.ANALYST.SENTIMENT_REPORT"
    NEWS_REPORT = "A2A.ANALYST.NEWS_REPORT"
    FUNDAMENTALS_REPORT = "A2A.ANALYST.FUNDAMENTALS_REPORT"
    RESEARCH_DEBATE_REQUEST = "A2A.CREW.DEBATE_REQUEST"
    RESEARCH_VERDICT = "A2A.CREW.RESEARCH_VERDICT"
    TRADING_PROPOSAL = "A2A.TRADER.PROPOSAL"


class A2AStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    REJECTED = "REJECTED"


def generate_trace_id() -> str:
    """Generates a W3C traceparent compliant distributed trace ID."""
    rand_hex = uuid.uuid4().hex
    return f"00-{rand_hex}-{rand_hex[:16]}-01"


def compute_payload_signature(payload: Dict[str, Any], secret_key: str = "kairos_a2a_secret") -> str:
    """Generates HMAC-SHA256 signature for envelope tamper-evidence."""
    canonical_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()


def verify_payload_signature(payload: Dict[str, Any], signature: str, secret_key: str = "kairos_a2a_secret") -> bool:
    """Verifies HMAC-SHA256 signature against envelope payload."""
    expected = compute_payload_signature(payload, secret_key)
    return hmac.compare_digest(expected, signature)


class A2ATaskEnvelope(BaseModel):
    """Standardized A2A task dispatch envelope for ADK <-> CrewAI communication."""

    trace_id: str = Field(default_factory=generate_trace_id, description="W3C traceparent distributed trace identifier")
    sender_agent: str = Field(..., description="e.g. google_adk.market_analyst")
    recipient_agent: str = Field(..., description="e.g. crewai.bull_researcher")
    version: str = Field(default="1.0.0", description="A2A protocol specification version")
    task_type: A2AMessageType = Field(..., description="Category of inter-agent task payload")
    payload: Dict[str, Any] = Field(..., description="Typed payload dictionary")
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signature: Optional[str] = Field(default=None, description="HMAC-SHA256 signature")

    def sign(self, secret_key: str = "kairos_a2a_secret") -> "A2ATaskEnvelope":
        """Signs the envelope payload using HMAC-SHA256."""
        self.signature = compute_payload_signature(self.payload, secret_key)
        return self

    def verify_integrity(self, secret_key: str = "kairos_a2a_secret") -> bool:
        """Checks whether the payload has been altered since signing."""
        if not self.signature:
            return False
        return verify_payload_signature(self.payload, self.signature, secret_key)


class A2AResponseEnvelope(BaseModel):
    """Standardized A2A acknowledgment or response envelope."""

    trace_id: str = Field(..., description="Correlated W3C trace ID")
    sender_agent: str = Field(...)
    status: A2AStatus = Field(default=A2AStatus.SUCCESS)
    data: Optional[Dict[str, Any]] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    latency_ms: float = Field(default=0.0)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

