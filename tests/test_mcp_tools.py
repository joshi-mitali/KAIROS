"""Unit tests for Model Context Protocol (MCP) tools and server."""

import json
import unittest

from kairos.mcp_server.server import MCPServer
from kairos.mcp_server.tools import MCPToolRegistry


class TestMCPTools(unittest.TestCase):

    def setUp(self):
        self.registry = MCPToolRegistry()
        self.server = MCPServer()

    def test_get_historical_prices_tool(self):
        res = self.registry.get_historical_prices("NVDA", limit=5)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ticker"], "NVDA")
        self.assertLessEqual(len(res["records"]), 5)
        self.assertIn("indicators", res)

    def test_get_historical_prices_invalid_ticker(self):
        res = self.registry.get_historical_prices("BAD;;TICKER")
        self.assertEqual(res["status"], "error")
        self.assertIn("error_message", res)

    def test_search_financial_news_tool(self):
        res = self.registry.search_financial_news("AAPL", limit=3)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ticker"], "AAPL")
        self.assertLessEqual(len(res["articles"]), 3)

    def test_get_company_fundamentals_tool(self):
        res = self.registry.get_company_fundamentals("MSFT")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ticker"], "MSFT")
        self.assertIn("ratios", res)

    def test_get_reddit_sentiment_tool(self):
        res = self.registry.get_reddit_sentiment("NVDA", limit=5)
        self.assertEqual(res["status"], "success")
        self.assertGreater(len(res["posts"]), 0)

    def test_get_dataset_status_tool(self):
        res = self.registry.get_dataset_status()
        self.assertEqual(res["status"], "success")
        self.assertIn("domains", res)

    def test_mcp_server_initialize(self):
        req = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "initialize",
            "params": {},
        }
        resp = self.server.handle_request(req)
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], "1")
        self.assertIn("serverInfo", resp["result"])

    def test_mcp_server_tools_list(self):
        req = {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/list",
            "params": {},
        }
        resp = self.server.handle_request(req)
        tools = resp["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("get_historical_prices", tool_names)
        self.assertIn("search_financial_news", tool_names)
        self.assertIn("get_company_fundamentals", tool_names)

    def test_mcp_server_tools_call(self):
        req = {
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {
                "name": "get_historical_prices",
                "arguments": {"ticker": "NVDA", "limit": 2},
            },
        }
        resp = self.server.handle_request(req)
        self.assertEqual(resp["jsonrpc"], "2.0")
        content = resp["result"]["content"][0]["text"]
        data = json.loads(content)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["ticker"], "NVDA")


if __name__ == "__main__":
    unittest.main()
