"""Reddit and sentiment data cleaning, redaction, deduplication, and export."""

import re
from typing import Any, Dict, List, Optional

from kairos.schemas.reddit import RedditPost, SentimentPayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger
from kairos.utils.security import sanitize_untrusted_text

logger = get_logger("kairos.processors.clean_reddit")

# Privacy redaction patterns
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_PATTERN = re.compile(r"(\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}")
USER_HANDLE_PATTERN = re.compile(r"(u/|@)[A-Za-z0-9_-]+")


def redact_pii(text: str) -> str:
    """Redacts emails, phone numbers, and explicit user handles to preserve privacy."""
    if not text:
        return ""
    text = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    text = PHONE_PATTERN.sub("[REDACTED_PHONE]", text)
    text = USER_HANDLE_PATTERN.sub("[REDACTED_USER]", text)
    return text


class CleanRedditProcessor:
    """Processes Reddit submissions, redacting personal data and preparing clean exports."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.file_store = file_store or FileStore()

    def process_and_export(self, payload: SentimentPayload) -> Dict[str, Any]:
        """Deduplicates posts, sanitizes untrusted text, redacts PII, and exports to CSV/Parquet."""
        target_name = payload.ticker or payload.subreddit or "community"
        posts = payload.posts

        seen_ids = set()
        clean_records: List[Dict[str, Any]] = []
        duplicate_count = 0

        for post in posts:
            if post.id in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(post.id)

            sanitized_title = sanitize_untrusted_text(redact_pii(post.title))
            sanitized_snippet = sanitize_untrusted_text(redact_pii(post.snippet or ""))

            clean_records.append({
                "post_id": post.id,
                "ticker": payload.ticker,
                "subreddit": post.subreddit,
                "author": getattr(post, "author", None) or "[anonymous]",
                "title": sanitized_title,
                "snippet": sanitized_snippet,
                "score": post.score,
                "num_comments": post.num_comments,
                "permalink": post.permalink,
                "created_utc": post.created_utc,
                "retrieval_timestamp": post.retrieval_timestamp,
                "is_synthetic": post.is_synthetic,
                "source_status": post.source_status,
                "target_ticker": payload.ticker,
                "relevance_level": getattr(post, "relevance_level", "TICKER_SPECIFIC") or "TICKER_SPECIFIC",
                "sentiment_label": getattr(post, "sentiment_label", "NEUTRAL") or "NEUTRAL",
                "sentiment_score": getattr(post, "sentiment_score", 0.0) or 0.0,
            })

        safe_filename_base = target_name.replace("/", "_").lower()
        csv_filename = f"{safe_filename_base}_sentiment_clean.csv"
        parquet_filename = f"{safe_filename_base}_sentiment_clean.parquet"

        csv_path = self.file_store.export_csv("reddit", csv_filename, clean_records)
        parquet_path = self.file_store.export_parquet("reddit", parquet_filename, clean_records)

        return {
            "target": target_name,
            "total_posts": len(posts),
            "clean_posts": len(clean_records),
            "duplicates_removed": duplicate_count,
            "csv_path": str(csv_path),
            "parquet_path": str(parquet_path),
            "records": clean_records,
        }
