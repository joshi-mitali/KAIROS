"""One small SQL helper: Postgres (Supabase) when DATABASE_URL is set, otherwise a local SQLite file.

SQL is written once with `?` placeholders; the Postgres side translates them to `%s`.
Postgres connections come from a small thread-safe pool, are pinged after idling and discarded when broken.
"""
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

POOL_MAX = 4  # Supabase free tier allows few connections
IDLE_PING_S = 20


class Database:
    def __init__(self, path, url=None, schema=None):
        url = (os.environ.get("DATABASE_URL", "") if url is None else url).strip()
        self.path, self.postgres, self.pool = path, bool(url), None
        if not url:
            path.parent.mkdir(parents=True, exist_ok=True)
            return
        from psycopg2.pool import ThreadedConnectionPool
        schema = schema or os.environ.get("KAIROS_DB_SCHEMA")
        opts = "-c statement_timeout=30000" + (f" -c search_path={schema},public" if schema else "")
        kw = {} if "sslmode" in url else {"sslmode": "require"}
        self.idle = {}  # connection id -> last used (monotonic)
        self.lock = threading.Lock()
        # Connects eagerly: an unreachable database fails here, at startup, with a clear error.
        try:
            self.pool = ThreadedConnectionPool(1, POOL_MAX, url, connect_timeout=10, options=opts,
                                               keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3, **kw)
        except Exception as exc:
            # Paper-order approvals must be durable, so never fall back to a disk that a restart wipes.
            raise RuntimeError(f"DATABASE_URL is set but the database is unreachable ({type(exc).__name__}). "
                               "Fix the connection or unset DATABASE_URL to use local SQLite.") from None

    def _checkout(self):
        conn = self.pool.getconn()
        last = self.idle.get(id(conn), 0)
        if conn.closed or time.monotonic() - last > IDLE_PING_S:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                conn.commit()
            except Exception:
                self.pool.putconn(conn, close=True)
                conn = self.pool.getconn()
        return conn

    @contextmanager
    def tx(self, lock=None):
        """Yield q(sql, params) -> list of dict rows, all in one transaction. `lock` serialises writers on that integer key."""
        if not self.postgres:
            conn = sqlite3.connect(self.path, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                if lock:
                    conn.execute("BEGIN IMMEDIATE")
                yield lambda sql, params=(): [dict(r) for r in conn.execute(sql, params).fetchall()]
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
            return
        from psycopg2.extras import RealDictCursor
        conn = self._checkout()
        broken = False
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if lock:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))

                def q(sql, params=()):
                    cur.execute(sql.replace("?", "%s"), params)
                    return [dict(r) for r in cur.fetchall()] if cur.description else []
                yield q
            conn.commit()
        except BaseException as exc:
            broken = conn.closed or type(exc).__module__.startswith("psycopg2") and "Operational" in type(exc).__name__
            if not conn.closed:
                conn.rollback()
            raise
        finally:
            self.idle[id(conn)] = time.monotonic()
            self.pool.putconn(conn, close=broken)

    def query(self, sql, params=()):
        """Run one statement in its own transaction; a dropped Postgres connection is retried once."""
        for attempt in (0, 1):
            try:
                with self.tx() as q:
                    return q(sql, params)
            except Exception as exc:
                if not (self.postgres and attempt == 0 and type(exc).__module__.startswith("psycopg2")
                        and type(exc).__name__ in ("OperationalError", "InterfaceError")):
                    raise

    def migrate(self, sqlite_ddl, postgres_ddl):
        """Create tables; Postgres tables get Row Level Security with no policies, so Supabase's anon/REST roles see nothing."""
        with self.tx() as q:
            if not self.postgres:
                for stmt in sqlite_ddl:
                    q(stmt)
                return
            q("SELECT pg_advisory_xact_lock(7419)")  # concurrent starts (deploy overlap) must not race on DDL
            for stmt in postgres_ddl:
                q(stmt)
                if stmt.lstrip().upper().startswith("CREATE TABLE IF NOT EXISTS"):
                    table = stmt.split()[5]
                    q(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    def setting(self, key, make):
        """Durable key/value (kairos_settings); `make()` supplies the value the first time. Postgres only."""
        self.migrate([], ["CREATE TABLE IF NOT EXISTS kairos_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"])
        self.query("INSERT INTO kairos_settings(key,value) VALUES(?,?) ON CONFLICT (key) DO NOTHING", (key, make()))
        return self.query("SELECT value FROM kairos_settings WHERE key=?", (key,))[0]["value"]
