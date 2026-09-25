"""The mission contract: `content/missions/<pack>/<mission>/mission.json`.

A mission is a ticket, not an exercise: context and a request from someone on the team, acceptance criteria, hints
the learner asks for one at a time, and a hidden checker. The learner works in a real project folder
(`missions/<id>/`, copied from the pack's base project plus the mission's `project/` overlay) with real tools; the
checker then looks at what really happened: read-only SQL on the catalog, the tools' own artifacts, files.

The lab field says which lab runs the mission (dbt today; the Terminal and Infra labs reuse the contract with their
own check kinds).
"""
from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

MISSION_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,47}$')
IDENT = re.compile(r'^[a-z][a-z0-9_]{0,40}$')
Scalar = Union[str, int, float, bool, None]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


def _join_lines(value: Any) -> Any:
    return '\n'.join(value) if isinstance(value, list) and all(isinstance(v, str) for v in value) else value


Lines = Annotated[str, BeforeValidator(_join_lines), Field(min_length=1, max_length=12000)]


def project_path(value: str) -> str:
    """A path inside the mission folder: relative, no `..`, simple characters."""
    parts = value.split('/')
    if (not re.fullmatch(r'[A-Za-z0-9_./-]{1,200}', value) or value.startswith('/') or '..' in parts
            or '' in parts or '.' in parts):
        raise ValueError(f'{value!r} is not a path inside the mission folder')
    return value


ProjectPath = Annotated[str, BeforeValidator(project_path)]


class CheckBase(Contract):
    # What the learner sees when the check fails (never the answer). Defaults to a generic sentence per kind.
    fail: str | None = Field(default=None, max_length=400)


class SqlCheck(CheckBase):
    """Read-only SQL on the workspace catalog, compared (order-independent) to the expected rows."""
    kind: Literal['sql']
    sql: str = Field(min_length=1, max_length=4000)
    expected: list[dict[str, Scalar]] = Field(max_length=60)


class NodeCheck(CheckBase):
    """A node of target/manifest.json and its configuration."""
    kind: Literal['node']
    name: str = Field(pattern=r'^[A-Za-z0-9_]{1,100}$')
    resource_type: Literal['model', 'seed', 'snapshot'] = 'model'
    materialized: str | None = None
    unique_key: list[str] | None = None
    tags: list[str] = Field(default_factory=list)
    # The compiled or raw SQL must mention these (lower-cased), e.g. is_incremental.
    code_contains: list[str] = Field(default_factory=list)


class TestCheck(CheckBase):
    """A generic data test on a model's column, still there and still an error (not warn, no where filter)."""
    kind: Literal['test']
    test: str = Field(pattern=r'^[a-z_]{1,40}$')
    model: str = Field(pattern=r'^[A-Za-z0-9_]{1,100}$')
    column: str = Field(pattern=r'^[A-Za-z0-9_]{1,100}$')
    severity: Literal['error', 'warn'] = 'error'


class RunCheck(CheckBase):
    """target/run_results.json of the learner's last dbt command."""
    kind: Literal['run']
    command: str | None = Field(default=None, pattern=r'^[a-z ]{1,30}$')
    nodes: dict[str, list[str]] = Field(default_factory=dict)
    no_failures: bool = False
    select_includes: list[str] = Field(default_factory=list)
    full_refresh: bool | None = None
    # Variables of the last command (--vars) and the values each may have.
    vars: dict[str, list[Scalar]] = Field(default_factory=dict)


class FreshnessConfigCheck(CheckBase):
    """A source table's freshness rules in target/manifest.json."""
    kind: Literal['freshness_config']
    source: str = Field(pattern=r'^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$')
    loaded_at_field: str
    warn_after: tuple[int, Literal['minute', 'hour', 'day']]
    error_after: tuple[int, Literal['minute', 'hour', 'day']]


class FreshnessResultCheck(CheckBase):
    """target/sources.json written by `dbt source freshness`: the status of each listed source table."""
    kind: Literal['freshness_result']
    expect: dict[str, list[Literal['pass', 'warn', 'error', 'runtime error']]]


class DctValidateCheck(CheckBase):
    """`dct validate --json <board>`: the result comes with the check request (the host ran the real dct)."""
    kind: Literal['dct_validate']
    board: ProjectPath


class BoardCheck(CheckBase):
    """The board file itself: a query on ref(model), a filter variable, a chart type."""
    kind: Literal['board']
    board: ProjectPath
    ref: str = Field(pattern=r'^[A-Za-z0-9_]{1,100}$')
    variable_column: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_]{1,100}$')
    chart_types: list[str] = Field(default_factory=list)


class RenderCheck(CheckBase):
    """A `dct render --format json` output: a chart's data must add up to the same total as a SQL query."""
    kind: Literal['render']
    file: ProjectPath
    chart_types: list[str] = Field(default_factory=list)
    total_sql: str = Field(min_length=1, max_length=2000)
    tolerance: float = 0.01


class FileCheck(CheckBase):
    kind: Literal['file']
    path: ProjectPath
    min_bytes: int = 1


class AirflowRun(Contract):
    logical_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    # The run's rendered bash_command must contain all of these (for example the day it loads).
    command_contains: list[str] = Field(default_factory=list, max_length=10)


class AirflowCheck(CheckBase):
    """An Airflow DAG file, parsed (never executed) and its schedule simulated up to `now` (Airflow 3 semantics)."""
    kind: Literal['airflow']
    dag: ProjectPath
    now: str
    # Exactly these runs, in any order.
    runs: list[AirflowRun] = Field(min_length=1, max_length=31)


Check = Annotated[Union[SqlCheck, NodeCheck, TestCheck, RunCheck, FreshnessConfigCheck, FreshnessResultCheck,
                        DctValidateCheck, BoardCheck, RenderCheck, FileCheck, AirflowCheck],
                  Field(discriminator='kind')]


class Criterion(Contract):
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    text: str = Field(min_length=1, max_length=400)
    checks: list[Check] = Field(min_length=1, max_length=12)


class Requirement(Contract):
    """A precondition (for example: the second day's data was loaded), with what to do when it is not met."""
    message: str = Field(min_length=1, max_length=400)
    check: Check


class Batch(Contract):
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    label: str = Field(min_length=1, max_length=200)
    # Fixture SQL files, relative to the pack folder; `${raw}` stands for the mission's raw schema.
    sql: list[str] = Field(min_length=1, max_length=8)


class Ticket(Contract):
    from_: str = Field(alias='from', min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=200)
    body: Lines


class Workspace(Contract):
    raw_schema: str = Field(pattern=IDENT.pattern)
    # Every schema dbt builds for this mission starts with this (dbt's <target schema>_<custom schema>).
    dev_schema: str = Field(pattern=IDENT.pattern)


class ReferenceStep(Contract):
    """How scripts/missions_smoke.py plays the reference solution: load a batch, run a real command."""
    batch: str | None = None
    dbt: str | None = Field(default=None, max_length=300)
    dct: str | None = Field(default=None, max_length=300)
    dct_validate: str | None = None
    # A command can be expected to fail, e.g. dbt source freshness with a stale source exits 1.
    exit_code: int = 0

    @model_validator(mode='after')
    def one(self) -> 'ReferenceStep':
        if sum(v is not None for v in (self.batch, self.dbt, self.dct, self.dct_validate)) != 1:
            raise ValueError('a reference step does exactly one thing')
        return self


class Mission(Contract):
    id: str = Field(pattern=MISSION_ID.pattern)
    version: str = Field(min_length=1, max_length=20)
    lab: Literal['dbt']
    title: str = Field(min_length=1, max_length=120)
    level: Literal['intro', 'intermediate', 'advanced']
    estimate: str = Field(max_length=40)
    skills: list[str] = Field(default_factory=list, max_length=10)
    ticket: Ticket
    acceptance: list[Criterion] = Field(min_length=1, max_length=10)
    requires: list[Requirement] = Field(default_factory=list, max_length=6)
    hints: list[str] = Field(default_factory=list, max_length=8)
    workspace: Workspace
    batches: list[Batch] = Field(min_length=1, max_length=6)
    reference: list[ReferenceStep] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def consistent(self) -> 'Mission':
        ids = [c.id for c in self.acceptance]
        if len(ids) != len(set(ids)):
            raise ValueError('acceptance criteria ids must be unique')
        batches = {b.id for b in self.batches}
        for step in self.reference:
            if step.batch is not None and step.batch not in batches:
                raise ValueError(f'reference step loads unknown batch {step.batch!r}')
        return self

    @property
    def folder(self) -> str:
        return f'missions/{self.id}'


def missions_root() -> Path:
    from datapass_runtime.content import CONTENT
    return CONTENT / 'missions'


def load_pack(pack_dir: Path) -> dict:
    pack = json.loads((pack_dir / 'pack.json').read_text(encoding='utf-8'))
    if not isinstance(pack, dict) or not isinstance(pack.get('missions'), list):
        raise ValueError(f'{pack_dir.name}/pack.json lists no missions')
    return pack


def find_mission(mission_id: str, root: Path | None = None) -> tuple[Mission, Path]:
    """The mission and its pack folder. Mission ids are unique across packs."""
    if not MISSION_ID.fullmatch(mission_id):
        raise ValueError('Invalid mission id.')
    root = root or missions_root()
    for pack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        path = pack_dir / mission_id / 'mission.json'
        if path.is_file():
            return Mission.model_validate(json.loads(path.read_text(encoding='utf-8'))), pack_dir
    raise KeyError(f'Unknown mission {mission_id}.')


def load_missions(root: Path | None = None) -> list[tuple[Mission, Path]]:
    root = root or missions_root()
    found = []
    for pack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for mission_id in load_pack(pack_dir)['missions']:
            found.append(find_mission(mission_id, root))
    return found
