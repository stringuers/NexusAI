# NEXUS AI implementation status

Updated 2026-11-13. The original supplied directory contained only an empty Git repository;
there was no prior source, on-disk AGENTS.md, implementation status or verified history.
User-provided Kluster rules were retained throughout. Existing .env was preserved; the
separate private .env.nexus.local is excluded from Git and Docker image contexts.

## Current verified implementation

A real LangGraph orchestration path is implemented and integration-tested:

Task intake → context retrieval → validated OpenAI plan → optional parallel Kimi/Gemini
→ isolated Claude worker → deterministic static + Chromium QA → independent Codex review
→ at most two repair iterations → persisted authenticated approval → verified delivery.

Official live adapters exist. No credentialed multi-provider execution has occurred.
Provider fixtures appear only in tests. Missing credentials/models produce an explicit
blocked state; they do not produce fake work or metrics. The intended target of this
first slice is a self-contained static frontend, not arbitrary full-stack development.

| Area | Implemented and verified | Remaining |
|---|---|---|
| API / projects | Authenticated workspace-scoped create/list/detail/edit, task/run intake, validation, idempotency | Full users/workspaces/membership identity model; POST /runs alias |
| Durable execution | PostgreSQL leases, bounded recovery, heartbeat fencing, cancellation, restart-safe stage journal, PostgreSQL LangGraph checkpoints, stale-container reconciliation | Manual recovery UI, stronger worker failure taxonomy |
| Orchestration | Typed validated DAG, serialized coding, concurrent read-only specialists, QA/review routing, bounded repairs, interrupt/resume | Arbitrary dependency task dispatch, more workflow templates, provider transient retry policy |
| Development / review | Official Claude Python SDK and Codex TypeScript SDK, isolated Git worktrees, commit/change metadata, restricted tools, call/write-byte caps | Live credentialed provider runs; Codex fallback coding; arbitrary repositories |
| QA | Independent static HTML and sandboxed Chromium desktop/mobile checks, actual screenshot files | Target-specific unit/E2E generation, arbitrary builds/typechecks, Firefox/WebKit parity |
| Approval / delivery | Exact parameter/hash binding, authenticated auditable decisions, replay-safe resume, source ZIP + report + screenshots | Production preview deployment and publication gates |
| Artifacts | Local objects, S3 adapter, byte verification, scoped download, metadata | Live S3 validation; richer previews; retention lifecycle |
| Memory | Versioned source notes, approved-version precedence, bounded project/workspace retrieval, text import UI | Binary/PDF/image ingestion pipeline, semantic retrieval/conflict UI |
| Providers | OpenAI/Claude/Codex/Kimi/Gemini contracts tested; Manus v2 operation adapter + RSA receipt verification | Manus persisted external-task dispatch/poll/resume/artifact lifecycle; Hermes |
| Automation | Signed n8n intake, durable deduplication, importable authenticated intake export | Live n8n test, notification/outbox/GitHub workflows |
| Dashboard | Next.js/React/strict TS/Tailwind, local shadcn-style primitive, Lucide, TanStack Query, RHF/Zod, React Flow, SSE | Full ten-page product scope, Monaco inspection, editable provider administration |
| Cost / security | Per-run/project/day dispatch reservations, database-backed workspace rate limits, token/report accounting, request IDs, metadata logs, output redaction | Exact billed-cost enforcement/reconciliation, provider quotas, unauthenticated edge limits, OTel export, production auth |
| Delivery setup | Locked dependencies, Compose PostgreSQL/proxy/API/web/migrations, non-root containers, CI config, recovery/threat docs | Remote CI/deployment, production PITR/RPO/RTO and operational hardening |

## Verification evidence

Most recent comprehensive run before final documentation:

- `NEXUS_TEST_DATABASE_URL=... NEXUS_TEST_DOCKER=1 .venv/bin/pytest -q`:
  **36 passed in 15.06s**, no skips. PostgreSQL-backed orchestration and real Docker/
  sandboxed Chromium QA enabled. Older intake regression tests intentionally use SQLite.
- Earlier default suite: **33 passed, 2 skipped** (before the final archive safety test;
  Docker tests require explicit opt-in). The comprehensive run above includes every test.
- `.venv/bin/ruff check .`: all checks passed.
- `npm run typecheck --prefix apps/web`: passed.
- `npm run test --prefix apps/web`: **3 passed**.
- `npm run build --prefix apps/web`: production Webpack build passed.
- Docker worker, API and web images built successfully. Compose migrations ran and
  API/web/PostgreSQL/proxy started. Local app: http://127.0.0.1:3102; API: 8111. The trusted host worker is running; private provider configuration is absent,
  so live missions block honestly rather than calling simulated providers.
- Playwright expanded desktop/mobile lifecycle + CSRF run: **2 passed in 2.8s** against
  the fully containerized deployment, including project editing and versioned requirements.
  Earlier host API browser run also passed.
- `npm audit` for dashboard and Codex worker: **0 vulnerabilities** after upgrading Vitest.
- `pip-audit`: **110 packages audited, 0 known vulnerabilities**.
- Gitleaks 8.30.1 redacted directory scan: **0 leaks** in scanned source. Private env files,
  installed dependencies and generated outputs were excluded; this is not a scan of secrets
  intentionally stored in private local configuration.
- Local `pg_dump`/`pg_restore` drill passed: six canonical table counts matched in a fresh
  temporary database; a private backup was retained and only the temporary database removed.
- Full fixture flow verifies bounded repair, persisted interrupt, new saver/engine resume,
  no repeated completed provider calls, scoped approval, hash-verified ZIP download and SSE.
- Additional tests cover DAG cycles/tool escalation, workspace isolation, migration data
  preservation, lease races/expiry/exhaustion, stale worker fencing, cancellation, quota
  exhaustion, rate limiting across API instances, configured retry refunds, source provenance,
  concurrent specialists, SDK protocols/options, path traversal, symlinks, redaction, signed
  webhook freshness and deduplication, plus real worker CLI unconfigured/retry behavior. A real orphan-container test verifies
  valid leases are preserved and cancelled work is removed.

Failures encountered and resolved:

- Initial Alembic test subprocess PATH error: use sys.executable -m alembic.
- Initial import/format/type errors: corrected and verified.
- Frontend form syntax and task-to-monitor navigation defects: fixed.
- Next.js internal-host CSRF mismatch: use browser host/canonical origin; tested cross-origin rejection.
- Mobile sign-out was hidden: added visible mobile control and reset navigation scroll.
- Central tool-registry export regression: SDK contract test caught it; restored export.
- Missing provider configuration incorrectly resembled an uncertain call: explicit not-started
  journal state now refunds and retries safely; uncertain calls remain non-replayable.
- Docker initially unavailable/ports occupied: started Desktop, used separate port 55432.
- Docker Hub DNS timeouts: direct official base image pulls succeeded, then builds passed.
- Turbopack compiler socket failure: supported Webpack build used and documented.
- Vitest advisories: upgraded to patched 5.1.0; audits now clean.
- Chromium namespace sandbox needed chroot: QA-only SYS_CHROOT capability and official
  Playwright seccomp policy allowed sandboxed startup; real screenshot test passes.

## Milestone interpretation and blockers

M1 now has a runnable UI/API/database/queue vertical slice, with service-token identity.
M2/M3 core execution and recovery are implemented with fixture-backed full-path evidence,
real PostgreSQL and real isolated QA. Live-agent acceptance is still unverified, so the
full M2/M3 milestones are not declared complete. M4/M5 contain tested adapters and intake
features, not complete specialist/automation factories. Full Website Factory (M6) and
production hardening (M7) remain incomplete. Redis is deferred while the PostgreSQL queue
and distributed limits provide canonical durable control; no competing orchestrator exists.

No provider configuration path has been supplied for live execution. Provider model IDs
are explicitly configured, never invented. Agent health remains not_checked. The current
private development config has no provider setup; all live integrations are unconfigured.
The optional specialist controls remain disabled until configured. Manus task dispatch
and Hermes are not exposed as working workflows.

Kluster initialization previously returned connectionError; no review/dependency-check
methods are available in this session. No successful Kluster review or clean-review claim
is made. Automated local tests/audits do not replace that missing review.

Next: use an operator-provided private provider environment file, run a bounded live
static-site mission, inspect Claude/Codex sessions and real cost reporting, then complete
external research/Manus lifecycle, stronger identity/sandbox operations, additional workflow
factories and production release gates. Do not mark the original complete product delivered
based only on these documents or fixture results.
