"""Comprehensive Unit and Integration Test Suite for KAIROS Phase 2.
Tests Google ADK specialist analysts (live API & deterministic fallback),
A2A messaging hub (HMAC verification, routing, tampering protection),
CrewAI research debate (Task creation, Crew.kickoff execution & fallback),
institutional guardrails, distributed tracing, and the end-to-end orchestrator.
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from kairos.a2a.broker import A2AMessagingHub
from kairos.a2a.contract import (
    A2AMessageType,
    A2AResponseEnvelope,
    A2AStatus,
    A2ATaskEnvelope,
    compute_payload_signature,
    generate_trace_id,
    verify_payload_signature,
)
from kairos.agents.adk_analysts import (
    BaseADKAnalyst,
    FundamentalsAnalyst,
    MarketAnalyst,
    NewsAnalyst,
    SentimentAnalyst,
)
from kairos.agents.crewai_research import (
    BearResearcher,
    BullResearcher,
    ResearchDebateCrew,
    ResearchManager,
)
from kairos.observability.callbacks import CallbackManager, LoggingCallback
from kairos.observability.guardrails import (
    DownsideRiskGuardrail,
    FreshnessGuardrail,
    InstitutionalGuardrailSuite,
    SchemaValidationGuardrail,
)
from kairos.observability.tracer import AgentTracer, global_tracer
from kairos.phase2_orchestrator import Phase2Orchestrator
from kairos.schemas.analyst_reports import (
    BearThesis,
    BullThesis,
    FundamentalsAnalysisReport,
    MarketAnalysisReport,
    NewsAnalysisReport,
    RecommendationVerdict,
    ResearchSynthesisVerdict,
    SentimentAnalysisReport,
    SignalStrength,
    ValuationPosture,
)


class TestADKSpecialistAnalysts(unittest.TestCase):
    """Verifies that the 4 Google ADK analyst agents correctly consume Phase 1 data."""

    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {"GROQ_API_KEY": "", "GEMINI_API_KEY": ""})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_market_analyst_reliance(self):
        analyst = MarketAnalyst()
        report = analyst.analyze("RELIANCE")
        self.assertIsInstance(report, MarketAnalysisReport)
        self.assertEqual(report.ticker, "RELIANCE")
        self.assertGreater(report.last_price, 0.0)
        self.assertGreaterEqual(report.bars_analyzed, 100)
        self.assertIn(report.quote_delay, ["15_MIN_DELAYED", "REAL_TIME"])
        self.assertGreaterEqual(report.indicators.rsi_14, 0.0)
        self.assertLessEqual(report.indicators.rsi_14, 100.0)
        self.assertGreater(report.resistance_level, report.support_level)
        self.assertTrue(len(report.key_observations) >= 3)
        self.assertIn(report.execution_mode, ["LIVE_GROQ_MODEL", "LIVE_GEMINI_MODEL", "DETERMINISTIC_FALLBACK"])

    def test_sentiment_analyst_reliance(self):
        analyst = SentimentAnalyst()
        report = analyst.analyze("RELIANCE")
        self.assertIsInstance(report, SentimentAnalysisReport)
        self.assertEqual(report.ticker, "RELIANCE")
        self.assertGreaterEqual(report.sample_size_posts, 1)
        self.assertGreaterEqual(report.sentiment_score, -1.0)
        self.assertLessEqual(report.sentiment_score, 1.0)
        self.assertGreaterEqual(report.retail_bull_ratio, 0.0)
        self.assertLessEqual(report.retail_bull_ratio, 1.0)
        self.assertTrue(report.noise_filter_applied)
        self.assertTrue(len(report.key_themes) >= 1)
        self.assertIn(report.execution_mode, ["LIVE_GROQ_MODEL", "LIVE_GEMINI_MODEL", "DETERMINISTIC_FALLBACK"])

    def test_news_analyst_reliance(self):
        analyst = NewsAnalyst()
        report = analyst.analyze("RELIANCE")
        self.assertIsInstance(report, NewsAnalysisReport)
        self.assertEqual(report.ticker, "RELIANCE")
        self.assertGreaterEqual(report.total_articles_verified, 1)
        self.assertTrue(len(report.top_verified_articles) >= 1)
        art = report.top_verified_articles[0]
        self.assertTrue(art.url.startswith("http"))
        self.assertTrue(len(art.headline) > 0)
        self.assertIn(report.execution_mode, ["LIVE_GROQ_MODEL", "LIVE_GEMINI_MODEL", "DETERMINISTIC_FALLBACK"])

    def test_fundamentals_analyst_currencies_and_standards(self):
        analyst = FundamentalsAnalyst()

        # INFY must be USD and sec-form-20f
        infy_rep = analyst.analyze("INFY")
        self.assertIsInstance(infy_rep, FundamentalsAnalysisReport)
        self.assertEqual(infy_rep.reporting_currency, "USD")
        self.assertEqual(infy_rep.filing_standard, "sec-form-20f")
        self.assertGreater(infy_rep.revenue, 0.0)
        self.assertGreater(infy_rep.total_assets, 0.0)
        self.assertIsNotNone(infy_rep.profit_margins)
        self.assertIn(infy_rep.execution_mode, ["LIVE_GROQ_MODEL", "LIVE_GEMINI_MODEL", "DETERMINISTIC_FALLBACK"])

        # RELIANCE must be INR and mca-ind-as
        rel_rep = analyst.analyze("RELIANCE")
        self.assertIsInstance(rel_rep, FundamentalsAnalysisReport)
        self.assertEqual(rel_rep.reporting_currency, "INR")
        self.assertEqual(rel_rep.filing_standard, "mca-ind-as")
        self.assertGreater(rel_rep.revenue, 0.0)


class TestGoogleADKModelInvocation(unittest.TestCase):
    """Verifies genuine Groq API and Google ADK / Gemini API invocation and fallback behavior."""

    def test_groq_invocation_success(self):
        analyst = MarketAnalyst()
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "ticker": "RELIANCE",
            "as_of_date": "2026-10-28",
            "last_price": 1210.5,
            "quote_delay": "15_MIN_DELAYED",
            "indicators": {
                "sma_20": 1195.0,
                "rsi_14": 52.0,
                "macd_line": 2.5,
                "macd_signal": 1.2,
                "macd_histogram": 1.3,
            },
            "trend_direction": "BULLISH",
            "signal_strength": "STRONG",
            "support_level": 1180.0,
            "resistance_level": 1300.0,
            "fifty_two_week_high": 1604.38,
            "fifty_two_week_low": 1152.2,
            "bars_analyzed": 2471,
            "key_observations": ["Groq Llama 3.3 model observed bullish momentum."],
        })
        mock_completion.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_completion
        analyst.groq_client = mock_client

        result = analyst.analyze("RELIANCE")
        self.assertEqual(result.execution_mode, "LIVE_GROQ_MODEL")
        self.assertEqual(result.ticker, "RELIANCE")
        self.assertNotEqual(result.last_price, 1210.5)
        self.assertIn("Groq Llama", result.key_observations[0])
        mock_client.chat.completions.create.assert_called_once()

    def test_groq_no_retry_on_401_auth_error(self):
        analyst = MarketAnalyst()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("401 invalid_api_key: Invalid API Key provided")
        analyst.groq_client = mock_client

        result = analyst.analyze("RELIANCE")
        self.assertEqual(result.execution_mode, "DETERMINISTIC_FALLBACK")
        # Permanent error must not retry
        self.assertEqual(mock_client.chat.completions.create.call_count, 1)

    def test_groq_bounded_retries_on_rate_limit(self):
        analyst = MarketAnalyst()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("429 rate_limit: Rate limit reached")
        analyst.groq_client = mock_client

        os.environ["GROQ_BACKOFF_SECONDS"] = "0.001"
        os.environ["GROQ_MAX_RETRIES"] = "2"
        try:
            result = analyst.analyze("RELIANCE")
            self.assertEqual(result.execution_mode, "DETERMINISTIC_FALLBACK")
            # Must retry at least 3 times before final fallback
            self.assertGreaterEqual(mock_client.chat.completions.create.call_count, 3)
        finally:
            os.environ.pop("GROQ_BACKOFF_SECONDS", None)
            os.environ.pop("GROQ_MAX_RETRIES", None)

    def test_groq_aborts_retries_when_request_exceeds_model_limits(self):
        analyst = MarketAnalyst()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError(
            "400 context_length_exceeded: This model's maximum context length is 8192 tokens. However, your messages resulted in 9500 tokens."
        )
        analyst.groq_client = mock_client

        result = analyst.analyze("RELIANCE")
        self.assertEqual(result.execution_mode, "DETERMINISTIC_FALLBACK")
        # Permanent model limit error must not retry
        self.assertEqual(mock_client.chat.completions.create.call_count, 1)

    def test_groq_respects_retry_after_extraction(self):
        from kairos.agents.adk_analysts.base_analyst import extract_retry_after
        # 1. From error string
        err_str = "Error code: 429 - {'error': {'message': 'Rate limit reached for model. Please try again in 1.63s'}}"
        val = extract_retry_after(RuntimeError(err_str))
        self.assertEqual(val, 1.63)

        # 2. From mock response headers
        mock_err = RuntimeError("429 Rate limited")
        mock_resp = MagicMock()
        mock_resp.headers = {"retry-after": "2.5"}
        mock_err.response = mock_resp
        val2 = extract_retry_after(mock_err)
        self.assertEqual(val2, 2.5)

    def test_schema_pruning_reduces_size(self):
        from kairos.agents.adk_analysts.base_analyst import prune_json_schema
        raw_schema = MarketAnalysisReport.model_json_schema()
        pruned = prune_json_schema(raw_schema)
        self.assertLess(len(json.dumps(pruned)), len(json.dumps(raw_schema)))
        self.assertNotIn("description", json.dumps(pruned))

    def test_gemini_invocation_success(self):
        analyst = MarketAnalyst()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_payload = {
            "ticker": "RELIANCE",
            "as_of_date": "2026-10-27",
            "last_price": 1196.2,
            "quote_delay": "15_MIN_DELAYED",
            "indicators": {
                "sma_20": 1190.23,
                "rsi_14": 46.27,
                "macd_line": -12.12,
                "macd_signal": -16.88,
                "macd_histogram": 4.76,
            },
            "trend_direction": "BULLISH",
            "signal_strength": "MODERATE",
            "support_level": 1152.2,
            "resistance_level": 1337.0,
            "fifty_two_week_high": 1604.38,
            "fifty_two_week_low": 1152.2,
            "bars_analyzed": 2471,
            "key_observations": ["Live Gemini model observed technical breakout."],
        }
        mock_response.text = json.dumps(mock_payload)
        mock_client.models.generate_content.return_value = mock_response

        analyst.groq_client = None
        analyst.gemini_client = mock_client
        result = analyst.analyze("RELIANCE")

        self.assertEqual(result.execution_mode, "LIVE_GEMINI_MODEL")
        self.assertEqual(result.ticker, "RELIANCE")
        self.assertIn("breakout", result.key_observations[0])
        mock_client.models.generate_content.assert_called_once()

    def test_gemini_invocation_fallback_on_api_error(self):
        analyst = MarketAnalyst()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("API Quota Exceeded or Auth Failure")
        analyst.groq_client = None
        analyst.gemini_client = mock_client

        fallback = analyst.run_analysis("RELIANCE")
        result = analyst.invoke_gemini_analysis("Prompt test", MarketAnalysisReport, fallback)

        # Must cleanly fall back without crashing and never masquerade as LIVE
        self.assertEqual(result.execution_mode, "DETERMINISTIC_FALLBACK")
        self.assertEqual(result.ticker, "RELIANCE")

    def test_gemini_no_retry_on_404_permanent_error(self):
        analyst = MarketAnalyst()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("404 NOT_FOUND: Model models/gemini-2.0-flash does not exist")
        analyst.groq_client = None
        analyst.gemini_client = mock_client

        result = analyst.analyze("RELIANCE")
        self.assertEqual(result.execution_mode, "DETERMINISTIC_FALLBACK")
        # Must only be called once because 404 is a permanent error
        self.assertEqual(mock_client.models.generate_content.call_count, 1)

    def test_gemini_bounded_retry_on_504_transient_error(self):
        analyst = MarketAnalyst()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("504 DEADLINE_EXCEEDED: Server deadline exceeded")
        analyst.groq_client = None
        analyst.gemini_client = mock_client

        # Speed up backoff for unit test
        os.environ["GEMINI_BACKOFF_SECONDS"] = "0.01"
        os.environ["GEMINI_MAX_RETRIES"] = "2"
        try:
            result = analyst.analyze("RELIANCE")
            self.assertEqual(result.execution_mode, "DETERMINISTIC_FALLBACK")
            # 1 initial attempt + 2 retries = 3 calls total
            self.assertEqual(mock_client.models.generate_content.call_count, 3)
        finally:
            os.environ.pop("GEMINI_BACKOFF_SECONDS", None)
            os.environ.pop("GEMINI_MAX_RETRIES", None)

    def test_sentiment_analyst_gemini_invocation(self):
        analyst = SentimentAnalyst()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "ticker": "RELIANCE",
            "overall_sentiment": "BULLISH",
            "sentiment_score": 0.45,
            "sample_size_posts": 10,
            "ticker_specific_posts_count": 8,
            "macro_context_posts_count": 2,
            "retail_bull_ratio": 0.75,
            "key_themes": ["Retail expansion into FMCG", "Strong Jio subscriber metrics"],
            "noise_filter_applied": True,
            "social_sources": ["r/IndianStockMarket"],
        })
        mock_client.models.generate_content.return_value = mock_resp
        analyst.groq_client = None
        analyst.gemini_client = mock_client
        report = analyst.analyze("RELIANCE")
        self.assertEqual(report.execution_mode, "LIVE_GEMINI_MODEL")
        self.assertEqual(report.ticker, "RELIANCE")
        self.assertAlmostEqual(report.sentiment_score, round(float(analyst._load_sentiment_data("RELIANCE")["sentiment_score"].mean()),4))
        self.assertEqual(report.key_themes[0], "Retail expansion into FMCG")

    def test_news_analyst_gemini_invocation(self):
        analyst = NewsAnalyst()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "ticker": "RELIANCE",
            "news_sentiment": "BULLISH",
            "total_articles_verified": 3,
            "key_catalysts": ["Green energy Gigafactory launch"],
            "regulatory_and_litigation_risks": ["Potential windfall tax adjustment"],
            "top_verified_articles": [
                {
                    "headline": "Reliance reports strong profit growth",
                    "summary": "Reliance Industries reported Q2 profit exceeding analyst projections.",
                    "source": "Economic Times",
                    "url": "https://economictimes.indiatimes.com/reliance-q2",
                    "published_at": "2026-10-27T10:00:00Z",
                }
            ],
        })
        mock_client.models.generate_content.return_value = mock_resp
        analyst.groq_client = None
        analyst.gemini_client = mock_client
        report = analyst.analyze("RELIANCE")
        self.assertEqual(report.execution_mode, "LIVE_GEMINI_MODEL")
        self.assertEqual(report.ticker, "RELIANCE")
        self.assertEqual(len(report.top_verified_articles), min(3,len(analyst._load_news_data("RELIANCE"))))
        self.assertNotEqual(report.top_verified_articles[0].url, "https://economictimes.indiatimes.com/reliance-q2")

    def test_fundamentals_analyst_gemini_invocation(self):
        analyst = FundamentalsAnalyst()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "ticker": "RELIANCE",
            "company_name": "RELIANCE INDUSTRIES LTD",
            "reporting_currency": "INR",
            "filing_standard": "mca-ind-as",
            "fiscal_period_end": "2026-03-31",
            "revenue": 10572190000000.0,
            "net_income": 790200000000.0,
            "total_assets": 18500000000000.0,
            "total_liabilities": 9200000000000.0,
            "operating_cash_flow": 1450000000000.0,
            "debt_to_equity": 0.48,
            "profit_margins": 0.075,
            "valuation_posture": "FAIR_VALUE",
            "solvency_health": "ROBUST",
        })
        mock_client.models.generate_content.return_value = mock_resp
        analyst.groq_client = None
        analyst.gemini_client = mock_client
        report = analyst.analyze("RELIANCE")
        self.assertEqual(report.execution_mode, "LIVE_GEMINI_MODEL")
        self.assertEqual(report.ticker, "RELIANCE")
        self.assertEqual(report.reporting_currency, "INR")


class TestA2AInteroperability(unittest.TestCase):
    """Verifies A2A envelopes, HMAC signatures, tamper protection, and broker routing."""

    def setUp(self):
        self.hub = A2AMessagingHub(secret_key="test_secret_key")

    def test_envelope_signature_and_verification(self):
        payload = {"ticker": "TCS", "last_price": 3800.0}
        sig = compute_payload_signature(payload, secret_key="test_secret_key")
        self.assertTrue(verify_payload_signature(payload, sig, secret_key="test_secret_key"))
        self.assertFalse(verify_payload_signature(payload, "invalid_sig", secret_key="test_secret_key"))

    def test_a2a_tamper_detection(self):
        envelope = A2ATaskEnvelope(
            trace_id=generate_trace_id(),
            sender_agent="google_adk.market_analyst",
            recipient_agent="crewai.bull_researcher",
            task_type=A2AMessageType.MARKET_REPORT,
            payload={"ticker": "RELIANCE", "price": 1200.0},
        )
        envelope.sign("test_secret_key")
        self.assertTrue(envelope.verify_integrity("test_secret_key"))

        # Tamper with payload
        envelope.payload["price"] = 9999.0
        self.assertFalse(envelope.verify_integrity("test_secret_key"))

        # Dispatch should reject tampered envelope
        resp = self.hub.dispatch(envelope, verify_sig=True)
        self.assertEqual(resp.status, A2AStatus.REJECTED)

    def test_a2a_unregistered_recipient_error(self):
        envelope = A2ATaskEnvelope(
            trace_id=generate_trace_id(),
            sender_agent="test.sender",
            recipient_agent="nonexistent.agent",
            task_type=A2AMessageType.MARKET_REPORT,
            payload={"action": "ping"},
        )
        envelope.sign("test_secret_key")
        resp = self.hub.dispatch(envelope, verify_sig=True)
        self.assertEqual(resp.status, A2AStatus.ERROR)
        self.assertIn("No handler registered", resp.error_message)

    def test_a2a_routing_and_audit(self):
        received_payloads = []

        def dummy_handler(env: A2ATaskEnvelope) -> A2AResponseEnvelope:
            received_payloads.append(env.payload)
            return A2AResponseEnvelope(
                trace_id=env.trace_id,
                sender_agent="test.recipient",
                status=A2AStatus.SUCCESS,
                data={"result": "OK"},
            )

        self.hub.register_agent_handler("test.recipient", dummy_handler)

        envelope = A2ATaskEnvelope(
            sender_agent="test.sender",
            recipient_agent="test.recipient",
            task_type=A2AMessageType.MARKET_REPORT,
            payload={"action": "test_echo"},
        )
        envelope.sign(self.hub.secret_key)

        resp = self.hub.dispatch(envelope)
        self.assertEqual(resp.status, A2AStatus.SUCCESS)
        self.assertEqual(len(received_payloads), 1)
        self.assertEqual(received_payloads[0]["action"], "test_echo")

        # Verify audit trail
        audit = self.hub.get_audit_trail(envelope.trace_id)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["status"], "SUCCESS")


class TestObservabilityAndGuardrails(unittest.TestCase):
    """Verifies distributed tracing, callbacks, and institutional guardrails."""

    def test_w3c_tracer_spans(self):
        tracer = AgentTracer()
        trace_id = generate_trace_id()
        self.assertTrue(trace_id.startswith("00-"))
        self.assertTrue(trace_id.endswith("-01"))

        with tracer.span("test_step_1", trace_id) as s:
            s.set_attribute("key", "val")

        spans = tracer.get_spans_for_trace(trace_id)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, "test_step_1")
        self.assertEqual(spans[0].status, "OK")

    def test_downside_risk_guardrail(self):
        guardrail = DownsideRiskGuardrail()

        # Valid negative downside
        valid_res = guardrail.evaluate({"downside_risk_pct": -12.5})
        self.assertTrue(valid_res.passed)

        # Invalid positive downside
        invalid_res = guardrail.evaluate({"downside_risk_pct": 5.0})
        self.assertFalse(invalid_res.passed)

        # Invalid extreme downside (< -100%)
        extreme_res = guardrail.evaluate({"downside_risk_pct": -105.0})
        self.assertFalse(extreme_res.passed)

    def test_schema_validation_guardrail(self):
        guardrail = SchemaValidationGuardrail(BullThesis)

        # Valid thesis
        valid_thesis = {
            "ticker": "RELIANCE",
            "target_horizon_months": 12,
            "primary_arguments": ["Strong revenue", "Solid margin"],
            "upside_potential_pct": 18.5,
            "catalysts": ["5G expansion"],
            "acknowledged_risks": ["Tariff regulation"],
            "conviction_level": "MODERATE",
            "researcher_name": "crewai.bull_researcher",
        }
        res = guardrail.evaluate(valid_thesis)
        self.assertTrue(res.passed)

        # Invalid thesis (missing primary_arguments)
        invalid_thesis = {"ticker": "RELIANCE", "upside_potential_pct": 10.0}
        res_inv = guardrail.evaluate(invalid_thesis)
        self.assertFalse(res_inv.passed)


class TestCrewAIDebateWorkflow(unittest.TestCase):
    """Verifies CrewAI Bull, Bear, and Research Manager agents, Tasks, and debate synthesis."""

    def setUp(self):
        self.bundle = {
            "market": {
                "ticker": "ICICIBANK",
                "as_of_date": "2026-10-27",
                "last_price": 1250.0,
                "quote_delay": "15_MIN_DELAYED",
                "indicators": {"sma_20": 1220.0, "rsi_14": 58.0, "macd_line": 5.0, "macd_signal": 3.0, "macd_histogram": 2.0},
                "trend_direction": "BULLISH",
                "signal_strength": "STRONG",
                "support_level": 1150.0,
                "resistance_level": 1380.0,
                "key_observations": ["Bullish moving average setup"],
            },
            "sentiment": {
                "ticker": "ICICIBANK",
                "overall_sentiment": "BULLISH",
                "sentiment_score": 0.25,
                "sample_size_posts": 10,
                "ticker_specific_posts_count": 8,
                "macro_context_posts_count": 2,
                "retail_bull_ratio": 0.70,
                "key_themes": ["Credit growth expansion"],
            },
            "news": {
                "ticker": "ICICIBANK",
                "news_sentiment": "BULLISH",
                "total_articles_verified": 5,
                "key_catalysts": ["Record net profit reported in Q2"],
                "regulatory_and_litigation_risks": ["RBI repo rate volatility"],
                "top_verified_articles": [],
            },
            "fundamentals": {
                "ticker": "ICICIBANK",
                "company_name": "ICICI BANK LTD",
                "reporting_currency": "INR",
                "filing_standard": "mca-ind-as",
                "fiscal_period_end": "2026-03-31",
                "revenue": 1800000000000.0,
                "net_income": 450000000000.0,
                "total_assets": 20000000000000.0,
                "total_liabilities": 17500000000000.0,
                "operating_cash_flow": 300000000000.0,
                "debt_to_equity": 4.5,
                "profit_margins": 0.25,
                "valuation_posture": "UNDERVALUED",
                "solvency_health": "ROBUST",
            },
        }

    def test_crewai_task_generation(self):
        bull = BullResearcher()
        bear = BearResearcher()
        manager = ResearchManager()

        b_task = bull.create_task("ICICIBANK", self.bundle)
        self.assertIn("ICICIBANK", b_task.description)
        self.assertEqual(b_task.output_pydantic, BullThesis)

        be_task = bear.create_task("ICICIBANK", self.bundle)
        self.assertIn("ICICIBANK", be_task.description)
        self.assertEqual(be_task.output_pydantic, BearThesis)

        m_task = manager.create_task("ICICIBANK", self.bundle, context=[b_task, be_task])
        self.assertIn("ICICIBANK", m_task.description)
        self.assertEqual(m_task.output_pydantic, ResearchSynthesisVerdict)
        self.assertEqual(len(m_task.context), 2)

    def test_crewai_debate_crew_fallback(self):
        crew = ResearchDebateCrew()
        verdict = crew.conduct_debate("ICICIBANK", self.bundle, force_fallback=True)
        self.assertIsInstance(verdict, ResearchSynthesisVerdict)
        self.assertEqual(verdict.ticker, "ICICIBANK")
        self.assertEqual(verdict.execution_mode, "DETERMINISTIC_FALLBACK")
        self.assertTrue(len(verdict.source_references) >= 3)
        self.assertTrue(len(verdict.limitations) >= 3)
        self.assertIn("research-only", verdict.research_only_disclaimer.lower())

    def test_crewai_debate_crew_kickoff_execution(self):
        """Tests that Crew.kickoff() runs when an LLM is active."""
        crew = ResearchDebateCrew()
        from crewai.llms.base_llm import BaseLLM

        class MockDebateLLM(BaseLLM):
            def __init__(self):
                super().__init__(model="mock-llm")

            def call(self, messages, **kwargs):
                msg_str = str(messages)
                if "ResearchSynthesisVerdict" in msg_str or "Moderator" in msg_str or "Chief Investment" in msg_str:
                    return json.dumps({
                        "ticker": "ICICIBANK",
                        "trace_id": "00-test-trace-01",
                        "recommendation": "OVERWEIGHT",
                        "conviction": "STRONG",
                        "bull_summary": "Strong retail loan growth and margin resilience",
                        "bear_summary": "Unsecured credit risk exposure and NPA uptick",
                        "synthesis_rationale": "Asymmetric 2.0x upside potential justifies overweight stance",
                        "key_decision_factors": ["Credit growth", "Robust net interest margin"],
                        "manager_name": "crewai.research_manager",
                        "deliberation_timestamp": "2026-10-27T17:00:00Z",
                        "generation_timestamp": "2026-10-27T17:00:00Z",
                        "data_freshness_status": "CURRENT_AS_OF_2026-10-27",
                        "source_references": ["Yahoo Finance MCP", "MCA Ind-AS"],
                        "limitations": ["Delayed quote feed", "Recency bias in social sentiment"],
                        "research_only_disclaimer": "Strictly research-only institutional investment synthesis.",
                        "debate_rounds": 2,
                        "execution_mode": "LIVE_CREWAI_LLM",
                    })
                elif "BearThesis" in msg_str or "Bear Risk Researcher" in msg_str:
                    return json.dumps({
                        "ticker": "ICICIBANK",
                        "primary_arguments": ["Macro interest rate sensitivity"],
                        "downside_risk_pct": -10.0,
                        "vulnerabilities": ["Unsecured retail debt leverage"],
                        "trigger_events": ["RBI tightening decree"],
                        "conviction_level": "MODERATE",
                        "researcher_name": "crewai.bear_researcher",
                        "debate_round": 1,
                    })
                else:
                    return json.dumps({
                        "ticker": "ICICIBANK",
                        "target_horizon_months": 12,
                        "primary_arguments": ["Strong credit growth in retail and SME portfolios"],
                        "upside_potential_pct": 18.5,
                        "catalysts": ["Retail branch expansion"],
                        "acknowledged_risks": ["Repo rate hikes"],
                        "conviction_level": "STRONG",
                        "researcher_name": "crewai.bull_researcher",
                        "debate_round": 1,
                    })

        mock_llm = MockDebateLLM()
        crew.research_manager.crew_agent.llm = mock_llm
        crew.bull_researcher.crew_agent.llm = mock_llm
        crew.bear_researcher.crew_agent.llm = mock_llm
        crew.research_manager.crew_agent._custom_llm_assigned = True

        verdict = crew.conduct_debate("ICICIBANK", self.bundle)
        self.assertIsInstance(verdict, ResearchSynthesisVerdict)
        self.assertEqual(verdict.execution_mode, "LIVE_CREWAI_LLM")
        self.assertEqual(verdict.recommendation, RecommendationVerdict.OVERWEIGHT)


class TestVerdictSchemaCompleteness(unittest.TestCase):
    """Verifies all mandatory audit fields in generated verdicts."""

    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {"GROQ_API_KEY": "", "GEMINI_API_KEY": ""})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_verdict_schema_audit_fields(self):
        orchestrator = Phase2Orchestrator()
        result = orchestrator.analyze_ticker("RELIANCE")
        v = result["verdict"]

        self.assertIn("data_freshness_status", v)
        self.assertTrue(len(v["data_freshness_status"]) > 5)

        self.assertIn("source_references", v)
        self.assertGreaterEqual(len(v["source_references"]), 3)

        self.assertIn("limitations", v)
        self.assertGreaterEqual(len(v["limitations"]), 3)

        self.assertIn("research_only_disclaimer", v)
        self.assertIn("research-only", v["research_only_disclaimer"].lower())

        self.assertIn("generation_timestamp", v)
        self.assertIn("execution_mode", v)
        self.assertIn(v["execution_mode"], ["LIVE_CREWAI_LLM", "DETERMINISTIC_FALLBACK"])


class TestLiveAPIIntegration(unittest.TestCase):
    """Separate live API integration tests. Skipped unless RUN_LIVE_TESTS is explicitly set to true."""

    @unittest.skipUnless(os.environ.get("RUN_LIVE_TESTS") == "true" and os.environ.get("GEMINI_API_KEY"), "Requires live GEMINI_API_KEY and RUN_LIVE_TESTS=true")
    def test_live_gemini_market_analyst_call(self):
        analyst = MarketAnalyst()
        self.assertIsNotNone(analyst.gemini_client, "Gemini client must initialize with live API key")
        report = analyst.analyze("RELIANCE")
        self.assertEqual(report.execution_mode, "LIVE_GEMINI_MODEL")
        self.assertGreater(report.last_price, 0.0)

    @unittest.skipUnless(os.environ.get("RUN_LIVE_TESTS") == "true" and os.environ.get("GEMINI_API_KEY"), "Requires live GEMINI_API_KEY and RUN_LIVE_TESTS=true")
    def test_live_gemini_sentiment_analyst_call(self):
        analyst = SentimentAnalyst()
        self.assertIsNotNone(analyst.gemini_client, "Gemini client must initialize with live API key")
        report = analyst.analyze("RELIANCE")
        self.assertEqual(report.execution_mode, "LIVE_GEMINI_MODEL")
        self.assertGreaterEqual(report.sample_size_posts, 1)

    @unittest.skipUnless(os.environ.get("RUN_LIVE_TESTS") == "true" and os.environ.get("GEMINI_API_KEY"), "Requires live GEMINI_API_KEY and RUN_LIVE_TESTS=true")
    def test_live_gemini_news_analyst_call(self):
        analyst = NewsAnalyst()
        self.assertIsNotNone(analyst.gemini_client, "Gemini client must initialize with live API key")
        report = analyst.analyze("RELIANCE")
        self.assertEqual(report.execution_mode, "LIVE_GEMINI_MODEL")
        self.assertGreaterEqual(report.total_articles_verified, 1)

    @unittest.skipUnless(os.environ.get("RUN_LIVE_TESTS") == "true" and os.environ.get("GEMINI_API_KEY"), "Requires live GEMINI_API_KEY and RUN_LIVE_TESTS=true")
    def test_live_gemini_fundamentals_analyst_call(self):
        analyst = FundamentalsAnalyst()
        self.assertIsNotNone(analyst.gemini_client, "Gemini client must initialize with live API key")
        report = analyst.analyze("RELIANCE")
        self.assertEqual(report.execution_mode, "LIVE_GEMINI_MODEL")
        self.assertGreater(report.revenue, 0.0)

    @unittest.skipUnless(os.environ.get("RUN_LIVE_TESTS") == "true" and os.environ.get("GROQ_API_KEY"), "Requires live GROQ_API_KEY and RUN_LIVE_TESTS=true")
    def test_live_groq_market_analyst_call(self):
        analyst = MarketAnalyst()
        self.assertIsNotNone(analyst.groq_client, "Groq client must initialize with live API key")
        report = analyst.analyze("RELIANCE")
        self.assertEqual(report.execution_mode, "LIVE_GROQ_MODEL")
        self.assertGreater(report.last_price, 0.0)

    @unittest.skipUnless(os.environ.get("RUN_LIVE_TESTS") == "true" and os.environ.get("GROQ_API_KEY"), "Requires live GROQ_API_KEY and RUN_LIVE_TESTS=true")
    def test_live_groq_crewai_kickoff_call(self):
        crew = ResearchDebateCrew()
        bundle = {
            "market": {"ticker": "RELIANCE", "last_price": 1200.0, "support_level": 1150.0, "resistance_level": 1350.0},
            "sentiment": {"ticker": "RELIANCE", "retail_bull_ratio": 0.6},
            "news": {"ticker": "RELIANCE", "key_catalysts": ["Telecom ARPU growth"]},
            "fundamentals": {"ticker": "RELIANCE", "revenue": 10572190000000.0, "profit_margins": 0.08, "solvency_health": "ROBUST"},
        }
        verdict = crew.conduct_debate("RELIANCE", bundle)
        self.assertEqual(verdict.execution_mode, "LIVE_CREWAI_LLM")

    @unittest.skipUnless(os.environ.get("RUN_LIVE_TESTS") == "true" and os.environ.get("GEMINI_API_KEY"), "Requires live GEMINI_API_KEY and RUN_LIVE_TESTS=true")
    def test_live_crewai_kickoff_call(self):
        crew = ResearchDebateCrew()
        bundle = {
            "market": {"ticker": "RELIANCE", "last_price": 1200.0, "support_level": 1150.0, "resistance_level": 1350.0},
            "sentiment": {"ticker": "RELIANCE", "retail_bull_ratio": 0.6},
            "news": {"ticker": "RELIANCE", "key_catalysts": ["Telecom ARPU growth"]},
            "fundamentals": {"ticker": "RELIANCE", "revenue": 10572190000000.0, "profit_margins": 0.08, "solvency_health": "ROBUST"},
        }
        verdict = crew.conduct_debate("RELIANCE", bundle)
        self.assertEqual(verdict.execution_mode, "LIVE_CREWAI_LLM")


if __name__ == "__main__":
    unittest.main()
