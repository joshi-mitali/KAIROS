"""Load validated JSONC identities and render task templates independently of the cwd."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import json5
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from kairos_config import CONFIG_DIR


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verbose: StrictBool = False
    allow_delegation: StrictBool = False


class AgentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    backstory: str = Field(min_length=1)
    settings: AgentSettings = Field(default_factory=AgentSettings)


class TaskDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: str = Field(pattern=r"^[a-z_]+$")
    description: str = Field(min_length=1)
    expected_output: str = Field(min_length=1)


def load_jsonc(path: Path) -> Any:
    try:
        return json5.loads(path.read_text(encoding="utf-8"), allow_duplicate_keys=False)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot load configuration {path}: {exc}") from exc


@lru_cache
def get_agent_definition(name: str) -> AgentDefinition:
    # Only packaged identities can be selected; a name is not a filesystem path.
    if not name or any(char not in "abcdefghijklmnopqrstuvwxyz_" for char in name):
        raise ValueError(f"Invalid agent name: {name!r}")
    return AgentDefinition.model_validate(
        load_jsonc(CONFIG_DIR / "agents" / f"{name}.jsonc")
    )


@lru_cache
def get_task_definitions() -> dict[str, TaskDefinition]:
    raw = load_jsonc(CONFIG_DIR / "prompts" / "tasks.jsonc")
    if not isinstance(raw, dict) or not raw:
        raise ValueError(
            "tasks.jsonc must contain a non-empty object of task definitions"
        )
    definitions = {
        name: TaskDefinition.model_validate(value) for name, value in raw.items()
    }
    for task in definitions.values():
        get_agent_definition(task.agent)
    return definitions


def render_task(name: str, **inputs: Any) -> dict[str, str]:
    """Render once so braces in news, titles or memory are never interpreted again."""
    task = get_task_definitions()[name]
    try:
        return {
            "description": task.description.format(**inputs),
            "expected_output": task.expected_output.format(**inputs),
        }
    except (KeyError, ValueError, IndexError) as exc:
        raise ValueError(f"Cannot render task {name!r}: {exc}") from exc
