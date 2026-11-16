"""KAIROS Phase 3 Trader Agent.
Consumes Google ADK specialist analyst reports and CrewAI research debate verdicts
to generate structured, risk-managed institutional trading proposals.
Strictly research-oriented; no automated order routing or live trade execution.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from kairos.a2a.contract import A2AMessageType, A2ATaskEnvelope, generate_trace_id
from kairos.agents.adk_analysts.base_analyst import BaseADKAnalyst
from kairos.memory.models import MemorySearchResult, RecordType, TradeOutcome
from kairos.memory.storage import MemoryManager, get_memory_manager
from kairos.observability.callbacks import CallbackManager
from kairos.observability.langfuse_tracing import traced
from kairos.schemas.analyst_reports import (
    FundamentalsAnalysisReport,
    MarketAnalysisReport,
    NewsAnalysisReport,
    RecommendationVerdict,
    ResearchSynthesisVerdict,
    SentimentAnalysisReport,
    SignalStrength,
    sentiment_prompt_line,
)
from kairos.schemas.trading_proposal import (
    TradeDirection,
    TradingProposal,
    print_layman_summary,
)
from kairos.config.agent_definitions import render_task
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.trader_agent")


class TraderAgent(BaseADKAnalyst):
    """Phase 3 Institutional Quantitative Trader Agent.
    Evaluates research synthesis verdicts and analyst findings alongside
    recency-weighted historical trade memory to construct actionable,
    risk-bounded trade proposals.
    """

    agent_name: str = "kairos.trader_agent"
    config_key: str = "trader_agent"
    task_message_type: A2AMessageType = A2AMessageType.TRADING_PROPOSAL
    output_schema = TradingProposal

    def __init__(
        self,
        data_dir: Optional[str] = None,
        callback_manager: Optional[CallbackManager] = None,
        secret_key: str = "kairos_a2a_secret",
        memory_manager: Optional[MemoryManager] = None,
    ):
        super().__init__(
            data_dir=data_dir, callback_manager=callback_manager, secret_key=secret_key
        )
        self.memory_manager = memory_manager or get_memory_manager()
        logger.info(
            f"{self.agent_name} initialized. Live trading is STRICTLY DISABLED (Paper/Simulation only)."
        )

    def generate_deterministic_proposal(
        self,
        ticker: str,
        analyst_reports: Dict[str, Any],
        verdict: Union[ResearchSynthesisVerdict, Dict[str, Any]],
        trace_id: Optional[str] = None,
        past_memories: Optional[List[MemorySearchResult]] = None,
        risk_preference: str = "NEUTRAL",
    ) -> TradingProposal:
        """Constructs a deterministic quantitative trading proposal based on technical levels,
        fundamental valuation, research manager consensus, recency-weighted trade memories,
        and user risk preference.
        """
        # Normalize user risk preference
        rp_clean = (risk_preference or "NEUTRAL").upper().strip()
        if "CONSERV" in rp_clean:
            risk_pref = "CONSERVATIVE"
        elif "AGGR" in rp_clean:
            risk_pref = "AGGRESSIVE"
        else:
            risk_pref = "NEUTRAL"

        # 1. Extract market technical metrics
        mkt = analyst_reports.get("market", {})
        if isinstance(mkt, BaseModel):
            mkt = mkt.model_dump()

        last_price = float(mkt.get("last_price", 1000.0))
        support = float(mkt.get("support_level", last_price * 0.95))
        resistance = float(mkt.get("resistance_level", last_price * 1.08))
        quote_delay = mkt.get("quote_delay", "15_MIN_DELAYED")
        prov = str(mkt.get("provenance", "")).upper()

        # Enforce market data guardrails and reject synthetic or incompatible data in production
        import os
        from kairos.config.settings import get_settings

        settings = get_settings()
        allow_mock = os.environ.get("KAIROS_ALLOW_MOCK", "").lower() in (
            "true",
            "1",
        ) or settings.env.lower() in ("test", "testing")
        if "SYNTHETIC" in prov and not allow_mock:
            raise ValueError(
                f"TraderAgent rejected proposal generation for {ticker}: "
                f"Synthetic fixture market data ('{prov}') is forbidden in production."
            )

        if last_price > 0 and support > 0 and resistance > 0:
            lower_tolerance = support * 0.65
            upper_tolerance = resistance * 1.35
            if last_price < lower_tolerance or last_price > upper_tolerance:
                raise ValueError(
                    f"TraderAgent rejected proposal generation for {ticker}: Severe price basis divergence detected "
                    f"(Last Price: ₹{last_price:.2f}, Support: ₹{support:.2f}, Resistance: ₹{resistance:.2f}). "
                    "Unadjusted corporate split or incompatible price fixture detected."
                )

        # 2. Extract synthesis recommendation & conviction
        if isinstance(verdict, ResearchSynthesisVerdict):
            rec = verdict.recommendation.value
            conv = verdict.conviction.value
            rationale_text = verdict.synthesis_rationale
            data_freshness = verdict.data_freshness_status
            verdict_limits = verdict.limitations
        elif isinstance(verdict, dict):
            rec_val = verdict.get("recommendation", "NEUTRAL")
            rec = rec_val.value if hasattr(rec_val, "value") else str(rec_val)
            conv_val = verdict.get("conviction", "MODERATE")
            conv = conv_val.value if hasattr(conv_val, "value") else str(conv_val)
            rationale_text = verdict.get(
                "synthesis_rationale", "Deterministic multi-agent synthesis."
            )
            data_freshness = verdict.get(
                "data_freshness_status", f"CURRENT_OCTOBER_2026 ({quote_delay})"
            )
            verdict_limits = verdict.get("limitations", [])
        else:
            rec, conv = "NEUTRAL", "MODERATE"
            rationale_text = "Standard quantitative positioning."
            data_freshness = f"CURRENT_OCTOBER_2026 ({quote_delay})"
            verdict_limits = []

        # 3. Memory Feedback Adjustment: Check historical win/loss lessons
        memory_notes: List[str] = []
        stop_loss_adjustment_pct = 0.0
        confidence_delta = 0.0

        if past_memories:
            for item in past_memories:
                m_rec = item.record
                if m_rec.record_type == RecordType.COMPLETED_TRADE:
                    if m_rec.outcome == TradeOutcome.LOSS:
                        # Incorporate loss lesson: widen stop-loss slightly to avoid premature stop-out
                        stop_loss_adjustment_pct += 0.005
                        confidence_delta -= 0.05
                        memory_notes.append(
                            f"Historical Memory: Past loss on {m_rec.date} ({m_rec.pnl_pct:+.1f}%) lesson: '{m_rec.lessons_learned}'."
                        )
                    elif m_rec.outcome == TradeOutcome.WIN:
                        confidence_delta += 0.05
                        memory_notes.append(
                            f"Historical Memory: Past win on {m_rec.date} ({m_rec.pnl_pct:+.1f}%) confirmed '{m_rec.strategy}' thesis."
                        )

        # 4. Determine trade direction, entry, stop-loss, target, and risk preference adaptations
        if rec in ("OVERWEIGHT", "BUY"):
            direction = TradeDirection.BUY
            if risk_pref == "CONSERVATIVE":
                # Disciplined entry closer to support to limit downside
                entry_price = round(
                    min(last_price, support * 1.015)
                    if support > 0 and support < last_price
                    else last_price * 0.99,
                    2,
                )
                base_sl = (
                    support * (0.99 - stop_loss_adjustment_pct)
                    if support < entry_price
                    else entry_price * 0.97
                )
                stop_loss = round(base_sl, 2)
                target = round(
                    min(
                        resistance * 1.01, entry_price + (entry_price - stop_loss) * 1.5
                    )
                    if resistance > entry_price
                    else entry_price + (entry_price - stop_loss) * 1.5,
                    2,
                )
                position_sizing = (
                    "CONSERVATIVE (1-2% of portfolio) — Prioritizing capital protection"
                )
                preference_influence = "Prioritizes capital protection: tightened stop-loss limits drawdown risk, entry requires disciplined support pricing, and allocation is capped at 1-2%."
            elif risk_pref == "AGGRESSIVE":
                # Immediate breakout entry, wider stop buffer to absorb volatility, extended target
                entry_price = round(last_price, 2)
                base_sl = (
                    support * (0.95 - stop_loss_adjustment_pct)
                    if support < entry_price
                    else entry_price * 0.92
                )
                stop_loss = round(base_sl, 2)
                min_target = round(entry_price + (entry_price - stop_loss) * 2.5, 2)
                target = round(
                    max(resistance * 1.08, min_target)
                    if resistance > entry_price
                    else min_target,
                    2,
                )
                position_sizing = (
                    "AGGRESSIVE (6-8% of portfolio) — Maximizing upside exposure"
                )
                preference_influence = "Prioritizes growth potential: wider stop-loss absorbs market noise, target profit objective is extended, and position size is active at 6-8%."
            else:  # NEUTRAL
                entry_price = round(last_price, 2)
                base_sl = (
                    support * (0.98 - stop_loss_adjustment_pct)
                    if support < entry_price
                    else entry_price * 0.95
                )
                stop_loss = round(base_sl, 2)
                min_target = round(entry_price + (entry_price - stop_loss) * 1.8, 2)
                target = round(
                    max(resistance * 1.02, min_target)
                    if resistance > entry_price
                    else min_target,
                    2,
                )
                position_sizing = (
                    "BALANCED (3-5% of portfolio) — Balanced risk and return"
                )
                preference_influence = "Balances potential return with risk: standard technical support buffers and moderate 3-5% position size applied."

            risk = max(0.01, entry_price - stop_loss)
            reward = max(0.01, target - entry_price)
            rr_ratio = round(reward / risk, 2)
            time_horizon = "3-6 MONTHS"
            base_conf = 0.80 if conv == "STRONG" else 0.65
            confidence = max(0.40, min(0.95, round(base_conf + confidence_delta, 2)))
            trade_rationale = (
                f"BUY limit proposal initiated at ₹{entry_price:.2f} ({risk_pref.lower()} profile). "
                f"Thesis aligns with Research Manager OVERWEIGHT verdict: strong fundamental margins "
                f"and bullish momentum above support ₹{support:.2f}. "
                f"Defensive stop-loss placed at ₹{stop_loss:.2f} with profit objective at ₹{target:.2f} "
                f"(Risk/Reward: {rr_ratio}:1). Position sizing: {position_sizing}."
            )
        elif rec in ("UNDERWEIGHT", "SELL"):
            direction = TradeDirection.SELL
            entry_price = round(last_price, 2)
            if risk_pref == "CONSERVATIVE":
                base_sl = (
                    min(
                        resistance * (1.01 + stop_loss_adjustment_pct),
                        entry_price * 1.025,
                    )
                    if resistance > last_price
                    else entry_price * 1.025
                )
                position_sizing = (
                    "AVOID / ZERO ALLOCATION (0% of portfolio) — Capital preservation"
                )
                preference_influence = "Conservative profile: capital preservation prioritized; avoid taking any equity risk under underweight conditions."
            elif risk_pref == "AGGRESSIVE":
                base_sl = (
                    min(
                        resistance * (1.04 + stop_loss_adjustment_pct),
                        entry_price * 1.06,
                    )
                    if resistance > last_price
                    else entry_price * 1.06
                )
                position_sizing = (
                    "TACTICAL SHORT (2-4% of portfolio) — Tactical short exposure"
                )
                preference_influence = "Aggressive profile: tactical short positioning with wider resistance ceiling to target full downside move."
            else:  # NEUTRAL
                base_sl = (
                    min(
                        resistance * (1.02 + stop_loss_adjustment_pct),
                        entry_price * 1.04,
                    )
                    if resistance > last_price
                    else entry_price * 1.04
                )
                position_sizing = "AVOID / HEDGE (0-1% of portfolio) — Defensive stance"
                preference_influence = "Neutral profile: underweight thesis indicates negative skew; observe support floor before reassessing."

            stop_loss = round(base_sl, 2)
            min_target = round(entry_price - (stop_loss - entry_price) * 1.5, 2)
            target = round(
                min(support * 0.98, min_target) if support < last_price else min_target,
                2,
            )
            risk = max(0.01, stop_loss - entry_price)
            reward = max(0.01, entry_price - target)
            rr_ratio = round(reward / risk, 2)
            time_horizon = "1-3 MONTHS"
            base_conf = 0.75 if conv == "STRONG" else 0.60
            confidence = max(0.40, min(0.95, round(base_conf + confidence_delta, 2)))
            trade_rationale = (
                f"SELL/Short limit proposal at ₹{entry_price:.2f} ({risk_pref.lower()} profile). "
                f"Manager thesis UNDERWEIGHT due to valuation stretch, debt leverage, or bearish momentum. "
                f"Risk ceiling established at resistance ₹{stop_loss:.2f} targeting support zone ₹{target:.2f} "
                f"(Risk/Reward: {rr_ratio}:1). Position sizing: {position_sizing}."
            )
        else:
            direction = TradeDirection.HOLD
            entry_price = round(last_price, 2)
            stop_loss = round(support * 0.95, 2)
            target = round(resistance * 1.05, 2)
            rr_ratio = 1.0
            time_horizon = "MONITOR (1-4 WEEKS)"
            confidence = 0.50
            if risk_pref == "CONSERVATIVE":
                position_sizing = (
                    "CASH / HOLD (0% new capital) — Wait for confirmed safety"
                )
                preference_influence = "Conservative stance: no edge in rangebound price action. Keep capital in liquid assets until a clear trend emerges."
            elif risk_pref == "AGGRESSIVE":
                position_sizing = "ACCUMULATE ON DIPS (2-3% scaled entries)"
                preference_influence = "Aggressive range trading: accumulate small tranches near support while maintaining risk bounds."
            else:
                position_sizing = "OBSERVE (0-2% discretionary tracking position)"
                preference_influence = "Neutral observation: observe price action between support and resistance before committing capital."

            trade_rationale = (
                f"HOLD proposal at ₹{entry_price:.2f} ({risk_pref.lower()} profile). "
                f"Balanced risk/reward and neutral consensus. Recommend observing price action "
                f"between support ₹{support:.2f} and resistance ₹{resistance:.2f} prior to capital deployment."
            )

        # 5. Synthesize risk warnings with memory takeaways
        risk_warnings = [
            f"Execution strictly simulated. Quote feed delay ({quote_delay}) entails potential market slippage.",
            f"Violation of key support level (₹{support:.2f}) invalidates the strategic thesis.",
            "Proposal subject to macroeconomic shifts, RBI monetary policy, and systemic equity market volatility.",
            "NON-EXECUTION COMPLIANCE: Research synthesis only. Strictly simulated paper proposal - NO REAL TRADING, no live trading, broker API routing, or capital commitment.",
        ]
        if memory_notes:
            risk_warnings.extend(memory_notes[:2])
        if verdict_limits:
            risk_warnings.extend(verdict_limits[:2])

        proposal = TradingProposal(
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            time_horizon=time_horizon,
            confidence=confidence,
            rationale=trade_rationale,
            data_freshness=data_freshness,
            risk_warnings=risk_warnings,
            risk_reward_ratio=rr_ratio,
            order_type="LIMIT",
            status="SIMULATED_PROPOSAL_ONLY",
            execution_mode="DETERMINISTIC_FALLBACK",
            risk_preference=risk_pref,
            position_sizing=position_sizing,
            preference_influence=preference_influence,
        )
        proposal.get_layman_summary(analyst_reports=analyst_reports, verdict=verdict)
        return proposal

    @traced("propose-trade", "agent", fields=("ticker", "risk_preference", "analyst_reports", "verdict"))
    def generate_proposal(
        self,
        ticker: str,
        analyst_reports: Dict[str, Any],
        verdict: Union[ResearchSynthesisVerdict, Dict[str, Any]],
        trace_id: Optional[str] = None,
        risk_preference: str = "NEUTRAL",
    ) -> TradingProposal:
        """Generates a structured Trading Proposal by evaluating analyst reports, CrewAI verdict,
        recency-weighted historical trade memory, and user risk preference.
        Utilizes Groq LLM when available with strict JSON Schema enforcement; falls back cleanly
        to the quantitative deterministic engine.
        """
        ticker = ticker.upper().strip()
        trace_id = trace_id or generate_trace_id()

        # 1. Retrieve relevant historical trade memory
        mkt = analyst_reports.get("market", {})
        if isinstance(mkt, BaseModel):
            mkt = mkt.model_dump()

        rsi = mkt.get("indicators", {}).get("rsi_14", 50.0)
        market_conditions = (
            "BULLISH_MOMENTUM"
            if rsi > 65
            else ("OVERSOLD_REVERSAL" if rsi < 35 else "RANGEBOUND")
        )
        strategy = "MOMENTUM_BREAKOUT" if rsi > 60 else "VALUE_ACCUMULATION"

        past_memories = self.memory_manager.retrieve_relevant_memories(
            ticker=ticker,
            market_conditions=market_conditions,
            strategy=strategy,
            limit=3,
        )

        fallback_proposal = self.generate_deterministic_proposal(
            ticker,
            analyst_reports,
            verdict,
            trace_id,
            past_memories=past_memories,
            risk_preference=risk_preference,
        )

        # 2. Format memory evidence clearly distinguishing completed trades from proposals
        memory_lines = []
        for item in past_memories:
            rec = item.record
            score_info = f"Recency: {item.recency_weight:.2f}, Relevance: {item.relevance_score:.2f}, Composite: {item.composite_score:.2f}"
            if rec.record_type == RecordType.COMPLETED_TRADE:
                pnl_str = (
                    f"{rec.pnl_pct:+.1f}% (₹{rec.pnl:+,.2f})"
                    if rec.pnl is not None
                    else "N/A"
                )
                memory_lines.append(
                    f"- [COMPLETED TRADE - REAL OUTCOME] {rec.ticker} ({rec.date}) | Outcome: {rec.outcome.value} ({pnl_str}) | {score_info} | Lesson: {rec.lessons_learned}"
                )
            elif rec.record_type == RecordType.HYPOTHETICAL_PROPOSAL:
                memory_lines.append(
                    f"- [HYPOTHETICAL PROPOSAL - UNEXECUTED] {rec.ticker} ({rec.date}) | Status: PENDING (Unexecuted) | {score_info} | Rationale: {rec.rationale[:90]}"
                )
            else:
                memory_lines.append(
                    f"- [RESEARCH RUN] {rec.ticker} ({rec.date}) | {score_info} | {rec.rationale[:90]}"
                )

        memory_context = (
            "\n".join(memory_lines)
            if memory_lines
            else "No prior trade memory recorded."
        )

        # If Groq client is not available, return deterministic proposal and store it
        if not self.groq_client and not self.gemini_client:
            logger.info(
                f"{self.agent_name}: No live LLM configured. Returning deterministic trading proposal."
            )
            self._persist_proposal_to_memory(
                fallback_proposal, market_conditions, strategy
            )
            return fallback_proposal

        # Format streamlined input bundle for LLM
        verdict_dict = (
            verdict.model_dump() if isinstance(verdict, BaseModel) else verdict
        )
        fund = analyst_reports.get("fundamentals", {})
        sentiment = analyst_reports.get("sentiment", {})
        news = analyst_reports.get("news", {})

        rationale_snippet = (verdict_dict.get("synthesis_rationale") or "")[:200]
        from kairos.observability.prompt_guard import guard_untrusted_text
        guard_untrusted_text(memory_context + "\n" + rationale_snippet, "trade_memory_and_verdict", self.callback_manager, trace_id)
        prompt = render_task(
            "trading_proposal",
            ticker=ticker,
            risk_preference=fallback_proposal.risk_preference,
            recommendation=verdict_dict.get("recommendation"),
            conviction=verdict_dict.get("conviction"),
            rationale_snippet=rationale_snippet,
            last_price=mkt.get("last_price"),
            support=mkt.get("support_level"),
            resistance=mkt.get("resistance_level"),
            sma_20=mkt.get("indicators", {}).get("sma_20"),
            rsi_14=mkt.get("indicators", {}).get("rsi_14"),
            profit_margins=fund.get("profit_margins"),
            solvency_health=fund.get("solvency_health"),
            sentiment=sentiment_prompt_line(sentiment),
            catalysts=", ".join(news.get("key_catalysts", [])[:2]),
            risks=", ".join(news.get("regulatory_and_litigation_risks", [])[:2]),
            memory_context=memory_context,
        )["description"]

        proposal = self.invoke_llm_analysis(
            prompt=prompt,
            schema_cls=TradingProposal,
            fallback_report=fallback_proposal,
        )

        proposal.risk_preference = fallback_proposal.risk_preference
        if not proposal.position_sizing:
            proposal.position_sizing = fallback_proposal.position_sizing
        if not proposal.preference_influence:
            proposal.preference_influence = fallback_proposal.preference_influence

        proposal.get_layman_summary(analyst_reports=analyst_reports, verdict=verdict)

        self._persist_proposal_to_memory(proposal, market_conditions, strategy)
        return proposal

    def _persist_proposal_to_memory(
        self, proposal: TradingProposal, market_conditions: str, strategy: str
    ) -> None:
        """Stores generated proposal to persistent memory (marked as PENDING)."""
        try:
            dir_str = (
                proposal.direction.value
                if hasattr(proposal.direction, "value")
                else str(proposal.direction)
            )
            self.memory_manager.store_trading_proposal(
                ticker=proposal.ticker,
                direction=dir_str,
                entry_price=proposal.entry_price,
                stop_loss=proposal.stop_loss,
                target=proposal.target,
                confidence=proposal.confidence,
                rationale=proposal.rationale,
                metadata={
                    "strategy": strategy,
                    "market_conditions": market_conditions,
                    "risk_reward_ratio": proposal.risk_reward_ratio,
                    "execution_mode": proposal.execution_mode,
                    "risk_preference": proposal.risk_preference,
                    "position_sizing": proposal.position_sizing,
                    "preference_influence": proposal.preference_influence,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to persist proposal to memory: {e}")

    def generate_proposals_from_verdicts_file(
        self,
        verdicts_path: Union[str, Path] = "data/processed/phase2_verdicts.json",
        output_path: Union[str, Path] = "data/processed/trading_proposals.json",
        risk_preference: str = "NEUTRAL",
    ) -> List[TradingProposal]:
        """Reads stored verdicts from data/processed/phase2_verdicts.json,
        generates trading proposals for each ticker, and saves to data/processed/trading_proposals.json.
        """
        v_path = Path(verdicts_path)
        if not v_path.is_absolute():
            v_path = self.workspace_root / v_path

        if not v_path.exists():
            raise FileNotFoundError(f"Verdicts file not found at: {v_path}")

        with open(v_path, "r", encoding="utf-8") as f:
            verdicts_data = json.load(f)

        proposals = []
        for entry in verdicts_data:
            ticker = entry["ticker"]
            analyst_reports = entry.get("analyst_reports", {})
            verdict = entry.get("verdict", {})
            trace_id = entry.get("trace_id")

            print(
                f"[{ticker}] Phase 3: Formulating Trading Proposal ({risk_preference.upper()})...",
                flush=True,
            )
            prop = self.generate_proposal(
                ticker,
                analyst_reports,
                verdict,
                trace_id=trace_id,
                risk_preference=risk_preference,
            )
            proposals.append(prop)

        self.save_proposals(proposals, output_path=output_path)
        return proposals

        self.save_proposals(proposals, output_path=output_path)
        return proposals

    def save_proposals(
        self,
        proposals: List[TradingProposal],
        output_path: Union[str, Path] = "data/processed/trading_proposals.json",
    ) -> Path:
        """Serializes proposals to the target JSON path."""
        out_p = Path(output_path)
        if not out_p.is_absolute():
            out_p = self.workspace_root / out_p

        out_p.parent.mkdir(parents=True, exist_ok=True)
        data = [p.model_dump() for p in proposals]
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved {len(proposals)} trading proposals to {out_p}")
        print(f"Proposals successfully exported to {out_p}", flush=True)
        return out_p


def main():
    import argparse

    parser = argparse.ArgumentParser(description="KAIROS Phase 3 Trader Agent")
    parser.add_argument(
        "--verdicts",
        type=str,
        default="data/processed/phase2_verdicts.json",
        help="Path to verdicts JSON",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/processed/trading_proposals.json",
        help="Path to save proposals JSON",
    )
    parser.add_argument(
        "--risk-preference",
        "--risk",
        type=str,
        default="NEUTRAL",
        choices=[
            "conservative",
            "neutral",
            "aggressive",
            "CONSERVATIVE",
            "NEUTRAL",
            "AGGRESSIVE",
        ],
        help="User risk preference",
    )
    args = parser.parse_args()

    agent = TraderAgent()
    print("\n=======================================================")
    print(f"  KAIROS Phase 3 Trader Agent Execution ({args.risk_preference.upper()})")
    print("  Generating Structured Risk-Managed Trading Proposals")
    print("=======================================================\n")
    proposals = agent.generate_proposals_from_verdicts_file(
        args.verdicts, args.output, risk_preference=args.risk_preference
    )

    print(
        f"\n{'Ticker':<10} | {'Direction':<10} | {'Entry (₹)':<12} | {'Stop Loss (₹)':<14} | {'Target (₹)':<12} | {'R:R':<6} | {'Confidence':<10} | {'Mode':<22}"
    )
    print("-" * 110)
    for p in proposals:
        dir_val = (
            p.direction.value if hasattr(p.direction, "value") else str(p.direction)
        )
        print(
            f"{p.ticker:<10} | {dir_val:<10} | {p.entry_price:<12.2f} | {p.stop_loss:<14.2f} | "
            f"{p.target:<12.2f} | {p.risk_reward_ratio:<6.2f} | {p.confidence:<10.2f} | {p.execution_mode:<22}"
        )
    print("-" * 110)

    # Display clean plain-English layman's summaries
    for p in proposals:
        print_layman_summary(p)


if __name__ == "__main__":
    main()
