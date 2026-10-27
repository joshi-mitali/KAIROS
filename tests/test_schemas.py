"""Unit tests for Pydantic v2 data schemas."""

import unittest
from pydantic import ValidationError

from kairos.schemas.fundamentals import CompanyFact, FundamentalsPayload
from kairos.schemas.market import MarketBar, MarketDataPayload
from kairos.schemas.news import NewsArticle, NewsPayload
from kairos.schemas.reddit import RedditPost, SentimentPayload


class TestDataSchemas(unittest.TestCase):

    def test_market_bar_valid(self):
        bar = MarketBar(
            timestamp="2026-10-25",
            open=130.0,
            high=135.0,
            low=129.0,
            close=134.0,
            volume=50000000,
            ticker="NVDA",
        )
        self.assertEqual(bar.open, 130.0)
        self.assertEqual(bar.high, 135.0)
        self.assertEqual(bar.ticker, "NVDA")

    def test_market_bar_invalid_ohlc(self):
        # High lower than Low
        with self.assertRaises(ValidationError):
            MarketBar(
                timestamp="2026-10-25",
                open=130.0,
                high=125.0,  # Invalid: high < low
                low=128.0,
                close=130.0,
                volume=1000,
            )

        # Low higher than Open
        with self.assertRaises(ValidationError):
            MarketBar(
                timestamp="2026-10-25",
                open=120.0,
                high=130.0,
                low=125.0,  # Invalid: low > open
                close=128.0,
                volume=1000,
            )

    def test_market_payload_min_length(self):
        with self.assertRaises(ValidationError):
            MarketDataPayload(ticker="AAPL", bars=[])

    def test_reddit_post_valid_and_permalink(self):
        post = RedditPost(
            post_id="post_123",
            title="Institutional analysis on NVDA",
            text="Checking quarterly volume and margins",
            score=150,
            num_comments=45,
            subreddit="stocks",
            permalink="https://www.reddit.com/r/stocks/comments/post_123/",
            created_utc=1700000000.0,
        )
        self.assertEqual(post.id, "post_123")
        self.assertEqual(post.score, 150)

        # Invalid permalink format
        with self.assertRaises(ValidationError):
            RedditPost(
                post_id="post_bad",
                title="Bad permalink",
                snippet="",
                score=0,
                num_comments=0,
                subreddit="stocks",
                permalink="ftp://invalid-url.com",
                created_utc=1700000000.0,
            )

    def test_news_article_validation(self):
        article = NewsArticle(
            headline="NVDA Reports Earnings",
            summary="Strong datacenter demand",
            source="Reuters",
            url="https://www.reuters.com/nvda-earnings",
            datetime="2026-10-26T12:00:00Z",
        )
        self.assertEqual(article.source, "Reuters")
        self.assertTrue(article.url.startswith("https://"))

        # Bad URL
        with self.assertRaises(ValidationError):
            NewsArticle(
                headline="Invalid URL Article",
                summary="Bad url test",
                source="Unknown",
                url="bad_url_without_http",
                datetime="2026-10-26",
            )

    def test_fundamentals_payload_validation(self):
        fact = CompanyFact(
            fact_name="Revenues",
            taxonomy="us-gaap",
            value=60922000000.0,
            unit="USD",
            fiscal_year=2024,
            fiscal_period="FY",
        )
        payload = FundamentalsPayload(
            ticker="NVDA",
            cik="0001045810",
            company_name="NVIDIA CORP",
            revenue=60922000000.0,
            facts=[fact],
        )
        self.assertEqual(payload.cik, "0001045810")
        self.assertEqual(len(payload.facts), 1)
        self.assertEqual(payload.facts[0].fact_name, "Revenues")


if __name__ == "__main__":
    unittest.main()
