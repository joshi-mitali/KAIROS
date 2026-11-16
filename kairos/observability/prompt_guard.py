"""Groq Prompt Guard at untrusted-text boundaries, with bounded input and fail-closed scans."""
import hashlib
import math
import os
import threading
from functools import lru_cache

import openai

from kairos.config.agent_definitions import load_jsonc
from kairos.observability.langfuse_tracing import observation
from kairos.providers.groq import GroqPoolClient
from kairos_config import CONFIG_DIR


class PromptGuardBlocked(ValueError):
    pass


class PromptGuardUnavailable(RuntimeError):
    pass


def chunks(text: str, size: int, overlap: int):
    if not 0 <= overlap < size <= 450:
        raise ValueError("Guard chunk limits must fit the 512-token model context.")
    data = text.encode("utf-8")
    start = 0
    while start < len(data):
        yield data[start:start+size].decode("utf-8", errors="ignore")
        start += size-overlap


_scan_lock = threading.Lock()  # Groq stalls ~1 in 4 concurrent guard-model requests until timeout; sequential scans (~0.15s each) do not


@lru_cache(maxsize=512)
def _scan(model, threshold, text):
    with _scan_lock:
        for attempt in range(2):  # a stalled scan is retried once on a short timeout; a scan takes ~0.15s when healthy
            try:
                response = _client().chat.completions.create(model=model,messages=[{"role":"user","content":text}],timeout=5)
                break
            except openai.APITimeoutError:
                if attempt:
                    raise
    score = float(response.choices[0].message.content.strip())
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Guard model returned an invalid attack score.")
    return score


@lru_cache
def _client():
    return GroqPoolClient()


def guard_untrusted_text(text: str, source: str, callback_manager=None, trace_id=""):
    enabled = os.environ.get("KAIROS_PROMPT_GUARD_ENABLED", "auto").lower()
    available = bool(os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEYS"))
    if enabled in ("false", "0") or (enabled == "auto" and not available):
        result = {"status":"NOT_RUN", "source":source, "reason":"Guard disabled or Groq credentials unavailable."}
        if callback_manager:
            callback_manager.dispatch("on_guardrail_result",result,trace_id)
        return result
    config = load_jsonc(CONFIG_DIR / "security.jsonc")["prompt_guard"]
    parts = list(chunks(text,config["chunk_bytes"],config["overlap_bytes"]))
    if len(parts) > config["max_chunks"]:
        raise PromptGuardBlocked("Untrusted content exceeds the bounded guard scan; reduce the input before retrying.")
    with observation("screen-untrusted-evidence","guardrail",inputs={"source":source,"content_sha256":hashlib.sha256(text.encode()).hexdigest(),"chunks":len(parts)},metadata={"model":config["model"]}) as span:
        try:
            scores = [_scan(config["model"],config["attack_threshold"],part) for part in parts]
            score = max(scores,default=0)
        except Exception as exc:
            if span is not None:
                span.update(output={"status":"UNAVAILABLE","failure_type":type(exc).__name__})
            raise PromptGuardUnavailable("Prompt Guard is unavailable. Untrusted evidence was not passed to a model; retry when the service recovers.") from None
        result={"status":"BLOCKED" if score >= config["attack_threshold"] else "PASSED","source":source,"max_attack_score":score,"model":config["model"],"chunks":len(parts)}
        if span is not None:
            span.update(output=result)
        if callback_manager:
            callback_manager.dispatch("on_guardrail_result",result,trace_id)
        if result["status"] == "BLOCKED":
            raise PromptGuardBlocked("Prompt Guard blocked suspicious instructions in " + source + ". Review the evidence before retrying.")
        return result
