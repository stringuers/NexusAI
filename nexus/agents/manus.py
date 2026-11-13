"""Documented Manus v2 protocol. No automatic retries for task creation."""

import os

import httpx
from pydantic import BaseModel, ConfigDict

from nexus.orchestration.contracts import Blocked, NotConfigured


class ExternalTask(BaseModel):
    model_config = ConfigDict(extra="ignore")
    task_id: str
    task_url: str
    share_visibility: str


class ManusClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def request(self, method: str, operation: str, *, body=None, params=None):
        key = os.getenv("MANUS_API_KEY")
        if not key:
            raise NotConfigured("manus_not_configured")
        async with httpx.AsyncClient(
            base_url="https://api.manus.ai/v2/",
            timeout=30,
            transport=self.transport,
            headers={"x-manus-api-key": key},
        ) as client:
            response = await client.request(method, operation, json=body, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get("ok") is not True:
            raise Blocked("manus_request_rejected")
        return data

    async def create(self, prompt: str) -> ExternalTask:
        if not prompt.strip() or len(prompt) > 12000:
            raise ValueError("Invalid Manus prompt")
        # The caller must persist intent and approval before this non-idempotent POST.
        data = await self.request(
            "POST",
            "task.create",
            body={
                "message": {"content": [{"type": "text", "text": prompt, "visibility": "visible"}]},
                "share_visibility": "private",
                "clear_connectors": True,
            },
        )
        result = ExternalTask.model_validate(data)
        if result.share_visibility != "private":
            raise Blocked("manus_visibility_policy_failed")
        return result

    async def messages(self, task_id: str, cursor: str | None = None):
        params = {"task_id": task_id, "order": "asc", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        return await self.request("GET", "task.listMessages", params=params)

    async def detail(self, task_id: str):
        return await self.request("GET", "task.detail", params={"task_id": task_id})

    async def stop(self, task_id: str):
        return await self.request("POST", "task.stop", body={"task_id": task_id})
