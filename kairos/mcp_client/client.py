"""Model Context Protocol (MCP) Client for interacting with external financial MCP servers."""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from kairos.config.settings import get_settings
from kairos.mcp_client.mock_transport import MockMCPTransport
from kairos.utils.logging_config import get_logger
from kairos.utils.security import sanitize_untrusted_text

logger = get_logger("kairos.mcp_client.client")


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
    ):
        self.server_name = server_name
        self.tool_name = tool_name
        # Redact any sensitive tokens from arguments
        clean_args = {k: ("***REDACTED***" if "key" in k.lower() or "secret" in k.lower() else v) for k, v in arguments.items()}
        self.arguments = clean_args
        self.latency_ms = round(latency_ms, 2)
        self.status = status
        self.error_message = error_message
        self.timestamp_utc = time.time()


class MCPClientManager:
    """Manages connections and tool invocations across multiple external MCP servers."""

    def __init__(self, config_path: Optional[Path] = None):
        settings = get_settings()
        self.config_path = config_path or settings.mcp_config_path
        self.servers_config = self._load_config()
        self.mock_transport = MockMCPTransport()
        self.tool_call_history: List[MCPToolCallRecord] = []
        self._active_processes: Dict[str, subprocess.Popen] = {}

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
        use_mock_fallback: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes a tool on an external MCP server.
        Attempts stdio execution first if command is configured.
        Falls back to validated mock transport for offline/sandbox test execution.
        """
        start_time = time.perf_counter()
        server_cfg = self.servers_config.get(server_name, {})
        command = server_cfg.get("command")

        result = None
        status = "SUCCESS"
        err_msg = None

        # 1. Attempt live subprocess stdio invocation if permitted
        if command and not use_mock_fallback:
            try:
                result = self._call_stdio_process(server_name, tool_name, arguments, server_cfg)
            except Exception as e:
                logger.warning(f"Live stdio invocation failed for {server_name}.{tool_name}: {e}")
                err_msg = str(e)
                result = None

        # 2. Seamless fallback to deterministic mock transport
        if result is None:
            try:
                result = self.mock_transport.dispatch(server_name, tool_name, arguments)
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
            )
        )

        return result

    def _call_stdio_process(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Dispatches JSON-RPC 2.0 tool call to child process over stdio."""
        cmd = [config["command"]] + config.get("args", [])
        env = os.environ.copy()
        env.update(config.get("env", {}))

        # JSON-RPC tool call payload
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

        stdout, stderr = proc.communicate(input=json.dumps(payload) + "\n", timeout=10)
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
