"""Distributed tracing and W3C traceparent context manager for KAIROS agents."""

import time
import uuid
from kairos.observability.langfuse_tracing import observation, mask_data
from contextlib import contextmanager
from typing import Any, Dict, List, Optional


class AgentSpan:
    """Represents an execution span for an individual agent operation."""

    def __init__(self, name: str, trace_id: str, parent_span_id: Optional[str] = None):
        self.span_id = uuid.uuid4().hex[:16]
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id
        self.name = name
        self.start_time = time.perf_counter()
        self.end_time: Optional[float] = None
        self.duration_ms: float = 0.0
        self.attributes: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []
        self.status: str = "RUNNING"
        self.error: Optional[str] = None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, event_name: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.events.append({
            "name": event_name,
            "timestamp": time.time(),
            "payload": payload or {},
        })

    def finish(self, status: str = "OK", error: Optional[str] = None) -> None:
        self.end_time = time.perf_counter()
        self.duration_ms = (self.end_time - self.start_time) * 1000.0
        self.status = status
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "error": self.error,
            "attributes": self.attributes,
            "events_count": len(self.events),
        }


class AgentTracer:
    """Manages spans and trace collection across Google ADK and CrewAI agents."""

    def __init__(self):
        self._completed_spans: List[AgentSpan] = []

    def start_span(self, name: str, trace_id: str, parent_span_id: Optional[str] = None) -> AgentSpan:
        span = AgentSpan(name=name, trace_id=trace_id, parent_span_id=parent_span_id)
        return span

    def record_span(self, span: AgentSpan) -> None:
        self._completed_spans.append(span)

    @contextmanager
    def span(self, name: str, trace_id: str, parent_span_id: Optional[str] = None):
        s = self.start_span(name, trace_id, parent_span_id)
        try:
            with observation(name, "agent", metadata={"kairos_trace_id": trace_id}) as remote:
                yield s
                if remote is not None:
                    remote.update(output=mask_data(s.attributes))
            s.finish("OK")
        except Exception as e:
            s.finish("ERROR", str(e))
            raise
        finally:
            self.record_span(s)

    def get_spans_for_trace(self, trace_id: str) -> List[AgentSpan]:
        return [s for s in self._completed_spans if s.trace_id == trace_id]

    def clear(self) -> None:
        self._completed_spans.clear()


# Global tracer instance
global_tracer = AgentTracer()

