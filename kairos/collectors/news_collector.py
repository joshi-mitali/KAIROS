"""Collector for financial news associated with Indian equities via MCP servers."""

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kairos.config.settings import get_settings
from kairos.mcp_client.adapters import YFinanceMCPAdapter
from kairos.processors.clean_news import CleanNewsProcessor
from kairos.schemas.news import NewsArticle, NewsPayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger
from kairos.utils.security import validate_ticker

logger = get_logger("kairos.collectors.news_collector")


class NewsCollector:
    """Collects company-related headlines and article metadata for Indian stocks via MCP."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.settings = get_settings()
        self.file_store = file_store or FileStore()
        self.yf_adapter = YFinanceMCPAdapter()
        self.clean_processor = CleanNewsProcessor(file_store=self.file_store)

    def fetch_ticker_news(self, symbol: str, limit: int = 10) -> NewsPayload:
        """Gathers news articles for an Indian equity using the existing yfinance MCP server."""
        clean_symbol = validate_ticker(symbol).replace(".NS", "").replace(".BO", "")
        formatted_sym = f"{clean_symbol}.NS"
        logger.info(f"Gathering financial news for {formatted_sym} via yfinance-mcp-server")

        raw_resp = self.yf_adapter.get_news(formatted_sym)
        news_items = raw_resp.get("news", [])

        # Save raw JSON
        self.file_store.save_raw("news", f"{clean_symbol.lower()}_news.json", raw_resp)

        articles: List[NewsArticle] = []
        retrieval_ts = datetime.now(timezone.utc).isoformat()

        for item in news_items[:limit]:
            title = item.get("title", "")
            publisher = item.get("publisher", "Financial Media")
            link = item.get("link", f"https://finance.yahoo.com/quote/{formatted_sym}")
            pub_time = item.get("providerPublishTime", int(time.time()))

            pub_dt_str = datetime.fromtimestamp(pub_time, tz=timezone.utc).isoformat()
            content_hash = hashlib.sha256(f"{title}|{pub_dt_str}|{link}".encode("utf-8")).hexdigest()[:16]

            articles.append(
                NewsArticle(
                    article_id=content_hash,
                    ticker=clean_symbol,
                    headline=title,
                    summary=f"Market disclosure and news regarding {clean_symbol} published by {publisher}.",
                    source=publisher,
                    url=link,
                    datetime=pub_dt_str,
                    provider="yfinance_mcp",
                    retrieved_at=retrieval_ts,
                    language="en",
                )
            )

        payload = NewsPayload(
            ticker=clean_symbol,
            articles=articles,
            is_live_data=True,
            provider="yfinance_mcp",
        )

        self.clean_processor.process_and_export(payload)
        return payload
