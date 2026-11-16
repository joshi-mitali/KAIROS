"""Pydantic v2 schemas for KAIROS Phase 2 Analyst and Research Reports."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class TrendDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class SignalStrength(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


class ValuationPosture(str, Enum):
    UNDERVALUED = "UNDERVALUED"
    FAIR_VALUE = "FAIR_VALUE"
    OVERVALUED = "OVERVALUED"


class RecommendationVerdict(str, Enum):
    OVERWEIGHT = "OVERWEIGHT"      # Buy / Accumulate
    NEUTRAL = "NEUTRAL"            # Hold
    UNDERWEIGHT = "UNDERWEIGHT"    # Sell / Reduce


# ---------------------------------------------------------------------------
# 1. Market Analyst Report Schema
# ---------------------------------------------------------------------------

class TechnicalIndicatorsSnapshot(BaseModel):
    sma_20: float = Field(..., description="20-day Simple Moving Average")
    rsi_14: float = Field(..., ge=0.0, le=100.0, description="14-day Relative Strength Index")
    macd_line: float = Field(..., description="MACD Line (12, 26)")
    macd_signal: float = Field(..., description="Signal Line (9)")
    macd_histogram: float = Field(..., description="MACD Histogram")


class MarketAnalysisReport(BaseModel):
    """Structured report produced by the Google ADK Market Analyst."""

    ticker: str = Field(..., description="NSE Stock Symbol (e.g. RELIANCE)")
    as_of_date: str = Field(..., description="Latest analysis trading date (YYYY-MM-DD)")
    last_price: float = Field(..., ge=0.0, description="Last traded price in INR")
    quote_delay: str = Field(default="15_MIN_DELAYED", description="Quote latency classification")
    indicators: TechnicalIndicatorsSnapshot = Field(..., description="Calculated technical indicators")
    trend_direction: TrendDirection = Field(..., description="Identified price trend")
    signal_strength: SignalStrength = Field(..., description="Confidence of technical setup")
    support_level: float = Field(..., ge=0.0, description="Nearest key support level in INR")
    resistance_level: float = Field(..., ge=0.0, description="Nearest key resistance level in INR")
    fifty_two_week_high: Optional[float] = Field(default=None, description="52-week high in INR")
    fifty_two_week_low: Optional[float] = Field(default=None, description="52-week low in INR")
    bars_analyzed: int = Field(default=2471, ge=100, description="Number of daily bars evaluated")
    key_observations: List[str] = Field(default_factory=list, description="Key technical findings")
    analyst_name: str = Field(default="google_adk.market_analyst")
    execution_mode: str = Field(default="DETERMINISTIC_FALLBACK", description="'LIVE_GEMINI_MODEL' or 'DETERMINISTIC_FALLBACK'")
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# 2. Sentiment Analyst Report Schema
# ---------------------------------------------------------------------------

class SentimentAnalysisReport(BaseModel):
    """Structured report produced by the Google ADK Sentiment Analyst."""

    ticker: str = Field(..., description="Target ticker symbol")
    overall_sentiment: TrendDirection = Field(..., description="Consensus retail sentiment")
    sentiment_score: float = Field(..., ge=-1.0, le=1.0, description="Mean sentiment score (-1.0 to +1.0)")
    sample_size_posts: int = Field(..., ge=0, description="Total Reddit posts evaluated")
    ticker_specific_posts_count: int = Field(..., ge=0, description="Posts directly mentioning ticker")
    macro_context_posts_count: int = Field(..., ge=0, description="Broader market posts analyzed")
    retail_bull_ratio: float = Field(..., ge=0.0, le=1.0, description="Proportion of bullish mentions")
    community_source: str = Field(default="r/IndianStockMarket")
    key_themes: List[str] = Field(default_factory=list, description="Identified retail topics")
    noise_filter_applied: bool = Field(default=True, description="True if memes and off-topic posts filtered")
    analyst_name: str = Field(default="google_adk.sentiment_analyst")
    execution_mode: str = Field(default="DETERMINISTIC_FALLBACK", description="'LIVE_GEMINI_MODEL' or 'DETERMINISTIC_FALLBACK'")
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data_source: str = Field(default="CURATED_FALLBACK", description="'LIVE_REDDIT_JSON', 'CURATED_FALLBACK', 'HYBRID', 'NO_RECENT_DISCUSSION' or 'SOURCE_UNAVAILABLE'")
    live_posts_count: int = Field(default=0, description="Count of verified live Reddit JSON posts")
    fallback_posts_count: int = Field(default=0, description="Count of curated fallback posts used")


SENTIMENT_UNAVAILABLE_NOTE = (
    "UNAVAILABLE: Reddit was unreachable, so retail sentiment was NOT assessed. "
    "Do not treat this as neutral and do not infer any retail sentiment."
)


def sentiment_prompt_line(sentiment: Any) -> str:
    """One line for debate, manager and trader prompts; unavailable evidence is never shown as a neutral ratio."""
    data = sentiment.model_dump() if hasattr(sentiment, "model_dump") else (sentiment or {})
    if data.get("data_source") == "SOURCE_UNAVAILABLE":
        return SENTIMENT_UNAVAILABLE_NOTE
    if data.get("data_source") == "NO_RECENT_DISCUSSION":
        return "No recent Reddit discussion of this stock was found (0 posts): there is no sentiment evidence, so do not read it as neutral."
    return f"Bull Ratio {float(data.get('retail_bull_ratio', 0.5)):.2f}"


# ---------------------------------------------------------------------------
# 3. News Analyst Report Schema
# ---------------------------------------------------------------------------

class VerifiedNewsItem(BaseModel):
    headline: str = Field(..., description="Article headline")
    summary: str = Field(..., description="Extracted lead content summary")
    source: str = Field(..., description="Financial media publisher")
    url: str = Field(..., description="Verified article URL")
    published_at: str = Field(..., description="Publication date or timestamp")


class NewsAnalysisReport(BaseModel):
    """Structured report produced by the Google ADK News Analyst."""

    ticker: str = Field(..., description="Target ticker symbol")
    news_sentiment: TrendDirection = Field(..., description="Aggregate media reporting tone")
    total_articles_verified: int = Field(..., ge=1, description="Count of HTTP 200 verified articles")
    key_catalysts: List[str] = Field(default_factory=list, description="Positive growth/deal catalysts")
    regulatory_and_litigation_risks: List[str] = Field(default_factory=list, description="SEBI/legal/probe concerns")
    top_verified_articles: List[VerifiedNewsItem] = Field(default_factory=list, description="Top audited articles")
    analyst_name: str = Field(default="google_adk.news_analyst")
    execution_mode: str = Field(default="DETERMINISTIC_FALLBACK", description="'LIVE_GEMINI_MODEL' or 'DETERMINISTIC_FALLBACK'")
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# 4. Fundamentals Analyst Report Schema
# ---------------------------------------------------------------------------

class FundamentalsAnalysisReport(BaseModel):
    """Structured report produced by the Google ADK Fundamentals Analyst."""

    ticker: str = Field(..., description="Target ticker symbol")
    company_name: str = Field(..., description="Registered corporate entity name")
    reporting_currency: str = Field(..., description="USD or INR")
    filing_standard: str = Field(..., description="sec-form-20f or mca-ind-as")
    fiscal_period_end: str = Field(..., description="Fiscal year end date (e.g. 2026-03-31)")
    revenue: float = Field(..., ge=0.0, description="Annual total revenue")
    net_income: float = Field(..., description="Annual net income / profit after tax")
    total_assets: float = Field(..., ge=0.0, description="Consolidated total assets")
    total_liabilities: float = Field(..., ge=0.0, description="Total liabilities")
    operating_cash_flow: float = Field(..., description="Operating cash flow")
    debt_to_equity: Optional[float] = Field(default=None, description="Debt-to-Equity ratio")
    profit_margins: Optional[float] = Field(default=None, description="Net margin (Net Income / Revenue)")
    valuation_posture: ValuationPosture = Field(..., description="Valuation assessment")
    solvency_health: str = Field(..., description="Balance sheet solvency status (ROBUST/MODERATE/CONSTRAINED)")
    analyst_name: str = Field(default="google_adk.fundamentals_analyst")
    execution_mode: str = Field(default="DETERMINISTIC_FALLBACK", description="'LIVE_GEMINI_MODEL' or 'DETERMINISTIC_FALLBACK'")
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# 5. Research Debate & Synthesis Schemas (CrewAI)
# ---------------------------------------------------------------------------

class BullThesis(BaseModel):
    """Investment thesis constructed by CrewAI Bull Researcher."""

    ticker: str
    target_horizon_months: int = Field(default=12, ge=1)
    primary_arguments: List[str] = Field(..., min_length=1, description="Bullish growth drivers")
    upside_potential_pct: float = Field(..., ge=0.0, description="Projected upside %")
    catalysts: List[str] = Field(default_factory=list, description="Near-term positive catalysts")
    acknowledged_risks: List[str] = Field(default_factory=list, description="Downside risks acknowledged")
    conviction_level: SignalStrength = Field(default=SignalStrength.MODERATE)
    researcher_name: str = Field(default="crewai.bull_researcher")
    debate_round: int = Field(default=1, ge=1, description="Debate deliberation round number")
    execution_mode: str = Field(default="LIVE_CREWAI_LLM", description="'LIVE_CREWAI_LLM' or 'DETERMINISTIC_FALLBACK'")


class BearThesis(BaseModel):
    """Counter-thesis constructed by CrewAI Bear Researcher."""

    ticker: str
    primary_arguments: List[str] = Field(..., min_length=1, description="Bearish risk factors")
    downside_risk_pct: float = Field(..., le=0.0, description="Projected downside % (negative float)")
    vulnerabilities: List[str] = Field(default_factory=list, description="Key operational vulnerabilities")
    trigger_events: List[str] = Field(default_factory=list, description="Events that could cause sell-off")
    conviction_level: SignalStrength = Field(default=SignalStrength.MODERATE)
    researcher_name: str = Field(default="crewai.bear_researcher")
    debate_round: int = Field(default=1, ge=1, description="Debate deliberation round number")
    execution_mode: str = Field(default="LIVE_CREWAI_LLM", description="'LIVE_CREWAI_LLM' or 'DETERMINISTIC_FALLBACK'")


def data_freshness_label(market: dict) -> str:
    """Freshness text from the run's own market report (as-of bar date, quote delay); today's date if absent."""
    as_of = str(market.get("as_of_date") or datetime.now(timezone.utc).date().isoformat())[:10]
    return f"CURRENT_AS_OF_{as_of} ({market.get('quote_delay', '15_MIN_DELAYED_QUOTE')})"


class ResearchSynthesisVerdict(BaseModel):
    """Final investment research synthesis produced by CrewAI Research Manager."""

    ticker: str
    trace_id: str = Field(..., description="End-to-end W3C distributed trace ID")
    recommendation: RecommendationVerdict = Field(..., description="OVERWEIGHT, NEUTRAL, or UNDERWEIGHT")
    conviction: SignalStrength = Field(..., description="Manager conviction score")
    bull_summary: str = Field(..., description="Summary of Bull case")
    bear_summary: str = Field(..., description="Summary of Bear case")
    synthesis_rationale: str = Field(..., description="Comprehensive reasoning justifying recommendation")
    key_decision_factors: List[str] = Field(default_factory=list)
    manager_name: str = Field(default="crewai.research_manager")
    deliberation_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    generation_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data_freshness_status: str = Field(
        default_factory=lambda: data_freshness_label({}),
        description="Freshness state of underlying market, news, sentiment and filings data",
    )
    source_references: List[str] = Field(
        default_factory=list,
        description="Audited data provenance source citations",
    )
    limitations: List[str] = Field(
        default_factory=lambda: [
            "Delayed quotes (15-min latency) from Yahoo Finance MCP",
            "Retail sentiment bounded to r/IndianStockMarket community sampling",
            "Subject to broader macroeconomic interest rate and regulatory shifts",
        ],
        description="Operational caveats, scope boundaries, and statistical constraints",
    )
    research_only_disclaimer: str = Field(
        default="KAIROS Phase 2 Institutional Equity Research Report. Strictly research-only advisory; not financial advice. No automated order placement or real-money trading.",
        description="Institutional research-only non-execution compliance disclaimer",
    )
    debate_rounds: int = Field(
        default=2,
        ge=1,
        description="Total multi-round deliberation exchanges conducted between Bull and Bear researchers",
    )
    execution_mode: str = Field(
        default="LIVE_CREWAI_LLM",
        description="'LIVE_CREWAI_LLM' or 'DETERMINISTIC_FALLBACK'",
    )

