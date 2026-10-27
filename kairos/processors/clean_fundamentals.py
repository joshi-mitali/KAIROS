"""Fundamentals processing, XBRL fact standardization, and clean export."""

from typing import Any, Dict, List, Optional

from kairos.schemas.fundamentals import FundamentalsPayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.processors.clean_fundamentals")


class CleanFundamentalsProcessor:
    """Standardizes corporate balance sheet and income statement metrics."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.file_store = file_store or FileStore()

    def process_and_export(self, payload: FundamentalsPayload) -> Dict[str, Any]:
        """Separates XBRL facts into structured records and exports clean CSV and Parquet."""
        ticker = payload.ticker.upper()
        facts = payload.facts

        clean_fact_records: List[Dict[str, Any]] = []
        for fact in facts:
            clean_fact_records.append({
                "ticker": ticker,
                "cik": payload.cik,
                "company_name": payload.company_name,
                "fact_name": fact.fact_name,
                "taxonomy": fact.taxonomy,
                "value": fact.value,
                "unit": fact.unit,
                "fiscal_year": fact.fiscal_year,
                "fiscal_period": fact.fiscal_period,
                "filing_date": fact.filing_date,
                "accession_number": fact.accession_number,
                "source": payload.source,
                "retrieval_timestamp": payload.retrieval_timestamp,
            })

        # Summary ratios record
        summary_record = [{
            "ticker": ticker,
            "cik": payload.cik,
            "company_name": payload.company_name,
            "market_cap": payload.market_cap,
            "pe_ratio": payload.pe_ratio,
            "forward_pe": payload.forward_pe,
            "debt_to_equity": payload.debt_to_equity,
            "profit_margins": payload.profit_margins,
            "revenue": payload.revenue,
            "net_income": payload.net_income,
            "total_assets": payload.total_assets,
            "total_liabilities": payload.total_liabilities,
            "operating_cash_flow": payload.operating_cash_flow,
            "source": payload.source,
            "retrieval_timestamp": payload.retrieval_timestamp,
        }]

        # Export facts table
        facts_csv = self.file_store.export_csv("fundamentals", f"{ticker.lower()}_facts_clean.csv", clean_fact_records)
        facts_parquet = self.file_store.export_parquet("fundamentals", f"{ticker.lower()}_facts_clean.parquet", clean_fact_records)

        # Export summary table
        summary_csv = self.file_store.export_csv("fundamentals", f"{ticker.lower()}_summary_clean.csv", summary_record)
        summary_parquet = self.file_store.export_parquet("fundamentals", f"{ticker.lower()}_summary_clean.parquet", summary_record)

        return {
            "ticker": ticker,
            "total_facts": len(facts),
            "facts_csv_path": str(facts_csv),
            "facts_parquet_path": str(facts_parquet),
            "summary_csv_path": str(summary_csv),
            "summary_parquet_path": str(summary_parquet),
            "facts_records": clean_fact_records,
            "summary_record": summary_record[0],
        }

