"""Docker supervisor. No agent process executes directly on the control-plane host."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from nexus.orchestration.contracts import Blocked, NotConfigured, ProviderResult


class DockerSandbox:
    def __init__(self, root: str, timeout: int = 600, lease=None):
        self.root, self.timeout = Path(root).resolve(), timeout
        self.lease = lease
        self.owner = hashlib.sha256(str(self.root).encode()).hexdigest()[:24]

    async def invoke(self, stage: str, workspace: str, request: dict) -> ProviderResult:
        path = Path(workspace).resolve()
        if not path.is_relative_to(self.root) or path.name != "worktree":
            raise Blocked("invalid_workspace")
        if stage not in {"claude", "codex", "qa"}:
            raise Blocked("unsupported_worker_stage")
        name = f"nexus-{uuid4()}"
        network = "none" if stage == "qa" else os.getenv("NEXUS_SANDBOX_NETWORK", "nexus-sandbox")
        image = os.getenv("NEXUS_WORKER_IMAGE", "nexus-worker:local")

        async def inspect(*arguments):
            try:
                check = await asyncio.create_subprocess_exec(
                    "docker",
                    *arguments,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(check.communicate(), 15)
                if check.returncode:
                    raise NotConfigured("sandbox_infrastructure_not_configured")
                return stdout.decode().strip()
            except FileNotFoundError:
                raise NotConfigured("docker_not_configured") from None

        await inspect("image", "inspect", "--format", "{{.Id}}", image)
        if (
            stage != "qa"
            and await inspect("network", "inspect", "--format", "{{.Internal}}", network) != "true"
        ):
            raise NotConfigured("sandbox_requires_internal_network")
        args = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--user",
            "1000:1000",
            "--label",
            f"nexus.owner={self.owner}",
            "--label",
            f"nexus.run_id={path.parent.name}",
            "--label",
            f"nexus.lease_hash={hashlib.sha256(self.lease.token.encode()).hexdigest() if self.lease else 'test'}",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=128",
            "--memory=1g",
            "--cpus=1",
            "--network",
            network,
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
            "--mount",
            f"type=bind,src={path},dst=/workspace"
            + (",readonly" if stage in {"codex", "qa"} else ""),
            "--workdir",
            "/workspace",
            "--env",
            "HOME=/tmp/home",
        ]
        if stage != "qa":
            # Operator-created internal network must only route through the allowlisted proxy.
            args += [
                "--env",
                "HTTPS_PROXY=http://nexus-egress:3128",
                "--env",
                "HTTP_PROXY=http://nexus-egress:3128",
                "--env",
                "NODE_USE_ENV_PROXY=1",
            ]
        if stage == "qa":
            output = path.parent / "qa-output"
            output.mkdir(exist_ok=True)
            output.chmod(0o777)
            profile = Path(__file__).resolve().parents[2] / "infra/docker/chromium-seccomp.json"
            args += [
                "--cap-add=SYS_CHROOT",
                "--security-opt",
                f"seccomp={profile}",
                "--mount",
                f"type=bind,src={output},dst=/output",
            ]
        args += [image, stage]
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def bounded_output(stream, limit):
                chunks, size = [], 0
                while chunk := await stream.read(16384):
                    size += len(chunk)
                    if size > limit:
                        raise Blocked("worker_output_limit")
                    chunks.append(chunk)
                return b"".join(chunks)

            async def exchange():
                process.stdin.write(json.dumps(request).encode())
                await process.stdin.drain()
                process.stdin.close()
                readers = [
                    asyncio.create_task(bounded_output(process.stdout, 200000)),
                    asyncio.create_task(bounded_output(process.stderr, 200000)),
                ]
                try:
                    output = await asyncio.gather(*readers)
                    await process.wait()
                    return output[0]
                finally:
                    for reader in readers:
                        reader.cancel()
                    await asyncio.gather(*readers, return_exceptions=True)

            stdout = await asyncio.wait_for(exchange(), self.timeout)
            if process.returncode != 0:
                raise Blocked("sandbox_worker_failed")
            if len(stdout) > 200000:
                raise Blocked("worker_output_limit")
            try:
                return ProviderResult.model_validate_json(stdout)
            except ValueError:
                raise Blocked("invalid_worker_result") from None
        except FileNotFoundError:
            raise Blocked("docker_unavailable") from None
        except TimeoutError:
            raise Blocked("worker_timeout") from None
        finally:
            # Cancellation/lease loss must terminate the container, not just Docker's client.
            try:
                cleanup = await asyncio.create_subprocess_exec(
                    "docker",
                    "rm",
                    "-f",
                    name,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(cleanup.wait(), 15)
            except (OSError, TimeoutError):
                pass
            if process and process.returncode is None:
                process.kill()
                await process.wait()

    async def reconcile(self, sessions):
        """Remove only this installation's containers whose canonical lease is no longer valid."""
        from sqlalchemy import select

        from nexus.db.models import Run
        from nexus.workers.queue import database_time

        async def docker(*arguments):
            process = await asyncio.create_subprocess_exec(
                "docker",
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            output, _ = await asyncio.wait_for(process.communicate(), 15)
            if process.returncode:
                raise Blocked("sandbox_reconciliation_failed")
            return output

        identifiers = (
            (await docker("ps", "-q", "--filter", f"label=nexus.owner={self.owner}"))
            .decode()
            .split()
        )
        for identifier in identifiers:
            details = json.loads(await docker("inspect", identifier))[0]
            labels = details["Config"]["Labels"]
            async with sessions() as session:
                now = await database_time(session)
                run = await session.scalar(select(Run).where(Run.id == labels.get("nexus.run_id")))
                active = (
                    run
                    and run.status == "running"
                    and run.lease_token
                    and run.lease_expires_at is not None
                    and run.lease_expires_at > now
                    and hashlib.sha256(run.lease_token.encode()).hexdigest()
                    == labels.get("nexus.lease_hash")
                )
            if not active:
                await docker("rm", "-f", identifier)
