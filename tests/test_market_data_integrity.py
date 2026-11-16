"""Unit and integration tests for KAIROS market data pipeline remediation.
Verifies MCP import collision fixes, mock transport isolation, corporate-action adjustments,
technical indicator recalculations, TraderAgent invalid data rejection, and Reddit provenance.
"""

import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
import pandas as pd

from kairos.mcp_client.client import MCPClientManager, _load_yfinance_mcp_module
from kairos.processors.clean_market import compute_macd, compute_rsi, compute_sma
from kairos.processors.validate_market import validate_market_data
from kairos.agents.trader_agent import TraderAgent
from kairos.schemas.analyst_reports import (
    RecommendationVerdict,
    ResearchSynthesisVerdict,
    SignalStrength,
)
from kairos.schemas.trading_proposal import TradeDirection


class TestMarketDataIntegrity(unittest.TestCase):

    def setUp(self):
        self.ticker = "RELIANCE"

    def test_mcp_import_collision_prevention(self):
        """Verifies that loading yfinance MCP server module does not import project root main.py."""
        import main as root_main
        # Root main is KAIROS CLI/runner (has 'main' function), NOT FastMCP server
        self.assertTrue(hasattr(root_main, "main"))
        self.assertFalse(hasattr(root_main, "get_stock_info"))

        # _load_yfinance_mcp_module loads the external module safely without collision
        mcp_mod = _load_yfinance_mcp_module()
        if mcp_mod:
            self.assertTrue(hasattr(mcp_mod, "get_stock_info") or hasattr(mcp_mod, "get_stock_history"))

    def test_mock_transport_isolation_production(self):
        """Verifies that mock transport is strictly blocked in production and raises RuntimeError."""
        with patch.dict(os.environ, {"KAIROS_ALLOW_MOCK": "false", "KAIROS_ENV": "production"}):
            client = MCPClientManager()
            self.assertFalse(client.allow_mock)
            # In production, calling tool that fails live must raise RuntimeError and NOT return synthetic fixture
            with patch.object(client, "_call_live_yfinance", side_effect=RuntimeError("Live connection failed")):
                with self.assertRaises(RuntimeError) as ctx:
                    client.call_tool("yfinance", "get_stock_info", {"symbol": "RELIANCE.NS"}, use_mock_fallback=None)
                self.assertIn("Silent mock fallback is strictly forbidden in production", str(ctx.exception))

    def test_mock_transport_explicit_test_environment(self):
        """Verifies that mock transport operates when explicitly allowed in a test environment."""
        with patch.dict(os.environ, {"KAIROS_ALLOW_MOCK": "true", "KAIROS_ENV": "test"}):
            client = MCPClientManager()
            self.assertTrue(client.allow_mock)
            # Mock is a fallback only: force the live call to fail so the result does not depend on network.
            with patch.object(client, "_call_live_yfinance", side_effect=RuntimeError("offline")):
                res = client.call_tool("yfinance", "get_stock_info", {"symbol": "RELIANCE.NS"}, use_mock_fallback=True)
            self.assertEqual(res.get("provenance"), "SYNTHETIC_FIXTURE")

    def test_corporate_action_adjustment_and_price_basis(self):
        """Verifies that genuine historical bars and quotes are on the same post-bonus price basis."""
        pq_path = "data/processed/market/reliance_10y_clean.parquet"
        if os.path.exists(pq_path):
            df = pd.read_parquet(pq_path)
            self.assertGreaterEqual(len(df), 2000)
            self.assertTrue(df["date"].is_monotonic_increasing)
            recent_60 = df.tail(60)
            sup = float(recent_60["low"].min())
            res = float(recent_60["high"].max())

            # Read live quote
            live_pq = "data/processed/live/reliance_live.parquet"
            live_df = pd.read_parquet(live_pq)
            last_price = float(live_df["last_price"].iloc[-1])

            # Verified Reliance post-bonus trading range (~₹1,150 - ₹1,400)
            self.assertGreater(last_price, 1000.0)
            self.assertLess(last_price, 1600.0)
            self.assertGreaterEqual(sup, 1000.0)
            self.assertLessEqual(res, 1600.0)

            # Price basis validation
            val_res = validate_market_data(self.ticker, df, live_df.iloc[-1].to_dict(), allow_mock=False)
            self.assertTrue(val_res.is_valid)
            self.assertTrue(val_res.price_basis_compatible)

    def test_technical_indicators_recalculation(self):
        """Verifies independent mathematical accuracy of SMA 20, RSI 14, and MACD calculations."""
        prices = [100.0 + i for i in range(50)]
        sma = compute_sma(prices, window=20)
        self.assertEqual(len(sma), 50)
        self.assertAlmostEqual(sma[-1], sum(prices[-20:]) / 20.0, places=3)

        rsi = compute_rsi(prices, period=14)
        self.assertEqual(len(rsi), 50)
        self.assertGreater(rsi[-1], 90.0)  # Monotonically increasing price gives very high RSI

        macd, sig, hist = compute_macd(prices)
        self.assertEqual(len(macd), 50)
        self.assertIsNotNone(macd[-1])

    def test_trader_agent_rejects_synthetic_fixture(self):
        """Verifies TraderAgent blocks proposal generation if market data is tagged SYNTHETIC_FIXTURE."""
        with patch.dict(os.environ, {"KAIROS_ALLOW_MOCK": "false", "KAIROS_ENV": "production"}):
            trader = TraderAgent()
            verdict = ResearchSynthesisVerdict(
                trace_id="test_tr",
                ticker="RELIANCE",
                recommendation=RecommendationVerdict.OVERWEIGHT,
                conviction=SignalStrength.STRONG,
                synthesis_rationale="Synthetic test",
                bull_summary="Bull",
                bear_summary="Bear",
                key_drivers=["Driver"],
                risk_factors=["Risk"],
                macro_alignment="Neutral",
                data_freshness_status="CURRENT",
            )
            synthetic_market = {
                "last_price": 1164.9,
                "support_level": 1152.2,
                "resistance_level": 1337.0,
                "provenance": "SYNTHETIC_FIXTURE",
            }
            with self.assertRaises(ValueError) as ctx:
                trader.generate_deterministic_proposal(
                    ticker="RELIANCE",
                    analyst_reports={"market": synthetic_market},
                    verdict=verdict,
                )
            self.assertIn("Synthetic fixture market data", str(ctx.exception))

    def test_trader_agent_rejects_price_basis_mismatch(self):
        """Verifies TraderAgent blocks proposal generation if current quote severely diverges from historical levels."""
        with patch.dict(os.environ, {"KAIROS_ALLOW_MOCK": "false", "KAIROS_ENV": "production"}):
            trader = TraderAgent()
            verdict = ResearchSynthesisVerdict(
                trace_id="test_tr",
                ticker="RELIANCE",
                recommendation=RecommendationVerdict.OVERWEIGHT,
                conviction=SignalStrength.STRONG,
                synthesis_rationale="Mismatch test",
                bull_summary="Bull",
                bear_summary="Bear",
                key_drivers=["Driver"],
                risk_factors=["Risk"],
                macro_alignment="Neutral",
                data_freshness_status="CURRENT",
            )
            # Pre-split quote ₹2,750 against post-split support/resistance ~₹1,152/₹1,337
            mismatched_market = {
                "last_price": 2750.0,
                "support_level": 1152.2,
                "resistance_level": 1337.0,
                "provenance": "LIVE_YAHOO_FINANCE",
            }
            with self.assertRaises(ValueError) as ctx:
                trader.generate_deterministic_proposal(
                    ticker="RELIANCE",
                    analyst_reports={"market": mismatched_market},
                    verdict=verdict,
                )
            self.assertIn("Severe price basis divergence detected", str(ctx.exception))

    def test_conservative_hold_zero_capital_allocation(self):
        """Verifies that a HOLD verdict under conservative profile strictly enforces 0% new capital."""
        trader = TraderAgent()
        verdict = ResearchSynthesisVerdict(
            trace_id="test_tr",
            ticker="RELIANCE",
            recommendation=RecommendationVerdict.NEUTRAL,
            conviction=SignalStrength.MODERATE,
            synthesis_rationale="Rangebound hold",
            bull_summary="Bull",
            bear_summary="Bear",
            key_drivers=["Driver"],
            risk_factors=["Risk"],
            macro_alignment="Neutral",
            data_freshness_status="CURRENT",
        )
        market_data = {
            "last_price": 1164.9,
            "support_level": 1152.2,
            "resistance_level": 1337.0,
            "provenance": "LIVE_YAHOO_FINANCE",
        }
        prop = trader.generate_deterministic_proposal(
            ticker="RELIANCE",
            analyst_reports={"market": market_data},
            verdict=verdict,
            risk_preference="CONSERVATIVE",
        )
        self.assertEqual(prop.direction, TradeDirection.HOLD)
        self.assertIn("0% new capital", prop.position_sizing)
        self.assertEqual(prop.risk_reward_ratio, 0.0)  # HOLD levels are reference only
        self.assertTrue(prop.levels_reference_only)

    def test_reddit_source_provenance_distinction(self):
        """Verifies that Reddit RSS posts are tagged LIVE_REDDIT_ATOM_FEED and not marked synthetic."""
        reddit_pq = "data/processed/reddit/reliance_sentiment_clean.parquet"
        if os.path.exists(reddit_pq):
            df = pd.read_parquet(reddit_pq)
            self.assertEqual(len(df), 6)
            self.assertTrue(all(df["source_status"] == "LIVE_REDDIT_ATOM_FEED"))
            self.assertFalse(any(df["is_synthetic"]))
            # Authors must be real handles
            authors = df["author"].tolist()
            self.assertIn("/u/SmolTeddu", authors)


if __name__ == "__main__":
    unittest.main()
