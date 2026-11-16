"""CrewAI Bear Researcher Agent for KAIROS ARGUE Stage.
Constructs an evidence-backed bear thesis evaluating downside risk and vulnerabilities.
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
from kairos.schemas.analyst_reports import BearThesis, SignalStrength, sentiment_prompt_line
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.crewai.bear")


class BearResearcher:
    """Institutional Sell-Side Bear Risk Researcher."""

    def __init__(self, callback_manager: Optional[CallbackManager] = None):
        self.callback_manager = callback_manager or CallbackManager()
        self.guardrails = InstitutionalGuardrailSuite()

        self.crew_agent = create_research_agent("bear_researcher")

    def create_task(
        self,
        ticker: str,
        analyst_reports: Dict[str, Any],
        round_num: int = 1,
        context: Optional[List[Task]] = None,
    ) -> Task:
        """Constructs a genuine CrewAI Task for the Bear Researcher.
        Round 1: Initial Bear Thesis formulation evaluating liabilities and downside.
        Round N (>1): Bear Counter-Rebuttal stress-testing Bull defenses.
        """
        mkt = analyst_reports.get("market", {})
        fund = analyst_reports.get("fundamentals", {})
        news = analyst_reports.get("news", {})

        mkt_price = float(mkt.get("last_price", 0.0))
        support = float(mkt.get("support_level", 0.0))
        resistance = float(mkt.get("resistance_level", 0.0))
        debt_eq = fund.get("debt_to_equity")
        liab = float(fund.get("total_liabilities", 0.0))
        top_risks = news.get("regulatory_and_litigation_risks", [])[:2]

        if round_num == 1:
            task_config = render_task(
                "bear_thesis",
                ticker=ticker,
                mkt_price=mkt_price,
                support=support,
                resistance=resistance,
                debt_eq=debt_eq,
                liab=liab,
                top_risks=top_risks,
                sentiment=sentiment_prompt_line(analyst_reports.get("sentiment", {})),
                round_num=round_num,
            )
        else:
            task_config = render_task(
                "bear_rebuttal",
                round_num=round_num,
                ticker=ticker,
            )

        return Task(
            config=task_config,
            agent=self.crew_agent,
            output_pydantic=BearThesis,
            context=context or [],
        )

    def generate_bear_thesis(
        self,
        ticker: str,
        analyst_reports: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> BearThesis:
        """Constructs an institutional Bear thesis with strictly negative downside bounds."""
        trace_id = trace_id or "trace-kairos-bear"

        with global_tracer.span("crewai.bear_researcher", trace_id) as span:
            span.set_attribute("ticker", ticker)

            mkt = analyst_reports.get("market", {})
            sentiment = analyst_reports.get("sentiment", {})
            news = analyst_reports.get("news", {})
            fund = analyst_reports.get("fundamentals", {})

            last_price = mkt.get("last_price", 1000.0)
            support = mkt.get("support_level", last_price * 0.90)
            debt_to_equity = fund.get("debt_to_equity")

            # Compute downside risk strictly negative
            pct_to_support = ((support - last_price) / last_price) * 100.0
            if pct_to_support >= 0.0:
                pct_to_support = -5.0

            # Fundamental multiple compression stress
            base_downside = min(pct_to_support, -8.0)
            if (
                debt_to_equity
                and debt_to_equity > 1.5
                and ticker not in ["HDFCBANK", "ICICIBANK"]
            ):
                base_downside -= 5.0

            downside_risk_pct = round(max(-50.0, min(-5.0, base_downside)), 2)

            # Assemble primary arguments
            primary_arguments = [
                f"Technical downside exposure to key support at ₹{support:,.2f} representing a {downside_risk_pct:.1f}% potential drawdown.",
                f"Macro/multiple compression risks amid {fund.get('reporting_currency', 'INR')} liabilities of {fund.get('total_liabilities', 0.0):,.0f}.",
            ]

            if news.get("regulatory_and_litigation_risks"):
                primary_arguments.append(
                    f"Regulatory/compliance sensitivity: {news['regulatory_and_litigation_risks'][0]}"
                )

            vulnerabilities = [
                f"Total corporate liabilities of {fund.get('total_liabilities', 0.0):,.0f} {fund.get('reporting_currency', 'INR')}",
                f"Valuation sensitivity if margin shrinks below {fund.get('profit_margins', 0.15) * 100:.1f}%",
            ]

            trigger_events = [
                "Unexpected monetary policy tightening or interest rate surge by RBI",
                "Adverse regulatory decree or tax compliance inquiry",
                f"Breakdown below technical support level of ₹{support:,.2f}",
            ]

            thesis = BearThesis(
                ticker=ticker,
                primary_arguments=primary_arguments,
                downside_risk_pct=downside_risk_pct,
                vulnerabilities=vulnerabilities,
                trigger_events=trigger_events,
                conviction_level=SignalStrength.MODERATE,
                researcher_name="crewai.bear_researcher",
                execution_mode="DETERMINISTIC_FALLBACK",
            )

            # Validate guardrails (enforces downside < 0.0)
            guardrail_res = self.guardrails.validate_debate_thesis(
                thesis, "bear", BearThesis, context={"target_ticker": ticker}
            )
            failed = [g for g in guardrail_res if not g.passed]
            if failed:
                err = f"Bear researcher guardrail failure: {failed[0].errors}"
                logger.error(err)
                raise ValueError(err)

            self.callback_manager.dispatch(
                "on_thesis_generated",
                "crewai.bear_researcher",
                ticker,
                thesis,
                trace_id,
            )
            return thesis

    def generate_bear_rebuttal(
        self,
        initial_bear: BearThesis,
        bull_thesis: Any,
        analyst_reports: Dict[str, Any],
        round_num: int = 2,
        trace_id: Optional[str] = None,
    ) -> BearThesis:
        """Deterministic fallback: Generates a refined Bear counter-rebuttal stress-testing Bull defenses."""
        ticker = initial_bear.ticker
        trace_id = trace_id or "trace-kairos-bear-rebuttal"

        with global_tracer.span(
            f"crewai.bear_researcher.round_{round_num}", trace_id
        ) as span:
            span.set_attribute("ticker", ticker)
            span.set_attribute("round", round_num)

            bull_upside = getattr(bull_thesis, "upside_potential_pct", 15.0)
            bull_catalysts = getattr(bull_thesis, "catalysts", [])

            rebuttal_args = [
                f"[Round {round_num} Counter] Challenged Bull upside of +{bull_upside:.1f}%: multiple expansion is capped by historical valuation ceiling.",
                f"[Round {round_num} Stress Test] Reasserted downside risk of {initial_bear.downside_risk_pct:.1f}% given prevailing interest rate and overhead resistance hurdles.",
            ]
            if bull_catalysts:
                rebuttal_args.append(
                    f"Discounted catalyst '{bull_catalysts[0]}' due to potential execution latency and sector headwinds."
                )

            rebuttal_thesis = BearThesis(
                ticker=ticker,
                primary_arguments=rebuttal_args,
                downside_risk_pct=initial_bear.downside_risk_pct,
                vulnerabilities=initial_bear.vulnerabilities,
                trigger_events=initial_bear.trigger_events,
                conviction_level=initial_bear.conviction_level,
                researcher_name="crewai.bear_researcher",
                debate_round=round_num,
                execution_mode="DETERMINISTIC_FALLBACK",
            )
            return rebuttal_thesis
