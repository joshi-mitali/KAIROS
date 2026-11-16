"""Persistent storage backends and manager for KAIROS Memory MCP.
Implements PostgreSQL + pgvector storage alongside local-first SQLite + Vector search fallback.
"""

import json
import math
import os
import sqlite3
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from kairos.config.settings import get_settings
from kairos.memory.models import (
    MemoryRecord,
    MemorySearchResult,
    RecordType,
    TradeOutcome,
)
from kairos.memory.recency import (
    calculate_composite_score,
    calculate_recency_weight,
    calculate_relevance_score,
)
from kairos.observability.langfuse_tracing import traced
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.memory.storage")
_DEMO_SEED_IDS = frozenset({
    "trade_tcs_20261016", "trade_reliance_20261006", "prop_infy_20261008",
    "trade_hdfc_20260906", "trade_icici_20260821", "trade_infy_20260421", "trade_reliance_20260302",
})


def _generate_synthetic_vector(text: str, dim: int = 16) -> List[float]:
    """Generates a deterministic normalized pseudo-embedding for text
    when external embedding APIs are offline or in test environments.
    """
    vec = [0.0] * dim
    clean = text.lower()
    for idx, char in enumerate(clean):
        bucket = (ord(char) * 31 + idx) % dim
        vec[bucket] += 1.0

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 1e-6:
        vec = [round(v / norm, 5) for v in vec]
    else:
        vec[0] = 1.0
    return vec


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 < 1e-6 or norm2 < 1e-6:
        return 0.0
    return max(0.0, min(1.0, dot / (norm1 * norm2)))


class BaseMemoryBackend(ABC):
    """Abstract interface for KAIROS persistent memory backends."""

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the backend is actively connected and ready."""
        pass

    @abstractmethod
    def store(self, record: MemoryRecord) -> str:
        """Persists a single MemoryRecord and returns its ID."""
        pass

    @abstractmethod
    def store_batch(self, records: List[MemoryRecord]) -> int:
        """Persists multiple MemoryRecords, returns count stored."""
        pass

    @abstractmethod
    def search(
        self,
        ticker: str,
        market_conditions: str = "NORMAL",
        strategy: str = "QUANTITATIVE_EQUITY",
        query_vector: Optional[List[float]] = None,
        record_type: Optional[RecordType] = None,
        limit: int = 5,
    ) -> List[MemorySearchResult]:
        """Retrieves and ranks memory records using domain relevance and recency weighting."""
        pass

    @abstractmethod
    def count(self) -> Dict[str, int]:
        """Returns counts partitioned by record type."""
        pass

    @abstractmethod
    def get_all(self, limit: int = 100) -> List[MemoryRecord]:
        """Retrieves raw stored records up to limit."""
        pass


class PostgresMemoryBackend(BaseMemoryBackend):
    """PostgreSQL + pgvector persistent memory backend.
    Operates in live mode if DATABASE_URL is configured and psycopg/pgvector drivers succeed;
    otherwise truthfully reports unavailable so system can safely fall back.
    """

    def __init__(self, database_url: Optional[str] = None):
        settings = get_settings()
        self.database_url = database_url or settings.database_url
        self._connected = False
        self._client = None
        self._has_pgvector = False

        if self.database_url:
            self._init_connection()
        else:
            logger.info("PostgreSQL DATABASE_URL not configured. Remote pgvector memory disabled.")

    def _init_connection(self) -> None:
        """Attempts connection to PostgreSQL and verifies pgvector support."""
        try:
            import psycopg2  # type: ignore
            self._client = psycopg2.connect(self.database_url)
            self._client.autocommit = True
            with self._client.cursor() as cur:
                # Check pgvector extension
                try:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                    self._has_pgvector = True
                except Exception as ext_err:
                    logger.warning(f"pgvector extension creation failed: {ext_err}. Continuing with standard PG tables.")
                    self._has_pgvector = False

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kairos_memory (
                        id TEXT PRIMARY KEY,
                        record_type TEXT NOT NULL,
                        ticker TEXT NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL,
                        date TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        market_conditions TEXT NOT NULL,
                        entry_price DOUBLE PRECISION,
                        exit_price DOUBLE PRECISION,
                        outcome TEXT NOT NULL,
                        pnl DOUBLE PRECISION,
                        pnl_pct DOUBLE PRECISION,
                        rationale TEXT,
                        lessons_learned TEXT,
                        embedding TEXT,
                        metadata JSONB
                    );
                """)
            self._connected = True
            logger.info("Successfully connected to PostgreSQL memory store (pgvector active: %s).", self._has_pgvector)
        except ImportError:
            logger.warning("[Memory MCP] PostgreSQL driver (psycopg2) not installed. PostgreSQL memory disabled.")
            self._connection_error = "Driver psycopg2 not installed"
            self._connected = False
        except Exception as e:
            err_msg = str(e)
            self._connection_error = err_msg
            if "nodename nor servname provided" in err_msg or "could not translate host name" in err_msg:
                logger.info(
                    "[Memory MCP] PostgreSQL host unreachable (sandbox/network isolation or DNS unavailable). "
                    "Local-First SQLite + Vector Memory active."
                )
            else:
                logger.warning("[Memory MCP] PostgreSQL connection failed (%s). PostgreSQL memory disabled.", err_msg)
            self._connected = False

    def is_available(self) -> bool:
        return self._connected

    def store(self, record: MemoryRecord) -> str:
        if not self._connected or not self._client:
            raise RuntimeError("PostgreSQL memory backend is not available.")
        with self._client.cursor() as cur:
            cur.execute("""
                INSERT INTO kairos_memory (
                    id, record_type, ticker, timestamp, date, strategy, market_conditions,
                    entry_price, exit_price, outcome, pnl, pnl_pct, rationale, lessons_learned,
                    embedding, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    outcome = EXCLUDED.outcome,
                    pnl = EXCLUDED.pnl,
                    pnl_pct = EXCLUDED.pnl_pct,
                    lessons_learned = EXCLUDED.lessons_learned,
                    metadata = EXCLUDED.metadata;
            """, (
                record.id,
                record.record_type.value,
                record.ticker,
                record.timestamp,
                record.date,
                record.strategy,
                record.market_conditions,
                record.entry_price,
                record.exit_price,
                record.outcome.value,
                record.pnl,
                record.pnl_pct,
                record.rationale,
                record.lessons_learned,
                json.dumps(record.embedding) if record.embedding else None,
                json.dumps(record.metadata),
            ))
        return record.id

    def store_batch(self, records: List[MemoryRecord]) -> int:
        if not self._connected:
            return 0
        stored = 0
        for r in records:
            try:
                self.store(r)
                stored += 1
            except Exception as e:
                logger.error(f"PostgreSQL store failed for {r.id}: {e}")
        return stored

    def search(
        self,
        ticker: str,
        market_conditions: str = "NORMAL",
        strategy: str = "QUANTITATIVE_EQUITY",
        query_vector: Optional[List[float]] = None,
        record_type: Optional[RecordType] = None,
        limit: int = 5,
    ) -> List[MemorySearchResult]:
        if not self._connected or not self._client:
            return []
        # Fallback to local python scoring on PG rows
        all_records = self.get_all(limit=200)
        return _score_and_rank_records(
            records=all_records,
            ticker=ticker,
            market_conditions=market_conditions,
            strategy=strategy,
            query_vector=query_vector,
            record_type=record_type,
            limit=limit,
        )

    def count(self) -> Dict[str, int]:
        if not self._connected or not self._client:
            return {"total": 0, "completed_trades": 0, "proposals": 0, "research_runs": 0}
        with self._client.cursor() as cur:
            cur.execute("SELECT record_type, COUNT(*) FROM kairos_memory GROUP BY record_type;")
            rows = cur.fetchall()
            counts = {"total": 0, "completed_trades": 0, "proposals": 0, "research_runs": 0}
            for rt, cnt in rows:
                counts["total"] += cnt
                if rt == RecordType.COMPLETED_TRADE.value:
                    counts["completed_trades"] = cnt
                elif rt == RecordType.HYPOTHETICAL_PROPOSAL.value:
                    counts["proposals"] = cnt
                elif rt == RecordType.RESEARCH_RUN.value:
                    counts["research_runs"] = cnt
            return counts

    def get_all(self, limit: int = 100) -> List[MemoryRecord]:
        if not self._connected or not self._client:
            return []
        with self._client.cursor() as cur:
            cur.execute("SELECT id, record_type, ticker, timestamp, date, strategy, market_conditions, entry_price, exit_price, outcome, pnl, pnl_pct, rationale, lessons_learned, embedding, metadata FROM kairos_memory ORDER BY date DESC LIMIT %s;", (limit,))
            rows = cur.fetchall()
            results = []
            for row in rows:
                rec = MemoryRecord(
                    id=row[0],
                    record_type=RecordType(row[1]),
                    ticker=row[2],
                    timestamp=row[3],
                    date=row[4],
                    strategy=row[5],
                    market_conditions=row[6],
                    entry_price=row[7],
                    exit_price=row[8],
                    outcome=TradeOutcome(row[9]),
                    pnl=row[10],
                    pnl_pct=row[11],
                    rationale=row[12] or "",
                    lessons_learned=row[13] or "",
                    embedding=json.loads(row[14]) if row[14] else None,
                    metadata=row[15] if isinstance(row[15], dict) else json.loads(row[15] or "{}"),
                )
                results.append(rec)
            return results


class SQLiteMemoryBackend(BaseMemoryBackend):
    """Local-First SQLite + Vector persistent memory store.
    Provides offline-first durability in data/processed/kairos_memory.db
    with cosine vector similarity computation and robust ACID safety.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            settings = get_settings()
            db_path = settings.processed_data_dir / "kairos_memory.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes tables for memory records."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS kairos_memory (
                        id TEXT PRIMARY KEY,
                        record_type TEXT NOT NULL,
                        ticker TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        date TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        market_conditions TEXT NOT NULL,
                        entry_price REAL,
                        exit_price REAL,
                        outcome TEXT NOT NULL,
                        pnl REAL,
                        pnl_pct REAL,
                        rationale TEXT,
                        lessons_learned TEXT,
                        embedding TEXT,
                        metadata TEXT
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_ticker ON kairos_memory(ticker);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_date ON kairos_memory(date);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_type ON kairos_memory(record_type);")
        finally:
            conn.close()

    def is_available(self) -> bool:
        return True

    def store(self, record: MemoryRecord) -> str:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO kairos_memory (
                        id, record_type, ticker, timestamp, date, strategy, market_conditions,
                        entry_price, exit_price, outcome, pnl, pnl_pct, rationale, lessons_learned,
                        embedding, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    record.id,
                    record.record_type.value,
                    record.ticker,
                    record.timestamp.isoformat(),
                    record.date,
                    record.strategy,
                    record.market_conditions,
                    record.entry_price,
                    record.exit_price,
                    record.outcome.value,
                    record.pnl,
                    record.pnl_pct,
                    record.rationale,
                    record.lessons_learned,
                    json.dumps(record.embedding) if record.embedding else None,
                    json.dumps(record.metadata),
                ))
            return record.id
        finally:
            conn.close()

    def store_batch(self, records: List[MemoryRecord]) -> int:
        stored = 0
        conn = self._get_connection()
        try:
            with conn:
                for r in records:
                    conn.execute("""
                        INSERT OR REPLACE INTO kairos_memory (
                            id, record_type, ticker, timestamp, date, strategy, market_conditions,
                            entry_price, exit_price, outcome, pnl, pnl_pct, rationale, lessons_learned,
                            embedding, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        r.id,
                        r.record_type.value,
                        r.ticker,
                        r.timestamp.isoformat(),
                        r.date,
                        r.strategy,
                        r.market_conditions,
                        r.entry_price,
                        r.exit_price,
                        r.outcome.value,
                        r.pnl,
                        r.pnl_pct,
                        r.rationale,
                        r.lessons_learned,
                        json.dumps(r.embedding) if r.embedding else None,
                        json.dumps(r.metadata),
                    ))
                    stored += 1
            return stored
        finally:
            conn.close()

    def search(
        self,
        ticker: str,
        market_conditions: str = "NORMAL",
        strategy: str = "QUANTITATIVE_EQUITY",
        query_vector: Optional[List[float]] = None,
        record_type: Optional[RecordType] = None,
        limit: int = 5,
    ) -> List[MemorySearchResult]:
        records = self.get_all(limit=500)
        return _score_and_rank_records(
            records=records,
            ticker=ticker,
            market_conditions=market_conditions,
            strategy=strategy,
            query_vector=query_vector,
            record_type=record_type,
            limit=limit,
        )

    def count(self) -> Dict[str, int]:
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT record_type, COUNT(*) FROM kairos_memory GROUP BY record_type;")
            counts = {"total": 0, "completed_trades": 0, "proposals": 0, "research_runs": 0}
            for row in cursor.fetchall():
                rt, cnt = row[0], row[1]
                counts["total"] += cnt
                if rt == RecordType.COMPLETED_TRADE.value:
                    counts["completed_trades"] = cnt
                elif rt == RecordType.HYPOTHETICAL_PROPOSAL.value:
                    counts["proposals"] = cnt
                elif rt == RecordType.RESEARCH_RUN.value:
                    counts["research_runs"] = cnt
            return counts
        finally:
            conn.close()

    def get_all(self, limit: int = 100) -> List[MemoryRecord]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT id, record_type, ticker, timestamp, date, strategy, market_conditions, "
                "entry_price, exit_price, outcome, pnl, pnl_pct, rationale, lessons_learned, "
                "embedding, metadata FROM kairos_memory ORDER BY date DESC LIMIT ?;",
                (limit,),
            )
            rows = cursor.fetchall()
            results = []
            for r in rows:
                rec = MemoryRecord(
                    id=r["id"],
                    record_type=RecordType(r["record_type"]),
                    ticker=r["ticker"],
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                    date=r["date"],
                    strategy=r["strategy"],
                    market_conditions=r["market_conditions"],
                    entry_price=r["entry_price"],
                    exit_price=r["exit_price"],
                    outcome=TradeOutcome(r["outcome"]),
                    pnl=r["pnl"],
                    pnl_pct=r["pnl_pct"],
                    rationale=r["rationale"] or "",
                    lessons_learned=r["lessons_learned"] or "",
                    embedding=json.loads(r["embedding"]) if r["embedding"] else None,
                    metadata=json.loads(r["metadata"] or "{}"),
                )
                results.append(rec)
            return results
        finally:
            conn.close()


def _score_and_rank_records(
    records: List[MemoryRecord],
    ticker: str,
    market_conditions: str,
    strategy: str,
    query_vector: Optional[List[float]],
    record_type: Optional[RecordType],
    limit: int,
) -> List[MemorySearchResult]:
    """Scores candidate records using domain relevance and recency weighting."""
    candidates = []
    for rec in records:
        if rec.id in _DEMO_SEED_IDS or rec.metadata.get("provenance") == "DEMO_SEED":
            continue
        if record_type is not None and rec.record_type != record_type:
            continue

        # Vector similarity if embeddings are present
        sim = None
        if query_vector is not None and rec.embedding is not None:
            sim = _cosine_similarity(query_vector, rec.embedding)

        recency_w = calculate_recency_weight(rec.date)
        relevance_s = calculate_relevance_score(
            record_ticker=rec.ticker,
            record_market_conditions=rec.market_conditions,
            record_strategy=rec.strategy,
            target_ticker=ticker,
            target_market_conditions=market_conditions,
            target_strategy=strategy,
            vector_similarity=sim,
        )
        composite_s = calculate_composite_score(relevance_s, recency_w)

        candidates.append(
            MemorySearchResult(
                record=rec,
                recency_weight=recency_w,
                relevance_score=relevance_s,
                composite_score=composite_s,
            )
        )

    # Sort descending by composite score
    candidates.sort(key=lambda x: x.composite_score, reverse=True)
    return candidates[:limit]


class MemoryManager:
    """Unified manager for KAIROS persistent memory.
    Coordinates PostgreSQL + pgvector and local SQLite backends, transparently
    falling back when credentials/drivers are unavailable, and managing seed data.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None, database_url: Optional[str] = None):
        self.sqlite_backend = SQLiteMemoryBackend(db_path)
        self.postgres_backend = PostgresMemoryBackend(database_url)

        if self.postgres_backend.is_available():
            self.active_backend = self.postgres_backend
            self.backend_name = "PostgreSQL (pgvector)"
            self.postgres_reason = "Connected"
            print("[Memory MCP] PostgreSQL (pgvector): CONNECTED. Remote persistence active.", flush=True)
        else:
            self.active_backend = self.sqlite_backend
            self.backend_name = "Local-First SQLite + Vector"
            reason = getattr(self.postgres_backend, "_connection_error", "No driver/database connection")
            if "nodename nor servname provided" in str(reason) or "could not translate host name" in str(reason):
                reason_summary = "Sandbox isolation / offline network mode"
            elif "not installed" in str(reason).lower():
                reason_summary = "psycopg2 driver not installed in current Python env"
            elif not self.postgres_backend.database_url:
                reason_summary = "DATABASE_URL not configured in .env"
            else:
                reason_summary = str(reason)
            self.postgres_reason = reason_summary
            print(
                f"[Memory MCP] PostgreSQL (pgvector): UNAVAILABLE ({reason_summary}). "
                "Using Local-First SQLite + Vector Memory Fallback.",
                flush=True,
            )

        # Demonstration records must never become production trade-performance evidence.
        if os.environ.get("KAIROS_SEED_DEMO_MEMORY", "false").lower() in ("true", "1"):
            self._ensure_seed_data()

    def get_status(self) -> Dict[str, Any]:
        """Returns detailed status of active memory storage."""
        counts = self.active_backend.count()
        return {
            "active_backend": self.backend_name,
            "postgres_connected": self.postgres_backend.is_available(),
            "postgres_reason": getattr(self, "postgres_reason", "Unavailable"),
            "sqlite_connected": self.sqlite_backend.is_available(),
            "counts": counts,
        }

    def store_trade_record(
        self,
        ticker: str,
        date_str: str,
        strategy: str,
        market_conditions: str,
        entry_price: float,
        exit_price: float,
        outcome: TradeOutcome,
        pnl: float,
        pnl_pct: float,
        rationale: str,
        lessons_learned: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Stores a completed historical trade with real verified outcome."""
        meta = metadata or {}
        prov = str(meta.get("provenance", "")).upper()
        settings = get_settings()
        allow_mock = os.environ.get("KAIROS_ALLOW_MOCK", "").lower() in ("true", "1") or settings.env.lower() in ("test", "testing")
        if "SYNTHETIC" in prov and not allow_mock:
            raise ValueError(f"Institutional memory strictly rejects storing synthetic fixture trades in production mode: {ticker}")

        vector = _generate_synthetic_vector(f"{ticker} {strategy} {market_conditions} {rationale}")
        record = MemoryRecord(
            record_type=RecordType.COMPLETED_TRADE,
            ticker=ticker.upper().strip(),
            date=date_str,
            strategy=strategy,
            market_conditions=market_conditions,
            entry_price=entry_price,
            exit_price=exit_price,
            outcome=outcome,
            pnl=pnl,
            pnl_pct=pnl_pct,
            rationale=rationale,
            lessons_learned=lessons_learned,
            embedding=vector,
            metadata=meta,
        )
        rec_id = self.active_backend.store(record)
        # Mirror to local SQLite for seamless offline fallback
        if self.active_backend is not self.sqlite_backend:
            try:
                self.sqlite_backend.store(record)
            except Exception:
                pass
        return rec_id

    def store_trading_proposal(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        target: float,
        confidence: float,
        rationale: str,
        date_str: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Stores a generated hypothetical trading proposal (outcome=PENDING, pnl=None)."""
        dt_str = date_str or date.today().isoformat()
        meta = metadata or {}
        meta.update({
            "direction": direction,
            "stop_loss": stop_loss,
            "target": target,
            "confidence": confidence,
        })
        vector = _generate_synthetic_vector(f"{ticker} PROPOSAL {direction} {rationale}")
        record = MemoryRecord(
            record_type=RecordType.HYPOTHETICAL_PROPOSAL,
            ticker=ticker.upper().strip(),
            date=dt_str,
            strategy=meta.get("strategy", "QUANTITATIVE_EQUITY"),
            market_conditions=meta.get("market_conditions", "NORMAL"),
            entry_price=entry_price,
            exit_price=None,
            outcome=TradeOutcome.PENDING,
            pnl=None,
            pnl_pct=None,
            rationale=rationale,
            lessons_learned="Awaiting market execution verification.",
            embedding=vector,
            metadata=meta,
        )
        rec_id = self.active_backend.store(record)
        # Mirror to local SQLite for seamless offline fallback
        if self.active_backend is not self.sqlite_backend:
            try:
                self.sqlite_backend.store(record)
            except Exception:
                pass
        return rec_id

    def store_research_run(
        self,
        ticker: str,
        verdict: Dict[str, Any],
        date_str: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Stores a full multi-agent research run."""
        dt_str = date_str or date.today().isoformat()
        meta = metadata or {}
        meta.update(verdict)
        rec = str(verdict.get("recommendation", "NEUTRAL"))
        conv = str(verdict.get("conviction", "MODERATE"))
        rationale = verdict.get("synthesis_rationale", "")
        vector = _generate_synthetic_vector(f"{ticker} RESEARCH {rec} {conv} {rationale}")
        record = MemoryRecord(
            record_type=RecordType.RESEARCH_RUN,
            ticker=ticker.upper().strip(),
            date=dt_str,
            strategy="MULTI_AGENT_SYNTHESIS",
            market_conditions=verdict.get("data_freshness_status", "NORMAL"),
            outcome=TradeOutcome.PENDING,
            rationale=f"Verdict: {rec} ({conv}). {rationale}",
            lessons_learned=f"Key limitations: {', '.join(verdict.get('limitations', [])[:2])}",
            embedding=vector,
            metadata=meta,
        )
        rec_id = self.active_backend.store(record)
        # Mirror to local SQLite for seamless offline fallback
        if self.active_backend is not self.sqlite_backend:
            try:
                self.sqlite_backend.store(record)
            except Exception:
                pass
        return rec_id

    @traced("retrieve-trade-memory", "retriever", fields=("ticker", "market_conditions", "strategy", "limit"))
    def retrieve_relevant_memories(
        self,
        ticker: str,
        market_conditions: str = "NORMAL",
        strategy: str = "QUANTITATIVE_EQUITY",
        record_type: Optional[RecordType] = None,
        limit: int = 4,
    ) -> List[MemorySearchResult]:
        """Retrieves top recency-weighted, domain-relevant historical trade records."""
        query_text = f"{ticker} {strategy} {market_conditions}"
        query_vec = _generate_synthetic_vector(query_text)
        return self.active_backend.search(
            ticker=ticker,
            market_conditions=market_conditions,
            strategy=strategy,
            query_vector=query_vec,
            record_type=record_type,
            limit=limit,
        )

    def _ensure_seed_data(self) -> None:
        """Seeds initial verified trade execution history and proposals if database is empty."""
        counts = self.sqlite_backend.count()
        if counts["total"] > 0:
            return

        logger.info("Initializing KAIROS Persistent Memory seed data with verified trades and proposals...")
        seed_records: List[MemoryRecord] = [
            # 1. TCS - Recent Completed Trade (12 days ago: 2026-10-16) -> High Recency (~0.94)
            MemoryRecord(
                id="trade_tcs_20261016",
                record_type=RecordType.COMPLETED_TRADE,
                ticker="TCS",
                date="2026-10-16",
                strategy="MOMENTUM_BREAKOUT",
                market_conditions="BULLISH_EARNINGS_RALLY",
                entry_price=3920.0,
                exit_price=4108.16,
                outcome=TradeOutcome.WIN,
                pnl=188.16,
                pnl_pct=4.8,
                rationale="Q2 deal total contract value exceeded guidance with strong BFSI conversion. Entered breakout above ₹3900.",
                lessons_learned="Trailing stop captured bulk of momentum run; avoid taking premature profit before resistance target.",
                embedding=_generate_synthetic_vector("TCS MOMENTUM_BREAKOUT BULLISH_EARNINGS_RALLY"),
                metadata={"volume_confirmation": True, "hold_days": 8},
            ),
            # 2. RELIANCE - Recent Completed Trade (22 days ago: 2026-10-06) -> High Recency (~0.89)
            MemoryRecord(
                id="trade_reliance_20261006",
                record_type=RecordType.COMPLETED_TRADE,
                ticker="RELIANCE",
                date="2026-10-06",
                strategy="VALUE_ACCUMULATION",
                market_conditions="RANGEBOUND_CONSOLIDATION",
                entry_price=2840.0,
                exit_price=2930.88,
                outcome=TradeOutcome.WIN,
                pnl=90.88,
                pnl_pct=3.2,
                rationale="Oil-to-chemicals refining margins stabilized while retail revenue sustained double-digit expansion. Entered at key support ₹2840.",
                lessons_learned="Support accumulation in defensive conglomerate generates steady alpha with low drawdown.",
                embedding=_generate_synthetic_vector("RELIANCE VALUE_ACCUMULATION RANGEBOUND_CONSOLIDATION"),
                metadata={"hold_days": 14},
            ),
            # 3. INFY - Recent Hypothetical Proposal (20 days ago: 2026-10-08) -> Pending / None PnL
            MemoryRecord(
                id="prop_infy_20261008",
                record_type=RecordType.HYPOTHETICAL_PROPOSAL,
                ticker="INFY",
                date="2026-10-08",
                strategy="MOMENTUM_BREAKOUT",
                market_conditions="HIGH_VOLATILITY_PRE_EARNINGS",
                entry_price=1780.0,
                exit_price=None,
                outcome=TradeOutcome.PENDING,
                pnl=None,
                pnl_pct=None,
                rationale="Pre-earnings momentum proposal anticipating BFSI discretionary spend uptick.",
                lessons_learned="Awaiting post-earnings resolution.",
                embedding=_generate_synthetic_vector("INFY MOMENTUM_BREAKOUT HIGH_VOLATILITY_PRE_EARNINGS"),
                metadata={"direction": "BUY", "target": 1890.0, "stop_loss": 1720.0},
            ),
            # 4. HDFCBANK - Moderate Trade (52 days ago: 2026-09-06) -> Moderate Recency (~0.68)
            MemoryRecord(
                id="trade_hdfc_20260906",
                record_type=RecordType.COMPLETED_TRADE,
                ticker="HDFCBANK",
                date="2026-09-06",
                strategy="MEAN_REVERSION",
                market_conditions="SECTOR_HEADWIND_CORRECTION",
                entry_price=1620.0,
                exit_price=1585.98,
                outcome=TradeOutcome.LOSS,
                pnl=-34.02,
                pnl_pct=-2.1,
                rationale="NIM compression overhang weighed on private banks. Attempted mean reversion bounce off 200 EMA.",
                lessons_learned="Strict stop loss at ₹1586 contained loss to 2.1%. Do not fight persistent sector liquidity squeeze.",
                embedding=_generate_synthetic_vector("HDFCBANK MEAN_REVERSION SECTOR_HEADWIND_CORRECTION"),
                metadata={"stop_loss_hit": True, "hold_days": 4},
            ),
            # 5. ICICIBANK - Moderate Trade (68 days ago: 2026-08-21) -> Moderate Recency (~0.56)
            MemoryRecord(
                id="trade_icici_20260821",
                record_type=RecordType.COMPLETED_TRADE,
                ticker="ICICIBANK",
                date="2026-08-21",
                strategy="MOMENTUM_BREAKOUT",
                market_conditions="BANKING_RALLY",
                entry_price=1140.0,
                exit_price=1214.10,
                outcome=TradeOutcome.WIN,
                pnl=74.10,
                pnl_pct=6.5,
                rationale="Strong return on assets (2.3%) and negligible slippages propelled breakout to all-time highs.",
                lessons_learned="Highest asset quality bank in the sector can sustain multi-week trends despite broader index weakness.",
                embedding=_generate_synthetic_vector("ICICIBANK MOMENTUM_BREAKOUT BANKING_RALLY"),
                metadata={"hold_days": 19},
            ),
            # 6. INFY - Very Old Historical Trade (190 days ago: 2026-04-21) -> Low Recency (~0.19)
            MemoryRecord(
                id="trade_infy_20260421",
                record_type=RecordType.COMPLETED_TRADE,
                ticker="INFY",
                date="2026-04-21",
                strategy="EARNINGS_PLAY",
                market_conditions="TECH_CORRECTION_BEAR",
                entry_price=1450.0,
                exit_price=1400.70,
                outcome=TradeOutcome.LOSS,
                pnl=-49.30,
                pnl_pct=-3.4,
                rationale="Speculative earnings long ahead of guidance revision.",
                lessons_learned="Guidance cut triggered morning gap-down. Avoid directional earnings speculation without protective put option hedges.",
                embedding=_generate_synthetic_vector("INFY EARNINGS_PLAY TECH_CORRECTION_BEAR"),
                metadata={"stop_loss_hit": True, "hold_days": 2},
            ),
            # 7. RELIANCE - Very Old Historical Trade (240 days ago: 2026-03-02) -> Floor Recency (0.15)
            MemoryRecord(
                id="trade_reliance_20260302",
                record_type=RecordType.COMPLETED_TRADE,
                ticker="RELIANCE",
                date="2026-03-02",
                strategy="BREAKOUT_CONTINUATION",
                market_conditions="MACRO_EXPANSION_BULL",
                entry_price=2700.0,
                exit_price=2837.70,
                outcome=TradeOutcome.WIN,
                pnl=137.70,
                pnl_pct=5.1,
                rationale="Telecom tariff increase anticipation and Jio customer addition acceleration.",
                lessons_learned="Long-term multi-month accumulation rewarded adherence to weekly swing levels.",
                embedding=_generate_synthetic_vector("RELIANCE BREAKOUT_CONTINUATION MACRO_EXPANSION_BULL"),
                metadata={"hold_days": 35},
            ),
        ]

        for record in seed_records:
            record.metadata["provenance"] = "DEMO_SEED"
        self.sqlite_backend.store_batch(seed_records)
        if self.postgres_backend.is_available():
            self.postgres_backend.store_batch(seed_records)
        logger.info("Successfully seeded %d historical records into KAIROS Memory.", len(seed_records))


# Global Singleton
_global_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Returns singleton MemoryManager instance."""
    global _global_memory_manager
    if _global_memory_manager is None:
        _global_memory_manager = MemoryManager()
    return _global_memory_manager
