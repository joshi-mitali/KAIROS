"""A2A Messaging Hub / Broker.
Routes envelopes between Google ADK analysts and CrewAI research agents with audit logging.
"""

import time
from typing import Any, Callable, Dict, List, Optional
from kairos.a2a.contract import A2AResponseEnvelope, A2AStatus, A2ATaskEnvelope
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.a2a.broker")


class A2AMessagingHub:
    """In-memory distributed communication hub for A2A message exchange."""

    def __init__(self, secret_key: str = "kairos_a2a_secret"):
        self.secret_key = secret_key
        self._handlers: Dict[str, Callable[[A2ATaskEnvelope], A2AResponseEnvelope]] = {}
        self._message_audit_log: List[Dict[str, Any]] = []

    def register_agent_handler(
        self, agent_id: str, handler: Callable[[A2ATaskEnvelope], A2AResponseEnvelope]
    ) -> None:
        """Registers a message receipt callback for a specific agent ID."""
        self._handlers[agent_id] = handler
        logger.info(f"Registered A2A handler for agent: {agent_id}")

    def dispatch(self, envelope: A2ATaskEnvelope, verify_sig: bool = True) -> A2AResponseEnvelope:
        """Dispatches an envelope to its designated recipient agent."""
        start_t = time.perf_counter()

        # Audit log entry
        audit_entry = {
            "trace_id": envelope.trace_id,
            "sender": envelope.sender_agent,
            "recipient": envelope.recipient_agent,
            "task_type": envelope.task_type.value,
            "timestamp": envelope.timestamp_utc,
            "has_signature": bool(envelope.signature),
        }

        # 1. Integrity check
        if verify_sig and envelope.signature:
            if not envelope.verify_integrity(self.secret_key):
                err_msg = f"A2A signature verification failed for trace {envelope.trace_id}"
                logger.error(err_msg)
                audit_entry["status"] = "REJECTED_SIGNATURE_MISMATCH"
                self._message_audit_log.append(audit_entry)
                return A2AResponseEnvelope(
                    trace_id=envelope.trace_id,
                    sender_agent="a2a.hub",
                    status=A2AStatus.REJECTED,
                    error_message=err_msg,
                    latency_ms=(time.perf_counter() - start_t) * 1000.0,
                )

        # 2. Routing
        recipient = envelope.recipient_agent
        handler = self._handlers.get(recipient)

        if not handler:
            err_msg = f"No handler registered for recipient agent: {recipient}"
            logger.warning(err_msg)
            audit_entry["status"] = "REJECTED_UNKNOWN_RECIPIENT"
            self._message_audit_log.append(audit_entry)
            return A2AResponseEnvelope(
                trace_id=envelope.trace_id,
                sender_agent="a2a.hub",
                status=A2AStatus.ERROR,
                error_message=err_msg,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        try:
            response = handler(envelope)
            response.latency_ms = (time.perf_counter() - start_t) * 1000.0
            audit_entry["status"] = response.status.value
            audit_entry["latency_ms"] = response.latency_ms
            self._message_audit_log.append(audit_entry)
            return response
        except Exception as e:
            logger.error(f"Error handling A2A message {envelope.trace_id}: {e}", exc_info=True)
            audit_entry["status"] = "ERROR_EXCEPTION"
            self._message_audit_log.append(audit_entry)
            return A2AResponseEnvelope(
                trace_id=envelope.trace_id,
                sender_agent=recipient,
                status=A2AStatus.ERROR,
                error_message=str(e),
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

    def get_audit_trail(self, trace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns the audit log of all A2A messages, optionally filtered by trace_id."""
        if trace_id:
            return [m for m in self._message_audit_log if m["trace_id"] == trace_id]
        return list(self._message_audit_log)


# Global default hub instance
default_a2a_hub = A2AMessagingHub()
