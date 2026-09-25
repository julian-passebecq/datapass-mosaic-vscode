"""SQL dialects translated to DuckDB for a documented subset: one translator for the whole Workbench.

Used by Mosaic's Run/Explain active SQL (the `-- dialect: <name>` header), Practice (`snowflake` exercises) and the
Cloud Lab SQL pool (T-SQL expressions and queries). Each result is labelled "<dialect> dialect translated to DuckDB,
not <engine>": it runs on the local DuckDB catalog, never on the real engine. See README.md.
"""
from __future__ import annotations

from typing import Any

from .bigquery import BigQuery, BigQueryDialectError
from .core import DialectError, Hooks, Translation, translate_expression_with, translate_with
from .postgres import Postgres, PostgresDialectError
from .snowflake import Snowflake, SnowflakeDialectError
from .spark import Spark, SparkDialectError
from .tsql import Tsql, TsqlDialectError

DIALECTS = {dialect.id: dialect for dialect in (Tsql(), Snowflake(), BigQuery(), Spark(), Postgres())}
TITLES = {'tsql': 'T-SQL', 'snowflake': 'Snowflake', 'bigquery': 'BigQuery', 'spark': 'Spark SQL',
          'postgres': 'PostgreSQL'}

__all__ = ['DIALECTS', 'TITLES', 'DialectError', 'Hooks', 'Translation', 'translate', 'translate_expression',
           'dialects', 'BigQueryDialectError', 'PostgresDialectError', 'SnowflakeDialectError', 'SparkDialectError',
           'TsqlDialectError']


def _dialect(name: str):
    try:
        return DIALECTS[name]
    except KeyError:
        raise DialectError(f"Unknown SQL dialect '{name}'. Supported: duckdb, {', '.join(DIALECTS)}.") from None


def translate(source: str, dialect: str = 'snowflake', *, mode: str = 'query', schema: dict[str, Any] | None = None,
              hooks: Hooks | None = None) -> Translation:
    """Translate `source` from `dialect` to DuckDB SQL, or raise the dialect's DialectError."""
    return translate_with(_dialect(dialect), source, mode=mode, schema=schema, hooks=hooks)


def translate_expression(source: str, dialect: str, *, schema: dict[str, Any] | None = None,
                         hooks: Hooks | None = None) -> Translation:
    return translate_expression_with(_dialect(dialect), source, schema=schema, hooks=hooks)


def dialects() -> list[dict[str, str]]:
    """The dialects a client can offer (Mosaic's status bar picker)."""
    return [{'id': key, 'title': TITLES[key], 'label': dialect.label} for key, dialect in DIALECTS.items()]
