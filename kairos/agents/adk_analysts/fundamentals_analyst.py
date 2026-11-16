"""Google ADK Fundamentals Analyst Agent for KAIROS.
Consumes balance sheet and income statement filings (SEC 20-F for INFY, MCA Ind-AS for domestic peers).
"""

from pathlib import Path
from typing import Optional
import pandas as pd

from kairos.a2a.contract import A2AMessageType
from kairos.agents.adk_analysts.base_analyst import BaseADKAnalyst
from kairos.schemas.analyst_reports import (
    FundamentalsAnalysisReport,
    ValuationPosture,
)
from kairos.config.agent_definitions import render_task
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.adk_analysts.fundamentals")


class FundamentalsAnalyst(BaseADKAnalyst):
    """Specialist Analyst evaluating balance sheet solvency, margins, cash flows, and filing standards."""

    agent_name: str = "google_adk.fundamentals_analyst"
    config_key: str = "fundamentals_analyst"
    task_message_type: A2AMessageType = A2AMessageType.FUNDAMENTALS_REPORT
    output_schema = FundamentalsAnalysisReport

    def _load_fundamentals_data(self, ticker: str) -> pd.DataFrame:
        fund_dir = self.data_dir / "processed" / "fundamentals"
        pq_path = fund_dir / f"{ticker.lower()}_summary_clean.parquet"
        csv_path = fund_dir / f"{ticker.lower()}_summary_clean.csv"

        if pq_path.exists():
            return pd.read_parquet(pq_path)
        elif csv_path.exists():
            return pd.read_csv(csv_path)
        else:
            raise FileNotFoundError(
                f"No fundamentals summary found for {ticker} in {fund_dir}"
            )

    def run_analysis(
        self, ticker: str, trace_id: Optional[str] = None
    ) -> FundamentalsAnalysisReport:
        df = self._load_fundamentals_data(ticker)

        if df.empty:
            raise ValueError(f"Fundamentals dataset for {ticker} is empty.")

        row = df.iloc[-1]
        company_name = str(row.get("company_name", ticker)).strip()
        currency = str(
            row.get("currency", "USD" if ticker == "INFY" else "INR")
        ).strip()
        filing_standard = str(
            row.get(
                "filing_standard", "sec-form-20f" if ticker == "INFY" else "mca-ind-as"
            )
        ).strip()
        fiscal_period_end = str(row.get("fiscal_period_end", "2026-03-31"))[:10]

        revenue = float(row.get("revenue", 0.0))
        net_income = float(row.get("net_income", 0.0))
        total_assets = float(row.get("total_assets", 0.0))
        total_liabilities = float(row.get("total_liabilities", 0.0))
        operating_cash_flow = float(row.get("operating_cash_flow", 0.0))

        debt_to_equity = (
            float(row["debt_to_equity"])
            if "debt_to_equity" in row and pd.notna(row["debt_to_equity"])
            else None
        )
        profit_margins = (
            float(row["profit_margins"])
            if "profit_margins" in row and pd.notna(row["profit_margins"])
            else (round(net_income / revenue, 4) if revenue > 0 else None)
        )

        # Assess solvency health (banking institutions have deposit leverage, so evaluate equity buffer)
        is_banking = ticker in ["HDFCBANK", "ICICIBANK"]
        net_worth = total_assets - total_liabilities

        if net_worth > 0 and (profit_margins and profit_margins > 0.08):
            solvency_health = "ROBUST"
        elif net_worth > 0:
            solvency_health = "MODERATE"
        else:
            solvency_health = "CONSTRAINED"

        # Valuation posture
        if (
            profit_margins
            and profit_margins > 0.15
            and (debt_to_equity is None or debt_to_equity < 1.5 or is_banking)
        ):
            valuation_posture = ValuationPosture.UNDERVALUED
        elif profit_margins and profit_margins > 0.05:
            valuation_posture = ValuationPosture.FAIR_VALUE
        else:
            valuation_posture = ValuationPosture.OVERVALUED

        fallback_report = FundamentalsAnalysisReport(
            ticker=ticker,
            company_name=company_name,
            reporting_currency=currency,
            filing_standard=filing_standard,
            fiscal_period_end=fiscal_period_end,
            revenue=revenue,
            net_income=net_income,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            operating_cash_flow=operating_cash_flow,
            debt_to_equity=round(debt_to_equity, 4)
            if debt_to_equity is not None
            else None,
            profit_margins=round(profit_margins, 4)
            if profit_margins is not None
            else None,
            valuation_posture=valuation_posture,
            solvency_health=solvency_health,
            execution_mode="DETERMINISTIC_FALLBACK",
        )

        from kairos.observability.prompt_guard import guard_untrusted_text
        guard_untrusted_text(company_name + " " + filing_standard + " " + currency, "fundamentals_analyst", self.callback_manager, trace_id or "")
        prompt = render_task(
            "fundamentals_analysis",
            company_name=company_name,
            ticker=ticker,
            filing_standard=filing_standard,
            revenue=revenue,
            currency=currency,
            net_income=net_income,
            margin_percentage=profit_margins * 100 if profit_margins else 0,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            debt_to_equity=debt_to_equity,
            operating_cash_flow=operating_cash_flow,
            solvency_health=solvency_health,
        )["description"]
        prompt += self.supplementary_context(ticker, ["company_documents", "disclosure"], trace_id or "")

        return self.invoke_gemini_analysis(
            prompt, FundamentalsAnalysisReport, fallback_report
        )
