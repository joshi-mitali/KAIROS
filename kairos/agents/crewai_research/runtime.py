"""Shared model selection and JSONC-backed CrewAI agent construction."""

import os
from typing import Any

from crewai import Agent, BaseLLM, LLM

from kairos.config.agent_definitions import get_agent_definition
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.crewai.runtime")


class UnavailableLLM(BaseLLM):
    """Allow agent/task construction without implicitly requiring OpenAI credentials."""

    def __init__(self):
        super().__init__(model="kairos/deterministic-fallback")

    def call(self, messages: Any, **kwargs: Any) -> str:
        raise RuntimeError(
            "No research model configured; use the deterministic debate engine."
        )


def create_research_llm(default_max_tokens: int = 750) -> BaseLLM:
    from kairos.providers.groq import get_key_pool
    gemini_key = os.environ.get("GEMINI_API_KEY")
    try:
        groq_key = get_key_pool().current() if (os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEYS")) else None
        if groq_key:
            return LLM(
                model=os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b"),
                base_url=os.environ.get(
                    "GROQ_BASE_URL", "https://api.groq.com/openai/v1"
                ),
                api_key=groq_key,
                timeout=float(os.environ.get("GROQ_TIMEOUT_SEC", "45.0")),
                custom_openai=True,
                temperature=0.1,
                stream=True,
                max_tokens=int(
                    os.environ.get(
                        "CREWAI_MAX_TOKENS",
                        os.environ.get("GROQ_MAX_TOKENS", str(default_max_tokens)),
                    )
                ),
            )
        if gemini_key:
            model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
            return LLM(
                model=model if model.startswith("gemini/") else f"gemini/{model}",
                api_key=gemini_key,
                timeout=float(os.environ.get("GEMINI_TIMEOUT_SEC", "60.0")),
                max_tokens=int(os.environ.get("CREWAI_MAX_TOKENS", "250")),
            )
    except Exception as exc:
        logger.warning(
            f"Research model initialization failed; using deterministic fallback: {exc}"
        )
    return UnavailableLLM()


def create_research_agent(name: str) -> Agent:
    definition = get_agent_definition(name)
    identity = definition.model_dump(exclude={"settings"})
    llm = create_research_llm(850 if name == "research_manager" else 750)
    return Agent(
        **identity,
        **definition.settings.model_dump(),
        llm=llm,
        function_calling_llm=llm,
    )
