"""FastMCP server wrapping all 4 collectors for KAIROS market data."""

import json
from kairos.mcp_server.server import MCPServer
from kairos.mcp_server.tools import MCPToolRegistry

registry = MCPToolRegistry()

# Standard callable functions returning structured JSON strings
def get_market_data(ticker: str) -> str:
    """Fetch validated historical OHLCV bars and technical indicators."""
    res = registry.get_historical_prices(ticker=ticker)
    return json.dumps(res, indent=2, default=str)


def get_reddit_sentiment(ticker: str) -> str:
    """Fetch permitted Reddit sentiment and posts."""
    res = registry.get_reddit_sentiment(ticker=ticker)
    return json.dumps(res, indent=2, default=str)


def get_financial_news(ticker: str) -> str:
    """Fetch financial news articles and metadata."""
    res = registry.search_financial_news(ticker=ticker)
    return json.dumps(res, indent=2, default=str)


def get_company_fundamentals(ticker: str) -> str:
    """Fetch verified balance sheet ratios and corporate facts."""
    res = registry.get_company_fundamentals(ticker=ticker)
    return json.dumps(res, indent=2, default=str)


# Try to initialize FastMCP if available
try:
    from fastmcp import FastMCP
    mcp = FastMCP("KAIROS-Market-Data-MCP")
    mcp.tool()(get_market_data)
    mcp.tool()(get_reddit_sentiment)
    mcp.tool()(get_financial_news)
    mcp.tool()(get_company_fundamentals)
except ImportError:
    mcp = None


if __name__ == "__main__":
    if mcp is not None:
        mcp.run()
    else:
        server = MCPServer()
        server.run_stdio()
