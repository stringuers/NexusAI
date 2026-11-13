import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from apps.api.main import create_app

TOKEN = "webhook-test-token" * 3
WORKSPACE = "00000000-0000-4000-8000-000000000001"


def test_n8n_intake_authentication_and_deduplication(orchestration_db, monkeypatch):
    secret = "n8n-fixture-secret" * 3
    monkeypatch.setenv("NEXUS_N8N_SECRET", secret)
    monkeypatch.setenv("NEXUS_AUTOMATION_WORKSPACE_ID", WORKSPACE)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(create_app(orchestration_db, {TOKEN: WORKSPACE})) as client:
        project = client.post(
            "/api/v1/projects", headers=headers, json={"name": "Automation"}
        ).json()
        body = json.dumps(
            {"event_id": "event-1", "task": {"project_id": project["id"], "instruction": "Build"}}
        ).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        webhook_headers = {"X-Nexus-Timestamp": timestamp, "X-Nexus-Signature": signature}
        assert client.post("/api/v1/webhooks/n8n", content=body).status_code == 401
        first = client.post("/api/v1/webhooks/n8n", headers=webhook_headers, content=body)
        assert first.status_code == 202
        assert first.json()["duplicate"] is False
        second = client.post("/api/v1/webhooks/n8n", headers=webhook_headers, content=body)
        assert second.json()["duplicate"] is True
        assert first.json()["run_id"] == second.json()["run_id"]
        assert len(client.get("/api/v1/runs", headers=headers).json()) == 1
        stale = {**webhook_headers, "X-Nexus-Timestamp": "1"}
        assert client.post("/api/v1/webhooks/n8n", headers=stale, content=body).status_code == 401
        assert client.post("/api/v1/webhooks/manus", content=b"{}").status_code == 503
