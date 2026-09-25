"""Configure the runtime's launch token for TestClient-based smokes, as the extension does for a real launch.

Call ``client_kwargs()`` before the first request to ``datapass_runtime.main.app``: Starlette builds the middleware
stack (and reads the token) once per process. ``TestClient(app, **client_kwargs())`` then sends the token and a
loopback Host header.
"""

import os
import secrets

PORT = "8765"


def client_kwargs() -> dict:
    token = os.environ.setdefault("DATAPASS_RUNTIME_TOKEN", secrets.token_hex(32))
    port = os.environ.setdefault("DATAPASS_RUNTIME_PORT", PORT)
    return {"base_url": f"http://127.0.0.1:{port}", "headers": {"X-Datapass-Token": token}}
