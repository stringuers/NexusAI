# ADR 0003 — LangGraph execution, durable journal and bounded provider autonomy

Accepted 2026-11-13. Extends the working intake/lease foundation.

LangGraph is the only orchestrator. PostgreSQL AsyncPostgresSaver persists transitions
and approval interrupts using a workspace/run thread ID. SQLite checkpointers are test/
development only. Database job leases deliver graph work; they are not another scheduler.
A unique per-run stage journal caches results independently of checkpoints, fences writes
and blocks ambiguous in-flight calls after a crash. Missing configuration is explicitly
not-started and safely refundable/retryable. Independent read-only Kimi/Gemini stages run
concurrently; coding in a shared worktree is serialized. Repairs are bounded to two.

The initial target is a small static frontend, intentionally avoiding arbitrary package
installs, repository commands and preview deployment before their permission model exists.
Claude uses its real Python Agent SDK inside a restricted container. Codex uses the
TypeScript SDK in a separate read-only process/container. Deterministic static and
Chromium checks run independently. A user approves exact hashes, then the same durable
graph resumes to finish delivery. Provider fixture tests are isolated from runtime code.

Project source context is versioned. Approved versions take precedence over suggestions;
retrieval is scoped and bounded. Canonical context is snapshotted into workflow state.
Agent session IDs are execution metadata, not canonical knowledge. Artifact objects are
content-addressed and byte-verified through local/S3 adapters.

Atomic dispatch reservations enforce per-run/project/day limits; they are estimates and
not provider billing ceilings. Usage exposes token counts and provider-reported costs
separately. Full billing reconciliation and quotas per provider remain pending.

No speculative model IDs are embedded. Health is not_checked until a real probe. Manus v2
protocol operations and RSA webhook receipts are contract-tested but external task lifecycle
and approval-gated dispatch are not integrated. Hermes remains optional/unimplemented.

Sources checked before implementation:
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://code.claude.com/docs/en/agent-sdk/python
- https://github.com/openai/codex/tree/main/sdk/typescript
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://googleapis.github.io/python-genai/
- https://platform.kimi.ai/docs/get-your-api-key
- https://open.manus.im/docs/v2/task.create
- https://open.manus.im/docs/v2/task.listMessages
- https://open.manus.ai/docs/v2/webhooks-security
- https://playwright.dev/docs/docker

The dashboard follows the requested technical dark palette with application-owned state,
accessible forms, empty/error states and a read-only dependency visualization. Webpack is
used because Turbopack failed with a compiler socket error in this environment; the
supported Webpack production build and browser flow have been verified.
