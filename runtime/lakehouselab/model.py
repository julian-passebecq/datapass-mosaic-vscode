"""The Lakehouse Lab's mission contract (content/lakehouse/<pack>/<mission>/mission.json).

A mission is a ticket done with the learner's own DuckDB SQL (or Polars, trusted Python only) in a folder of the
workspace, `lakehouse/<id>/`. The fixture is built by the runtime from the pack only; the checks read what the
learner's run left on disk (files, their sizes, their Parquet schemas, DuckDB's own EXPLAIN ANALYZE) and in the
mission's DuckLake catalog (tables, snapshots, time travel).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MISSION_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,47}')
Engine = Literal['duckdb', 'polars']


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Ticket(_Strict):
    model_config = ConfigDict(extra='forbid')
    from_: str = Field(alias='from')
    subject: str
    body: str | list[str]

    def text(self) -> str:
        return '\n'.join(self.body) if isinstance(self.body, list) else self.body


class Check(_Strict):
    """One check. `kind` says what it reads; the other fields belong to that kind (see checks.py)."""
    kind: Literal['layout', 'files', 'parquet_columns', 'sql', 'pruning', 'snapshots', 'untouched']
    fail: str = ''
    # layout / files / parquet_columns / untouched: a folder of the mission (relative, forward slashes)
    path: str | None = None
    partitions: list[str] = []          # layout: the Hive keys, outermost first
    count: int | None = None            # layout: partition folders; files: data files
    min_count: int | None = None
    max_count: int | None = None
    min_avg_bytes: int | None = None    # files: average data file size
    absent: list[str] = []              # parquet_columns: columns the data files must not store
    # sql: a query (on the files and, when the mission has one, the DuckLake catalog) and the rows it must return
    query: str | None = None
    before: list[str] = []              # sql: pack statements run first (ATTACH a Delta version for time travel)
    expected: list[list] | None = None
    expected_query: str | None = None
    # pruning: the learner's query file, its result compared to expected_query, and the files DuckDB really read
    file: str | None = None
    max_files_read: int | None = None
    # snapshots: the DuckLake history
    table: str | None = None
    min_new: int | None = None
    max_new: int | None = None
    readable: list[int] = []            # snapshot ids that must still be readable (time travel)
    not_recreated: bool = False

    @model_validator(mode='after')
    def _fields(self):
        needs = {
            'layout': ('path',), 'files': ('path',), 'parquet_columns': ('path',), 'untouched': ('path', 'count'),
            'sql': ('query',), 'pruning': ('file', 'expected_query', 'max_files_read'), 'snapshots': ('table',),
        }[self.kind]
        missing = [name for name in needs if getattr(self, name) in (None, '')]
        if missing:
            raise ValueError(f'a {self.kind} check needs {", ".join(missing)}')
        if self.kind == 'sql' and (self.expected is None) == (self.expected_query is None):
            raise ValueError('a sql check has expected rows or an expected_query, not both')
        for path in (self.path, self.file):
            if path and (path.startswith(('/', '.')) or '..' in path.split('/') or '\\' in path):
                raise ValueError(f'{path}: a relative path inside the mission folder')
        return self


class Criterion(_Strict):
    id: str
    text: str
    checks: list[Check] = Field(min_length=1)


class Fixture(_Strict):
    """Pack SQL run by the runtime (never a request) in the new folder: data files and the DuckLake history."""
    sql: list[str] = []
    snapshots: int = 0                  # the DuckLake snapshot count the fixture leaves (checked after building)


class Mission(_Strict):
    id: str
    version: str = '1'
    lab: Literal['lakehouse']
    title: str
    level: Literal['intro', 'intermediate', 'advanced']
    estimate: str = ''
    skills: list[str] = []
    ticket: Ticket
    engines: list[Engine] = Field(min_length=1)
    ducklake: bool = False
    # Delta tables (folders with a _delta_log) the lab attaches by folder name through DuckDB's delta extension.
    delta: list[str] = []
    fixture: Fixture = Fixture()
    acceptance: list[Criterion] = Field(min_length=1)
    hints: list[str] = []
    # The learner's files the Run button runs (per engine) and the smoke's reference / mutants replace.
    files: dict[Engine, str]
    concepts: list[str] = []

    @model_validator(mode='after')
    def _consistent(self):
        if not MISSION_ID.fullmatch(self.id):
            raise ValueError(f'invalid mission id {self.id}')
        if set(self.files) != set(self.engines):
            raise ValueError('one learner file per engine')
        if self.delta and (self.engines != ['duckdb'] or self.ducklake):
            raise ValueError('a Delta mission is done in DuckDB SQL (the delta extension), without DuckLake')
        if any(not re.fullmatch(r'[a-z0-9_]+(/[a-z0-9_]+)*', path) for path in self.delta):
            raise ValueError('Delta tables are relative folders of lower-case names')
        if self.ducklake and self.engines != ['duckdb']:
            raise ValueError('a DuckLake mission is done in DuckDB SQL (the ducklake extension)')
        if not self.ducklake and self.fixture.snapshots:
            raise ValueError('only a DuckLake mission has snapshots')
        if not self.ducklake and any(c.kind == 'snapshots' for a in self.acceptance for c in a.checks):
            raise ValueError('snapshots checks need a DuckLake mission')
        return self

    @property
    def folder(self) -> str:
        return f'lakehouse/{self.id}'

    def view(self) -> dict:
        """What the Workbench shows (never the checks: they are hidden)."""
        return {
            'id': self.id, 'version': self.version, 'lab': self.lab, 'title': self.title, 'level': self.level,
            'estimate': self.estimate, 'skills': self.skills,
            'ticket': {'from': self.ticket.from_, 'subject': self.ticket.subject, 'body': self.ticket.text()},
            'acceptance': [{'id': c.id, 'text': c.text} for c in self.acceptance], 'hints': self.hints,
            'engines': self.engines, 'ducklake': self.ducklake, 'delta': self.delta, 'files': self.files, 'concepts': self.concepts,
        }


def lakehouse_root() -> Path:
    from datapass_runtime.content import CONTENT
    return CONTENT / 'lakehouse'


def load_pack(pack_dir: Path) -> list[str]:
    pack = json.loads((pack_dir / 'pack.json').read_text(encoding='utf-8'))
    missions = pack.get('missions') if isinstance(pack, dict) else None
    if not isinstance(missions, list) or not all(isinstance(m, str) for m in missions):
        raise ValueError(f'{pack_dir.name}/pack.json lists no missions')
    return missions


def load_missions(root: Path | None = None) -> list[tuple[Mission, Path]]:
    root = root or lakehouse_root()
    found = []
    for pack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for mission_id in load_pack(pack_dir):
            found.append(find_mission(mission_id, root))
    return found


def find_mission(mission_id: str, root: Path | None = None) -> tuple[Mission, Path]:
    if not MISSION_ID.fullmatch(mission_id):
        raise ValueError('Invalid mission id.')
    root = root or lakehouse_root()
    for pack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        path = pack_dir / mission_id / 'mission.json'
        if path.is_file():
            return Mission.model_validate(json.loads(path.read_text(encoding='utf-8'))), pack_dir
    raise KeyError(f'Unknown mission {mission_id}.')
