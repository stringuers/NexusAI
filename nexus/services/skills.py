"""Versioned instruction catalog; skill text cannot grant execution permissions."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CATALOG = {"project-planner", "website-builder", "research", "visual-qa", "security-review"}
ROOT = Path(__file__).resolve().parents[2] / "skills"


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    agent: Literal["openai", "claude", "kimi", "gemini", "codex"]
    execution: Literal["instructions-only"]
    instructions: str = Field(min_length=1, max_length=10000)


def load_skill(name: str, agent: str) -> Skill:
    if name not in CATALOG:
        raise PermissionError("Unknown skill")
    _, header, body = (ROOT / name / "SKILL.md").read_text().split("---", 2)
    metadata = dict(line.split(": ", 1) for line in header.strip().splitlines())
    skill = Skill(**metadata, instructions=body.strip())
    if skill.name != name or skill.agent != agent:
        raise PermissionError("Skill outside agent scope")
    return skill
