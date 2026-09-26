"""The API process's side of the API Lab: one simulated API server at a time, for the active mission.

Files, under `<workspace>/.datapass/apilab/`:

- `<mission>/server.json`: the server's config (scenario, seed, the mission's fictitious key, paths);
- `<mission>/state.json`: the API's day and the current run number (the server reads it on each request);
- `<mission>/requests.jsonl`: the request log the server writes;
- `<mission>/runs.json`: each run of the learner's ingestion (day, status, error, output tail).

The server process gets an allowlisted environment (`server_env`): never the runtime's launch token.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from .model import Mission

# Only what Python needs to start on each platform. Nothing named *TOKEN*, *KEY*, *SECRET* can pass.
ENV_ALLOW = ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE', 'LANG',
             'LC_ALL', 'PYTHONPATH', 'VIRTUAL_ENV', 'PYTHONUTF8')
TRUTH = 'Simulated API (Datapass), your ingestion code runs for real'


def server_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in ENV_ALLOW}
    env['PYTHONUNBUFFERED'] = '1'
    token = os.environ.get('DATAPASS_RUNTIME_TOKEN')
    assert not token or all(token not in v for v in env.values()), 'the runtime token must not reach the API server'
    return env


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


class ApiLabService:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.mission_id: str | None = None
        self.port: int | None = None
        self.root: Path | None = None

    # ---- paths ----
    @staticmethod
    def home(root: Path) -> Path:
        return root / '.datapass' / 'apilab'

    def folder(self, root: Path, mission_id: str) -> Path:
        return self.home(root) / mission_id

    # ---- lifecycle ----
    def start(self, root: Path, mission: Mission) -> dict:
        """Start (over): a new key, day 1, run 0, an empty request log and run history, and a fresh server."""
        with self.lock:
            self.stop()
            folder = self.folder(root, mission.id)
            if folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(parents=True)
            key = f'sim_{mission.id.split("-")[1] if "-" in mission.id else "api"}_{secrets.token_hex(16)}'
            _write(folder / 'server.json', {
                'mission_id': mission.id, 'scenario': mission.api.scenario, 'seed': mission.api.seed, 'key': key,
                'state': str(folder / 'state.json'), 'log': str(folder / 'requests.jsonl')})
            _write(folder / 'state.json', {'day': 1, 'batch': mission.batches[0].id, 'run': 0})
            (folder / 'requests.jsonl').write_text('', encoding='utf-8')
            _write(folder / 'runs.json', [])
            self._spawn(root, mission.id)
            return self.status(root)

    def ensure(self, root: Path, mission: Mission) -> None:
        """The mission's server is up (after a runtime restart it comes back with the same key, day and log)."""
        with self.lock:
            if self.mission_id == mission.id and self.root == root and self.process and self.process.poll() is None:
                return
            if not (self.folder(root, mission.id) / 'server.json').is_file():
                raise ValueError(f'Start the mission {mission.id} first: its simulated API is not set up.')
            self.stop()
            self._spawn(root, mission.id)

    def _spawn(self, root: Path, mission_id: str) -> None:
        folder = self.folder(root, mission_id)
        with open(folder / 'server.stderr.log', 'a', encoding='utf-8') as errors:
            process = subprocess.Popen(
                [sys.executable, '-m', 'apilab.server', str(folder / 'server.json')], cwd=str(folder),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, encoding='utf-8',
                env=server_env())
        line = [None]
        reader = threading.Thread(target=lambda: line.__setitem__(0, process.stdout.readline()), daemon=True)
        reader.start()
        reader.join(15)
        text = line[0] or ''
        if not text.startswith('LISTENING '):
            process.kill()
            raise RuntimeError('The simulated API did not start; see .datapass/apilab/'
                               f'{mission_id}/server.stderr.log.')
        self.process, self.mission_id, self.port, self.root = process, mission_id, int(text.split()[1]), root

    def stop(self) -> None:
        with self.lock:
            process, self.process, self.mission_id, self.port = self.process, None, None, None
            if process is None:
                return
            try:
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=3)

    # ---- days and runs ----
    def advance(self, root: Path, mission: Mission, batch_id: str) -> dict:
        batch = next((b for b in mission.batches if b.id == batch_id), None)
        if batch is None:
            raise ValueError(f'Mission {mission.id} has no day {batch_id}.')
        with self.lock:
            folder = self.folder(root, mission.id)
            state = _read(folder / 'state.json', None)
            if state is None:
                raise ValueError(f'Start the mission {mission.id} first.')
            _write(folder / 'state.json', {**state, 'day': batch.day, 'batch': batch.id})
            return self.status(root)

    def begin_run(self, root: Path, mission: Mission) -> dict:
        with self.lock:
            self.ensure(root, mission)
            folder = self.folder(root, mission.id)
            state = _read(folder / 'state.json', {'day': 1, 'run': 0})
            state['run'] = int(state.get('run', 0)) + 1
            _write(folder / 'state.json', state)
            config = _read(folder / 'server.json', {})
            return {'run': state['run'], 'day': state['day'], 'base_url': f'http://127.0.0.1:{self.port}',
                    'key': config['key']}

    def record_run(self, root: Path, mission_id: str, run: dict, result: dict) -> dict:
        folder = self.folder(root, mission_id)
        requests = [e for e in self.log(root, mission_id) if e.get('run') == run['run']]
        entry = {'run': run['run'], 'day': run['day'], 'at': datetime.now().astimezone().isoformat(timespec='seconds'),
                 'status': result.get('status', 'error'), 'error': result.get('error'),
                 'stdout': (result.get('stdout') or '')[-4000:], 'tables': result.get('tables', []),
                 'requests': len(requests), 'records': sum(int(e.get('records') or 0) for e in requests),
                 'statuses': sorted({e['status'] for e in requests})}
        with self.lock:
            runs = _read(folder / 'runs.json', [])
            runs.append(entry)
            _write(folder / 'runs.json', runs[-50:])
        return entry

    # ---- reading ----
    def log(self, root: Path, mission_id: str) -> list[dict]:
        path = self.folder(root, mission_id) / 'requests.jsonl'
        out = []
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            pass
        return out

    def runs(self, root: Path, mission_id: str) -> list[dict]:
        return _read(self.folder(root, mission_id) / 'runs.json', [])

    def status(self, root: Path, mission_id: str | None = None) -> dict:
        """What the Workbench shows: the active (or given) mission's API, its key, day, runs and last requests."""
        with self.lock:
            mission_id = mission_id or self.mission_id
            alive = bool(self.process and self.process.poll() is None and self.mission_id == mission_id)
            if not mission_id:
                return {'truth': TRUTH, 'mission_id': None, 'running': False}
            folder = self.folder(root, mission_id)
            config = _read(folder / 'server.json', None)
            state = _read(folder / 'state.json', {})
            if config is None:
                return {'truth': TRUTH, 'mission_id': mission_id, 'running': False}
            log = self.log(root, mission_id)
            return {
                'truth': TRUTH, 'mission_id': mission_id, 'running': alive,
                'base_url': f'http://127.0.0.1:{self.port}' if alive else None,
                'key': config['key'], 'day': state.get('day', 1), 'batch': state.get('batch'),
                'run': state.get('run', 0), 'runs': self.runs(root, mission_id)[-10:],
                'requests': [{k: e.get(k) for k in ('n', 'at', 'run', 'day', 'method', 'path', 'query', 'status',
                                                    'records', 'retry_after', 'violation')} for e in log[-40:]],
                'request_count': len(log),
            }


service = ApiLabService()
