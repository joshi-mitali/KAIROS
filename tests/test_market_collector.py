"""Unit tests for MarketCollector."""

import unittest
from kairos.collectors.market_collector import MarketCollector


class TestMarketCollector(unittest.TestCase):

    def setUp(self):
        self.collector = MarketCollector()

    def test_fetch_ticker_data_nvda(self):
        payload = self.collector.fetch_ticker_data("NVDA")
        self.assertEqual(payload.ticker, "NVDA")
        self.assertGreater(len(payload.bars), 0)
        self.assertIsNotNone(payload.sma_20)
        self.assertIsNotNone(payload.rsi_14)
        self.assertGreater(payload.rsi_14, 0.0)
        self.assertLessEqual(payload.rsi_14, 100.0)

    def test_invalid_ticker_rejection(self):
        with self.assertRaises(ValueError):
            self.collector.fetch_ticker_data("INVALID;;DROP TABLE")

    def test_empty_ticker_rejection(self):
        with self.assertRaises(ValueError):
            self.collector.fetch_ticker_data("")

    def test_ohlc_integrity(self):
        payload = self.collector.fetch_ticker_data("AAPL")
        for bar in payload.bars:
            self.assertGreaterEqual(bar.high, bar.low)
            self.assertGreaterEqual(bar.high, bar.open)
            self.assertGreaterEqual(bar.high, bar.close)
            self.assertLessEqual(bar.low, bar.open)
            self.assertLessEqual(bar.low, bar.close)


if __name__ == "__main__":
    unittest.main()
