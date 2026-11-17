import os

import pytest

# Several modules call load_dotenv() at import; it never overrides an existing variable,
# so pinning these to empty keeps the real database in .env out of the test suite.
os.environ["DATABASE_URL"] = ""
os.environ["KAIROS_DB_SCHEMA"] = ""


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch):
    """Postgres tests opt in via KAIROS_TEST_DATABASE_URL (a throwaway schema)."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("KAIROS_DB_SCHEMA", "")
