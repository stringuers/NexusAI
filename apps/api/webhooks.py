import hashlib
import json
import os
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nexus.db.models import InboundEvent
from nexus.security.webhooks import verify_manus, verify_n8n


class Intake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    task: dict


async def limited_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 100000:
            raise HTTPException(413, "Webhook payload too large")
    return bytes(body)


def webhooks(sessions, submit, task_schema):
    router = APIRouter(prefix="/api/v1/webhooks")

    async def record(source: str, event_id: str, body_hash: str, run_id=None):
        async with sessions() as session:
            item = await session.scalar(
                select(InboundEvent).where(
                    InboundEvent.source == source, InboundEvent.event_id == event_id
                )
            )
            if item:
                if item.body_hash != body_hash:
                    raise HTTPException(409, "Webhook event ID conflict")
                return False
            session.add(
                InboundEvent(source=source, event_id=event_id, body_hash=body_hash, run_id=run_id)
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                item = await session.scalar(
                    select(InboundEvent).where(
                        InboundEvent.source == source, InboundEvent.event_id == event_id
                    )
                )
                if not item or item.body_hash != body_hash:
                    raise HTTPException(409, "Webhook event ID conflict") from None
                return False
            return True

    @router.post("/n8n", status_code=202)
    async def n8n(request: Request):
        secret = os.getenv("NEXUS_N8N_SECRET", "")
        workspace = os.getenv("NEXUS_AUTOMATION_WORKSPACE_ID", "")
        if len(secret) < 32 or not workspace:
            raise HTTPException(503, "n8n integration not configured")
        try:
            scope = str(UUID(workspace))
        except ValueError:
            raise HTTPException(503, "Automation workspace invalid") from None
        body = await limited_body(request)
        if not verify_n8n(
            secret,
            body,
            request.headers.get("X-Nexus-Timestamp", ""),
            request.headers.get("X-Nexus-Signature", ""),
        ):
            raise HTTPException(401, "Invalid webhook signature")
        try:
            intake = Intake.model_validate_json(body)
            task = task_schema.model_validate(intake.task)
        except ValidationError:
            raise HTTPException(422, "Invalid intake payload") from None
        # Canonical idempotency constraint handles a crash between task commit and receipt commit.
        run = await submit(task, scope, f"n8n:{intake.event_id}")
        inserted = await record("n8n", intake.event_id, hashlib.sha256(body).hexdigest(), run.id)
        return {"run_id": run.id, "task_id": run.task_id, "duplicate": not inserted}

    @router.post("/manus", status_code=200)
    async def manus(request: Request):
        public_key = os.getenv("NEXUS_MANUS_PUBLIC_KEY", "")
        callback_url = os.getenv("NEXUS_MANUS_CALLBACK_URL", "")
        if not public_key or not callback_url:
            raise HTTPException(503, "Manus webhook verification not configured")
        body = await limited_body(request)
        if not verify_manus(
            public_key,
            callback_url,
            body,
            request.headers.get("X-Webhook-Timestamp", ""),
            request.headers.get("X-Webhook-Signature", ""),
        ):
            raise HTTPException(401, "Invalid webhook signature")
        try:
            data = json.loads(body)
            event_id = data["event_id"]
            if not isinstance(event_id, str) or not 1 <= len(event_id) <= 100:
                raise ValueError("Invalid event ID")
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "Invalid Manus event envelope") from None
        inserted = await record("manus", event_id, hashlib.sha256(body).hexdigest())
        # Receipt only: no workflow is resumed from an uncorrelated external task.
        return {"accepted": True, "duplicate": not inserted, "workflow_resumed": False}

    return router
