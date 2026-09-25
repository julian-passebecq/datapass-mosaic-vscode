"""dbt exercises graded on the Datapass dbt emulation, each check on an isolated DuckDB catalog.

The learner's file joins the scenario's project files; the commands run with the emulation (sandboxed Jinja,
real DuckDB SQL). The learner's workspace catalog is never read or written.
"""
from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from bilab.exercise import project as project_rows
from dbtlab.engine import DbtRunError, Runner
from dbtlab.exercise import DbtScenario, graded_columns
from dbtlab.lab import lineage_of
from dbtlab.project import DbtProjectError, load_project
from dbtlab.render import RenderError

from .catalog import Catalog
from .exercise_validation import validate_result
from .warehouse_grading import _seed


class Rejected(Exception):
    pass


def run_fixture(code: str, scenario: DbtScenario) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix='datapass-dbt-exercise-', ignore_cleanup_errors=True) as folder:
        catalog = Catalog(Path(folder), 'duckdb')
        try:
            return _rows(catalog, code, scenario)
        finally:
            catalog.close()


def _rows(catalog: Catalog, code: str, scenario: DbtScenario) -> list[dict[str, Any]]:
    files = {**scenario.files, scenario.file: code}
    for table in scenario.tables:
        _seed(catalog, table)
    last: dict[str, Any] | None = None
    runner = None
    for step in scenario.runs:
        for table in step.tables:
            _seed(catalog, table)
        if step.setup:
            catalog.execute(step.setup, 'exercise-setup')
        try:
            project = load_project(files, 'silver', step.vars)
        except DbtProjectError as error:
            raise Rejected(f'Project rejected: {error}') from error
        runner = Runner(catalog, project, step.now)
        try:
            last = runner.run(step.command, step.select or None, step.exclude or None, step.full_refresh)
        except DbtRunError as error:
            raise Rejected(f'dbt {step.command} rejected: {error}') from error
    kind = scenario.outcome
    if kind == 'nodes':
        rows = [{'name': r['name'], 'resource_type': r['resource_type'], 'status': r['status'],
                 'failures': r['failures'], 'materialized': r['materialized'], 'relation': r['relation']}
                for r in last['results']]
        return [r for r in rows if r['name'] in scenario.only] if scenario.only else rows
    errors = [r for r in last['results'] if r['status'] == 'error']
    if errors:
        raise Rejected(f"{errors[0]['name']} failed: {errors[0]['message']}")
    if kind == 'table':
        if not catalog.exists(scenario.table):
            raise Rejected(f'{scenario.table} does not exist after dbt {scenario.runs[-1].command}.')
        return catalog.query(f'SELECT * FROM {scenario.table}')['rows']
    if kind == 'result':
        try:
            return catalog.query(scenario.query)['rows']
        except Exception as error:
            raise Rejected(f'The graded query failed on your tables: {str(error).splitlines()[0]}') from error
    view = lineage_of(catalog, runner.project, runner)
    blocking = [i for i in view['issues'] if i['path'] == scenario.file]
    if blocking:
        raise Rejected(f"Lineage not computed: {blocking[0]['message']}")
    out = []
    for item in view['columns']:
        if item['table'] in scenario.lineage_of or f"{item['table']}.{item['column']}" in scenario.lineage_of:
            for source in item['origins'] or ['']:
                out.append({'table': item['table'], 'column': item['column'], 'source': source, 'transform': item['transform']})
    return out


def grade_dbt_project(engine, request, spec, private):
    start = time.perf_counter()
    checks = []
    for fixture in private.fixtures:
        if request['mode'] != 'submit' and fixture.visibility != 'visible':
            continue
        scenario = DbtScenario.model_validate(fixture.scenario)
        rows: list[dict[str, Any]] = []
        message = None
        try:
            raw = run_fixture(request['code'], scenario)
            rows = project_rows(raw, graded_columns(scenario, raw))
        except (Rejected, RenderError) as exc:
            message = str(exc)
        result = {'rows': rows, 'columns': graded_columns(scenario, rows), 'truncated': len(rows) > 200}
        passed = message is None and validate_result(result, fixture.expected, spec.validation,
                                                     request['code'], spec.language)
        check = dict(id=fixture.id, visibility=fixture.visibility, passed=passed,
                     status='passed' if passed else 'failed', execution_id=uuid.uuid4().hex,
                     execution_status='error' if message else 'success', elapsed_ms=0, input_versions={},
                     message=message or ('dbt outcome matches.' if passed else 'dbt outcome differs.'))
        if fixture.visibility == 'visible':
            check.update(actual=rows[:200], expected=fixture.expected)
        checks.append(check)
    import duckdb
    return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',
                checks=checks, runs=[], truth='semantic-emulation',
                runtime=dict(adapter=spec.runtime, engine='datapass-dbt-emulation', engine_version=duckdb.__version__,
                             session_generation=engine.generation),
                elapsed_ms=round((time.perf_counter() - start) * 1000, 3))
