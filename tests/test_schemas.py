"""Unit tests for Pydantic v2 data schemas."""

import unittest
from pydantic import ValidationError

from kairos.schemas.common import QuoteDelayClassification
from kairos.schemas.fundamentals import CompanyFact, FundamentalsPayload
from kairos.schemas.history import HistoricalBar, HistoricalDataPayload
from kairos.schemas.live_quote import LiveQuote, LiveQuotePayload
from kairos.schemas.news import NewsArticle, NewsPayload
from kairos.schemas.reddit import RedditPost, SentimentPayload


class TestDataSchemas(unittest.TestCase):

    def test_live_quote_valid(self):
        quote = LiveQuote(
            symbol="RELIANCE",
            last_price=2750.0,
            quote_timestamp="2026-10-27T10:00:00Z",
            volume=5000000,
            day_open=2740.0,
            day_high=2760.0,
            day_low=2735.0,
            previous_close=2730.0,
            quote_delay=QuoteDelayClassification.REAL_TIME,
        )
        self.assertEqual(quote.symbol, "RELIANCE")
        self.assertEqual(quote.last_price, 2750.0)
        self.assertEqual(quote.quote_delay, QuoteDelayClassification.REAL_TIME)

    def test_historical_bar_valid(self):
        bar = HistoricalBar(
            date="2024-10-25",
            symbol="TCS.NS",
            open=3940.0,
            high=3980.0,
            low=3930.0,
            close=3975.0,
            adjusted_close=3975.0,
            volume=1200000,
        )
        self.assertEqual(bar.close, 3975.0)
        self.assertEqual(bar.adjusted_close, 3975.0)

    def test_historical_bar_invalid_ohlc(self):
        with self.assertRaises(ValidationError):
            HistoricalBar(
                date="2024-10-25",
                symbol="TCS.NS",
                open=3940.0,
                high=3900.0,  # Invalid: high < open
                low=3920.0,
                close=3930.0,
                volume=1000,
            )

    def test_reddit_post_validation(self):
        post = RedditPost(
            post_id="post_ind_01",
            title="Analysis on NIFTY 50 and RELIANCE",
            snippet="Delivery volumes expanding",
            score=150,
            num_comments=45,
            subreddit="IndianStockMarket",
            permalink="https://www.reddit.com/r/IndianStockMarket/comments/post_ind_01/",
            created_utc=1700000000.0,
        )
        self.assertEqual(post.id, "post_ind_01")
        self.assertEqual(post.subreddit, "IndianStockMarket")

    def test_news_article_validation(self):
        article = NewsArticle(
            headline="TCS Signs Major Enterprise Cloud Deal",
            summary="Multi-year digital transformation partnership",
            source="The Economic Times",
            url="https://economictimes.indiatimes.com/tcs-deal",
            datetime="2026-10-26T12:00:00Z",
        )
        self.assertEqual(article.source, "The Economic Times")
        self.assertTrue(article.url.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
