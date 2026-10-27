"""Reddit sentiment collector with compliance checks, provider switching, and fixture fallbacks."""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

from kairos.config.settings import get_settings
from kairos.processors.clean_reddit import CleanRedditProcessor
from kairos.schemas.reddit import RedditPost, SentimentPayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger
from kairos.utils.security import validate_ticker

logger = get_logger("kairos.collectors.reddit_collector")


class RedditCollector:
    """Collects sentiment and discussion records adhering strictly to Reddit API compliance policies."""

    def __init__(self, file_store: Optional[FileStore] = None):
        self.settings = get_settings()
        self.file_store = file_store or FileStore()
        self.clean_processor = CleanRedditProcessor(file_store=self.file_store)

    def fetch_community_sentiment(
        self,
        ticker: str,
        subreddits: Optional[List[str]] = None,
        limit_per_sub: int = 5,
    ) -> SentimentPayload:
        """
        Gathers Reddit posts referencing a ticker.
        Checks for authorized credentials first.
        If credentials/permissions are missing or network is unavailable, returns a clearly labeled
        synthetic fixture for safe pipeline testing and auditable reporting.
        """
        clean_ticker = validate_ticker(ticker)
        target_subs = subreddits or ["stocks", "wallstreetbets", "investing"]
        all_posts: List[RedditPost] = []
        is_live = False
        permission_status = "PERMITTED_SAMPLE_FIXTURE"

        headers = {
            "User-Agent": self.settings.reddit_user_agent
        }

        # Check if authorized live access is enabled
        if self.settings.reddit_authorized:
            logger.info("Attempting authorized Reddit collection...")
            for sub in target_subs:
                url = f"https://www.reddit.com/r/{sub}/search.json?q={clean_ticker}&restrict_sr=1&sort=new&limit={limit_per_sub}"
                try:
                    resp = requests.get(url, headers=headers, timeout=self.settings.request_timeout_seconds)
                    if resp.status_code == 200:
                        posts = self._parse_reddit_json(sub, resp.json(), is_synthetic=False)
                        all_posts.extend(posts)
                        is_live = True
                        permission_status = "AUTHORIZED_LIVE_API"
                    elif resp.status_code == 429:
                        logger.warning(f"Reddit rate limit encountered for r/{sub}. Falling back to permitted fixture.")
                    else:
                        logger.warning(f"Reddit API returned status {resp.status_code} for r/{sub}.")
                except Exception as e:
                    logger.warning(f"Network error accessing Reddit endpoint for r/{sub}: {e}")
        else:
            logger.info("Live Reddit credentials not configured. Utilizing approved synthetic sample fixtures.")
            permission_status = "UNCONFIGURED_CREDENTIALS_FIXTURE_MODE"

        # If live retrieval produced no posts, use deterministic sample fixture
        if not all_posts:
            logger.info(f"Generating deterministic synthetic sentiment fixture for {clean_ticker}")
            all_posts = self._generate_synthetic_fixture(clean_ticker, target_subs, limit_per_sub)
            is_live = False

        payload = SentimentPayload(
            ticker=clean_ticker,
            posts=all_posts,
            is_live_data=is_live,
            permission_status=permission_status,
        )

        # Save raw JSON
        raw_export = {
            "ticker": clean_ticker,
            "permission_status": permission_status,
            "is_live_data": is_live,
            "posts": [p.model_dump() for p in all_posts],
        }
        self.file_store.save_raw("reddit", f"{clean_ticker.lower()}_sentiment.json", raw_export)

        # Process, redact PII, and export clean CSV/Parquet
        self.clean_processor.process_and_export(payload)
        return payload

    def _parse_reddit_json(self, subreddit: str, data: Dict[str, Any], is_synthetic: bool = False) -> List[RedditPost]:
        """Parses raw Reddit JSON listing into RedditPost models."""
        posts: List[RedditPost] = []
        try:
            children = data.get("data", {}).get("children", [])
            retrieval_ts = datetime.now(timezone.utc).isoformat()

            for child in children:
                post_data = child.get("data", {})
                post_id = str(post_data.get("id", ""))
                title = str(post_data.get("title", ""))
                selftext = str(post_data.get("selftext", ""))
                score = int(post_data.get("score", 0))
                num_comments = int(post_data.get("num_comments", 0))
                permalink = str(post_data.get("permalink", f"/r/{subreddit}/comments/{post_id}"))
                created_utc = float(post_data.get("created_utc", time.time()))

                post = RedditPost(
                    id=post_id,
                    title=title,
                    snippet=selftext[:500],
                    score=score,
                    num_comments=num_comments,
                    subreddit=subreddit,
                    permalink=permalink if permalink.startswith("http") or permalink.startswith("/r/") else f"/r/{subreddit}/comments/{post_id}",
                    created_utc=created_utc,
                    retrieval_timestamp=retrieval_ts,
                    is_synthetic=is_synthetic,
                    source_status="LIVE_API" if not is_synthetic else "SYNTHETIC_FIXTURE",
                )
                posts.append(post)
        except Exception as e:
            logger.error(f"Error parsing Reddit JSON payload: {e}")

        return posts

    def _generate_synthetic_fixture(
        self, ticker: str, subreddits: List[str], limit_per_sub: int
    ) -> List[RedditPost]:
        """Builds clearly labeled synthetic posts to verify pipelines without accessing unauthorized networks."""
        posts: List[RedditPost] = []
        retrieval_ts = datetime.now(timezone.utc).isoformat()
        current_time = time.time()

        sample_templates = [
            ("Institutional quarterly volume breakout analysis on ${ticker}", "Tracking institutional dark pool order flow and delta volume.", 245, 48),
            ("${ticker} earnings options implied volatility setup", "Evaluating straddle pricing and skew prior to the upcoming disclosure.", 132, 29),
            ("Long-term margin expansion hypothesis for ${ticker}", "Gross margin sustainability models assuming competitive market share holds.", 380, 85),
            ("Technical resistance test at 50-day moving average for ${ticker}", "Consolidating near key resistance zone with declining average volume.", 95, 14),
            ("Sector rotation and capital allocation implications for ${ticker}", "Portfolio rebalancing across technology hardware and datacenter compute.", 174, 33),
        ]

        counter = 1
        for sub in subreddits:
            for i in range(min(limit_per_sub, len(sample_templates))):
                title_template, snippet_template, score, comments = sample_templates[i]
                post_id = f"syn_{ticker.lower()}_{sub[:4]}_{counter}"
                post = RedditPost(
                    id=post_id,
                    title=title_template.replace("${ticker}", ticker),
                    snippet=snippet_template.replace("${ticker}", ticker),
                    score=score + (counter * 10),
                    num_comments=comments + counter,
                    subreddit=sub,
                    permalink=f"https://www.reddit.com/r/{sub}/comments/{post_id}/sample_post/",
                    created_utc=current_time - (counter * 3600),
                    retrieval_timestamp=retrieval_ts,
                    is_synthetic=True,
                    source_status="SYNTHETIC_FIXTURE",
                )
                posts.append(post)
                counter += 1

        return posts
