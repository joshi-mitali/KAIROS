"""KAIROS Phase 2 End-to-End Multi-Agent Orchestrator.
Orchestrates GATHER (Google ADK) -> A2A (Signed Envelope Dispatch) -> ARGUE (CrewAI Debate)
across target NSE tickers.
"""

import argparse
import asyncio
import json
import os
import sys
import time
import resource
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from kairos.a2a.broker import A2AMessagingHub, default_a2a_hub
from kairos.a2a.contract import (
    A2AMessageType,
    A2AResponseEnvelope,
    A2AStatus,
    A2ATaskEnvelope,
    generate_trace_id,
)
from kairos.agents.adk_analysts import (
    FundamentalsAnalyst,
    MarketAnalyst,
    NewsAnalyst,
    SentimentAnalyst,
)
from kairos.agents.crewai_research import ResearchDebateCrew
from kairos.agents.trader_agent import TraderAgent
from kairos.agents.adk_analysts.adk_market_agent import ADKMarketAnalyst
from kairos.a2a.standard import create_a2a_app, call_agent
from kairos.memory.storage import MemoryManager, get_memory_manager
from kairos.observability.callbacks import CallbackManager, LoggingCallback
from kairos.observability.tracer import global_tracer
from kairos.observability.langfuse_tracing import traced
from kairos.schemas.analyst_reports import ResearchSynthesisVerdict
from kairos.schemas.trading_proposal import TradingProposal
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.phase2_orchestrator")

DEFAULT_TARGET_TICKERS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]


class Phase2Orchestrator:
    """Institutional Multi-Agent Orchestrator coordinating Google ADK, A2A, CrewAI,
    Memory MCP (PostgreSQL / SQLite vector fallback), and Trader Agent.
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        a2a_hub: Optional[A2AMessagingHub] = None,
        callback_manager: Optional[CallbackManager] = None,
        memory_manager: Optional[MemoryManager] = None,
    ):
        self.workspace_root = Path(__file__).resolve().parent.parent
        self.data_dir = Path(data_dir) if data_dir else self.workspace_root / "data"
        self.callback_manager = callback_manager or CallbackManager([LoggingCallback()])
        self.a2a_hub = a2a_hub or default_a2a_hub
        self.memory_manager = memory_manager or get_memory_manager()

        # 1. Initialize Google ADK Analysts
        self.market_analyst = ADKMarketAnalyst(str(self.data_dir), self.callback_manager)
        self.sentiment_analyst = SentimentAnalyst(str(self.data_dir), self.callback_manager)
        self.news_analyst = NewsAnalyst(str(self.data_dir), self.callback_manager)
        self.fundamentals_analyst = FundamentalsAnalyst(str(self.data_dir), self.callback_manager)

        # 2. Initialize CrewAI Debate Crew (auto-registers with A2A Hub)
        self.debate_crew = ResearchDebateCrew(self.callback_manager, self.a2a_hub)
        self.standard_a2a = create_a2a_app(self.market_analyst, self.debate_crew)
        self._use_legacy_hub = a2a_hub is not None

        # 3. Initialize Phase 3 Trader Agent with Memory MCP integration
        self.trader_agent = TraderAgent(
            str(self.data_dir),
            self.callback_manager,
            self.a2a_hub.secret_key,
            memory_manager=self.memory_manager,
        )

    @traced("analyze-equity", "chain", fields=("ticker", "risk_preference"))
    def analyze_ticker(self, ticker: str, risk_preference: str = "NEUTRAL") -> Dict[str, Any]:
        """Runs the complete GATHER -> A2A -> ARGUE pipeline for a single stock."""
        ticker = ticker.upper().strip()
        trace_id = generate_trace_id()
        start_time = time.perf_counter()

        print(f"\n[{ticker}] Starting Multi-Agent Analysis Pipeline (Trace: {trace_id[:16]})...", flush=True)
        logger.info(f"[{trace_id[:16]}] Starting Phase 2 workflow for {ticker}...")

        # -------------------------------------------------------------
        # STAGE 1: GATHER — Google ADK Specialist Analysts
        # -------------------------------------------------------------
        print(f"[{ticker}] Phase 2.1: Executing Google ADK Specialist Analysts (Market, Sentiment, News, Fundamentals)...", flush=True)
        from kairos.schemas.analyst_reports import MarketAnalysisReport
        mkt_report = MarketAnalysisReport.model_validate(asyncio.run(call_agent(
            self.standard_a2a, "market", {"ticker": ticker}, trace_id
        )))
        sentiment_report = self.sentiment_analyst.analyze(ticker, trace_id=trace_id)
        news_report = self.news_analyst.analyze(ticker, trace_id=trace_id)
        fund_report = self.fundamentals_analyst.analyze(ticker, trace_id=trace_id)

        analyst_bundle = {
            "market": mkt_report.model_dump(),
            "sentiment": sentiment_report.model_dump(),
            "news": news_report.model_dump(),
            "fundamentals": fund_report.model_dump(),
        }

        # -------------------------------------------------------------
        # STAGE 2: A2A — Standardized Inter-Framework Envelope Dispatch
        # -------------------------------------------------------------
        print(f"[{ticker}] Phase 2.2: Signing and routing A2A inter-framework envelope...", flush=True)
        task_envelope = A2ATaskEnvelope(
            trace_id=trace_id,
            sender_agent="kairos.orchestrator",
            recipient_agent="crewai.research_crew",
            task_type=A2AMessageType.RESEARCH_DEBATE_REQUEST,
            payload={
                "ticker": ticker,
                "analyst_reports": analyst_bundle,
            },
        )
        task_envelope.sign(self.a2a_hub.secret_key)

        # -------------------------------------------------------------
        # STAGE 3: ARGUE — CrewAI Debate & Research Manager Synthesis
        # -------------------------------------------------------------
        print(f"[{ticker}] Phase 2.3: Synthesizing debate via CrewAI (Bull vs Bear -> Manager)...", flush=True)
        if self._use_legacy_hub:
            response_envelope = self.a2a_hub.dispatch(task_envelope)
            if response_envelope.status != A2AStatus.SUCCESS or not response_envelope.data:
                raise RuntimeError(f"Legacy dispatch failed: {response_envelope.error_message}")
            verdict = ResearchSynthesisVerdict.model_validate(response_envelope.data)
        else:
            verdict = ResearchSynthesisVerdict.model_validate(asyncio.run(call_agent(
                self.standard_a2a, "research", {"ticker": ticker, "analyst_reports": analyst_bundle}, trace_id
            )))

        # -------------------------------------------------------------
        # STAGE 4: PERSIST RESEARCH — Memory MCP (PostgreSQL / SQLite)
        # -------------------------------------------------------------
        print(f"[{ticker}] Phase 2.4: Persisting Research Run to Memory MCP ({self.memory_manager.backend_name})...", flush=True)
        try:
            self.memory_manager.store_research_run(
                ticker=ticker,
                verdict=verdict.model_dump(),
            )
        except Exception as mem_err:
            logger.warning(f"Failed to persist research run to memory: {mem_err}")

        # -------------------------------------------------------------
        # STAGE 5: PROPOSE — Phase 3 Trader Agent Execution with Memory
        # -------------------------------------------------------------
        print(f"[{ticker}] Phase 3: Retrieving Memory & Formulating Trading Proposal ({risk_preference.upper()})...", flush=True)
        self.callback_manager.dispatch("on_analyst_start", "trader_agent", ticker, trace_id)
        proposal_start = time.perf_counter()
        trading_proposal = self.trader_agent.generate_proposal(
            ticker=ticker,
            analyst_reports=analyst_bundle,
            verdict=verdict,
            trace_id=trace_id,
            risk_preference=risk_preference,
        )
        self.callback_manager.dispatch("on_analyst_complete", "trader_agent", ticker, trading_proposal, (time.perf_counter()-proposal_start)*1000, trace_id)

        total_time_ms = (time.perf_counter() - start_time) * 1000.0

        # Memory utilization measurement
        # On macOS ru_maxrss is in bytes; on Linux in kilobytes
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            mem_mb = usage / (1024 * 1024)
        else:
            mem_mb = usage / 1024

        print(
            f"[{ticker}] Completed in {total_time_ms:.1f}ms | Verdict: {verdict.recommendation.value} ({verdict.conviction.value}) | "
            f"Proposal: {trading_proposal.direction.value} @ ₹{trading_proposal.entry_price:.2f} (SL: ₹{trading_proposal.stop_loss:.2f}, Target: ₹{trading_proposal.target:.2f})",
            flush=True,
        )
        logger.info(
            f"[{trace_id[:16]}] Finished {ticker}: Recommendation={verdict.recommendation.value}, "
            f"Conviction={verdict.conviction.value}, Proposal={trading_proposal.direction.value}, "
            f"Latency={total_time_ms:.1f}ms, RAM={mem_mb:.1f}MB"
        )

        return {
            "ticker": ticker,
            "trace_id": trace_id,
            "latency_ms": round(total_time_ms, 2),
            "memory_mb": round(mem_mb, 2),
            "analyst_reports": analyst_bundle,
            "verdict": verdict.model_dump(),
            "trading_proposal": trading_proposal.model_dump(),
        }

    def run_all(self, tickers: Optional[List[str]] = None, risk_preference: str = "NEUTRAL") -> List[Dict[str, Any]]:
        """Runs the complete analysis across all configured institutional tickers."""
        target_tickers = tickers or DEFAULT_TARGET_TICKERS
        results = []
        for ticker in target_tickers:
            res = self.analyze_ticker(ticker, risk_preference=risk_preference)
            results.append(res)
        return results


def main():
    parser = argparse.ArgumentParser(description="KAIROS Phase 2 Institutional Multi-Agent Orchestrator")
    parser.add_argument("--ticker", type=str, help="Single NSE ticker symbol (e.g. RELIANCE)")
    parser.add_argument("--all", action="store_true", help="Analyze all 5 target tickers")
    parser.add_argument("--output", type=str, default="data/processed/phase2_verdicts.json", help="Output path for verdicts")
    args = parser.parse_args()

    orchestrator = Phase2Orchestrator()

    if args.ticker:
        target_list = [args.ticker.upper()]
    elif args.all:
        target_list = DEFAULT_TARGET_TICKERS
    else:
        target_list = DEFAULT_TARGET_TICKERS

    print(f"\n=======================================================")
    print(f"  KAIROS Phase 2 Institutional Multi-Agent Analysis")
    print(f"  Target Equities: {', '.join(target_list)}")
    print(f"=======================================================\n")

    results = orchestrator.run_all(target_list)

    # Print summary table
    print(f"\n{'Ticker':<10} | {'Recommendation':<14} | {'Direction':<10} | {'Entry (₹)':<11} | {'Stop (₹)':<11} | {'Target (₹)':<11} | {'R:R':<6} | {'Confidence':<10} | {'Mode':<20}")
    print("-" * 115)
    for r in results:
        v = r["verdict"]
        p = r.get("trading_proposal", {})
        rec = v["recommendation"].value if hasattr(v["recommendation"], "value") else str(v["recommendation"])
        prop_dir = p.get("direction", "N/A")
        if hasattr(prop_dir, "value"):
            prop_dir = prop_dir.value
        entry_p = p.get("entry_price", 0.0)
        stop_p = p.get("stop_loss", 0.0)
        target_p = p.get("target", 0.0)
        rr = p.get("risk_reward_ratio", 0.0)
        conf = p.get("confidence", 0.0)
        mode = p.get("execution_mode", v.get("execution_mode", "UNKNOWN"))
        print(f"{r['ticker']:<10} | {rec:<14} | {prop_dir:<10} | {entry_p:<11.2f} | {stop_p:<11.2f} | {target_p:<11.2f} | {rr:<6.2f} | {conf:<10.2f} | {mode:<20}")
    print("-" * 115)

    # Save output JSONs
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    proposals_data = [r["trading_proposal"] for r in results if "trading_proposal" in r]
    proposals_path = output_path.parent / "trading_proposals.json"
    with open(proposals_path, "w", encoding="utf-8") as f:
        json.dump(proposals_data, f, indent=2)

    # Save memory audit
    memory_audit_path = output_path.parent / "memory_audit.json"
    memory_status = orchestrator.memory_manager.get_status()
    all_memories = [m.model_dump(mode="json") for m in orchestrator.memory_manager.sqlite_backend.get_all(limit=50)]
    with open(memory_audit_path, "w", encoding="utf-8") as f:
        json.dump({
            "status": memory_status,
            "recent_records": all_memories,
        }, f, indent=2, default=str)

    print(f"\nDetailed synthesis results exported to {output_path}")
    print(f"Trading proposals exported to {proposals_path}")
    print(f"Memory audit exported to {memory_audit_path}")
    print(f"Research debate transcript exported to {output_path.parent / 'research_debate.json'}")


if __name__ == "__main__":
    main()
