"""Translated SQL dialects on the local catalog (runtime/sqldialects): Mosaic's `-- dialect:` files, Explain and
Practice. The translation is labelled "<dialect> dialect translated to DuckDB, not <engine>"; the DuckDB SQL it
produces goes through the same catalog validation as any other SQL and really runs on the local catalog."""
from __future__ import annotations

from typing import Any

DIALECT_IDS = ('tsql', 'snowflake', 'bigquery', 'spark', 'postgres')
# Practice languages written in a translated dialect: graded like `sql`, with truth semantic-emulation.
PRACTICE_DIALECTS = frozenset({'snowflake', 'tsql', 'bigquery', 'sparksql'})
# A Practice language whose id is not its dialect's id (`sparksql` next to the `sparklab` DataFrame language).
PRACTICE_DIALECT_OF = {'sparksql': 'spark'}


def catalog_types(catalog) -> dict[str, dict[str, dict[str, str]]]:
    """{schema: {table: {column: DuckDB type}}} of the catalog file, for the translator's type-aware rules."""
    rows = catalog.db.execute(
        "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_catalog = current_database() AND table_schema NOT IN ('information_schema', 'pg_catalog') "
        "ORDER BY table_schema, table_name, ordinal_position").fetchall()
    types: dict[str, dict[str, dict[str, str]]] = {}
    for schema, table, column, data_type in rows:
        types.setdefault(str(schema).lower(), {}).setdefault(str(table).lower(), {})[str(column).lower()] = str(data_type)
    return types


def translate_for_catalog(catalog, code: str, dialect: str, mode: str, schema: dict[str, Any] | None = None):
    """The dialect's SQL as DuckDB SQL; `schema` defaults to the catalog's own tables."""
    from sqldialects import translate
    if catalog.kind == 'sqlite':
        raise ValueError('Translated SQL dialects need the DuckDB catalog.')
    return translate(code, dialect, mode=mode, schema=catalog_types(catalog) if schema is None else schema)


def dialect_view(translation) -> dict[str, Any]:
    """What a client shows next to the result: the dialect, the label, the DuckDB SQL that ran and the rewrites."""
    return {'source': translation.dialect, 'target': 'duckdb', 'label': translation.label, 'sql': translation.sql,
            'rewrites': translation.rewrites}
