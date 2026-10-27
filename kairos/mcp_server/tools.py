"""Model Context Protocol (MCP) tool implementations for KAIROS market data."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from kairos.collectors.fundamentals_collector import FundamentalsCollector
from kairos.collectors.market_collector import MarketCollector
from kairos.collectors.news_collector import NewsCollector
from kairos.collectors.reddit_collector import RedditCollector
from kairos.config.settings import get_settings
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger
from kairos.utils.security import sanitize_untrusted_text, validate_ticker

logger = get_logger("kairos.mcp_server.tools")


# Pydantic Tool Input Schemas
class HistoricalPricesInput(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol (e.g. NVDA, AAPL, MSFT)")
    start_date: Optional[str] = Field(default=None, description="Start date in YYYY-MM-DD format")
    end_date: Optional[str] = Field(default=None, description="End date in YYYY-MM-DD format")
    limit: int = Field(default=30, ge=1, le=252, description="Maximum number of daily bars to return")


class FinancialNewsInput(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol (e.g. NVDA, AAPL)")
    query: Optional[str] = Field(default=None, description="Keywords to filter articles")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of articles to return")


class CompanyFundamentalsInput(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol (e.g. NVDA, MSFT)")


class DatasetStatusInput(BaseModel):
    source: Optional[str] = Field(default=None, description="Domain source name (market, news, reddit, fundamentals)")


class RedditSentimentInput(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol (e.g. NVDA, AAPL)")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum posts to return")


class MCPToolRegistry:
    """Registry executing read-only institutional data tools for MCP agents."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.file_store = file_store or FileStore()
        self.market_collector = MarketCollector(file_store=self.file_store)
        self.news_collector = NewsCollector(file_store=self.file_store)
        self.reddit_collector = RedditCollector(file_store=self.file_store)
        self.fundamentals_collector = FundamentalsCollector(file_store=self.file_store)

    def get_historical_prices(self, ticker: str, start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 30) -> Dict[str, Any]:
        """Tool: Fetches validated historical OHLCV market bars and moving averages."""
        try:
            clean_ticker = validate_ticker(ticker)
            payload = self.market_collector.fetch_ticker_data(clean_ticker)
            bars = payload.bars[-limit:]

            records = [
                {
                    "timestamp": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in bars
            ]

            return {
                "status": "success",
                "ticker": clean_ticker,
                "source": "yahoo_finance",
                "is_live_data": payload.is_live_data,
                "date_coverage": {
                    "start": bars[0].timestamp if bars else None,
                    "end": bars[-1].timestamp if bars else None,
                },
                "record_count": len(records),
                "indicators": {
                    "sma_20": payload.sma_20,
                    "rsi_14": payload.rsi_14,
                    "macd": payload.macd,
                },
                "records": records,
            }
        except Exception as e:
            logger.error(f"Error in get_historical_prices: {e}")
            return {
                "status": "error",
                "ticker": ticker,
                "error_message": sanitize_untrusted_text(str(e)),
                "records": [],
            }

    def search_financial_news(self, ticker: str, query: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """Tool: Searches financial news headlines and metadata for a ticker."""
        try:
            clean_ticker = validate_ticker(ticker)
            payload = self.news_collector.fetch_ticker_news(clean_ticker, query=query, max_records=limit)
            articles = [
                {
                    "article_id": a.article_id,
                    "headline": a.headline,
                    "summary": a.summary,
                    "source": a.source,
                    "url": a.url,
                    "published_at": str(a.datetime),
                }
                for a in payload.articles[:limit]
            ]

            return {
                "status": "success",
                "ticker": clean_ticker,
                "provider": payload.provider,
                "is_live_data": payload.is_live_data,
                "record_count": len(articles),
                "articles": articles,
            }
        except Exception as e:
            logger.error(f"Error in search_financial_news: {e}")
            return {
                "status": "error",
                "ticker": ticker,
                "error_message": sanitize_untrusted_text(str(e)),
                "articles": [],
            }

    def get_company_fundamentals(self, ticker: str) -> Dict[str, Any]:
        """Tool: Retrieves authoritative SEC EDGAR corporate facts and balance sheet ratios."""
        try:
            clean_ticker = validate_ticker(ticker)
            payload = self.fundamentals_collector.fetch_fundamentals(clean_ticker)

            return {
                "status": "success",
                "ticker": clean_ticker,
                "cik": payload.cik,
                "company_name": payload.company_name,
                "source": payload.source,
                "is_live_data": payload.is_live_data,
                "ratios": {
                    "market_cap": payload.market_cap,
                    "pe_ratio": payload.pe_ratio,
                    "forward_pe": payload.forward_pe,
                    "debt_to_equity": payload.debt_to_equity,
                    "profit_margins": payload.profit_margins,
                },
                "key_metrics": {
                    "revenue": payload.revenue,
                    "net_income": payload.net_income,
                    "total_assets": payload.total_assets,
                    "total_liabilities": payload.total_liabilities,
                    "operating_cash_flow": payload.operating_cash_flow,
                },
                "fact_count": len(payload.facts),
            }
        except Exception as e:
            logger.error(f"Error in get_company_fundamentals: {e}")
            return {
                "status": "error",
                "ticker": ticker,
                "error_message": sanitize_untrusted_text(str(e)),
            }

    def get_reddit_sentiment(self, ticker: str, limit: int = 10) -> Dict[str, Any]:
        """Tool: Gathers discussion posts and community sentiment metrics."""
        try:
            clean_ticker = validate_ticker(ticker)
            payload = self.reddit_collector.fetch_community_sentiment(clean_ticker, limit_per_sub=limit)
            posts = [
                {
                    "post_id": p.id,
                    "subreddit": p.subreddit,
                    "title": p.title,
                    "snippet": p.snippet,
                    "score": p.score,
                    "num_comments": p.num_comments,
                    "permalink": p.permalink,
                    "is_synthetic": p.is_synthetic,
                    "source_status": p.source_status,
                }
                for p in payload.posts[:limit]
            ]

            return {
                "status": "success",
                "ticker": clean_ticker,
                "permission_status": payload.permission_status,
                "is_live_data": payload.is_live_data,
                "record_count": len(posts),
                "posts": posts,
            }
        except Exception as e:
            logger.error(f"Error in get_reddit_sentiment: {e}")
            return {
                "status": "error",
                "ticker": ticker,
                "error_message": sanitize_untrusted_text(str(e)),
                "posts": [],
            }

    def get_dataset_status(self, source: Optional[str] = None) -> Dict[str, Any]:
        """Tool: Reports inventory of stored raw and processed datasets."""
        try:
            settings = get_settings()
            domains = [source] if source else ["market", "reddit", "news", "fundamentals"]
            inventory: Dict[str, Any] = {}

            for dom in domains:
                raw_path = settings.raw_data_dir / dom
                proc_path = settings.processed_data_dir / dom
                raw_files = [f.name for f in raw_path.glob("*.json")] if raw_path.exists() else []
                proc_csv = [f.name for f in proc_path.glob("*.csv")] if proc_path.exists() else []
                proc_parquet = [f.name for f in proc_path.glob("*.parquet")] if proc_path.exists() else []

                inventory[dom] = {
                    "raw_files": raw_files,
                    "processed_csv_files": proc_csv,
                    "processed_parquet_files": proc_parquet,
                    "raw_count": len(raw_files),
                    "processed_count": len(proc_csv),
                }

            manifests = [f.name for f in settings.manifests_dir.glob("*.json")]
            reports = [f.name for f in settings.reports_dir.glob("*.json")]

            return {
                "status": "success",
                "domains": inventory,
                "manifest_count": len(manifests),
                "report_count": len(reports),
            }
        except Exception as e:
            return {"status": "error", "error_message": str(e)}
