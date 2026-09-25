"""Practice exercises on the Factory Lab: one fixture = one scenario, graded on an outcome table.

The learner writes a pipeline JSON document (language `factory`) or a notebook
that a given pipeline runs (language `factory-notebook`). Each fixture scenario
sets the product flavor, parameters, trigger time and per-activity behavior,
the lab files the pipeline references, and optionally tables seeded in an
isolated local catalog (data plane `local`). The pipeline runs `runs` times and
one outcome table is compared with the expected rows:

- activity_runs: pipeline, name, type, status, attempts, start_s, end_s,
  iteration, parent, error_code, error (every activity run, child pipelines too);
- run: status, duration_s, evaluated, return_value (the last run);
- variables: name, value (values as text: strings as-is, others as JSON);
- inputs / outputs: name, iteration, field, value for the `fields` paths
  (dotted, into each activity run's resolved input or output);
- table: the rows of `table` in the isolated catalog after the last run.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .activities import FLAVORS
from .engine import ActivityBehavior, ActivityRun, PipelineRunResult

OUTCOME_COLUMNS: dict[str, list[str]] = {
    'activity_runs': ['pipeline', 'name', 'type', 'status', 'attempts', 'start_s', 'end_s', 'iteration', 'parent',
                      'error_code', 'error'],
    'run': ['status', 'duration_s', 'evaluated', 'return_value'],
    'variables': ['name', 'value'],
    'inputs': ['name', 'iteration', 'field', 'value'],
    'outputs': ['name', 'iteration', 'field', 'value'],
}
LAB_TABLE = re.compile(r'^(source|bronze|silver|gold|warehouse|features|metrics)\.[A-Za-z][A-Za-z0-9_]{0,62}$')


class LabTable(BaseModel):
    """A table seeded in the isolated catalog before the run. Types are inferred unless given."""
    model_config = ConfigDict(extra='forbid')
    name: str = Field(pattern=LAB_TABLE.pattern)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    columns: list[str] | None = None
    types: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def shaped(self) -> 'LabTable':
        columns = self.columns or (list(self.rows[0]) if self.rows else [])
        if not columns:
            raise ValueError(f"{self.name}: an empty table needs columns")
        if any(list(row) != columns for row in self.rows):
            raise ValueError(f"{self.name}: every row needs the columns {columns} in that order")
        if set(self.types) - set(columns):
            raise ValueError(f"{self.name}: types name unknown columns")
        return self


class LabFiles(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pipelines: dict[str, dict[str, Any]] = Field(default_factory=dict)
    datasets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    procedures: dict[str, str] = Field(default_factory=dict)
    notebooks: dict[str, str] = Field(default_factory=dict)


class ExerciseScenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    flavor: Literal['fabric', 'adf', 'synapse']
    # The pipeline name (pipeline().Pipeline); for factory-notebook, the key of files.pipelines to run.
    pipeline: str = 'pipeline'
    # factory-notebook: the notebook reference the learner's code provides ("fabric:nb", "databricks:/Shared/nb").
    notebook: str | None = None
    now: datetime | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    trigger_type: str = 'Manual'
    activities: dict[str, ActivityBehavior] = Field(default_factory=dict)
    data_plane: Literal['local', 'simulated'] = 'simulated'
    tables: list[LabTable] = Field(default_factory=list, max_length=8)
    files: LabFiles = Field(default_factory=LabFiles)
    runs: int = Field(default=1, ge=1, le=3)
    outcome: Literal['activity_runs', 'run', 'variables', 'inputs', 'outputs', 'table'] = 'activity_runs'
    # activity_runs / inputs / outputs: keep only these activities (names), in any container or child pipeline.
    only: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    table: str | None = Field(default=None, pattern=LAB_TABLE.pattern)
    columns: list[str] | None = None

    @model_validator(mode='after')
    def consistent(self) -> 'ExerciseScenario':
        if self.flavor not in FLAVORS:
            raise ValueError('unknown flavor')
        if (self.outcome == 'table') != (self.table is not None):
            raise ValueError("outcome 'table' needs table, and only it")
        if (self.tables or self.outcome == 'table') and self.data_plane != 'local':
            raise ValueError('seeded tables and table outcomes need the local data plane')
        if self.outcome in {'inputs', 'outputs'} and not self.fields:
            raise ValueError('inputs / outputs outcomes need fields')
        if self.columns is not None and self.outcome != 'table':
            unknown = set(self.columns) - set(OUTCOME_COLUMNS[self.outcome])
            if unknown or not self.columns:
                raise ValueError(f"columns must come from {OUTCOME_COLUMNS[self.outcome]}")
        return self


def text(value: Any) -> str | None:
    """Values compared as text: strings as-is, everything else as compact JSON."""
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def _path(value: Any, dotted: str) -> tuple[bool, Any]:
    for part in dotted.split('.'):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return False, None
    return True, value


def _all_runs(result: PipelineRunResult) -> list[tuple[str, ActivityRun]]:
    return [(result.pipeline, run) for run in result.runs] + [item for child in result.children for item in _all_runs(child)]


def outcome_rows(result: PipelineRunResult, scenario: ExerciseScenario,
                 table_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The graded table for one fixture, from the last run (and the isolated catalog for `table`)."""
    if scenario.outcome == 'table':
        rows = list(table_rows or [])
        return [{k: row.get(k) for k in scenario.columns} for row in rows] if scenario.columns else rows
    runs = [(pipeline, run) for pipeline, run in _all_runs(result) if not scenario.only or run.name in scenario.only]
    if scenario.outcome == 'activity_runs':
        rows = [{'pipeline': pipeline, 'name': run.name, 'type': run.type, 'status': run.status,
                 'attempts': run.attempts, 'start_s': float(run.start_s), 'end_s': float(run.end_s),
                 'iteration': run.iteration or '', 'parent': run.parent or '',
                 'error_code': (run.error or {}).get('errorCode') or '', 'error': (run.error or {}).get('message') or ''}
                for pipeline, run in runs]
    elif scenario.outcome == 'run':
        rows = [{'status': result.status, 'duration_s': float(result.duration_s),
                 'evaluated': ','.join(sorted(result.evaluated)), 'return_value': text(result.return_value)}]
    elif scenario.outcome == 'variables':
        rows = [{'name': name, 'value': text(value)} for name, value in sorted(result.variables.items())]
    else:
        rows = []
        for _, run in runs:
            source = run.input if scenario.outcome == 'inputs' else run.output
            for field in scenario.fields:
                found, value = _path(source, field)
                if found:
                    rows.append({'name': run.name, 'iteration': run.iteration or '', 'field': field, 'value': text(value)})
    columns = graded_columns(scenario, rows)
    return [{column: row[column] for column in columns} for row in rows]


DEFAULT_COLUMNS = {'activity_runs': ['name', 'status'], 'run': ['status'], 'variables': ['name', 'value']}


def graded_columns(scenario: ExerciseScenario, rows: list[dict[str, Any]]) -> list[str]:
    if scenario.outcome == 'table':
        return scenario.columns or (list(rows[0]) if rows else [])
    return scenario.columns or DEFAULT_COLUMNS.get(scenario.outcome, OUTCOME_COLUMNS[scenario.outcome])
