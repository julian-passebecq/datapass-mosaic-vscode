"""The Lakehouse Lab's hidden checker.

Files are measured here (walks of the mission folder: paths, counts, bytes). Everything that needs DuckDB (rows,
Parquet schemas, DuckLake snapshots, EXPLAIN ANALYZE) is a read-only probe run in the sandbox process on the same
folder, with the DuckLake catalog attached READ_ONLY. A failed check shows its `fail` sentence and what it found,
never the expected answer.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from .model import Check, Mission

Outcome = tuple[bool, str]


def _sql_text(value: str) -> str:
    return value.replace("'", "''")


def _queries(check: Check, folder: Path) -> list[dict]:
    """The probes a check needs, in the order it reads their answers."""
    if check.kind == 'parquet_columns':
        return [{'sql': f"SELECT DISTINCT name FROM parquet_schema('{_sql_text(check.path)}/**/*.parquet')"}]
    if check.kind == 'sql':
        return [{'sql': check.query, 'before': check.before}] + ([{'sql': check.expected_query}] if check.expected_query else [])
    if check.kind == 'pruning':
        source = folder / check.file
        text = source.read_text(encoding='utf-8') if source.is_file() else ''
        return [{'sql': text, 'script': True}, {'sql': text, 'script': True, 'analyze': True}, {'sql': check.expected_query}]
    if check.kind == 'snapshots':
        table = check.table
        probes = [{'sql': 'SELECT count(*) FROM lake.snapshots()'},
                  {'sql': f"SELECT count(*) FROM lake.snapshots() WHERE list_contains(changes['tables_created'], 'main.{table}')"},
                  {'sql': f'SELECT count(*) FROM lake.main."{table}"'}]
        probes += [{'sql': f'SELECT count(*) FROM lake.main."{table}" AT (VERSION => {n})'} for n in check.readable]
        return probes
    return []


def probe_queries(mission: Mission, folder: Path) -> list[dict]:
    return [query for criterion in mission.acceptance for check in criterion.checks for query in _queries(check, folder)]


def _data_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob('*') if p.is_file() and not p.name.startswith(('.', '_')))


def _layout(check: Check, folder: Path, _answers: list[dict], _mission: Mission) -> Outcome:
    root = folder / check.path
    if not root.is_dir():
        return False, f'{check.path}/ does not exist.'
    files = _data_files(root)
    if not files:
        return False, f'{check.path}/ holds no file.'
    others = [f for f in files if f.suffix.lower() != '.parquet']
    if others:
        return False, f'{len(others)} file(s) are not Parquet, e.g. {others[0].relative_to(folder).as_posix()}.'
    leaves = set()
    for path in files:
        parts = path.relative_to(root).parts[:-1]
        keys = [part.split('=', 1)[0] for part in parts]
        if keys != check.partitions or any('=' not in part for part in parts):
            shown = '/'.join(parts) or '(no partition folder)'
            want = '/'.join(f'{key}=…' for key in check.partitions)
            return False, f'{path.relative_to(folder).as_posix()} sits in {shown}; expected folders {want}.'
        leaves.add(parts)
    found = len(leaves)
    if check.count is not None and found != check.count:
        return False, f'{found} partition folders.'
    if check.min_count is not None and found < check.min_count:
        return False, f'{found} partition folders.'
    return True, f'{found} partitions, {len(files)} Parquet files.'


def _files(check: Check, folder: Path, _answers: list[dict], _mission: Mission) -> Outcome:
    root = folder / check.path
    files = [f for f in _data_files(root) if f.suffix.lower() == '.parquet'] if root.is_dir() else []
    count = len(files)
    total = sum(f.stat().st_size for f in files)
    average = total // count if count else 0
    shown = f'{count} Parquet files, {total:,} bytes, {average:,} bytes on average (measured).'
    if not count:
        return False, f'{check.path}/ holds no Parquet file.'
    if check.count is not None and count != check.count:
        return False, shown
    if check.min_count is not None and count < check.min_count:
        return False, shown
    if check.max_count is not None and count > check.max_count:
        return False, shown
    if check.min_avg_bytes is not None and average < check.min_avg_bytes:
        return False, shown
    return True, shown


def _untouched(check: Check, folder: Path, _answers: list[dict], _mission: Mission) -> Outcome:
    root = folder / check.path
    count = len(_data_files(root)) if root.is_dir() else 0
    return (count == check.count), f'{check.path}/ holds {count} files.'


def _parquet_columns(check: Check, _folder: Path, answers: list[dict], _mission: Mission) -> Outcome:
    answer = answers[0]
    if answer.get('error'):
        return False, f'Could not read the Parquet schemas: {_short(answer["error"])}'
    names = {str(row[0]) for row in answer['rows']}
    stored = sorted(names & set(check.absent))
    if stored:
        return False, f'The data files also store {", ".join(stored)}.'
    return True, 'Partition values live in the folder names only.'


def _same(actual: list[list], expected: list[list]) -> bool:
    if len(actual) != len(expected):
        return False

    def key(row: list) -> tuple:
        return tuple((0, round(float(v), 6)) if isinstance(v, (int, float)) and not isinstance(v, bool)
                     else (1, '' if v is None else str(v)) for v in row)

    for a, b in zip(sorted(actual, key=key), sorted(expected, key=key)):
        if len(a) != len(b):
            return False
        for x, y in zip(a, b):
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                if not math.isclose(float(x), float(y), rel_tol=1e-9, abs_tol=1e-6):
                    return False
            elif x != y:
                return False
    return True


def _rows(answer: dict) -> str:
    rows = answer.get('rows') or []
    return f'{rows[:3]}{" …" if len(rows) > 3 else ""}'


def _short(error: str) -> str:
    return error.splitlines()[0][:300]


def _sql(check: Check, _folder: Path, answers: list[dict], _mission: Mission) -> Outcome:
    actual = answers[0]
    if actual.get('error'):
        return False, f'The check query failed: {_short(actual["error"])}'
    expected = check.expected
    if check.expected_query:
        if answers[1].get('error'):
            return False, f'The reference query failed: {_short(answers[1]["error"])}'
        expected = answers[1]['rows']
    if _same(actual['rows'], expected or []):
        return True, 'As expected.'
    return False, f'Found: {_rows(actual)}'


def _pruning(check: Check, folder: Path, answers: list[dict], _mission: Mission) -> Outcome:
    if not (folder / check.file).is_file():
        return False, f'{check.file} is missing.'
    result, plan, expected = answers
    if result.get('error'):
        return False, f'{check.file} failed: {_short(result["error"])}'
    if expected.get('error'):
        return False, f'The reference query failed: {_short(expected["error"])}'
    if not _same(result['rows'], expected['rows']):
        return False, f'{check.file} returns {_rows(result)}'
    if plan.get('error'):
        return False, f'EXPLAIN ANALYZE failed: {_short(plan["error"])}'
    read = plan.get('files_read')
    if read is None:
        return False, 'DuckDB\'s plan shows no Parquet scan: query the partitioned files.'
    if read > check.max_files_read:
        return False, f'Right result, but DuckDB read {read} files (EXPLAIN ANALYZE, "Total Files Read").'
    return True, f'DuckDB read {read} file(s) (EXPLAIN ANALYZE, "Total Files Read").'


def _snapshots(check: Check, _folder: Path, answers: list[dict], mission: Mission) -> Outcome:
    errors = [a['error'] for a in answers[:3] if a.get('error')]
    if errors:
        return False, f'Could not read the lake: {_short(errors[0])}'
    total = int(answers[0]['rows'][0][0])
    created = int(answers[1]['rows'][0][0])
    new = total - mission.fixture.snapshots
    if check.not_recreated and created != 1:
        return False, f'{check.table} was created {created} times: dropping or replacing a table starts a new history.'
    for n, answer in zip(check.readable, answers[3:]):
        if answer.get('error'):
            return False, f'Snapshot {n} of {check.table} can no longer be read: {_short(answer["error"])}'
    if check.min_new is not None and new < check.min_new:
        return False, f'{new} new snapshot(s) since the ticket.'
    if check.max_new is not None and new > check.max_new:
        return False, f'{new} new snapshots since the ticket (each autocommitted statement is one).'
    return True, f'{new} new snapshot(s); history intact.'


CHECKS = {'layout': _layout, 'files': _files, 'untouched': _untouched, 'parquet_columns': _parquet_columns,
          'sql': _sql, 'pruning': _pruning, 'snapshots': _snapshots}


def evaluate(mission: Mission, folder: Path, answers: list[dict]) -> dict:
    """Run every check; `answers` holds the probes of probe_queries() in the same order."""
    position = 0
    criteria = []
    for criterion in mission.acceptance:
        results = []
        for check in criterion.checks:
            count = len(_queries(check, folder))
            mine = answers[position:position + count]
            position += count
            try:
                passed, detail = CHECKS[check.kind](check, folder, mine, mission)
            except Exception as error:  # a broken file is a failed check, not an outage
                passed, detail = False, f'Could not check: {error}'
            if not passed and check.fail:
                detail = f'{check.fail} {detail}'
            results.append({'kind': check.kind, 'passed': passed, 'detail': detail})
        criteria.append({'id': criterion.id, 'text': criterion.text, 'passed': all(r['passed'] for r in results),
                         'checks': results})
    passed = all(c['passed'] for c in criteria)
    return {'mission_id': mission.id, 'version': mission.version, 'status': 'passed' if passed else 'not-yet',
            'requires': [], 'criteria': criteria,
            'checked_at': datetime.now().astimezone().isoformat(timespec='seconds')}

