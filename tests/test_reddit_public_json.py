"""Unit tests for the Reddit CLI collector: scoring, RSS-only access, and explicit curated-fallback attribution."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from kairos.collectors.reddit_collector import RedditCollector, score_sentiment_text
from kairos.agents.adk_analysts.sentiment_analyst import SentimentAnalyst
from kairos.schemas.reddit import RedditPost, SentimentPayload
from kairos.schemas.analyst_reports import SentimentAnalysisReport, TrendDirection
from kairos.storage.file_store import FileStore


class TestRedditPublicJsonCollection(unittest.TestCase):
    """Verifies CLI collection error handling and attribution."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.file_store = FileStore(base_dir=self.tmp_dir.name)
        self.mock_session = MagicMock(spec=requests.Session)
        self.collector = RedditCollector(
            file_store=self.file_store,
            session=self.mock_session,
            max_retries=1,
        )

        # Seed minimal fallback dataset so fallback activation succeeds cleanly
        raw_reddit = Path(self.tmp_dir.name) / "raw" / "reddit"
        raw_reddit.mkdir(parents=True, exist_ok=True)
        sample_fallback = {
            "symbol": "RELIANCE",
            "posts": [
                {
                    "id": "fallback_1",
                    "title": "Reliance Q2 Results Review and Core Margins",
                    "snippet": "Strong EBITDA expansion in Retail, debt remains manageable.",
                    "score": 45,
                    "num_comments": 12,
                    "subreddit": "IndianStockMarket",
                    "permalink": "/r/IndianStockMarket/comments/fallback_1",
                    "created_utc": 1730000000.0,
                    "relevance_level": "TICKER_SPECIFIC",
                },
                {
                    "id": "fallback_2",
                    "title": "Nifty Weekly Trend and Indian Markets",
                    "snippet": "Broader market consolidation expected.",
                    "score": 20,
                    "num_comments": 5,
                    "subreddit": "IndianStockMarket",
                    "permalink": "/r/IndianStockMarket/comments/fallback_2",
                    "created_utc": 1730001000.0,
                    "relevance_level": "MACRO_MARKET_CONTEXT",
                },
            ]
        }
        with open(raw_reddit / "reliance_sentiment.json", "w", encoding="utf-8") as f:
            json.dump(sample_fallback, f)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_sentiment_scoring_lexicon(self):
        """Tests financial sentiment lexicon scoring."""
        lbl_pos, score_pos = score_sentiment_text("Reliance announces massive profit, growth and multibagger rally")
        self.assertEqual(lbl_pos, "POSITIVE")
        self.assertGreater(score_pos, 0.0)

        lbl_neg, score_neg = score_sentiment_text("Market crash and severe loss with overvalued risk debt")
        self.assertEqual(lbl_neg, "NEGATIVE")
        self.assertLess(score_neg, 0.0)

        lbl_neu, score_neu = score_sentiment_text("General discussion on trading hours")
        self.assertEqual(lbl_neu, "NEUTRAL")
        self.assertEqual(score_neu, 0.0)

    def test_http_403_triggers_fallback(self):
        """Verifies that HTTP 403 (firewall/unauthorized) cleanly activates fallback without endless retries."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.headers = {"Server": "snooserv"}
        self.mock_session.get.return_value = mock_resp

        payload = self.collector.fetch_community_sentiment("RELIANCE", subreddits=["IndianStockMarket"])

        self.assertFalse(payload.is_live_data)
        self.assertEqual(payload.permission_status, "CURATED_FALLBACK")
        self.assertEqual(payload.live_posts_count, 0)
        self.assertGreater(payload.fallback_posts_count, 0)
        for p in payload.posts:
            self.assertEqual(p.source_status, "CURATED_FALLBACK")
            self.assertTrue(p.is_synthetic)

    @patch("kairos.collectors.reddit_collector.time.sleep")
    def test_http_429_rate_limit_handling(self, _sleep):
        """Verifies handling of HTTP 429 rate limit with Retry-After and fallback on exhaustion."""
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"Retry-After": "0.1"}
        self.mock_session.get.return_value = mock_resp

        payload = self.collector.fetch_community_sentiment("RELIANCE", subreddits=["IndianStockMarket"])

        # Should fall back cleanly after bounded retries
        self.assertFalse(payload.is_live_data)
        self.assertEqual(payload.permission_status, "CURATED_FALLBACK")
        self.assertEqual(payload.live_posts_count, 0)

    def test_never_requests_login_gated_json(self):
        """Anonymous .json is login-gated, so only RSS URLs are requested."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        self.mock_session.get.return_value = mock_resp
        self.collector.fetch_community_sentiment("RELIANCE", subreddits=["IndianStockMarket"])
        urls = [c.args[0] for c in self.mock_session.get.call_args_list]
        self.assertTrue(urls)
        self.assertFalse([u for u in urls if ".json" in u])

    def test_sentiment_analyst_consumes_fallback_posts(self):
        """Verifies that SentimentAnalyst truthfully reports CURATED_FALLBACK when live data is unavailable."""
        # Trigger fallback by simulating 403
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        self.mock_session.get.return_value = mock_resp

        self.collector.fetch_community_sentiment("RELIANCE", subreddits=["IndianStockMarket"])

        analyst = SentimentAnalyst(data_dir=self.tmp_dir.name)
        report = analyst.run_analysis("RELIANCE")

        self.assertEqual(report.data_source, "CURATED_FALLBACK")
        self.assertEqual(report.live_posts_count, 0)
        self.assertGreater(report.fallback_posts_count, 0)
        self.assertIn("CURATED_FALLBACK", report.community_source)


if __name__ == "__main__":
    unittest.main()

