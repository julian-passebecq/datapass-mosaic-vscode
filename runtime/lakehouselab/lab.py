"""Lakehouse Lab operations for the API: the mission list, building a mission folder, running the learner's file,
the hidden checker and the storage view. Every DuckDB statement runs in the sandbox child process (sandbox.py)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .checks import evaluate, probe_queries
from .extensions import ducklake_status
from .model import Mission, find_mission, load_missions

TRUTH_SQL = 'DuckDB (real, local): your SQL ran in a DuckDB process bounded to the mission folder.'
TRUTH_POLARS = 'Polars (real, local): your file ran as trusted local Python in the mission folder (not a sandbox).'
TRUTH_CHECK = ('Checked on disk and in the catalog: file counts and sizes measured, Parquet schemas and rows read by '
               'DuckDB, DuckLake snapshots and time travel queried, pruning read from DuckDB\'s EXPLAIN ANALYZE.')
SANDBOX_TIMEOUT = 120
POLARS_TIMEOUT = 180


class LabError(Exception):
    """A request the lab refuses or cannot do (shown to the learner as is)."""


def _child_env() -> dict[str, str]:
    """The runtime's environment without its per-launch token (a child never needs it)."""
    return {key: value for key, value in os.environ.items()
            if key != 'DATAPASS_RUNTIME_TOKEN' and 'TOKEN' not in key.upper() and 'SECRET' not in key.upper()}


def sandbox(folder: Path, request: dict, timeout: int = SANDBOX_TIMEOUT) -> dict:
    runtime_root = str(Path(__file__).resolve().parents[1])
    env = _child_env()
    env['PYTHONPATH'] = runtime_root + os.pathsep + env.get('PYTHONPATH', '')
    env['PYTHONIOENCODING'] = 'utf-8'
    try:
        done = subprocess.run([sys.executable, '-m', 'lakehouselab.sandbox'], input=json.dumps(request), cwd=folder,
                              env=env, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    except subprocess.TimeoutExpired:
        raise LabError(f'DuckDB did not finish within {timeout} s; the run was stopped.') from None
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError:
        raise LabError(f'The DuckDB process failed: {(done.stderr or done.stdout)[-800:]}') from None


def missions() -> dict:
    status = ducklake_status()
    return {'missions': [mission.view() for mission, _ in load_missions()], 'ducklake': status,
            'trusted_python': os.getenv('DATAPASS_TRUSTED_PYTHON') == '1'}


def mission(mission_id: str) -> tuple[Mission, Path]:
    try:
        return find_mission(mission_id)
    except (KeyError, ValueError) as error:
        raise LabError(str(error).strip("'")) from None


def mission_folder(workspace: Path, found: Mission) -> Path:
    folder = workspace / found.folder
    if not folder.is_dir():
        raise LabError(f'{found.folder} does not exist yet: start the mission first.')
    return folder


def build(workspace: Path, mission_id: str) -> dict:
    """(Re)build `lakehouse/<id>/` from the pack. An existing folder is moved to .datapass/lakehouse/attic/, never
    deleted. The folder is built in place (DuckLake records its data path), from the pack's files and fixture SQL."""
    found, pack_dir = mission(mission_id)
    if found.delta and not ducklake_status().get('delta'):
        raise LabError('This mission needs the DuckDB delta extension. Run "Datapass: Setup runtime" once with a '
                       'network connection (it installs it), then start the mission again.')
    if found.ducklake and not ducklake_status()['installed']:
        raise LabError('This mission needs the DuckDB ducklake extension. Run "Datapass: Setup runtime" once with a '
                       'network connection (it installs it), then start the mission again.')
    target = workspace / found.folder
    previous = None
    if target.exists():
        attic = workspace / '.datapass' / 'lakehouse' / 'attic'
        attic.mkdir(parents=True, exist_ok=True)
        stamp = f'{found.id}-{datetime.now().strftime("%Y%m%d-%H%M%S")}'
        previous = attic / stamp
        n = 1
        while previous.exists():  # two starts in the same second
            n += 1
            previous = attic / f'{stamp}-{n}'
        _rename(target, previous)
    target.mkdir(parents=True)
    overlay = pack_dir / found.id / 'project'
    files = 0
    if overlay.is_dir():
        for path in sorted(overlay.rglob('*')):
            destination = target / path.relative_to(overlay)
            if path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif path.is_file() and not path.is_symlink():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
                files += 1
    (target / 'lake').mkdir(exist_ok=True)
    (target / 'data').mkdir(exist_ok=True)
    statements = [(pack_dir / relative).read_text(encoding='utf-8') for relative in found.fixture.sql]
    if statements or found.ducklake:
        answer = sandbox(target, {'op': 'fixture', 'statements': statements, 'ducklake': found.ducklake})
        if answer.get('error'):
            raise LabError(f'The mission fixture could not be built: {answer["error"]}')
        if found.ducklake and answer.get('snapshots') != found.fixture.snapshots:
            raise LabError(f'The fixture left {answer.get("snapshots")} DuckLake snapshots, not {found.fixture.snapshots}.')
    return {'folder': found.folder, 'files': files,
            'previous': previous.relative_to(workspace).as_posix() if previous else None}


def _rename(source: Path, target: Path) -> None:
    for attempt in range(20):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == 19:
                raise LabError(f'{source.name} could not be moved aside: a program still has it open. Close it, then '
                               'start over again.') from None
            time.sleep(0.25)


def run(workspace: Path, mission_id: str, engine: str) -> dict:
    found, _ = mission(mission_id)
    folder = mission_folder(workspace, found)
    if engine not in found.files:
        raise LabError(f'This mission is done in {" or ".join(found.engines)}.')
    source = folder / found.files[engine]  # type: ignore[index]
    if not source.is_file():
        raise LabError(f'{found.folder}/{found.files[engine]} is missing.')  # type: ignore[index]
    if engine == 'polars':
        return _run_polars(folder, source)
    answer = sandbox(folder, {'op': 'run', 'sql': source.read_text(encoding='utf-8'), 'ducklake': found.ducklake,
                              'delta': found.delta})
    return {'engine': 'duckdb', 'file': source.name, 'truth': TRUTH_SQL, **answer}


def _run_polars(folder: Path, source: Path) -> dict:
    if os.getenv('DATAPASS_TRUSTED_PYTHON') != '1':
        raise LabError('The Polars engine runs your file as local Python: turn on trusted Python for this workspace '
                       'first (it is off, so nothing ran).')
    started = time.perf_counter()
    env = _child_env()
    env['PYTHONIOENCODING'] = 'utf-8'
    try:
        done = subprocess.run([sys.executable, source.name], cwd=folder, env=env, capture_output=True, text=True,
                              encoding='utf-8', timeout=POLARS_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise LabError(f'{source.name} did not finish within {POLARS_TIMEOUT} s; it was stopped.') from None
    return {'engine': 'polars', 'file': source.name, 'truth': TRUTH_POLARS, 'exit_code': done.returncode,
            'stdout': done.stdout[-4000:], 'stderr': done.stderr[-4000:],
            'elapsed_ms': round((time.perf_counter() - started) * 1000)}


def check(workspace: Path, mission_id: str) -> dict:
    found, _ = mission(mission_id)
    folder = mission_folder(workspace, found)
    queries = probe_queries(found, folder)
    answers: list[dict] = []
    if queries:
        answer = sandbox(folder, {'op': 'probe', 'queries': queries, 'ducklake': found.ducklake, 'delta': found.delta})
        if answer.get('error'):
            answers = [{'error': answer['error']} for _ in queries]
        else:
            answers = answer['answers']
    result = evaluate(found, folder, answers)
    result['truth'] = TRUTH_CHECK
    return result


def storage(workspace: Path, mission_id: str) -> dict:
    """What is on disk under the mission's lake/ and data/: per folder, the data files and their bytes (measured);
    for a DuckLake mission, its snapshots (queried)."""
    found, _ = mission(mission_id)
    folder = mission_folder(workspace, found)
    groups: dict[str, dict[str, int]] = {}
    for top in ('data', 'lake'):
        root = folder / top
        if not root.is_dir():
            continue
        for path in root.rglob('*'):
            if not path.is_file() or path.suffix.lower() not in ('.parquet', '.csv', '.json'):
                continue
            group = groups.setdefault(path.parent.relative_to(folder).as_posix(), {'files': 0, 'bytes': 0})
            group['files'] += 1
            group['bytes'] += path.stat().st_size
    view: dict[str, Any] = {
        'folder': found.folder, 'truth': 'measured on disk',
        'folders': [{'path': key, **value} for key, value in sorted(groups.items())][:400],
    }
    if found.ducklake and (folder / 'lake' / 'catalog.ducklake').is_file():
        answer = sandbox(folder, {'op': 'probe', 'ducklake': True, 'queries': [
            {'sql': 'SELECT snapshot_id, CAST(changes AS VARCHAR) FROM lake.snapshots() ORDER BY snapshot_id'},
            {'sql': "SELECT table_name, file_count, file_size_bytes FROM ducklake_table_info('lake') ORDER BY 1"},
        ]})
        if answer.get('error'):
            view['snapshotsError'] = answer['error']
        else:
            snaps, tables = answer['answers']
            view['snapshots'] = [{'id': row[0], 'changes': row[1]} for row in snaps.get('rows', [])]
            view['tables'] = [{'name': row[0], 'files': row[1], 'bytes': row[2]} for row in tables.get('rows', [])]
            if snaps.get('error') or tables.get('error'):
                view['snapshotsError'] = snaps.get('error') or tables.get('error')
    return view
