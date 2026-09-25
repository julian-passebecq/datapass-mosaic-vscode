"""Practice exercises on the SQL pool Lab: the learner writes a T-SQL script, graded on an outcome table.

Each fixture scenario seeds tables in an isolated catalog (rows, types, the
design they already have and how many real rows they stand for), may run setup
T-SQL, runs the learner's script, may run T-SQL after it, and compares one
outcome table with the expected rows:

- designs: table, distribution, distribution_columns, index, index_columns,
  partition_column, partition_range, partitions, cluster_by;
- distribution: table, distribution, skew_pct, skew_over_10pct, max_share_pct,
  empty_distributions (the lab's distribution model, see physical.py);
- partitions: table, partition_number, rows, rows_per_distribution, columnstore_ok;
- partition_health: table, partitions, populated_partitions, min_rows_per_distribution
  (over populated partitions, at scale) and columnstore_ok (every populated partition);
- movement: operation, tables, columns (the data movement of the graded query's plan);
- scans: table, partitions_scanned, partitions_total;
- result: the graded query's rows; table: a table's rows;
- constraints: table, kind, columns, enforced.

The graded query is `query` (run after the script) or the script's last SELECT/EXPLAIN.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LAB_TABLE = re.compile(r'^(dbo|source|bronze|silver|gold|warehouse|features|metrics)\.[A-Za-z][A-Za-z0-9_]{0,62}$')
OUTCOME_COLUMNS: dict[str, list[str]] = {
    'designs': ['table', 'distribution', 'distribution_columns', 'index', 'index_columns', 'partition_column',
                'partition_range', 'partitions', 'cluster_by'],
    'distribution': ['table', 'distribution', 'skew_pct', 'skew_over_10pct', 'max_share_pct', 'empty_distributions'],
    'partitions': ['table', 'partition_number', 'rows', 'rows_per_distribution', 'columnstore_ok'],
    'partition_health': ['table', 'partitions', 'populated_partitions', 'min_rows_per_distribution',
                         'columnstore_ok'],
    'movement': ['operation', 'tables', 'columns'],
    'scans': ['table', 'partitions_scanned', 'partitions_total'],
    'constraints': ['table', 'kind', 'columns', 'enforced'],
}


class PoolTable(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(pattern=LAB_TABLE.pattern)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    columns: list[str] | None = None
    types: dict[str, str] = Field(default_factory=dict)
    # How many real rows the table stands for (the lab scales its row counts by represented / lab rows).
    represented_rows: float | None = Field(default=None, gt=0)
    # Table options it already has, as T-SQL: "DISTRIBUTION = HASH(customer_id), CLUSTERED COLUMNSTORE INDEX".
    design: str | None = None

    @model_validator(mode='after')
    def shaped(self) -> 'PoolTable':
        columns = self.columns or (list(self.rows[0]) if self.rows else [])
        if not columns:
            raise ValueError(f"{self.name}: an empty table needs columns")
        if any(list(row) != columns for row in self.rows):
            raise ValueError(f"{self.name}: every row needs the columns {columns} in that order")
        return self


class PoolScenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    flavor: Literal['synapse', 'fabric'] = 'synapse'
    now: datetime | None = None
    tables: list[PoolTable] = Field(default_factory=list, max_length=8)
    setup: str | None = None
    after: str | None = None
    query: str | None = None
    outcome: Literal['designs', 'distribution', 'partitions', 'partition_health', 'movement', 'scans', 'result',
                     'table', 'constraints'] = 'designs'
    only: list[str] = Field(default_factory=list)
    table: str | None = Field(default=None, pattern=LAB_TABLE.pattern)
    columns: list[str] | None = None

    @model_validator(mode='after')
    def consistent(self) -> 'PoolScenario':
        if (self.outcome == 'table') != (self.table is not None):
            raise ValueError("outcome 'table' needs table, and only it")
        if self.outcome in ('designs', 'distribution', 'partitions', 'partition_health', 'constraints') and not self.only:
            raise ValueError(f"outcome '{self.outcome}' needs the tables to report in only")
        if self.columns is not None and self.outcome in OUTCOME_COLUMNS:
            unknown = set(self.columns) - set(OUTCOME_COLUMNS[self.outcome])
            if unknown or not self.columns:
                raise ValueError(f"columns must come from {OUTCOME_COLUMNS[self.outcome]}")
        return self


def graded_columns(scenario: PoolScenario, rows: list[dict[str, Any]]) -> list[str]:
    if scenario.columns:
        return scenario.columns
    if scenario.outcome in OUTCOME_COLUMNS:
        return OUTCOME_COLUMNS[scenario.outcome]
    return list(rows[0]) if rows else []


def project(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    return [{c: row.get(c) for c in columns} for row in rows]
