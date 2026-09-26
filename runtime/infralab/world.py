"""The simulated world of one Infra Lab folder: `<folder>/.infralab/world.json` and the command journal.

The world is what the simulated tools act on: a fake Azure subscription (resource groups, storage, networks, virtual
machines with their metric scenarios, alert rules), a local Docker engine (images, build cache, containers) and a
Kubernetes cluster (nodes, objects, events). Nothing in it exists anywhere else. It is plain JSON, deterministic
(fixed ids and a simulated clock that each command advances), and rebuilt from the mission's shipped fixture when a
mission starts over.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any

WORLD_DIR = '.infralab'
WORLD_FILE = 'world.json'
JOURNAL_FILE = 'journal.jsonl'
MAX_WORLD_BYTES = 8_000_000
MAX_JOURNAL_LINES = 2000
SIMULATED = 'Simulated by the Datapass Infra Lab: nothing was provisioned, built or deployed.'

DEFAULT_WORLD: dict[str, Any] = {
    'version': 1,
    'note': SIMULATED,
    'clock': '2026-10-05T09:00:00Z',
    'azure': {
        'subscription_id': '6d1f2c3a-0b4e-4c8d-9a7f-2e5b8c1d4f60',
        'subscription_name': 'Contoso Data (lab)',
        'tenant_id': 'b7e3a9d2-5c14-4f6e-8a21-9d0c7e4b3f15',
        'client_object_id': '0f4c8e21-7a3b-4d59-b6e2-1c9a5d3f7e08',
        'resources': {},
        'taken_names': {'storage_account': [], 'key_vault': []},
    },
    'terraform': {'initialized': False, 'providers': {}},
    'docker': {'images': {}, 'containers': {}, 'cache': [], 'base_images': {}, 'apps': {}},
    'kube': {'nodes': [], 'images': {}, 'objects': {}, 'events': [], 'rollouts': []},
}


class WorldError(RuntimeError):
    pass


def world_path(folder: Path) -> Path:
    return folder / WORLD_DIR / WORLD_FILE


def merge_defaults(world: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(DEFAULT_WORLD)
    for key, value in world.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **deepcopy(value)}
        else:
            out[key] = deepcopy(value)
    return out


def load(folder: Path) -> dict[str, Any]:
    path = world_path(folder)
    if not path.is_file():
        return merge_defaults({})
    if path.stat().st_size > MAX_WORLD_BYTES:
        raise WorldError('The simulated world file is too large.')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise WorldError(f'{WORLD_DIR}/{WORLD_FILE} is not valid JSON ({error.msg}); start the mission over to rebuild it.') from None
    if not isinstance(data, dict):
        raise WorldError(f'{WORLD_DIR}/{WORLD_FILE} is not a JSON object.')
    return merge_defaults(data)


def save(folder: Path, world: dict[str, Any]) -> None:
    path = world_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, world)


def write_json(path: Path, data: Any) -> None:
    text = json.dumps(data, indent=2, sort_keys=False) + '\n'
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(text, encoding='utf-8', newline='\n')
    for attempt in range(20):
        try:
            os.replace(temp, path)
            return
        except PermissionError:  # a scanner holds the file for a moment on Windows
            if attempt == 19:
                raise
            import time
            time.sleep(0.1)


# ---- Clock ---------------------------------------------------------------------------------------------------------


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)


def format_time(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def now(world: dict[str, Any]) -> datetime:
    return parse_time(world['clock'])


def advance(world: dict[str, Any], seconds: float) -> str:
    moment = now(world) + timedelta(seconds=max(0, round(seconds)))
    world['clock'] = format_time(moment)
    return world['clock']


# ---- Journal -------------------------------------------------------------------------------------------------------


def journal_path(folder: Path) -> Path:
    return folder / WORLD_DIR / JOURNAL_FILE


def append_journal(folder: Path, entry: dict[str, Any]) -> None:
    path = journal_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(entry, sort_keys=True) + '\n')


def read_journal(folder: Path) -> list[dict[str, Any]]:
    path = journal_path(folder)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines()[-MAX_JOURNAL_LINES:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def reset(folder: Path, world: dict[str, Any]) -> None:
    """Write a fresh world (from a mission fixture) and an empty journal."""
    save(folder, merge_defaults(world))
    path = journal_path(folder)
    if path.exists():
        path.unlink()
