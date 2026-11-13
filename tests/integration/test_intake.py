import os
import subprocess
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app

TOKEN = "a" * 40
OTHER = "b" * 40
SCOPES = {TOKEN: str(uuid4()), OTHER: str(uuid4())}
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
OTHER_HEADERS = {"Authorization": f"Bearer {OTHER}"}


@pytest.fixture
def database(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "DATABASE_URL": url},
    )
    return url


def test_persistence_idempotency_and_isolation(database):
    with TestClient(create_app(database, SCOPES)) as client:
        assert client.get("/api/v1/projects").status_code == 401
        project = client.post("/api/v1/projects", headers=HEADERS, json={"name": "Website Factory"})
        assert project.status_code == 201
        project_id = project.json()["id"]
        body = {"project_id": project_id, "instruction": "Build an accessible navigation"}
        headers = {**HEADERS, "Idempotency-Key": "task-1"}
        response = client.post("/api/v1/tasks", headers=headers, json=body)
        assert response.status_code == 202
        run = response.json()
        assert run["status"] == "queued"
        assert client.post("/api/v1/tasks", headers=headers, json=body).json() == run
        assert (
            client.post(
                "/api/v1/tasks", headers=headers, json={**body, "instruction": "Different"}
            ).status_code
            == 409
        )
        assert (
            client.get(f"/api/v1/projects/{project_id}", headers=OTHER_HEADERS).status_code == 404
        )
        assert (
            client.post(
                "/api/v1/tasks", headers={**OTHER_HEADERS, "Idempotency-Key": "x"}, json=body
            ).status_code
            == 404
        )
        assert client.get(f"/api/v1/runs/{run['id']}", headers=OTHER_HEADERS).status_code == 404
        assert (
            client.get(f"/api/v1/tasks/{run['task_id']}", headers=OTHER_HEADERS).status_code == 404
        )
        assert client.get("/api/v1/projects", headers=OTHER_HEADERS).json() == []
    with TestClient(create_app(database, SCOPES)) as restarted:
        assert restarted.get(f"/api/v1/runs/{run['id']}", headers=HEADERS).json() == run
        assert (
            restarted.get(f"/api/v1/tasks/{run['task_id']}", headers=HEADERS).json()["instruction"]
            == body["instruction"]
        )
        assert restarted.get("/api/v1/projects", headers=HEADERS).json()[0]["id"] == project_id


def test_validation(database):
    with TestClient(create_app(database, SCOPES)) as client:
        assert (
            client.post("/api/v1/projects", headers=HEADERS, json={"name": " "}).status_code == 422
        )
        assert (
            client.post(
                "/api/v1/projects",
                headers=HEADERS,
                json={"name": "X", "workspace_id": str(uuid4())},
            ).status_code
            == 422
        )
        assert client.get("/api/v1/projects?limit=101", headers=HEADERS).status_code == 422
        assert (
            client.post(
                "/api/v1/tasks",
                headers=HEADERS,
                json={"project_id": str(uuid4()), "instruction": "X"},
            ).status_code
            == 422
        )
        assert (
            client.get("/api/v1/projects", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )


def test_fail_closed():
    with pytest.raises(ValueError):
        create_app("sqlite+aiosqlite://", {})
    with pytest.raises(ValueError):
        create_app("sqlite+aiosqlite://", {"short": str(uuid4())})


def submit_run(client, key="task-1"):
    project = client.post("/api/v1/projects", headers=HEADERS, json={"name": "Lease test"})
    response = client.post(
        "/api/v1/tasks",
        headers={**HEADERS, "Idempotency-Key": key},
        json={"project_id": project.json()["id"], "instruction": "Build"},
    )
    assert response.status_code == 202
    return response.json()


def test_preflight_and_cancellation_survive_restart(database):
    with TestClient(create_app(database, SCOPES)) as client:
        run = submit_run(client)
        result = subprocess.run(
            [sys.executable, "-m", "nexus.workers.preflight"],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "DATABASE_URL": database},
        )
        assert '"status": "blocked"' in result.stdout
        result = subprocess.run(
            [sys.executable, "-m", "nexus.workers.preflight"],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "DATABASE_URL": database},
        )
        assert '"status": "idle"' in result.stdout
    with TestClient(create_app(database, SCOPES)) as client:
        url = f"/api/v1/runs/{run['id']}"
        record = client.get(url, headers=HEADERS).json()
        assert record["status"] == "blocked"
        assert record["attempt_count"] == 1
        assert record["status_reason"] == "execution_pipeline_not_implemented"
        assert "lease_token" not in record
        assert client.post(url + "/cancel").status_code == 401
        assert client.post(url + "/cancel", headers=OTHER_HEADERS).status_code == 404
        cancelled = client.post(url + "/cancel", headers=HEADERS)
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert client.post(url + "/cancel", headers=HEADERS).json() == cancelled.json()
    with TestClient(create_app(database, SCOPES)) as client:
        assert client.get(url, headers=HEADERS).json()["status"] == "cancelled"


def test_queued_cancellation_prevents_claim(database):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from nexus.workers.queue import RunQueue

    with TestClient(create_app(database, SCOPES)) as client:
        run = submit_run(client)
        assert (
            client.post(f"/api/v1/runs/{run['id']}/cancel", headers=HEADERS).json()["status"]
            == "cancelled"
        )

    async def check():
        engine = create_async_engine(database)
        try:
            assert await RunQueue(async_sessionmaker(engine)).claim() is None
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_leases_concurrency_recovery_fencing_and_exhaustion(database):
    import asyncio

    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from nexus.db.models import Run
    from nexus.workers.queue import RunQueue

    with TestClient(create_app(database, SCOPES)) as client:
        run = submit_run(client)

    async def scenario():
        engine = create_async_engine(database)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        queue = RunQueue(sessions, max_attempts=2)
        try:
            claims = await asyncio.gather(queue.claim(), queue.claim())
            owned = [claim for claim in claims if claim is not None]
            assert len(owned) == 1
            first = owned[0]
            assert first.attempt == 1
            assert await queue.heartbeat(first)
            # Deterministic crash/timeout fixture: no wall-clock sleeps.
            async with sessions.begin() as session:
                await session.execute(
                    update(Run).where(Run.id == run["id"]).values(lease_expires_at=0)
                )
            assert not await queue.heartbeat(first)
            assert not await queue.finish(first, "blocked", "stale")
            # A new process/session factory can recover persisted expired work.
            recovered = await RunQueue(sessions, max_attempts=2).claim()
            assert recovered.run_id == first.run_id
            assert recovered.token != first.token
            assert recovered.attempt == 2
            assert not await queue.finish(first, "failed", "stale")
            async with sessions.begin() as session:
                await session.execute(
                    update(Run).where(Run.id == run["id"]).values(lease_expires_at=0)
                )
            assert await queue.claim() is None
            async with sessions() as session:
                record = await session.get(Run, run["id"])
                assert record.status == "failed"
                assert record.status_reason == "lease_attempts_exhausted"
                assert record.lease_token is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())
    with TestClient(create_app(database, SCOPES)) as client:
        assert client.post(f"/api/v1/runs/{run['id']}/cancel", headers=HEADERS).status_code == 409


def test_running_cancellation_fences_worker(database):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from nexus.workers.queue import RunQueue

    with TestClient(create_app(database, SCOPES)) as client:
        run = submit_run(client)

        async def scenario():
            engine = create_async_engine(database)
            queue = RunQueue(async_sessionmaker(engine))
            try:
                lease = await queue.claim()
                response = await asyncio.to_thread(
                    client.post, f"/api/v1/runs/{run['id']}/cancel", headers=HEADERS
                )
                assert response.status_code == 200
                assert not await queue.heartbeat(lease)
                assert not await queue.finish(lease, "blocked", "pipeline_unavailable")
                assert await queue.claim() is None
            finally:
                await engine.dispose()

        asyncio.run(scenario())


def test_migration_preserves_existing_queued_run(database):
    import sqlite3

    environment = {**os.environ, "DATABASE_URL": database}
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0001"], check=True, env=environment
    )
    project_id, task_id, run_id = (str(uuid4()) for _ in range(3))
    workspace = SCOPES[TOKEN]
    with sqlite3.connect(database.removeprefix("sqlite+aiosqlite:///")) as db:
        db.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
            (project_id, workspace, "Existing", "", "2026-11-13 00:00:00"),
        )
        db.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, workspace, project_id, "Existing task", "old-key", "2026-11-13 00:00:00"),
        )
        db.execute(
            "INSERT INTO workflow_runs VALUES (?, ?, ?, ?, ?)",
            (run_id, workspace, task_id, "queued", "2026-11-13 00:00:00"),
        )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=environment
    )
    with TestClient(create_app(database, SCOPES)) as client:
        result = client.get(f"/api/v1/runs/{run_id}", headers=HEADERS)
        assert result.status_code == 200
        assert result.json()["status"] == "queued"
        assert result.json()["attempt_count"] == 0
        assert result.json()["status_reason"] is None
