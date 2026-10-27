"""Typed provider adapters wrapping documented tool interfaces for selected MCP servers."""

from typing import Any, Dict, List, Optional
from kairos.mcp_client.client import MCPClientManager, get_mcp_client
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.mcp_client.adapters")


class YFinanceMCPAdapter:
    """Adapter for yfinance-mcp-server exposing 10-year Indian equity history and statements."""

    def __init__(self, client: Optional[MCPClientManager] = None):
        self.client = client or get_mcp_client()

    def get_historical_stock_prices(self, symbol: str, period: str = "10y", interval: str = "1d") -> Dict[str, Any]:
        """Calls get_historical_stock_prices tool on yfinance MCP server."""
        formatted_sym = symbol if symbol.endswith(".NS") or symbol.endswith(".BO") else f"{symbol}.NS"
        return self.client.call_tool(
            server_name="yfinance",
            tool_name="get_historical_stock_prices",
            arguments={"symbol": formatted_sym, "period": period, "interval": interval},
        )

    def get_stock_info(self, symbol: str) -> Dict[str, Any]:
        """Calls get_stock_info tool on yfinance MCP server."""
        formatted_sym = symbol if symbol.endswith(".NS") or symbol.endswith(".BO") else f"{symbol}.NS"
        return self.client.call_tool(
            server_name="yfinance",
            tool_name="get_stock_info",
            arguments={"symbol": formatted_sym},
        )

    def get_financial_statement(self, symbol: str, statement: str = "income", quarterly: bool = False) -> Dict[str, Any]:
        """Calls get_financial_statement tool on yfinance MCP server."""
        formatted_sym = symbol if symbol.endswith(".NS") or symbol.endswith(".BO") else f"{symbol}.NS"
        return self.client.call_tool(
            server_name="yfinance",
            tool_name="get_financial_statement",
            arguments={"symbol": formatted_sym, "statement": statement, "quarterly": quarterly},
        )

    def get_news(self, symbol: str) -> Dict[str, Any]:
        """Calls get_news tool on yfinance MCP server."""
        formatted_sym = symbol if symbol.endswith(".NS") or symbol.endswith(".BO") else f"{symbol}.NS"
        return self.client.call_tool(
            server_name="yfinance",
            tool_name="get_news",
            arguments={"symbol": formatted_sym},
        )


class NSEMCPAdapter:
    """Adapter for nse-mcp exposing native live NSE quotes and session status."""

    def __init__(self, client: Optional[MCPClientManager] = None):
        self.client = client or get_mcp_client()

    def stock_quote(self, symbol: str) -> Dict[str, Any]:
        """Calls stock_quote tool on nse-mcp server."""
        clean_sym = symbol.replace(".NS", "").replace(".BO", "").upper()
        return self.client.call_tool(
            server_name="nse",
            tool_name="stock_quote",
            arguments={"symbol": clean_sym},
        )

    def market_status(self) -> Dict[str, Any]:
        """Calls market_status tool on nse-mcp server."""
        return self.client.call_tool(
            server_name="nse",
            tool_name="market_status",
            arguments={},
        )

    def chart_data(self, symbol: str) -> Dict[str, Any]:
        """Calls chart_data tool on nse-mcp server."""
        clean_sym = symbol.replace(".NS", "").replace(".BO", "").upper()
        return self.client.call_tool(
            server_name="nse",
            tool_name="chart_data",
            arguments={"symbol": clean_sym},
        )


class AlphaVantageMCPAdapter:
    """Adapter for Alpha Vantage MCP server (restricted to BSE quotes)."""

    def __init__(self, client: Optional[MCPClientManager] = None):
        self.client = client or get_mcp_client()

    def global_quote(self, symbol: str) -> Dict[str, Any]:
        """Calls GLOBAL_QUOTE tool on Alpha Vantage MCP server."""
        formatted_sym = symbol if symbol.endswith(".BSE") else f"{symbol}.BSE"
        return self.client.call_tool(
            server_name="alphavantage",
            tool_name="GLOBAL_QUOTE",
            arguments={"symbol": formatted_sym},
        )

    def time_series_daily(self, symbol: str, outputsize: str = "compact") -> Dict[str, Any]:
        """Calls TIME_SERIES_DAILY tool on Alpha Vantage MCP server."""
        formatted_sym = symbol if symbol.endswith(".BSE") else f"{symbol}.BSE"
        return self.client.call_tool(
            server_name="alphavantage",
            tool_name="TIME_SERIES_DAILY",
            arguments={"symbol": formatted_sym, "outputsize": outputsize},
        )


class RedditMCPAdapter:
    """Adapter for mcp-server-reddit exposing retail Indian stock discussions."""

    def __init__(self, client: Optional[MCPClientManager] = None):
        self.client = client or get_mcp_client()

    def get_subreddit_posts(self, subreddit: str = "IndianStockMarket", limit: int = 10) -> Dict[str, Any]:
        """Calls get_subreddit_posts tool on Reddit MCP server."""
        return self.client.call_tool(
            server_name="reddit",
            tool_name="get_subreddit_posts",
            arguments={"subreddit": subreddit, "limit": limit},
        )

    def search_reddit(self, query: str, subreddit: str = "IndianStockMarket") -> Dict[str, Any]:
        """Calls search_reddit tool on Reddit MCP server."""
        return self.client.call_tool(
            server_name="reddit",
            tool_name="search_reddit",
            arguments={"query": query, "subreddit": subreddit},
        )
