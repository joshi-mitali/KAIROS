"""Unit tests for DataQualityChecker."""

import json
import unittest
from pathlib import Path

from kairos.validation.quality_checks import DataQualityChecker


class TestQualityChecks(unittest.TestCase):

    def setUp(self):
        self.checker = DataQualityChecker()

    def test_quality_analysis_clean(self):
        records = [
            {"ticker": "NVDA", "timestamp": "2026-10-20", "open": 130.0, "high": 135.0, "low": 129.0, "close": 134.0, "volume": 50000},
            {"ticker": "NVDA", "timestamp": "2026-10-21", "open": 134.0, "high": 138.0, "low": 133.0, "close": 137.0, "volume": 60000},
        ]
        report, quarantined = self.checker.analyze_dataset(
            domain="market",
            records=records,
            required_fields=["ticker", "timestamp", "open", "high", "low", "close", "volume"],
            provider="test_provider",
            data_classification="LIVE_API",
            date_field="timestamp",
        )
        self.assertEqual(report.total_records, 2)
        self.assertEqual(report.valid_records, 2)
        self.assertEqual(report.invalid_records, 0)
        self.assertEqual(len(quarantined), 0)
        self.assertEqual(report.missing_value_percentages["open"], 0.0)

    def test_quarantine_invalid_records(self):
        records = [
            {"ticker": "NVDA", "timestamp": "2026-10-20", "open": 130.0, "high": 135.0, "low": 129.0, "close": 134.0, "volume": 50000},
            {"ticker": "NVDA", "timestamp": "2026-10-21", "open": None, "high": 138.0, "low": 133.0, "close": 137.0, "volume": 60000},  # missing open
            {"ticker": "NVDA", "timestamp": "", "open": 137.0, "high": 139.0, "low": 135.0, "close": 138.0, "volume": 40000},  # empty timestamp
        ]
        report, quarantined = self.checker.analyze_dataset(
            domain="market",
            records=records,
            required_fields=["ticker", "timestamp", "open", "high", "low", "close", "volume"],
            provider="test_provider",
            data_classification="LIVE_API",
            date_field="timestamp",
        )
        self.assertEqual(report.total_records, 3)
        self.assertEqual(report.valid_records, 1)
        self.assertEqual(report.invalid_records, 2)
        self.assertEqual(len(quarantined), 2)
        self.assertIsNotNone(report.quarantine_file)
        self.assertTrue(Path(report.quarantine_file).exists())


if __name__ == "__main__":
    unittest.main()
