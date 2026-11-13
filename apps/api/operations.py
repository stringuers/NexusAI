import asyncio
import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from nexus.agents.registry import agents
from nexus.db.models import Approval, Artifact, Event, Execution, Knowledge, Project, Run, now
from nexus.orchestration.contracts import Blocked
from nexus.services.artifacts import configured_objects
from nexus.services.execution import action_hash


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=30000)
    source: str = Field(default="user", min_length=1, max_length=1000)
    approved: bool = False


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject", "request_changes"]
    action_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def operations(sessions, workspace, bearer):
    router = APIRouter(prefix="/api/v1")
    Scope = Annotated[str, Depends(workspace)]

    @router.post("/projects/{project_id}/knowledge", status_code=201)
    async def add_knowledge(project_id: UUID, body: KnowledgeInput, scope: Scope):
        async with sessions.begin() as session:
            project = await session.scalar(
                update(Project)
                .where(Project.id == str(project_id), Project.workspace_id == scope)
                .values(name=Project.name)
                .returning(Project)
            )
            if not project:
                raise HTTPException(404, "Project not found")
            version = (
                await session.scalar(
                    select(func.max(Knowledge.version)).where(
                        Knowledge.project_id == project.id, Knowledge.title == body.title
                    )
                )
                or 0
            ) + 1
            item = Knowledge(
                workspace_id=scope, project_id=project.id, version=version, **body.model_dump()
            )
            session.add(item)
            await session.flush()
            return {"id": item.id, "version": version, "approved": item.approved}

    @router.get("/projects/{project_id}/knowledge")
    async def knowledge(
        project_id: UUID,
        scope: Scope,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        async with sessions() as session:
            if not await session.scalar(
                select(Project.id).where(
                    Project.id == str(project_id), Project.workspace_id == scope
                )
            ):
                raise HTTPException(404, "Project not found")
            rows = (
                await session.scalars(
                    select(Knowledge)
                    .where(Knowledge.project_id == str(project_id), Knowledge.workspace_id == scope)
                    .order_by(Knowledge.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return [
                {
                    "id": r.id,
                    "title": r.title,
                    "content": r.content,
                    "source": r.source,
                    "version": r.version,
                    "approved": r.approved,
                }
                for r in rows
            ]

    @router.get("/agents")
    async def agent_list(scope: Scope):
        return agents()

    @router.get("/agents/{agent_id}")
    async def agent_detail(agent_id: str, scope: Scope):
        for agent in agents():
            if agent["id"] == agent_id:
                return agent
        raise HTTPException(404, "Agent not found")

    @router.get("/runs")
    async def runs(
        scope: Scope, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        async with sessions() as session:
            records = (
                await session.scalars(
                    select(Run)
                    .where(Run.workspace_id == scope)
                    .order_by(Run.created_at.desc(), Run.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return [
                {
                    "id": r.id,
                    "task_id": r.task_id,
                    "status": r.status,
                    "status_reason": r.status_reason,
                    "attempt_count": r.attempt_count,
                    "budget_microusd": r.budget_microusd,
                    "reserved_microusd": r.reserved_microusd,
                }
                for r in records
            ]

    @router.get("/runs/{run_id}/executions")
    async def executions(run_id: UUID, scope: Scope):
        async with sessions() as session:
            run = await session.scalar(
                select(Run).where(Run.id == str(run_id), Run.workspace_id == scope)
            )
            if not run:
                raise HTTPException(404, "Run not found")
            records = (
                await session.scalars(
                    select(Execution)
                    .where(Execution.run_id == run.id, Execution.workspace_id == scope)
                    .order_by(Execution.created_at)
                )
            ).all()
            return [
                {
                    "id": e.id,
                    "stage": e.stage_key,
                    "agent": e.agent,
                    "status": e.status,
                    "result": e.result,
                    "reserved_microusd": e.reserved_microusd,
                }
                for e in records
            ]

    @router.get("/runs/{run_id}/events")
    async def events(
        run_id: UUID,
        scope: Scope,
        request: Request,
        after: int = Query(0, ge=0),
        last_event_id: Annotated[str | None, Header(pattern=r"^[0-9]+$")] = None,
    ):
        key = str(run_id)
        async with sessions() as session:
            if not await session.scalar(
                select(Run.id).where(Run.id == key, Run.workspace_id == scope)
            ):
                raise HTTPException(404, "Run not found")
        cursor = max(after, int(last_event_id or 0))

        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                async with sessions() as session:
                    records = (
                        await session.scalars(
                            select(Event)
                            .where(
                                Event.run_id == key,
                                Event.workspace_id == scope,
                                Event.sequence > cursor,
                            )
                            .order_by(Event.sequence)
                            .limit(100)
                        )
                    ).all()
                    status = await session.scalar(select(Run.status).where(Run.id == key))
                for event in records:
                    cursor = event.sequence
                    payload = json.dumps(
                        {"sequence": cursor, "kind": event.kind, "payload": event.payload}
                    )
                    yield f"id: {cursor}\nevent: execution\ndata: {payload}\n\n"
                if not records and status != "running" and status != "queued":
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/approvals")
    async def approvals(
        scope: Scope, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        async with sessions() as session:
            records = (
                await session.scalars(
                    select(Approval)
                    .where(Approval.workspace_id == scope)
                    .order_by(Approval.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return [
                {
                    "id": a.id,
                    "run_id": a.run_id,
                    "parameters": a.parameters,
                    "action_hash": a.action_hash,
                    "decision": a.decision,
                    "decided_by": a.decided_by,
                }
                for a in records
            ]

    @router.post("/approvals/{approval_id}/decision")
    async def decide(
        approval_id: UUID, body: Decision, scope: Scope, auth: Annotated[object, Depends(bearer)]
    ):
        async with sessions.begin() as session:
            approval = await session.scalar(
                select(Approval).where(
                    Approval.id == str(approval_id), Approval.workspace_id == scope
                )
            )
            if not approval:
                raise HTTPException(404, "Approval not found")
            run = await session.scalar(
                update(Run)
                .where(Run.id == approval.run_id, Run.workspace_id == scope)
                .values(status=Run.status)
                .returning(Run)
            )
            await session.refresh(approval)
            if (
                body.action_hash != approval.action_hash
                or action_hash(approval.parameters) != body.action_hash
            ):
                raise HTTPException(409, "Approval parameters changed")
            if approval.decision:
                if approval.decision != body.decision:
                    raise HTTPException(409, "Approval already decided")
                return {"id": approval.id, "decision": approval.decision}
            if run.status != "awaiting_approval":
                raise HTTPException(409, "Run is not awaiting approval")
            approval.decision, approval.decided_at = body.decision, now()
            approval.decided_by = hashlib.sha256(auth.credentials.encode()).hexdigest()
            run.status, run.status_reason = "queued", None
            sequence = (
                await session.scalar(select(func.max(Event.sequence)).where(Event.run_id == run.id))
                or 0
            ) + 1
            session.add(
                Event(
                    workspace_id=scope,
                    run_id=run.id,
                    sequence=sequence,
                    kind="approval_decided",
                    payload={"approval_id": approval.id, "decision": body.decision},
                )
            )
            return {"id": approval.id, "decision": approval.decision}

    @router.post("/runs/{run_id}/retry")
    async def retry(run_id: UUID, scope: Scope):
        async with sessions.begin() as session:
            run = await session.scalar(
                update(Run)
                .where(Run.id == str(run_id), Run.workspace_id == scope, Run.status == "blocked")
                .values(status="queued", status_reason=None, attempt_count=0)
                .returning(Run)
            )
            if run:
                return {"id": run.id, "status": run.status}
            exists = await session.scalar(
                select(Run.id).where(Run.id == str(run_id), Run.workspace_id == scope)
            )
            raise HTTPException(
                409 if exists else 404, "Run is not blocked" if exists else "Run not found"
            )

    @router.get("/projects/{project_id}/artifacts")
    async def artifacts(
        project_id: UUID,
        scope: Scope,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        async with sessions() as session:
            if not await session.scalar(
                select(Project.id).where(
                    Project.id == str(project_id), Project.workspace_id == scope
                )
            ):
                raise HTTPException(404, "Project not found")
            records = (
                await session.scalars(
                    select(Artifact)
                    .where(Artifact.project_id == str(project_id), Artifact.workspace_id == scope)
                    .order_by(Artifact.created_at)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return [
                {
                    "id": a.id,
                    "run_id": a.run_id,
                    "name": a.name,
                    "sha256": a.sha256,
                    "size": a.size,
                    "media_type": a.media_type,
                }
                for a in records
            ]

    @router.get("/artifacts/{artifact_id}")
    async def artifact(artifact_id: UUID, scope: Scope):
        async with sessions() as session:
            item = await session.scalar(
                select(Artifact).where(
                    Artifact.id == str(artifact_id), Artifact.workspace_id == scope
                )
            )
            if not item:
                raise HTTPException(404, "Artifact not found")
            try:
                objects = configured_objects()
                data = await asyncio.to_thread(objects.read, item.object_key, item.sha256)
            except (OSError, Blocked):
                raise HTTPException(409, "Artifact unavailable or verification failed") from None
            return Response(
                data,
                media_type=item.media_type,
                headers={
                    "Content-Disposition": f'attachment; filename="{item.name}"',
                    "X-Content-Type-Options": "nosniff",
                    "Cache-Control": "private, no-store",
                },
            )

    @router.get("/usage")
    async def usage(scope: Scope):
        async with sessions() as session:
            records = (
                await session.scalars(select(Execution).where(Execution.workspace_id == scope))
            ).all()
            return {
                "dispatch_reserved_microusd": sum(e.reserved_microusd for e in records),
                "input_tokens": sum((e.result or {}).get("input_tokens", 0) for e in records),
                "output_tokens": sum((e.result or {}).get("output_tokens", 0) for e in records),
                "provider_reported_cost_usd": sum(
                    (e.result or {}).get("reported_cost_usd") or 0 for e in records
                ),
                "billing_status": "provider_reported_or_unavailable",
                "executions": len(records),
            }

    return router
