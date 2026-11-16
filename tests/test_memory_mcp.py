"""Unit tests for KAIROS Memory MCP.
Validates:
1. Pydantic schema constraints and proposal data integrity (no fake outcomes/PnL).
2. Recency decay curves (last 30d highest, 30-90d decaying, >90d floor >= 0.15).
3. Mathematical guarantee that recency cannot override relevance or risk.
4. SQLite local-first persistence & vector similarity search.
5. PostgreSQL truthful reporting and graceful fallback.
6. FastMCP tool registrations and responses.
7. Trader Agent memory retrieval, lesson integration, and proposal persistence.
"""

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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
    parse_date_to_days_ago,
)
from kairos.memory.storage import (
    MemoryManager,
    PostgresMemoryBackend,
    SQLiteMemoryBackend,
)
from kairos.memory.mcp_server import (
    get_memory_status,
    retrieve_memory_records,
    store_research_run,
    store_trade_record,
    store_trading_proposal,
)
from kairos.agents.trader_agent import TraderAgent
from kairos.schemas.analyst_reports import (
    MarketAnalysisReport,
    RecommendationVerdict,
    ResearchSynthesisVerdict,
    SignalStrength,
)


class TestMemoryMCPModelsAndRecency(unittest.TestCase):
    """Tests Pydantic validation rules and recency weighting mathematics."""

    def test_proposal_integrity_rejects_fake_outcomes(self):
        """Hypothetical proposals MUST NOT invent trade outcomes or P&L."""
        # A proposal with outcome WIN must raise ValueError
        with self.assertRaises(ValueError):
            MemoryRecord(
                record_type=RecordType.HYPOTHETICAL_PROPOSAL,
                ticker="RELIANCE",
                date="2026-10-27",
                outcome=TradeOutcome.WIN,  # Invalid for proposal
            )

        # A proposal with real PnL must raise ValueError
        with self.assertRaises(ValueError):
            MemoryRecord(
                record_type=RecordType.HYPOTHETICAL_PROPOSAL,
                ticker="RELIANCE",
                date="2026-10-27",
                outcome=TradeOutcome.PENDING,
                pnl=500.0,  # Invalid for proposal
            )

        # Valid proposal
        prop = MemoryRecord(
            record_type=RecordType.HYPOTHETICAL_PROPOSAL,
            ticker="RELIANCE",
            date="2026-10-27",
            outcome=TradeOutcome.PENDING,
            pnl=None,
            pnl_pct=None,
            exit_price=None,
        )
        self.assertEqual(prop.outcome, TradeOutcome.PENDING)
        self.assertIsNone(prop.pnl)

    def test_completed_trade_requires_definite_outcome(self):
        """Completed trades must not have outcome PENDING."""
        with self.assertRaises(ValueError):
            MemoryRecord(
                record_type=RecordType.COMPLETED_TRADE,
                ticker="TCS",
                date="2026-10-15",
                outcome=TradeOutcome.PENDING,  # Invalid for completed trade
            )

        trade = MemoryRecord(
            record_type=RecordType.COMPLETED_TRADE,
            ticker="TCS",
            date="2026-10-15",
            outcome=TradeOutcome.WIN,
            pnl=120.0,
            pnl_pct=3.1,
            entry_price=3900.0,
            exit_price=4020.0,
        )
        self.assertEqual(trade.outcome, TradeOutcome.WIN)
        self.assertEqual(trade.pnl, 120.0)

    def test_recency_weight_curves(self):
        """Validates the 3 piecewise stages of the recency decay function."""
        today = date(2026, 10, 28)

        # Stage 1: Last 30 days -> Highest weight in [0.85, 1.00]
        w_day0 = calculate_recency_weight(today, reference_date=today)
        w_day15 = calculate_recency_weight(today - timedelta(days=15), reference_date=today)
        w_day30 = calculate_recency_weight(today - timedelta(days=30), reference_date=today)

        self.assertAlmostEqual(w_day0, 1.00, places=2)
        self.assertGreaterEqual(w_day15, 0.90)
        self.assertAlmostEqual(w_day30, 0.85, places=2)
        self.assertTrue(1.0 >= w_day0 >= w_day15 >= w_day30 >= 0.85)

        # Stage 2: 30 to 90 days -> Gradually reducing importance in [0.40, 0.85]
        w_day45 = calculate_recency_weight(today - timedelta(days=45), reference_date=today)
        w_day60 = calculate_recency_weight(today - timedelta(days=60), reference_date=today)
        w_day90 = calculate_recency_weight(today - timedelta(days=90), reference_date=today)

        self.assertTrue(0.85 > w_day45 > w_day60 > w_day90 >= 0.40)
        self.assertAlmostEqual(w_day90, 0.40, places=2)

        # Stage 3: Very old trades (> 90 days) -> Low but nonzero floor >= 0.15
        w_day180 = calculate_recency_weight(today - timedelta(days=180), reference_date=today)
        w_day365 = calculate_recency_weight(today - timedelta(days=365), reference_date=today)

        self.assertLess(w_day180, 0.40)
        self.assertGreaterEqual(w_day180, 0.15)
        self.assertGreaterEqual(w_day365, 0.15)  # Strict nonzero floor
        self.assertAlmostEqual(w_day365, 0.15, places=2)

    def test_recency_does_not_override_relevance_or_risk(self):
        """Validates the mathematical guarantee:
        1. If relevance == 0, composite == 0 (freshness alone cannot rank an irrelevant item).
        2. Highly relevant older trade beats irrelevant fresh trade.
        """
        # Irrelevant fresh trade (occurred today)
        rel_irrelevant = 0.0
        rec_fresh = 1.00
        comp_irrelevant = calculate_composite_score(rel_irrelevant, rec_fresh)
        self.assertEqual(comp_irrelevant, 0.0)

        # Highly relevant older trade (9 months old) vs marginally relevant yesterday's trade
        rel_relevant_old = 0.95
        rec_old = 0.15  # At floor
        comp_relevant_old = calculate_composite_score(rel_relevant_old, rec_old)

        rel_marg_recent = 0.25
        rec_recent = 0.98
        comp_marg_recent = calculate_composite_score(rel_marg_recent, rec_recent)

        # Old relevant trade MUST outrank fresh irrelevant trade
        self.assertGreater(comp_relevant_old, comp_marg_recent)
        self.assertGreater(comp_relevant_old, 0.40)
        self.assertLess(comp_marg_recent, 0.26)


class TestSQLiteStorageAndManager(unittest.TestCase):
    """Tests SQLite local-first storage, cosine similarity search, and manager fallback."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_memory.db"
        self.backend = SQLiteMemoryBackend(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sqlite_crud_and_counts(self):
        """Verifies storing and counting records partitioned by type."""
        trade = MemoryRecord(
            record_type=RecordType.COMPLETED_TRADE,
            ticker="TCS",
            date="2026-10-20",
            strategy="MOMENTUM_BREAKOUT",
            market_conditions="BULL",
            outcome=TradeOutcome.WIN,
            pnl=150.0,
            pnl_pct=3.8,
            entry_price=3950.0,
            exit_price=4100.0,
        )
        rec_id = self.backend.store(trade)
        self.assertEqual(rec_id, trade.id)

        prop = MemoryRecord(
            record_type=RecordType.HYPOTHETICAL_PROPOSAL,
            ticker="INFY",
            date="2026-10-25",
            outcome=TradeOutcome.PENDING,
        )
        self.backend.store(prop)

        counts = self.backend.count()
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["completed_trades"], 1)
        self.assertEqual(counts["proposals"], 1)

    def test_sqlite_recency_weighted_search(self):
        """Verifies that search returns candidate records sorted by composite score."""
        r1 = MemoryRecord(
            record_type=RecordType.COMPLETED_TRADE,
            ticker="RELIANCE",
            date="2026-10-26",  # 2 days ago
            strategy="VALUE_ACCUMULATION",
            market_conditions="BULL_TREND",
            outcome=TradeOutcome.WIN,
            pnl=50.0,
            pnl_pct=2.0,
            embedding=[0.9, 0.1, 0.0] + [0.0] * 13,
        )
        r2 = MemoryRecord(
            record_type=RecordType.COMPLETED_TRADE,
            ticker="RELIANCE",
            date="2026-03-01",  # 240 days ago
            strategy="VALUE_ACCUMULATION",
            market_conditions="BULL_TREND",
            outcome=TradeOutcome.WIN,
            pnl=120.0,
            pnl_pct=4.5,
            embedding=[0.9, 0.1, 0.0] + [0.0] * 13,
        )
        self.backend.store_batch([r1, r2])

        results = self.backend.search(
            ticker="RELIANCE",
            market_conditions="BULL_TREND",
            strategy="VALUE_ACCUMULATION",
            limit=2,
        )
        self.assertEqual(len(results), 2)
        # The 2-day old record should have higher composite score than the 240-day old record
        self.assertGreater(results[0].composite_score, results[1].composite_score)
        self.assertEqual(results[0].record.id, r1.id)

    def test_memory_manager_transparent_fallback(self):
        """Verifies MemoryManager truthfully reports Postgres status and uses SQLite fallback."""
        mgr = MemoryManager(db_path=self.db_path)
        status = mgr.get_status()

        self.assertEqual(status["active_backend"], "Local-First SQLite + Vector")
        self.assertFalse(status["postgres_connected"])
        self.assertTrue(status["sqlite_connected"])
        self.assertEqual(status["counts"]["total"], 0)  # Empty production memory must not invent trade outcomes.


class TestFastMCPMemoryServer(unittest.TestCase):
    """Tests FastMCP tool functions."""

    def test_store_and_retrieve_trade_mcp_tools(self):
        """Verifies FastMCP tool execution."""
        status = get_memory_status()
        self.assertIn("active_backend", status)

        res = store_trade_record(
            ticker="ICICIBANK",
            date="2026-10-22",
            strategy="BREAKOUT",
            market_conditions="BULL",
            entry_price=1200.0,
            exit_price=1260.0,
            outcome="WIN",
            pnl=60.0,
            pnl_pct=5.0,
            rationale="Credit growth acceleration",
            lessons_learned="Trail stop on bank rally",
        )
        self.assertEqual(res["status"], "SUCCESS")

        records = retrieve_memory_records(ticker="ICICIBANK", limit=3)
        self.assertGreaterEqual(len(records), 1)
        self.assertEqual(records[0]["ticker"], "ICICIBANK")
        self.assertIn("recency_weight", records[0])
        self.assertIn("composite_score", records[0])

    def test_store_proposal_mcp_tool_integrity(self):
        """Verifies FastMCP proposal tool persists strictly as PENDING."""
        prop_res = store_trading_proposal(
            ticker="HDFCBANK",
            direction="BUY",
            entry_price=1650.0,
            stop_loss=1600.0,
            target=1750.0,
            confidence=0.75,
            rationale="Deposit growth stabilization thesis.",
        )
        self.assertEqual(prop_res["status"], "SUCCESS")

        proposals = retrieve_memory_records(ticker="HDFCBANK", record_type="PROPOSAL", limit=5)
        for p in proposals:
            self.assertEqual(p["record_type"], "HYPOTHETICAL_PROPOSAL")
            self.assertEqual(p["outcome"], "PENDING")
            self.assertIsNone(p["pnl"])


class TestTraderAgentMemoryIntegration(unittest.TestCase):
    """Verifies that TraderAgent consumes recency-weighted memory lessons."""

    def test_trader_agent_incorporates_memory(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "test_trader_mem.db"
        mem_mgr = MemoryManager(db_path=db_path)

        # Seed a prior LOSS on TCS to test risk warning and stop-loss adjustment
        mem_mgr.store_trade_record(
            ticker="TCS",
            date_str="2026-10-18",
            strategy="MOMENTUM_BREAKOUT",
            market_conditions="VOLATILE_CHOP",
            entry_price=4000.0,
            exit_price=3920.0,
            outcome=TradeOutcome.LOSS,
            pnl=-80.0,
            pnl_pct=-2.0,
            rationale="Chased false breakout in rangebound tape.",
            lessons_learned="Widen stop-loss for chop; do not enter extended RSI.",
        )

        agent = TraderAgent(memory_manager=mem_mgr)

        reports = {
            "market": {
                "last_price": 4050.0,
                "support_level": 3950.0,
                "resistance_level": 4200.0,
                "quote_delay": "REALTIME",
                "indicators": {"rsi_14": 52.0, "sma_20": 4010.0},
            },
            "fundamentals": {"profit_margins": 0.24, "solvency_health": "STRONG"},
            "sentiment": {"retail_bull_ratio": 0.60},
            "news": {"key_catalysts": ["Cloud transformation deal"], "regulatory_and_litigation_risks": []},
        }

        verdict = ResearchSynthesisVerdict(
            ticker="TCS",
            trace_id="00-test-trace-id-01",
            recommendation=RecommendationVerdict.OVERWEIGHT,
            conviction=SignalStrength.STRONG,
            synthesis_rationale="Solid earnings momentum and cloud migration deal pipeline.",
            limitations=["FX volatility"],
            data_freshness_status="CURRENT_OCTOBER_2026",
            bull_summary="Growth intact",
            bear_summary="IT margin pressure",
        )

        proposal = agent.generate_proposal("TCS", reports, verdict)

        # Verify proposal properties
        self.assertEqual(proposal.ticker, "TCS")
        self.assertIn(proposal.direction.value, ("BUY", "HOLD"))
        self.assertGreater(proposal.target, proposal.entry_price)

        # Verify historical memory was integrated into risk warnings
        has_memory_warning = any("Historical Memory" in w for w in proposal.risk_warnings)
        self.assertTrue(has_memory_warning)

        # Verify proposal was persisted to memory
        status = mem_mgr.get_status()
        self.assertGreater(status["counts"]["proposals"], 0)

        temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
