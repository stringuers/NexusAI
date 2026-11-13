"""Untrusted provider data is validated before it influences execution."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanTask(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    name: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=4000)
    agent: Literal["claude"]
    dependencies: list[str] = Field(max_length=20)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)
    allowed_tools: list[Literal["Read", "Write", "Edit", "Glob", "Grep"]]


class Plan(StrictModel):
    summary: str = Field(min_length=1, max_length=4000)
    tasks: list[PlanTask] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_dag(self):
        tasks = {task.id: task for task in self.tasks}
        if len(tasks) != len(self.tasks):
            raise ValueError("Duplicate task IDs")
        pending = set(tasks)
        complete = set()
        while pending:
            ready = {key for key in pending if set(tasks[key].dependencies) <= complete}
            if not ready:
                raise ValueError("Cyclic graph or unknown dependency")
            pending -= ready
            complete |= ready
        return self

    def ordered(self) -> list[PlanTask]:
        result = []
        pending = list(self.tasks)
        while pending:
            ready = [
                task for task in pending if set(task.dependencies) <= {done.id for done in result}
            ]
            result.extend(ready)
            pending = [task for task in pending if task not in ready]
        return result


class Finding(StrictModel):
    severity: Literal["critical", "high", "medium", "low"]
    file: str
    line: int = Field(ge=1)
    description: str
    reproduction: str
    suggested_change: str


class Review(StrictModel):
    recommendation: Literal["approve", "changes_requested"]
    findings: list[Finding]
    uncertainties: list[str]

    @model_validator(mode="after")
    def enforce_findings(self):
        if any(f.severity in {"critical", "high", "medium"} for f in self.findings):
            self.recommendation = "changes_requested"
        return self


class ProviderResult(StrictModel):
    data: dict
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reported_cost_usd: float | None = Field(default=None, ge=0)
    session_id: str | None = None


class Providers(Protocol):
    async def plan(self, instruction: str) -> ProviderResult: ...
    async def research(self, context: dict) -> ProviderResult: ...
    async def design(self, context: dict) -> ProviderResult: ...
    async def develop(
        self, instruction: str, plan: Plan, feedback: dict, workspace: str, budget_usd: float
    ) -> ProviderResult: ...
    async def validate(self, workspace: str) -> ProviderResult: ...
    async def review(self, instruction: str, plan: Plan, workspace: str) -> ProviderResult: ...


class Blocked(RuntimeError):
    """Safe public error code; do not place raw provider errors/secrets here."""


class NotConfigured(Blocked):
    """No provider request or side effect was started."""


class LeaseLost(RuntimeError):
    pass
