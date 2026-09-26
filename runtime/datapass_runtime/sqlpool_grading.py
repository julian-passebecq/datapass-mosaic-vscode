"""SQL pool Lab grading: run the learner's T-SQL per fixture scenario on an isolated catalog, compare outcome rows.

Each check gets a DuckDB catalog in a temporary folder, seeded from the fixture's
tables (with the designs and scale they already have). The learner's workspace
catalog is never read or written. Data statements really run; distributions,
partitions and plans come from the lab's model.
"""
from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from sqlpoollab.engine import SqlPool, StatementResult
from sqlpoollab.exercise import PoolScenario, PoolTable, graded_columns, project
from sqlpoollab.lab import display_name, display_text
from sqlpoollab.model import Metadata, PoolError, TableDesign
from sqlpoollab.physical import distribution_stats, partition_stats
from sqlpoollab.tsql import lab_name, read_options, tokenize

from .catalog import Catalog
from .exercise_validation import validate_result
from .factory_grading import _column_type
from .sqlpool_database import CatalogDatabase


class ScriptRejected(Exception):
    pass


def _seed(catalog: Catalog, metadata: Metadata, table: PoolTable) -> None:
    from .exercises import _fixture_sql
    name = lab_name(table.name.split('.'))
    columns = table.columns or list(table.rows[0])
    types = {c: table.types.get(c) or _column_type([row[c] for row in table.rows]) for c in columns}
    catalog.execute(f"CREATE TABLE {name} AS {_fixture_sql(table.rows, columns, types)}", 'exercise-fixture')
    design = TableDesign(name, created_by='exercise fixture')
    if table.design:
        options = read_options(tokenize(table.design))
        design.distribution = options.distribution or 'ROUND_ROBIN'
        design.hash_columns = list(options.hash_columns)
        design.index = options.index or 'CLUSTERED COLUMNSTORE INDEX'
        design.index_columns = list(options.index_columns)
        design.partition = options.partition
    if table.represented_rows:
        design.scale_factor = table.represented_rows / max(1, len(table.rows))
    metadata.tables[name] = design


def _first_error(results: list[StatementResult]) -> StatementResult | None:
    return next((r for r in results if r.status == 'error'), None)


def run_fixture(code: str, scenario: PoolScenario) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix='datapass-sqlpool-exercise-', ignore_cleanup_errors=True) as folder:
        catalog = Catalog(Path(folder), 'duckdb')
        try:
            return _run(catalog, code, scenario)
        finally:
            catalog.close()


def _run(catalog: Catalog, code: str, scenario: PoolScenario) -> list[dict[str, Any]]:
    db = CatalogDatabase(catalog)
    metadata = Metadata(None)
    for table in scenario.tables:
        _seed(catalog, metadata, table)
    pool = SqlPool(db, metadata, scenario.flavor, scenario.now)
    if scenario.setup:
        failed = _first_error(pool.run(scenario.setup))
        if failed:
            raise RuntimeError(f"Exercise setup failed: {failed.message}")
    results = pool.run(code)
    failed = _first_error(results)
    if failed:
        raise ScriptRejected(f"Statement {failed.index} (line {failed.line}) failed: {display_text(failed.message)}")
    graded = next((r for r in reversed(results) if r.kind in ('SELECT', 'EXPLAIN')), None)
    if scenario.after:
        failed = _first_error(pool.run(scenario.after))
        if failed:
            raise ScriptRejected(f"After your script, the check ran {failed.kind} and it failed: "
                                 f"{display_text(failed.message)}")
    if scenario.outcome == 'principals':
        return project(_as_principals(pool, scenario), graded_columns(scenario, []) if scenario.columns else
                       _principal_columns(pool, scenario))
    if scenario.query:
        outcome = pool.run(scenario.query)
        failed = _first_error(outcome)
        if failed:
            raise ScriptRejected(f"The graded query failed on your tables: {display_text(failed.message)}")
        graded = outcome[-1]
    rows = _outcome(pool, catalog, scenario, graded)
    return project(rows, graded_columns(scenario, rows))


def _as_principals(pool: SqlPool, scenario: PoolScenario) -> list[dict[str, Any]]:
    """The graded query as each principal: its rows, or one row with the permission error."""
    rows: list[dict[str, Any]] = []
    for principal in scenario.principals:
        if principal.lower() != 'dbo':
            failed = _first_error(pool.run(f"EXECUTE AS USER = '{principal}';"))
            if failed:
                raise ScriptRejected(f"EXECUTE AS USER = '{principal}' failed after your script: "
                                     f"{display_text(failed.message)}")
        results = pool.run(scenario.query or '')
        failed = _first_error(results)
        if principal.lower() != 'dbo':
            pool.run('REVERT;')
        if failed:
            if 'permission was denied' not in failed.message:
                raise ScriptRejected(f"The graded query failed as {principal}: {display_text(failed.message)}")
            rows.append({'principal': principal, 'denied': display_text(failed.message)})
            continue
        graded = results[-1]
        rows.extend({'principal': principal, 'denied': None, **row} for row in graded.rows)
    return rows


def _principal_columns(pool: SqlPool, scenario: PoolScenario) -> list[str]:
    results = pool.run(scenario.query or '')
    columns = results[-1].columns if results and results[-1].status == 'ok' else []
    return ['principal', 'denied'] + list(columns)


def _outcome(pool: SqlPool, catalog: Catalog, scenario: PoolScenario,
             graded: StatementResult | None) -> list[dict[str, Any]]:
    kind = scenario.outcome
    if kind in ('movement', 'scans', 'result'):
        if graded is None:
            raise ScriptRejected('The script has no SELECT or EXPLAIN to grade.')
        if kind == 'result':
            return graded.rows
        plan = graded.plan or {}
        if kind == 'movement':
            return [{'operation': s['operation'], 'tables': ', '.join(display_name(t) for t in s['tables']),
                     'columns': ', '.join(s['columns'])} for s in plan.get('steps', [])
                    if s['operation'] != 'ReturnOperation']
        return [{'table': display_name(s['table']), 'partitions_scanned': s['partitions_scanned'],
                 'partitions_total': s['partitions_total']} for s in plan.get('scans', [])]
    if kind == 'table':
        name = lab_name(scenario.table.split('.'))
        if not catalog.exists(name):
            raise ScriptRejected(f"{scenario.table} does not exist after your script.")
        return catalog.query(f"SELECT * FROM {name}")['rows']
    rows = []
    for wanted in scenario.only:
        name = lab_name(wanted.split('.'))
        design = pool.design_of(name)
        if design is None:
            raise ScriptRejected(f"{wanted} does not exist after your script.")
        count = pool.db.count(name)
        factor = design.scale_factor or pool.scale
        shown = display_name(name)
        if kind == 'designs':
            rows.append({'table': shown, 'distribution': design.distribution,
                         'distribution_columns': ', '.join(design.hash_columns), 'index': design.index,
                         'index_columns': ', '.join(design.index_columns),
                         'partition_column': design.partition.column if design.partition else '',
                         'partition_range': design.partition.range if design.partition else '',
                         'partitions': design.partition.count if design.partition else 1,
                         'cluster_by': ', '.join(design.cluster_by)})
        elif kind == 'distribution':
            stats = distribution_stats(pool.db, design, count, factor)
            rows.append({'table': shown, 'distribution': design.distribution, 'skew_pct': stats.skew_pct,
                         'skew_over_10pct': stats.skew_pct >= 10, 'max_share_pct': round(stats.max_share * 100, 1),
                         'empty_distributions': stats.empty_distributions})
        elif kind == 'partition_health':
            parts = [p for p in partition_stats(pool.db, design, count, factor) if p.rows]
            if not design.partition:
                per = count * factor / (60 if design.distribution != 'REPLICATE' else 1)
                parts_total, populated, low = 1, 1 if count else 0, per
                ok = design.index != 'CLUSTERED COLUMNSTORE INDEX' or per >= 1_000_000
            else:
                parts_total, populated = design.partition.count, len(parts)
                low = min((p.rows_per_distribution or 0) for p in parts) if parts else 0
                ok = all(p.columnstore_ok is not False for p in parts)
            rows.append({'table': shown, 'partitions': parts_total, 'populated_partitions': populated,
                         'min_rows_per_distribution': round(low), 'columnstore_ok': ok})
        elif kind == 'partitions':
            rows.extend({'table': shown, 'partition_number': p.number, 'rows': p.rows,
                         'rows_per_distribution': round(p.rows_per_distribution or 0),
                         'columnstore_ok': p.columnstore_ok}
                        for p in partition_stats(pool.db, design, count, factor))
        else:
            rows.extend({'table': shown, 'kind': c['kind'], 'columns': ', '.join(c['columns']),
                         'enforced': bool(c.get('enforced'))} for c in design.constraints)
    return rows


def grade_sqlpool(engine, request, spec, private):
    start = time.perf_counter()
    checks = []
    for fixture in private.fixtures:
        if request['mode'] != 'submit' and fixture.visibility != 'visible':
            continue
        scenario = PoolScenario.model_validate(fixture.scenario)
        rows: list[dict[str, Any]] = []
        message = None
        try:
            rows = run_fixture(request['code'], scenario)
        except (ScriptRejected, PoolError) as exc:
            message = str(exc)
        result = {'rows': rows, 'columns': graded_columns(scenario, rows), 'truncated': len(rows) > 200}
        passed = message is None and validate_result(result, fixture.expected, spec.validation,
                                                     request['code'], spec.language)
        check = dict(id=fixture.id, visibility=fixture.visibility, passed=passed,
                     status='passed' if passed else 'failed', execution_id=uuid.uuid4().hex,
                     execution_status='error' if message else 'success', elapsed_ms=0, input_versions={},
                     message=message or ('SQL pool outcome matches.' if passed else 'SQL pool outcome differs.'))
        if fixture.visibility == 'visible':
            check.update(actual=rows[:200], expected=fixture.expected)
        checks.append(check)
    return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',
                checks=checks, runs=[], truth='simulated',
                runtime=dict(adapter=spec.runtime, engine='datapass-sqlpool-simulator',
                             engine_version='1', session_generation=engine.generation),
                elapsed_ms=round((time.perf_counter() - start) * 1000, 3))
