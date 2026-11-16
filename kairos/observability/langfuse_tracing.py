"""Optional, privacy-aware Langfuse tracing shared by CLI, API and agent frameworks."""

import inspect
import logging
import os
from contextlib import contextmanager
from functools import lru_cache, wraps
from typing import Any

from pydantic import BaseModel

from kairos.config.agent_definitions import load_jsonc
from kairos.utils.logging_config import redact_sensitive_data
from kairos_config import CONFIG_DIR

logger = logging.getLogger(__name__)
_SECRET_FIELDS = ("secret", "password", "api_key", "authorization", "credential", "access_token")


def mask_data(data: Any, **kwargs: Any) -> Any:
    value = data
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if any(term in str(key).lower() for term in _SECRET_FIELDS) else mask_data(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [mask_data(item) for item in value]
    if isinstance(value, str):
        value = redact_sensitive_data(value)
        for key, secret in os.environ.items():
            if any(term in key.lower() for term in ("api_key", "secret", "password")) and len(secret) >= 8:
                for item in secret.split(","):
                    if len(item.strip()) >= 8:
                        value = value.replace(item.strip(), "[REDACTED]")
        return value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)


@lru_cache
def get_langfuse():
    if os.environ.get("KAIROS_LANGFUSE_ENABLED", "false").lower() not in ("true", "1"):
        return None
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        logger.warning("Langfuse enabled but credentials are missing; local tracing remains available.")
        return None
    from langfuse import Langfuse

    config = load_jsonc(CONFIG_DIR / "observability.jsonc")
    os.environ.setdefault("OTEL_SERVICE_NAME", config["application"])
    client = Langfuse(
        base_url=os.environ.get("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com"),
        environment=os.environ.get("LANGFUSE_TRACING_ENVIRONMENT", "development"),
        release=config["release"],
        mask=mask_data,
        timeout=10,
    )
    # Use framework integrations for individual model/tool calls, not an aggregate generation.
    from openinference.instrumentation.crewai import CrewAIInstrumentor
    from openinference.instrumentation.google_adk import GoogleADKInstrumentor

    CrewAIInstrumentor().instrument(skip_dep_check=True)
    GoogleADKInstrumentor().instrument()
    return client


@contextmanager
def observation(name: str, kind: str = "span", inputs: Any = None, metadata: dict | None = None):
    client = get_langfuse()
    if client is None:
        yield None
        return
    from langfuse import propagate_attributes

    config = load_jsonc(CONFIG_DIR / "observability.jsonc")
    with propagate_attributes(tags=config["tags"], metadata={"application": config["application"]}):
        with client.start_as_current_observation(
            name=name, as_type=kind, input=mask_data(inputs), metadata=mask_data(metadata or {})
        ) as current:
            try:
                yield current
            except Exception as exc:
                current.update(level="ERROR", status_message=mask_data(str(exc)))
                raise


def traced(name: str, kind: str = "span", fields: tuple[str, ...] = ()):
    """Capture selected arguments only; never serialize clients, managers, or all locals."""
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            inputs = {field: bound.arguments[field] for field in fields if field in bound.arguments}
            with observation(name, kind, inputs=inputs) as current:
                result = function(*args, **kwargs)
                if current is not None:
                    if name == "analyze-equity" and isinstance(result, dict):
                        result["langfuse_trace_url"] = get_langfuse().get_trace_url()
                    safe_result = mask_data(result)
                    current.update(output=safe_result)
                    if isinstance(safe_result, dict) and safe_result.get("execution_mode"):
                        current.update(metadata={"execution_mode": safe_result["execution_mode"]})
                return result
        return wrapped
    return decorate


def flush_traces() -> None:
    client = get_langfuse()
    if client is not None:
        client.flush()
