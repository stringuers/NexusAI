"""Request correlation and metadata-only structured access logs."""

import json
import logging
import time
from uuid import UUID, uuid4

from starlette.responses import JSONResponse

logger = logging.getLogger("nexus.audit")


class RequestContext:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            request_id = str(UUID(headers.get(b"x-request-id", b"").decode()))
        except (ValueError, UnicodeError):
            request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        length = headers.get(b"content-length", b"0")
        if not length.isdigit() or int(length) > 2 * 1024 * 1024:
            return await JSONResponse(
                {"detail": "Request body too large", "request_id": request_id}, status_code=413
            )(scope, receive, send)
        started, status = time.monotonic(), 500

        async def audited_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, audited_send)
        finally:
            route = scope.get("route")
            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "method": scope["method"],
                        "route": getattr(route, "path", "unmatched"),
                        "status": status,
                        "workspace_id": scope["state"].get("workspace_id"),
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    }
                )
            )
