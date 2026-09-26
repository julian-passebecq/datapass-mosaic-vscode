"""Practice exercises on the Databricks Lab: one fixture = one scenario, graded on an outcome table.

The learner writes a job (language `databricks-job`, Jobs API JSON), a notebook a
given job runs (`databricks-notebook`) or the workspace's Unity Catalog grants
(`databricks-grants`, GRANT/REVOKE SQL). Each fixture scenario gives the lab files
(notebooks, SQL files, jobs, compute, Unity Catalog groups and grants), tables for
an isolated catalog, jobs to run first (`setup_jobs`), the run settings, how many
times the job runs, and one outcome table:

- task_runs: task, kind, state, attempts, start_s, end_s, outcome, error_code;
- run: result_state, duration_s, leaves (the last run);
- values: task, key, value (task values as text);
- compute: kind, key, tasks, startup_s, billed_s, dbu, cost, idle_cost;
- table: a table's rows in the isolated catalog;
- models: name, version, aliases, owner, inputs (the Unity Catalog registry);
- mlflow_runs: experiment, run_name, status, params, metrics (as JSON text);
- access: principal, action, object, allowed (Unity Catalog checks after the runs,
  for `access` probes such as {"principal": "sp-etl", "action": "read", "object": "main.source.orders"});
- principal_rows: principal, denied, then the query's columns: each `queries` probe runs its read-only SQL as its
  principal, with Unity Catalog privileges, row filters and column masks enforced (denied is the error, or null);
- pii: table, column, tag, principal, masked for every column tagged with the key `pii_tag` (default pii): masked
  is true when the principal (`pii_principal`) sees none of the column's non-null values unchanged.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .engine import TaskBehavior

OUTCOME_COLUMNS: dict[str, list[str]] = {
    'task_runs': ['task', 'kind', 'state', 'attempts', 'start_s', 'end_s', 'outcome', 'error_code'],
    'run': ['result_state', 'duration_s', 'leaves'],
    'values': ['task', 'key', 'value'],
    'compute': ['kind', 'key', 'tasks', 'startup_s', 'billed_s', 'dbu', 'cost', 'idle_cost'],
    'models': ['name', 'version', 'aliases', 'owner', 'inputs'],
    'mlflow_runs': ['experiment', 'run_name', 'status', 'params', 'metrics'],
    'access': ['principal', 'action', 'object', 'allowed'],
    'pii': ['table', 'column', 'tag', 'principal', 'masked'],
}
LAB_TABLE = re.compile(r'^(source|bronze|silver|gold|warehouse|features|metrics)\.[A-Za-z][A-Za-z0-9_]{0,62}$')


class LabTable(BaseModel):
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
        return self


class LabFiles(BaseModel):
    model_config = ConfigDict(extra='forbid')
    notebooks: dict[str, str] = Field(default_factory=dict)
    sql: dict[str, str] = Field(default_factory=dict)
    jobs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    compute: dict[str, Any] | None = None
    unity_catalog: dict[str, Any] | None = None
    grants: str | None = None


class AccessProbe(BaseModel):
    model_config = ConfigDict(extra='forbid')
    principal: str
    action: Literal['read', 'write', 'create', 'register_model', 'load_model']
    object: str = Field(pattern=r'^main\.[a-z_]+\.[A-Za-z][A-Za-z0-9_]*$')


class QueryProbe(BaseModel):
    model_config = ConfigDict(extra='forbid')
    principal: str = Field(min_length=1, max_length=80)
    sql: str = Field(min_length=1, max_length=2000)


class DbxScenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job: str | None = None  # databricks-notebook / databricks-grants: the job of files.jobs to run
    notebook: str | None = None  # databricks-notebook: the notebook key the learner's code provides
    files: LabFiles = Field(default_factory=LabFiles)
    tables: list[LabTable] = Field(default_factory=list, max_length=8)
    setup_jobs: list[str] = Field(default_factory=list, max_length=3)
    now: datetime = datetime(2026, 3, 5, 6, 0, tzinfo=timezone.utc)
    job_parameters: dict[str, str] = Field(default_factory=dict)
    trigger_type: str = 'one_time'
    tasks: dict[str, TaskBehavior] = Field(default_factory=dict)
    cluster_states: dict[str, Literal['RUNNING', 'TERMINATED']] = Field(default_factory=dict)
    runs: int = Field(default=1, ge=1, le=3)
    data_plane: Literal['local', 'simulated'] = 'local'
    outcome: Literal['task_runs', 'run', 'values', 'compute', 'table', 'models', 'mlflow_runs', 'access',
                     'principal_rows', 'pii'] = 'task_runs'
    queries: list[QueryProbe] = Field(default_factory=list, max_length=12)
    pii_principal: str | None = None
    pii_tag: str = 'pii'
    only: list[str] = Field(default_factory=list)
    table: str | None = Field(default=None, pattern=LAB_TABLE.pattern)
    access: list[AccessProbe] = Field(default_factory=list, max_length=20)
    columns: list[str] | None = None

    @model_validator(mode='after')
    def consistent(self) -> 'DbxScenario':
        if (self.outcome == 'table') != (self.table is not None):
            raise ValueError("outcome 'table' needs table, and only it")
        if (self.outcome == 'access') != bool(self.access):
            raise ValueError("outcome 'access' needs access probes, and only it")
        if (self.outcome == 'principal_rows') != bool(self.queries):
            raise ValueError("outcome 'principal_rows' needs queries, and only it")
        if (self.outcome == 'pii') != (self.pii_principal is not None):
            raise ValueError("outcome 'pii' needs pii_principal, and only it")
        for name in self.setup_jobs + ([self.job] if self.job else []):
            if name not in self.files.jobs:
                raise ValueError(f"job {name!r} is not in files.jobs")
        if self.notebook is not None and not re.fullmatch(r'databricks:/[\w./-]+', self.notebook):
            raise ValueError('notebook is a key such as databricks:/Shared/nb_orders')
        if self.columns is not None and self.outcome in OUTCOME_COLUMNS:
            unknown = set(self.columns) - set(OUTCOME_COLUMNS[self.outcome])
            if unknown or not self.columns:
                raise ValueError(f"columns must come from {OUTCOME_COLUMNS[self.outcome]}")
        return self

    def run_scenario(self) -> dict[str, Any]:
        return {'now': self.now, 'job_parameters': self.job_parameters, 'trigger_type': self.trigger_type,
                'tasks': {k: v.model_dump() for k, v in self.tasks.items()}, 'cluster_states': self.cluster_states}


def graded_columns(scenario: DbxScenario, rows: list[dict[str, Any]]) -> list[str]:
    if scenario.columns:
        return scenario.columns
    if scenario.outcome in OUTCOME_COLUMNS:
        return OUTCOME_COLUMNS[scenario.outcome]
    return list(rows[0]) if rows else []


def as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def outcome_rows(scenario: DbxScenario, run: dict[str, Any], mlflow: dict[str, Any]) -> list[dict[str, Any]]:
    kind = scenario.outcome
    tasks = [t for t in run['tasks'] if not scenario.only or t['key'] in scenario.only]
    if kind == 'task_runs':
        return [{'task': t['key'], 'kind': t['kind'], 'state': t['state'], 'attempts': len(t['attempts']),
                 'start_s': t['start_s'], 'end_s': t['end_s'], 'outcome': t['outcome'],
                 'error_code': t['error_code'] or None} for t in tasks]
    if kind == 'run':
        return [{'result_state': run['result_state'], 'duration_s': run['duration_s'],
                 'leaves': ', '.join(run['leaves'])}]
    if kind == 'values':
        return [{'task': t['key'], 'key': k, 'value': as_text(v)} for t in tasks for k, v in sorted(t['values'].items())]
    if kind == 'compute':
        return [{'kind': u['kind'], 'key': u['key'], 'tasks': ', '.join(u['tasks']), 'startup_s': u['startup_s'],
                 'billed_s': u['billed_s'], 'dbu': round(u['dbu'], 4), 'cost': round(u['cost'], 4),
                 'idle_cost': round(u['idle_cost'], 4)} for u in run['compute']]
    if kind == 'models':
        return [{'name': m['name'], 'version': v['version'],
                 'aliases': ', '.join(sorted(a for a, n in m['aliases'].items() if n == v['version'])),
                 'owner': m['owner'], 'inputs': ', '.join((v.get('signature') or {}).get('inputs', []))}
                for m in mlflow['models'] for v in m['versions']]
    if kind == 'mlflow_runs':
        return [{'experiment': e['name'], 'run_name': r['run_name'], 'status': r['status'],
                 'params': as_text(r['params']), 'metrics': as_text({k: round(v, 4) for k, v in r['metrics'].items()})}
                for e in mlflow['experiments'] for r in e['runs']]
    raise ValueError(f"outcome {kind} is computed by the grader")


def project(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    return [{c: row.get(c) for c in columns} for row in rows]
