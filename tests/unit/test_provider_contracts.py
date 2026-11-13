import asyncio
import io
import json

import boto3
import httpx
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber
from openai import AsyncOpenAI

from nexus.agents.specialists import ResearchReport, Specialists, validate_citations
from nexus.orchestration.contracts import Blocked
from nexus.services.artifacts import S3Objects


def test_kimi_uses_official_compatible_protocol(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "fixture-key")
    monkeypatch.setenv("NEXUS_KIMI_MODEL", "fixture-model")
    report = {
        "summary": "Fixture synthesis",
        "claims": [{"claim": "French", "source_ids": ["source-1"], "confidence": "supported"}],
        "uncertainties": [],
    }

    def handler(request):
        assert str(request.url) == "https://api.moonshot.ai/v1/chat/completions"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "fixture-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(report)},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    def client(**kwargs):
        return AsyncOpenAI(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setattr("nexus.agents.specialists.AsyncOpenAI", client)
    result = asyncio.run(
        Specialists().research({"knowledge": [{"id": "source-1", "content": "French"}]})
    )
    assert result.input_tokens == 10
    assert result.data["summary"] == report["summary"]
    invalid = ResearchReport.model_validate(report)
    with pytest.raises(Blocked, match="unverified_research_citations"):
        validate_citations(invalid, [])


def test_s3_stores_and_verifies_actual_bytes(monkeypatch):
    import hashlib

    payload = b"verified content"
    digest = hashlib.sha256(payload).hexdigest()
    client = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="fixture", aws_secret_access_key="fixture"
    )
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    objects = S3Objects("test-bucket")
    with Stubber(client) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "test-bucket",
                "Key": digest,
                "Body": payload,
                "ContentType": "application/octet-stream",
                "Metadata": {"sha256": digest},
            },
        )
        stub.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(payload), len(payload))},
            {"Bucket": "test-bucket", "Key": digest},
        )
        assert objects.put(payload) == (digest, len(payload))
        stub.assert_no_pending_responses()


def test_manus_creation_is_not_blindly_retried(monkeypatch):
    from nexus.agents.manus import ManusClient

    monkeypatch.setenv("MANUS_API_KEY", "fixture")
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("task.create"):
            payload = json.loads(request.content)
            assert payload["share_visibility"] == "private"
            assert payload["clear_connectors"] is True
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "task_id": "task_fixture",
                    "task_url": "https://manus.im/app/task_fixture",
                    "share_visibility": "private",
                },
            )
        return httpx.Response(200, json={"ok": True, "messages": []})

    async def scenario():
        client = ManusClient(httpx.MockTransport(handler))
        task = await client.create("Research a public restaurant")
        assert task.task_id == "task_fixture"
        await client.messages(task.task_id)
        await client.stop(task.task_id)

    asyncio.run(scenario())
    assert len(calls) == 3
    assert calls[1].method == "GET"


def test_claude_sdk_contract_uses_restricted_tools_and_bounded_budget(monkeypatch):
    from claude_agent_sdk import ResultMessage

    from nexus.workers import container_entry

    captured = {}

    class Client:
        def __init__(self, *, options):
            captured["options"] = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def query(self, prompt):
            captured["prompt"] = prompt

        async def receive_response(self):
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="fixture-session",
                total_cost_usd=0.01,
                usage={"input_tokens": 10, "output_tokens": 20},
                result="Fixture implementation",
            )

    monkeypatch.setattr(container_entry, "ClaudeSDKClient", Client)
    result = asyncio.run(
        container_entry.claude(
            {
                "api_key": "fixture",
                "model": "fixture-model",
                "budget_usd": 1,
                "allowed_tools": ["Read", "Write", "Bash"],
                "instruction": "Build",
                "plan": {},
                "feedback": {},
                "skill": {},
            }
        )
    )
    options = captured["options"]
    assert options.tools == ["Read", "Write"]
    assert options.permission_mode == "default"
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.max_budget_usd == 1
    hook = options.hooks["PreToolUse"][0].hooks[0]
    denied = asyncio.run(hook({"tool_name": "Bash", "tool_input": {"command": "id"}}, None, {}))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert result["reported_cost_usd"] == 0.01


def test_openai_planner_uses_structured_outputs(monkeypatch):
    from nexus.agents.live import LiveProviders

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setenv("NEXUS_PLANNER_MODEL", "fixture-model")
    plan = {
        "summary": "Fixture plan",
        "tasks": [
            {
                "id": "site",
                "name": "Site",
                "goal": "Build",
                "agent": "claude",
                "dependencies": [],
                "acceptance_criteria": ["Loads"],
                "allowed_tools": ["Read", "Write"],
            }
        ],
    }

    def handler(request):
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        assert body["text"]["format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "fixture-model",
                "output": [
                    {
                        "id": "msg_fixture",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": json.dumps(plan), "annotations": []}
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            },
        )

    def client(**kwargs):
        return AsyncOpenAI(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setattr("nexus.agents.live.AsyncOpenAI", client)
    result = asyncio.run(LiveProviders(None, None).plan("Build a site"))
    assert result.data == plan
    assert result.input_tokens == 10


def test_gemini_design_contract_uses_official_types(monkeypatch):
    from google import genai
    from google.genai import types

    monkeypatch.setenv("GEMINI_API_KEY", "fixture-key")
    monkeypatch.setenv("NEXUS_GEMINI_MODEL", "fixture-model")
    specification = {
        "direction": "Editorial",
        "typography": ["serif", "sans"],
        "palette": ["#090d16"],
        "pages": ["Home"],
        "components": ["Navigation"],
        "responsive_guidelines": ["No overflow"],
        "accessibility_checks": ["Keyboard navigation"],
        "animation_guidelines": ["Reduced motion"],
        "limitations": ["No screenshot supplied"],
    }

    class AsyncClient:
        models = None

        def __init__(self):
            self.models = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def generate_content(self, *, model, contents, config):
            assert model == "fixture-model"
            assert isinstance(config, types.GenerateContentConfig)
            assert config.response_mime_type == "application/json"
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            parts=[types.Part.from_text(text=json.dumps(specification))]
                        )
                    )
                ],
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=10, candidates_token_count=20
                ),
            )

    class Client:
        def __init__(self, **kwargs):
            self.aio = AsyncClient()

    monkeypatch.setattr(genai, "Client", Client)
    result = asyncio.run(Specialists().design({"instruction": "Design a site"}))
    assert result.data == specification
    assert result.output_tokens == 20
