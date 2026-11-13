# ADR 0001: transactional intake before autonomous execution

Status: accepted, 2026-11-13.

The inspected repository contained only .git, no commits, source, status report,
on-disk AGENTS.md, or test history. User-provided review rules apply. Preserve this
finding rather than invent prior milestones.

Build a small M1 subset: FastAPI, async SQLAlchemy, explicit Alembic migrations,
workspace-scoped service-token authorization, projects and transactional task/run
submission. A unique (workspace_id, idempotency_key) constraint prevents duplicate
runs. Both records commit together. Reusing a key with different input is rejected.
Queued records survive restarts but are not yet a functioning background executor.

PostgreSQL remains the intended canonical database. SQLite is only the test harness.
No substitute orchestrator, simulated agent, or provider SDK wrapper is introduced.
A later worker must claim jobs durably with leases and recover interrupted execution;
completed external side effects require their own idempotency records. Do not dispatch
queued jobs until permissions, budget checks, sandboxing, and adapter contracts exist.

Reviewed official interfaces:
- https://fastapi.tiangolo.com/reference/security/ (HTTPBearer)
- https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
  (create_async_engine, async_sessionmaker; one session per operation)

Resolved dependencies are pinned in uv.lock. Live AI SDK documentation must be checked
before implementing those adapters; this milestone contains no AI API calls.

Acceptance: missing/invalid tokens fail; workspace B cannot read or submit to workspace A;
validated project and task persist across application restart; duplicate requests return
one run; conflicting idempotency requests fail; migrations apply to fresh test databases.
