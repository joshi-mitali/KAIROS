"""Collector for Indian retail stock discussions and sentiment via Reddit MCP server."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kairos.config.settings import get_settings
from kairos.mcp_client.adapters import RedditMCPAdapter
from kairos.processors.clean_reddit import CleanRedditProcessor
from kairos.schemas.reddit import RedditPost, SentimentPayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger
from kairos.utils.security import validate_ticker

logger = get_logger("kairos.collectors.reddit_collector")


class RedditCollector:
    """Collects social sentiment across Indian finance communities (r/IndianStockMarket, etc.)."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.settings = get_settings()
        self.file_store = file_store or FileStore()
        self.reddit_adapter = RedditMCPAdapter()
        self.clean_processor = CleanRedditProcessor(file_store=self.file_store)

    def fetch_community_sentiment(
        self,
        symbol: str,
        subreddits: Optional[List[str]] = None,
        limit_per_sub: int = 5,
    ) -> SentimentPayload:
        """
        Gathers Reddit posts referencing an Indian equity across retail trading subreddits.
        Redacts personal identifiers and preserves permission provenance.
        """
        clean_symbol = validate_ticker(symbol).replace(".NS", "").replace(".BO", "")
        target_subs = subreddits or self.settings.reddit_subreddits
        logger.info(f"Gathering Reddit sentiment for {clean_symbol} across {target_subs} via Reddit MCP")

        all_posts: List[RedditPost] = []
        is_live = self.settings.reddit_authorized
        permission_status = "AUTHORIZED_API" if is_live else "PERMITTED_SAMPLE_FIXTURE"

        retrieval_ts = datetime.now(timezone.utc).isoformat()

        for sub in target_subs:
            try:
                raw_resp = self.reddit_adapter.search_reddit(query=clean_symbol, subreddit=sub)
                raw_posts = raw_resp.get("posts", [])
                for p in raw_posts[:limit_per_sub]:
                    post = RedditPost(
                        id=str(p["id"]),
                        title=str(p["title"]),
                        snippet=str(p.get("selftext", "")),
                        score=int(p.get("score", 0)),
                        num_comments=int(p.get("num_comments", 0)),
                        subreddit=sub,
                        permalink=str(p.get("permalink", f"/r/{sub}/comments/{p['id']}")),
                        created_utc=float(p.get("created_utc", 0.0)),
                        retrieval_timestamp=retrieval_ts,
                        is_synthetic=not is_live,
                        source_status="LIVE_API" if is_live else "PERMITTED_SAMPLE_FIXTURE",
                    )
                    all_posts.append(post)
            except Exception as e:
                logger.warning(f"Error fetching sentiment for {clean_symbol} in r/{sub}: {e}")

        # Save raw JSON
        raw_export = {
            "symbol": clean_symbol,
            "subreddits": target_subs,
            "permission_status": permission_status,
            "posts": [p.model_dump() for p in all_posts],
        }
        self.file_store.save_raw("reddit", f"{clean_symbol.lower()}_sentiment.json", raw_export)

        payload = SentimentPayload(
            ticker=clean_symbol,
            posts=all_posts,
            is_live_data=is_live,
            permission_status=permission_status,
        )

        self.clean_processor.process_and_export(payload)
        return payload
