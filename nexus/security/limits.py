from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from nexus.db.models import RateBucket
from nexus.workers.queue import database_time


async def enforce_rate_limit(sessions, workspace_id: str, limit: int):
    async with sessions.begin() as session:
        window = (await database_time(session)) // 60
        insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        statement = insert(RateBucket).values(workspace_id=workspace_id, window=window, count=1)
        statement = statement.on_conflict_do_update(
            index_elements=[RateBucket.workspace_id, RateBucket.window],
            set_={"count": RateBucket.count + 1},
            where=RateBucket.count < limit,
        )
        counted = await session.scalar(statement.returning(RateBucket.count))
        if counted is None:
            raise HTTPException(
                429, "Workspace request limit reached", headers={"Retry-After": "60"}
            )
        await session.execute(delete(RateBucket).where(RateBucket.window < window - 2))
