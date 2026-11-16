"""Unit and Integration Tests for KAIROS Multi-Round Bull vs Bear Debate."""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from kairos.agents.crewai_research.bull_researcher import BullResearcher
from kairos.agents.crewai_research.bear_researcher import BearResearcher
from kairos.agents.crewai_research.research_manager import ResearchManager
from kairos.agents.crewai_research.research_crew import ResearchDebateCrew
from kairos.schemas.analyst_reports import (
    BullThesis,
    BearThesis,
    RecommendationVerdict,
    ResearchSynthesisVerdict,
    SignalStrength,
)


class TestMultiRoundDebateStructure(unittest.TestCase):
    """Verifies that configurable N rounds create the exact sequential exchange of tasks."""

    def setUp(self):
        self.crew = ResearchDebateCrew()
        self.bundle = {
            "market": {
                "ticker": "RELIANCE",
                "last_price": 1250.0,
                "support_level": 1200.0,
                "resistance_level": 1350.0,
                "indicators": {"sma_20": 1220.0, "rsi_14": 55.0},
            },
            "fundamentals": {
                "revenue": 10572190000000.0,
                "profit_margins": 0.08,
                "solvency_health": "ROBUST",
            },
            "sentiment": {"retail_bull_ratio": 0.65},
            "news": {"key_catalysts": ["Telecom growth"], "regulatory_and_litigation_risks": []},
        }

    def test_task_generation_for_n_rounds(self):
        """Verifies that N=3 creates 2*3 + 1 = 7 sequential tasks with proper context chaining."""
        ticker = "RELIANCE"
        num_rounds = 3

        debate_tasks = []
        last_bull_task = None
        last_bear_task = None

        for r in range(1, num_rounds + 1):
            if r == 1:
                b_task = self.crew.bull_researcher.create_task(ticker, self.bundle, round_num=1)
                br_task = self.crew.bear_researcher.create_task(ticker, self.bundle, round_num=1, context=[b_task])
            else:
                b_task = self.crew.bull_researcher.create_task(ticker, self.bundle, round_num=r, context=[last_bear_task])
                br_task = self.crew.bear_researcher.create_task(ticker, self.bundle, round_num=r, context=[b_task])

            debate_tasks.extend([b_task, br_task])
            last_bull_task = b_task
            last_bear_task = br_task

        manager_task = self.crew.research_manager.create_task(
            ticker, self.bundle, context=debate_tasks, total_rounds=num_rounds
        )
        all_tasks = debate_tasks + [manager_task]

        self.assertEqual(len(all_tasks), 7)
        # Check chaining:
        # Bear 1 has Bull 1 in context
        self.assertEqual(all_tasks[1].context, [all_tasks[0]])
        # Bull 2 has Bear 1 in context
        self.assertEqual(all_tasks[2].context, [all_tasks[1]])
        # Bear 2 has Bull 2 in context
        self.assertEqual(all_tasks[3].context, [all_tasks[2]])
        # Bull 3 has Bear 2 in context
        self.assertEqual(all_tasks[4].context, [all_tasks[3]])
        # Bear 3 has Bull 3 in context
        self.assertEqual(all_tasks[5].context, [all_tasks[4]])
        # Manager has all 6 debate tasks in context
        self.assertEqual(len(all_tasks[6].context), 6)

    def test_deterministic_multi_round_exchange(self):
        """Verifies that the deterministic engine performs multi-round argument exchange."""
        verdict = self.crew.conduct_debate("RELIANCE", self.bundle, force_fallback=True, rounds=3)

        self.assertIsInstance(verdict, ResearchSynthesisVerdict)
        self.assertEqual(verdict.ticker, "RELIANCE")
        self.assertEqual(verdict.execution_mode, "DETERMINISTIC_FALLBACK")
        self.assertEqual(verdict.debate_rounds, 3)
        self.assertIn(verdict.recommendation, [RecommendationVerdict.OVERWEIGHT, RecommendationVerdict.NEUTRAL, RecommendationVerdict.UNDERWEIGHT])

    def test_env_var_configurable_rounds(self):
        """Verifies that KAIROS_DEBATE_ROUNDS environment variable controls round count."""
        with patch.dict(os.environ, {"KAIROS_DEBATE_ROUNDS": "4"}):
            verdict = self.crew.conduct_debate("RELIANCE", self.bundle, force_fallback=True)
            self.assertEqual(verdict.debate_rounds, 4)

    def test_rebuttal_generation_methods(self):
        """Verifies Bull and Bear rebuttal methods."""
        bull_1 = self.crew.bull_researcher.generate_bull_thesis("RELIANCE", self.bundle)
        bear_1 = self.crew.bear_researcher.generate_bear_thesis("RELIANCE", self.bundle)

        self.assertEqual(bull_1.debate_round, 1)
        self.assertEqual(bear_1.debate_round, 1)

        bull_2 = self.crew.bull_researcher.generate_bull_rebuttal(bull_1, bear_1, self.bundle, round_num=2)
        bear_2 = self.crew.bear_researcher.generate_bear_rebuttal(bear_1, bull_2, self.bundle, round_num=2)

        self.assertEqual(bull_2.debate_round, 2)
        self.assertEqual(bear_2.debate_round, 2)
        self.assertIn("Round 2", bull_2.primary_arguments[0])
        self.assertIn("Round 2", bear_2.primary_arguments[0])

    def test_concise_prompts_and_token_bounds(self):
        """Verifies that Bull, Bear, and Manager task descriptions contain token limit constraints."""
        b_task = self.crew.bull_researcher.create_task("RELIANCE", self.bundle, round_num=1)
        br_task = self.crew.bear_researcher.create_task("RELIANCE", self.bundle, round_num=1)
        mgr_task = self.crew.research_manager.create_task("RELIANCE", self.bundle, total_rounds=2)

        self.assertIn("150 tokens", b_task.description)
        self.assertIn("150 tokens", br_task.description)
        self.assertIn("200 tokens", mgr_task.description)
        # Ensure only relevant data passed
        self.assertIn("Price ₹", b_task.description)
        self.assertIn("Debt/Equity", br_task.description)

    def test_bounded_retries_and_truthful_fallback_on_rate_limit(self):
        """Verifies that temporary rate limits trigger bounded retries and truthfully fall back to DETERMINISTIC_FALLBACK."""
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk-mock-key", "CREWAI_MAX_RETRIES": "1", "CREWAI_BACKOFF_SECONDS": "0.01"}):
            with patch("crewai.Crew.kickoff") as mock_kickoff:
                mock_kickoff.side_effect = RuntimeError("429 rate_limit_exceeded: Please try again in 0.05s")
                verdict = self.crew.conduct_debate("RELIANCE", self.bundle)

                # Must retry boundedly
                self.assertGreaterEqual(mock_kickoff.call_count, 2)
                # Must never label deterministic results as live AI
                self.assertEqual(verdict.execution_mode, "DETERMINISTIC_FALLBACK")
                self.assertEqual(verdict.ticker, "RELIANCE")


if __name__ == "__main__":
    unittest.main()

