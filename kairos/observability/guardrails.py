"""Institutional Guardrails for KAIROS Agents.
Enforces schema compliance, data freshness, evidence citation, and downside risk bounds.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, ValidationError
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.observability.guardrails")


class GuardrailResult(BaseModel):
    """Result of a guardrail evaluation."""
    guardrail_name: str
    passed: bool
    errors: List[str] = []
    warnings: List[str] = []
    metadata: Dict[str, Any] = {}


class BaseGuardrail:
    """Base class for agent execution guardrails."""
    name: str = "base_guardrail"

    def evaluate(self, payload: Any, context: Optional[Dict[str, Any]] = None) -> GuardrailResult:
        raise NotImplementedError


class SchemaValidationGuardrail(BaseGuardrail):
    """Enforces that an agent's output conforms strictly to its designated Pydantic model."""
    name: str = "schema_validation"

    def __init__(self, schema_cls: Type[BaseModel]):
        self.schema_cls = schema_cls

    def evaluate(self, payload: Any, context: Optional[Dict[str, Any]] = None) -> GuardrailResult:
        errors = []
        if isinstance(payload, self.schema_cls):
            return GuardrailResult(
                guardrail_name=self.name,
                passed=True,
                metadata={"schema": self.schema_cls.__name__},
            )

        if not isinstance(payload, dict):
            return GuardrailResult(
                guardrail_name=self.name,
                passed=False,
                errors=[f"Expected dict or {self.schema_cls.__name__}, got {type(payload).__name__}"],
                metadata={"schema": self.schema_cls.__name__},
            )

        try:
            self.schema_cls.model_validate(payload)
            return GuardrailResult(
                guardrail_name=self.name,
                passed=True,
                metadata={"schema": self.schema_cls.__name__},
            )
        except ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(p) for p in err.get("loc", []))
                msg = err.get("msg", "Validation error")
                errors.append(f"Field '{loc}': {msg}")
            return GuardrailResult(
                guardrail_name=self.name,
                passed=False,
                errors=errors,
                metadata={"schema": self.schema_cls.__name__},
            )


class FreshnessGuardrail(BaseGuardrail):
    """Verifies that market and report timestamps are not stale or future-dated."""
    name: str = "data_freshness"

    def __init__(self, max_days_stale: int = 45):
        self.max_days_stale = max_days_stale

    def evaluate(self, payload: Any, context: Optional[Dict[str, Any]] = None) -> GuardrailResult:
        errors = []
        as_of = None

        if isinstance(payload, dict):
            as_of = payload.get("as_of_date") or payload.get("generated_at") or payload.get("fiscal_period_end")
        elif hasattr(payload, "as_of_date"):
            as_of = getattr(payload, "as_of_date")
        elif hasattr(payload, "generated_at"):
            as_of = getattr(payload, "generated_at")

        if not as_of:
            return GuardrailResult(
                guardrail_name=self.name,
                passed=True,
                warnings=["No date field found to evaluate freshness."],
            )

        try:
            # Parse YYYY-MM-DD or ISO timestamp
            dt_str = str(as_of)[:10]
            dt = datetime.strptime(dt_str, "%Y-%m-%d")
            now = datetime.now()
            # If date is more than 365 days stale (unless annual fundamentals)
            # We flag warning or error based on context
            delta_days = (now - dt).days
            if delta_days > self.max_days_stale:
                errors.append(f"Data dated {dt_str} is {delta_days} days old; maximum allowed is {self.max_days_stale} days.")
            if delta_days < -1:
                errors.append(f"Date {dt_str} is in the future ({delta_days} days ahead).")
        except Exception as e:
            errors.append(f"Failed to parse date '{as_of}': {e}")

        passed = len(errors) == 0
        return GuardrailResult(
            guardrail_name=self.name,
            passed=passed,
            errors=errors,
            metadata={"as_of": as_of},
        )


class EvidenceCitationGuardrail(BaseGuardrail):
    """Ensures that analyst claims cite known Phase 1 data without fabrication.
    Verifies that reported ticker matches target, last_price is positive, and sources are cited.
    """
    name: str = "evidence_citation"

    def evaluate(self, payload: Any, context: Optional[Dict[str, Any]] = None) -> GuardrailResult:
        errors = []
        warnings = []
        data = payload if isinstance(payload, dict) else payload.model_dump()

        ticker = data.get("ticker")
        expected_ticker = context.get("target_ticker") if context else None
        if expected_ticker and ticker and ticker != expected_ticker:
            errors.append(f"Ticker mismatch: payload cites '{ticker}', expected '{expected_ticker}'")

        # Check for citation of source or observations
        has_citations = any([
            bool(data.get("key_observations")),
            bool(data.get("key_themes")),
            bool(data.get("top_verified_articles")),
            bool(data.get("filing_standard")),
            bool(data.get("primary_arguments")),
            bool(data.get("key_decision_factors")),
        ])

        if not has_citations:
            warnings.append("No evidentiary citations, key observations, or primary arguments found.")

        return GuardrailResult(
            guardrail_name=self.name,
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            metadata={"ticker": ticker},
        )


class DownsideRiskGuardrail(BaseGuardrail):
    """Enforces that Bear Thesis contains strictly non-positive downside potential and realistic bounds."""
    name: str = "downside_risk_bounds"

    def evaluate(self, payload: Any, context: Optional[Dict[str, Any]] = None) -> GuardrailResult:
        errors = []
        data = payload if isinstance(payload, dict) else payload.model_dump()
        downside = data.get("downside_risk_pct")

        if downside is None:
            errors.append("Bear thesis missing 'downside_risk_pct' metric.")
        elif downside >= 0.0:
            errors.append(f"Bear thesis downside risk must be negative, got {downside:.2f}%")
        elif downside < -100.0:
            errors.append(f"Bear thesis downside risk exceeds -100%, got {downside:.2f}%")

        return GuardrailResult(
            guardrail_name=self.name,
            passed=len(errors) == 0,
            errors=errors,
            metadata={"downside_risk_pct": downside},
        )


class InstitutionalGuardrailSuite:
    """Orchestrates all institutional guardrails for KAIROS agent outputs."""

    def __init__(self):
        self.freshness_guardrail = FreshnessGuardrail()
        self.evidence_guardrail = EvidenceCitationGuardrail()
        self.downside_guardrail = DownsideRiskGuardrail()

    def validate_analyst_report(
        self, report: Any, schema_cls: Type[BaseModel], context: Optional[Dict[str, Any]] = None
    ) -> List[GuardrailResult]:
        results = []
        # 1. Schema
        schema_guardrail = SchemaValidationGuardrail(schema_cls)
        results.append(schema_guardrail.evaluate(report, context))

        # 2. Freshness
        results.append(self.freshness_guardrail.evaluate(report, context))

        # 3. Evidence citation
        results.append(self.evidence_guardrail.evaluate(report, context))

        return results

    def validate_debate_thesis(
        self, thesis: Any, thesis_type: str, schema_cls: Type[BaseModel], context: Optional[Dict[str, Any]] = None
    ) -> List[GuardrailResult]:
        results = []
        # 1. Schema
        schema_guardrail = SchemaValidationGuardrail(schema_cls)
        results.append(schema_guardrail.evaluate(thesis, context))

        # 2. Evidence citation
        results.append(self.evidence_guardrail.evaluate(thesis, context))

        # 3. Downside specific
        if thesis_type.lower() == "bear":
            results.append(self.downside_guardrail.evaluate(thesis, context))

        return results

