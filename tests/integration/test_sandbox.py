import asyncio
import os
from uuid import uuid4

import pytest

from nexus.workers.sandbox import DockerSandbox
from nexus.workers.workspace import Workspaces


@pytest.mark.skipif(os.getenv("NEXUS_TEST_DOCKER") != "1", reason="explicit Docker opt-in required")
def test_real_container_qa_and_git_capture(tmp_path):
    workspaces = Workspaces(str(tmp_path / "workspaces"))
    tree = workspaces.prepare(str(uuid4()))
    tree.joinpath("index.html").write_text("""<!doctype html><html lang="en"><head>
    <title>Sandbox check</title><meta name="viewport" content="width=device-width"></head>
    <body><nav><a href="#main">Home</a></nav><main id="main"><h1>Sandbox</h1></main></body></html>""")
    result = asyncio.run(DockerSandbox(str(workspaces.root)).invoke("qa", str(tree), {}))
    assert result.data["passed"] is True
    assert result.data["browser"]["passed"] is True
    for name in ("desktop.png", "mobile.png"):
        assert (tree.parent / "qa-output" / name).read_bytes().startswith(b"\x89PNG")
    commit = workspaces.commit(str(tree))
    assert len(commit["commit_sha"]) == 40
    assert "index.html" in commit["changed_files"]


@pytest.mark.skipif(os.getenv("NEXUS_TEST_DOCKER") != "1", reason="explicit Docker opt-in required")
def test_orphan_cleanup_preserves_valid_leases(orchestration_db, tmp_path):
    import hashlib

    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from apps.api.main import create_app
    from nexus.workers.queue import RunQueue

    token, scope = "orphan-cleanup-fixture" * 3, str(uuid4())
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(orchestration_db, {token: scope})) as client:
        project = client.post("/api/v1/projects", headers=headers, json={"name": "Cleanup"}).json()
        run = client.post(
            "/api/v1/tasks",
            headers={**headers, "Idempotency-Key": "cleanup"},
            json={"project_id": project["id"], "instruction": "Test cleanup"},
        ).json()

        async def docker(*arguments):
            process = await asyncio.create_subprocess_exec(
                "docker",
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            output, _ = await process.communicate()
            return process.returncode, output.decode().strip()

        async def scenario():
            engine = create_async_engine(orchestration_db)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            sandbox = DockerSandbox(str(tmp_path / "cleanup-root"))
            identifier = None
            try:
                lease = await RunQueue(sessions).claim()
                code, identifier = await docker(
                    "run",
                    "-d",
                    "--rm",
                    "--network",
                    "none",
                    "--read-only",
                    "--user",
                    "1000:1000",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--label",
                    f"nexus.owner={sandbox.owner}",
                    "--label",
                    f"nexus.run_id={lease.run_id}",
                    "--label",
                    f"nexus.lease_hash={hashlib.sha256(lease.token.encode()).hexdigest()}",
                    "--entrypoint",
                    "python",
                    "nexus-worker:local",
                    "-c",
                    "import time; time.sleep(60)",
                )
                assert code == 0
                await sandbox.reconcile(sessions)
                assert (await docker("inspect", identifier))[0] == 0
                response = await asyncio.to_thread(
                    client.post, f"/api/v1/runs/{run['id']}/cancel", headers=headers
                )
                assert response.status_code == 200
                await sandbox.reconcile(sessions)
                assert (await docker("inspect", identifier))[0] != 0
            finally:
                if identifier:
                    await docker("rm", "-f", identifier)
                await engine.dispose()

        asyncio.run(scenario())
