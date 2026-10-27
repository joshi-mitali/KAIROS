"""Centralized configuration and environment settings for KAIROS Indian stock market pipeline."""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


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
    """Application settings for Indian equities ingestion via existing MCP servers."""

    def __init__(self) -> None:
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

        # Target Equities Scope (Configurable NSE tickers)
        default_tickers = "RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK"
        raw_tickers = os.environ.get("KAIROS_TARGET_TICKERS", default_tickers)
        self.target_tickers: List[str] = [t.strip().upper() for t in raw_tickers.split(",") if t.strip()]

        # Target Historical Years (10 years default)
        self.historical_years_target: int = int(os.environ.get("KAIROS_HISTORY_YEARS", "10"))

        # MCP Configuration Path
        self.mcp_config_path: Path = Path(os.environ.get("KAIROS_MCP_CONFIG", "config/mcp_servers.json"))

        # Alpha Vantage Credentials
        self.alphavantage_api_key: Optional[str] = os.environ.get("ALPHAVANTAGE_API_KEY") or None

        # Reddit Credentials & Configuration
        self.reddit_client_id: Optional[str] = os.environ.get("REDDIT_CLIENT_ID") or None
        self.reddit_client_secret: Optional[str] = os.environ.get("REDDIT_CLIENT_SECRET") or None
        self.reddit_authorized: bool = bool(self.reddit_client_id and self.reddit_client_secret)
        self.reddit_subreddits: List[str] = ["IndianStockMarket", "IndiaInvestments", "dalalstreetbets"]

        # Storage & Database (Optional Supabase / Postgres)
        self.database_url: Optional[str] = os.environ.get("DATABASE_URL") or None

        # Request Timeouts & Bounds
        self.request_timeout_seconds: int = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "15"))
        self.max_retries: int = int(os.environ.get("MAX_RETRIES", "3"))

    def ensure_directories(self) -> None:
        """Ensures all standard data directories exist on disk."""
        for d in [
            self.raw_data_dir / "market",
            self.raw_data_dir / "live",
            self.raw_data_dir / "reddit",
            self.raw_data_dir / "news",
            self.raw_data_dir / "fundamentals",
            self.processed_data_dir / "market",
            self.processed_data_dir / "live",
            self.processed_data_dir / "reddit",
            self.processed_data_dir / "news",
            self.processed_data_dir / "fundamentals",
            self.manifests_dir,
            self.reports_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


_SETTINGS_INSTANCE: Optional[Settings] = None


def get_settings() -> Settings:
    """Provides singleton access to application settings."""
    global _SETTINGS_INSTANCE
    if _SETTINGS_INSTANCE is None:
        _SETTINGS_INSTANCE = Settings()
        _SETTINGS_INSTANCE.ensure_directories()
    return _SETTINGS_INSTANCE
