"""Authenticated intake. Queued records never imply an agent has executed."""

import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.operations import operations
from apps.api.webhooks import webhooks
from nexus.db.models import Event, Project, Run, Task
from nexus.security.limits import enforce_rate_limit
from nexus.security.middleware import RequestContext


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    budget_microusd: int = Field(default=100000000, ge=500000, le=1000000000)


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    budget_microusd: int | None = Field(default=None, ge=500000, le=1000000000)

    @model_validator(mode="after")
    def non_null_changes(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("Provide at least one non-null project field")
        return self


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    project_id: UUID
    instruction: str = Field(min_length=1, max_length=20000)
    budget_microusd: int = Field(default=5000000, ge=500000, le=100000000)
    research: bool = False
    design: bool = False


class Record(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str


class ProjectOutput(Record):
    name: str
    description: str
    budget_microusd: int


class RunOutput(Record):
    task_id: str
    status: str
    status_reason: str | None = None
    attempt_count: int = 0
    budget_microusd: int = 5000000
    reserved_microusd: int = 0


class TaskOutput(Record):
    project_id: str
    instruction: str


def create_app(database_url: str, credentials: dict[str, str]) -> FastAPI:
    # Token -> workspace mappings are server-owned, never supplied in request bodies.
    if not credentials or any(len(token) < 32 for token in credentials):
        raise ValueError("Configure workspace bearer tokens of at least 32 characters")
    for workspace in credentials.values():
        UUID(workspace)
    credentials = {token: str(UUID(scope)) for token, scope in credentials.items()}
    rate_limit = int(os.getenv("NEXUS_API_RATE_LIMIT", "600"))
    if rate_limit < 1:
        raise ValueError("API rate limit must be positive")
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await engine.dispose()

    app = FastAPI(title="NEXUS AI Control Plane", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestContext)
    bearer = HTTPBearer(auto_error=False)

    async def workspace(
        request: Request,
        auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        if auth:
            supplied = hashlib.sha256(auth.credentials.encode()).digest()
            for token, scope in credentials.items():
                if secrets.compare_digest(supplied, hashlib.sha256(token.encode()).digest()):
                    await enforce_rate_limit(sessions, scope, rate_limit)
                    request.state.workspace_id = scope
                    return scope
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})

    Scope = Annotated[str, Depends(workspace)]

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/v1/projects", response_model=ProjectOutput, status_code=201)
    async def create_project(body: ProjectInput, scope: Scope):
        async with sessions.begin() as session:
            project = Project(workspace_id=scope, **body.model_dump())
            session.add(project)
        return project

    @app.get("/api/v1/projects", response_model=list[ProjectOutput])
    async def projects(
        scope: Scope, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        async with sessions() as session:
            return (
                await session.scalars(
                    select(Project)
                    .where(Project.workspace_id == scope)
                    .order_by(Project.created_at, Project.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()

    @app.get("/api/v1/projects/{project_id}", response_model=ProjectOutput)
    async def project(project_id: UUID, scope: Scope):
        async with sessions() as session:
            item = await session.scalar(
                select(Project).where(Project.id == str(project_id), Project.workspace_id == scope)
            )
            if not item:
                raise HTTPException(404, "Project not found")
            return item

    @app.patch("/api/v1/projects/{project_id}", response_model=ProjectOutput)
    async def edit_project(project_id: UUID, body: ProjectPatch, scope: Scope):
        async with sessions.begin() as session:
            project = await session.scalar(
                update(Project)
                .where(Project.id == str(project_id), Project.workspace_id == scope)
                .values(**body.model_dump(exclude_unset=True))
                .returning(Project)
            )
            if not project:
                raise HTTPException(404, "Project not found")
            return project

    @app.post("/api/v1/tasks", response_model=RunOutput, status_code=202)
    async def submit(
        body: TaskInput,
        scope: Scope,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
    ):
        async def existing(session):
            task = await session.scalar(
                select(Task).where(
                    Task.workspace_id == scope, Task.idempotency_key == idempotency_key
                )
            )
            if task:
                if (
                    task.project_id != str(body.project_id)
                    or task.instruction != body.instruction
                    or any(
                        bool(task.options.get(key, False)) != getattr(body, key)
                        for key in ("research", "design")
                    )
                ):
                    raise HTTPException(409, "Idempotency key already used for a different request")
                run = await session.scalar(select(Run).where(Run.task_id == task.id))
                if run.budget_microusd != body.budget_microusd:
                    raise HTTPException(409, "Idempotency budget conflict")
                return run
            return None

        async with sessions() as session:
            item = await session.scalar(
                select(Project).where(
                    Project.id == str(body.project_id), Project.workspace_id == scope
                )
            )
            if not item:
                raise HTTPException(404, "Project not found")
            previous = await existing(session)
            if previous:
                return previous
            task = Task(
                workspace_id=scope,
                project_id=str(body.project_id),
                instruction=body.instruction,
                idempotency_key=idempotency_key,
                options={"research": body.research, "design": body.design},
            )
            session.add(task)
            try:
                await session.flush()
                run = Run(workspace_id=scope, task_id=task.id, budget_microusd=body.budget_microusd)
                session.add(run)
                await session.flush()
                session.add(
                    Event(
                        workspace_id=scope,
                        run_id=run.id,
                        sequence=1,
                        kind="run_queued",
                        payload={"task_id": task.id},
                    )
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                previous = await existing(session)
                if previous:
                    return previous
                raise
            return run

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskOutput)
    async def task(task_id: UUID, scope: Scope):
        async with sessions() as session:
            item = await session.scalar(
                select(Task).where(Task.id == str(task_id), Task.workspace_id == scope)
            )
            if not item:
                raise HTTPException(404, "Task not found")
            return item

    @app.get("/api/v1/runs/{run_id}", response_model=RunOutput)
    async def run(run_id: UUID, scope: Scope):
        async with sessions() as session:
            item = await session.scalar(
                select(Run).where(Run.id == str(run_id), Run.workspace_id == scope)
            )
            if not item:
                raise HTTPException(404, "Run not found")
            return item

    @app.post("/api/v1/runs/{run_id}/cancel", response_model=RunOutput)
    async def cancel(run_id: UUID, scope: Scope):
        async with sessions.begin() as session:
            item = await session.scalar(
                update(Run)
                .where(
                    Run.id == str(run_id),
                    Run.workspace_id == scope,
                    Run.status.in_(["queued", "running", "blocked", "awaiting_approval"]),
                )
                .values(
                    status="cancelled",
                    status_reason="cancelled_by_user",
                    lease_token=None,
                    lease_expires_at=None,
                )
                .returning(Run)
            )
            if item:
                sequence = (
                    await session.scalar(
                        select(func.max(Event.sequence)).where(Event.run_id == item.id)
                    )
                    or 0
                ) + 1
                session.add(
                    Event(
                        workspace_id=scope,
                        run_id=item.id,
                        sequence=sequence,
                        kind="run_cancelled",
                        payload={"status": "cancelled"},
                    )
                )
                return item
            item = await session.scalar(
                select(Run).where(Run.id == str(run_id), Run.workspace_id == scope)
            )
            if not item:
                raise HTTPException(404, "Run not found")
            if item.status == "cancelled":
                return item
            raise HTTPException(409, "Run is already terminal")

    app.include_router(operations(sessions, workspace, bearer))
    app.include_router(webhooks(sessions, submit, TaskInput))
    return app


def app_factory() -> FastAPI:
    return create_app(
        os.environ["DATABASE_URL"],
        {os.environ["NEXUS_API_TOKEN"]: os.environ["NEXUS_WORKSPACE_ID"]},
    )
