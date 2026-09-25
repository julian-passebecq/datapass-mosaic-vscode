"""Mission fixtures and the hidden checker.

Everything the checker looks at is real: read-only SQL on the workspace catalog (in the kernel), the dbt Core
artifacts the learner's own runs wrote (target/manifest.json, run_results.json, sources.json), files in the mission
folder, the result of the real `dct validate` (run by the host, passed in), and an Airflow DAG file parsed by the
Airflow Lab's whitelisted reader and simulated (never executed). Nothing is re-run or approximated here.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Callable

import yaml

from .model import (AirflowCheck, BoardCheck, DctValidateCheck, FileCheck, FreshnessConfigCheck,
                    FreshnessResultCheck, Mission, NodeCheck, RenderCheck, RunCheck, SqlCheck, TestCheck)

MAX_ARTIFACT_BYTES = 40_000_000
MAX_FILE_BYTES = 400_000
TRUTH = ('Checked for real: read-only SQL on your catalog, the artifacts of your own dbt Core runs, your files, '
         'the real dct validate, and your Airflow DAG parsed and simulated (never executed).')
PERIOD_SECONDS = {'minute': 60, 'hour': 3600, 'day': 86400}
# The target schema of the profiles the dbt Lab generates (src/platform/dbtTools.ts DBT_DEV_SCHEMA).
TARGET_SCHEMA = 'dbt_dev'


# ---- Fixtures --------------------------------------------------------------------------------------------------


def fixture_statements(mission: Mission, pack_dir: Path, batch_id: str) -> list[str]:
    """The SQL of one batch. The first batch starts over: it drops the mission's raw and dev schemas first."""
    from datapass_runtime.catalog import statements
    batch = next((b for b in mission.batches if b.id == batch_id), None)
    if batch is None:
        raise ValueError(f'Mission {mission.id} has no batch {batch_id!r}.')
    raw, dev = mission.workspace.raw_schema, mission.workspace.dev_schema
    out: list[str] = []
    if batch_id == mission.batches[0].id:
        out += [f'DROP SCHEMA IF EXISTS {raw} CASCADE', f'CREATE SCHEMA {raw}', f'DROP SCHEMA IF EXISTS {dev} CASCADE',
                # The dbt Lab profile's target schema, which dct connects to; shared, so never dropped.
                f'CREATE SCHEMA IF NOT EXISTS {TARGET_SCHEMA}']
    for relative in batch.sql:
        path = (pack_dir / relative).resolve()
        if not path.is_relative_to(pack_dir.resolve()) or path.suffix != '.sql':
            raise ValueError(f'Fixture {relative!r} is outside the pack.')
        out += statements(path.read_text(encoding='utf-8').replace('${raw}', raw))
    return out


# ---- Artifacts ---------------------------------------------------------------------------------------------------


class Files:
    """Read-only access to the mission folder in the workspace, confined to it."""

    def __init__(self, folder: Path):
        self.folder = folder.resolve()
        self._json: dict[str, Any] = {}

    def path(self, relative: str) -> Path:
        path = (self.folder / relative).resolve()
        if not path.is_relative_to(self.folder):
            raise ValueError(f'{relative} is outside the mission folder')
        return path

    def exists(self, relative: str) -> bool:
        path = self.path(relative)
        return path.is_file() and not path.is_symlink()

    def text(self, relative: str, limit: int = MAX_FILE_BYTES) -> str | None:
        path = self.path(relative)
        if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
            return None
        return path.read_text(encoding='utf-8', errors='replace')

    def json(self, relative: str) -> Any:
        if relative not in self._json:
            text = self.text(relative, MAX_ARTIFACT_BYTES)
            try:
                self._json[relative] = json.loads(text) if text is not None else None
            except json.JSONDecodeError:
                self._json[relative] = None
        return self._json[relative]


def _manifest_nodes(files: Files) -> dict[str, dict]:
    manifest = files.json('target/manifest.json')
    return manifest.get('nodes', {}) if isinstance(manifest, dict) else {}


def _find_node(files: Files, name: str, resource_type: str) -> dict | None:
    return next((n for n in _manifest_nodes(files).values()
                 if n.get('resource_type') == resource_type and n.get('name') == name), None)


# ---- Check kinds -------------------------------------------------------------------------------------------------

Outcome = tuple[bool, str]


def _node(check: NodeCheck, files: Files, _ctx: dict) -> Outcome:
    if files.json('target/manifest.json') is None:
        return False, 'No target/manifest.json yet: run dbt in the mission folder.'
    node = _find_node(files, check.name, check.resource_type)
    if node is None:
        return False, f'The project has no {check.resource_type} named {check.name}.'
    config = node.get('config') or {}
    if check.materialized and config.get('materialized') != check.materialized:
        return False, f'{check.name} is materialized as {config.get("materialized")}.'
    if check.unique_key is not None:
        key = config.get('unique_key')
        keys = [key] if isinstance(key, str) else list(key or [])
        if sorted(k.strip().lower() for k in keys) != sorted(k.lower() for k in check.unique_key):
            return False, f'{check.name} has unique_key {key!r}.'
    missing = [t for t in check.tags if t not in (node.get('tags') or [])]
    if missing:
        return False, f'{check.name} is not tagged {", ".join(missing)}.'
    code = (node.get('raw_code') or '').lower()
    absent = [c for c in check.code_contains if c.lower() not in code]
    if absent:
        return False, f'{check.name} does not use {", ".join(absent)}.'
    return True, f'{check.name}: {config.get("materialized")}.'


def _test(check: TestCheck, files: Files, _ctx: dict) -> Outcome:
    if files.json('target/manifest.json') is None:
        return False, 'No target/manifest.json yet: run dbt in the mission folder.'
    model = _find_node(files, check.model, 'model')
    if model is None:
        return False, f'The project has no model {check.model}.'
    for node in _manifest_nodes(files).values():
        meta = node.get('test_metadata') or {}
        if node.get('resource_type') != 'test' or meta.get('name') != check.test:
            continue
        if node.get('attached_node') != model.get('unique_id') or (node.get('column_name') or '').lower() != check.column.lower():
            continue
        config = node.get('config') or {}
        if str(config.get('severity', 'ERROR')).lower() != check.severity:
            return False, f'The {check.test} test on {check.model}.{check.column} has severity {config.get("severity")}.'
        if config.get('where') or config.get('enabled') is False:
            return False, f'The {check.test} test on {check.model}.{check.column} was filtered or disabled.'
        return True, f'{check.test} on {check.model}.{check.column} is in place.'
    return False, f'There is no {check.test} test on {check.model}.{check.column} any more.'


def _run(check: RunCheck, files: Files, _ctx: dict) -> Outcome:
    results = files.json('target/run_results.json')
    if not isinstance(results, dict):
        return False, 'No target/run_results.json yet: run dbt in the mission folder.'
    args = results.get('args') or {}
    which = 'docs generate' if args.get('which') == 'generate' else str(args.get('which', ''))
    if check.command and which != check.command:
        return False, f'Your last dbt command was dbt {which}, not dbt {check.command}.'
    by_name = {}
    for result in results.get('results') or []:
        uid = str(result.get('unique_id', ''))
        by_name[uid.split('.')[-1] if not uid.startswith('test.') else uid.split('.')[2]] = result
    for name, allowed in check.nodes.items():
        result = by_name.get(name)
        if result is None:
            return False, f'Your last dbt command did not run {name}.'
        if result.get('status') not in allowed:
            return False, f'{name} ended with status {result.get("status")} in your last dbt command.'
    if check.no_failures:
        bad = [r for r in results.get('results') or [] if r.get('status') in ('error', 'fail', 'runtime error', 'skipped')]
        if bad:
            names = ', '.join(str(r.get('unique_id', '')).split('.')[-1] if not str(r.get('unique_id', '')).startswith('test.')
                              else str(r.get('unique_id')).split('.')[2] for r in bad[:4])
            return False, f'Your last dbt command still has failures: {names}.'
    selected = args.get('select') or []
    selected = [selected] if isinstance(selected, str) else list(selected)
    missing = [s for s in check.select_includes if s not in selected]
    if missing:
        return False, f'Your last dbt command selected {" ".join(selected) or "everything"}.'
    if check.full_refresh is not None and bool(args.get('full_refresh')) != check.full_refresh:
        return False, 'Your last dbt command used --full-refresh.' if args.get('full_refresh') else 'Your last dbt command did not use --full-refresh.'
    if check.vars:
        given = args.get('vars') or {}
        if isinstance(given, str):
            try:
                given = yaml.safe_load(given) or {}
            except yaml.YAMLError:
                given = {}
        for key, allowed in check.vars.items():
            if str(given.get(key)) not in {str(value) for value in allowed}:
                return False, f'Your last dbt command ran with {key} = {given.get(key)!r}.'
    return True, f'Last command: dbt {which}{" --select " + " ".join(selected) if selected else ""}.'


def _source_node(files: Files, source: str) -> dict | None:
    manifest = files.json('target/manifest.json')
    source_name, table = source.split('.')
    for node in (manifest or {}).get('sources', {}).values():
        if node.get('source_name') == source_name and node.get('name') == table:
            return node
    return None


def _freshness_config(check: FreshnessConfigCheck, files: Files, _ctx: dict) -> Outcome:
    if files.json('target/manifest.json') is None:
        return False, 'No target/manifest.json yet: run dbt in the mission folder.'
    node = _source_node(files, check.source)
    if node is None:
        return False, f'The project has no source {check.source}.'
    config = node.get('config') or {}
    freshness = node.get('freshness') or config.get('freshness') or {}
    field = node.get('loaded_at_field') or config.get('loaded_at_field')
    if (field or '').lower() != check.loaded_at_field.lower():
        return False, f'{check.source} has no freshness on {check.loaded_at_field}.'

    def seconds(rule: Any) -> float | None:
        if not isinstance(rule, dict) or rule.get('count') is None or rule.get('period') not in PERIOD_SECONDS:
            return None
        return float(rule['count']) * PERIOD_SECONDS[rule['period']]

    for key, (count, period) in (('warn_after', check.warn_after), ('error_after', check.error_after)):
        if seconds(freshness.get(key)) != count * PERIOD_SECONDS[period]:
            return False, f'{check.source} has {key} {freshness.get(key)}.'
    return True, f'{check.source}: freshness on {field}.'


def _freshness_result(check: FreshnessResultCheck, files: Files, _ctx: dict) -> Outcome:
    sources = files.json('target/sources.json')
    if not isinstance(sources, dict):
        return False, 'No target/sources.json yet: run dbt source freshness in the mission folder.'
    by_name = {}
    for result in sources.get('results') or []:
        uid = str(result.get('unique_id', ''))  # source.<project>.<source>.<table>
        parts = uid.split('.')
        if len(parts) >= 4:
            by_name[f'{parts[2]}.{parts[3]}'] = result.get('status')
    for source, allowed in check.expect.items():
        status = by_name.get(source)
        if status is None:
            return False, f'dbt source freshness did not check {source}.'
        if status not in allowed:
            return False, f'{source} is {status} in target/sources.json.'
    return True, ', '.join(f'{k}: {v}' for k, v in sorted(by_name.items()))


def _dct_validate(check: DctValidateCheck, files: Files, ctx: dict) -> Outcome:
    if not files.exists(check.board):
        return False, f'{check.board} does not exist yet.'
    result = (ctx.get('dct') or {}).get(check.board)
    if not isinstance(result, dict):
        return False, f'dct validate has not checked {check.board}.'
    errors = result.get('errors') or []
    if not result.get('success') or errors:
        first = errors[0].get('message') if errors and isinstance(errors[0], dict) else ''
        return False, f'dct validate reports {len(errors)} error(s). {first}'.strip()
    return True, 'dct validate: no errors.'


def _board(check: BoardCheck, files: Files, _ctx: dict) -> Outcome:
    text = files.text(check.board)
    if text is None:
        return False, f'{check.board} does not exist yet.'
    try:
        board = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return False, f'{check.board} is not valid YAML: {str(error).splitlines()[0]}'
    if not isinstance(board, dict):
        return False, f'{check.board} is not a board.'
    queries = board.get('queries') or {}
    sql_texts = [q if isinstance(q, str) else str((q or {}).get('sql', '')) for q in queries.values()] if isinstance(queries, dict) else []
    ref = re.compile(r"ref\(\s*['\"]" + re.escape(check.ref) + r"['\"]\s*\)")
    if not any(ref.search(sql) for sql in sql_texts):
        return False, f'No query of the board reads ref(\'{check.ref}\').'
    if check.variable_column:
        variables = board.get('variables') or {}
        columns = [str((v or {}).get('column', '')) for v in variables.values()] if isinstance(variables, dict) else []
        if not any(c.split('.')[-1] == check.variable_column for c in columns):
            return False, f'The board has no filter on {check.variable_column}.'
    if check.chart_types:
        charts = board.get('charts') or {}
        types = [str((c or {}).get('type', '')) for c in charts.values()] if isinstance(charts, dict) else []
        if not any(t in check.chart_types for t in types):
            return False, f'The board has no {" or ".join(check.chart_types)} chart.'
    return True, f'{check.board} reads {check.ref}.'


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _render(check: RenderCheck, files: Files, ctx: dict) -> Outcome:
    render = files.json(check.file)
    if not isinstance(render, dict):
        return False, f'{check.file} does not exist yet: render the board with dct as JSON.'
    expected = ctx['sql'].get(check.total_sql)
    if not expected or expected.get('error') or not expected.get('rows'):
        return False, f'The warehouse total could not be read: {(expected or {}).get("error", "no rows")}'
    total = _number(next(iter(expected['rows'][0].values())))
    charts = []

    def walk(items: list) -> None:
        for item in items:
            if isinstance(item, dict):
                if isinstance(item.get('items'), list):
                    walk(item['items'])
                if item.get('type') == 'chart' and isinstance(item.get('chart'), dict):
                    charts.append(item)

    walk(render.get('items') or [])
    candidates = [c for c in charts if not check.chart_types or c['chart'].get('chart_type') in check.chart_types]
    if not candidates:
        return False, f'{check.file} has no {" or ".join(check.chart_types)} chart.'
    for chart in candidates:
        y = chart['chart'].get('y')
        ys = y if isinstance(y, list) else [y]
        for column in ys:
            values = [_number(row.get(column)) for row in chart.get('data') or [] if isinstance(row, dict)]
            if values and all(v is not None for v in values) and total is not None and abs(sum(values) - total) <= check.tolerance:
                return True, f'{chart["chart"].get("id")}: {sum(values):,.2f} in total, as in the warehouse.'
    return False, f'No chart in {check.file} adds up to the warehouse total ({total:,.2f}).'


def _file(check: FileCheck, files: Files, _ctx: dict) -> Outcome:
    if not files.exists(check.path) or files.path(check.path).stat().st_size < check.min_bytes:
        return False, f'{check.path} does not exist yet.'
    return True, f'{check.path} exists.'


def _airflow(check: AirflowCheck, files: Files, _ctx: dict) -> Outcome:
    from airflowlab.lab import lab_view
    source = files.text(check.dag, 60_000)
    if source is None:
        return False, f'{check.dag} does not exist yet.'
    view = lab_view(source, {'now': check.now, 'outcome': 'runs'})
    if view.get('status') != 'simulated' and view.get('error'):
        error = view['error']
        return False, f'The Airflow Lab cannot read {check.dag}: {error.get("message")}' + (f' (line {error["line"]})' if error.get('line') else '')
    runs = {str(run.get('logical_date', ''))[:10]: run for run in view.get('runs') or []}
    if sorted(runs) != sorted(r.logical_date for r in check.runs):
        return False, f'Up to {check.now[:16]} UTC, the simulated scheduler plans runs for {", ".join(sorted(runs)) or "no date"}.'
    for expected in check.runs:
        run = runs[expected.logical_date]
        if run.get('render_error'):
            return False, f'The run of {expected.logical_date} cannot render its templates: {run["render_error"]}'
        rendered = [r for r in run.get('rendered') or [] if r.get('field') == 'bash_command']
        if not rendered:
            return False, f'The run of {expected.logical_date} has no BashOperator command.'
        if not any(all(part in str(r.get('value')) for part in expected.command_contains) for r in rendered):
            return False, f'The run of {expected.logical_date} renders: {rendered[0].get("value")}'
    return True, f'{len(runs)} simulated runs: {", ".join(sorted(runs))}.'


def _sql(check: SqlCheck, _files: Files, ctx: dict) -> Outcome:
    from datapass_runtime.execution import compare_rows
    result = ctx['sql'].get(check.sql)
    if result is None or result.get('error'):
        return False, f'The check query failed: {(result or {}).get("error", "not run")}'
    if result.get('truncated'):
        return False, 'The check result is truncated.'
    if compare_rows(result['rows'], check.expected):
        return True, 'As expected.'
    shown = json.dumps(result['rows'][:4], default=str)
    return False, f'Found: {shown}{" …" if len(result["rows"]) > 4 else ""}'


CHECKS: dict[str, Callable[[Any, Files, dict], Outcome]] = {
    'sql': _sql, 'node': _node, 'test': _test, 'run': _run, 'freshness_config': _freshness_config,
    'freshness_result': _freshness_result, 'dct_validate': _dct_validate, 'board': _board, 'render': _render,
    'file': _file, 'airflow': _airflow,
}


def sql_queries(mission: Mission) -> list[str]:
    """Every query the checker needs from the kernel, deduplicated."""
    queries: list[str] = []
    checks = [c for criterion in mission.acceptance for c in criterion.checks] + [r.check for r in mission.requires]
    for check in checks:
        text = check.sql if isinstance(check, SqlCheck) else check.total_sql if isinstance(check, RenderCheck) else None
        if text and text not in queries:
            queries.append(text)
    return queries


def evaluate(mission: Mission, folder: Path, sql_results: dict[str, dict], dct: dict[str, Any] | None = None) -> dict:
    """Run every check. `sql_results` maps each query of sql_queries() to {rows, truncated} or {error}."""
    files = Files(folder)
    ctx = {'sql': sql_results, 'dct': dct or {}}

    def run(check) -> dict:
        try:
            passed, detail = CHECKS[check.kind](check, files, ctx)
        except Exception as error:  # a broken artifact is a failed check, not an outage
            passed, detail = False, f'Could not check: {error}'
        return {'kind': check.kind, 'passed': passed, 'detail': detail if passed or not check.fail else f'{check.fail} {detail}'}

    unmet = []
    for requirement in mission.requires:
        if not run(requirement.check)['passed']:
            unmet.append(requirement.message)
    criteria = []
    for criterion in mission.acceptance:
        results = [run(check) for check in criterion.checks]
        criteria.append({'id': criterion.id, 'text': criterion.text, 'passed': all(r['passed'] for r in results),
                         'checks': results})
    passed = not unmet and all(c['passed'] for c in criteria)
    return {
        'mission_id': mission.id, 'version': mission.version, 'status': 'passed' if passed else 'not-yet',
        'requires': unmet, 'criteria': criteria, 'checked_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'truth': TRUTH,
    }
