import asyncio
import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.main import create_app
from nexus.db.models import Execution
from nexus.orchestration.checkpoints import checkpoints
from nexus.orchestration.contracts import Blocked, Plan, ProviderResult
from nexus.services.artifacts import LocalObjects
from nexus.services.execution import RunStore
from nexus.workers.qa import check_site
from nexus.workers.queue import RunQueue
from nexus.workers.runtime import execute
from nexus.workers.workspace import Workspaces

TOKEN = "orchestration-test-token" * 3
WORKSPACE = "00000000-0000-4000-8000-000000000001"
OTHER = "other-workspace-token" * 3
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
CREDENTIALS = {TOKEN: WORKSPACE, OTHER: "00000000-0000-4000-8000-000000000002"}
PLAN = {
    "summary": "Build a small site",
    "tasks": [
        {
            "id": "site",
            "name": "Build site",
            "goal": "Build accessible site",
            "agent": "claude",
            "dependencies": [],
            "acceptance_criteria": ["Responsive navigation"],
            "allowed_tools": ["Read", "Write"],
        }
    ],
}
HTML = """<!doctype html><html lang="en"><head><title>Test site</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body><nav><a href="#main">Home</a></nav><main id="main"><h1>Test</h1></main></body></html>"""


class FixtureProviders:
    """Controlled fixtures only; never imported by operational code."""

    def __init__(self, fail_reviews=0):
        self.calls = []
        self.fail_reviews = fail_reviews

    async def plan(self, instruction):
        self.calls.append("plan")
        return ProviderResult(data=PLAN, input_tokens=10, output_tokens=20)

    async def develop(self, instruction, plan, feedback, workspace, budget_usd):
        self.calls.append("develop")
        Path(workspace, "index.html").write_text(HTML)
        return ProviderResult(data={"summary": "Fixture implementation"})

    async def validate(self, workspace):
        self.calls.append("validate")
        return ProviderResult(data=check_site(Path(workspace)))

    async def review(self, instruction, plan, workspace):
        self.calls.append("review")
        failing = self.fail_reviews > 0
        self.fail_reviews -= 1
        return ProviderResult(
            data={
                "recommendation": "changes_requested" if failing else "approve",
                "findings": [],
                "uncertainties": [],
            }
        )


def submit(client, budget=5000000):
    project = client.post("/api/v1/projects", headers=HEADERS, json={"name": "Website"}).json()
    response = client.post(
        "/api/v1/tasks",
        headers={**HEADERS, "Idempotency-Key": "run"},
        json={"project_id": project["id"], "instruction": "Build site", "budget_microusd": budget},
    )
    assert response.status_code == 202
    return project, response.json()


def test_graph_approval_delivery_and_replay(orchestration_db, tmp_path, monkeypatch):
    objects = LocalObjects(str(tmp_path / "objects"))
    monkeypatch.setenv("NEXUS_ARTIFACT_ROOT", str(objects.root))
    workspaces = Workspaces(str(tmp_path / "workspaces"))
    providers = FixtureProviders(fail_reviews=1)
    database = orchestration_db
    with TestClient(create_app(database, CREDENTIALS)) as client:
        project, run = submit(client)

        async def process():
            engine = create_async_engine(database)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                lease = await RunQueue(sessions).claim()
                assert lease
                async with checkpoints(database, str(tmp_path / "checkpoints.db")) as saver:
                    await execute(sessions, lease, providers, workspaces, objects, saver)
            finally:
                await engine.dispose()

        asyncio.run(process())
        assert (
            client.get(f"/api/v1/runs/{run['id']}", headers=HEADERS).json()["status"]
            == "awaiting_approval"
        )
        approvals = client.get("/api/v1/approvals", headers=HEADERS).json()
        assert len(approvals) == 1
        approval = approvals[0]
        url = f"/api/v1/approvals/{approval['id']}/decision"
        body = {"decision": "approve", "action_hash": approval["action_hash"]}
        assert (
            client.post(url, headers={"Authorization": f"Bearer {OTHER}"}, json=body).status_code
            == 404
        )
        assert (
            client.post(url, headers=HEADERS, json={**body, "action_hash": "0" * 64}).status_code
            == 409
        )
        assert client.post(url, headers=HEADERS, json=body).status_code == 200
        assert client.post(url, headers=HEADERS, json=body).status_code == 200
        calls = list(providers.calls)
        asyncio.run(process())  # New engine, saver and graph: resume actual persisted interrupt.
        assert providers.calls == calls  # No provider calls repeated after approval.
        assert calls.count("develop") == 2  # Bounded targeted repair occurred.
        record = client.get(f"/api/v1/runs/{run['id']}", headers=HEADERS).json()
        assert record["status"] == "completed"
        artifacts = client.get(
            f"/api/v1/projects/{project['id']}/artifacts", headers=HEADERS
        ).json()
        source = next(a for a in artifacts if a["name"] == "project.zip")
        payload = client.get(f"/api/v1/artifacts/{source['id']}", headers=HEADERS)
        assert payload.status_code == 200
        assert hashlib.sha256(payload.content).hexdigest() == source["sha256"]
        assert zipfile.ZipFile(io.BytesIO(payload.content)).read("index.html").decode() == HTML
        assert (
            client.get(
                f"/api/v1/artifacts/{source['id']}", headers={"Authorization": f"Bearer {OTHER}"}
            ).status_code
            == 404
        )
        events = client.get(f"/api/v1/runs/{run['id']}/events", headers=HEADERS).text
        assert "stage_completed" in events and "approval_decided" in events
        assert "event: execution" in events
        assert client.get("/api/v1/usage", headers=HEADERS).json()["input_tokens"] == 10


def test_budget_and_uncertain_call_fail_closed(orchestration_db):
    database = orchestration_db
    with TestClient(create_app(database, CREDENTIALS)) as client:
        submit(client, budget=500000)

    async def scenario():
        engine = create_async_engine(database)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            lease = await RunQueue(sessions).claim()
            store = RunStore(sessions, lease)
            count = 0

            async def completed():
                nonlocal count
                count += 1
                return ProviderResult(data={"ok": True})

            await store.stage("once", "test", 500000, completed)
            await store.stage("once", "test", 500000, completed)
            assert count == 1
            with pytest.raises(Blocked, match="dispatch_budget_exhausted"):
                await store.stage("over-budget", "test", 1, completed)

            async def crash():
                raise TimeoutError()

            with pytest.raises(TimeoutError):
                await store.stage("uncertain", "test", 0, crash)
            with pytest.raises(Blocked, match="uncertain_stage"):
                await store.stage("uncertain", "test", 0, completed)
            assert count == 1
            async with sessions() as session:
                assert len((await session.scalars(select(Execution))).all()) == 2
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_plan_rejects_cycles_and_privilege_escalation():
    assert len(Plan.model_validate(PLAN).ordered()) == 1
    import copy

    cycle = copy.deepcopy(PLAN)
    cycle["tasks"][0]["dependencies"] = ["site"]
    with pytest.raises(ValueError):
        Plan.model_validate(cycle)
    unsafe = copy.deepcopy(PLAN)
    unsafe["tasks"][0]["allowed_tools"] = ["Bash"]
    with pytest.raises(ValueError):
        Plan.model_validate(unsafe)


def test_missing_configuration_is_retryable_without_duplicate_budget(orchestration_db):
    from nexus.orchestration.contracts import NotConfigured

    with TestClient(create_app(orchestration_db, CREDENTIALS)) as client:
        submit(client)

    async def scenario():
        engine = create_async_engine(orchestration_db)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            lease = await RunQueue(sessions).claim()
            store = RunStore(sessions, lease)

            async def unavailable():
                raise NotConfigured("planner_not_configured")

            with pytest.raises(NotConfigured):
                await store.stage("planning", "openai", 500000, unavailable)

            async def configured():
                return ProviderResult(data=PLAN)

            result = await store.stage("planning", "openai", 500000, configured)
            assert result["data"] == PLAN
            from nexus.db.models import Run

            async with sessions() as session:
                run = await session.get(Run, lease.run_id)
                assert run.reserved_microusd == 500000
                stages = (await session.scalars(select(Execution))).all()
                assert len(stages) == 1
                assert stages[0].status == "succeeded"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_versioned_context_is_scoped_and_approved_versions_take_precedence(orchestration_db):
    with TestClient(create_app(orchestration_db, CREDENTIALS)) as client:
        project, _run = submit(client)
        path = f"/api/v1/projects/{project['id']}/knowledge"
        first = client.post(
            path,
            headers=HEADERS,
            json={
                "title": "Brand",
                "content": "French language",
                "source": "client brief",
                "approved": True,
            },
        )
        assert first.status_code == 201
        assert first.json()["version"] == 1
        second = client.post(
            path,
            headers=HEADERS,
            json={
                "title": "Brand",
                "content": "English language",
                "source": "draft suggestion",
                "approved": False,
            },
        )
        assert second.json()["version"] == 2
        assert client.get(path, headers={"Authorization": f"Bearer {OTHER}"}).status_code == 404

    async def inspect_context():
        engine = create_async_engine(orchestration_db)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            lease = await RunQueue(sessions).claim()
            context = await RunStore(sessions, lease).context()
            assert context["knowledge"][0]["content"] == "French language"
            assert context["knowledge"][0]["source"] == "client brief"
            assert context["knowledge"][0]["approved"] is True
        finally:
            await engine.dispose()

    asyncio.run(inspect_context())


def test_independent_specialists_run_concurrently(orchestration_db, tmp_path):
    class ConcurrentProviders(FixtureProviders):
        async def specialist(self, name):
            self.started.add(name)
            if len(self.started) == 2:
                self.both.set()
            await asyncio.wait_for(self.both.wait(), 2)
            return ProviderResult(data={"summary": f"Fixture {name}"})

        async def research(self, context):
            return await self.specialist("research")

        async def design(self, context):
            return await self.specialist("design")

    with TestClient(create_app(orchestration_db, CREDENTIALS)) as client:
        project = client.post("/api/v1/projects", headers=HEADERS, json={"name": "Parallel"}).json()
        run = client.post(
            "/api/v1/tasks",
            headers={**HEADERS, "Idempotency-Key": "parallel"},
            json={
                "project_id": project["id"],
                "instruction": "Build",
                "research": True,
                "design": True,
            },
        ).json()

    async def scenario():
        engine = create_async_engine(orchestration_db)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        providers = ConcurrentProviders()
        providers.started, providers.both = set(), asyncio.Event()
        try:
            lease = await RunQueue(sessions).claim()
            async with checkpoints(orchestration_db, str(tmp_path / "parallel.db")) as saver:
                await execute(
                    sessions,
                    lease,
                    providers,
                    Workspaces(str(tmp_path / "workspaces")),
                    LocalObjects(str(tmp_path / "objects")),
                    saver,
                )
            assert providers.started == {"research", "design"}
            async with sessions() as session:
                stages = (
                    await session.scalars(
                        select(Execution).where(
                            Execution.run_id == run["id"], Execution.agent.in_(["kimi", "gemini"])
                        )
                    )
                ).all()
                assert len(stages) == 2
                assert all(stage.status == "succeeded" for stage in stages)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_project_patch_preserves_unspecified_fields(orchestration_db):
    with TestClient(create_app(orchestration_db, CREDENTIALS)) as client:
        project = client.post(
            "/api/v1/projects",
            headers=HEADERS,
            json={"name": "Original", "description": "Keep this"},
        ).json()
        path = f"/api/v1/projects/{project['id']}"
        result = client.patch(path, headers=HEADERS, json={"name": "Updated"})
        assert result.status_code == 200
        assert result.json()["description"] == "Keep this"
        assert client.patch(path, headers=HEADERS, json={"name": None}).status_code == 422
        assert client.patch(path, headers=HEADERS, json={}).status_code == 422
        assert (
            client.patch(
                path, headers={"Authorization": f"Bearer {OTHER}"}, json={"name": "Unauthorized"}
            ).status_code
            == 404
        )
        assert "x-request-id" in result.headers


def test_database_rate_limit_is_shared_across_api_instances(orchestration_db, monkeypatch):
    monkeypatch.setenv("NEXUS_API_RATE_LIMIT", "2")
    with TestClient(create_app(orchestration_db, CREDENTIALS)) as first:
        assert first.get("/api/v1/projects", headers=HEADERS).status_code == 200
        assert first.get("/api/v1/projects", headers=HEADERS).status_code == 200
    with TestClient(create_app(orchestration_db, CREDENTIALS)) as second:
        rejected = second.get("/api/v1/projects", headers=HEADERS)
        assert rejected.status_code == 429
        assert rejected.headers["retry-after"] == "60"
        assert (
            second.get("/api/v1/projects", headers={"Authorization": f"Bearer {OTHER}"}).status_code
            == 200
        )


def test_daily_dispatch_quota_prevents_new_calls_across_runs(orchestration_db, monkeypatch):
    monkeypatch.setenv("NEXUS_DAILY_DISPATCH_MICROUSD", "500000")
    with TestClient(create_app(orchestration_db, CREDENTIALS)) as client:
        project, _run = submit(client)
        client.post(
            "/api/v1/tasks",
            headers={**HEADERS, "Idempotency-Key": "second"},
            json={"project_id": project["id"], "instruction": "Second task"},
        )

    async def scenario():
        engine = create_async_engine(orchestration_db)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        calls = 0

        async def provider():
            nonlocal calls
            calls += 1
            return ProviderResult(data={"ok": True})

        try:
            queue = RunQueue(sessions)
            first = await queue.claim()
            await RunStore(sessions, first).stage("planning", "openai", 500000, provider)
            second = await queue.claim()
            with pytest.raises(Blocked, match="project_or_daily"):
                await RunStore(sessions, second).stage("planning", "openai", 500000, provider)
            assert calls == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_real_worker_cli_records_unconfigured_and_retries_safely(orchestration_db, tmp_path):
    import os
    import subprocess
    import sys

    environment = {
        **os.environ,
        "DATABASE_URL": orchestration_db,
        "OPENAI_API_KEY": "",
        "NEXUS_PLANNER_MODEL": "",
        "NEXUS_S3_BUCKET": "",
        "NEXUS_CHECKPOINT_PATH": str(tmp_path / "worker-checkpoints.db"),
        "NEXUS_WORKSPACE_ROOT": str(tmp_path / "workspaces"),
        "NEXUS_ARTIFACT_ROOT": str(tmp_path / "objects"),
    }
    with TestClient(create_app(orchestration_db, CREDENTIALS)) as client:
        _project, run = submit(client)
        for attempt in range(2):
            subprocess.run(
                [sys.executable, "-m", "nexus.workers.runtime", "--once"],
                env=environment,
                check=True,
                capture_output=True,
                timeout=30,
            )
            record = client.get(f"/api/v1/runs/{run['id']}", headers=HEADERS).json()
            assert record["status"] == "blocked"
            assert record["status_reason"] == "openai_planner_not_configured"
            assert record["reserved_microusd"] == 0
            if attempt == 0:
                assert (
                    client.post(f"/api/v1/runs/{run['id']}/retry", headers=HEADERS).status_code
                    == 200
                )
        executions = client.get(f"/api/v1/runs/{run['id']}/executions", headers=HEADERS).json()
        assert len(executions) == 1
        assert executions[0]["status"] == "not_started"
