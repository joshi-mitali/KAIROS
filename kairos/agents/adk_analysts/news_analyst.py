"""Google ADK News Analyst Agent for KAIROS.
Consumes verified financial media articles to evaluate catalysts and regulatory risks.
"""

from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone
import pandas as pd

from kairos.a2a.contract import A2AMessageType
from kairos.agents.adk_analysts.base_analyst import BaseADKAnalyst
from kairos.schemas.analyst_reports import (
    NewsAnalysisReport,
    TrendDirection,
    VerifiedNewsItem,
)
from kairos.config.agent_definitions import render_task
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.adk_analysts.news")


class NewsAnalyst(BaseADKAnalyst):
    """Specialist Analyst auditing financial news, corporate developments, and regulatory exposure."""

    agent_name: str = "google_adk.news_analyst"
    config_key: str = "news_analyst"
    task_message_type: A2AMessageType = A2AMessageType.NEWS_REPORT
    output_schema = NewsAnalysisReport

    def _load_news_data(self, ticker: str) -> pd.DataFrame:
        news_dir = self.data_dir / "processed" / "news"
        pq_path = news_dir / f"{ticker.lower()}_news_clean.parquet"
        csv_path = news_dir / f"{ticker.lower()}_news_clean.csv"

        if pq_path.exists():
            return pd.read_parquet(pq_path)
        elif csv_path.exists():
            return pd.read_csv(csv_path)
        else:
            raise FileNotFoundError(f"No news dataset found for {ticker} in {news_dir}")

    def run_analysis(
        self, ticker: str, trace_id: Optional[str] = None
    ) -> NewsAnalysisReport:
        df = self._load_news_data(ticker)

        if df.empty:
            raise ValueError(f"News dataset for {ticker} is empty.")

        verified_articles: List[VerifiedNewsItem] = []
        catalysts: List[str] = []
        risks: List[str] = []

        catalyst_keywords = [
            "growth",
            "deal",
            "fundraising",
            "earnings",
            "profit",
            "results",
            "expansion",
            "contract",
            "record",
            "dividend",
        ]
        risk_keywords = [
            "probe",
            "investigation",
            "penalty",
            "tax",
            "litigation",
            "regulatory",
            "weakness",
            "uncertainty",
            "fall",
            "decline",
            "sebi",
            "rbi",
        ]

        for _, row in df.iterrows():
            headline = str(row.get("headline", "")).strip()
            summary = str(row.get("summary", "")).strip()
            source = str(row.get("source", "Financial Media")).strip()
            url = str(row.get("url", "")).strip()
            published_at = str(
                row.get("datetime", str(row.get("retrieved_at", datetime.now(timezone.utc).isoformat())))
            ).strip()

            item = VerifiedNewsItem(
                headline=headline,
                summary=summary,
                source=source,
                url=url,
                published_at=published_at,
            )
            verified_articles.append(item)

            combined_text = f"{headline} {summary}".lower()
            for kw in catalyst_keywords:
                if kw in combined_text and len(catalysts) < 4:
                    cat_desc = f"Identified growth catalyst: {headline[:80]}..."
                    if cat_desc not in catalysts:
                        catalysts.append(cat_desc)
                    break

            for rk in risk_keywords:
                if rk in combined_text and len(risks) < 4:
                    risk_desc = f"Identified regulatory/market risk: {headline[:80]}..."
                    if risk_desc not in risks:
                        risks.append(risk_desc)
                    break

        if not catalysts:
            catalysts = [
                f"Steady institutional holding and operational stability for {ticker}"
            ]
        if not risks:
            risks = [
                "Macroeconomic interest rate sensitivity and broad market multiple compression"
            ]

        # Determine news sentiment
        if len(catalysts) > len(risks):
            news_sentiment = TrendDirection.BULLISH
        elif len(risks) > len(catalysts):
            news_sentiment = TrendDirection.BEARISH
        else:
            news_sentiment = TrendDirection.NEUTRAL

        fallback_report = NewsAnalysisReport(
            ticker=ticker,
            news_sentiment=news_sentiment,
            total_articles_verified=len(verified_articles),
            key_catalysts=catalysts,
            regulatory_and_litigation_risks=risks,
            top_verified_articles=verified_articles[:5],
            execution_mode="DETERMINISTIC_FALLBACK",
        )

        headlines_text = "\n".join(
            f"  * {a.headline[:55]} ({a.source})" for a in verified_articles[:2]
        )
        from kairos.observability.prompt_guard import guard_untrusted_text
        guard_untrusted_text(headlines_text + "\n" + str(catalysts[:2]) + "\n" + str(risks[:2]), "news_analyst", self.callback_manager, trace_id or "")
        prompt = render_task(
            "news_analysis",
            ticker=ticker,
            article_count=len(verified_articles),
            headlines_text=headlines_text,
            top_catalysts=catalysts[:2],
            top_risks=risks[:2],
        )["description"]
        prompt += self.supplementary_context(
            ticker, ["disclosure", "regulatory", "news_discovery", "market_reference"], trace_id or "")

        return self.invoke_gemini_analysis(prompt, NewsAnalysisReport, fallback_report)
