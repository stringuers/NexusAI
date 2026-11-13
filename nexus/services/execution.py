"""Fenced execution journal: checkpoint replay never repeats an uncertain call."""

import hashlib
import json
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from nexus.db.models import Approval, Artifact, Event, Execution, Run, Task
from nexus.memory.retrieval import retrieve
from nexus.orchestration.contracts import Blocked, LeaseLost, NotConfigured, ProviderResult
from nexus.security.redaction import redact
from nexus.services.budget import refund, reserve
from nexus.workers.queue import Lease, database_time


def action_hash(parameters: dict) -> str:
    return hashlib.sha256(
        json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class RunStore:
    def __init__(self, sessions: async_sessionmaker, lease: Lease):
        self.sessions, self.lease = sessions, lease

    async def owned(self, session) -> Run:
        now = await database_time(session)
        run = await session.scalar(
            update(Run)
            .where(
                Run.id == self.lease.run_id,
                Run.status == "running",
                Run.lease_token == self.lease.token,
                Run.lease_expires_at > now,
            )
            .values(status="running")
            .returning(Run)
        )
        if run is None:
            raise LeaseLost()
        return run

    async def event(self, session, run: Run, kind: str, payload: dict):
        sequence = (
            await session.scalar(select(func.max(Event.sequence)).where(Event.run_id == run.id))
            or 0
        ) + 1
        session.add(
            Event(
                workspace_id=run.workspace_id,
                run_id=run.id,
                sequence=sequence,
                kind=kind,
                payload=payload,
            )
        )

    async def context(self) -> dict:
        async with self.sessions.begin() as session:
            run = await self.owned(session)
            task = await session.get(Task, run.task_id)
            return {
                "run_id": run.id,
                "project_id": task.project_id,
                "workspace_id": run.workspace_id,
                "instruction": task.instruction,
                "options": task.options,
                "knowledge": await retrieve(
                    session, run.workspace_id, task.project_id, task.instruction
                ),
            }

    async def stage(
        self, key: str, agent: str, reservation: int, call: Callable[[], Awaitable[ProviderResult]]
    ) -> dict:
        async with self.sessions.begin() as session:
            run = await self.owned(session)
            existing = await session.scalar(
                select(Execution).where(Execution.run_id == run.id, Execution.stage_key == key)
            )
            if existing:
                if existing.status == "succeeded":
                    return existing.result
                if existing.status != "not_started":
                    raise Blocked("uncertain_stage_requires_manual_recovery")
            if reservation < 0 or run.reserved_microusd + reservation > run.budget_microusd:
                raise Blocked("dispatch_budget_exhausted")
            bucket_keys = await reserve(session, run, reservation)
            run.reserved_microusd += reservation
            if existing:
                existing.status = "running"
                existing.reserved_microusd = reservation
            else:
                execution = Execution(
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    stage_key=key,
                    agent=agent,
                    reserved_microusd=reservation,
                )
                session.add(execution)
            await self.event(session, run, "stage_started", {"stage": key, "agent": agent})
        # Do not catch BaseException: LangGraph interrupts and cancellation must propagate.
        try:
            result = await call()
        except NotConfigured:
            async with self.sessions.begin() as session:
                run = await self.owned(session)
                execution = await session.scalar(
                    select(Execution).where(Execution.run_id == run.id, Execution.stage_key == key)
                )
                execution.status = "not_started"
                execution.reserved_microusd = 0
                run.reserved_microusd -= reservation
                await refund(session, run, reservation, bucket_keys)
            raise
        serialized = redact(result.model_dump(mode="json"))
        if len(json.dumps(serialized)) > 200000:
            raise Blocked("provider_result_too_large")
        async with self.sessions.begin() as session:
            run = await self.owned(session)
            execution = await session.scalar(
                select(Execution).where(Execution.run_id == run.id, Execution.stage_key == key)
            )
            execution.status = "succeeded"
            execution.result = serialized
            await self.event(session, run, "stage_completed", {"stage": key, "agent": agent})
        return serialized

    async def approval(self, parameters: dict) -> dict:
        digest = action_hash(parameters)
        async with self.sessions.begin() as session:
            run = await self.owned(session)
            item = await session.scalar(
                select(Approval).where(Approval.run_id == run.id, Approval.action_hash == digest)
            )
            if item is None:
                item = Approval(
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    action_hash=digest,
                    parameters=parameters,
                )
                session.add(item)
                await session.flush()
                await self.event(session, run, "approval_requested", {"approval_id": item.id})
            return {
                "id": item.id,
                "action_hash": digest,
                "parameters": parameters,
                "decision": item.decision,
            }

    async def artifact(
        self, context: dict, name: str, digest: str, size: int, media_type: str
    ) -> dict:
        async with self.sessions.begin() as session:
            run = await self.owned(session)
            item = await session.scalar(
                select(Artifact).where(Artifact.run_id == run.id, Artifact.name == name)
            )
            if item and item.sha256 != digest:
                raise Blocked("artifact_changed_after_capture")
            if item is None:
                item = Artifact(
                    workspace_id=run.workspace_id,
                    project_id=context["project_id"],
                    run_id=run.id,
                    name=name,
                    sha256=digest,
                    size=size,
                    object_key=digest,
                    media_type=media_type,
                )
                session.add(item)
                await session.flush()
                await self.event(session, run, "artifact_stored", {"artifact_id": item.id})
            return {"id": item.id, "name": name, "sha256": digest, "size": size}

    async def settle(self, status: str, reason: str | None = None):
        if status not in {"awaiting_approval", "completed", "rejected", "blocked", "failed"}:
            raise ValueError("Invalid settlement")
        async with self.sessions.begin() as session:
            run = await self.owned(session)
            run.status, run.status_reason = status, reason
            run.lease_token = run.lease_expires_at = None
            await self.event(session, run, "run_status", {"status": status, "reason": reason})
