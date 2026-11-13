# Local operations, backup and recovery

1. Keep private environment configuration outside version control and image contexts.
2. Run PostgreSQL migrations before starting the API; the worker calls the official
   checkpointer setup for its separate LangGraph checkpoint tables.
3. Start the API, web and trusted worker supervisor independently. See README commands.
4. A missing provider/model yields blocked with a public reason code. Correct private
   configuration, restart API/worker, then use Retry. No provider result is simulated.
5. A worker crash leaves a lease recoverable after expiry. Completed journal stages are
   reused. A call left uncertain is not automatically reissued. Inspect provider session
   records, sandbox processes and repository state before any manual recovery. No UI to
   override uncertain stages exists yet; do not delete journal rows to force a replay.
6. After an approval, a run becomes queued. The worker reopens the same PostgreSQL thread
   and uses Command(resume=...) only when an interrupt is pending. The stored authenticated
   decision and exact hashes are checked independently of the resume value.
7. If a run is cancelled, the lease is revoked immediately. The worker observes loss and
   removes its container. After a host crash, restart the trusted supervisor: its reconciler removes containers
   with cancelled, expired or superseded canonical leases and preserves valid work.
   Containers are scoped by installation and run labels. Inspect uncertain provider calls
   before recovery. Source-retention policies remain pending.

Back up the PostgreSQL database (including LangGraph tables), object bucket/local object
folder, and retained Git repositories as one recovery set. Encrypt backups and protect
private configuration separately. For the local development database:

```sh
mkdir -p .data/backups
docker compose -f infra/compose.yaml exec -T postgres pg_dump -U nexus -d nexus -Fc > .data/backups/nexus.dump
```

Take backups while dispatch is stopped for a consistent development snapshot. Restore into
a **new** database first with pg_restore, copy objects/worktrees, run migrations, and verify
artifact hashes and pending approvals before enabling dispatch. A local Compose restore drill verified counts in six canonical tables using a fresh temporary
database; the source database was preserved. Run `uv run python scripts/verify_local_backup.py`
with the dedicated local configuration to repeat it. The script rejects other hosts/ports/databases.
PITR, RPO/RTO and automated backup scheduling have not been exercised as production release gates.
Never use `docker compose down -v` unless intentionally deleting all local database data.

Current generated-site QA targets a static frontend. It does not claim arbitrary build,
application-specific unit-test coverage, browser-engine parity or production preview
hosting. Chromium namespace sandbox failure is a blocker, not a reason to disable it.
