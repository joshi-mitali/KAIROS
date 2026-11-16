"""FastMCP Memory Server for KAIROS.
Exposes MCP tools for storing and retrieving quantitative research runs,
trading proposals, and verified historical trade records with recency-weighted scoring.
"""

from typing import Any, Dict, List, Optional
from fastmcp import FastMCP

from kairos.memory.models import RecordType, TradeOutcome
from kairos.memory.storage import get_memory_manager
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.memory.mcp_server")

# Initialize FastMCP Server
mcp_server = FastMCP(
    name="kairos-memory",
)


@mcp_server.tool()
def store_trade_record(
    ticker: str,
    date: str,
    strategy: str,
    market_conditions: str,
    entry_price: float,
    exit_price: float,
    outcome: str,
    pnl: float,
    pnl_pct: float,
    rationale: str,
    lessons_learned: str,
) -> Dict[str, Any]:
    """Stores an executed historical trade record with verified P&L and outcome in persistent memory."""
    mgr = get_memory_manager()
    out_upper = outcome.upper().strip()
    if out_upper not in ("WIN", "LOSS", "BREAKEVEN"):
        raise ValueError(f"Trade outcome must be WIN, LOSS, or BREAKEVEN, got: {outcome}")

    record_id = mgr.store_trade_record(
        ticker=ticker,
        date_str=date,
        strategy=strategy,
        market_conditions=market_conditions,
        entry_price=entry_price,
        exit_price=exit_price,
        outcome=TradeOutcome(out_upper),
        pnl=pnl,
        pnl_pct=pnl_pct,
        rationale=rationale,
        lessons_learned=lessons_learned,
    )
    return {"status": "SUCCESS", "record_id": record_id, "backend": mgr.backend_name}


@mcp_server.tool()
def store_trading_proposal(
    ticker: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    target: float,
    confidence: float,
    rationale: str,
    date: str = "",
    strategy: str = "QUANTITATIVE_EQUITY",
    market_conditions: str = "NORMAL",
) -> Dict[str, Any]:
    """Stores a simulated trading proposal (marked strictly as PENDING with no invented P&L)."""
    mgr = get_memory_manager()
    record_id = mgr.store_trading_proposal(
        ticker=ticker,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        confidence=confidence,
        rationale=rationale,
        date_str=date if date else None,
        metadata={"strategy": strategy, "market_conditions": market_conditions},
    )
    return {"status": "SUCCESS", "record_id": record_id, "backend": mgr.backend_name}


@mcp_server.tool()
def store_research_run(
    ticker: str,
    recommendation: str,
    conviction: str,
    synthesis_rationale: str,
    date: str = "",
    limitations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Stores a multi-agent equity research run verdict in persistent memory."""
    mgr = get_memory_manager()
    verdict_dict = {
        "recommendation": recommendation,
        "conviction": conviction,
        "synthesis_rationale": synthesis_rationale,
        "limitations": limitations or [],
    }
    record_id = mgr.store_research_run(
        ticker=ticker,
        verdict=verdict_dict,
        date_str=date if date else None,
    )
    return {"status": "SUCCESS", "record_id": record_id, "backend": mgr.backend_name}


@mcp_server.tool()
def retrieve_memory_records(
    ticker: str,
    market_conditions: str = "NORMAL",
    strategy: str = "QUANTITATIVE_EQUITY",
    record_type: str = "ALL",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Retrieves domain-relevant, recency-weighted trade memories and proposals from persistent memory.
    Trades from last 30 days receive highest weights; older trades decay smoothly; very old trades maintain >= 0.15 floor.
    """
    mgr = get_memory_manager()
    rt_filter = None
    if record_type.upper() in ("COMPLETED_TRADE", "TRADE"):
        rt_filter = RecordType.COMPLETED_TRADE
    elif record_type.upper() in ("HYPOTHETICAL_PROPOSAL", "PROPOSAL"):
        rt_filter = RecordType.HYPOTHETICAL_PROPOSAL
    elif record_type.upper() in ("RESEARCH_RUN", "RESEARCH"):
        rt_filter = RecordType.RESEARCH_RUN

    results = mgr.retrieve_relevant_memories(
        ticker=ticker,
        market_conditions=market_conditions,
        strategy=strategy,
        record_type=rt_filter,
        limit=limit,
    )
    serialized = []
    for res in results:
        serialized.append({
            "id": res.record.id,
            "record_type": res.record.record_type.value,
            "ticker": res.record.ticker,
            "date": res.record.date,
            "strategy": res.record.strategy,
            "market_conditions": res.record.market_conditions,
            "entry_price": res.record.entry_price,
            "exit_price": res.record.exit_price,
            "outcome": res.record.outcome.value,
            "pnl": res.record.pnl,
            "pnl_pct": res.record.pnl_pct,
            "rationale": res.record.rationale,
            "lessons_learned": res.record.lessons_learned,
            "recency_weight": res.recency_weight,
            "relevance_score": res.relevance_score,
            "composite_score": res.composite_score,
        })
    return serialized


@mcp_server.tool()
def get_memory_status() -> Dict[str, Any]:
    """Returns the operational status, backend type (PostgreSQL or SQLite fallback), and storage metrics."""
    mgr = get_memory_manager()
    return mgr.get_status()


if __name__ == "__main__":
    mcp_server.run()

