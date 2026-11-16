"""Google ADK Sentiment Analyst Agent for KAIROS.
Consumes classified Reddit posts from r/IndianStockMarket to evaluate retail sentiment.
"""

import json
from pathlib import Path
from typing import List, Optional
import pandas as pd

from kairos.a2a.contract import A2AMessageType
from kairos.agents.adk_analysts.base_analyst import BaseADKAnalyst
from kairos.schemas.analyst_reports import SentimentAnalysisReport, TrendDirection
from kairos.config.agent_definitions import render_task
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.adk_analysts.sentiment")


class SentimentAnalyst(BaseADKAnalyst):
    """Specialist Analyst evaluating social chatter, retail sentiment distribution, and emerging themes."""

    agent_name: str = "google_adk.sentiment_analyst"
    config_key: str = "sentiment_analyst"
    task_message_type: A2AMessageType = A2AMessageType.SENTIMENT_REPORT
    output_schema = SentimentAnalysisReport

    def _load_sentiment_data(self, ticker: str) -> pd.DataFrame:
        reddit_dir = self.data_dir / "processed" / "reddit"
        pq_path = reddit_dir / f"{ticker.lower()}_sentiment_clean.parquet"
        csv_path = reddit_dir / f"{ticker.lower()}_sentiment_clean.csv"

        if pq_path.exists():
            return pd.read_parquet(pq_path)
        elif csv_path.exists():
            return pd.read_csv(csv_path)
        else:
            raise FileNotFoundError(
                f"No sentiment dataset found for {ticker} in {reddit_dir}"
            )

    def run_analysis(
        self, ticker: str, trace_id: Optional[str] = None
    ) -> SentimentAnalysisReport:
        provenance = self.data_dir / "provenance.json"
        if provenance.exists() and json.loads(provenance.read_text()).get("sources", {}).get("sentiment", {}).get("status") == "UNAVAILABLE":
            # Reddit could not be reached: say sentiment was not assessed, never present it as neutral.
            return SentimentAnalysisReport(
                ticker=ticker,
                overall_sentiment=TrendDirection.NEUTRAL,
                sentiment_score=0.0,
                sample_size_posts=0,
                ticker_specific_posts_count=0,
                macro_context_posts_count=0,
                retail_bull_ratio=0.5,
                community_source="Reddit (unreachable; sentiment NOT assessed)",
                key_themes=["Sentiment not assessed: Reddit was unreachable. This is missing evidence, not a neutral reading."],
                execution_mode="DETERMINISTIC_FALLBACK",
                data_source="SOURCE_UNAVAILABLE",
            )

        df = self._load_sentiment_data(ticker)

        if df.empty:
            # Reddit was reachable but had no stock-specific posts this week: say so, invent nothing.
            return SentimentAnalysisReport(
                ticker=ticker,
                overall_sentiment=TrendDirection.NEUTRAL,
                sentiment_score=0.0,
                sample_size_posts=0,
                ticker_specific_posts_count=0,
                macro_context_posts_count=0,
                retail_bull_ratio=0.5,
                community_source="Reddit (live feeds reached; no posts about this stock in the last 7 days)",
                key_themes=["No recent retail discussion found; insufficient evidence, sentiment treated as neutral with low confidence"],
                execution_mode="DETERMINISTIC_FALLBACK",
                data_source="NO_RECENT_DISCUSSION",
            )

        total_posts = len(df)
        ticker_col = (
            "relevance_level" if "relevance_level" in df.columns else "market_category"
        )
        if ticker_col in df.columns:
            ticker_posts = df[df[ticker_col] == "TICKER_SPECIFIC"]
            ticker_count = len(ticker_posts)
        else:
            ticker_count = total_posts

        macro_count = max(0, total_posts - ticker_count)

        # Detect source provenance (live json vs live rss/atom vs curated fallback)
        live_json_count = 0
        live_atom_count = 0
        fallback_count = 0
        if "source_status" in df.columns:
            live_json_count = int((df["source_status"] == "LIVE_REDDIT_JSON").sum())
            live_atom_count = int(
                (df["source_status"] == "LIVE_REDDIT_ATOM_FEED").sum()
            )
            fallback_count = int((df["source_status"] == "CURATED_FALLBACK").sum())

        total_live = live_json_count + live_atom_count
        if total_live == 0 and fallback_count == 0:
            fallback_count = total_posts

        if live_json_count > 0 and live_atom_count == 0 and fallback_count == 0:
            data_source = "LIVE_REDDIT_JSON"
            source_desc = (
                f"r/IndianStockMarket (LIVE_REDDIT_JSON, {live_json_count} live posts)"
            )
        elif live_atom_count > 0 and live_json_count == 0 and fallback_count == 0:
            data_source = "LIVE_REDDIT_ATOM_FEED"
            source_desc = f"r/IndianStockMarket (LIVE_REDDIT_ATOM_FEED, {live_atom_count} live syndication posts)"
        elif total_live > 0 and fallback_count == 0:
            data_source = "LIVE_REDDIT_MULTI"
            source_desc = f"r/IndianStockMarket (LIVE_REDDIT: {live_json_count} JSON, {live_atom_count} RSS)"
        elif total_live > 0 and fallback_count > 0:
            data_source = "HYBRID"
            source_desc = f"r/IndianStockMarket (HYBRID: {total_live} live, {fallback_count} fallback)"
        else:
            data_source = "CURATED_FALLBACK"
            source_desc = f"r/IndianStockMarket (CURATED_FALLBACK, {total_posts} posts)"

        # Calculate sentiment score
        if "sentiment_score" in df.columns:
            avg_score = float(df["sentiment_score"].mean())
        else:
            avg_score = 0.0

        avg_score = max(-1.0, min(1.0, avg_score))

        # Calculate retail bull ratio
        if "sentiment_label" in df.columns:
            pos_count = (df["sentiment_label"] == "POSITIVE").sum()
            neg_count = (df["sentiment_label"] == "NEGATIVE").sum()
            neutral_count = (df["sentiment_label"] == "NEUTRAL").sum()
            directional = pos_count + neg_count
            bull_ratio = float(pos_count / directional) if directional > 0 else 0.5
        else:
            bull_ratio = 0.5

        # Determine consensus sentiment
        if avg_score > 0.05 or bull_ratio > 0.60:
            overall_sentiment = TrendDirection.BULLISH
        elif avg_score < -0.05 or bull_ratio < 0.40:
            overall_sentiment = TrendDirection.BEARISH
        else:
            overall_sentiment = TrendDirection.NEUTRAL

        # Extract key themes from titles
        key_themes = []
        if "title" in df.columns:
            titles = df["title"].dropna().tolist()
            for t in titles[:5]:
                clean_title = t.strip()
                if clean_title and clean_title not in key_themes:
                    key_themes.append(clean_title[:100])

        if not key_themes:
            key_themes = [
                f"Retail investor discussion on {ticker} positioning and outlook"
            ]

        fallback_report = SentimentAnalysisReport(
            ticker=ticker,
            overall_sentiment=overall_sentiment,
            sentiment_score=round(avg_score, 4),
            sample_size_posts=total_posts,
            ticker_specific_posts_count=ticker_count,
            macro_context_posts_count=macro_count,
            retail_bull_ratio=round(bull_ratio, 4),
            community_source=source_desc,
            key_themes=key_themes,
            noise_filter_applied=True,
            execution_mode="DETERMINISTIC_FALLBACK",
            data_source=data_source,
            live_posts_count=total_live,
            fallback_posts_count=fallback_count,
        )

        sample_titles = [t[:50] for t in key_themes[:2]]
        from kairos.observability.prompt_guard import guard_untrusted_text
        guard_untrusted_text("\n".join(sample_titles), "sentiment_analyst", self.callback_manager, trace_id or "")
        prompt = render_task(
            "sentiment_analysis",
            ticker=ticker,
            data_source=data_source,
            total_live=total_live,
            fallback_count=fallback_count,
            total_posts=total_posts,
            bull_percentage=bull_ratio * 100,
            avg_score=avg_score,
            sample_titles=sample_titles,
        )["description"]

        report = self.invoke_gemini_analysis(
            prompt, SentimentAnalysisReport, fallback_report
        )
        if hasattr(report, "data_source"):
            report.data_source = data_source
        if hasattr(report, "live_posts_count"):
            report.live_posts_count = total_live
        if hasattr(report, "fallback_posts_count"):
            report.fallback_posts_count = fallback_count
        if (
            hasattr(report, "community_source")
            and data_source not in report.community_source
        ):
            report.community_source = source_desc
        return report
