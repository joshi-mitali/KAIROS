"""CrewAI Research Crew coordinating Bull, Bear, and Manager Agents.
Implements the ARGUE workflow and A2A inter-framework message handling.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from kairos.agents.crewai_research.crewai_patch import ensure_crewai_patched

ensure_crewai_patched()

from crewai import Crew, Process, Task
from kairos.a2a.broker import A2AMessagingHub, default_a2a_hub
from kairos.a2a.contract import (
    A2AMessageType,
    A2AResponseEnvelope,
    A2AStatus,
    A2ATaskEnvelope,
    generate_trace_id,
)
from kairos.agents.adk_analysts.base_analyst import (
    _global_rate_limiter,
    extract_retry_after,
    is_model_limit_exceeded,
)
from kairos.agents.crewai_research.bear_researcher import BearResearcher
from kairos.agents.crewai_research.bull_researcher import BullResearcher
from kairos.agents.crewai_research.research_manager import ResearchManager
from kairos.agents.crewai_research.runtime import UnavailableLLM, create_research_llm
from kairos.observability.callbacks import CallbackManager
from kairos.observability.langfuse_tracing import traced
from kairos.schemas.analyst_reports import ResearchSynthesisVerdict
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.crewai.crew")


def print_debate_transcript(
    ticker: str,
    num_rounds: int,
    rounds_data: List[Dict[str, Any]],
    verdict: ResearchSynthesisVerdict,
) -> None:
    """Prints the complete multi-round Bull vs Bear debate and Manager verdict to terminal."""
    mode = getattr(verdict, "execution_mode", "UNKNOWN")
    print("\n" + "=" * 84)
    print(f"  CREWAI MULTI-ROUND ARGUE STAGE: BULL VS BEAR DEBATE — {ticker}")
    print(f"  Debate Rounds: {num_rounds} | Execution Mode: {mode}")
    print("=" * 84)

    for r_entry in rounds_data:
        r_num = r_entry.get("round", 1)
        bull = r_entry.get("bull_argument", {})
        bear = r_entry.get("bear_counterargument", {})

        round_title = (
            "INITIAL THESES" if r_num == 1 else f"REBUTTALS & DEFENSES (ROUND {r_num})"
        )
        print(f"\n" + "-" * 84)
        print(f"  ROUND {r_num}: {round_title}")
        print("-" * 84)

        # Bull Output
        bull_upside = bull.get("upside_potential_pct", "N/A")
        bull_conv = bull.get("conviction_level", "MODERATE")
        if hasattr(bull_conv, "value"):
            bull_conv = bull_conv.value
        print(
            f"\n  [BULL RESEARCHER] (Upside Target: +{bull_upside}% | Conviction: {bull_conv})"
        )
        if "primary_arguments" in bull and bull["primary_arguments"]:
            print("  • Arguments & Growth Drivers:")
            for arg in bull["primary_arguments"]:
                print(f"    - {arg}")
        if "catalysts" in bull and bull["catalysts"]:
            print(f"  • Key Growth Catalysts: {', '.join(bull['catalysts'])}")
        if "acknowledged_risks" in bull and bull["acknowledged_risks"]:
            print(f"  • Acknowledged Risks:   {', '.join(bull['acknowledged_risks'])}")

        # Bear Output
        bear_downside = bear.get("downside_risk_pct", "N/A")
        bear_conv = bear.get("conviction_level", "MODERATE")
        if hasattr(bear_conv, "value"):
            bear_conv = bear_conv.value
        print(
            f"\n  [BEAR RESEARCHER] (Downside Risk: {bear_downside}% | Conviction: {bear_conv})"
        )
        if "primary_arguments" in bear and bear["primary_arguments"]:
            print("  • Counterarguments & Identified Risks:")
            for arg in bear["primary_arguments"]:
                print(f"    - {arg}")
        if "vulnerabilities" in bear and bear["vulnerabilities"]:
            print(f"  • Critical Vulnerabilities: {', '.join(bear['vulnerabilities'])}")
        if "trigger_events" in bear and bear["trigger_events"]:
            print(f"  • Sell-Off Triggers:        {', '.join(bear['trigger_events'])}")

    # Research Manager Final Synthesis & Stance
    rec = (
        verdict.recommendation.value
        if hasattr(verdict.recommendation, "value")
        else str(verdict.recommendation)
    )
    conv = (
        verdict.conviction.value
        if hasattr(verdict.conviction, "value")
        else str(verdict.conviction)
    )
    print("\n" + "=" * 84)
    print(
        f"  RESEARCH MANAGER DELIBERATION & FINAL VERDICT: {rec} (Conviction: {conv})"
    )
    print("=" * 84)
    print(f"  • Bull Summary:      {verdict.bull_summary}")
    print(f"  • Bear Summary:      {verdict.bear_summary}")
    print(f"  • Synthesis Rationale:\n    {verdict.synthesis_rationale}")
    if verdict.key_decision_factors:
        print("  • Key Decision Factors:")
        for idx, factor in enumerate(verdict.key_decision_factors, 1):
            print(f"    {idx}. {factor}")
    if verdict.limitations:
        print(f"  • Limitations Noted:  {', '.join(verdict.limitations)}")
    print("=" * 84 + "\n")


def save_debate_transcript(
    ticker: str,
    trace_id: str,
    num_rounds: int,
    rounds_data: List[Dict[str, Any]],
    verdict: ResearchSynthesisVerdict,
    output_path: Union[str, Path] = "data/processed/research_debate.json",
) -> Path:
    """Serializes the multi-round debate transcript and verdict to research_debate.json."""
    out_p = Path(output_path)
    if not out_p.is_absolute():
        workspace_root = Path(__file__).resolve().parent.parent.parent.parent
        out_p = workspace_root / out_p

    out_p.parent.mkdir(parents=True, exist_ok=True)

    def _serialize(obj):
        if hasattr(obj, "value"):
            return obj.value
        return str(obj)

    debate_entry = {
        "ticker": ticker,
        "trace_id": trace_id,
        "total_rounds": num_rounds,
        "execution_mode": getattr(verdict, "execution_mode", "UNKNOWN"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rounds": rounds_data,
        "manager_verdict": {
            "recommendation": _serialize(verdict.recommendation),
            "conviction": _serialize(verdict.conviction),
            "bull_summary": verdict.bull_summary,
            "bear_summary": verdict.bear_summary,
            "synthesis_rationale": verdict.synthesis_rationale,
            "key_decision_factors": verdict.key_decision_factors,
            "limitations": verdict.limitations,
            "data_freshness_status": verdict.data_freshness_status,
        },
    }

    existing = []
    if out_p.exists():
        try:
            with open(out_p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    existing = [d for d in data if d.get("ticker") != ticker]
        except Exception:
            existing = []

    existing.append(debate_entry)

    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, default=_serialize)

    logger.info(f"Saved complete debate transcript for {ticker} to {out_p}")
    return out_p


class ResearchDebateCrew:
    """Coordinates CrewAI Bull and Bear researchers and Research Manager for debate synthesis."""

    def __init__(
        self,
        callback_manager: Optional[CallbackManager] = None,
        a2a_hub: Optional[A2AMessagingHub] = None,
    ):
        self.callback_manager = callback_manager or CallbackManager()
        self.a2a_hub = a2a_hub or default_a2a_hub

        self.bull_researcher = BullResearcher(self.callback_manager)
        self.bear_researcher = BearResearcher(self.callback_manager)
        self.research_manager = ResearchManager(self.callback_manager)

        # CrewAI Crew definition
        self.crew = Crew(
            agents=[
                self.bull_researcher.crew_agent,
                self.bear_researcher.crew_agent,
                self.research_manager.crew_agent,
            ],
            tasks=[],
            process=Process.sequential,
            verbose=False,
        )

        # Register A2A handler
        self._register_a2a_handler()

    def _register_a2a_handler(self) -> None:
        """Registers A2A message handlers on the messaging hub."""
        self.a2a_hub.register_agent_handler(
            "crewai.research_crew", self.handle_a2a_debate_request
        )
        self.a2a_hub.register_agent_handler(
            "crewai.research_manager", self.handle_a2a_debate_request
        )

    @traced("debate-investment-case", "chain", fields=("ticker", "analyst_reports", "rounds", "force_fallback"))
    def conduct_debate(
        self,
        ticker: str,
        analyst_reports: Dict[str, Any],
        trace_id: Optional[str] = None,
        force_fallback: bool = False,
        rounds: Optional[int] = None,
    ) -> ResearchSynthesisVerdict:
        """Executes the multi-round ARGUE debate between Bull and Bear across configurable N rounds,
        moderated and synthesized by the Research Manager.
        """
        trace_id = trace_id or generate_trace_id()
        ticker = ticker.upper().strip()

        # Configurable N debate rounds (defaults to environment or 2)
        num_rounds = (
            rounds
            if rounds is not None
            else int(
                os.environ.get(
                    "KAIROS_DEBATE_ROUNDS", os.environ.get("DEBATE_ROUNDS", "2")
                )
            )
        )
        num_rounds = max(1, num_rounds)

        self.callback_manager.dispatch("on_debate_start", ticker, trace_id)

        # 1. Create multi-round CrewAI debate tasks across N rounds
        debate_tasks: List[Task] = []
        last_bull_task: Optional[Task] = None
        last_bear_task: Optional[Task] = None

        for r in range(1, num_rounds + 1):
            if r == 1:
                b_task = self.bull_researcher.create_task(
                    ticker, analyst_reports, round_num=1
                )
                br_task = self.bear_researcher.create_task(
                    ticker, analyst_reports, round_num=1, context=[b_task]
                )
            else:
                b_task = self.bull_researcher.create_task(
                    ticker, analyst_reports, round_num=r, context=[last_bear_task]
                )
                br_task = self.bear_researcher.create_task(
                    ticker, analyst_reports, round_num=r, context=[b_task]
                )

            debate_tasks.extend([b_task, br_task])
            last_bull_task = b_task
            last_bear_task = br_task

        manager_task = self.research_manager.create_task(
            ticker, analyst_reports, context=debate_tasks, total_rounds=num_rounds
        )
        all_crew_tasks = debate_tasks + [manager_task]
        for task in all_crew_tasks:
            role = task.agent.role
            def report_task(output, role=role):
                parsed = getattr(output, "pydantic", None)
                self.callback_manager.dispatch("on_research_task", role, parsed.model_dump(mode="json") if parsed else {"summary": str(getattr(output, "raw", output))}, trace_id)
            task.callback = report_task

        # Refresh model settings without replacing an explicitly injected test/custom model.
        is_mock = (
            getattr(self.research_manager.crew_agent, "_is_mock_llm", False)
            or type(self.research_manager.crew_agent.llm).__name__ == "MockDebateLLM"
        )
        if not is_mock and (
            os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEYS") or os.environ.get("GEMINI_API_KEY")
        ):
            llm = create_research_llm()
            if not isinstance(llm, UnavailableLLM):
                for agent in [
                    self.bull_researcher.crew_agent,
                    self.bear_researcher.crew_agent,
                    self.research_manager.crew_agent,
                ]:
                    agent.llm = llm
                    agent.function_calling_llm = llm
                self.research_manager.crew_agent._custom_llm_assigned = True

        # 3. Assemble the crew with multi-round tasks
        debate_crew = Crew(
            agents=[
                self.bull_researcher.crew_agent,
                self.bear_researcher.crew_agent,
                self.research_manager.crew_agent,
            ],
            tasks=all_crew_tasks,
            process=Process.sequential,
            verbose=False,
        )

        verdict: Optional[ResearchSynthesisVerdict] = None
        rounds_data: List[Dict[str, Any]] = []

        # 4. If an LLM is active on the agents and not force_fallback, execute via Crew.kickoff()
        has_api_key = bool(
            os.environ.get("GROQ_API_KEY")
            or os.environ.get("GROQ_API_KEYS")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        has_custom_llm = getattr(
            self.research_manager.crew_agent, "_custom_llm_assigned", False
        )

        if (has_api_key or has_custom_llm) and not force_fallback:
            max_crew_retries = int(os.environ.get("CREWAI_MAX_RETRIES", "2"))
            backoff_sec = float(os.environ.get("CREWAI_BACKOFF_SECONDS", "2.0"))

            for attempt in range(max_crew_retries + 1):
                try:
                    # Prevent overlapping requests and burst rate limits
                    _global_rate_limiter.acquire()

                    attempt_label = (
                        f" (attempt {attempt + 1}/{max_crew_retries + 1})"
                        if attempt > 0
                        else ""
                    )
                    print(
                        f"  -> [crewai.research_crew] Executing {num_rounds}-round multi-agent debate via Crew.kickoff(){attempt_label}...",
                        flush=True,
                    )
                    logger.info(
                        f"Executing CrewAI {num_rounds}-round debate via Crew.kickoff() for {ticker}{attempt_label}..."
                    )

                    from kairos.observability.crew_events import monitor_tasks
                    with monitor_tasks(all_crew_tasks, self.callback_manager, trace_id):
                        crew_output = debate_crew.kickoff()
                    if manager_task.output and manager_task.output.pydantic:
                        verdict = manager_task.output.pydantic
                    elif crew_output and getattr(crew_output, "pydantic", None):
                        verdict = crew_output.pydantic
                    elif crew_output and getattr(crew_output, "raw", None):
                        raw_str = crew_output.raw.strip()
                        if raw_str.startswith("```json"):
                            raw_str = (
                                raw_str.split("```json")[1].split("```")[0].strip()
                            )
                        elif raw_str.startswith("```"):
                            raw_str = raw_str.split("```")[1].split("```")[0].strip()
                        data = json.loads(raw_str)
                        verdict = ResearchSynthesisVerdict.model_validate(data)

                    # Extract actual CrewAI outputs for each debate round
                    for r in range(1, num_rounds + 1):
                        b_idx = 2 * (r - 1)
                        br_idx = 2 * (r - 1) + 1
                        b_t = debate_tasks[b_idx] if b_idx < len(debate_tasks) else None
                        br_t = (
                            debate_tasks[br_idx] if br_idx < len(debate_tasks) else None
                        )

                        b_dict = {}
                        if b_t and b_t.output:
                            if getattr(b_t.output, "pydantic", None):
                                b_dict = b_t.output.pydantic.model_dump()
                            elif getattr(b_t.output, "raw", None):
                                b_dict = {
                                    "speaker": "Bull Researcher",
                                    "primary_arguments": [b_t.output.raw],
                                }
                        if b_dict:
                            b_dict["execution_mode"] = "LIVE_CREWAI_LLM"

                        br_dict = {}
                        if br_t and br_t.output:
                            if getattr(br_t.output, "pydantic", None):
                                br_dict = br_t.output.pydantic.model_dump()
                            elif getattr(br_t.output, "raw", None):
                                br_dict = {
                                    "speaker": "Bear Researcher",
                                    "primary_arguments": [br_t.output.raw],
                                }
                        if br_dict:
                            br_dict["execution_mode"] = "LIVE_CREWAI_LLM"

                        rounds_data.append(
                            {
                                "round": r,
                                "bull_argument": b_dict,
                                "bear_counterargument": br_dict,
                            }
                        )

                    if verdict:
                        verdict.execution_mode = "LIVE_CREWAI_LLM"
                        verdict.trace_id = trace_id
                        verdict.debate_rounds = num_rounds
                        logger.info(
                            f"Crew.kickoff() completed successfully with LIVE_CREWAI_LLM verdict for {ticker} across {num_rounds} rounds."
                        )
                        break

                except Exception as e:
                    err_str = str(e)
                    is_permanent = any(
                        code in err_str
                        for code in [
                            "401",
                            "invalid_api_key",
                            "403",
                            "404",
                            "model_not_found",
                        ]
                    )
                    is_limit_exceeded = is_model_limit_exceeded(err_str)

                    if is_permanent:
                        logger.warning(
                            f"Crew.kickoff() permanent error ({err_str[:120]}). Skipping retries."
                        )
                        print(
                            f"  -> [crewai.research_crew] Permanent error ({err_str[:80]}). Skipping retries.",
                            flush=True,
                        )
                        break

                    if is_limit_exceeded:
                        logger.warning(
                            f"Crew.kickoff() exceeded model limits ({err_str[:120]}). Aborting retries."
                        )
                        print(
                            f"  -> [crewai.research_crew] Exceeded model limits. Proceeding to fallback.",
                            flush=True,
                        )
                        break

                    if attempt >= max_crew_retries:
                        logger.warning(
                            f"Crew.kickoff() failed after {max_crew_retries + 1} attempts ({err_str[:120]}). Proceeding to institutional fallback engine."
                        )
                        break

                    if "429" in err_str or "rate_limit" in err_str.lower():
                        from kairos.providers.groq import get_key_pool
                        pool = get_key_pool()
                        try:
                            old_key = getattr(self.research_manager.crew_agent.llm, "api_key", None) or pool.current()
                            pool.rate_limited(old_key, e)
                            replacement = create_research_llm()
                            if not isinstance(replacement, UnavailableLLM):
                                for researcher in [self.bull_researcher, self.bear_researcher, self.research_manager]:
                                    researcher.crew_agent.llm = replacement
                                    researcher.crew_agent.function_calling_llm = replacement
                        except Exception:
                            pass
                    wait_sec = extract_retry_after(e)
                    if wait_sec is None:
                        import random

                        wait_sec = backoff_sec * (2**attempt) + random.uniform(0.2, 0.8)

                    logger.warning(
                        f"Crew.kickoff() transient error ({err_str[:80]}). Retrying in {wait_sec:.1f}s..."
                    )
                    print(
                        f"  -> [crewai.research_crew] Rate limit / transient error. Retrying in {wait_sec:.1f}s...",
                        flush=True,
                    )
                    import time

                    time.sleep(wait_sec)
        else:
            logger.info(
                f"No active LLM credentials configured. Routing {ticker} to institutional fallback debate engine."
            )

        # 5. Deterministic institutional synthesis fallback across N rounds
        if not verdict:
            logger.error(
                f"[crewai.research_crew] Live Groq multi-round debate execution failed for {ticker}. "
                f"Activating explicit fallback engine (execution_mode=DETERMINISTIC_FALLBACK)."
            )
            print(
                f"  -> [crewai.research_crew] WARNING: Live Groq LLM failed. Explicitly activating deterministic fallback engine...",
                flush=True,
            )
            rounds_data = []

            # Round 1
            bull_thesis = self.bull_researcher.generate_bull_thesis(
                ticker=ticker,
                analyst_reports=analyst_reports,
                trace_id=trace_id,
            )
            bear_thesis = self.bear_researcher.generate_bear_thesis(
                ticker=ticker,
                analyst_reports=analyst_reports,
                trace_id=trace_id,
            )
            rounds_data.append(
                {
                    "round": 1,
                    "bull_argument": bull_thesis.model_dump(),
                    "bear_counterargument": bear_thesis.model_dump(),
                }
            )

            # Rounds 2..N
            for r in range(2, num_rounds + 1):
                bull_thesis = self.bull_researcher.generate_bull_rebuttal(
                    initial_bull=bull_thesis,
                    bear_thesis=bear_thesis,
                    analyst_reports=analyst_reports,
                    round_num=r,
                    trace_id=trace_id,
                )
                bear_thesis = self.bear_researcher.generate_bear_rebuttal(
                    initial_bear=bear_thesis,
                    bull_thesis=bull_thesis,
                    analyst_reports=analyst_reports,
                    round_num=r,
                    trace_id=trace_id,
                )
                rounds_data.append(
                    {
                        "round": r,
                        "bull_argument": bull_thesis.model_dump(),
                        "bear_counterargument": bear_thesis.model_dump(),
                    }
                )

            verdict = self.research_manager.synthesize_debate(
                bull_thesis=bull_thesis,
                bear_thesis=bear_thesis,
                analyst_reports=analyst_reports,
                trace_id=trace_id,
                total_rounds=num_rounds,
            )
            verdict.execution_mode = "DETERMINISTIC_FALLBACK"
            verdict.debate_rounds = num_rounds

        # 6. Display actual Bull vs Bear debate transcript in terminal & persist to research_debate.json
        self.callback_manager.dispatch("on_debate_transcript", ticker, rounds_data, verdict, trace_id)
        print_debate_transcript(ticker, num_rounds, rounds_data, verdict)
        save_debate_transcript(ticker, trace_id, num_rounds, rounds_data, verdict)

        return verdict

    def handle_a2a_debate_request(
        self, envelope: A2ATaskEnvelope
    ) -> A2AResponseEnvelope:
        """A2A entrypoint: handles inter-agent debate request envelopes."""
        trace_id = envelope.trace_id
        ticker = envelope.payload.get("ticker", "UNKNOWN")
        analyst_reports = envelope.payload.get("analyst_reports", {})

        try:
            verdict = self.conduct_debate(ticker, analyst_reports, trace_id=trace_id)
            return A2AResponseEnvelope(
                trace_id=trace_id,
                sender_agent="crewai.research_crew",
                status=A2AStatus.SUCCESS,
                data=verdict.model_dump(),
            )
        except Exception as e:
            logger.error(
                f"Failed to conduct debate for trace {trace_id}: {e}", exc_info=True
            )
            return A2AResponseEnvelope(
                trace_id=trace_id,
                sender_agent="crewai.research_crew",
                status=A2AStatus.ERROR,
                error_message=str(e),
            )
