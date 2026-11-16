"""Unit tests for MCP client integration with existing financial MCP servers."""

import functools
import unittest
from kairos.mcp_client.adapters import (
    AlphaVantageMCPAdapter,
    NSEMCPAdapter,
    RedditMCPAdapter,
    YFinanceMCPAdapter,
)
from kairos.mcp_client.client import MCPClientManager


def skip_if_live_unavailable(fn):
    """Skip (never fake success) when the live third-party service/binary/credential is unavailable here."""

    @functools.wraps(fn)
    def wrapper(self):
        try:
            return fn(self)
        except RuntimeError as e:
            if "Live MCP tool call failed" in str(e):
                self.skipTest(f"live MCP service unavailable in this environment: {str(e)[:160]}")
            raise

    return wrapper


class TestMCPClientIntegration(unittest.TestCase):

    def setUp(self):
        self.client_manager = MCPClientManager()
        self.yf_adapter = YFinanceMCPAdapter(client=self.client_manager)
        self.nse_adapter = NSEMCPAdapter(client=self.client_manager)
        self.alpha_adapter = AlphaVantageMCPAdapter(client=self.client_manager)
        self.reddit_adapter = RedditMCPAdapter(client=self.client_manager)

    def test_mcp_server_discovery(self):
        servers = self.client_manager.list_servers()
        self.assertIn("yfinance", servers)
        self.assertIn("nse", servers)
        self.assertIn("alphavantage", servers)
        self.assertIn("reddit", servers)

    def test_yfinance_mcp_historical_tools(self):
        res = self.yf_adapter.get_historical_stock_prices("RELIANCE.NS", period="10y")
        self.assertIn("bars", res)
        self.assertGreater(len(res["bars"]), 1000)
        # Check first and latest bar dates to verify ~10-year span through 2026
        first_date = res["bars"][0]["date"]
        latest_date = res["bars"][-1]["date"]
        self.assertTrue(first_date.startswith("2016") or first_date.startswith("2014"))
        self.assertTrue(latest_date.startswith("2026"))

    def test_yfinance_mcp_stock_info(self):
        res = self.yf_adapter.get_stock_info("TCS.NS")
        self.assertIn("currentPrice", res)
        self.assertEqual(res["currency"], "INR")
        self.assertEqual(res["exchange"], "NSE")
        self.assertEqual(res["quoteDelay"], "15_MIN_DELAYED")

    def test_yfinance_mcp_financials(self):
        res = self.yf_adapter.get_financial_statement("INFY.NS", statement="income")
        self.assertIn("financials", res)
        self.assertIn("TotalRevenue", res["financials"])
        self.assertEqual(res["currency"], "INR")

    @skip_if_live_unavailable
    def test_nse_mcp_live_quote(self):
        res = self.nse_adapter.stock_quote("HDFCBANK")
        self.assertEqual(res["symbol"], "HDFCBANK")
        self.assertIn("lastPrice", res)
        self.assertIn("totalTradedVolume", res)

    @skip_if_live_unavailable
    def test_nse_mcp_market_status(self):
        res = self.nse_adapter.market_status()
        self.assertIn("marketState", res)

    def test_alphavantage_mcp_bse_quote(self):
        res = self.alpha_adapter.global_quote("RELIANCE.BSE")
        if "Global Quote" not in res and "error" in str(res.get("structuredContent", res)):
            self.skipTest("Alpha Vantage key lacks entitlement / is rate limited")
        # Hosted server now answers with MCP content (CSV text); the legacy "Global Quote" shape is mock-only.
        if "Global Quote" in res:
            self.assertEqual(res["Global Quote"]["01. symbol"], "RELIANCE.BSE")
        else:
            self.assertIn("RELIANCE.BSE", res["content"][0]["text"])

    @skip_if_live_unavailable
    def test_reddit_mcp_posts(self):
        res = self.reddit_adapter.search_reddit(query="RELIANCE", subreddit="IndianStockMarket")
        self.assertIn("posts", res)
        self.assertGreater(len(res["posts"]), 0)


if __name__ == "__main__":
    unittest.main()
