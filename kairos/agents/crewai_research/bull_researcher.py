"""CrewAI Bull Researcher Agent for KAIROS ARGUE Stage.
Constructs an evidence-backed bull thesis evaluating upside potential and catalysts.
"""

from typing import Any, Dict, List, Optional

from kairos.agents.crewai_research.crewai_patch import ensure_crewai_patched

ensure_crewai_patched()

from crewai import Task
from kairos.config.agent_definitions import render_task
from kairos.agents.crewai_research.runtime import create_research_agent
from kairos.observability.callbacks import CallbackManager
from kairos.observability.guardrails import InstitutionalGuardrailSuite
from kairos.observability.tracer import global_tracer
from kairos.schemas.analyst_reports import BullThesis, SignalStrength, sentiment_prompt_line
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.crewai.bull")


class BullResearcher:
    """Institutional Buy-Side Bull Equity Researcher."""

    def __init__(self, callback_manager: Optional[CallbackManager] = None):
        self.callback_manager = callback_manager or CallbackManager()
        self.guardrails = InstitutionalGuardrailSuite()

        self.crew_agent = create_research_agent("bull_researcher")

    def create_task(
        self,
        ticker: str,
        analyst_reports: Dict[str, Any],
        round_num: int = 1,
        context: Optional[List[Task]] = None,
    ) -> Task:
        """Constructs a genuine CrewAI Task for the Bull Researcher.
        Round 1: Initial Bull Thesis formulation based on analyst reports.
        Round N (>1): Bull Rebuttal defending growth thesis against Bear counter-arguments.
        """
        mkt = analyst_reports.get("market", {})
        fund = analyst_reports.get("fundamentals", {})
        news = analyst_reports.get("news", {})
        sentiment = analyst_reports.get("sentiment", {})

        mkt_price = float(mkt.get("last_price", 0.0))
        support = float(mkt.get("support_level", 0.0))
        resistance = float(mkt.get("resistance_level", 0.0))
        margin = fund.get("profit_margins", 0.0)
        solvency = fund.get("solvency_health", "MODERATE")
        top_cats = news.get("key_catalysts", [])[:2]
        bull_ratio = float(sentiment.get("retail_bull_ratio", 0.5))

        if round_num == 1:
            task_config = render_task(
                "bull_thesis",
                ticker=ticker,
                mkt_price=mkt_price,
                support=support,
                resistance=resistance,
                margin=margin,
                solvency=solvency,
                sentiment=sentiment_prompt_line(sentiment),
                top_cats=top_cats,
                round_num=round_num,
            )
        else:
            task_config = render_task(
                "bull_rebuttal",
                round_num=round_num,
                ticker=ticker,
            )

        return Task(
            config=task_config,
            agent=self.crew_agent,
            output_pydantic=BullThesis,
            context=context or [],
        )

    def generate_bull_thesis(
        self,
        ticker: str,
        analyst_reports: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> BullThesis:
        """Constructs an institutional Bull thesis from the 4 analyst reports."""
        trace_id = trace_id or "trace-kairos-bull"

        with global_tracer.span("crewai.bull_researcher", trace_id) as span:
            span.set_attribute("ticker", ticker)

            mkt = analyst_reports.get("market", {})
            sentiment = analyst_reports.get("sentiment", {})
            news = analyst_reports.get("news", {})
            fund = analyst_reports.get("fundamentals", {})

            last_price = mkt.get("last_price", 1000.0)
            resistance = mkt.get("resistance_level", last_price * 1.10)
            margins = fund.get("profit_margins", 0.15) or 0.15
            bull_ratio = sentiment.get("retail_bull_ratio", 0.50)

            # Compute upside target
            price_upside_to_resistance = max(
                5.0, ((resistance - last_price) / last_price) * 100.0
            )
            fundamental_expansion_pct = min(25.0, max(8.0, margins * 100.0))
            upside_potential_pct = round(
                (price_upside_to_resistance * 0.4) + (fundamental_expansion_pct * 0.6),
                2,
            )
            upside_potential_pct = max(5.0, min(45.0, upside_potential_pct))

            # Assemble primary arguments
            primary_arguments = [
                f"Solid earnings engine with reported annual revenue of {fund.get('revenue', 0.0):,.0f} {fund.get('reporting_currency', 'INR')} and {margins * 100:.1f}% net margin.",
                f"Balance sheet solvency characterized as {fund.get('solvency_health', 'ROBUST')} under {fund.get('filing_standard', 'mca-ind-as')} filing standards.",
                f"Technical posture indicates support established at ₹{mkt.get('support_level', 0.0):,.2f} with 20-day SMA at ₹{mkt.get('indicators', {}).get('sma_20', 0.0):,.2f}.",
            ]

            if news.get("key_catalysts"):
                primary_arguments.append(f"Media catalyst: {news['key_catalysts'][0]}")

            # Conviction level
            if fund.get("solvency_health") == "ROBUST" and bull_ratio >= 0.50 and sentiment.get("data_source") != "SOURCE_UNAVAILABLE":
                conviction = SignalStrength.STRONG
            elif fund.get("solvency_health") in ["ROBUST", "MODERATE"]:
                conviction = SignalStrength.MODERATE
            else:
                conviction = SignalStrength.WEAK

            catalysts = list(news.get("key_catalysts", []))
            if not catalysts:
                catalysts = [f"Institutional accumulation in {ticker}"]

            acknowledged_risks = list(news.get("regulatory_and_litigation_risks", []))
            acknowledged_risks.append(
                f"Near-term technical overhead resistance at ₹{resistance:,.2f}"
            )

            thesis = BullThesis(
                ticker=ticker,
                target_horizon_months=12,
                primary_arguments=primary_arguments,
                upside_potential_pct=upside_potential_pct,
                catalysts=catalysts,
                acknowledged_risks=acknowledged_risks,
                conviction_level=conviction,
                researcher_name="crewai.bull_researcher",
                execution_mode="DETERMINISTIC_FALLBACK",
            )

            # Validate guardrails
            guardrail_res = self.guardrails.validate_debate_thesis(
                thesis, "bull", BullThesis, context={"target_ticker": ticker}
            )
            failed = [g for g in guardrail_res if not g.passed]
            if failed:
                err = f"Bull researcher guardrail failure: {failed[0].errors}"
                logger.error(err)
                raise ValueError(err)

            self.callback_manager.dispatch(
                "on_thesis_generated",
                "crewai.bull_researcher",
                ticker,
                thesis,
                trace_id,
            )
            return thesis

    def generate_bull_rebuttal(
        self,
        initial_bull: BullThesis,
        bear_thesis: Any,
        analyst_reports: Dict[str, Any],
        round_num: int = 2,
        trace_id: Optional[str] = None,
    ) -> BullThesis:
        """Deterministic fallback: Generates a refined Bull rebuttal addressing Bear arguments."""
        ticker = initial_bull.ticker
        trace_id = trace_id or "trace-kairos-bull-rebuttal"

        with global_tracer.span(
            f"crewai.bull_researcher.round_{round_num}", trace_id
        ) as span:
            span.set_attribute("ticker", ticker)
            span.set_attribute("round", round_num)

            # Refine upside taking into account acknowledged bear risks
            adjusted_upside = max(
                5.0, round(initial_bull.upside_potential_pct * 0.96, 2)
            )
            downside_val = getattr(bear_thesis, "downside_risk_pct", -10.0)
            bear_vulns = getattr(bear_thesis, "vulnerabilities", [])
            bear_triggers = getattr(bear_thesis, "trigger_events", [])

            rebuttal_args = [
                f"[Round {round_num} Rebuttal] Rebutted Bear downside of {downside_val:.1f}%: balance sheet solvency and operating cash flows absorb near-term macro shocks.",
                f"[Round {round_num} Moat Defense] Sustaining primary driver: {initial_bull.primary_arguments[0]}",
            ]
            if bear_vulns:
                rebuttal_args.append(
                    f"Addressed vulnerability '{bear_vulns[0]}': corporate margins maintain adequate downside margin of safety."
                )

            new_acknowledged_risks = list(initial_bull.acknowledged_risks)
            if bear_triggers and bear_triggers[0] not in new_acknowledged_risks:
                new_acknowledged_risks.append(
                    f"Monitored catalyst trigger: {bear_triggers[0]}"
                )

            rebuttal_thesis = BullThesis(
                ticker=ticker,
                target_horizon_months=initial_bull.target_horizon_months,
                primary_arguments=rebuttal_args,
                upside_potential_pct=adjusted_upside,
                catalysts=initial_bull.catalysts,
                acknowledged_risks=new_acknowledged_risks,
                conviction_level=initial_bull.conviction_level,
                researcher_name="crewai.bull_researcher",
                debate_round=round_num,
                execution_mode="DETERMINISTIC_FALLBACK",
            )
            return rebuttal_thesis
