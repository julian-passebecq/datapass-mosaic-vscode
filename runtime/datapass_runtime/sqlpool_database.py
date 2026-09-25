"""SQL pool Lab data plane: the sqlpoollab Database protocol over the shared catalog.

Learner SQL arrives already translated by sqlpoollab and still goes through the
catalog's validation (statement allowlist, no file or network functions, external
access disabled). Only SQL the engine generates itself (sequences for IDENTITY,
renames, aggregate queries on validated table names) runs directly.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

from .catalog import ASSET, Catalog


class CatalogDatabase:
    def __init__(self, catalog: Catalog):
        if catalog.kind not in ('duckdb', 'ducklake'):
            raise RuntimeError('The SQL pool Lab needs DuckDB; the SQLite fallback cannot run it.')
        self.catalog = catalog
        self.kind = catalog.kind

    def query(self, sql: str) -> dict[str, Any]:
        return self.catalog.query(sql)

    def execute(self, sql: str, producer: str) -> dict[str, Any]:
        return self.catalog.execute(sql, producer)

    def fetch(self, sql: str) -> list[tuple[Any, ...]]:
        return self.catalog.db.execute(sql).fetchall()

    def generated(self, sql: str) -> None:
        self.catalog.db.execute(sql)

    def exists(self, name: str) -> bool:
        return bool(ASSET.fullmatch(name)) and self.catalog.exists(name)

    def columns(self, name: str) -> list[tuple[str, str]]:
        schema, table = name.split('.')
        return [(c, t) for c, t in self.catalog.db.execute(
            'SELECT column_name, data_type FROM information_schema.columns WHERE table_catalog = current_database() '
            'AND table_schema = ? AND lower(table_name) = ? ORDER BY ordinal_position', [schema, table]).fetchall()]

    def count(self, name: str) -> int:
        if not ASSET.fullmatch(name):
            raise ValueError(f"Not a lab table: {name}")
        return int(self.catalog.db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0])

    def serialize(self, select_sql: str) -> dict[str, Any]:
        return json.loads(self.catalog.db.execute('SELECT json_serialize_sql(?)', [select_sql]).fetchone()[0])

    def rename(self, old: str, new: str) -> None:
        if not (ASSET.fullmatch(old) and ASSET.fullmatch(new)) or old.split('.')[0] != new.split('.')[0]:
            raise ValueError('Renames stay within one lab schema')
        self.catalog.db.execute(f"ALTER TABLE {old} RENAME TO {new.split('.')[1]}")
        versions = self.catalog.versions
        if old in versions:
            versions[new] = versions.pop(old)
            self.catalog._save_versions()

    @contextmanager
    def session(self) -> Iterator[None]:
        """Unqualified table names resolve to the warehouse schema (the pool's dbo) during a run."""
        self.catalog.db.execute("SET search_path = 'warehouse,main'")
        try:
            yield
        finally:
            self.catalog.db.execute('RESET search_path')
