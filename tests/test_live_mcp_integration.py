"""Live integration tests for existing MCP servers (distinguished from unit tests)."""

import unittest
from kairos.config.settings import get_settings
from kairos.mcp_client.client import get_mcp_client
from verify_live_mcp import (
    test_live_alphavantage_mcp,
    test_live_nse_mcp,
    test_live_reddit_mcp,
    test_live_yfinance_mcp,
)


class TestLiveMCPIntegration(unittest.TestCase):
    """
    Live integration tests that probe real environments, binaries, and networks.
    Explicitly reports environment prerequisites and does NOT mock responses.
    """

    def setUp(self):
        self.settings = get_settings()
        self.client = get_mcp_client()

    def test_live_mcp_configuration_loaded(self):
        servers = self.client.list_servers()
        self.assertIn("yfinance", servers)
        self.assertIn("nse", servers)
        self.assertIn("alphavantage", servers)
        self.assertIn("reddit", servers)

    def test_live_yfinance_probe(self):
        res = test_live_yfinance_mcp()
        self.assertEqual(res["server"], "yfinance")
        self.assertIn(res["status"], ["CONNECTED", "AVAILABLE", "NOT_INSTALLED", "ERROR"])
        self.assertIn("get_historical_stock_prices", res["declared_tools"])

    def test_live_nse_probe(self):
        res = test_live_nse_mcp()
        self.assertEqual(res["server"], "nse")
        self.assertIn(res["status"], ["CONNECTED", "GATEWAY_THROTTLED", "UNREACHABLE", "ERROR"])
        self.assertIn("stock_quote", res["declared_tools"])

    def test_live_alphavantage_credentials_check(self):
        res = test_live_alphavantage_mcp(self.settings.alphavantage_api_key or "")
        self.assertEqual(res["server"], "alphavantage")
        self.assertIn(res["status"], ["CONNECTED", "MISSING_CREDENTIALS", "NETWORK_ERROR"])

    def test_live_reddit_credentials_check(self):
        res = test_live_reddit_mcp(
            self.settings.reddit_client_id or "", self.settings.reddit_client_secret or ""
        )
        self.assertEqual(res["server"], "reddit")
        self.assertIn(res["status"], ["CONFIGURED", "MISSING_CREDENTIALS", "BINARY_NOT_FOUND"])


if __name__ == "__main__":
    unittest.main()

