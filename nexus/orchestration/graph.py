"""Single LangGraph workflow: plan -> implement -> QA -> review -> approval -> delivery."""

import asyncio
import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from nexus.orchestration.contracts import Blocked, Plan, Providers, Review
from nexus.services.artifacts import LocalObjects, archive, source_files
from nexus.services.execution import RunStore


class State(TypedDict, total=False):
    context: dict
    plan: dict
    workspace: str
    iteration: int
    implementation: dict
    validation: dict
    review: dict
    artifacts: list[dict]
    approval: dict
    specialists: dict
    outcome: str


def build_graph(
    store: RunStore,
    providers: Providers,
    objects: LocalObjects,
    workspaces,
    checkpointer,
    *,
    max_repairs: int = 2,
):
    async def planning(state: State):
        result = await store.stage(
            "planning",
            "openai",
            500000,
            lambda: providers.plan(
                json.dumps(
                    {
                        "instruction": state["context"]["instruction"],
                        "knowledge": state["context"].get("knowledge", []),
                    }
                )
            ),
        )
        plan = Plan.model_validate(result["data"])
        workspace = await asyncio.to_thread(workspaces.prepare, state["context"]["run_id"])
        return {"plan": plan.model_dump(), "workspace": str(workspace), "iteration": 0}

    async def specialists(state: State):
        context = state["context"]

        async def run(name, agent, reservation):
            return name, await store.stage(
                name, agent, reservation, lambda: getattr(providers, name)(context)
            )

        requests = []
        if context.get("options", {}).get("research"):
            requests.append(run("research", "kimi", 500000))
        if context.get("options", {}).get("design"):
            requests.append(run("design", "gemini", 500000))
        # Read-only independent work shares no filesystem. Each call has a bounded timeout.
        tasks = [asyncio.create_task(asyncio.wait_for(request, 120)) for request in requests]
        try:
            results = await asyncio.gather(*tasks)
            return {"specialists": dict(results)}
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def implementation(state: State):
        iteration = state["iteration"]
        feedback = {
            "tests": state.get("validation"),
            "review": state.get("review"),
            "specialists": state.get("specialists", {}),
            "knowledge": state["context"].get("knowledge", []),
        }
        result = await store.stage(
            f"implementation-{iteration}",
            "claude",
            1000000,
            lambda: providers.develop(
                state["context"]["instruction"],
                Plan.model_validate(state["plan"]),
                feedback,
                state["workspace"],
                1.0,
            ),
        )
        return {"implementation": result}

    async def validation(state: State):
        result = await store.stage(
            f"validation-{state['iteration']}",
            "deterministic_qa",
            0,
            lambda: providers.validate(state["workspace"]),
        )
        return {"validation": result}

    async def review(state: State):
        result = await store.stage(
            f"review-{state['iteration']}",
            "codex",
            500000,
            lambda: providers.review(
                state["context"]["instruction"],
                Plan.model_validate(state["plan"]),
                state["workspace"],
            ),
        )
        Review.model_validate(result["data"])
        return {"review": result}

    def route(state: State):
        passed = state["validation"]["data"].get("passed") is True
        approved = Review.model_validate(state["review"]["data"]).recommendation == "approve"
        if passed and approved:
            return "capture"
        return "repair" if state["iteration"] < max_repairs else "quality_failed"

    def repair(state: State):
        return {"iteration": state["iteration"] + 1}

    async def quality_failed(state: State):
        raise Blocked("quality_gate_failed_repair_limit")

    async def capture(state: State):
        # Workers have exited. Freeze the exact source approved by the user.
        files = await asyncio.to_thread(source_files, Path(state["workspace"]))
        source = await asyncio.to_thread(archive, files)
        report = json.dumps(
            {
                "plan": state["plan"],
                "validation": state["validation"],
                "review": state["review"],
                "implementation": state["implementation"],
                "specialists": state.get("specialists", {}),
            },
            indent=2,
        ).encode()
        records = []
        for name, data, media in (
            ("project.zip", source, "application/zip"),
            ("verification.json", report, "application/json"),
        ):
            digest, size = await asyncio.to_thread(objects.put, data)
            records.append(await store.artifact(state["context"], name, digest, size, media))
        screenshots = Path(state["workspace"]).parent / "qa-output"
        if screenshots.exists():
            captured = await asyncio.to_thread(source_files, screenshots)
            for name in ("desktop.png", "mobile.png"):
                if name in captured:
                    digest, size = await asyncio.to_thread(objects.put, captured[name])
                    records.append(
                        await store.artifact(state["context"], name, digest, size, "image/png")
                    )
        return {"artifacts": records}

    async def approval(state: State):
        parameters = {
            "action": "release_artifacts",
            "run_id": state["context"]["run_id"],
            "artifacts": state["artifacts"],
        }
        record = await store.approval(parameters)
        # The persisted authenticated decision is authoritative, never the resume value.
        interrupt(
            {
                "approval_id": record["id"],
                "action_hash": record["action_hash"],
                "parameters": parameters,
            }
        )
        record = await store.approval(parameters)
        if record["decision"] not in {"approve", "reject", "request_changes"}:
            raise Blocked("approval_decision_missing")
        return {
            "approval": record,
            "outcome": "completed" if record["decision"] == "approve" else "rejected",
        }

    graph = StateGraph(State)
    nodes = {
        "planning": planning,
        "specialists": specialists,
        "implementation": implementation,
        "validation": validation,
        "review": review,
        "repair": repair,
        "quality_failed": quality_failed,
        "capture": capture,
        "approval": approval,
    }
    for name, node in nodes.items():
        graph.add_node(name, node)
    graph.add_edge(START, "planning")
    for a, b in (
        ("planning", "specialists"),
        ("specialists", "implementation"),
        ("implementation", "validation"),
        ("validation", "review"),
        ("repair", "implementation"),
        ("capture", "approval"),
        ("approval", END),
        ("quality_failed", END),
    ):
        graph.add_edge(a, b)
    graph.add_conditional_edges(
        "review", route, {name: name for name in ("capture", "repair", "quality_failed")}
    )
    return graph.compile(checkpointer=checkpointer)
