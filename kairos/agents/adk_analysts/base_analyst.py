"""Base Google ADK Analyst for KAIROS Institutional Multi-Agent System."""

import json
import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from kairos.a2a.contract import A2AMessageType, A2ATaskEnvelope, generate_trace_id
from kairos.config.agent_definitions import get_agent_definition
from kairos.config.settings import get_settings
from kairos.observability.callbacks import CallbackManager
from kairos.observability.guardrails import InstitutionalGuardrailSuite
from kairos.observability.tracer import global_tracer
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.adk_analysts.base")


def ground_model_output(data, schema_cls, evidence):
    """Models explain evidence; they cannot invent measurements, timestamps or citations."""
    allowed = {
        "MarketAnalysisReport": {"key_observations"},
        "SentimentAnalysisReport": {"key_themes"},
        "NewsAnalysisReport": {"news_sentiment", "key_catalysts", "regulatory_and_litigation_risks"},
        "FundamentalsAnalysisReport": {"valuation_posture"},
        "TradingProposal": {"rationale", "risk_warnings", "time_horizon"},
    }.get(schema_cls.__name__)
    if allowed is None:
        return schema_cls.model_validate(data)
    grounded = evidence.model_dump(mode="json")
    grounded.update({key: value for key, value in data.items() if key in allowed})
    return schema_cls.model_validate(grounded)


def prune_json_schema(obj: Any) -> Any:
    """Recursively removes verbose metadata (descriptions, titles, defaults)
    to minimize prompt token overhead for fast inference and avoid 429 TPM limits.
    """
    if isinstance(obj, dict):
        return {
            k: prune_json_schema(v)
            for k, v in obj.items()
            if k not in ("title", "description", "default")
        }
    elif isinstance(obj, list):
        return [prune_json_schema(x) for x in obj]
    return obj


def extract_retry_after(error: Exception) -> Optional[float]:
    """Extracts explicit retry-after duration from HTTP response headers or error messages."""
    # 1. Check HTTP response headers attached to OpenAI / Groq error objects
    response = getattr(error, "response", None)
    if response and hasattr(response, "headers"):
        h = response.headers
        for hdr in ("retry-after", "Retry-After"):
            if hdr in h:
                try:
                    return float(h[hdr])
                except (ValueError, TypeError):
                    pass
        for hdr in ("retry-after-ms", "Retry-After-Ms"):
            if hdr in h:
                try:
                    return float(h[hdr]) / 1000.0
                except (ValueError, TypeError):
                    pass

    # 2. Extract from error string (e.g., Groq returns "Please try again in 1.63s" or "try again in 2s")
    err_text = str(error)
    m = re.search(r"try again in (\d+\.?\d*)\s*s", err_text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = re.search(r"retry after (\d+\.?\d*)\s*s", err_text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    return None


def is_model_limit_exceeded(err_str: str) -> bool:
    """Detects if request permanently exceeds model context or single-request limits."""
    lower_err = err_str.lower()
    patterns = [
        "context_length_exceeded",
        "maximum context length",
        "exceeds maximum context length",
        "request too large",
        "too large for model",
        "reduce the length of the messages",
        "tokens requested exceeds",
        "prompt is too long",
    ]
    return any(p in lower_err for p in patterns)


class APIRateLimiter:
    """Thread-safe minimum-interval rate limiter to prevent burst 429 errors on free API tiers."""

    def __init__(self, min_interval_seconds: float = 0.5):
        self._lock = threading.Lock()
        self._min_interval = min_interval_seconds
        self._last_call_time = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call_time = time.time()


_global_rate_limiter = APIRateLimiter(
    min_interval_seconds=float(os.environ.get("GROQ_MIN_INTERVAL_SEC", "1.5"))
)


class BaseADKAnalyst:
    """Base class for Google ADK specialist analysts.
    Provides structured reporting, W3C distributed tracing, guardrails, and A2A envelope creation.
    """

    agent_name: str = "google_adk.base_analyst"
    role_description: str = "Institutional Research Specialist"
    config_key: Optional[str] = None
    task_message_type: A2AMessageType = A2AMessageType.MARKET_REPORT
    output_schema: Type[BaseModel] = BaseModel

    def __init__(
        self,
        data_dir: Optional[str] = None,
        callback_manager: Optional[CallbackManager] = None,
        secret_key: str = "kairos_a2a_secret",
    ):
        self.data_dir = Path(data_dir) if data_dir else get_settings().data_dir.resolve()
        self.workspace_root = get_settings().data_dir.resolve().parent
        self.callback_manager = callback_manager or CallbackManager()
        self.guardrails = InstitutionalGuardrailSuite()
        self.secret_key = secret_key
        self.goal = "Produce evidence-backed institutional research."
        self.backstory = "You assess supplied data and clearly state its limitations."
        if self.config_key:
            definition = get_agent_definition(self.config_key)
            self.role_description = definition.role
            self.goal = definition.goal
            self.backstory = definition.backstory

        # 1. Primary: Groq API client
        self.groq_client = None
        groq_key = os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEYS")
        if groq_key:
            try:
                from kairos.providers.groq import GroqPoolClient
                self.groq_client = GroqPoolClient()
                logger.info(
                    f"{self.agent_name}: Groq API client initialized successfully."
                )
            except Exception as e:
                logger.warning(f"{self.agent_name}: Failed to init Groq client ({e}).")

        # 2. Secondary: Google GenAI client (optional fallback)
        self.gemini_client = None
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            try:
                import google.genai as genai

                timeout_ms = int(os.environ.get("GEMINI_TIMEOUT_MS", "60000"))
                self.gemini_client = genai.Client(
                    api_key=gemini_key,
                    http_options={"timeout": timeout_ms},
                )
                logger.info(
                    f"{self.agent_name}: Google GenAI client initialized with {timeout_ms}ms timeout."
                )
            except Exception as e:
                logger.warning(
                    f"{self.agent_name}: Failed to init Google GenAI client ({e})."
                )

    def invoke_llm_analysis(
        self,
        prompt: str,
        schema_cls: Type[BaseModel],
        fallback_report: BaseModel,
        model_name: Optional[str] = None,
    ) -> BaseModel:
        """Invokes Groq API (or Gemini) with structured Pydantic outputs.
        Applies bounded retries with exponential backoff and jitter for transient errors (429, 503, 504, timeout).
        Never retries permanent errors (401, 403, 404, 400).
        Falls back safely and transparently to the deterministic quantitative engine if API is unavailable or times out.
        """
        prompt = (
            f"You are {self.role_description}.\n"
            f"Goal: {self.goal}\nBackground: {self.backstory}\n{prompt}"
        )
        # If Groq is available, use it as primary
        if self.groq_client:
            primary_model = model_name or os.environ.get(
                "GROQ_MODEL", "qwen/qwen3.8-27b"
            )
            candidate_models = [primary_model]
            backup_model = os.environ.get("GROQ_BACKUP_MODEL")
            if backup_model and backup_model not in candidate_models:
                candidate_models.append(backup_model)

            max_retries = int(os.environ.get("GROQ_MAX_RETRIES", "3"))
            backoff_base = float(os.environ.get("GROQ_BACKOFF_SECONDS", "1.5"))

            # Prune schema to dramatically reduce prompt token size
            pruned_schema = prune_json_schema(schema_cls.model_json_schema())
            schema_json = json.dumps(pruned_schema)
            json_prompt = (
                f"{prompt}\n\n"
                f"Respond ONLY with a valid JSON object matching this schema:\n"
                f"{schema_json}\n"
                f"Output strictly the raw JSON object without markdown or backticks."
            )

            for target_model in candidate_models:
                for attempt in range(max_retries + 1):
                    try:
                        # Throttle concurrent/burst requests to respect API rate limits
                        _global_rate_limiter.acquire()

                        attempt_label = (
                            f" (attempt {attempt + 1}/{max_retries + 1})"
                            if attempt > 0
                            else ""
                        )
                        print(
                            f"  -> [{self.agent_name}] Invoking Groq model ({target_model}){attempt_label}...",
                            flush=True,
                        )
                        logger.info(
                            f"{self.agent_name}: Dispatching prompt to Groq model ({target_model}){attempt_label}..."
                        )

                        chat_completion = self.groq_client.chat.completions.create(
                            model=target_model,
                            messages=[
                                {
                                    "role": "system",
                                    "content": f"You are {self.role_description}. Respond strictly with a valid JSON object adhering to the schema.",
                                },
                                {
                                    "role": "user",
                                    "content": json_prompt,
                                },
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.1,
                            max_tokens=int(os.environ.get("GROQ_MAX_TOKENS", "450")),
                        )

                        content = chat_completion.choices[0].message.content
                        if content:
                            data = json.loads(content)
                            report = ground_model_output(data, schema_cls, fallback_report)
                            if hasattr(report, "execution_mode"):
                                report.execution_mode = "LIVE_GROQ_MODEL"
                            logger.info(
                                f"{self.agent_name}: Successfully generated LIVE_GROQ_MODEL report using {target_model}."
                            )
                            return report
                        else:
                            logger.warning(
                                f"{self.agent_name}: Empty content from Groq ({target_model})."
                            )
                            break

                    except Exception as e:
                        err_str = str(e)
                        is_permanent = any(
                            code in err_str
                            for code in [
                                "401",
                                "invalid_api_key",
                                "403",
                                "404",
                                "model_not_found",
                            ]
                        )
                        if is_permanent:
                            logger.warning(
                                f"{self.agent_name}: Permanent Groq error encountered ({err_str}). Skipping retries."
                            )
                            print(
                                f"  -> [{self.agent_name}] Permanent error ({err_str[:80]}). Skipping retries.",
                                flush=True,
                            )
                            if hasattr(fallback_report, "execution_mode"):
                                fallback_report.execution_mode = (
                                    "DETERMINISTIC_FALLBACK"
                                )
                            return fallback_report

                        # Stop retrying if request permanently exceeds model context / token limits
                        if is_model_limit_exceeded(err_str):
                            logger.warning(
                                f"{self.agent_name}: Request permanently exceeds model context limits ({err_str[:120]}). Aborting retries."
                            )
                            print(
                                f"  -> [{self.agent_name}] Request exceeds model limits. Using deterministic fallback.",
                                flush=True,
                            )
                            if hasattr(fallback_report, "execution_mode"):
                                fallback_report.execution_mode = (
                                    "DETERMINISTIC_FALLBACK"
                                )
                            return fallback_report

                        is_connect_error = any(
                            code in err_str
                            for code in [
                                "Connection error",
                                "ConnectError",
                                "Network is unreachable",
                                "No route to host",
                                "Failed to resolve",
                            ]
                        )
                        if is_connect_error:
                            logger.warning(
                                f"{self.agent_name}: Network connection unreachable ({err_str[:80]}). Falling back to deterministic engine."
                            )
                            print(
                                f"  -> [{self.agent_name}] Network unreachable. Falling back to deterministic engine.",
                                flush=True,
                            )
                            if hasattr(fallback_report, "execution_mode"):
                                fallback_report.execution_mode = (
                                    "DETERMINISTIC_FALLBACK"
                                )
                            return fallback_report

                        is_rate_limit = any(
                            code in err_str
                            for code in ["429", "rate_limit", "Rate limit reached"]
                        )
                        is_transient = is_rate_limit or any(
                            code in err_str
                            for code in ["503", "504", "timeout", "Timeout"]
                        )

                        if attempt < max_retries and is_transient:
                            retry_after = (
                                extract_retry_after(e) if is_rate_limit else None
                            )
                            if retry_after is not None:
                                sleep_time = min(
                                    max(retry_after + random.uniform(0.1, 0.3), 0.5),
                                    15.0,
                                )
                                logger.warning(
                                    f"{self.agent_name}: Rate limit encountered. Respecting retry-after ({retry_after:.2f}s). Sleeping {sleep_time:.2f}s..."
                                )
                                print(
                                    f"  -> [{self.agent_name}] Rate limit (retry-after: {retry_after:.2f}s). Retrying in {sleep_time:.2f}s...",
                                    flush=True,
                                )
                            else:
                                jitter = random.uniform(0.1, 0.5)
                                sleep_time = min(
                                    backoff_base * (2**attempt) + jitter, 15.0
                                )
                                logger.warning(
                                    f"{self.agent_name}: Transient Groq error ({err_str[:80]}). Retrying in {sleep_time:.2f}s..."
                                )
                                print(
                                    f"  -> [{self.agent_name}] Transient error. Retrying in {sleep_time:.2f}s...",
                                    flush=True,
                                )
                            time.sleep(sleep_time)
                        else:
                            logger.warning(
                                f"{self.agent_name}: Groq attempt failed on {target_model}: {err_str[:100]}"
                            )
                            break

            logger.warning(
                f"{self.agent_name}: All live Groq attempts exhausted. Falling back to deterministic engine."
            )
            if hasattr(fallback_report, "execution_mode"):
                fallback_report.execution_mode = "DETERMINISTIC_FALLBACK"
            return fallback_report

        # Secondary fallback: Gemini if configured
        elif self.gemini_client:
            target_model = model_name or os.environ.get(
                "GEMINI_MODEL", "gemini-3.8-flash"
            )
            timeout_ms = int(os.environ.get("GEMINI_TIMEOUT_MS", "60000"))
            max_retries = int(os.environ.get("GEMINI_MAX_RETRIES", "2"))
            backoff_seconds = float(os.environ.get("GEMINI_BACKOFF_SECONDS", "2.0"))

            for attempt in range(max_retries + 1):
                try:
                    attempt_label = (
                        f" (attempt {attempt + 1}/{max_retries + 1})"
                        if attempt > 0
                        else ""
                    )
                    print(
                        f"  -> [{self.agent_name}] Invoking Gemini model ({target_model}){attempt_label}...",
                        flush=True,
                    )
                    logger.info(
                        f"{self.agent_name}: Dispatching prompt to Gemini model ({target_model}){attempt_label}..."
                    )
                    response = self.gemini_client.models.generate_content(
                        model=target_model,
                        contents=prompt,
                        config={
                            "response_mime_type": "application/json",
                            "response_schema": schema_cls,
                            "http_options": {"timeout": timeout_ms},
                        },
                    )
                    if response and response.text:
                        data = json.loads(response.text)
                        report = ground_model_output(data, schema_cls, fallback_report)
                        if hasattr(report, "execution_mode"):
                            report.execution_mode = "LIVE_GEMINI_MODEL"
                        logger.info(
                            f"{self.agent_name}: Successfully generated LIVE_GEMINI_MODEL report using {target_model}."
                        )
                        return report
                    else:
                        break
                except Exception as e:
                    err_str = str(e)
                    is_permanent = any(
                        code in err_str
                        for code in [
                            "404",
                            "NOT_FOUND",
                            "401",
                            "UNAUTHENTICATED",
                            "403",
                            "PERMISSION_DENIED",
                            "400",
                            "INVALID_ARGUMENT",
                        ]
                    )
                    if is_permanent:
                        break
                    is_transient = any(
                        code in err_str
                        for code in [
                            "504",
                            "DEADLINE_EXCEEDED",
                            "429",
                            "RESOURCE_EXHAUSTED",
                            "503",
                            "UNAVAILABLE",
                            "timeout",
                            "Timeout",
                            "ConnectError",
                        ]
                    )
                    if attempt < max_retries and is_transient:
                        jitter = random.uniform(0.1, 0.5)
                        sleep_time = backoff_seconds * (2**attempt) + jitter
                        time.sleep(sleep_time)
                    else:
                        break

        # Deterministic engine fallback
        logger.warning(
            f"{self.agent_name}: All live LLM attempts failed or not configured. Falling back to deterministic engine."
        )
        if hasattr(fallback_report, "execution_mode"):
            fallback_report.execution_mode = "DETERMINISTIC_FALLBACK"
        return fallback_report

    invoke_gemini_analysis = invoke_llm_analysis

    def supplementary_context(self, ticker: str, categories: List[str], trace_id: str = "", cap: int = 8) -> str:
        """Compact, labelled supplementary evidence (official disclosures, macro) for a prompt; '' if none."""
        path = self.data_dir / "processed" / "supplementary" / f"{ticker.lower()}_evidence.parquet"
        if not path.exists():
            return ""
        import pandas as pd

        df = pd.read_parquet(path)
        if df.empty:
            return ""
        lines = []
        for title, cats, note in (
            ("Official/supplementary sources", categories, ""),
            ("Macro context (not company-specific)", ["macro"], ""),
        ):
            for _, r in df[df["category"].isin(cats)].head(cap).iterrows():
                g = lambda k, d="": d if pd.isna(r.get(k)) or r.get(k) in (None, "") else r.get(k)  # NaN-safe cell
                tag = f"{r['source_name']} | {str(g('published_at', 'undated'))[:10]} | {r['url']}"
                source = f"{r['source_id']} {r['source_name']}".lower()
                extra = ""
                if "world" in source and "bank" in source:
                    extra = f" [annual/structural indicator, data year {g('period', 'unknown')}]"
                if "nse" in source and "mcp" in source:
                    extra += " [informational, delayed; not for trading or order prices]"
                if g("value") != "":
                    extra += f" [{g('indicator')} {g('value')} {g('unit')}]"
                lines.append(f"- ({title}) {r['title'][:120]} - {str(g('summary'))[:160]} ({tag}){extra}")
        if not lines:
            return ""
        text = "\nSupplementary evidence (cite source, date, URL):\n" + "\n".join(lines)
        from kairos.observability.prompt_guard import guard_untrusted_text

        guard_untrusted_text(text, self.config_key or "analyst", self.callback_manager, trace_id)
        return text

    def run_analysis(self, ticker: str, trace_id: Optional[str] = None) -> BaseModel:
        """Subclasses must implement specific analysis logic returning a Pydantic report."""
        raise NotImplementedError

    def analyze(self, ticker: str, trace_id: Optional[str] = None) -> BaseModel:
        """Executes analyst workflow with tracing, callbacks, and guardrail validation."""
        ticker = ticker.upper().strip()
        trace_id = trace_id or generate_trace_id()
        start_time = time.perf_counter()

        self.callback_manager.dispatch(
            "on_analyst_start", self.agent_name, ticker, trace_id
        )

        with global_tracer.span(self.agent_name, trace_id) as span:
            span.set_attribute("ticker", ticker)
            span.set_attribute("agent_role", self.role_description)

            try:
                report = self.run_analysis(ticker, trace_id)
                latency_ms = (time.perf_counter() - start_time) * 1000.0

                # Validate institutional guardrails
                guardrail_results = self.guardrails.validate_analyst_report(
                    report, self.output_schema, context={"target_ticker": ticker}
                )
                failed_guardrails = [g for g in guardrail_results if not g.passed]
                if failed_guardrails:
                    err_msg = f"Guardrail failures in {self.agent_name}: " + "; ".join(
                        f"[{g.guardrail_name}] {g.errors}" for g in failed_guardrails
                    )
                    logger.error(err_msg)
                    raise ValueError(err_msg)

                span.set_attribute("report", report.model_dump(mode="json"))
                span.set_attribute("execution_mode", getattr(report, "execution_mode", "UNKNOWN"))
                span.set_attribute("latency_ms", latency_ms)
                span.set_attribute("guardrails_passed", True)

                self.callback_manager.dispatch(
                    "on_analyst_complete",
                    self.agent_name,
                    ticker,
                    report,
                    latency_ms,
                    trace_id,
                )
                return report

            except Exception as e:
                self.callback_manager.dispatch("on_error", self.agent_name, e, trace_id)
                logger.error(
                    f"Analysis failed in {self.agent_name} for {ticker}: {e}",
                    exc_info=True,
                )
                raise

    def create_a2a_envelope(
        self, report: BaseModel, recipient_agent: str, trace_id: str
    ) -> A2ATaskEnvelope:
        """Encapsulates report into an HMAC-signed A2ATaskEnvelope for CrewAI dispatch."""
        envelope = A2ATaskEnvelope(
            trace_id=trace_id,
            sender_agent=self.agent_name,
            recipient_agent=recipient_agent,
            task_type=self.task_message_type,
            payload=report.model_dump(),
        )
        envelope.sign(self.secret_key)
        return envelope
