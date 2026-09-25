"""Factory Lab data plane: a pipeline's local activities run on the shared catalog.

The Factory engine (runtime/factorylab) orchestrates; this adapter lets Copy,
Lookup, Script, stored procedure and notebook activities act on the learner's
local lakehouse layers. Notebooks run on SparkLab's whitelisted AST interpreter
(never eval/exec), and their table writes, spark.sql statements and count()
actions execute here as they are reached. Nothing reaches Microsoft Fabric,
Azure or Databricks.

Lab files come from the host with every request, keyed by reference:
- pipelines: invoked child pipelines, by name;
- datasets: Azure Data Factory / Synapse datasets, by name;
- procedures: `<schema>.<name>` (unqualified names resolve to dbo, as in SQL Server);
- notebooks: `fabric:<name>`, `synapse:<name>` or `databricks:/Workspace/path`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from factorylab.lab import factory_view
from sparklab.safe_parser import SafeSparkParser, SparkLabSyntaxError
from sparklab.sparklab import SparkSession

from .catalog import ASSET, Catalog, sql_tokens

SPARK_HOME = Path(__file__).resolve().parents[1] / 'sparklab'
NOTEBOOK_HOMES = {
    'fabric': 'factory/fabric/<name>.Notebook/notebook-content.py',
    'synapse': 'factory/synapse/notebook/<name>.py',
    'databricks': 'factory/databricks/<path>.py',
}
_WRITTEN = re.compile(r'\b(?:TABLE(?:\s+IF\s+NOT\s+EXISTS)?|INTO|UPDATE|DELETE\s+FROM)\s+'
                      r'((?:bronze|silver|gold|warehouse|features|metrics)\.[A-Za-z][A-Za-z0-9_]*)', re.I)


class CatalogNotebookRuntime:
    """Side effects of one pipeline notebook run, applied to the catalog in statement order."""

    def __init__(self, catalog: Catalog, producer: str):
        self.catalog = catalog
        self.producer = producer
        self.written: list[str] = []
        self.notes: list[str] = []

    def table_name(self, name: str) -> str:
        parts = name.split('.')
        if len(parts) == 3:  # lakehouse.schema.table (Fabric) or catalog.schema.table (Unity Catalog)
            self._note(f"'{parts[0]}.' ignored: the lab has one local lakehouse / catalog")
            return '.'.join(parts[1:])
        return name

    def columns(self, sql: str) -> list[str]:
        return self.catalog.query(f"SELECT * FROM ({sql}) AS notebook_source LIMIT 0")['columns']

    def count(self, dataframe: Any) -> int:
        return int(self.catalog.query(f"SELECT COUNT(*) AS n FROM ({dataframe.sql}) AS notebook_count")['rows'][0]['n'])

    def statement(self, sql: str) -> None:
        self.catalog.execute(sql, self.producer)
        for match in _WRITTEN.finditer(sql_tokens(sql)):
            self._written(match.group(1).lower())

    def save_as_table(self, dataframe: Any, table: str, mode: str, partition_by: tuple[str, ...]) -> str:
        name = self.table_name(table)
        if name.lower().startswith('source.'):
            raise ValueError('The source layer is read-only; write to bronze, silver, gold or warehouse')
        if not ASSET.fullmatch(name):
            raise ValueError(f"saveAsTable('{table}'): name a lab table as layer.table, for example silver.orders "
                             "(layers: bronze, silver, gold, warehouse, features, metrics)")
        exists = self.catalog.exists(name)
        if exists and mode == 'errorifexists':
            raise ValueError(f"[TABLE_OR_VIEW_ALREADY_EXISTS] Cannot create table or view {name} because it already "
                             "exists; the default save mode is errorifexists: choose mode('overwrite') or "
                             "mode('append')")
        if exists and mode == 'ignore':
            self._note(f"{name} exists: mode('ignore') left it unchanged")
            return name
        if exists and mode == 'append':
            self.catalog.execute(f"INSERT INTO {name} BY NAME {dataframe.sql}", self.producer)
        else:
            self.catalog.execute(f"CREATE OR REPLACE TABLE {name} AS {dataframe.sql}", self.producer)
        if partition_by:
            self._note(f"{name}: partitionBy({', '.join(partition_by)}) recorded; the local table is not "
                       "physically partitioned")
        self._written(name)
        return name

    def _written(self, name: str) -> None:
        if name not in self.written:
            self.written.append(name)

    def _note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


class FactoryWorkspace:
    """The Workspace protocol of factorylab.engine over the shared catalog and the lab files."""

    def __init__(self, catalog: Catalog | None, files: dict[str, Any], local: bool = True):
        self.catalog = catalog
        # DuckDB SQL (CREATE OR REPLACE, INSERT BY NAME, MERGE) is required for local activities.
        self.local = bool(local and catalog is not None and catalog.kind != 'sqlite')
        self.pipelines = dict(files.get('pipelines') or {})
        self.datasets = dict(files.get('datasets') or {})
        self.procedures = {self._procedure_key(k): v for k, v in (files.get('procedures') or {}).items()}
        self.notebooks = dict(files.get('notebooks') or {})

    @staticmethod
    def _procedure_key(name: str) -> str:
        return name.replace('[', '').replace(']', '').strip().lower()

    def query(self, sql: str) -> dict[str, Any]:
        return self.catalog.query(sql)

    def execute(self, sql: str, producer: str) -> dict[str, Any]:
        return self.catalog.execute(sql, producer)

    def table_exists(self, name: str) -> bool:
        try:
            return self.catalog.exists(name)
        except ValueError:
            return False

    def procedure_source(self, name: str) -> str | None:
        key = self._procedure_key(name)
        found = self.procedures.get(key)
        if found is None and '.' not in key:
            found = self.procedures.get(f'dbo.{key}')
        return found

    def run_notebook(self, kind: str, reference: str, parameters: dict[str, Any]) -> dict[str, Any] | None:
        source = self.notebooks.get(f'{kind}:{reference}')
        if source is None:
            available = sorted(k.split(':', 1)[1] for k in self.notebooks if k.startswith(f'{kind}:'))
            return {'status': 'error', 'error': (
                f"Notebook '{reference}' was not found in the lab ({NOTEBOOK_HOMES[kind]})"
                + (f"; available: {', '.join(available)}" if available else ''))}
        profile = json.loads((SPARK_HOME / 'profiles.json').read_text())['retail']
        session = SparkSession(profile)
        runtime = CatalogNotebookRuntime(self.catalog, f'notebook:{kind}:{reference}')
        session.notebook_runtime = runtime  # spark.table reads current columns from the catalog
        try:
            run = SafeSparkParser(session).run_notebook(source, parameters, kind)
        except SparkLabSyntaxError as exc:
            return {'status': 'error', 'error': str(exc), 'tables_written': runtime.written, 'notes': runtime.notes}
        notes = list(run.notes) + runtime.notes
        if kind != 'databricks' and parameters:
            where = 'after the parameters cell' if run.parameters_cell else 'at the top (no parameters cell)'
            notes.insert(0, f"parameters {', '.join(sorted(run.injected))} injected {where}")
        return {'status': 'success', 'exit_value': run.exit_value, 'exited': run.exited,
                'tables_written': runtime.written, 'notes': notes}

    def pipeline_document(self, name: str) -> Any | None:
        return self.pipelines.get(name)

    def dataset_document(self, name: str) -> Any | None:
        return self.datasets.get(name)


def simulate(catalog: Catalog, request: dict[str, Any]) -> dict[str, Any]:
    """Kernel op factory_simulate: validate, simulate and (for local activities) run a pipeline."""
    workspace = FactoryWorkspace(catalog, request.get('files') or {}, request.get('data_plane', 'local') == 'local')
    before = {name: meta.get('version') for name, meta in catalog.versions.items()}
    view = factory_view(request['document'], request['name'], request['flavor'], request.get('scenario') or {},
                        workspace)
    changed = [asset for asset in catalog.listing() if before.get(asset['name']) != asset.get('version')]
    view['data_plane'] = 'local' if workspace.local else 'simulated'
    view['tables_changed'] = [{'name': a['name'], 'rows': a['row_count'], 'producer': a.get('producer')}
                              for a in changed]
    return view
