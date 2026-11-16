"""JSONC parsing, runtime wiring and template rendering without external services."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pydantic import BaseModel

from kairos.config import agent_definitions as config
from kairos.agents.adk_analysts import MarketAnalyst
from kairos.agents.crewai_research import (
    BullResearcher,
    BearResearcher,
    ResearchManager,
)


class TestAgentConfiguration(unittest.TestCase):
    def tearDown(self):
        config.get_agent_definition.cache_clear()
        config.get_task_definitions.cache_clear()

    def test_all_eight_agents_and_ten_tasks_are_connected(self):
        agents = {path.stem for path in (config.CONFIG_DIR / "agents").glob("*.jsonc")}
        tasks = config.get_task_definitions()
        self.assertEqual(len(agents), 8)
        self.assertEqual(len(tasks), 10)
        self.assertEqual({task.agent for task in tasks.values()}, agents)
        for name in agents:
            definition = config.get_agent_definition(name)
            self.assertTrue(
                definition.role and definition.goal and definition.backstory
            )

    def test_comments_trailing_commas_and_url_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.jsonc"
            path.write_text("""{
                // This comment must not remove the URL below.
                "url": "https://example.com/a//b", /* inline comment */
                "text": "literal /* content */ and {braces}",
            }""")
            value = config.load_jsonc(path)
            self.assertEqual(value["url"], "https://example.com/a//b")
            self.assertIn("/* content */", value["text"])

    def test_invalid_json_and_duplicate_keys_report_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.jsonc"
            for text in ['{"role":', '{"role":"one", "role":"two"}']:
                path.write_text(text)
                with self.assertRaisesRegex(ValueError, "broken.jsonc"):
                    config.load_jsonc(path)

    def test_unknown_agent_and_invalid_settings_fail_early(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(config, "CONFIG_DIR", Path(tmp)),
        ):
            (Path(tmp) / "prompts").mkdir()
            (Path(tmp) / "prompts" / "tasks.jsonc").write_text("""{
                "task": {"agent":"missing", "description":"Analyze", "expected_output":"JSON"}
            }""")
            with self.assertRaisesRegex(ValueError, "missing.jsonc"):
                config.get_task_definitions()
        with self.assertRaises(ValueError):
            config.AgentDefinition(
                role="A", goal="B", backstory="C", settings={"verbose": "false"}
            )

    def test_agent_names_cannot_escape_the_config_directory(self):
        for name in ["../secrets", "", "/tmp/agent"]:
            with self.assertRaisesRegex(ValueError, "Invalid agent name"):
                config.get_agent_definition(name)

    def test_rendering_preserves_untrusted_braces_and_numeric_formats(self):
        result = config.render_task(
            "bull_thesis",
            ticker="TCS",
            mkt_price=1234.5,
            support=1200.0,
            resistance=1400.0,
            margin=0.1,
            solvency="ROBUST",
            sentiment="Bull Ratio 0.60",
            top_cats=["Growth {do_not_interpolate}"],
            round_num=1,
        )
        self.assertIn("₹1234.50", result["description"])
        self.assertIn("{do_not_interpolate}", result["description"])
        self.assertIn("Round 1", result["expected_output"])
        with self.assertRaisesRegex(ValueError, "Cannot render task 'bull_rebuttal'"):
            config.render_task("bull_rebuttal", ticker="TCS")

    def test_configuration_paths_do_not_depend_on_working_directory(self):
        with patch("pathlib.Path.cwd", return_value=Path("/unrelated")):
            self.assertEqual(
                config.get_task_definitions()["market_analysis"].agent, "market_analyst"
            )

    @patch.dict(
        "os.environ", {"GROQ_API_KEY": "", "GEMINI_API_KEY": "", "OPENAI_API_KEY": ""}
    )
    def test_role_goal_and_backstory_reach_the_model_prompt(self):
        class Ping(BaseModel):
            status: str

        analyst = MarketAnalyst()
        analyst.groq_client = MagicMock()
        analyst.gemini_client = None
        analyst.groq_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"status":"ok"}'))
            ]
        )
        result = analyst.invoke_llm_analysis(
            "Analyze TCS", Ping, Ping(status="fallback")
        )
        self.assertEqual(result.status, "ok")
        messages = analyst.groq_client.chat.completions.create.call_args.kwargs[
            "messages"
        ]
        prompt = "\n".join(message["content"] for message in messages)
        definition = config.get_agent_definition("market_analyst")
        for value in [definition.role, definition.goal, definition.backstory]:
            self.assertIn(value, prompt)

    @patch.dict(
        "os.environ", {"GROQ_API_KEY": "", "GEMINI_API_KEY": "", "OPENAI_API_KEY": ""}
    )
    def test_crewai_agents_use_jsonc_and_construct_without_credentials(self):
        for name, factory in [
            ("bull_researcher", BullResearcher),
            ("bear_researcher", BearResearcher),
            ("research_manager", ResearchManager),
        ]:
            instance = factory()
            definition = config.get_agent_definition(name)
            self.assertEqual(instance.crew_agent.role, definition.role)
            self.assertEqual(instance.crew_agent.goal, definition.goal)
            self.assertEqual(instance.crew_agent.backstory, definition.backstory)
            task = instance.create_task("TCS", {})
            self.assertIs(task.agent, instance.crew_agent)
            self.assertIn("TCS", task.description)
            self.assertIsNotNone(task.output_pydantic)


if __name__ == "__main__":
    unittest.main()
