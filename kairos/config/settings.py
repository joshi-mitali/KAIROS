"""Centralized configuration and environment settings for KAIROS."""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _load_env_file(filepath: Path) -> None:
    """Lightweight .env parser fallback without requiring external packages."""
    if not filepath.exists():
        return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


class Settings:
    """Application settings with immutable defaults and runtime environment overrides."""

    def __init__(self) -> None:
        # Load .env if present in root
        root_env = Path(".env")
        if root_env.exists():
            _load_env_file(root_env)

        self.env: str = os.environ.get("KAIROS_ENV", "development")
        self.log_level: str = os.environ.get("LOG_LEVEL", "INFO")
        
        # Paths
        base_data = Path(os.environ.get("KAIROS_DATA_DIR", "data"))
        self.data_dir: Path = base_data
        self.raw_data_dir: Path = base_data / "raw"
        self.processed_data_dir: Path = base_data / "processed"
        self.manifests_dir: Path = base_data / "manifests"
        self.reports_dir: Path = base_data / "reports"

        # Unique Execution Run ID
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.run_id: str = os.environ.get("KAIROS_RUN_ID", f"run_{ts}_{uuid.uuid4().hex[:6]}")

        # SEC EDGAR Requirements
        self.sec_user_agent: str = os.environ.get(
            "SEC_EDGAR_USER_AGENT",
            "KAIROS-Institutional-Trader research@kairos-trader.edu"
        )

        # Reddit Connector Settings
        self.reddit_authorized: bool = os.environ.get("REDDIT_AUTHORIZED", "false").lower() in ("true", "1", "yes")
        self.reddit_client_id: Optional[str] = os.environ.get("REDDIT_CLIENT_ID") or None
        self.reddit_client_secret: Optional[str] = os.environ.get("REDDIT_CLIENT_SECRET") or None
        self.reddit_user_agent: str = os.environ.get(
            "REDDIT_USER_AGENT",
            "Mozilla/5.0 (compatible; KAIROS-Trader-Audit/1.0)"
        )

        # News Providers
        self.news_provider: str = os.environ.get("NEWS_PROVIDER", "gdelt").lower()
        self.finnhub_api_key: Optional[str] = os.environ.get("FINNHUB_API_KEY") or None

        # Storage & Database (Optional Supabase / Postgres)
        self.database_url: Optional[str] = os.environ.get("DATABASE_URL") or None

        # MCP Server Defaults
        self.mcp_server_name: str = os.environ.get("MCP_SERVER_NAME", "KAIROS-Market-Data-MCP")
        self.mcp_server_version: str = os.environ.get("MCP_SERVER_VERSION", "1.0.0")

        # Request Timeouts & Bounds
        self.request_timeout_seconds: int = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "15"))
        self.max_retries: int = int(os.environ.get("MAX_RETRIES", "3"))

    def ensure_directories(self) -> None:
        """Ensures all standard data directories exist on disk."""
        for d in [
            self.raw_data_dir / "market",
            self.raw_data_dir / "reddit",
            self.raw_data_dir / "news",
            self.raw_data_dir / "fundamentals",
            self.processed_data_dir / "market",
            self.processed_data_dir / "reddit",
            self.processed_data_dir / "news",
            self.processed_data_dir / "fundamentals",
            self.manifests_dir,
            self.reports_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


_SETTINGS_INSTANCE: Optional[Settings] = None


def get_settings() -> Settings:
    """Provides a singleton instance of application settings."""
    global _SETTINGS_INSTANCE
    if _SETTINGS_INSTANCE is None:
        _SETTINGS_INSTANCE = Settings()
        _SETTINGS_INSTANCE.ensure_directories()
    return _SETTINGS_INSTANCE
