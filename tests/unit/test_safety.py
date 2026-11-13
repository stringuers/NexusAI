from pathlib import Path

import pytest

from nexus.orchestration.contracts import Blocked, Review
from nexus.security.worker_tools import permitted
from nexus.services.artifacts import LocalObjects, source_files
from nexus.workers.qa import check_site


def test_tools_and_paths(tmp_path):
    assert permitted(
        "Write", {"file_path": str(tmp_path / "index.html"), "content": "test"}, tmp_path
    )
    assert not permitted("Bash", {"command": "id"}, tmp_path)
    assert not permitted("Read", {"file_path": "/etc/passwd"}, tmp_path)
    assert not permitted("Write", {"file_path": "../outside"}, tmp_path)
    assert not permitted("Write", {"file_path": ".git/config"}, tmp_path)
    assert not permitted("Glob", {"pattern": "../*"}, tmp_path)
    (tmp_path / "escape").symlink_to(Path("/tmp"))
    assert not permitted("Read", {"file_path": "escape/secret"}, tmp_path)


def test_artifact_symlinks_and_tampering(tmp_path):
    tree = tmp_path / "workspace"
    tree.mkdir()
    (tree / "escape").symlink_to("/etc/passwd")
    with pytest.raises(Blocked, match="symlink"):
        source_files(tree)
    objects = LocalObjects(str(tmp_path / "objects"))
    digest, _ = objects.put(b"verified")
    assert objects.read(digest, digest) == b"verified"
    (objects.root / digest).write_bytes(b"tampered")
    with pytest.raises(Blocked, match="hash_mismatch"):
        objects.read(digest, digest)
    with pytest.raises(Blocked, match="invalid_object_key"):
        objects.read("../secret", digest)


def test_qa_rejects_missing_landmarks_and_local_escape(tmp_path):
    (tmp_path / "index.html").write_text('<html><a href="../outside">Escape</a></html>')
    result = check_site(tmp_path)
    assert not result["passed"]
    assert any(not check["passed"] for check in result["checks"])


def test_review_cannot_approve_serious_findings():
    result = Review.model_validate(
        {
            "recommendation": "approve",
            "findings": [
                {
                    "severity": "high",
                    "file": "index.html",
                    "line": 1,
                    "description": "Broken form",
                    "reproduction": "Submit form",
                    "suggested_change": "Fix handler",
                }
            ],
            "uncertainties": [],
        }
    )
    assert result.recommendation == "changes_requested"


def test_manus_rsa_signature_binds_url_body_and_time():
    import base64
    import hashlib
    import time

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    from nexus.security.webhooks import verify_manus

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    body, url, timestamp = (
        b'{"event_id":"fixture"}',
        "https://nexus.example/api/v1/webhooks/manus",
        str(int(time.time())),
    )
    content = f"{timestamp}.{url}.{hashlib.sha256(body).hexdigest()}".encode()
    signature = base64.b64encode(key.sign(content, padding.PKCS1v15(), hashes.SHA256())).decode()
    assert verify_manus(public, url, body, timestamp, signature)
    assert not verify_manus(public, url, b"tampered", timestamp, signature)
    assert not verify_manus(public, url + "?other", body, timestamp, signature)
    assert not verify_manus(public, url, body, "1", signature)


def test_skill_catalog_is_versioned_and_agent_scoped():
    from nexus.services.skills import CATALOG, load_skill

    for name, agent in [
        ("project-planner", "openai"),
        ("website-builder", "claude"),
        ("research", "kimi"),
        ("visual-qa", "gemini"),
        ("security-review", "codex"),
    ]:
        skill = load_skill(name, agent)
        assert skill.version == "1.0.0"
        assert skill.execution == "instructions-only"
    assert len(CATALOG) == 5
    with pytest.raises(PermissionError):
        load_skill("../escape", "claude")
    with pytest.raises(PermissionError):
        load_skill("security-review", "claude")


def test_provider_output_redacts_known_secrets(monkeypatch):
    from nexus.security.redaction import redact

    monkeypatch.setenv("OPENAI_API_KEY", "sensitive-fixture-key")
    result = redact({"summary": "Found sensitive-fixture-key", "logs": ["Bearer another-token"]})
    assert result == {"summary": "Found [REDACTED]", "logs": ["Bearer [REDACTED]"]}


def test_tool_registry_enforces_server_permissions():
    from nexus.tools.registry import authorize

    assert authorize("Read", {"project:read"}).side_effect == "read"
    with pytest.raises(PermissionError):
        authorize("Write", {"project:read"})
    with pytest.raises(PermissionError):
        authorize("deploy_production", {"project:write"})


def test_artifact_archive_rejects_windows_path_escapes(tmp_path):
    (tmp_path / "nested\\..\\escape.txt").write_text("unsafe archive name")
    with pytest.raises(Blocked, match="unsafe_artifact_path"):
        source_files(tmp_path)
