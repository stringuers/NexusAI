# Optional n8n automation

Import task-intake.json into your self-hosted n8n. It is deliberately inactive.
Configure an HTTP Header Auth credential on the inbound webhook (a separate secret),
and another on Submit persisted task (`Authorization: Bearer <workspace token>`).
Set the NEXUS_API_URL n8n variable to the reachable FastAPI origin. Activate only after
testing against your deployment. Send event_id, project_id, instruction and optional
budget_microusd. The workflow returns the persisted run object. Authentication and
canonical validation happen again in FastAPI; repeated event IDs use task idempotency.
This export has not been executed in a live n8n instance.

Alternatively, call POST /api/v1/webhooks/n8n with a signed envelope:
`{"event_id":"unique-id","task":{"project_id":"uuid","instruction":"..."}}`.
Configure NEXUS_N8N_SECRET (>=32 characters) and NEXUS_AUTOMATION_WORKSPACE_ID on FastAPI.
Send X-Nexus-Timestamp (Unix seconds) and X-Nexus-Signature (hex HMAC-SHA256 of
`timestamp + '.' + exact_raw_body`). Five-minute freshness is enforced. Receipt IDs
and body hashes persist. A crash between task submission and receipt insertion is
safe because the task itself has a unique idempotency key.

Approval and completion events are available through the authenticated persisted SSE
API. Notification channels, outbound outbox delivery, GitHub signature intake and the
other notification exports remain unimplemented; no external messages are sent.
