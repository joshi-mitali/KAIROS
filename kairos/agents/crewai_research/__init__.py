"""CrewAI Research & Debate Module for KAIROS ARGUE Stage."""

from kairos.agents.crewai_research.bear_researcher import BearResearcher
from kairos.agents.crewai_research.bull_researcher import BullResearcher
from kairos.agents.crewai_research.crewai_patch import ensure_crewai_patched
from kairos.agents.crewai_research.research_crew import ResearchDebateCrew
from kairos.agents.crewai_research.research_manager import ResearchManager

__all__ = [
    "ensure_crewai_patched",
    "BullResearcher",
    "BearResearcher",
    "ResearchManager",
    "ResearchDebateCrew",
]

