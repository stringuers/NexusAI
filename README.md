# NEXUS AI

A working early command center for durable AI-assisted project execution.

The implemented LangGraph path is:

**Task → OpenAI plan → optional parallel Kimi/Gemini → isolated Claude development →
static + Chromium QA → independent Codex review → bounded repair → human approval →
hash-verified ZIP, report and screenshots.**

The complete state machine is integration-tested with controlled provider fixtures.
Official live adapters are implemented; a credentialed multi-provider run has not been
performed. Missing configuration is recorded as **Not configured / blocked**, never
simulated. This is an early static-frontend workflow, not a production-ready agency or
completion of every milestone in the original specification.

## Start locally

Requires Python 3.12+, uv, Node 22+, Git and Docker Desktop/Engine.

```sh
uv sync --locked
npm ci --prefix apps/web
# Preserve any existing .env. Use a dedicated private file.
cp .env.example .env.nexus.local
# Set NEXUS_API_TOKEN to a generated value: openssl rand -hex 32
chmod 600 .env.nexus.local
set -a
source .env.nexus.local
set +a
docker compose -f infra/compose.yaml up -d postgres egress
uv run alembic upgrade head
docker build -f infra/docker/worker.Dockerfile -t nexus-worker:local .
```

Run in separate terminals after loading the same environment:

```sh
uv run uvicorn apps.api.main:app_factory --factory --host 127.0.0.1 --port 8110
```

```sh
NEXUS_API_URL=http://127.0.0.1:8110 npm run dev --prefix apps/web -- --port 3101
```

```sh
uv run python -m nexus.workers.runtime
```

Open **http://127.0.0.1:3101**. Sign in with the workspace token from your private
configuration. The browser session uses an HttpOnly, SameSite=Strict cookie. API docs
are at http://127.0.0.1:8110/docs. The API uses service-token authentication scoped to a
workspace; individual user identities/OIDC are not implemented.

The development database binds **127.0.0.1:55432**. Existing services on 5432 are
preserved. The separate local configuration created during development is gitignored.
Never paste provider keys into project briefs or source documents.

## Configure live agents

Set these in the private environment file, then restart the API and worker:

| Agent | Required variables | Role |
|---|---|---|
| OpenAI | OPENAI_API_KEY, NEXUS_PLANNER_MODEL | Validated structured plan |
| Claude | ANTHROPIC_API_KEY, NEXUS_CLAUDE_MODEL | Development in a restricted container |
| Codex | OPENAI_API_KEY, NEXUS_CODEX_MODEL | Official TypeScript SDK, read-only review |
| Kimi | KIMI_API_KEY, NEXUS_KIMI_MODEL | Optional synthesis of supplied project sources |
| Gemini | GEMINI_API_KEY, NEXUS_GEMINI_MODEL | Optional design specification; PNG input adapter |

Model IDs are explicit configuration, not guessed defaults. Select models supported
by your accounts and the documented structured-output/tool interfaces. A configured
agent is **not** reported healthy until checked; current health is `not_checked`.

The initial target is a self-contained static frontend with index.html, embedded CSS/JS,
local assets, accessible navigation and responsive layout. It does not install arbitrary
packages or clone arbitrary remote repositories. Research currently synthesizes supplied
source documents, not independent web browsing. Gemini specifications are not generated
image assets. Manus has a tested v2 protocol adapter and verified receipt endpoint;
external-task dispatch/resumption is not wired into the main graph. Hermes is unavailable.

## Use the command center

Create a project, save approved requirements or import a text document in Projects,
and submit a brief with a dispatch budget. Optional specialist checkboxes require their
providers to be configured. Inspect live persisted events, agent stage results and the
read-only task graph. Cancel a run cooperatively or retry a blocked run after correcting
configuration. Uncertain provider calls are deliberately not automatically replayed.

Passing work appears in Approvals with the exact artifact hashes. Approve to queue
resumption and release delivery, or reject/request changes to reject delivery. Request
changes currently ends delivery; it does not automatically start another coding loop.
Artifacts can be downloaded for authenticated review before approval; this does not
publish or deploy them. A worker must be running for approval resumption.

## Storage and budgets

Local development objects live in `.data/artifacts`; Git worktrees in `.data/workspaces`.
PostgreSQL stores canonical metadata and LangGraph checkpoints. SQLite checkpoints are
supported only for development/tests. Set NEXUS_S3_BUCKET and optional NEXUS_S3_ENDPOINT
plus standard AWS credentials/region to use an S3-compatible private bucket. Provision
the bucket yourself. Writes and reads verify actual bytes against SHA-256. S3 is contract-
tested with fixtures; no live S3 account has been exercised.

Budgets are dispatch reservations: per-run, per-project and daily per workspace. Default
stage reservations are $0.50 planning, $1.00 development, $0.50 review, and $0.50 per
optional specialist. QA reserves no provider cost. Reservations are enforced atomically;
known configuration failures refund them. Unknown in-flight calls retain reservations.
These are **not exact billed-cost ceilings**. Provider pricing, reasoning tokens, cost
reporting and SDK budget overshoot require further billing reconciliation. Claude also
receives its SDK max_budget_usd. Reported costs are distinguished from reservations.

## Checks

```sh
uv run ruff check .
uv run pytest -q
npm run typecheck --prefix apps/web
npm run test --prefix apps/web
npm run build --prefix apps/web
npm audit --prefix apps/web
npm audit --prefix packages/codex-worker
uv run pip-audit
```

Enable real PostgreSQL test databases and real isolated Chromium QA explicitly:

```sh
NEXUS_TEST_DATABASE_URL=postgresql+asyncpg://nexus:local-development-only@127.0.0.1:55432/nexus \
NEXUS_TEST_DOCKER=1 uv run pytest -q
```

The test database user must be allowed to create/drop temporary databases. Never point
the test-admin URL at production. Tests use unique temporary database names.

With API and web running, configure NEXUS_E2E_TOKEN or use the private local development
configuration, then run `npm run test:e2e --prefix apps/web`. Set NEXUS_WEB_URL if your
web port differs; run `npx playwright install chromium` from apps/web if needed. An
existing Chromium executable can be selected via PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH.
Gitleaks directory scanning can use `.gitleaks.local.toml` to exclude private local configuration;
CI uses the stricter `.gitleaks.toml` so accidentally committed environment files are scanned.
Browser tests create real projects/tasks labelled Browser mission; they are test actions,
not fabricated operational fixtures.

## Optional containerized control plane

`docker compose -f infra/compose.yaml --profile app up -d --build` provides migrations,
API on 8111 and web on 3102. The trusted worker supervisor remains on the host: no
Docker socket is mounted into API, web or agent containers. Container packaging is
separately validated; see implementation status for the latest execution evidence.

See [implementation status](docs/IMPLEMENTATION_STATUS.md),
[sandbox threat model](docs/security/SANDBOX.md), [recovery](docs/setup/RECOVERY.md), and
[n8n integration](integrations/n8n/README.md). Production deployment, protected-branch
writes, outbound communications, purchases and destructive operations are not exposed
as agent tools. See the status document for remaining release blockers.
