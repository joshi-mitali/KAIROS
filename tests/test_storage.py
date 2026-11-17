"""Store layer: SQLite always; real Postgres only when KAIROS_TEST_DATABASE_URL is set (uses a throwaway schema)."""
import json
import os
import uuid
from unittest.mock import MagicMock

import pandas as pd
import pytest

from kairos.storage.db import Database
from kairos.web.runs import RunStore

PG_URL = os.environ.get("KAIROS_TEST_DATABASE_URL")


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(not PG_URL, reason="KAIROS_TEST_DATABASE_URL not set"))])
def store(request, tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    schema = None
    if request.param == "postgres":
        import psycopg2
        schema = "kairos_test_" + uuid.uuid4().hex[:8]
        admin = psycopg2.connect(PG_URL, connect_timeout=10, sslmode="require")
        admin.autocommit = True
        admin.cursor().execute(f"CREATE SCHEMA {schema}")
        monkeypatch.setenv("KAIROS_DB_SCHEMA", schema)
    s = RunStore(tmp_path / "runs.db", tmp_path, url=PG_URL if schema else None)
    s.worker.submit = MagicMock()
    yield s
    if schema:
        s.db.pool.closeall()
        admin.cursor().execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()


def test_run_lifecycle_events_and_single_active_run(store):
    run_id = store.create("o", "RELIANCE", "NEUTRAL", "live")
    with pytest.raises(ValueError):
        store.create("o", "TCS", "NEUTRAL", "live")
    store.emit(run_id, "run-started", {"x": 1})
    events = store.events(run_id)
    assert [e["type"] for e in events] == ["run-queued", "run-started"]
    assert store.events(run_id, events[0]["id"])[0]["payload"] == {"x": 1}
    assert store.status(run_id) == "QUEUED" and store.get(run_id, "other") is None
    assert store.get(run_id, "o")["ticker"] == "RELIANCE"
    assert store.list("o")[0]["id"] == run_id


def test_evidence_roundtrip_through_database(store):
    if not store.db.postgres:
        store.save_evidence("r")  # no-op on SQLite: files already live on disk
        assert not store.evidence_dir("r").exists()
        return
    root = store.evidence_dir("r1")
    (root / "processed" / "news").mkdir(parents=True)
    pd.DataFrame([{"title": "a", "when": pd.Timestamp("2026-01-02")}]).to_parquet(root / "processed" / "news" / "x_news.parquet")
    (root / "provenance.json").write_text(json.dumps({"sources": {}}))
    store.save_evidence("r1")
    import shutil
    shutil.rmtree(root)
    store.restore_evidence("r1")
    assert pd.read_parquet(root / "processed" / "news" / "x_news.parquet").title.tolist() == ["a"]
    assert json.loads((root / "provenance.json").read_text()) == {"sources": {}}


def test_rls_enabled_on_every_table(store):
    if not store.db.postgres:
        pytest.skip("Postgres only")
    rows = store.db.query("SELECT relname, relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND relkind='r'")
    assert rows and all(r["relrowsecurity"] for r in rows)


def test_postgres_path_translates_placeholders_and_enables_rls(tmp_path, monkeypatch):
    """Mocked cursor/pool: checks the SQL the Postgres side sends, without a server."""
    sent = []
    cur = MagicMock(description=None)
    cur.execute.side_effect = lambda sql, params=None: sent.append((sql, params))
    cur.__enter__.return_value = cur
    conn = MagicMock(closed=False)
    conn.cursor.return_value = cur
    db = Database.__new__(Database)
    db.path, db.postgres, db.idle, db.pool = tmp_path, True, {}, MagicMock(getconn=lambda: conn)
    db.query("SELECT 1 FROM t WHERE a=? AND b=?", (1, 2))
    assert ("SELECT 1 FROM t WHERE a=%s AND b=%s", (1, 2)) in sent
    sent.clear()
    db.migrate([], ["CREATE TABLE IF NOT EXISTS foo (id TEXT)"])
    assert any(sql == "ALTER TABLE foo ENABLE ROW LEVEL SECURITY" for sql, _ in sent)
    db.pool.putconn.assert_called()


def test_unreachable_database_fails_clearly_at_startup(tmp_path):
    with pytest.raises(RuntimeError, match="unreachable"):
        Database(tmp_path / "x.db", "postgresql://u:p@127.0.0.1:9/db")
