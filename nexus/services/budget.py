import os

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from nexus.db.models import DispatchBucket, Project, Task
from nexus.orchestration.contracts import Blocked
from nexus.workers.queue import database_time


async def reserve(session, run, amount: int) -> list[tuple[str, int]]:
    if amount == 0:
        return []
    project_id = await session.scalar(select(Task.project_id).where(Task.id == run.task_id))
    limit = await session.scalar(select(Project.budget_microusd).where(Project.id == project_id))
    day = (await database_time(session)) // 86400
    daily = int(os.getenv("NEXUS_DAILY_DISPATCH_MICROUSD", "50000000"))
    if daily < 1:
        raise Blocked("daily_dispatch_disabled")
    keys = []
    for scope, period, ceiling in ((f"project:{project_id}", 0, limit), ("daily", day, daily)):
        if amount > ceiling:
            raise Blocked("project_or_daily_dispatch_budget_exhausted")
        insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        statement = insert(DispatchBucket).values(
            workspace_id=run.workspace_id, scope=scope, period=period, reserved_microusd=amount
        )
        statement = statement.on_conflict_do_update(
            index_elements=[
                DispatchBucket.workspace_id,
                DispatchBucket.scope,
                DispatchBucket.period,
            ],
            set_={"reserved_microusd": DispatchBucket.reserved_microusd + amount},
            where=DispatchBucket.reserved_microusd + amount <= ceiling,
        )
        if await session.scalar(statement.returning(DispatchBucket.reserved_microusd)) is None:
            raise Blocked("project_or_daily_dispatch_budget_exhausted")
        keys.append((scope, period))
    return keys


async def refund(session, run, amount: int, keys: list[tuple[str, int]]):
    for scope, period in keys:
        await session.execute(
            update(DispatchBucket)
            .where(
                DispatchBucket.workspace_id == run.workspace_id,
                DispatchBucket.scope == scope,
                DispatchBucket.period == period,
            )
            .values(reserved_microusd=DispatchBucket.reserved_microusd - amount)
        )
