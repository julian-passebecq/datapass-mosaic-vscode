"""Notebook helpers SparkLab understands, so Fabric, Synapse and Databricks notebooks can run in a pipeline.

A pipeline notebook runs statement by statement on the same whitelisted AST
interpreter as SparkLab cells (nothing is eval'd or exec'd). A notebook runtime,
supplied by the local Workbench runtime, performs the side effects on the local
catalog as they are reached:

- `df.write.mode(...).saveAsTable("silver.orders")`: Spark's default save mode is
  errorifexists, so writing an existing table without mode('overwrite') or
  mode('append') fails, as in Spark; mode('ignore') leaves it untouched.
- `spark.sql("...")`: a SELECT becomes a DataFrame; any other statement runs at once.
- `df.count()`: an action, computed on the catalog.
- `notebookutils.notebook.exit(v)` (Fabric), `mssparkutils.notebook.exit(v)`
  (Synapse, older Fabric) and `dbutils.notebook.exit(v)` (Databricks) end the
  notebook; the pipeline activity output carries `v` as text.
- `dbutils.widgets.text/dropdown(name, default, ...)` declare a Databricks
  parameter; `dbutils.widgets.get(name)` reads the value the pipeline passed
  (baseParameters) or the default.
- `display(df)` shows a DataFrame and `print(...)` does nothing: output is not captured.

Fabric and Synapse pass pipeline parameters by injecting assignments right after
the cell marked as the parameters cell; without one, they are injected at the top
of the notebook, where later assignments silently overwrite them.
"""
from __future__ import annotations

import re
from typing import Any, Protocol

SAVE_MODES = {'overwrite', 'append', 'errorifexists', 'error', 'ignore'}

# Cell markers of the notebook source formats: Fabric git (.py), Databricks source, percent format.
_CELL_MARKER = re.compile(r'^#\s*(?:(?:PARAMETERS\s+)?CELL|MARKDOWN)\s+\*{3,}|^#\s*COMMAND\s+-{3,}|^#\s*%%')
_PARAMETERS_MARKER = re.compile(r'^#\s*PARAMETERS\s+CELL\b|^#\s*%%.*(?:\[parameters\]|tags\s*=\s*\[[^\]]*["\']parameters["\'])', re.I)


class NotebookRuntime(Protocol):
    def table_name(self, name: str) -> str: ...
    def columns(self, sql: str) -> list[str]: ...
    def count(self, dataframe: Any) -> int: ...
    def statement(self, sql: str) -> None: ...
    def save_as_table(self, dataframe: Any, table: str, mode: str, partition_by: tuple[str, ...]) -> str: ...


class NotebookExit(Exception):
    def __init__(self, value: Any):
        super().__init__('notebook exit')
        self.value = value


def parameters_cell_end(source: str) -> int | None:
    """First line after the parameters cell, or None when the notebook has no parameters cell."""
    lines = source.splitlines()
    start = None
    for number, line in enumerate(lines, 1):
        if start is not None and _CELL_MARKER.match(line):
            return number
        if start is None and _PARAMETERS_MARKER.match(line):
            start = number
    return None if start is None else len(lines) + 1


def exit_text(value: Any) -> str | None:
    """Exit values reach the pipeline as text, as str() renders them."""
    return None if value is None else value if isinstance(value, str) else str(value)


class DataFrameWriter:
    def __init__(self, dataframe: Any, mode: str = 'errorifexists', partition_by: tuple[str, ...] = ()):
        self.dataframe = dataframe
        self._mode = mode
        self._partition_by = partition_by

    def mode(self, mode: str) -> 'DataFrameWriter':
        if not isinstance(mode, str) or mode.lower() not in SAVE_MODES:
            raise ValueError(f"Save mode must be one of {', '.join(sorted(SAVE_MODES))}")
        return DataFrameWriter(self.dataframe, mode.lower(), self._partition_by)

    def format(self, name: str) -> 'DataFrameWriter':
        if not isinstance(name, str) or name.lower() not in {'delta', 'parquet'}:
            raise ValueError("Lakehouse tables are Delta tables here: use format('delta') or leave it out")
        return self

    def option(self, key: str, value: Any) -> 'DataFrameWriter':
        return self

    def partitionBy(self, *columns: str) -> 'DataFrameWriter':
        if len(columns) == 1 and isinstance(columns[0], (list, tuple)):
            columns = tuple(columns[0])
        if not columns or not all(isinstance(c, str) for c in columns):
            raise ValueError('partitionBy takes column names')
        return DataFrameWriter(self.dataframe, self._mode, tuple(columns))

    def saveAsTable(self, name: str) -> None:
        runtime = self.dataframe.session.notebook_runtime
        if runtime is None:
            raise ValueError('saveAsTable runs when the notebook runs in a pipeline; in SparkLab cells, use Publish')
        if not isinstance(name, str) or not name:
            raise ValueError('saveAsTable needs a table name such as silver.orders')
        mode = 'errorifexists' if self._mode == 'error' else self._mode
        runtime.save_as_table(self.dataframe, name, mode, self._partition_by)


class _NotebookApi:
    def exit(self, value: Any = None) -> None:
        raise NotebookExit(exit_text(value))

    def run(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError('notebook.run is not simulated; chain notebooks with pipeline activities')


class NotebookUtils:
    """notebookutils (Fabric) and mssparkutils (Synapse, older Fabric)."""

    def __init__(self) -> None:
        self.notebook = _NotebookApi()


class _Widgets:
    def __init__(self, parameters: dict[str, Any]):
        self.parameters = parameters
        self.defaults: dict[str, Any] = {}

    def text(self, name: str, defaultValue: Any = '', label: str | None = None) -> None:
        self.defaults[name] = defaultValue

    def dropdown(self, name: str, defaultValue: Any, choices: Any = None, label: str | None = None) -> None:
        self.defaults[name] = defaultValue

    def get(self, name: str) -> Any:
        if name in self.parameters:
            return exit_text(self.parameters[name])  # widget values are always text
        if name in self.defaults:
            return exit_text(self.defaults[name])
        raise ValueError(f"InputWidgetNotDefined: no input widget named {name} is defined "
                         "(declare it with dbutils.widgets.text or pass it in baseParameters)")


class DbUtils:
    def __init__(self, parameters: dict[str, Any]):
        self.widgets = _Widgets(parameters)
        self.notebook = _NotebookApi()


def no_op(*args: Any, **kwargs: Any) -> None:
    return None
