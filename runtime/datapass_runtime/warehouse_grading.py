"""BI Lab grading: run the learner's warehouse SQL (or check their star model) per fixture on an isolated catalog.

Each check gets a DuckDB catalog in a temporary folder, seeded from the fixture's tables. The learner's
workspace catalog is never read or written. SQL really runs on DuckDB, model checks are real queries, and
lineage is a static analysis of the SQL text.
"""
from __future__ import annotations

import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bilab.exercise import WarehouseScenario, WarehouseTable, graded_columns, project
from bilab.lab import _validation_message, catalog_schema
from bilab.lineage import Lineage
from bilab.model import StarModel, check_model
from bilab.script import ScriptError, run_script, run_statements, split_script

from .catalog import Catalog
from .exercise_validation import validate_result
from .factory_grading import _column_type


class Rejected(Exception):
    pass


def _seed(catalog: Catalog, table: WarehouseTable) -> None:
    from .exercises import _fixture_sql
    columns = table.columns or list(table.rows[0])
    types = {c: table.types.get(c) or _column_type([row[c] for row in table.rows]) for c in columns}
    catalog.execute(f'CREATE OR REPLACE TABLE {table.name} AS {_fixture_sql(table.rows, columns, types)}', 'exercise-fixture')


def _run(catalog: Catalog, text: str, label: str) -> None:
    try:
        results = run_script(catalog, text, 'exercise')
    except ScriptError as error:
        raise Rejected(f'{label}: {error}') from error
    failed = next((r for r in results if r.status == 'error'), None)
    if failed:
        raise Rejected(f'{label}: statement {failed.index} (line {failed.line}) failed: {failed.message}')


def run_fixture(code: str, scenario: WarehouseScenario, language: str) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix='datapass-warehouse-exercise-', ignore_cleanup_errors=True) as folder:
        catalog = Catalog(Path(folder), 'duckdb')
        try:
            return _grade_rows(catalog, code, scenario, language)
        finally:
            catalog.close()


def _grade_rows(catalog: Catalog, code: str, scenario: WarehouseScenario, language: str) -> list[dict[str, Any]]:
    model = None
    if language == 'bi-model':
        try:
            model = StarModel.model_validate(json.loads(code))
        except json.JSONDecodeError as error:
            raise Rejected(f'Model rejected: not valid JSON (line {error.lineno}): {error.msg}') from error
        except ValidationError as error:
            raise Rejected(f'Model rejected: {_validation_message(error)}') from error
    elif scenario.model is not None:
        model = StarModel.model_validate(scenario.model)
    for table in scenario.tables:
        _seed(catalog, table)
    if scenario.setup:
        try:
            _run(catalog, scenario.setup, 'Exercise setup')
        except Rejected as error:
            raise RuntimeError(str(error)) from error
    last_select: list[dict[str, Any]] | None = None
    if language == 'warehouse':
        for step in scenario.runs:
            for table in step.tables:
                _seed(catalog, table)
            try:
                statements = split_script(code)
            except ScriptError as error:
                raise Rejected(str(error)) from error
            results = run_statements(catalog, statements, 'exercise')
            failed = next((r for r in results if r.status == 'error'), None)
            if failed:
                raise Rejected(f'Statement {failed.index} (line {failed.line}) failed: {failed.message}')
            selects = [r for r in results if r.kind in ('SELECT', 'WITH')]
            if selects:
                last_select = selects[-1].rows
    if scenario.after:
        _run(catalog, scenario.after, 'After your script, the check ran SQL and it failed')
    kind = scenario.outcome
    if kind == 'result':
        if scenario.query:
            try:
                return catalog.query(scenario.query)['rows']
            except Exception as error:
                raise Rejected(f'The graded query failed on your tables: {str(error).splitlines()[0]}') from error
        if last_select is None:
            raise Rejected('The script has no SELECT to grade.')
        return last_select
    if kind == 'table':
        if not catalog.exists(scenario.table):
            raise Rejected(f'{scenario.table} does not exist after your script.')
        return catalog.query(f'SELECT * FROM {scenario.table}')['rows']
    if kind in ('checks', 'relationships'):
        if model is None:
            raise RuntimeError('This scenario has no star model to check.')
        outcome = check_model(catalog, model)
        rows = outcome['checks'] if kind == 'checks' else outcome['relationships']
        if scenario.only:
            key = 'check' if kind == 'checks' else 'relationship'
            rows = [r for r in rows if r[key] in scenario.only]
        return rows
    lineage = Lineage({name: [c['name'] for c in cols] for name, cols in catalog_schema(catalog).items()})
    if scenario.setup:
        lineage.add_script('setup', scenario.setup)
    if language == 'warehouse':
        lineage.add_script('solution.sql', code)
    blocking = [i for i in lineage.issues if i['path'] == 'solution.sql' or i.get('code') == 'sqlglot']
    if blocking:
        raise Rejected(f"Lineage not computed: line {blocking[0]['line']}: {blocking[0]['message']}")
    if kind == 'impact':
        layer_table, column = scenario.impact_of.rsplit('.', 1)
        return lineage.impact((layer_table, column))
    rows = []
    view = lineage.view()
    for item in view['columns']:
        if item['table'] not in scenario.lineage_of and f"{item['table']}.{item['column']}" not in scenario.lineage_of:
            continue
        sources = item['origins'] if scenario.lineage_depth == 'origins' else item['sources']
        for source in sources or ['']:
            rows.append({'table': item['table'], 'column': item['column'], 'source': source,
                         'transform': item['transform']})
    return rows


def grade_warehouse(engine, request, spec, private):
    start = time.perf_counter()
    checks = []
    for fixture in private.fixtures:
        if request['mode'] != 'submit' and fixture.visibility != 'visible':
            continue
        scenario = WarehouseScenario.model_validate(fixture.scenario)
        rows: list[dict[str, Any]] = []
        message = None
        try:
            raw = run_fixture(request['code'], scenario, spec.language)
            rows = project(raw, graded_columns(scenario, raw))
        except Rejected as exc:
            message = str(exc)
        result = {'rows': rows, 'columns': graded_columns(scenario, rows), 'truncated': len(rows) > 200}
        passed = message is None and validate_result(result, fixture.expected, spec.validation,
                                                     request['code'], spec.language)
        check = dict(id=fixture.id, visibility=fixture.visibility, passed=passed,
                     status='passed' if passed else 'failed', execution_id=uuid.uuid4().hex,
                     execution_status='error' if message else 'success', elapsed_ms=0, input_versions={},
                     message=message or ('Warehouse outcome matches.' if passed else 'Warehouse outcome differs.'))
        if fixture.visibility == 'visible':
            check.update(actual=rows[:200], expected=fixture.expected)
        checks.append(check)
    import duckdb
    return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',
                checks=checks, runs=[], truth='real',
                runtime=dict(adapter=spec.runtime, engine='duckdb', engine_version=duckdb.__version__,
                             session_generation=engine.generation),
                elapsed_ms=round((time.perf_counter() - start) * 1000, 3))
