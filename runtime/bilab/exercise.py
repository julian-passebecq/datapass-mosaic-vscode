"""Practice exercises on the BI Lab warehouse, graded on an isolated DuckDB catalog.

Two languages share this scenario model:

- `warehouse`: the learner writes a DuckDB SQL script (dimensions, facts, SCD loads, MERGE ...);
- `bi-model`: the learner writes the star model file (tables, keys, relationships) for given tables.

A scenario seeds `tables`, runs `setup` SQL, then runs the learner's script once per entry of `runs` (each run
can first replace some tables: the next day's change batch), then `after` SQL, and compares one outcome:

- result: the rows of `query` (or of the script's last SELECT);
- table: the rows of `table`;
- checks: the star model checks (check, subject, status, detail) of `model` or of the learner's model;
- relationships: the model's relationships with what the data shows (bi-model);
- lineage: one row per (table, column, source) for the tables (layer.table) or columns (layer.table.column) in
  `lineage_of`, from the SQL text of the setup and the learner's script (`lineage_depth`: sources = the tables
  the statement reads; origins = back to tables no analyzed statement builds, through the learner's own staging);
- impact: what a change to `impact_of` (layer.table.column) reaches (table, column, effect).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .model import CHECK_COLUMNS, COLUMN_REF, RELATIONSHIP_COLUMNS, TABLE, StarModel

OUTCOME_COLUMNS: dict[str, list[str]] = {
    'checks': ['check', 'subject', 'status'],
    'relationships': RELATIONSHIP_COLUMNS,
    'lineage': ['table', 'column', 'source', 'transform'],
    'impact': ['table', 'column', 'effect'],
}
ALL_COLUMNS: dict[str, list[str]] = {**OUTCOME_COLUMNS, 'checks': CHECK_COLUMNS}


class WarehouseTable(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(pattern=TABLE)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    columns: list[str] | None = None
    types: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def shaped(self) -> 'WarehouseTable':
        columns = self.columns or (list(self.rows[0]) if self.rows else [])
        if not columns:
            raise ValueError(f'{self.name}: an empty table needs columns')
        if any(list(row) != columns for row in self.rows):
            raise ValueError(f'{self.name}: every row needs the columns {columns} in that order')
        return self


class RunStep(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # Tables (re)created with these rows before this run of the learner's script, e.g. the day's change batch.
    tables: list[WarehouseTable] = Field(default_factory=list, max_length=4)


class WarehouseScenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tables: list[WarehouseTable] = Field(default_factory=list, max_length=10)
    setup: str | None = Field(default=None, max_length=40_000)
    runs: list[RunStep] = Field(default_factory=lambda: [RunStep()], min_length=1, max_length=3)
    after: str | None = Field(default=None, max_length=20_000)
    query: str | None = Field(default=None, max_length=20_000)
    model: dict[str, Any] | None = None
    outcome: Literal['result', 'table', 'checks', 'relationships', 'lineage', 'impact'] = 'result'
    table: str | None = Field(default=None, pattern=TABLE)
    only: list[str] = Field(default_factory=list)
    lineage_of: list[str] = Field(default_factory=list)
    lineage_depth: Literal['sources', 'origins'] = 'sources'
    impact_of: str | None = Field(default=None, pattern=COLUMN_REF.pattern)
    columns: list[str] | None = None

    @model_validator(mode='after')
    def consistent(self) -> 'WarehouseScenario':
        if (self.outcome == 'table') != (self.table is not None):
            raise ValueError("outcome 'table' needs table, and only it")
        if (self.outcome == 'lineage') != bool(self.lineage_of):
            raise ValueError("outcome 'lineage' needs lineage_of, and only it")
        if (self.outcome == 'impact') != (self.impact_of is not None):
            raise ValueError("outcome 'impact' needs impact_of, and only it")
        if self.model is not None:
            StarModel.model_validate(self.model)
        if self.columns is not None and self.outcome in ALL_COLUMNS:
            unknown = set(self.columns) - set(ALL_COLUMNS[self.outcome])
            if unknown or not self.columns:
                raise ValueError(f'columns must come from {ALL_COLUMNS[self.outcome]}')
        return self


def graded_columns(scenario: WarehouseScenario, rows: list[dict[str, Any]]) -> list[str]:
    if scenario.columns:
        return scenario.columns
    if scenario.outcome in OUTCOME_COLUMNS:
        return OUTCOME_COLUMNS[scenario.outcome]
    return list(rows[0]) if rows else []


def project(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    return [{c: row.get(c) for c in columns} for row in rows]
