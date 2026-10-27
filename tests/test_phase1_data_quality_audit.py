"""Automated Data Quality & Integrity Validation Tests for KAIROS Phase 1."""

import json
import unittest
from pathlib import Path
import pandas as pd


class TestPhase1DataQualityAudit(unittest.TestCase):
    """Rigorous audit tests validating all four Phase 1 data categories."""

    def test_hdfcbank_quote_reconciliation(self):
        """Verifies HDFCBANK's live quote, delayed classification, and post-split reconciliation."""
        f_live = Path("data/processed/live/hdfcbank_live.csv")
        self.assertTrue(f_live.exists(), "hdfcbank_live.csv must exist")
        df = pd.read_csv(f_live)
        row = df.iloc[0]

        # Reconcile price
        self.assertAlmostEqual(row["last_price"], 680.20, delta=0.05,
                               msg=f"HDFCBANK live quote should be ₹680.20, got {row['last_price']}")

        # Verify delayed status classification
        self.assertEqual(row["quote_delay"], "15_MIN_DELAYED",
                         "NSE quote feed from Yahoo Finance must be classified as 15_MIN_DELAYED")
        self.assertTrue(bool(row["is_live_data"]), "Quote should be marked is_live_data=True")
        self.assertEqual(row["exchange"], "NSE")
        self.assertEqual(row["currency"], "INR")

    def test_fundamentals_filings_and_taxonomy(self):
        """Verifies statutory taxonomy, units, and removes unsupported provenance claims."""
        target_tickers = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
        for sym in target_tickers:
            f_fund = Path(f"data/processed/fundamentals/{sym.lower()}_summary_clean.csv")
            self.assertTrue(f_fund.exists(), f"Missing fundamentals for {sym}")
            df = pd.read_csv(f_fund)
            row = df.iloc[0]

            self.assertGreater(row["revenue"], 0)
            self.assertGreater(row["total_assets"], 0)
            self.assertEqual(row["provenance"], "LIVE_YAHOO_FINANCE_MCP",
                             "Provenance must be LIVE_YAHOO_FINANCE_MCP without unsupported claims")

            if sym == "INFY":
                # INFY reports consolidated to US SEC under Form 20-F in USD
                self.assertEqual(row["currency"], "USD", "INFY financial currency must be USD")
                self.assertEqual(row["filing_standard"], "sec-form-20f", "INFY taxonomy must be sec-form-20f")
                self.assertGreater(row["revenue"], 15_000_000_000.0)  # >$15B USD
            else:
                # Domestic peers report in INR under MCA Ind-AS
                self.assertEqual(row["currency"], "INR", f"{sym} financial currency must be INR")
                self.assertEqual(row["filing_standard"], "mca-ind-as", f"{sym} taxonomy must be mca-ind-as")

    def test_news_collection_quality_and_relevance(self):
        """Verifies no unrelated articles in HDFCBANK, working URLs, and genuine content summaries."""
        target_tickers = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
        forbidden_hdfc_kws = ["cyient", "sugar", "fdi", "mtf", "indian overseas bank"]

        for sym in target_tickers:
            f_news = Path(f"data/processed/news/{sym.lower()}_news_clean.csv")
            self.assertTrue(f_news.exists(), f"Missing clean news for {sym}")
            df = pd.read_csv(f_news)
            self.assertGreaterEqual(len(df), 5, f"{sym} must have at least 5 verified articles")

            # All URLs must be verified working (HTTP 200)
            self.assertTrue((df["http_status"] == 200).all(), f"All {sym} URLs must have http_status=200")

            # Genuine summaries: no dummy static template
            for _, art in df.iterrows():
                summary = str(art["summary"])
                self.assertFalse(summary.startswith("Disclosures and market reporting regarding"),
                                 f"Generic summary template detected in {sym} article {art['article_id']}")
                self.assertGreater(len(summary), 20, f"Summary too short in {sym} article {art['article_id']}")

            # Strict relevance check for HDFCBANK
            if sym == "HDFCBANK":
                for _, art in df.iterrows():
                    h_lower = str(art["headline"]).lower()
                    for bad_kw in forbidden_hdfc_kws:
                        self.assertNotIn(bad_kw, h_lower,
                                         f"Unrelated article '{art['headline']}' assigned to HDFCBANK!")

    def test_reddit_provenance_and_ticker_classification(self):
        """Verifies Reddit 403 error logging, alternative feed provenance, and post classification."""
        f_raw = Path("data/raw/reddit/indianstockmarket_raw.json")
        f_probe = Path("data/raw/reddit/primary_endpoint_probe.json")
        f_master = Path("data/processed/reddit/indianstockmarket_sentiment.csv")

        self.assertTrue(f_raw.exists() and f_probe.exists() and f_master.exists())

        # Probe error evidence
        with open(f_probe) as fp:
            probe = json.load(fp)
        self.assertEqual(probe.get("http_status"), 403, "Primary endpoint probe must record HTTP 403")
        self.assertEqual(probe.get("server"), "snooserv", "Server must be recorded as snooserv")

        # Master dataset classification
        df = pd.read_csv(f_master)
        self.assertGreaterEqual(len(df), 20)
        self.assertIn("relevant_tickers", df.columns)
        self.assertIn("market_category", df.columns)
        self.assertIn("sentiment_label", df.columns)
        self.assertIn("sentiment_score", df.columns)

        # Per-ticker sentiment files have relevance_level
        for sym in ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]:
            f_ticker = Path(f"data/processed/reddit/{sym.lower()}_sentiment_clean.csv")
            self.assertTrue(f_ticker.exists())
            t_df = pd.read_csv(f_ticker)
            self.assertIn("relevance_level", t_df.columns)
            self.assertIn("target_ticker", t_df.columns)

    def test_historical_10y_ohlcv_continuity(self):
        """Verifies 10 years continuous daily historical data without gaps."""
        target_tickers = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
        for sym in target_tickers:
            f_csv = Path(f"data/processed/market/{sym.lower()}_10y_clean.csv")
            self.assertTrue(f_csv.exists())
            df = pd.read_csv(f_csv)
            self.assertEqual(len(df), 2471, f"{sym} must have 2471 bars")
            self.assertEqual(df["date"].iloc[0], "2016-10-27")
            self.assertEqual(df["date"].iloc[-1], "2026-10-27")


if __name__ == "__main__":
    unittest.main()
