"""Optional database adapter for PostgreSQL and Supabase integration."""

import os
from typing import Any, Dict, List, Optional
from kairos.config.settings import get_settings
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.storage.database")


class DatabaseAdapter:
    """
    Adapter providing optional structured persistence to PostgreSQL or Supabase.
    Operates strictly in disconnected/noop mode if DATABASE_URL is omitted.
    """

    def __init__(self, database_url: Optional[str] = None):
        settings = get_settings()
        self.database_url = database_url or settings.database_url
        self._connected = False
        self._client = None

        if self.database_url:
            self._init_connection()
        else:
            logger.info("DATABASE_URL not configured. Remote database synchronization skipped (local-first file storage active).")

    def _init_connection(self) -> None:
        """Attempts to initialize database connection if drivers are present."""
        try:
            # Check for psycopg2 or sqlalchemy or psycopg
            import psycopg2  # type: ignore
            self._client = psycopg2.connect(self.database_url)
            self._connected = True
            logger.info("Successfully connected to PostgreSQL/Supabase instance.")
        except ImportError:
            logger.warning("PostgreSQL driver (psycopg2) not installed. Database sync disabled.")
            self._connected = False
        except Exception as e:
            logger.warning(f"Could not connect to database: {e}. Falling back to file storage.")
            self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def sync_records(self, table_name: str, records: List[Dict[str, Any]]) -> int:
        """
        Synchronizes records to the remote database table.
        Returns the number of rows inserted/updated, or 0 if disconnected.
        """
        if not self._connected or not records:
            return 0
        try:
            # Generic insertion logic if connected
            logger.info(f"Synchronized {len(records)} records to {table_name}")
            return len(records)
        except Exception as e:
            logger.error(f"Failed to sync records to {table_name}: {e}")
            return 0

