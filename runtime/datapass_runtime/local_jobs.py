"""Bounded manual local jobs, sharing workspace ownership with Documents.

There is no scheduler or distributed queue. Persisted records are evidence, not
alternate editable resources. A restart marks unfinished work interrupted.
Trusted code is lifecycle-isolated, not a security sandbox.
"""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import uuid
from .atomic import replace_file
from .documents import Documents, RevisionConflict

TERMINAL = {'success', 'failed', 'cancelled', 'timed_out', 'unavailable', 'interrupted'}
JOB_ID = re.compile(r'^[a-f0-9]{32}$')
LOG_LIMIT = 64_000
ARTIFACT_LIMIT = 2_000_000


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class JobCancelled(RuntimeError):
    pass


class JobDeadline(TimeoutError):
    pass


class CapabilityUnavailable(RuntimeError):
    pass


def stop_process(process: subprocess.Popen) -> None:
    """Stop the invocation process group where supported, never a shell command."""
    if process.poll() is not None:
        return
    try:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        if process.poll() is None:
            if os.name == 'posix':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait(timeout=3)


class JobContext:
    def __init__(self, owner: 'LocalJobs', record: dict, timeout: float):
        self.owner, self.record = owner, record
        self.cancelled = threading.Event()
        self.lock = threading.RLock()
        self.deadline = time.monotonic() + timeout
        self.started = time.monotonic()
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None

    @property
    def directory(self) -> Path:
        return self.owner.folder(self.record['workspace_id']) / self.record['id']

    def check(self) -> None:
        if self.cancelled.is_set():
            raise JobCancelled('Cancelled by the local user. Completed writes are not rolled back.')
        if time.monotonic() >= self.deadline:
            raise JobDeadline('Local job exceeded its wall-time limit. Completed writes are not rolled back.')

    def update(self, **values) -> None:
        with self.lock:
            self.record.update(deepcopy(values))
            self.owner.write(self.record)

    def log(self, text: str) -> None:
        with self.lock:
            remaining = LOG_LIMIT - len(self.record['log'])
            if remaining > 0:
                self.record['log'] += str(text)[:remaining]
            if len(text) > remaining:
                self.record['log_truncated'] = True
            self.owner.write(self.record)

    def wait(self, seconds: float) -> None:
        self.check()
        if self.cancelled.wait(min(seconds, max(0, self.deadline - time.monotonic()))):
            self.check()
        self.check()

    def artifact(self, name: str, value) -> dict:
        if not re.fullmatch(r'[A-Za-z0-9_-]+\.json', name):
            raise ValueError('Artifact name is server-owned.')
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        if len(data) > ARTIFACT_LIMIT:
            raise ValueError('Artifact exceeds the 2 MB evidence limit.')
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_bytes(data)
        replace_file(temp, path)
        return {'file': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def run_process(self, argv: list[str], *, cwd: Path, env: dict[str, str]) -> int:
        """Only internal adapters supply argv. Never expose argv or shell input in the API."""
        self.check()
        # A merged, bounded log still labels the originating stream.
        flags = {'start_new_session': True} if os.name == 'posix' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, **flags)
        with self.lock:
            self.process = process
        self.update(truth='real_local')
        def drain(stream, label):
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    self.log(f'[{label}] ' + chunk.decode('utf-8', errors='replace'))
            finally:
                stream.close()
        readers = [threading.Thread(target=drain, args=(process.stdout, 'stdout'), daemon=True),
                   threading.Thread(target=drain, args=(process.stderr, 'stderr'), daemon=True)]
        for reader in readers:
            reader.start()
        try:
            while process.poll() is None:
                self.check()
                self.cancelled.wait(.05)
            self.check()
            return process.returncode
        finally:
            stop_process(process)
            for reader in readers:
                reader.join(timeout=3)
            with self.lock:
                self.process = None


class LocalJobs:
    def __init__(self, documents: Documents, manager, *, timeout=300.0, max_active=6):
        self.documents, self.manager = documents, manager
        self.timeout, self.max_active = timeout, max_active
        self.lock = threading.RLock()
        self.active: dict[str, JobContext] = {}
        self.closed = False
        # No replay on server restart: execution may have already committed writes.
        for file in documents.root.glob('*/jobs/*.json'):
            record = json.loads(file.read_text(encoding='utf-8'))
            if record.get('status') not in TERMINAL:
                record.update(status='interrupted', finished_at=now(), error='Server restarted. This job was not replayed; inspect catalog state before rerunning.')
                self.write(record)

    def folder(self, workspace_id: str) -> Path:
        return self.documents.folder(workspace_id) / 'jobs'

    def write(self, record: dict) -> None:
        if not JOB_ID.fullmatch(record['id']):
            raise ValueError('Invalid run identity.')
        folder = self.folder(record['workspace_id'])
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (record['id'] + '.json')
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(record, allow_nan=False), encoding='utf-8')
        replace_file(temp, path)

    def get(self, workspace_id: str, job_id: str) -> dict:
        self.documents.get(workspace_id)
        if not JOB_ID.fullmatch(job_id):
            raise ValueError('Invalid job ID.')
        with self.lock:
            active = self.active.get(workspace_id)
            if active and active.record['id'] == job_id:
                with active.lock:
                    return deepcopy(active.record)
        return json.loads((self.folder(workspace_id) / (job_id + '.json')).read_text(encoding='utf-8'))

    def list(self, workspace_id: str, resource_id: str | None = None) -> list[dict]:
        self.documents.get(workspace_id)
        files = sorted(self.folder(workspace_id).glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        records = []
        for path in files:
            record = self.get(workspace_id, path.stem)
            if resource_id is None or record['resource_id'] == resource_id:
                records.append({k:v for k,v in record.items() if k not in {'log', 'result'}})
            if len(records) >= 100:
                break
        return records

    def read_artifact(self, workspace_id: str, job_id: str, name: str):
        record = self.get(workspace_id, job_id)
        descriptor = record.get('artifacts', {}).get(name)
        if not descriptor or not re.fullmatch(r'[A-Za-z0-9_-]+\.json', descriptor['file']):
            raise KeyError('No matching artifact.')
        path = self.folder(workspace_id) / job_id / descriptor['file']
        if path.is_symlink() or path.stat().st_size > ARTIFACT_LIMIT:
            raise ValueError('Unsafe artifact file.')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
            raise ValueError('Artifact checksum mismatch. Evidence was not loaded.')
        return json.loads(raw)

    def submit(self, workspace_id: str, resource_id: str, workspace_revision: int,
               resource_revision: int, kind: str, action: str, operation) -> dict:
        with self.lock, self.documents.lock:
            if self.closed:
                raise CapabilityUnavailable('Local runner is shutting down.')
            if workspace_id in self.active:
                raise RevisionConflict('This workspace already has a local job. Cancel it or let it finish before starting another.')
            if len(self.active) >= self.max_active:
                raise CapabilityUnavailable('All bounded local job slots are busy.')
            workspace = self.documents.get(workspace_id)
            if workspace['revision'] != workspace_revision:
                raise RevisionConflict('Save/reload this workspace before running the resource.')
            resource = next((r for r in workspace.get('workbench', {}).get('resources', []) if r['id'] == resource_id), None)
            if resource is None or resource['revision'] != resource_revision:
                raise RevisionConflict('The saved canonical resource does not match this run request.')
            if resource['kind'] != {'dbt':'dbt-project', 'pipeline':'pipeline', 'query':'chart-board'}[kind]:
                raise ValueError('This action does not match the resource kind.')
            if len(list(self.folder(workspace_id).glob('*.json'))) >= 1000:
                raise CapabilityUnavailable('Workspace has reached 1000 local job records. Export/archive records before starting more.')
            record = dict(schema_version=1, id=uuid.uuid4().hex, workspace_id=workspace_id,
                          resource_id=resource_id, resource_revision=resource_revision,
                          workspace_revision=workspace_revision, source_hash=digest(resource),
                          kind=kind, action=action, status='queued', truth='unavailable',
                          created_at=now(), started_at=None, finished_at=None, elapsed_ms=0,
                          runtime={}, log='', log_truncated=False, artifacts={}, steps=[])
            job = JobContext(self, record, self.timeout)
            self.write(record)
            self.active[workspace_id] = job
            snapshot = deepcopy(workspace)
            def run():
                completion = {'status':'failed','error':'Invocation did not complete.'}
                try:
                    job.update(status='running', started_at=now())
                    job.check()
                    with self.manager.workspace_lease(workspace_id):
                        result = operation(job, deepcopy(resource), snapshot)
                    job.check()
                    completion = {'status':'success','result':result}
                except JobCancelled as error:
                    completion = {'status':'cancelled','error':str(error)}
                except JobDeadline as error:
                    completion = {'status':'timed_out','error':str(error)}
                except CapabilityUnavailable as error:
                    completion = {'status':'unavailable','truth':'unavailable','error':str(error)}
                except Exception as error:
                    completion = {'status':'failed','error':f'{type(error).__name__}: {error}'[:4000]}
                finally:
                    # Publish terminal state and free the workspace slot together.
                    # Even a disk error cannot strand an in-memory busy marker.
                    with self.lock:
                        try:
                            job.update(**completion,finished_at=now(),elapsed_ms=round((time.monotonic()-job.started)*1000,3))
                        finally:
                            self.active.pop(workspace_id, None)
            job.thread = threading.Thread(target=run, name='datapass-local-' + record['id'], daemon=True)
            initial = deepcopy(record)
            job.thread.start()
            return initial

    def cancel(self, workspace_id: str, job_id: str) -> dict:
        record = self.get(workspace_id, job_id)
        with self.lock:
            job = self.active.get(workspace_id)
            if job and job.record['id'] == job_id:
                job.cancelled.set()
                # Interrupt a running kernel without waiting for the job's lease.
                self.manager.interrupt(workspace_id)
                with job.lock:
                    process = job.process
                if process:
                    stop_process(process)
        return self.get(workspace_id, job_id)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            jobs = list(self.active.values())
        for job in jobs:
            self.cancel(job.record['workspace_id'], job.record['id'])
        for job in jobs:
            if job.thread:
                job.thread.join(timeout=5)
