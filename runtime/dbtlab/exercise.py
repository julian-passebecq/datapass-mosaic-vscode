"""Practice exercises on the dbt emulation: the learner writes one file of a small dbt project.

- `dbt-sql`: a model, snapshot, singular test or macro (the scenario's `file`, ending in .sql);
- `dbt-yml`: a properties file with sources, descriptions and tests (ending in .yml).

A scenario gives the rest of the project (`files`), seeds source tables in an isolated catalog (`tables`), runs
one to three dbt commands (`runs`; each can first replace tables, like a new day of source data), and compares
one outcome:

- nodes: name, resource_type, status (and failures) of the last run's nodes (`only` keeps some names);
- table: the rows of a relation (layer.table); result: the rows of `query`;
- lineage: table, column, source of `lineage_of` models (origins through the project's own models).
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bilab.exercise import WarehouseTable

SELECTOR = re.compile(r'^[A-Za-z0-9_.*+:/@-]{1,120}$')
NODE_COLUMNS = ['name', 'resource_type', 'status']
ALL_NODE_COLUMNS = ['name', 'resource_type', 'status', 'failures', 'materialized', 'relation']


class DbtStep(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tables: list[WarehouseTable] = Field(default_factory=list, max_length=6)
    setup: str | None = Field(default=None, max_length=20_000)
    command: Literal['build', 'run', 'test', 'seed', 'snapshot'] = 'build'
    select: list[str] = Field(default_factory=list, max_length=6)
    exclude: list[str] = Field(default_factory=list, max_length=6)
    full_refresh: bool = False
    vars: dict[str, Any] = Field(default_factory=dict)
    now: str = '2026-03-01 06:00:00'

    @model_validator(mode='after')
    def bounded(self) -> 'DbtStep':
        for selector in [*self.select, *self.exclude]:
            if not SELECTOR.fullmatch(selector) or selector.startswith('-'):
                raise ValueError(f'{selector!r} is not a dbt selector')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', self.now):
            raise ValueError('now is YYYY-MM-DD HH:MM:SS')
        return self


class DbtScenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    files: dict[str, str] = Field(default_factory=dict)
    file: str = Field(pattern=r'^[a-z_]+(/[A-Za-z0-9_.-]+)+\.(sql|yml)$')
    tables: list[WarehouseTable] = Field(default_factory=list, max_length=10)
    runs: list[DbtStep] = Field(default_factory=lambda: [DbtStep()], min_length=1, max_length=3)
    outcome: Literal['nodes', 'table', 'result', 'lineage'] = 'nodes'
    table: str | None = None
    query: str | None = Field(default=None, max_length=20_000)
    only: list[str] = Field(default_factory=list)
    lineage_of: list[str] = Field(default_factory=list)
    columns: list[str] | None = None

    @model_validator(mode='after')
    def consistent(self) -> 'DbtScenario':
        if 'dbt_project.yml' not in self.files:
            raise ValueError('the scenario files need dbt_project.yml')
        if self.file in self.files:
            raise ValueError(f'{self.file} is the learner\'s file: it cannot also be in files')
        if (self.outcome == 'table') != (self.table is not None):
            raise ValueError("outcome 'table' needs table, and only it")
        if (self.outcome == 'result') != (self.query is not None):
            raise ValueError("outcome 'result' needs query, and only it")
        if (self.outcome == 'lineage') != bool(self.lineage_of):
            raise ValueError("outcome 'lineage' needs lineage_of, and only it")
        if self.columns is not None and self.outcome == 'nodes' and (set(self.columns) - set(ALL_NODE_COLUMNS) or not self.columns):
            raise ValueError(f'columns must come from {ALL_NODE_COLUMNS}')
        return self


def graded_columns(scenario: DbtScenario, rows: list[dict[str, Any]]) -> list[str]:
    if scenario.columns:
        return scenario.columns
    if scenario.outcome == 'nodes':
        return NODE_COLUMNS
    if scenario.outcome == 'lineage':
        return ['table', 'column', 'source']
    return list(rows[0]) if rows else []
