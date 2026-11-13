# Sandbox threat model

Assets: host filesystem, project isolation, provider credentials, canonical decisions,
budgets, approvals, artifact integrity, availability. Repository files, source documents,
model outputs, browser content and generated code are untrusted.

The trusted host supervisor creates a unique Git repository/worktree per run. Containers
mount only that worktree, not the parent repository, platform configuration, Docker
socket or unrelated host paths. Claude gets scoped file/search tools only, with typed
inputs and a PreToolUse hook; hidden/outside paths, shell tools and escalation requests
are denied. Each development attempt permits at most 100 authorized tool calls and
30 MiB of cumulative authorized write content. Tool availability intersects validated plan requests with server policy.
Codex runs in a separate read-only mount using its official SDK. QA mounts source read-
only, has no network or provider keys, and writes screenshots into a separate output
folder. Generated code never runs directly on the host. Git commands use trusted Git
metadata and hooks disabled. Symlinks, devices, oversized/many files are rejected.

Containers run non-root with a read-only root filesystem, no-new-privileges, memory/CPU/
PID limits, bounded output, tmpfs and timeouts. Coding/review capabilities are dropped.
Chromium QA alone adds SYS_CHROOT plus the official Playwright seccomp profile to retain
Chromium's namespace sandbox. No SYS_ADMIN, privileged mode, host network or host IPC.
A real Docker test verifies browser startup and screenshots under these restrictions.

Provider workers use an internal network and a CONNECT-only proxy allowing only
api.anthropic.com and api.openai.com:443. The supervisor verifies that the network is
internal. The operator must protect Docker/network configuration from untrusted changes.
Network denial for QA is Docker-level. Proxy hostnames are server configuration, not
model output. API keys pass via stdin to the worker, never command-line arguments.
Known secrets are redacted from recorded provider output; provider stderr is discarded.
Redaction is defense in depth, not a guarantee against encoded or novel secret leakage.

Canonical state changes require the active database lease. Heartbeat loss/timeouts
cancel execution and trigger container removal. A stage journal caches completed calls;
uncertain calls after crashes are blocked for manual recovery. Cancellation is cooperative
(up to the heartbeat interval). A control-plane/host crash can leave an orphan container until supervision resumes.
A periodic reconciler removes only containers labelled for this installation when their
canonical run/lease is cancelled, expired or superseded; valid lease hashes are preserved.
This behavior is verified with real containers. Operators must still inspect uncertain
provider calls before recovery. Retention cleanup and stronger failure handling remain pending.
No claim of exactly-once external side effects is made.

Docker shares a kernel and is not a hardened hostile multi-tenant boundary. Production
needs a dedicated worker host, OS patching, stronger VM/microVM isolation where appropriate,
secret broker/egress enforcement, image scanning/signing, constrained daemon access and
operational incident procedures. Do not expose this early deployment as a public service.
Service-token identity is workspace-level, not a full user/membership authorization model.
Deploy behind TLS and edge authentication/rate controls. Authenticated workspace rate
limits are persisted; unauthenticated abuse still needs edge controls.

Approvals bind action parameters and artifact hashes. The authenticated persisted decision
is authoritative; LangGraph resume values cannot authorize delivery. Approval does not
publish or deploy anything. Artifact access checks workspace metadata and verifies bytes;
files are downloaded as attachments rather than served as active project HTML on the
control-plane origin. Keep object buckets private.
