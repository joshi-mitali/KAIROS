"""News processing, canonical URL deduplication, text sanitization, and export."""

import hashlib
from typing import Any, Dict, List, Optional

from kairos.schemas.news import NewsArticle, NewsPayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger
from kairos.utils.security import sanitize_untrusted_text

logger = get_logger("kairos.processors.clean_news")


def compute_article_hash(headline: str, published_at: str, url: str) -> str:
    """Generates a stable SHA-256 fingerprint for deduplication."""
    content = f"{headline.strip()}|{str(published_at).strip()}|{url.strip()}".lower()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class CleanNewsProcessor:
    """Normalizes and deduplicates news articles across providers."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.file_store = file_store or FileStore()

    def process_and_export(self, payload: NewsPayload) -> Dict[str, Any]:
        """Cleans news articles, eliminates duplicate stories, and exports to CSV and Parquet."""
        ticker = payload.ticker.upper()
        articles = payload.articles

        seen_urls = set()
        seen_hashes = set()
        clean_records: List[Dict[str, Any]] = []
        duplicate_count = 0

        for art in articles:
            url_key = art.url.strip().lower()
            art_hash = art.article_id or compute_article_hash(art.headline, str(art.datetime), art.url)

            if url_key in seen_urls or art_hash in seen_hashes:
                duplicate_count += 1
                continue

            seen_urls.add(url_key)
            seen_hashes.add(art_hash)

            clean_records.append({
                "article_id": art_hash,
                "ticker": ticker,
                "headline": sanitize_untrusted_text(art.headline),
                "summary": sanitize_untrusted_text(art.summary),
                "source": art.source,
                "url": art.url,
                "published_at": str(art.datetime),
                "provider": art.provider or payload.provider or "news_provider",
                "retrieved_at": art.retrieved_at,
                "language": art.language or "en",
            })

        csv_filename = f"{ticker.lower()}_news_clean.csv"
        parquet_filename = f"{ticker.lower()}_news_clean.parquet"

        csv_path = self.file_store.export_csv("news", csv_filename, clean_records)
        parquet_path = self.file_store.export_parquet("news", parquet_filename, clean_records)

        return {
            "ticker": ticker,
            "total_articles": len(articles),
            "clean_articles": len(clean_records),
            "duplicates_removed": duplicate_count,
            "csv_path": str(csv_path),
            "parquet_path": str(parquet_path),
            "records": clean_records,
        }
