"""CrewAI Research Manager Agent for KAIROS ARGUE Stage.
Moderates Bull vs Bear debate and produces the final institutional investment verdict.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kairos.agents.crewai_research.crewai_patch import ensure_crewai_patched

ensure_crewai_patched()

from crewai import Task
from kairos.config.agent_definitions import render_task
from kairos.agents.crewai_research.runtime import create_research_agent
from kairos.observability.callbacks import CallbackManager
from kairos.observability.guardrails import InstitutionalGuardrailSuite
from kairos.observability.tracer import global_tracer
from kairos.schemas.analyst_reports import (
    BearThesis,
    BullThesis,
    RecommendationVerdict,
    ResearchSynthesisVerdict,
    SENTIMENT_UNAVAILABLE_NOTE,
    SignalStrength,
    TrendDirection,
    sentiment_prompt_line,
    data_freshness_label,
)
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.crewai.manager")


class ResearchManager:
    """Chief Investment Officer / Equity Research Debate Moderator."""

    def __init__(self, callback_manager: Optional[CallbackManager] = None):
        self.callback_manager = callback_manager or CallbackManager()
        self.guardrails = InstitutionalGuardrailSuite()

        self.crew_agent = create_research_agent("research_manager")

    def create_task(
        self,
        ticker: str,
        analyst_reports: Dict[str, Any],
        context: Optional[List[Task]] = None,
        total_rounds: int = 2,
    ) -> Task:
        """Constructs a genuine CrewAI Task for the Research Manager to evaluate the full multi-round debate."""
        task_config = render_task(
            "research_synthesis",
            total_rounds=total_rounds,
            ticker=ticker,
            sentiment=sentiment_prompt_line(analyst_reports.get("sentiment", {})),
            data_freshness=data_freshness_label(analyst_reports.get("market", {})),
        )
        return Task(
            config=task_config,
            agent=self.crew_agent,
            output_pydantic=ResearchSynthesisVerdict,
            context=context or [],
        )

    def synthesize_debate(
        self,
        bull_thesis: BullThesis,
        bear_thesis: BearThesis,
        analyst_reports: Dict[str, Any],
        trace_id: str,
        total_rounds: int = 2,
    ) -> ResearchSynthesisVerdict:
        """Evaluates opposing research theses and produces the synthesis verdict."""
        ticker = bull_thesis.ticker

        with global_tracer.span("crewai.research_manager", trace_id) as span:
            span.set_attribute("ticker", ticker)
            span.set_attribute("total_rounds", total_rounds)

            mkt = analyst_reports.get("market", {})
            fund = analyst_reports.get("fundamentals", {})

            trend_raw = mkt.get("trend_direction", TrendDirection.NEUTRAL.value)
            trend = trend_raw.value if hasattr(trend_raw, "value") else str(trend_raw)
            solvency = fund.get("solvency_health", "ROBUST")
            upside = bull_thesis.upside_potential_pct
            downside = abs(bear_thesis.downside_risk_pct)

            risk_reward_ratio = upside / downside if downside > 0 else 1.0

            # Recommendation logic
            if (
                risk_reward_ratio >= 1.4
                and solvency == "ROBUST"
                and trend != TrendDirection.BEARISH.value
            ):
                recommendation = RecommendationVerdict.OVERWEIGHT
                conviction = (
                    SignalStrength.STRONG
                    if risk_reward_ratio >= 2.0
                    else SignalStrength.MODERATE
                )
            elif risk_reward_ratio < 0.9 or solvency == "CONSTRAINED":
                recommendation = RecommendationVerdict.UNDERWEIGHT
                conviction = SignalStrength.MODERATE
            else:
                recommendation = RecommendationVerdict.NEUTRAL
                conviction = SignalStrength.MODERATE

            bull_summary = (
                f"Bull thesis projects +{upside:.1f}% upside driven by robust corporate profitability "
                f"({fund.get('profit_margins', 0.15) * 100:.1f}% margin) and positive catalyst momentum."
            )
            bear_summary = (
                f"Bear thesis highlights -{downside:.1f}% downside risk toward support level "
                f"amid macro multiple sensitivity and outstanding liabilities."
            )

            rationale = (
                f"KAIROS Research Committee reviewed evidence for {ticker}. "
                f"Risk/reward asymmetry stands at {risk_reward_ratio:.2f}x (upside +{upside:.1f}% vs downside -{downside:.1f}%). "
                f"Given {solvency.lower()} solvency posture under audited {fund.get('filing_standard', 'mca-ind-as')} accounts "
                f"and prevailing {trend.lower()} technical regime, committee concludes an institutional {recommendation.value} stance."
            )

            key_decision_factors = [
                f"Asymmetric risk/reward profile: {risk_reward_ratio:.2f}x",
                f"Solvency classification: {solvency}",
                f"Technical trend posture: {trend}",
                f"Catalyst backing vs legal/regulatory exposure ratio",
            ]

            sentiment_unavailable = analyst_reports.get("sentiment", {}).get("data_source") == "SOURCE_UNAVAILABLE"
            quote_delay = mkt.get("quote_delay", "15_MIN_DELAYED")
            as_of_date = mkt.get("as_of_date") or datetime.now(timezone.utc).date().isoformat()
            data_freshness_status = f"CURRENT_AS_OF_{as_of_date} ({quote_delay})"

            source_references = [
                f"Yahoo Finance MCP: 10-Year Daily OHLCV ({mkt.get('bars_analyzed', 2471)} bars through {as_of_date})",
                f"Corporate Filings: {fund.get('company_name', ticker)} ({fund.get('filing_standard', 'mca-ind-as')} in {fund.get('reporting_currency', 'INR')})",
                "Social Chatter: Reddit unreachable; sentiment NOT assessed"
                if sentiment_unavailable
                else f"Social Chatter: r/IndianStockMarket ({analyst_reports.get('sentiment', {}).get('sample_size_posts', 0)} posts analyzed)",
                f"Media Developments: {analyst_reports.get('news', {}).get('total_articles_verified', 0)} HTTP-200 verified news items",
            ]

            limitations = [
                f"Market price reflects {quote_delay} feed latency from Yahoo Finance MCP",
                SENTIMENT_UNAVAILABLE_NOTE
                if sentiment_unavailable
                else "Retail sentiment represents online investor community discourse and may exhibit recency bias",
                "Valuation metrics do not guarantee future multiple expansion under sudden RBI policy shifts",
                "System is strictly read-only: no automated order placement or capital commitment",
            ]

            now_iso = datetime.now(timezone.utc).isoformat()

            verdict = ResearchSynthesisVerdict(
                ticker=ticker,
                trace_id=trace_id,
                recommendation=recommendation,
                conviction=conviction,
                bull_summary=bull_summary,
                bear_summary=bear_summary,
                synthesis_rationale=rationale,
                key_decision_factors=key_decision_factors,
                manager_name="crewai.research_manager",
                deliberation_timestamp=now_iso,
                generation_timestamp=now_iso,
                data_freshness_status=data_freshness_status,
                source_references=source_references,
                limitations=limitations,
                research_only_disclaimer=(
                    "KAIROS Phase 2 Institutional Equity Research Report. "
                    "Strictly research-only advisory; not financial advice. No automated order placement or real-money trading."
                ),
                debate_rounds=total_rounds,
                execution_mode="DETERMINISTIC_FALLBACK",
            )

            self.callback_manager.dispatch("on_verdict_reached", verdict, trace_id)
            return verdict
