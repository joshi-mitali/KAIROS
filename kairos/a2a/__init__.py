"""KAIROS A2A (Agent-to-Agent) Interoperability Module."""

from kairos.a2a.contract import (
    A2AMessageType,
    A2AResponseEnvelope,
    A2AStatus,
    A2ATaskEnvelope,
    compute_payload_signature,
    generate_trace_id,
    verify_payload_signature,
)
from kairos.a2a.broker import A2AMessagingHub, default_a2a_hub

__all__ = [
    "A2AMessageType",
    "A2AStatus",
    "A2ATaskEnvelope",
    "A2AResponseEnvelope",
    "generate_trace_id",
    "compute_payload_signature",
    "verify_payload_signature",
    "A2AMessagingHub",
    "default_a2a_hub",
]

