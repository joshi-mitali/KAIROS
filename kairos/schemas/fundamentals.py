"""Company fundamentals Pydantic v2 validation models."""

from typing import List, Optional
from pydantic import BaseModel, Field


class CompanyFact(BaseModel):
    """Detailed US-GAAP / SEC financial metric fact."""

    fact_name: str = Field(..., description="Fact identifier e.g. Revenues, Assets")
    taxonomy: str = Field(default="us-gaap", description="Taxonomy standard e.g. us-gaap, dei")
    value: float = Field(..., description="Reported numeric value")
    unit: str = Field(default="USD", description="Reporting unit e.g. USD, shares")
    fiscal_year: Optional[int] = Field(default=None, description="Fiscal year")
    fiscal_period: Optional[str] = Field(default=None, description="Fiscal period e.g. FY, Q1, Q2, Q3")
    filing_date: Optional[str] = Field(default=None, description="Official filing date YYYY-MM-DD")
    accession_number: Optional[str] = Field(default=None, description="SEC accession number")


class FundamentalsPayload(BaseModel):
    """Payload encapsulating audited corporate balance sheet and income statement metrics."""

    ticker: str = Field(..., description="Stock ticker symbol")
    cik: Optional[str] = Field(default=None, description="SEC Central Index Key (10-digit padded)")
    company_name: Optional[str] = Field(default=None, description="Official registrant name")
    market_cap: Optional[int] = Field(default=None, ge=0, description="Market Capitalization in USD")
    pe_ratio: Optional[float] = Field(default=None, description="Trailing P/E ratio")
    forward_pe: Optional[float] = Field(default=None, description="Forward P/E ratio")
    debt_to_equity: Optional[float] = Field(default=None, description="Debt to Equity ratio")
    profit_margins: Optional[float] = Field(default=None, description="Profit margin ratio (0.0 to 1.0)")
    revenue: Optional[float] = Field(default=None, description="Most recent annual or TTM revenue")
    net_income: Optional[float] = Field(default=None, description="Most recent net income")
    total_assets: Optional[float] = Field(default=None, description="Total corporate assets")
    total_liabilities: Optional[float] = Field(default=None, description="Total corporate liabilities")
    operating_cash_flow: Optional[float] = Field(default=None, description="Cash flow from operations")
    facts: List[CompanyFact] = Field(default_factory=list, description="Raw audited XBRL facts from SEC EDGAR")
    retrieval_timestamp: Optional[str] = Field(default=None, description="ISO timestamp when retrieved")
    source: Optional[str] = Field(default="SEC-EDGAR", description="Authoritative data source")
    is_live_data: bool = Field(default=True, description="True if retrieved from live regulatory or API endpoint")

