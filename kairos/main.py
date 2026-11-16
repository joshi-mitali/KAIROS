#!/usr/bin/env python3
"""KAIROS Institutional Multi-Agent Analysis Runner.
Interactive command to run Phase 2 analysis across target NSE equities.
"""

import argparse
import os
import sys
from pathlib import Path

# Automatically load environment variables from .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from kairos.observability.langfuse_tracing import flush_traces
from kairos.memory.storage import get_memory_manager
from kairos.phase2_orchestrator import DEFAULT_TARGET_TICKERS, Phase2Orchestrator
from kairos.schemas.trading_proposal import print_layman_summary

COMPANY_METADATA = {
    "RELIANCE": "Reliance Industries Ltd (Conglomerate / Energy)",
    "TCS": "Tata Consultancy Services Ltd (IT Services & Consulting)",
    "INFY": "Infosys Ltd (IT Services & Consulting)",
    "HDFCBANK": "HDFC Bank Ltd (Banking & Financial Services)",
    "ICICIBANK": "ICICI Bank Ltd (Banking & Financial Services)",
}


def display_interactive_menu() -> str:
    """Displays an interactive company selection menu and returns chosen ticker or 'ALL'."""
    print("\n" + "=" * 76)
    print("  KAIROS — Institutional Multi-Agent Equity Research & Quantitative System")
    print("=" * 76)

    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if groq_key:
        model = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")
        print(f"  [LLM Engine]  Live Groq Model Engine (Model: {model})")
    elif gemini_key:
        model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
        print(f"  [LLM Engine]  Live Gemini Model Engine (Model: {model})")
    else:
        print(f"  [LLM Engine]  Institutional Deterministic Fallback Engine (No API key)")

    mem_mgr = get_memory_manager()
    mem_status = mem_mgr.get_status()
    if mem_status["postgres_connected"]:
        print(f"  [Memory MCP]  PostgreSQL + pgvector (Live Remote Database)")
    else:
        reason = mem_status.get("postgres_reason", "No driver/database connection")
        print(f"  [Memory MCP]  Local-First SQLite + Vector Fallback ({mem_status['counts']['total']} records indexed)")
        print(f"                -> PostgreSQL: UNAVAILABLE ({reason})")

    print("-" * 76)
    print("  Select an Indian equity to analyze:")
    for idx, ticker in enumerate(DEFAULT_TARGET_TICKERS, 1):
        desc = COMPANY_METADATA.get(ticker, "")
        print(f"    [{idx}] {ticker:<10} - {desc}")
    print(f"    [{len(DEFAULT_TARGET_TICKERS) + 1}] ALL        - Analyze all 5 equities sequentially")
    print("-" * 76)

    try:
        choice = input(f"  Enter selection [1-{len(DEFAULT_TARGET_TICKERS) + 1}] (default=1: RELIANCE): ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        print("\n\nOperation cancelled.")
        sys.exit(0)

    if not choice:
        return "RELIANCE"

    menu_map = {str(i): t for i, t in enumerate(DEFAULT_TARGET_TICKERS, 1)}
    menu_map[str(len(DEFAULT_TARGET_TICKERS) + 1)] = "ALL"

    if choice in menu_map:
        return menu_map[choice]

    # Check if entered as ticker symbol directly
    if choice in DEFAULT_TARGET_TICKERS or choice == "ALL":
        return choice

    print(f"  Unrecognized choice '{choice}', defaulting to RELIANCE.")
    return "RELIANCE"


def prompt_user_risk_preference() -> str:
    """Prompts the user to select their risk preference.
    Defaults to Neutral if skipped or unrecognized.
    """
    print("-" * 76)
    print("  Select Your Risk Preference for Trade Proposals:")
    print("    [1] Conservative — prioritize capital protection and lower risk")
    print("    [2] Neutral      — balance potential returns and risk (Default)")
    print("    [3] Aggressive   — accept higher risk for potentially higher returns")
    print("-" * 76)
    try:
        choice = input("  Enter selection [1-3] (default=2: Neutral): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nUsing default risk preference: Neutral")
        return "NEUTRAL"

    mapping = {
        "1": "CONSERVATIVE",
        "2": "NEUTRAL",
        "3": "AGGRESSIVE",
        "CONSERVATIVE": "CONSERVATIVE",
        "NEUTRAL": "NEUTRAL",
        "AGGRESSIVE": "AGGRESSIVE",
    }
    selected = mapping.get(choice.upper(), "NEUTRAL")
    print(f"  -> Risk Preference Selected: {selected}\n")
    return selected


def main():
    parser = argparse.ArgumentParser(description="KAIROS Phase 2 Analysis Runner")
    parser.add_argument("--ticker", type=str, help="NSE ticker symbol to analyze (e.g. RELIANCE, TCS, INFY)")
    parser.add_argument("--all", action="store_true", help="Analyze all 5 target equities")
    parser.add_argument("--output", type=str, default="data/processed/phase2_verdicts.json", help="Path for output JSON")
    parser.add_argument("--diagnose", action="store_true", help="Run API diagnostic test suite (Groq/Gemini)")
    parser.add_argument("--trader-only", action="store_true", help="Run Phase 3 Trader Agent directly on existing verdicts")
    parser.add_argument(
        "--risk-preference",
        "--risk",
        type=str,
        choices=["conservative", "neutral", "aggressive", "CONSERVATIVE", "NEUTRAL", "AGGRESSIVE"],
        default=None,
        help="User risk preference: conservative, neutral, aggressive (default: neutral)",
    )
    args = parser.parse_args()

    if args.diagnose:
        from kairos.diagnostics.diagnose_api import main as run_diag
        run_diag()
        return

    if args.risk_preference:
        risk_pref = args.risk_preference.upper().strip()
    elif not args.ticker and not args.all:
        risk_pref = None  # Will be prompted interactively after menu
    else:
        risk_pref = "NEUTRAL"

    if args.trader_only:
        from kairos.agents.trader_agent import TraderAgent
        agent = TraderAgent()
        print("\n=======================================================")
        print(f"  Running KAIROS Phase 3 Trader Agent ({risk_pref or 'NEUTRAL'})")
        print("=======================================================\n")
        proposals = agent.generate_proposals_from_verdicts_file(
            args.output, "data/processed/trading_proposals.json", risk_preference=risk_pref or "NEUTRAL"
        )
        for p in proposals:
            print_layman_summary(p)
        return

    if args.ticker:
        selected = args.ticker.upper().strip()
    elif args.all:
        selected = "ALL"
    else:
        # Prompt the user with the interactive company selector
        selected = display_interactive_menu()
        if not risk_pref:
            risk_pref = prompt_user_risk_preference()

    if not risk_pref:
        risk_pref = "NEUTRAL"

    if selected == "ALL":
        targets = DEFAULT_TARGET_TICKERS
    else:
        targets = [selected]

    orchestrator = Phase2Orchestrator()
    print(f"\n=======================================================")
    print(f"  Executing KAIROS Phase 2 for: {', '.join(targets)}")
    print(f"  User Risk Preference: {risk_pref}")
    print(f"=======================================================")

    try:
        results = orchestrator.run_all(targets, risk_preference=risk_pref)
    finally:
        flush_traces()

    # Summary table
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

    # Display readable institutional proposal cards for demo
    for r in results:
        p = r.get("trading_proposal", {})
        if not p:
            continue
        p_dir = p.get("direction", "N/A")
        if hasattr(p_dir, "value"):
            p_dir = p_dir.value
        print("\n" + "=" * 76)
        print(f"  INSTITUTIONAL TRADING PROPOSAL: {r['ticker']}")
        print("=" * 76)
        print(f"  Direction:         {p_dir}")
        print(f"  Entry Price:       ₹{p.get('entry_price', 0.0):,.2f}")
        print(f"  Stop-Loss:         ₹{p.get('stop_loss', 0.0):,.2f}")
        print(f"  Target Price:      ₹{p.get('target', 0.0):,.2f}")
        print(f"  Risk / Reward:     {p.get('risk_reward_ratio', 0.0):.2f}:1")
        print(f"  Time Horizon:      {p.get('time_horizon', 'N/A')}")
        print(f"  Conviction/Conf:   {p.get('confidence', 0.0)*100:.1f}%")
        print(f"  Data Freshness:    {p.get('data_freshness', 'N/A')}")
        print(f"  Execution Mode:    {p.get('execution_mode', 'N/A')}")
        print("-" * 76)
        print(f"  Strategic Rationale:\n    {p.get('rationale', 'N/A')}")
        print("-" * 76)
        print("  Key Risk Warnings & Memory Feedback:")
        for w in p.get("risk_warnings", []):
            print(f"    • {w}")
        print("=" * 76)

        # Display clean, plain-English summary for non-technical users
        print_layman_summary(p, analyst_reports=r.get("analyst_reports"), verdict=r.get("verdict"))

    # Save outputs
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    proposals_data = [r["trading_proposal"] for r in results if "trading_proposal" in r]
    proposals_path = output_path.parent / "trading_proposals.json"
    with open(proposals_path, "w", encoding="utf-8") as f:
        json.dump(proposals_data, f, indent=2)

    memory_audit_path = output_path.parent / "memory_audit.json"
    mem_mgr = get_memory_manager()
    all_memories = [m.model_dump(mode="json") for m in mem_mgr.sqlite_backend.get_all(limit=50)]
    with open(memory_audit_path, "w", encoding="utf-8") as f:
        json.dump({
            "status": mem_mgr.get_status(),
            "recent_records": all_memories,
        }, f, indent=2, default=str)

    print(f"\nVerdicts exported to:         {output_path}")
    print(f"Trading proposals exported to: {proposals_path}")
    print(f"Memory audit exported to:     {memory_audit_path}")
    print(f"Research debate exported to:  {output_path.parent / 'research_debate.json'}")


if __name__ == "__main__":
    main()
