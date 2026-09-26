"""The Lakehouse Lab's DuckDB child process: the learner's SQL, the pack's fixture SQL and the checker's probes.

It runs as `python -m lakehouselab.sandbox` with the mission folder as its working directory, reads one JSON request
on stdin and writes one JSON answer on stdout, so a runaway query is killed by a timeout and never holds the API.

The connection is bounded, not a security sandbox: DuckDB's own settings keep every file access inside the mission
folder (`allowed_directories` + `enable_external_access=false`, then `lock_configuration`), extensions are neither
installed nor loaded on demand, and statements that would change that (ATTACH, DETACH, INSTALL, LOAD, SET, PRAGMA,
EXPORT, COPY FROM DATABASE, PREPARE/EXECUTE) are refused before anything runs. DuckLake is attached by this module
only, from the folder's own `lake/` (metadata `lake/catalog.ducklake`, Parquet files under `lake/data/`).
"""
from __future__ import annotations

import json
import re
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

ROW_LIMIT = 50
REFUSED = {'ATTACH', 'DETACH', 'EXTENSION', 'LOAD', 'SET', 'VARIABLE_SET', 'PRAGMA', 'EXPORT', 'COPY_DATABASE',
           'PREPARE', 'EXECUTE', 'LOGICAL_PLAN', 'INVALID', 'MULTI'}
READ_ONLY = {'SELECT', 'EXPLAIN'}
FILES_READ = re.compile(r'Total Files Read:\s*(\d+)')
LAKE = 'lake'


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def connect(folder: Path, ducklake: bool, read_only: bool = False, delta: list[str] | None = None):
    import duckdb
    db = duckdb.connect(config={'autoinstall_known_extensions': False, 'autoload_known_extensions': False})
    db.execute("SET memory_limit='2GB'")
    if ducklake:
        try:
            db.execute('LOAD ducklake')
        except Exception as error:
            raise RuntimeError(
                'This mission needs the official DuckDB ducklake extension, which is not installed. Run '
                '"Datapass: Setup runtime" once with a network connection (it installs it), then try again. '
                f'({error})') from None
        lake = folder / 'lake'
        (lake / 'data').mkdir(parents=True, exist_ok=True)
        options = "DATA_PATH '" + _sql_path(lake / 'data') + "/', DATA_INLINING_ROW_LIMIT 0"
        if read_only:
            options += ', READ_ONLY'
        db.execute(f"ATTACH 'ducklake:{_sql_path(lake / 'catalog.ducklake')}' AS {LAKE} ({options})")
        db.execute(f'USE {LAKE}')
    if delta:
        try:
            db.execute('LOAD delta')
        except Exception as error:
            raise RuntimeError(
                'This mission needs the official DuckDB delta extension, which is not installed. Run '
                '"Datapass: Setup runtime" once with a network connection (it installs it), then try again. '
                f'({error})') from None
        for table in delta:
            if (folder / table / '_delta_log').is_dir():
                db.execute(f"ATTACH '{_sql_path(folder / table)}' AS {table.rsplit('/', 1)[-1]} (TYPE delta)")
    db.execute(f"SET allowed_directories=['{_sql_path(folder)}/']")
    db.execute('SET enable_external_access=false')
    db.execute('SET lock_configuration=true')
    return db


def split(db, text: str, allowed: set[str] | None = None) -> list[tuple[str, str]]:
    """The statements of a script as (type, sql); refuses the whole script when one statement is not allowed."""
    statements = []
    for statement in db.extract_statements(text):
        kind = str(statement.type).split('.')[-1]
        query = statement.query.strip()
        if kind in REFUSED or (allowed is not None and kind not in allowed):
            first = query.split(None, 1)[0].upper() if query else kind
            raise PermissionError(f'{first} is not allowed here: the lab attaches the lake and sets DuckDB up itself.')
        statements.append((kind, query))
    return statements


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _display(db, query: str) -> dict | None:
    """Run one statement; a statement that returns rows comes back as text cells (any type displays)."""
    relation = db.sql(query)
    if relation is None:
        return None
    names = relation.columns
    casts = ', '.join(f'CAST(#{i + 1} AS VARCHAR)' for i in range(len(names)))
    rows = relation.limit(ROW_LIMIT + 1).project(casts).fetchall() if names else []
    return {'columns': names, 'rows': [list(row) for row in rows[:ROW_LIMIT]], 'truncated': len(rows) > ROW_LIMIT}


def run_script(folder: Path, text: str, ducklake: bool, delta: list[str] | None = None) -> dict:
    """The learner's SQL file: every statement in order; the first error stops the script (like the DuckDB CLI)."""
    started = time.perf_counter()
    db = connect(folder, ducklake, delta=delta)
    try:
        statements = split(db, text)
        results = []
        for index, (kind, query) in enumerate(statements):
            try:
                shown = _display(db, query)
            except Exception as error:
                return {'statements': results, 'error': str(error), 'failed_statement': index + 1,
                        'elapsed_ms': round((time.perf_counter() - started) * 1000)}
            results.append({'type': kind, 'sql': query[:300], **(shown or {})})
        return {'statements': results, 'elapsed_ms': round((time.perf_counter() - started) * 1000)}
    finally:
        db.close()


def run_fixture(folder: Path, statements: list[str], ducklake: bool) -> dict:
    db = connect(folder, ducklake)
    try:
        for text in statements:
            for _kind, query in split(db, text):
                db.execute(query)
        snapshots = db.execute(f'SELECT count(*) FROM {LAKE}.snapshots()').fetchone()[0] if ducklake else 0
        return {'snapshots': int(snapshots)}
    finally:
        db.close()


def probe(folder: Path, ducklake: bool, queries: list[dict], delta: list[str] | None = None) -> dict:
    """The checker's read-only queries. `{latest}` in a query is the latest DuckLake snapshot id. A query with
    `analyze` runs under EXPLAIN ANALYZE and reports how many files DuckDB really read."""
    db = connect(folder, ducklake, read_only=True, delta=delta)
    try:
        latest = db.execute(f'SELECT max(snapshot_id) FROM {LAKE}.snapshots()').fetchone()[0] if ducklake else None
        answers = []
        for item in queries:
            query = str(item['sql']).replace('{latest}', str(latest))
            try:
                for statement in item.get('before') or []:
                    db.execute(str(statement))
                if item.get('script'):
                    statements = split(db, query, READ_ONLY)
                    if not statements:
                        raise ValueError('the file holds no query')
                    query = statements[-1][1]
                    split(db, query, {'SELECT'})
                if item.get('analyze'):
                    plan = '\n'.join(str(row[1]) for row in db.execute(f'EXPLAIN ANALYZE {query}').fetchall())
                    reads = [int(n) for n in FILES_READ.findall(plan)]
                    answers.append({'files_read': sum(reads) if reads else None, 'scans': len(reads)})
                    continue
                rows = db.execute(query).fetchmany(1001)
                answers.append({'rows': [[_cell(v) for v in row] for row in rows[:1000]], 'truncated': len(rows) > 1000})
            except Exception as error:
                answers.append({'error': str(error)})
        return {'answers': answers, 'latest': latest}
    finally:
        db.close()


def main() -> None:
    request = json.loads(sys.stdin.read())
    folder = Path.cwd()
    try:
        op = request['op']
        if op == 'run':
            answer = run_script(folder, request['sql'], bool(request.get('ducklake')), list(request.get('delta') or []))
        elif op == 'fixture':
            answer = run_fixture(folder, list(request['statements']), bool(request.get('ducklake')))
        elif op == 'probe':
            answer = probe(folder, bool(request.get('ducklake')), list(request['queries']), list(request.get('delta') or []))
        else:
            raise ValueError(f'unknown op {op}')
    except PermissionError as error:
        answer = {'error': str(error), 'refused': True}
    except Exception as error:
        answer = {'error': str(error)}
    sys.stdout.write(json.dumps(answer, default=str))


if __name__ == '__main__':
    main()
