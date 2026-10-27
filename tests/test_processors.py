"""Unit tests for processors and indicators."""

import unittest
from pathlib import Path

from kairos.processors.clean_fundamentals import CleanFundamentalsProcessor
from kairos.processors.clean_market import (
    CleanMarketProcessor,
    compute_ema,
    compute_macd,
    compute_rsi,
    compute_sma,
)
from kairos.processors.clean_news import CleanNewsProcessor
from kairos.processors.clean_reddit import CleanRedditProcessor, redact_pii
from kairos.schemas.fundamentals import CompanyFact, FundamentalsPayload
from kairos.schemas.market import MarketBar, MarketDataPayload
from kairos.schemas.news import NewsArticle, NewsPayload
from kairos.schemas.reddit import RedditPost, SentimentPayload


class TestProcessors(unittest.TestCase):

    def test_compute_sma(self):
        prices = [float(i) for i in range(1, 25)]
        sma = compute_sma(prices, window=5)
        self.assertIsNone(sma[0])
        self.assertIsNone(sma[3])
        # 5th element: (1+2+3+4+5)/5 = 3.0
        self.assertEqual(sma[4], 3.0)

    def test_compute_rsi(self):
        prices = [100.0 + i for i in range(20)]
        rsi = compute_rsi(prices, period=14)
        # All gains, zero loss -> RSI = 100
        self.assertEqual(rsi[14], 100.0)

    def test_compute_macd(self):
        prices = [100.0 + (i * 0.5) for i in range(40)]
        macd, signal, hist = compute_macd(prices, fast=12, slow=26, signal_span=9)
        self.assertIsNotNone(macd[-1])
        self.assertIsNotNone(signal[-1])
        self.assertIsNotNone(hist[-1])

    def test_market_deduplication_and_export(self):
        processor = CleanMarketProcessor()
        b1 = MarketBar(timestamp="2026-10-20", open=100.0, high=105.0, low=99.0, close=104.0, volume=1000)
        b2 = MarketBar(timestamp="2026-10-20", open=100.0, high=105.0, low=99.0, close=104.0, volume=1000)  # duplicate
        b3 = MarketBar(timestamp="2026-10-21", open=104.0, high=108.0, low=103.0, close=107.0, volume=2000)

        payload = MarketDataPayload(ticker="TEST", bars=[b1, b2, b3])
        res = processor.process_and_export(payload)

        self.assertEqual(res["total_bars"], 3)
        self.assertEqual(res["clean_bars"], 2)
        self.assertEqual(res["duplicates_removed"], 1)
        self.assertTrue(Path(res["csv_path"]).exists())
        self.assertTrue(Path(res["parquet_path"]).exists())

    def test_reddit_pii_redaction(self):
        raw_text = "Contact trader@wallstreet.com or call 555-123-4567 regarding u/wallstreet_king"
        redacted = redact_pii(raw_text)
        self.assertNotIn("trader@wallstreet.com", redacted)
        self.assertNotIn("555-123-4567", redacted)
        self.assertNotIn("u/wallstreet_king", redacted)
        self.assertIn("[REDACTED_EMAIL]", redacted)
        self.assertIn("[REDACTED_PHONE]", redacted)
        self.assertIn("[REDACTED_USER]", redacted)

    def test_news_deduplication(self):
        processor = CleanNewsProcessor()
        a1 = NewsArticle(
            headline="NVIDIA Expands AI Chips",
            summary="New GPU announcements",
            source="TechNews",
            url="https://technews.com/nvidia-ai-1",
            datetime="2026-10-25",
        )
        a2 = NewsArticle(
            headline="NVIDIA Expands AI Chips",
            summary="Identical story",
            source="TechNews",
            url="https://technews.com/nvidia-ai-1",  # duplicate URL
            datetime="2026-10-25",
        )
        payload = NewsPayload(ticker="NVDA", articles=[a1, a2])
        res = processor.process_and_export(payload)

        self.assertEqual(res["total_articles"], 2)
        self.assertEqual(res["clean_articles"], 1)
        self.assertEqual(res["duplicates_removed"], 1)


if __name__ == "__main__":
    unittest.main()
