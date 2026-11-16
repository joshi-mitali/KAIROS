"""Unit and Integration Tests for KAIROS Phase 3 Trader Agent."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from kairos.agents.trader_agent import TraderAgent
from kairos.schemas.analyst_reports import RecommendationVerdict, ResearchSynthesisVerdict, SignalStrength
from kairos.schemas.trading_proposal import (
    TradeDirection,
    TradingProposal,
    build_layman_summary,
    format_layman_summary_terminal,
)


class TestTradingProposalSchema(unittest.TestCase):
    """Verifies schema validation, normalizers, and mandatory compliance fields."""

    def test_schema_valid_construction(self):
        proposal = TradingProposal(
            ticker="RELIANCE",
            direction=TradeDirection.BUY,
            entry_price=1250.0,
            stop_loss=1190.0,
            target=1380.0,
            time_horizon="3-6 MONTHS",
            confidence=0.85,
            rationale="Robust earnings momentum and technical breakout above 20-day SMA.",
            data_freshness="CURRENT_OCTOBER_2026_AUDITED (15_MIN_DELAYED)",
            risk_warnings=[
                "Execution simulated. Intraday quote latency of 15 minutes applies.",
                "Support breakdown at ₹1190 invalidates trade thesis.",
            ],
            risk_reward_ratio=2.17,
        )
        self.assertEqual(proposal.ticker, "RELIANCE")
        self.assertEqual(proposal.direction, TradeDirection.BUY)
        self.assertEqual(proposal.entry_price, 1250.0)
        self.assertEqual(proposal.stop_loss, 1190.0)
        self.assertEqual(proposal.target, 1380.0)
        self.assertEqual(proposal.confidence, 0.85)
        self.assertIn("simulated", proposal.disclaimer.lower())
        self.assertEqual(proposal.status, "SIMULATED_PROPOSAL_ONLY")
        self.assertEqual(proposal.order_type, "LIMIT")

    def test_direction_normalizer(self):
        p1 = TradingProposal(
            ticker="TCS",
            direction="OVERWEIGHT",
            entry_price=3500.0,
            stop_loss=3350.0,
            target=3800.0,
            time_horizon="3-6 MONTHS",
            confidence="STRONG",
            rationale="Overweight thesis translates to BUY limit order.",
            data_freshness="CURRENT",
            risk_warnings=["General market volatility"],
        )
        self.assertEqual(p1.direction, TradeDirection.BUY)
        self.assertEqual(p1.confidence, 0.85)

        p2 = TradingProposal(
            ticker="INFY",
            direction="UNDERWEIGHT",
            entry_price=1500.0,
            stop_loss=1580.0,
            target=1350.0,
            time_horizon="1-3 MONTHS",
            confidence="MODERATE",
            rationale="Underweight thesis translates to SELL limit order.",
            data_freshness="CURRENT",
            risk_warnings=["Client discretionary spending risk"],
        )
        self.assertEqual(p2.direction, TradeDirection.SELL)
        self.assertEqual(p2.confidence, 0.65)


class TestTraderAgentDeterministicEngine(unittest.TestCase):
    """Verifies quantitative calculations for entry, stop-loss, target, and risk-reward."""

    def setUp(self):
        # Enforce deterministic mode by patching API keys for fast offline unit tests
        self.env_patcher = patch.dict(os.environ, {"GROQ_API_KEY": "", "GEMINI_API_KEY": ""})
        self.env_patcher.start()
        self.agent = TraderAgent()
        self.analyst_bundle = {
            "market": {
                "ticker": "RELIANCE",
                "last_price": 1250.0,
                "support_level": 1200.0,
                "resistance_level": 1350.0,
                "quote_delay": "15_MIN_DELAYED",
            },
            "fundamentals": {
                "revenue": 10572190000000.0,
                "profit_margins": 0.08,
                "solvency_health": "ROBUST",
            },
            "sentiment": {
                "retail_bull_ratio": 0.70,
                "overall_sentiment": "BULLISH",
            },
            "news": {
                "key_catalysts": ["Telecom ARPU expansion", "Retail store growth"],
                "regulatory_and_litigation_risks": ["Crude windfall tax review"],
            },
        }

    def tearDown(self):
        self.env_patcher.stop()

    def test_overweight_verdict_generates_buy_proposal(self):
        verdict = {
            "recommendation": "OVERWEIGHT",
            "conviction": "STRONG",
            "synthesis_rationale": "High-conviction long opportunity with favorable margin profile.",
            "data_freshness_status": "CURRENT_OCTOBER_2026_AUDITED",
            "limitations": ["Quote delay of 15 min"],
        }
        proposal = self.agent.generate_deterministic_proposal("RELIANCE", self.analyst_bundle, verdict)

        self.assertIsInstance(proposal, TradingProposal)
        self.assertEqual(proposal.ticker, "RELIANCE")
        self.assertEqual(proposal.direction, TradeDirection.BUY)
        self.assertEqual(proposal.entry_price, 1250.0)
        self.assertLess(proposal.stop_loss, proposal.entry_price)
        self.assertGreater(proposal.target, proposal.entry_price)
        self.assertGreaterEqual(proposal.risk_reward_ratio, 1.0)
        self.assertEqual(proposal.confidence, 0.80)
        self.assertEqual(proposal.execution_mode, "DETERMINISTIC_FALLBACK")
        self.assertIn("NO REAL TRADING", " ".join(proposal.risk_warnings).upper())

    def test_underweight_verdict_generates_sell_proposal(self):
        verdict = {
            "recommendation": "UNDERWEIGHT",
            "conviction": "MODERATE",
            "synthesis_rationale": "Downside exposure due to debt-to-equity leverage.",
            "data_freshness_status": "CURRENT_OCTOBER_2026_AUDITED",
        }
        proposal = self.agent.generate_deterministic_proposal("RELIANCE", self.analyst_bundle, verdict)

        self.assertEqual(proposal.direction, TradeDirection.SELL)
        self.assertEqual(proposal.entry_price, 1250.0)
        self.assertGreater(proposal.stop_loss, proposal.entry_price)
        self.assertLess(proposal.target, proposal.entry_price)
        self.assertGreaterEqual(proposal.risk_reward_ratio, 1.0)
        self.assertEqual(proposal.confidence, 0.60)

    def test_neutral_verdict_generates_hold_proposal(self):
        verdict = {
            "recommendation": "NEUTRAL",
            "conviction": "MODERATE",
            "synthesis_rationale": "Symmetric risk profile. No trade edge.",
            "data_freshness_status": "CURRENT_OCTOBER_2026_AUDITED",
        }
        proposal = self.agent.generate_deterministic_proposal("RELIANCE", self.analyst_bundle, verdict)

        self.assertEqual(proposal.direction, TradeDirection.HOLD)
        self.assertEqual(proposal.confidence, 0.50)
        self.assertIn("HOLD", proposal.rationale)

    def test_risk_preference_adaptation(self):
        verdict = {
            "recommendation": "OVERWEIGHT",
            "conviction": "STRONG",
            "synthesis_rationale": "High upside thesis.",
        }
        # 1. Conservative
        p_cons = self.agent.generate_deterministic_proposal(
            "RELIANCE", self.analyst_bundle, verdict, risk_preference="CONSERVATIVE"
        )
        self.assertEqual(p_cons.risk_preference, "CONSERVATIVE")
        self.assertIn("1-2%", p_cons.position_sizing)
        self.assertIn("tightened", p_cons.preference_influence.lower())
        self.assertLessEqual(p_cons.entry_price, 1250.0)

        # 2. Aggressive
        p_aggr = self.agent.generate_deterministic_proposal(
            "RELIANCE", self.analyst_bundle, verdict, risk_preference="AGGRESSIVE"
        )
        self.assertEqual(p_aggr.risk_preference, "AGGRESSIVE")
        self.assertIn("6-8%", p_aggr.position_sizing)
        self.assertIn("wider", p_aggr.preference_influence.lower())
        # Aggressive stop-loss has wider buffer than conservative
        self.assertLess(p_aggr.stop_loss, p_cons.stop_loss)
        # Aggressive target is higher than conservative
        self.assertGreater(p_aggr.target, p_cons.target)

        # 3. Default to Neutral
        p_default = self.agent.generate_deterministic_proposal(
            "RELIANCE", self.analyst_bundle, verdict
        )
        self.assertEqual(p_default.risk_preference, "NEUTRAL")
        self.assertIn("3-5%", p_default.position_sizing)


class TestTraderAgentGroqInvocation(unittest.TestCase):
    """Verifies Groq LLM integration and mock response handling."""

    def test_live_groq_mock_response_validation(self):
        agent = TraderAgent()
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "ticker": "TCS",
            "direction": "BUY",
            "entry_price": 2496.90,
            "stop_loss": 2350.00,
            "target": 2850.00,
            "time_horizon": "3-6 MONTHS",
            "confidence": 0.85,
            "rationale": "Live Groq model proposal: Strong 18.4% net margins with technical support holding.",
            "data_freshness": "CURRENT_OCTOBER_2026",
            "risk_warnings": [
                "Intraday quote delay of 15 min",
                "Sluggish discretionary IT spending",
                "Strictly simulated research proposal only",
            ],
            "risk_reward_ratio": 2.40,
            "order_type": "LIMIT",
            "status": "SIMULATED_PROPOSAL_ONLY",
            "disclaimer": "Simulated proposal. No real trade execution.",
        })
        mock_completion.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_completion
        agent.groq_client = mock_client

        bundle = {"market": {"last_price": 2496.90, "support_level": 2350.0, "resistance_level": 2800.0}}
        verdict = {"recommendation": "OVERWEIGHT", "conviction": "STRONG", "data_freshness_status": "CURRENT"}

        proposal = agent.generate_proposal("TCS", bundle, verdict)
        self.assertEqual(proposal.execution_mode, "LIVE_GROQ_MODEL")
        self.assertEqual(proposal.ticker, "TCS")
        self.assertEqual(proposal.direction, TradeDirection.BUY)
        self.assertEqual(proposal.entry_price, 2496.90)
        expected = agent.generate_deterministic_proposal("TCS", bundle, verdict, proposal.generated_at)
        self.assertEqual(proposal.stop_loss, expected.stop_loss)
        self.assertEqual(proposal.target, expected.target)
        self.assertEqual(proposal.confidence, expected.confidence)
        self.assertIn("Live Groq model proposal", proposal.rationale)

    def test_groq_error_falls_back_to_deterministic(self):
        agent = TraderAgent()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("401 invalid_api_key: Invalid API Key")
        agent.groq_client = mock_client

        bundle = {"market": {"last_price": 1200.0, "support_level": 1150.0, "resistance_level": 1300.0}}
        verdict = {"recommendation": "OVERWEIGHT", "conviction": "STRONG", "data_freshness_status": "CURRENT"}

        proposal = agent.generate_proposal("RELIANCE", bundle, verdict)
        self.assertEqual(proposal.execution_mode, "DETERMINISTIC_FALLBACK")
        self.assertEqual(proposal.ticker, "RELIANCE")
        self.assertEqual(proposal.direction, TradeDirection.BUY)


class TestTraderAgentFileOperations(unittest.TestCase):
    """Verifies loading from phase2_verdicts.json and saving to trading_proposals.json."""

    def test_generate_and_save_proposals_flow(self):
        agent = TraderAgent()
        agent.groq_client = None  # Use deterministic engine for test

        sample_verdicts = [
            {
                "ticker": "RELIANCE",
                "trace_id": "00-test-trace-01",
                "analyst_reports": {
                    "market": {"ticker": "RELIANCE", "last_price": 1250.0, "support_level": 1200.0, "resistance_level": 1350.0},
                    "fundamentals": {"revenue": 10572190000000.0, "profit_margins": 0.08, "solvency_health": "ROBUST"},
                    "sentiment": {"retail_bull_ratio": 0.70, "overall_sentiment": "BULLISH"},
                    "news": {"key_catalysts": ["Telecom growth"]},
                },
                "verdict": {
                    "ticker": "RELIANCE",
                    "recommendation": "OVERWEIGHT",
                    "conviction": "STRONG",
                    "synthesis_rationale": "High upside potential with defensible cash flows.",
                    "data_freshness_status": "CURRENT_OCTOBER_2026",
                    "limitations": ["Quote latency"],
                },
            }
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            v_file = Path(tmp_dir) / "phase2_verdicts.json"
            p_file = Path(tmp_dir) / "trading_proposals.json"

            with open(v_file, "w", encoding="utf-8") as f:
                json.dump(sample_verdicts, f)

            proposals = agent.generate_proposals_from_verdicts_file(v_file, p_file)

            self.assertEqual(len(proposals), 1)
            self.assertTrue(p_file.exists())

            with open(p_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)

            self.assertEqual(len(saved_data), 1)
            saved_p = saved_data[0]
            self.assertEqual(saved_p["ticker"], "RELIANCE")
            self.assertEqual(saved_p["direction"], "BUY")
            self.assertIn("entry_price", saved_p)
            self.assertIn("stop_loss", saved_p)
            self.assertIn("target", saved_p)
            self.assertIn("time_horizon", saved_p)
            self.assertIn("confidence", saved_p)
            self.assertIn("rationale", saved_p)
            self.assertIn("data_freshness", saved_p)
            self.assertIn("risk_warnings", saved_p)
            self.assertIn("SIMULATED", saved_p["status"])
            self.assertIn("layman_summary", saved_p)
            self.assertEqual(saved_p["layman_summary"]["action"], "Buy")


class TestLaymanSummary(unittest.TestCase):
    """Verifies plain-English non-technical summary generation and formatting."""

    def setUp(self):
        self.analyst_bundle = {
            "market": {
                "ticker": "RELIANCE",
                "last_price": 1250.0,
                "support_level": 1200.0,
                "resistance_level": 1350.0,
            },
            "fundamentals": {
                "profit_margins": 0.082,
                "solvency_health": "ROBUST",
            },
            "sentiment": {
                "retail_bull_ratio": 0.72,
            },
            "news": {
                "key_catalysts": ["Retail store expansion"],
                "regulatory_and_litigation_risks": ["Crude windfall tax review"],
            },
        }

    def test_buy_proposal_layman_summary(self):
        summary = build_layman_summary(
            ticker="RELIANCE",
            direction="BUY",
            entry_price=1250.0,
            stop_loss=1190.0,
            target=1380.0,
            time_horizon="3-6 MONTHS",
            confidence=0.85,
            risk_reward_ratio=2.17,
            analyst_reports=self.analyst_bundle,
        )

        # 1. Action: Buy, Hold, or Avoid
        self.assertEqual(summary["action"], "Buy")
        self.assertIn("buying", summary["action_detail"].lower())

        # 2. Why: 2-3 simple reasons
        self.assertGreaterEqual(len(summary["reasons"]), 2)
        self.assertLessEqual(len(summary["reasons"]), 3)
        reasons_text = " ".join(summary["reasons"])
        self.assertIn("profits", reasons_text.lower())
        self.assertIn("1,200", reasons_text)

        # 3. Entry price
        self.assertIn("1,250", summary["entry_price"])

        # 4. Stop-loss
        self.assertIn("1,190", summary["stop_loss"])
        self.assertIn("limit", summary["stop_loss_explanation"].lower())

        # 5. Target price
        self.assertIn("1,380", summary["target_price"])
        self.assertIn("profit", summary["target_explanation"].lower())

        # 6. Risk level: Low, Medium, or High
        self.assertIn(summary["risk_level"], ["Low", "Medium", "High"])
        self.assertTrue(len(summary["risk_explanation"]) > 10)

        # 7. Time horizon
        self.assertIn("3 to 6 months", summary["time_horizon"])

        # 8. What could go wrong: key risks in plain language
        self.assertGreaterEqual(len(summary["what_could_go_wrong"]), 2)
        risks_text = " ".join(summary["what_could_go_wrong"])
        self.assertIn("market", risks_text.lower())

        # Compliance: profit non-guarantee & non-executed
        self.assertIn("never guaranteed", summary["disclaimer"].lower())
        self.assertIn("no real trade", summary["disclaimer"].lower())

    def test_sell_proposal_maps_to_avoid(self):
        summary = build_layman_summary(
            ticker="TCS",
            direction="SELL",
            entry_price=3000.0,
            stop_loss=3150.0,
            target=2700.0,
            time_horizon="1-3 MONTHS",
            confidence=0.70,
            risk_reward_ratio=2.0,
        )
        self.assertEqual(summary["action"], "Avoid")
        self.assertEqual(summary["risk_level"], "High")
        self.assertIn("3,000", summary["entry_price"])
        self.assertIn("3,150", summary["stop_loss"])

    def test_hold_proposal_maps_to_hold(self):
        summary = build_layman_summary(
            ticker="INFY",
            direction="HOLD",
            entry_price=1500.0,
            stop_loss=1420.0,
            target=1600.0,
            time_horizon="MONITOR",
            confidence=0.50,
            risk_reward_ratio=1.0,
        )
        self.assertEqual(summary["action"], "Hold")
        self.assertEqual(summary["risk_level"], "Medium")

    def test_terminal_format_contains_all_fields(self):
        proposal = TradingProposal(
            ticker="RELIANCE",
            direction=TradeDirection.BUY,
            entry_price=1250.0,
            stop_loss=1190.0,
            target=1380.0,
            time_horizon="3-6 MONTHS",
            confidence=0.85,
            rationale="Solid earnings momentum.",
            data_freshness="CURRENT",
            risk_warnings=["Simulated proposal"],
            risk_reward_ratio=2.17,
        )
        proposal.get_layman_summary(analyst_reports=self.analyst_bundle)

        terminal_card = format_layman_summary_terminal(proposal)
        self.assertIn("What should I do?", terminal_card)
        self.assertIn("Why?", terminal_card)
        self.assertIn("Entry price:", terminal_card)
        self.assertIn("Stop-loss:", terminal_card)
        self.assertIn("Target price:", terminal_card)
        self.assertIn("Risk level:", terminal_card)
        self.assertIn("Time horizon:", terminal_card)
        self.assertIn("What could go wrong?", terminal_card)
        self.assertIn("Risk Preference:", terminal_card)
        self.assertIn("Suggested Allocation:", terminal_card)
        self.assertIn("Strategy Impact:", terminal_card)
        self.assertIn("NEVER guaranteed", terminal_card)
        self.assertIn("NO real trade", terminal_card)


if __name__ == "__main__":
    unittest.main()

