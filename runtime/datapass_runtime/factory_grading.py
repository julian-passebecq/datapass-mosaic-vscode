"""Cloud Lab pipeline grading: run the learner's pipeline (or notebook) per fixture scenario, compare outcome rows.

The pipeline JSON is validated and simulated by `factorylab`; notebooks run on
SparkLab's whitelisted interpreter. With the local data plane, Copy, Lookup,
Script, stored procedures and notebooks act on an isolated DuckDB catalog built
for the fixture in a temporary folder: the learner's workspace catalog is never
read or written.
"""
from __future__ import annotations

import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from factorylab.engine import FactoryScenario, Simulator
from factorylab.exercise import ExerciseScenario, LabTable, graded_columns, outcome_rows
from factorylab.loader import load_pipeline
from factorylab.model import FactoryLabError

from .catalog import Catalog
from .exercise_validation import validate_result
from .factory_workspace import FactoryWorkspace


def _column_type(values: list[Any]) -> str:
    present = [v for v in values if v is not None]
    if present and all(isinstance(v, bool) for v in present):
        return 'BOOLEAN'
    if present and all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        return 'BIGINT'
    if present and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return 'DOUBLE'
    return 'VARCHAR'


def _seed(catalog: Catalog, table: LabTable) -> None:
    from .exercises import _fixture_sql
    columns = table.columns or list(table.rows[0])
    types = {c: table.types.get(c) or _column_type([row[c] for row in table.rows]) for c in columns}
    catalog.execute(f"CREATE OR REPLACE TABLE {table.name} AS {_fixture_sql(table.rows, columns, types)}",
                    'exercise-fixture')


@contextmanager
def isolated_catalog(scenario: ExerciseScenario) -> Iterator[Catalog | None]:
    if scenario.data_plane != 'local':
        yield None
        return
    with tempfile.TemporaryDirectory(prefix='datapass-factory-exercise-', ignore_cleanup_errors=True) as folder:
        catalog = Catalog(Path(folder), 'duckdb')
        try:
            for table in scenario.tables:
                _seed(catalog, table)
            yield catalog
        finally:
            catalog.close()


def run_fixture(language: str, code: str, scenario: ExerciseScenario) -> list[dict[str, Any]]:
    """Outcome rows for one scenario. Raises FactoryLabError when the pipeline is rejected."""
    files = scenario.files.model_dump()
    if language == 'factory-notebook':
        files['notebooks'][scenario.notebook] = code
        document: Any = files['pipelines'][scenario.pipeline]
    else:
        document = code
    pipeline = load_pipeline(document, scenario.pipeline, scenario.flavor)
    run_scenario = FactoryScenario(now=scenario.now, parameters=scenario.parameters,
                                   trigger_type=scenario.trigger_type, activities=scenario.activities)
    with isolated_catalog(scenario) as catalog:
        workspace = FactoryWorkspace(catalog, files, local=catalog is not None)
        result = None
        for _ in range(scenario.runs):
            result = Simulator(pipeline, run_scenario, workspace).run()
        table_rows = None
        if scenario.outcome == 'table':
            table_rows = catalog.query(f"SELECT * FROM {scenario.table}")['rows'] if catalog.exists(scenario.table) else []
    return outcome_rows(result, scenario, table_rows)


def grade_factory(engine, request, spec, private):
    start = time.perf_counter()
    checks = []
    for fixture in private.fixtures:
        if request['mode'] != 'submit' and fixture.visibility != 'visible':
            continue
        scenario = ExerciseScenario.model_validate(fixture.scenario)
        rows: list[dict[str, Any]] = []
        message = None
        try:
            rows = run_fixture(spec.language, request['code'], scenario)
        except FactoryLabError as exc:
            problems = '; '.join(f"{i.path}: {i.message}" if i.path else i.message for i in exc.issues[:6])
            message = f"Pipeline rejected: {problems}"
        result = {'rows': rows, 'columns': graded_columns(scenario, rows), 'truncated': len(rows) > 200}
        passed = message is None and validate_result(result, fixture.expected, spec.validation,
                                                     request['code'], spec.language)
        check = dict(id=fixture.id, visibility=fixture.visibility, passed=passed,
                     status='passed' if passed else 'failed', execution_id=uuid.uuid4().hex,
                     execution_status='error' if message else 'success', elapsed_ms=0, input_versions={},
                     message=message or ('Pipeline outcome matches.' if passed else 'Pipeline outcome differs.'))
        if fixture.visibility == 'visible':
            check.update(actual=rows[:200], expected=fixture.expected)
        checks.append(check)
    return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',
                checks=checks, runs=[], truth='simulated',
                runtime=dict(adapter=spec.runtime, engine='datapass-factory-simulator',
                             engine_version='1', session_generation=engine.generation),
                elapsed_ms=round((time.perf_counter() - start) * 1000, 3))
