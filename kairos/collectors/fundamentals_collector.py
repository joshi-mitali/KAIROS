"""Collector for Indian company financial fundamentals via existing MCP servers."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kairos.config.settings import get_settings
from kairos.mcp_client.adapters import YFinanceMCPAdapter
from kairos.processors.clean_fundamentals import CleanFundamentalsProcessor
from kairos.schemas.fundamentals import CompanyFact, FundamentalsPayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger
from kairos.utils.security import validate_ticker

logger = get_logger("kairos.collectors.fundamentals_collector")


class FundamentalsCollector:
    """Collects balance sheet, income statement, and cash flow facts for Indian equities via MCP."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.settings = get_settings()
        self.file_store = file_store or FileStore()
        self.yf_adapter = YFinanceMCPAdapter()
        self.clean_processor = CleanFundamentalsProcessor(file_store=self.file_store)

    def fetch_fundamentals(self, symbol: str) -> FundamentalsPayload:
        """Gathers audited financial statements for an Indian company in INR."""
        clean_symbol = validate_ticker(symbol).replace(".NS", "").replace(".BO", "")
        formatted_sym = f"{clean_symbol}.NS"
        logger.info(f"Gathering financial statements for {formatted_sym} via yfinance-mcp-server")

        raw_resp = self.yf_adapter.get_financial_statement(formatted_sym, statement="income", quarterly=False)
        self.file_store.save_raw("fundamentals", f"{clean_symbol.lower()}_fundamentals.json", raw_resp)

        financials = raw_resp.get("financials", {})
        currency = raw_resp.get("currency", "INR")
        retrieval_ts = datetime.now(timezone.utc).isoformat()

        revenue_val = float(financials.get("TotalRevenue", 0.0))
        net_income_val = float(financials.get("NetIncome", 0.0))
        assets_val = float(financials.get("TotalAssets", 0.0))
        liab_val = float(financials.get("TotalLiabilities", 0.0))
        ocf_val = float(financials.get("OperatingCashFlow", 0.0))

        facts: List[CompanyFact] = []
        fact_mappings = [
            ("TotalRevenue", revenue_val),
            ("NetIncome", net_income_val),
            ("TotalAssets", assets_val),
            ("TotalLiabilities", liab_val),
            ("OperatingCashFlow", ocf_val),
        ]

        for tag, val in fact_mappings:
            if val > 0:
                facts.append(
                    CompanyFact(
                        fact_name=tag,
                        taxonomy="mca-ind-as",
                        value=val,
                        unit=currency,
                        fiscal_year=datetime.now().year - 1,
                        fiscal_period="FY",
                    )
                )

        debt_to_equity = None
        if assets_val > liab_val and (assets_val - liab_val) > 0:
            equity = assets_val - liab_val
            debt_to_equity = round(liab_val / equity, 4)

        profit_margin = None
        if revenue_val > 0:
            profit_margin = round(net_income_val / revenue_val, 4)

        payload = FundamentalsPayload(
            ticker=clean_symbol,
            company_name=f"{clean_symbol} INDIA LTD",
            revenue=revenue_val if revenue_val > 0 else None,
            net_income=net_income_val if net_income_val > 0 else None,
            total_assets=assets_val if assets_val > 0 else None,
            total_liabilities=liab_val if liab_val > 0 else None,
            operating_cash_flow=ocf_val if ocf_val > 0 else None,
            debt_to_equity=debt_to_equity,
            profit_margins=profit_margin,
            facts=facts,
            retrieval_timestamp=retrieval_ts,
            source="yfinance_mcp",
            is_live_data=True,
        )

        self.clean_processor.process_and_export(payload)
        return payload
