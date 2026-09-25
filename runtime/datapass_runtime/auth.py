"""Loopback request authentication for the local runtime.

The runtime listens on 127.0.0.1, but a loopback port is reachable by any local
process and, through DNS rebinding, by a web page. The extension therefore
generates a random token for each launch and passes it, with the port, in the
child environment (``DATAPASS_RUNTIME_TOKEN``, ``DATAPASS_RUNTIME_PORT``). Every
HTTP request must:

1. carry a Host header that is exactly ``127.0.0.1:<port>`` or ``localhost:<port>``
   (a rebound page sends its own host name), else 400;
2. carry the token in ``X-Datapass-Token``, else 401.

``/api/health`` is no exception: the extension always has the token, so nothing
needs an open endpoint. The check fails closed: a runtime started without a
token or a port refuses every request (503). The token is never logged, and the
kernel worker never sees it (its environment drops ``*TOKEN*`` variables).
"""

from __future__ import annotations

import hmac
import json
import os

TOKEN_ENV = "DATAPASS_RUNTIME_TOKEN"
PORT_ENV = "DATAPASS_RUNTIME_PORT"
TOKEN_HEADER = b"x-datapass-token"


class RuntimeAuthMiddleware:
    """Pure ASGI middleware, so it also guards routes that stream or raise before FastAPI's handlers."""

    def __init__(self, app) -> None:
        self.app = app
        # Read once: Starlette builds the middleware stack at the first request, after the
        # extension (or a smoke) has configured the environment.
        self.token = os.environ.get(TOKEN_ENV, "").encode("utf-8")
        port = os.environ.get(PORT_ENV, "").strip()
        self.hosts = {f"127.0.0.1:{port}".encode(), f"localhost:{port}".encode()} if port.isdigit() else set()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        status, detail = self.refusal(scope)
        if status is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    def refusal(self, scope) -> tuple[int | None, str]:
        if not self.token or not self.hosts:
            return 503, "The Datapass runtime was started without its launch token; start it from VS Code."
        headers: dict[bytes, bytes] = {}
        for name, value in scope.get("headers", []):
            # A repeated Host or token header is ambiguous: refuse rather than pick one.
            if name in headers and name in (b"host", TOKEN_HEADER):
                return 400, "Duplicate Host or token header."
            headers[name] = value
        if headers.get(b"host", b"").lower() not in self.hosts:
            return 400, "Invalid Host header."
        if not hmac.compare_digest(headers.get(TOKEN_HEADER, b""), self.token):
            return 401, "Missing or invalid Datapass runtime token."
        return None, ""
