"""Databricks Lab grading: run the learner's job, notebook or grants per fixture scenario, compare outcome rows.

Every check builds an isolated DuckDB catalog in a temporary folder, seeds the
fixture tables and runs the job there (notebooks on SparkLab, never eval/exec).
The learner's workspace catalog and Databricks state are never read or written.
"""
from __future__ import annotations

import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from databrickslab.compute import load_compute
from databrickslab.engine import JobScenario, simulate_job
from databrickslab.exercise import DbxScenario, LabTable, graded_columns, outcome_rows, project
from databrickslab.mlflow_store import MlflowStore, describe as describe_mlflow
from databrickslab.model import DatabricksLabError
from databrickslab.unity import PermissionDenied, lab_table

from .catalog import Catalog
from .catalog import references, validate_sql
from .databricks_workspace import DatabricksWorkspace, map_names, secured_statement, table_columns
from databrickslab.governance import mask_leaks
from .exercise_validation import validate_result
from .factory_grading import _column_type


class JobRejected(Exception):
    pass


def _seed(catalog: Catalog, table: LabTable) -> None:
    from .exercises import _fixture_sql
    columns = table.columns or list(table.rows[0])
    types = {c: table.types.get(c) or _column_type([row[c] for row in table.rows]) for c in columns}
    catalog.execute(f"CREATE OR REPLACE TABLE {table.name} AS {_fixture_sql(table.rows, columns, types)}",
                    'exercise-fixture')


def run_fixture(language: str, code: str, scenario: DbxScenario) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix='datapass-databricks-exercise-', ignore_cleanup_errors=True) as folder:
        catalog = Catalog(Path(folder), 'duckdb')
        try:
            return _run(catalog, language, code, scenario)
        finally:
            catalog.close()


def _run(catalog: Catalog, language: str, code: str, scenario: DbxScenario) -> list[dict[str, Any]]:
    for table in scenario.tables:
        _seed(catalog, table)
    files = scenario.files.model_dump()
    jobs = files.pop('jobs')
    if language == 'databricks-job':
        try:
            document = json.loads(code)
        except ValueError as exc:
            raise JobRejected(f"Job rejected: Invalid JSON ({exc})") from None
    elif language == 'databricks-notebook':
        files['notebooks'][scenario.notebook] = code
        document = jobs[scenario.job]
    else:
        files['grants'] = code
        document = jobs.get(scenario.job) if scenario.job else None
    state: dict[str, Any] = {'owners': {}}
    compute = load_compute(files.get('compute'))
    result: dict[str, Any] | None = None
    workspace: DatabricksWorkspace | None = None

    def execute(doc: Any, label: str) -> dict[str, Any]:
        nonlocal workspace
        workspace = DatabricksWorkspace(catalog, files, state, scenario.data_plane == 'local')
        workspace.clock = scenario.now
        if workspace.unity.warnings and language == 'databricks-grants':
            raise JobRejected('Grants rejected: ' + '; '.join(workspace.unity.warnings))
        try:
            _, outcome = simulate_job(doc, compute, JobScenario.model_validate(scenario.run_scenario()), workspace)
        except DatabricksLabError as exc:
            raise JobRejected(f"{label} rejected: " + '; '.join(i['message'] for i in exc.issues)) from None
        state['owners'] = {k: v for k, v in workspace.unity.owners.items()}
        return outcome

    for name in scenario.setup_jobs:
        execute(jobs[name], f"Setup job {name}")
    if document is not None:
        for _ in range(scenario.runs):
            result = execute(document, 'Job')
    if workspace is None:  # grants only: build the catalog view once
        workspace = DatabricksWorkspace(catalog, files, state, scenario.data_plane == 'local')
        if workspace.unity.warnings:
            raise JobRejected('Grants rejected: ' + '; '.join(workspace.unity.warnings))
    if scenario.outcome == 'table':
        if not catalog.exists(scenario.table):
            return []  # no table after the run: graded as no rows
        return catalog.query(f"SELECT * FROM {scenario.table}")['rows']
    if scenario.outcome == 'principal_rows':
        return [row for probe in scenario.queries for row in _as_principal(workspace, catalog, probe.principal, probe.sql)]
    if scenario.outcome == 'pii':
        return _pii(workspace, catalog, scenario.pii_principal or '', scenario.pii_tag)
    if scenario.outcome == 'access':
        return [_probe(workspace, catalog, state, p.principal, p.action, p.object) for p in scenario.access]
    if result is None:
        raise JobRejected('The scenario runs no job')
    return outcome_rows(scenario, result, describe_mlflow(state.get('mlflow', {})))


def _as_principal(workspace: DatabricksWorkspace, catalog: Catalog, principal: str, sql: str) -> list[dict[str, Any]]:
    """A read-only query as the principal: Unity Catalog privileges, row filters and column masks enforced."""
    try:
        statements = validate_sql(map_names(sql), read_only=True)
        if len(statements) != 1 or not statements[0].lstrip().lower().startswith(('select', 'with')):
            raise JobRejected('A principal probe is one SELECT')
        statement = statements[0]
        for table in references(statement):
            workspace.unity.check_read(principal, table.lower())
        secured, _ = secured_statement(workspace.unity, catalog, statement, principal)
        result = catalog.query(secured)
    except PermissionDenied as exc:
        return [{'principal': principal, 'denied': str(exc)}]
    except ValueError as exc:
        raise JobRejected(f"Probe as {principal} failed: {exc}") from None
    return [{'principal': principal, 'denied': None, **row} for row in result['rows']]


def _pii(workspace: DatabricksWorkspace, catalog: Catalog, principal: str, tag: str) -> list[dict[str, Any]]:
    gov, rows = workspace.unity.governance, []
    groups = workspace.unity.identities(principal)
    for table, columns in sorted(gov.tags.items()):
        for column, tags in sorted(columns.items()):
            if tag not in tags:
                continue
            try:
                leaks = mask_leaks(gov, table, column, principal, groups,
                                   lambda name: table_columns(catalog, name),
                                   lambda sql: catalog.db.execute(sql).fetchone()[0])
            except ValueError as exc:
                raise JobRejected(f"Mask of {table}.{column} failed for {principal}: {exc}") from None
            rows.append({'table': table, 'column': column, 'tag': f"{tag}={tags[tag]}", 'principal': principal,
                         'masked': leaks == 0})
    return rows


def _probe(workspace: DatabricksWorkspace, catalog: Catalog, state: dict[str, Any], principal: str, action: str,
           name: str) -> dict[str, Any]:
    unity = workspace.unity
    try:
        if action in ('register_model', 'load_model'):
            store = MlflowStore(state.setdefault('mlflow', {}), unity, principal, workspace.clock)
            exists = name in store.state.get('models', {})
            unity.check_model(principal, name, 'register' if action == 'register_model' else 'load', exists)
        else:
            table = lab_table(name)
            if action == 'read':
                unity.check_read(principal, table)
            else:
                unity.check_write(principal, table, catalog.exists(table) if action == 'write' else False)
        allowed = True
    except PermissionDenied:
        allowed = False
    return {'principal': principal, 'action': action, 'object': name, 'allowed': allowed}


def grade_databricks(engine, request, spec, private):
    start = time.perf_counter()
    checks = []
    for fixture in private.fixtures:
        if request['mode'] != 'submit' and fixture.visibility != 'visible':
            continue
        scenario = DbxScenario.model_validate(fixture.scenario)
        rows: list[dict[str, Any]] = []
        message = None
        try:
            rows = run_fixture(spec.language, request['code'], scenario)
        except JobRejected as exc:
            message = str(exc)
        columns = graded_columns(scenario, rows)
        rows = project(rows, columns)
        result = {'rows': rows, 'columns': columns, 'truncated': len(rows) > 200}
        passed = message is None and validate_result(result, fixture.expected, spec.validation, request['code'],
                                                     spec.language)
        check = dict(id=fixture.id, visibility=fixture.visibility, passed=passed,
                     status='passed' if passed else 'failed', execution_id=uuid.uuid4().hex,
                     execution_status='error' if message else 'success', elapsed_ms=0, input_versions={},
                     message=message or ('Job outcome matches.' if passed else 'Job outcome differs.'))
        if fixture.visibility == 'visible':
            check.update(actual=rows[:200], expected=fixture.expected)
        checks.append(check)
    return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',
                checks=checks, runs=[], truth='simulated',
                runtime=dict(adapter=spec.runtime, engine='datapass-databricks-simulator',
                             engine_version='1', session_generation=engine.generation),
                elapsed_ms=round((time.perf_counter() - start) * 1000, 3))
