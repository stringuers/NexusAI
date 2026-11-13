"""Durable delivery leases, not a workflow scheduler.

Leases fence database writes only. Future side effects need their own idempotency
records, sandbox termination, and LangGraph checkpoints before crash replay is safe.
"""

from dataclasses import dataclass
from datetime import UTC
from typing import Literal
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.db.models import Run


@dataclass(frozen=True)
class Lease:
    run_id: str
    token: str
    attempt: int


async def database_time(session: AsyncSession) -> int:
    # Database clock prevents worker host clock skew from invalidating other leases.
    value = await session.scalar(select(func.current_timestamp()))
    return int((value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp())


class RunQueue:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        lease_seconds: int = 60,
        max_attempts: int = 3,
    ):
        if not 5 <= lease_seconds <= 3600 or not 1 <= max_attempts <= 10:
            raise ValueError("Invalid lease duration or attempt limit")
        self.sessions = sessions
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    async def claim(self) -> Lease | None:
        async with self.sessions.begin() as session:
            now = await database_time(session)
            expired = and_(Run.status == "running", Run.lease_expires_at <= now)
            await session.execute(
                update(Run)
                .where(expired, Run.attempt_count >= self.max_attempts)
                .values(
                    status="failed",
                    status_reason="lease_attempts_exhausted",
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            eligible = and_(
                or_(Run.status == "queued", expired), Run.attempt_count < self.max_attempts
            )
            query = select(Run.id).where(eligible).order_by(Run.created_at, Run.id).limit(16)
            if session.bind.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            candidates = (await session.scalars(query)).all()
            for run_id in candidates:
                token = str(uuid4())
                # Repeat eligibility in UPDATE: SQLite and competing stale readers
                # must not acquire an already claimed/cancelled row.
                attempt = await session.scalar(
                    update(Run)
                    .where(Run.id == run_id, eligible)
                    .values(
                        status="running",
                        status_reason=None,
                        lease_token=token,
                        lease_expires_at=now + self.lease_seconds,
                        attempt_count=Run.attempt_count + 1,
                    )
                    .returning(Run.attempt_count)
                )
                if attempt is not None:
                    return Lease(run_id, token, attempt)
            return None

    async def heartbeat(self, lease: Lease) -> bool:
        return await self._owned_update(lease, extend=True)

    async def finish(self, lease: Lease, status: Literal["blocked", "failed"], reason: str) -> bool:
        # Deliberately no success transition before verified artifact delivery exists.
        if status not in {"blocked", "failed"} or not reason or len(reason) > 200:
            raise ValueError("Invalid worker outcome")
        return await self._owned_update(
            lease, status=status, status_reason=reason, lease_token=None, lease_expires_at=None
        )

    async def _owned_update(self, lease: Lease, *, extend: bool = False, **values) -> bool:
        async with self.sessions.begin() as session:
            now = await database_time(session)
            if extend:
                values["lease_expires_at"] = now + self.lease_seconds
            matched = await session.scalar(
                update(Run)
                .where(
                    Run.id == lease.run_id,
                    Run.status == "running",
                    Run.lease_token == lease.token,
                    Run.lease_expires_at > now,
                )
                .values(**values)
                .returning(Run.id)
            )
            return matched is not None
