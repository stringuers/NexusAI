# ADR 0002: durable queue delivery and cancellation

Accepted 2026-11-13. Extends ADR 0001; does not introduce a second orchestrator.

A separate one-shot preflight process claims a persisted run with a time-limited lease.
The database owns lease time. PostgreSQL uses SELECT FOR UPDATE SKIP LOCKED; all
backends repeat eligibility in the UPDATE predicate. Each acquisition increments a
bounded attempt counter and rotates an opaque ownership token. Heartbeat and outcome
writes require the current unexpired token. Expired attempts are reclaimed, or marked
failed when the configured attempt limit is exhausted. All workers must use the same
lease/attempt configuration. Tokens are not exposed through the API or CLI output.

The worker currently records blocked/execution_pipeline_not_implemented. It does not
inspect credentials, invoke providers, generate artifacts, or claim execution success.
Blocked runs are not automatically retried. A future authenticated retry operation
must explicitly define attempts, budgets, and deduplication semantics.

Cancellation is workspace-scoped and atomic: queued/running/blocked -> cancelled.
It revokes the lease immediately; repeated cancellation is idempotent. Failed and
other terminal states return 409. Cancellation of a foreign/missing run returns 404.
No processes or external actions currently run. Later execution workers must poll for
revocation and terminate their sandbox; fencing database writes alone cannot terminate
a process or prevent duplicate external effects. Crash replay is not safe for external
side effects until durable idempotency records and LangGraph checkpoints are implemented.

No success transition is exposed by the lease service: completion needs verified
artifacts, independent review and approval. This is queue delivery infrastructure,
not implementation of workflow planning, scheduling, checkpoints, or provider adapters.

Migration 0002 is additive and tested with a populated 0001 database. SQLite concurrency,
recovery, cancellation and subprocess preflight tests pass. PostgreSQL SQL and locking
behavior remain unverified locally because Docker's daemon is unavailable.

Official interfaces checked:
- https://docs.sqlalchemy.org/en/20/orm/queryguide/dml.html
- https://www.postgresql.org/docs/current/sql-select.html (SKIP LOCKED queues)
