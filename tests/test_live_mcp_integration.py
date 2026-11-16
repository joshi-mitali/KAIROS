"""
Live integration tests for existing MCP servers.
Explicitly distinguishes real network & child-process calls from mock transport.
Does NOT fabricate successful network responses if network is restricted.
"""

import json
import shutil
import socket
import subprocess
import unittest
from pathlib import Path

from kairos.config.settings import get_settings
from kairos.mcp_client.client import get_mcp_client
from kairos.verification import live_mcp  # module import: its test_* helpers must not be collected as tests

_ROOT = Path(__file__).resolve().parent.parent
_VENV_BIN = _ROOT / ".venv" / "bin"


class TestLiveMCPIntegration(unittest.TestCase):
    """
    Live integration tests that probe real environments, binaries, and networks.
    Explicitly reports environment prerequisites and does NOT mock responses.
    """

    def setUp(self):
        self.settings = get_settings()
        self.client = get_mcp_client()

    def test_live_mcp_configuration_loaded(self):
        """Verifies external MCP configuration file is parsed correctly."""
        servers = self.client.list_servers()
        self.assertIn("yfinance", servers)
        self.assertIn("nse", servers)
        self.assertIn("alphavantage", servers)
        self.assertIn("reddit", servers)

    def test_yfinance_fastmcp_stdio_jsonrpc(self):
        """
        Executes a genuine JSON-RPC 2.0 handshake over stdio with the installed
        FastMCP yfinance-mcp-server child process.
        """
        binary = _VENV_BIN / "yfinance-mcp-server"
        if not binary.exists():
            binary_which = shutil.which("yfinance-mcp-server")
            if binary_which:
                binary = Path(binary_which)
            else:
                self.skipTest("yfinance-mcp-server binary not found on PATH or in .venv")

        try:
            p = subprocess.Popen(
                [str(binary)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as e:  # e.g. venv copied from another machine: shebang interpreter missing
            self.skipTest(f"yfinance-mcp-server is not executable here: {e}")
        try:
            # 1. Initialize
            init_req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "kairos-audit", "version": "1.0"},
                },
            }
            p.stdin.write(json.dumps(init_req) + "\n")
            p.stdin.flush()
            init_line = p.stdout.readline()
            self.assertTrue(init_line, "No response from FastMCP server on initialize")
            init_res = json.loads(init_line)
            self.assertEqual(init_res["id"], 1)
            self.assertEqual(init_res["result"]["serverInfo"]["name"], "yfinance-server")
            self.assertEqual(init_res["result"]["protocolVersion"], "2024-11-05")

            # 2. Initialized Notification
            notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            p.stdin.write(json.dumps(notif) + "\n")
            p.stdin.flush()

            # 3. tools/list
            tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            p.stdin.write(json.dumps(tools_req) + "\n")
            p.stdin.flush()
            tools_line = p.stdout.readline()
            self.assertTrue(tools_line, "No response from FastMCP server on tools/list")
            tools_res = json.loads(tools_line)
            self.assertEqual(tools_res["id"], 2)
            tool_names = [t["name"] for t in tools_res["result"]["tools"]]
            self.assertIn("get_stock_info", tool_names)
            self.assertIn("get_stock_history", tool_names)
            self.assertIn("get_income_statement", tool_names)
            self.assertGreaterEqual(len(tool_names), 8)
        finally:
            p.terminate()
            try:
                p.wait(timeout=2)
            except Exception:
                p.kill()
            if p.stdin:
                p.stdin.close()
            if p.stdout:
                p.stdout.close()
            if p.stderr:
                p.stderr.close()

    def test_live_network_yfinance_quote(self):
        """
        Executes a real live network call to yfinance.
        If running inside a sandboxed environment without network, explicitly skips.
        """
        try:
            socket.gethostbyname("query1.finance.yahoo.com")
        except socket.gaierror:
            self.skipTest("Sandbox isolation active; external network is blocked.")

        import yfinance as yf
        t = yf.Ticker("RELIANCE.NS")
        price = t.fast_info.last_price
        self.assertIsNotNone(price)
        self.assertGreater(price, 0.0)

    def test_live_network_nse_mcp_probe(self):
        """
        Probes official NSE MCP endpoint (https://mcp.nseindia.in/cmmkt/mcp).
        If running inside a sandboxed environment without network, explicitly skips.
        """
        try:
            socket.gethostbyname("mcp.nseindia.in")
        except socket.gaierror:
            self.skipTest("Sandbox isolation active; external DNS is blocked.")

        res = live_mcp.test_live_nse_mcp()
        self.assertEqual(res["server"], "nse")
        # In live network: server reaches Akamai edge (HTTP 200 or 400 depending on session)
        self.assertIn(res["status"], ["CONNECTED", "GATEWAY_THROTTLED", "HTTP_400", "HTTP_None"])

    def test_alphavantage_credentials_requirement(self):
        """Audits Alpha Vantage configuration and asserts missing credentials warning."""
        # Explicit empty key: the real .env may hold a valid key, which is not what this test audits.
        res = live_mcp.test_live_alphavantage_mcp("")
        self.assertEqual(res["server"], "alphavantage")
        self.assertEqual(res["status"], "MISSING_CREDENTIALS")
        self.assertIn("ALPHAVANTAGE_API_KEY", res["error"])

    def test_reddit_credentials_requirement(self):
        """Audits Reddit credentials configuration and asserts missing credentials warning."""
        res = live_mcp.test_live_reddit_mcp(
            self.settings.reddit_client_id or "", self.settings.reddit_client_secret or ""
        )
        self.assertEqual(res["server"], "reddit")
        self.assertEqual(res["status"], "MISSING_CREDENTIALS")
        self.assertIn("REDDIT_CLIENT_ID", res["error"])


if __name__ == "__main__":
    unittest.main()
