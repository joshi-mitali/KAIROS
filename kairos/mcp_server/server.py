"""Model Context Protocol (MCP) server implementation for KAIROS data tools."""

import json
import sys
from typing import Any, Dict, Optional

from kairos.config.settings import get_settings
from kairos.mcp_server.tools import MCPToolRegistry
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.mcp_server.server")

# Define MCP tool manifests
MCP_TOOL_DEFINITIONS = [
    {
        "name": "get_historical_prices",
        "description": "Fetch validated historical OHLCV market price bars, volume, and technical indicators (SMA-20, RSI-14, MACD) for a stock ticker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol (e.g. NVDA, AAPL)"},
                "start_date": {"type": "string", "description": "Optional start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "Optional end date YYYY-MM-DD"},
                "limit": {"type": "integer", "default": 30, "description": "Max bars to return (1-252)"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "search_financial_news",
        "description": "Search financial news headlines, publisher metadata, and article URLs for a company ticker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Company ticker symbol"},
                "query": {"type": "string", "description": "Optional search keyword"},
                "limit": {"type": "integer", "default": 10, "description": "Max news articles to return"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_company_fundamentals",
        "description": "Retrieve audited SEC EDGAR corporate facts, balance sheet ratios, revenue, net income, assets, and liabilities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol (e.g. NVDA)"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_reddit_sentiment",
        "description": "Gather permitted discussion posts and community sentiment metrics across finance subreddits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Target ticker symbol"},
                "limit": {"type": "integer", "default": 10, "description": "Max posts to return"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_dataset_status",
        "description": "Check inventory of stored raw and processed datasets, manifests, and data quality reports.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Optional domain filter (market, news, reddit, fundamentals)"},
            },
        },
    },
]


class MCPServer:
    """Standard JSON-RPC 2.0 stdio Model Context Protocol (MCP) Server."""

    def __init__(self):
        self.settings = get_settings()
        self.registry = MCPToolRegistry()

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Dispatches an incoming JSON-RPC 2.0 request."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": self.settings.mcp_server_name,
                        "version": self.settings.mcp_server_version,
                    },
                },
            }

        elif method == "notifications/initialized":
            # Client handshake acknowledgment, no response required
            return None

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": MCP_TOOL_DEFINITIONS},
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            result = self._execute_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, default=str),
                        }
                    ],
                    "isError": result.get("status") == "error",
                },
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found",
                },
            }

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Maps tool names to registry methods."""
        if name in ("get_historical_prices", "get_market_data"):
            return self.registry.get_historical_prices(
                ticker=args.get("ticker", ""),
                start_date=args.get("start_date"),
                end_date=args.get("end_date"),
                limit=args.get("limit", 30),
            )
        elif name in ("search_financial_news", "get_financial_news"):
            return self.registry.search_financial_news(
                ticker=args.get("ticker", ""),
                query=args.get("query"),
                limit=args.get("limit", 10),
            )
        elif name == "get_company_fundamentals":
            return self.registry.get_company_fundamentals(
                ticker=args.get("ticker", ""),
            )
        elif name == "get_reddit_sentiment":
            return self.registry.get_reddit_sentiment(
                ticker=args.get("ticker", ""),
                limit=args.get("limit", 10),
            )
        elif name == "get_dataset_status":
            return self.registry.get_dataset_status(
                source=args.get("source"),
            )
        else:
            return {
                "status": "error",
                "error_message": f"Tool '{name}' is not recognized.",
            }

    def run_stdio(self) -> None:
        """Runs the MCP server reading from standard input and writing to standard output."""
        logger.info(f"Starting {self.settings.mcp_server_name} on stdio...")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


def start_server():
    """Entrypoint to launch the MCP server."""
    server = MCPServer()
    server.run_stdio()


if __name__ == "__main__":
    start_server()
