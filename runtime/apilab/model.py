"""The API Lab's missions (`content/missions/api-v1`): mission.json contract.

It follows runtime/missionlab (ticket, acceptance criteria, hints, hidden checks, reference, mutants) and reuses its
ticket and SQL check; the API-specific parts are the simulated API (`api`), its days (`batches`) and the request
log checks.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from missionlab.model import MISSION_ID, Contract, CheckBase, IDENT, SqlCheck, Ticket

from .scenario import SCENARIOS

PACK = 'api-v1'
Endpoint = Annotated[str, Field(pattern=r'^/v1/[a-z]{1,30}$')]


class ApiLogCheck(CheckBase):
    """The simulated API's request log for one run of the learner's ingestion (the last one by default)."""
    kind: Literal['api_log']
    endpoint: Endpoint
    # The run must have happened on this day of the API (after "Load day 2", for example).
    day: int | None = Field(default=None, ge=1, le=5)
    # A 200 answer for the last page (or the last cursor) of the endpoint.
    complete: bool = False
    # Answers the run must have met (the scenario was exercised: 429, 503).
    saw_status: list[int] = Field(default_factory=list, max_length=4)
    # Every 5xx was followed by the same request answered 200 later in the run.
    retried_5xx: bool = False
    # No request arrived while a Retry-After window was open.
    retry_after_respected: bool = False
    # At most this many records came back in the run (an incremental run does not refetch everything).
    max_records: int | None = Field(default=None, ge=0)
    # Every request to the endpoint carried this query parameter.
    param_required: str | None = Field(default=None, pattern=r'^[a-z_]{1,40}$')
    # Every request presented the mission key (no 401 in the run).
    authorized: bool = False


class ApiRunCheck(CheckBase):
    """The last run of the learner's ingestion finished without an error (on a given day of the API)."""
    kind: Literal['api_run']
    day: int | None = Field(default=None, ge=1, le=5)


Check = Annotated[Union[SqlCheck, ApiLogCheck, ApiRunCheck], Field(discriminator='kind')]


class Criterion(Contract):
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    text: str = Field(min_length=1, max_length=400)
    checks: list[Check] = Field(min_length=1, max_length=12)


class Requirement(Contract):
    message: str = Field(min_length=1, max_length=400)
    check: Check


class Day(Contract):
    """A day of the simulated API. The first one starts the mission; later ones are loaded by the learner."""
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    label: str = Field(min_length=1, max_length=200)
    day: int = Field(ge=1, le=5)


class Api(Contract):
    scenario: str
    seed: int = Field(ge=0, le=1_000_000)
    # Bronze tables the mission writes: dropped when the mission starts (over).
    tables: list[str] = Field(min_length=1, max_length=4)

    @model_validator(mode='after')
    def known(self) -> 'Api':
        if self.scenario not in SCENARIOS:
            raise ValueError(f'unknown API scenario {self.scenario!r}')
        for table in self.tables:
            if not IDENT.fullmatch(table):
                raise ValueError(f'{table!r} is not a simple table name (it lives in the bronze layer)')
        return self


class ReferenceStep(Contract):
    """How scripts/api_lab_smoke.py plays the answer: run an ingestion file, or load the next day of the API."""
    run: str | None = Field(default=None, pattern=r'^[a-z_/]{1,60}\.py$')
    batch: str | None = None

    @model_validator(mode='after')
    def one(self) -> 'ReferenceStep':
        if (self.run is None) == (self.batch is None):
            raise ValueError('a reference step either runs a file or loads a day')
        return self


class Mission(Contract):
    id: str = Field(pattern=MISSION_ID.pattern)
    version: str = Field(min_length=1, max_length=20)
    lab: Literal['apilab']
    title: str = Field(min_length=1, max_length=120)
    level: Literal['intro', 'intermediate', 'advanced']
    estimate: str = Field(max_length=40)
    skills: list[str] = Field(default_factory=list, max_length=10)
    ticket: Ticket
    acceptance: list[Criterion] = Field(min_length=1, max_length=10)
    requires: list[Requirement] = Field(default_factory=list, max_length=6)
    hints: list[str] = Field(default_factory=list, max_length=8)
    api: Api
    batches: list[Day] = Field(min_length=1, max_length=5)
    reference: list[ReferenceStep] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def consistent(self) -> 'Mission':
        ids = [c.id for c in self.acceptance]
        if len(ids) != len(set(ids)):
            raise ValueError('acceptance criteria ids must be unique')
        if [b.day for b in self.batches] != list(range(1, len(self.batches) + 1)):
            raise ValueError('batches are the API days 1, 2, … in order')
        if len(self.batches) > SCENARIOS[self.api.scenario].days:
            raise ValueError(f'scenario {self.api.scenario} has {SCENARIOS[self.api.scenario].days} day(s)')
        known = {b.id for b in self.batches}
        for step in self.reference:
            if step.batch is not None and step.batch not in known:
                raise ValueError(f'reference step loads unknown day {step.batch!r}')
        for check in all_checks(self):
            if isinstance(check, SqlCheck) and 'bronze.' not in check.sql:
                raise ValueError('an API Lab SQL check reads the bronze layer')
        return self

    @property
    def folder(self) -> str:
        return f'missions/{self.id}'


def all_checks(mission: Mission) -> list:
    return [c for criterion in mission.acceptance for c in criterion.checks] + [r.check for r in mission.requires]


def pack_dir() -> Path:
    from datapass_runtime.content import CONTENT
    return CONTENT / 'missions' / PACK


def load_missions(root: Path | None = None) -> list[Mission]:
    root = root or pack_dir()
    pack = json.loads((root / 'pack.json').read_text(encoding='utf-8'))
    return [find_mission(mission_id, root) for mission_id in pack['missions']]


def find_mission(mission_id: str, root: Path | None = None) -> Mission:
    if not MISSION_ID.fullmatch(mission_id):
        raise ValueError('Invalid mission id.')
    path = (root or pack_dir()) / mission_id / 'mission.json'
    if not path.is_file():
        raise KeyError(f'Unknown API Lab mission {mission_id}.')
    return Mission.model_validate(json.loads(path.read_text(encoding='utf-8')))
