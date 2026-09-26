"""Runs the learner's ingestion file in the kernel worker (trusted local Python only) and gives it the bronze layer.

The code is real Python run as is: it calls the simulated API with requests or httpx over loopback. Its namespace
gets `API_BASE_URL`, `API_KEY` (the mission's fictitious key, never the runtime token: the worker's environment has
no token at all) and `bronze`, a small writer for the bronze layer of the local catalog with schema enforcement
(like a Delta table): a column the table does not have is refused unless the call passes `evolve=True`.
"""
from __future__ import annotations

import json
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from datapass_runtime.catalog import IDENT

MAX_ROWS = 10_000


def _sql_type(values: list[Any]) -> str:
    present = [v for v in values if v is not None]
    if present and all(isinstance(v, bool) for v in present):
        return 'BOOLEAN'
    if present and all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        return 'BIGINT'
    if present and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return 'DOUBLE'
    return 'VARCHAR'


def _value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return value


class Bronze:
    """`bronze.append / merge / overwrite / query / columns` over tables of the catalog's bronze layer."""

    def __init__(self, catalog, producer: str):
        self._catalog = catalog
        self._producer = producer
        self.written: dict[str, int] = {}

    def _name(self, table: str) -> str:
        if not isinstance(table, str) or not IDENT.fullmatch(table):
            raise ValueError(f'bronze table names are simple identifiers, e.g. "api_orders" (got {table!r})')
        return f'bronze.{table}'

    def _rows(self, rows) -> list[dict]:
        rows = list(rows)
        if len(rows) > MAX_ROWS:
            raise ValueError(f'one call writes at most {MAX_ROWS} rows')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('rows are dicts (one per record)')
            for column in row:
                if not isinstance(column, str) or not IDENT.fullmatch(column):
                    raise ValueError(f'column names are simple identifiers (got {column!r})')
        return rows

    def columns(self, table: str) -> list[str]:
        """The table's columns, or [] when it does not exist yet."""
        name = self._name(table)
        if not self._catalog.exists(name):
            return []
        return [c[0] for c in self._catalog.db.execute(f'SELECT * FROM {name} LIMIT 0').description]

    def query(self, sql: str) -> list[dict]:
        """A read-only query on the catalog (for example your watermark: SELECT max(updated_at) ...)."""
        result = self._catalog.query(sql)
        if result['truncated']:
            raise ValueError('the query result was truncated; aggregate it in SQL')
        return result['rows']

    def _prepare(self, name: str, rows: list[dict], evolve: bool) -> list[str]:
        db = self._catalog.db
        incoming: list[str] = []
        for row in rows:
            for column in row:
                if column not in incoming:
                    incoming.append(column)
        if not self._catalog.exists(name):
            if not incoming:
                raise ValueError(f'{name} does not exist yet and the rows have no columns')
            columns = ', '.join(f'"{c}" {_sql_type([r.get(c) for r in rows])}' for c in incoming)
            db.execute(f'CREATE TABLE {name} ({columns})')
            return incoming
        existing = [c[0] for c in db.execute(f'SELECT * FROM {name} LIMIT 0').description]
        new = [c for c in incoming if c not in existing]
        if new and not evolve:
            raise ValueError(
                f'schema enforcement: {name} has no column {", ".join(new)}. Map the field to an existing column, '
                'or pass evolve=True to add it (existing rows get NULL).')
        for column in new:
            db.execute(f'ALTER TABLE {name} ADD COLUMN "{column}" {_sql_type([r.get(column) for r in rows])}')
        return existing + new

    def _insert(self, name: str, columns: list[str], rows: list[dict]) -> None:
        if not rows:
            return
        placeholders = ', '.join('?' for _ in columns)
        quoted = ', '.join(f'"{c}"' for c in columns)
        self._catalog.db.executemany(f'INSERT INTO {name} ({quoted}) VALUES ({placeholders})',
                                     [tuple(_value(row.get(c)) for c in columns) for row in rows])

    def _write(self, table: str, rows, evolve: bool, action) -> int:
        name = self._name(table)
        rows = self._rows(rows)
        db = self._catalog.db
        db.execute('BEGIN TRANSACTION')
        try:
            # No rows (nothing changed since the watermark): the table stays as it is.
            if rows:
                action(name, self._prepare(name, rows, evolve), rows)
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        if self._catalog.exists(name):
            self._catalog._touch(name, [], self._producer)
        self.written[name] = self.written.get(name, 0) + len(rows)
        return len(rows)

    def append(self, table: str, rows, evolve: bool = False) -> int:
        """Insert the rows as they are (duplicates stay duplicates)."""
        return self._write(table, rows, evolve, self._insert)

    def overwrite(self, table: str, rows) -> int:
        """Replace the whole table with these rows (its schema too)."""
        name = self._name(table)
        if self._catalog.exists(name):
            self._catalog.db.execute(f'DROP TABLE {name}')
        return self._write(table, rows, True, self._insert)

    def merge(self, table: str, rows, key: str, evolve: bool = False) -> int:
        """Upsert on `key`: a row whose key is already in the table replaces it; within `rows`, the last one wins."""
        if not isinstance(key, str) or not IDENT.fullmatch(key):
            raise ValueError('merge needs the key column name, e.g. key="order_id"')
        latest: dict[Any, dict] = {}
        for row in self._rows(rows):
            if row.get(key) is None:
                raise ValueError(f'every merged row needs a value for the key {key!r}')
            latest[row[key]] = row
        unique = list(latest.values())

        def action(name: str, columns: list[str], batch: list[dict]) -> None:
            if key not in columns:
                raise ValueError(f'{name} has no key column {key!r}')
            keys = [_value(row[key]) for row in batch]
            for start in range(0, len(keys), 500):
                part = keys[start:start + 500]
                self._catalog.db.execute(f'DELETE FROM {name} WHERE "{key}" IN ({", ".join("?" for _ in part)})', part)
            self._insert(name, columns, batch)

        return self._write(table, unique, evolve, action)


class _Bounded:
    def __init__(self, limit: int = 20_000):
        self.parts: list[str] = []
        self.size = 0
        self.limit = limit

    def write(self, text: str) -> int:
        if self.size < self.limit:
            self.parts.append(text[: self.limit - self.size])
            self.size += len(text)
        return len(text)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        text = ''.join(self.parts)
        return text + ('\n… output truncated' if self.size > self.limit else '')


def run(engine, request: dict) -> dict:
    """Kernel op `apilab_run`: {mission_id, code, api_base_url, api_key}."""
    if not engine.trusted_python:
        raise ValueError('Trusted local Python is off. The API Lab runs your ingestion code as real local Python: '
                         'enable trusted Python in the Workbench first (only for code you trust).')
    if engine.catalog.kind == 'sqlite':
        raise ValueError('The API Lab needs the DuckDB catalog.')
    bronze = Bronze(engine.catalog, f"apilab:{request['mission_id']}")
    namespace = {'__name__': '__main__', 'API_BASE_URL': request['api_base_url'], 'API_KEY': request['api_key'],
                 'bronze': bronze}
    output = _Bounded()
    status, error = 'ok', None
    try:
        code = compile(request['code'], 'ingest.py', 'exec')
        # Deliberate trusted code execution inside the worker (never the API process), like Mosaic Python.
        with redirect_stdout(output), redirect_stderr(output):
            exec(code, namespace, namespace)
    except SystemExit as stop:
        if stop.code not in (None, 0):
            status, error = 'error', f'SystemExit({stop.code!r})'
    except BaseException:  # the learner's exception is the run's result, not an outage
        status = 'error'
        lines = traceback.format_exc().splitlines()
        # Keep the learner's frames: drop the runner's own first frame.
        error = '\n'.join(line for line in lines if 'apilab' + '/runner.py' not in line.replace('\\', '/'))[-4000:]
    tables = []
    for name in sorted(bronze.written):
        if engine.catalog.exists(name):
            count = engine.catalog.query(f'SELECT count(*) AS n FROM {name}')['rows'][0]['n']
            tables.append({'name': name, 'rows': count, 'written': bronze.written[name]})
    return {'status': status, 'error': error, 'stdout': output.getvalue(), 'tables': tables}
