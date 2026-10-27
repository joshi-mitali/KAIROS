"""Unit tests for Indian equities market collectors."""

import unittest
from kairos.collectors.history_collector import HistoryCollector
from kairos.collectors.live_quote_collector import LiveQuoteCollector
from kairos.schemas.common import QuoteDelayClassification


class TestIndianMarketCollectors(unittest.TestCase):

    def setUp(self):
        self.history_collector = HistoryCollector()
        self.live_collector = LiveQuoteCollector()

    def test_live_quote_collection_reliance(self):
        payload = self.live_collector.fetch_live_quote("RELIANCE")
        self.assertEqual(payload.symbol, "RELIANCE")
        self.assertGreater(payload.quote.last_price, 0.0)
        self.assertIn(
            payload.quote.quote_delay,
            [QuoteDelayClassification.REAL_TIME, QuoteDelayClassification.DELAYED_15_MIN, QuoteDelayClassification.END_OF_DAY]
        )

    def test_history_collection_ten_years_tcs(self):
        payload = self.history_collector.fetch_historical_data("TCS", period="10y")
        self.assertEqual(payload.symbol, "TCS")
        self.assertGreater(len(payload.bars), 1000)
        # Verify coverage is approximately 10 years
        self.assertGreaterEqual(payload.coverage_years, 9.0)
        self.assertTrue(payload.is_ten_year_complete)
        self.assertIsNotNone(payload.sma_20)
        self.assertIsNotNone(payload.rsi_14)
        self.assertIsNotNone(payload.macd)

    def test_incremental_historical_merge(self):
        # Fetching twice with incremental=True should not duplicate records
        p1 = self.history_collector.fetch_historical_data("INFY", period="10y", incremental=True)
        count_1 = len(p1.bars)
        p2 = self.history_collector.fetch_historical_data("INFY", period="10y", incremental=True)
        count_2 = len(p2.bars)
        self.assertEqual(count_1, count_2)

    def test_ohlc_integrity_on_historical_bars(self):
        payload = self.history_collector.fetch_historical_data("HDFCBANK", period="10y")
        for bar in payload.bars:
            self.assertGreaterEqual(bar.high, bar.low)
            self.assertGreaterEqual(bar.high, bar.open)
            self.assertGreaterEqual(bar.high, bar.close)
            self.assertLessEqual(bar.low, bar.open)
            self.assertLessEqual(bar.low, bar.close)
            # Volume non-negative
            self.assertGreaterEqual(bar.volume, 0)


if __name__ == "__main__":
    unittest.main()
