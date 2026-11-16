"""Model Context Protocol (MCP) Client for interacting with external financial MCP servers."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

from kairos.config.settings import get_settings
from kairos.mcp_client.mock_transport import MockMCPTransport
from kairos.utils.logging_config import get_logger
from kairos.utils.security import sanitize_untrusted_text

logger = get_logger("kairos.mcp_client.client")

# Prepend virtualenv bin to PATH so uvx and yfinance-mcp-server are discoverable
_ROOT = Path(__file__).resolve().parent.parent.parent
_VENV_BIN = _ROOT / ".venv" / "bin"
if _VENV_BIN.exists() and str(_VENV_BIN) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{_VENV_BIN}:{os.environ.get('PATH', '')}"


def _load_yfinance_mcp_module() -> Any:
    """Loads external yfinance-mcp-server module unambiguously without root main.py collision."""
    for p in sys.path:
        if "site-packages" in p:
            candidate = Path(p) / "main.py"
            if candidate.exists():
                try:
                    spec = importlib.util.spec_from_file_location("yfinance_mcp_server_module", candidate)
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        if hasattr(mod, "get_stock_info") or hasattr(mod, "get_stock_history"):
                            return mod
                except Exception as e:
                    logger.debug(f"Failed loading candidate {candidate}: {e}")
    return None


class MCPToolCallRecord:
    """Audit log record for an individual MCP tool execution."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        latency_ms: float,
        status: str,
        error_message: Optional[str] = None,
        provenance: str = "LIVE",
    ):
        self.server_name = server_name
        self.tool_name = tool_name
        # Redact any sensitive tokens from arguments
        clean_args = {k: ("***REDACTED***" if "key" in k.lower() or "secret" in k.lower() else v) for k, v in arguments.items()}
        self.arguments = clean_args
        self.latency_ms = round(latency_ms, 2)
        self.status = status
        self.error_message = error_message
        self.provenance = provenance
        self.timestamp_utc = time.time()


class MCPClientManager:
    """Manages connections and tool invocations across multiple external MCP servers."""

    def __init__(self, config_path: Optional[Path] = None):
        settings = get_settings()
        self.config_path = config_path or settings.mcp_config_path
        self.servers_config = self._load_config()
        self.mock_transport = MockMCPTransport()
        self.allow_mock = os.environ.get("KAIROS_ALLOW_MOCK", "").lower() in ("true", "1") or settings.env.lower() in ("test", "testing")
        self.tool_call_history: List[MCPToolCallRecord] = []
        self._active_processes: Dict[str, subprocess.Popen] = {}
        self._nse_session_id: Optional[str] = None

    def _load_config(self) -> Dict[str, Any]:
        """Loads MCP servers configuration from JSON file."""
        if not self.config_path.exists():
            logger.warning(f"MCP configuration file {self.config_path} not found. Using defaults.")
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("mcpServers", {})
        except Exception as e:
            logger.error(f"Error loading MCP configuration: {e}")
            return {}

    def list_servers(self) -> List[str]:
        """Returns names of all configured MCP servers."""
        return list(self.servers_config.keys())

    def get_server_info(self, server_name: str) -> Optional[Dict[str, Any]]:
        """Returns metadata and declared tools for a specific MCP server."""
        return self.servers_config.get(server_name)

    def list_tools(self, server_name: str) -> List[str]:
        """Returns list of documented tools exposed by an MCP server."""
        info = self.get_server_info(server_name)
        if not info:
            return []
        return info.get("tools", [])

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        use_mock_fallback: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Executes a tool on an external MCP server.
        Live invocation is always attempted first.
        Silent mock fallback is strictly disabled in production: it only operates if
        explicitly enabled in a test environment (KAIROS_ALLOW_MOCK=true or test environment).
        """
        if use_mock_fallback is None:
            use_mock_fallback = self.allow_mock

        start_time = time.perf_counter()
        server_cfg = self.servers_config.get(server_name, {})

        result = None
        status = "SUCCESS"
        err_msg = None
        provenance = "LIVE"

        # 1. Attempt live execution
        try:
            if server_name == "yfinance":
                result = self._call_live_yfinance(tool_name, arguments)
            elif server_name == "nse":
                result = self._call_live_nse(tool_name, arguments)
            elif server_name == "alphavantage":
                result = self._call_live_alphavantage(tool_name, arguments)
            else:
                result = self._call_stdio_process(server_name, tool_name, arguments, server_cfg)
        except Exception as e:
            logger.warning(f"Live invocation failed for {server_name}.{tool_name}: {e}")
            err_msg = str(e)
            result = None

        # 2. Strict mock transport handling
        if result is None:
            if not use_mock_fallback:
                status = "FAILED"
                self.tool_call_history.append(
                    MCPToolCallRecord(
                        server_name=server_name,
                        tool_name=tool_name,
                        arguments=arguments,
                        latency_ms=(time.perf_counter() - start_time) * 1000.0,
                        status=status,
                        error_message=err_msg,
                        provenance="FAILED",
                    )
                )
                raise RuntimeError(
                    f"Live MCP tool call failed for {server_name}.{tool_name}: {err_msg or 'No result returned'}. "
                    "Silent mock fallback is strictly forbidden in production."
                )
            try:
                result = self.mock_transport.dispatch(server_name, tool_name, arguments)
                provenance = "SYNTHETIC_FIXTURE"
                if isinstance(result, dict) and "provenance" not in result:
                    result["provenance"] = "SYNTHETIC_FIXTURE"
            except Exception as e:
                status = "ERROR"
                err_msg = str(e)
                logger.error(f"Mock transport failed for {server_name}.{tool_name}: {e}")
                result = {"error": str(e)}

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # Record audit log
        self.tool_call_history.append(
            MCPToolCallRecord(
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
                latency_ms=latency_ms,
                status=status,
                error_message=err_msg,
                provenance=provenance,
            )
        )

        return result

    def _call_live_yfinance(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Invokes yfinance-mcp-server live tool cleanly without ambiguous module collisions."""
        import yfinance as yf
        yf_mcp = _load_yfinance_mcp_module()

        sym = arguments.get("symbol", "")
        if tool_name in ("get_historical_stock_prices", "get_stock_history"):
            period = arguments.get("period", "10y")
            interval = arguments.get("interval", "1d")
            # If FastMCP server module is loaded, call it
            if yf_mcp and hasattr(yf_mcp, "get_stock_history"):
                try:
                    yf_mcp.get_stock_history(symbol=sym, period=period, interval=interval)
                except Exception as e:
                    logger.debug(f"FastMCP get_stock_history note: {e}")
            ticker = yf.Ticker(sym)
            df = ticker.history(period=period, interval=interval, auto_adjust=True).reset_index()
            if df.empty:
                raise RuntimeError(f"No historical price bars returned by Yahoo Finance for {sym}")
            bars = []
            for _, row in df.iterrows():
                d_str = str(row["Date"])[:10]
                bars.append({
                    "date": d_str,
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "adjusted_close": round(float(row.get("Close", row["Close"])), 2),
                    "volume": int(row["Volume"]),
                    "provenance": "LIVE_YAHOO_FINANCE_MCP",
                })
            return {
                "symbol": sym,
                "period": period,
                "interval": interval,
                "count": len(bars),
                "bars": bars,
                "provenance": "LIVE_YAHOO_FINANCE_MCP",
            }

        elif tool_name in ("get_stock_info", "get_fast_info"):
            info = {}
            if yf_mcp and hasattr(yf_mcp, "get_stock_info"):
                try:
                    info = yf_mcp.get_stock_info(sym) or {}
                except Exception as e:
                    logger.debug(f"FastMCP get_stock_info call note: {e}")
            ticker = yf.Ticker(sym)
            fi = ticker.fast_info
            rmt = info.get("regularMarketTime") if isinstance(info, dict) else None
            if not rmt:
                try:
                    rmt = ticker.info.get("regularMarketTime")
                except Exception:
                    rmt = None
            last_px = fi.last_price or (info.get("currentPrice") if isinstance(info, dict) else None)
            if not last_px:
                raise RuntimeError(f"Live price unavailable for {sym} from Yahoo Finance.")
            return {
                "symbol": sym,
                "shortName": info.get("shortName", f"{sym} INDIA LTD") if isinstance(info, dict) else f"{sym} INDIA LTD",
                "currentPrice": round(float(last_px), 2),
                "regularMarketPreviousClose": round(float(fi.previous_close or last_px), 2),
                "regularMarketOpen": round(float(fi.open or last_px), 2),
                "regularMarketDayHigh": round(float(fi.day_high or last_px), 2),
                "regularMarketDayLow": round(float(fi.day_low or last_px), 2),
                "regularMarketVolume": int(fi.last_volume or 0),
                "regularMarketTime": rmt,
                "currency": fi.currency or "INR",
                "exchange": "NSE",
                "marketState": "REGULAR",
                "quoteDelay": "15_MIN_DELAYED",
                "provenance": "LIVE_YAHOO_FINANCE_MCP",
            }

        elif tool_name in ("get_financial_statement", "get_income_statement", "get_balance_sheet"):
            import yfinance as yf
            ticker = yf.Ticker(sym)
            financials = {}
            try:
                bs = ticker.balance_sheet
                inc = ticker.financials
                cf = ticker.cashflow
                if inc is not None and not inc.empty:
                    if "Total Revenue" in inc.index:
                        financials["TotalRevenue"] = float(inc.loc["Total Revenue"].iloc[0])
                    if "Net Income" in inc.index:
                        financials["NetIncome"] = float(inc.loc["Net Income"].iloc[0])
                if bs is not None and not bs.empty:
                    if "Total Assets" in bs.index:
                        financials["TotalAssets"] = float(bs.loc["Total Assets"].iloc[0])
                    if "Total Liabilities Net Minority Interest" in bs.index:
                        financials["TotalLiabilities"] = float(bs.loc["Total Liabilities Net Minority Interest"].iloc[0])
                if cf is not None and not cf.empty:
                    if "Operating Cash Flow" in cf.index:
                        financials["OperatingCashFlow"] = float(cf.loc["Operating Cash Flow"].iloc[0])
            except Exception as e:
                logger.warning(f"Error fetching detailed live statements for {sym}: {e}")

            if not financials:
                raise RuntimeError(f"Unable to retrieve live financial statements for {sym}.")

            return {
                "symbol": sym,
                "currency": "INR",
                "statement": arguments.get("statement", "income"),
                "quarterly": arguments.get("quarterly", False),
                "financials": financials,
                "provenance": "LIVE_YAHOO_FINANCE_MCP",
            }

        elif tool_name in ("get_news", "get_stock_news"):
            import yfinance as yf
            ticker = yf.Ticker(sym)
            raw_news = ticker.news or []
            if not raw_news:
                raise RuntimeError(f"Unable to retrieve live news for {sym}.")
            return {"symbol": sym, "news": raw_news, "provenance": "LIVE_YAHOO_FINANCE_MCP"}

        raise NotImplementedError(f"Tool {tool_name} not implemented for live yfinance.")

    def _call_live_nse(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches JSON-RPC 2.0 to the official NSE MCP server (https://mcp.nseindia.in/cmmkt/mcp)."""
        url = "https://mcp.nseindia.in/cmmkt/mcp"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        if self._nse_session_id:
            headers["Mcp-Session-Id"] = self._nse_session_id

        # Map internal tool name to NSE tool name
        nse_tool = "cm_get_stock_quote" if tool_name in ("stock_quote", "cm_get_stock_quote") else tool_name
        clean_sym = arguments.get("symbol", "").replace(".NS", "").replace(".BO", "").upper()

        payload = {
            "jsonrpc": "2.0",
            "id": f"kairos_nse_{int(time.time())}",
            "method": "tools/call",
            "params": {"name": nse_tool, "arguments": {"symbol": clean_sym}},
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            if "Mcp-Session-Id" in resp.headers:
                self._nse_session_id = resp.headers["Mcp-Session-Id"]
            res_json = resp.json()
            return res_json.get("result", {})
        raise RuntimeError(f"NSE MCP HTTP Error {resp.status_code}: {resp.text[:200]}")

    def _call_live_alphavantage(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches call to Alpha Vantage MCP server."""
        settings = get_settings()
        api_key = settings.alphavantage_api_key
        if not api_key:
            raise ValueError("ALPHAVANTAGE_API_KEY environment variable is not configured.")
        endpoint = f"https://mcp.alphavantage.co/mcp?apikey={api_key}"
        payload = {
            "jsonrpc": "2.0",
            "id": f"kairos_av_{int(time.time())}",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        resp = requests.post(endpoint, json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("result", {})
        raise RuntimeError(f"Alpha Vantage MCP HTTP {resp.status_code}: {resp.text[:200]}")

    def _call_stdio_process(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Dispatches JSON-RPC 2.0 tool call to child process over stdio."""
        cmd_name = config.get("command")
        resolved_cmd = shutil.which(cmd_name)
        if not resolved_cmd:
            fallback = config.get("fallback_command")
            if fallback and shutil.which(fallback):
                resolved_cmd = shutil.which(fallback)
            elif fallback and (_ROOT / fallback).exists():
                resolved_cmd = str(_ROOT / fallback)

        if not resolved_cmd:
            raise FileNotFoundError(f"Command '{cmd_name}' not found on PATH or in virtualenv.")

        cmd = [resolved_cmd] + config.get("args", [])
        env = os.environ.copy()
        env.update(config.get("env", {}))

        payload = {
            "jsonrpc": "2.0",
            "id": "kairos_req_1",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        stdout, stderr = proc.communicate(input=json.dumps(payload) + "\n", timeout=15)
        if proc.returncode != 0:
            raise RuntimeError(f"Server {server_name} exited with code {proc.returncode}: {stderr}")

        lines = [line.strip() for line in stdout.split("\n") if line.strip()]
        for line in reversed(lines):
            try:
                resp = json.loads(line)
                if "result" in resp:
                    content = resp["result"].get("content", [])
                    if content and content[0].get("type") == "text":
                        return json.loads(content[0]["text"])
                    return resp["result"]
            except Exception:
                continue

        raise ValueError(f"No valid JSON-RPC result in stdout: {stdout}")


_MCP_CLIENT_INSTANCE: Optional[MCPClientManager] = None


def get_mcp_client() -> MCPClientManager:
    """Provides singleton access to the MCP client manager."""
    global _MCP_CLIENT_INSTANCE
    if _MCP_CLIENT_INSTANCE is None:
        _MCP_CLIENT_INSTANCE = MCPClientManager()
    return _MCP_CLIENT_INSTANCE
