"""Callbacks and event listeners for KAIROS agent lifecycle monitoring."""

from typing import Any, Callable, Dict, List, Optional
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.observability.callbacks")


class AgentLifecycleCallback:
    """Base callback interface for KAIROS agent events."""

    def on_analyst_start(self, agent_name: str, ticker: str, trace_id: str) -> None:
        pass

    def on_analyst_complete(self, agent_name: str, ticker: str, report: Any, latency_ms: float, trace_id: str) -> None:
        pass

    def on_debate_start(self, ticker: str, trace_id: str) -> None:
        pass

    def on_thesis_generated(self, researcher_role: str, ticker: str, thesis: Any, trace_id: str) -> None:
        pass

    def on_verdict_reached(self, verdict: Any, trace_id: str) -> None:
        pass

    def on_error(self, agent_name: str, error: Exception, trace_id: str) -> None:
        pass


class LoggingCallback(AgentLifecycleCallback):
    """Default callback logging structured agent execution milestones."""

    def on_analyst_start(self, agent_name: str, ticker: str, trace_id: str) -> None:
        logger.info(f"[{trace_id[:16]}] Analyst started: {agent_name} for {ticker}")

    def on_analyst_complete(self, agent_name: str, ticker: str, report: Any, latency_ms: float, trace_id: str) -> None:
        logger.info(f"[{trace_id[:16]}] Analyst completed: {agent_name} for {ticker} in {latency_ms:.1f}ms")

    def on_debate_start(self, ticker: str, trace_id: str) -> None:
        logger.info(f"[{trace_id[:16]}] CrewAI Research Debate started for {ticker}")

    def on_thesis_generated(self, researcher_role: str, ticker: str, thesis: Any, trace_id: str) -> None:
        logger.info(f"[{trace_id[:16]}] Thesis produced by {researcher_role} for {ticker}")

    def on_verdict_reached(self, verdict: Any, trace_id: str) -> None:
        logger.info(f"[{trace_id[:16]}] Research Manager Verdict: {getattr(verdict, 'recommendation', 'UNKNOWN')}")

    def on_error(self, agent_name: str, error: Exception, trace_id: str) -> None:
        logger.error(f"[{trace_id[:16]}] Error in agent {agent_name}: {error}")


class CallbackManager:
    """Dispatches lifecycle events to all registered callback handlers."""

    def __init__(self, callbacks: Optional[List[AgentLifecycleCallback]] = None):
        self.callbacks: List[AgentLifecycleCallback] = callbacks or [LoggingCallback()]

    def add_callback(self, cb: AgentLifecycleCallback) -> None:
        self.callbacks.append(cb)

    def dispatch(self, event_name: str, *args, **kwargs) -> None:
        for cb in self.callbacks:
            handler = getattr(cb, event_name, None)
            if handler and callable(handler):
                try:
                    handler(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"Error in callback {cb.__class__.__name__}.{event_name}: {e}")

