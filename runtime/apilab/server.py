"""The API Lab's simulated REST API: a small HTTP server on 127.0.0.1, one per active mission, on its own port.

Started by the runtime (service.py) as `python -m apilab.server <config.json>` with an allowlisted environment: it
never receives the runtime's launch token, and the runtime's own auth (auth.py) is untouched. Its own rules:

1. the Host header must be exactly `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding), else 400;
2. `Authorization: Bearer <mission key>` (a fictitious key made for the mission and shown to the learner), else 401;
3. GET only; the scenario (scenario.py) answers the rest.

Every request is appended to the request log (JSON lines) that the mission checks read. The log never records a
header value. The server exits when its stdin closes (the runtime stopped or died).
"""
from __future__ import annotations

import hmac
import json
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .scenario import ApiError, Memory, respond


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, config: dict):
        super().__init__(('127.0.0.1', 0), Handler)
        self.config = config
        self.key = config['key'].encode('utf-8')
        self.hosts = {f'127.0.0.1:{self.server_port}', f'localhost:{self.server_port}'}
        self.state_path = Path(config['state'])
        self.log_path = Path(config['log'])
        self.memory = Memory()
        self.lock = threading.Lock()
        self.count = sum(1 for _ in self.log_path.open(encoding='utf-8')) if self.log_path.exists() else 0

    def state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'day': 1, 'run': 0}

    def log(self, entry: dict) -> None:
        self.count += 1
        with self.log_path.open('a', encoding='utf-8') as out:
            out.write(json.dumps({'n': self.count, **entry}) + '\n')


class Handler(BaseHTTPRequestHandler):
    server: ApiServer
    protocol_version = 'HTTP/1.1'
    server_version = 'DatapassSimulatedApi/1'
    sys_version = ''

    def log_message(self, format, *args):  # noqa: A002 - the server's request log is the JSON lines file
        pass

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    do_PUT = do_DELETE = do_PATCH = do_POST

    def reply(self, status: int, body: object, headers: dict[str, str] | None = None) -> None:
        data = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self) -> None:
        # Drain a body so the connection stays usable; the API has no write endpoint.
        length = int(self.headers.get('Content-Length') or 0)
        if 0 < length <= 1_000_000:
            self.rfile.read(length)
        hosts = self.headers.get_all('Host') or []
        if len(hosts) != 1 or hosts[0].lower() not in self.server.hosts:
            # A rebound web page sends its own host name: refuse before anything else.
            with self.server.lock:
                self.server.log(self.entry(400, auth='not_checked', note='host_rejected'))
            self.reply(400, {'error': 'Invalid Host header.'})
            return
        given = self.headers.get_all('Authorization') or []
        token = given[0][7:].strip().encode('utf-8') if len(given) == 1 and given[0][:7].lower() == 'bearer ' else b''
        if not token or not hmac.compare_digest(token, self.server.key):
            with self.server.lock:
                self.server.log(self.entry(401, auth='missing' if not given else 'invalid'))
            self.reply(401, {'error': 'Missing or invalid API key. Send Authorization: Bearer <your key>.'},
                       {'WWW-Authenticate': 'Bearer realm="datapass-simulated-api"'})
            return
        if self.command != 'GET':
            with self.server.lock:
                self.server.log(self.entry(405))
            self.reply(405, {'error': 'This API is read-only: use GET.'}, {'Allow': 'GET'})
            return
        url = urlsplit(self.path)
        query = dict(parse_qsl(url.query, keep_blank_values=True))
        with self.server.lock:
            state = self.server.state()
            day, run = int(state.get('day', 1)), int(state.get('run', 0))
            memory = self.server.memory.for_run(run)
            try:
                answer = respond(self.server.config['scenario'], int(self.server.config['seed']), day, url.path, query,
                                 memory, time.monotonic())
                status, body, headers = 200, answer.body, answer.headers
                entry = self.entry(200, url.path, query, day, run, records=answer.records, final=answer.final)
            except ApiError as error:
                status, body, headers = error.status, {'error': error.message}, error.headers
                entry = self.entry(error.status, url.path, query, day, run, **error.meta)
                if 'Retry-After' in error.headers:
                    entry['retry_after'] = int(error.headers['Retry-After'])
            self.server.log(entry)
        self.reply(status, body, headers)

    def entry(self, status: int, path: str | None = None, query: dict | None = None, day: int | None = None,
              run: int | None = None, **extra) -> dict:
        if day is None or run is None:
            state = self.server.state()
            day, run = int(state.get('day', 1)), int(state.get('run', 0))
        now = datetime.now(timezone.utc)
        return {'at': now.isoformat(timespec='milliseconds'), 't': round(time.monotonic(), 4), 'run': run, 'day': day,
                'method': self.command, 'path': path if path is not None else urlsplit(self.path).path,
                'query': query if query is not None else dict(parse_qsl(urlsplit(self.path).query)),
                'status': status, **extra}


def main() -> None:
    config = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    server = ApiServer(config)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sys.stdout.write(f'LISTENING {server.server_port}\n')
    sys.stdout.flush()
    # The runtime holds our stdin: EOF means it stopped us or died.
    try:
        sys.stdin.read()
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
