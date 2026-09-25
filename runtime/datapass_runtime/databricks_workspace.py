"""Databricks Lab data plane: a job's notebook and SQL tasks run on the shared catalog, under Unity Catalog rules.

The engine (runtime/databrickslab) orchestrates and simulates compute. Here:
- notebook tasks run on SparkLab's whitelisted interpreter (never eval/exec) with
  dbutils widgets, task values and the lab's MLflow; table reads and writes go through
  Unity Catalog checks for the job's `run_as` principal;
- SQL tasks run their .sql file on DuckDB with named parameters (`:name`) and
  three-level names (`main.silver.orders`) mapped to the lab's layers;
- Unity Catalog ownership and the MLflow tracking/registry state persist in
  `databricks_state.json` next to the catalog.
Nothing reaches Azure Databricks.
"""
from __future__ import annotations

import json
import re
from typing import Any

from databrickslab.compute import ComputeCatalog, load_compute
from databrickslab.engine import JobScenario, design, simulate_job
from databrickslab.mlflow_store import MlflowStore, describe as describe_mlflow, empty_state
from databrickslab.model import DatabricksLabError
from databrickslab.unity import (CATALOG, LAB_USER, MODEL_SCHEMAS, TABLE_SCHEMAS, PermissionDenied, UnityCatalog,
                                 full_name, lab_table, load_unity)
from sparklab.safe_parser import SafeSparkParser, SparkLabSyntaxError
from sparklab.sparklab import SparkSession

from .catalog import ASSET, Catalog, references, sql_tokens, validate_sql
from .factory_workspace import SPARK_HOME, CatalogNotebookRuntime, _WRITTEN

STATE_FILE = 'databricks_state.json'
TRUTH = ('Simulated Azure Databricks: job orchestration, compute (clusters, serverless, SQL warehouses) and its cost '
         'are modelled; notebook and SQL tasks really run on the local catalog (SparkLab, DuckDB) under Unity '
         'Catalog rules. Nothing connects to Azure Databricks.')
_THREE_PART = re.compile(r'(?<![\w.])([A-Za-z_]\w*)\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)(?![\w(])')
# String literals and comments are left alone by name mapping and parameter binding.
_LITERAL = re.compile(r"'(?:''|[^'])*'|--[^\n]*|/\*[\s\S]*?\*/")
_PARAMETER = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def map_names(sql: str) -> str:
    """Three-level Unity Catalog names in SQL -> lab layer names (literals are left alone)."""
    def convert(segment: str) -> str:
        def replace(match: re.Match[str]) -> str:
            catalog, schema, table = match.groups()
            if schema.lower() not in TABLE_SCHEMAS:
                return match.group(0)
            return lab_table(f"{catalog}.{schema}.{table}")
        return _THREE_PART.sub(replace, segment)
    out, last = [], 0
    for literal in _LITERAL.finditer(sql):
        out.append(convert(sql[last:literal.start()]))
        out.append(literal.group(0))
        last = literal.end()
    out.append(convert(sql[last:]))
    return ''.join(out)


def bind_parameters(sql: str, parameters: dict[str, str]) -> str:
    """Named parameter markers (:name) become string literals, outside literals."""
    def convert(segment: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in parameters:
                raise ValueError(f"[UNBOUND_SQL_PARAMETER] Found the unbound parameter: {name}. Add it to the SQL "
                                 "task's parameters")
            return "'" + parameters[name].replace("'", "''") + "'"
        return _PARAMETER.sub(replace, segment)
    out, last = [], 0
    for literal in _LITERAL.finditer(sql):
        out.append(convert(sql[last:literal.start()]))
        out.append(literal.group(0))
        last = literal.end()
    out.append(convert(sql[last:]))
    return ''.join(out)


class DatabricksNotebookRuntime(CatalogNotebookRuntime):
    """Notebook side effects under Unity Catalog: every read and write is checked for the principal."""

    def __init__(self, catalog: Catalog, producer: str, unity: UnityCatalog, principal: str):
        super().__init__(catalog, producer)
        self.unity, self.principal = unity, principal

    def table_name(self, name: str) -> str:
        return lab_table(name)

    def check_read(self, name: str) -> None:
        self.unity.check_read(self.principal, name)

    def columns(self, sql: str) -> list[str]:
        mapped = map_names(sql)
        for table in references(mapped):
            self.unity.check_read(self.principal, table.lower())
        return super().columns(mapped)

    def statement(self, sql: str) -> None:
        mapped = map_names(sql)
        for table in references(mapped):
            self.unity.check_read(self.principal, table.lower())
        written = [m.group(1).lower() for m in _WRITTEN.finditer(sql_tokens(mapped))]
        for table in written:
            self.unity.check_write(self.principal, table, self.catalog.exists(table))
        existed = {t: self.catalog.exists(t) for t in written}
        super().statement(mapped)
        for table in written:
            if not existed[table]:
                self.unity.created(self.principal, table)

    def save_as_table(self, dataframe: Any, table: str, mode: str, partition_by: tuple[str, ...]) -> str:
        name = self.table_name(table)
        exists = ASSET.fullmatch(name) is not None and self.catalog.exists(name)
        if not (exists and mode in ('ignore', 'errorifexists')):
            self.unity.check_write(self.principal, name, exists)
        saved = super().save_as_table(dataframe, name, mode, partition_by)
        if not exists:
            self.unity.created(self.principal, saved)
        return saved


class DatabricksWorkspace:
    """The Workspace protocol of databrickslab.engine over the catalog and the lab files."""

    def __init__(self, catalog: Catalog | None, files: dict[str, Any], state: dict[str, Any], local: bool = True):
        self.catalog = catalog
        self.local = bool(local and catalog is not None and catalog.kind != 'sqlite')
        self.notebooks = dict(files.get('notebooks') or {})
        self.sql = dict(files.get('sql') or {})
        self.state = state
        tables = {a['name'] for a in catalog.listing()} if catalog is not None else set()
        self.unity = load_unity(files.get('unity_catalog'), files.get('grants'), state.get('owners', {}), tables,
                                set(state.get('mlflow', {}).get('models', {})))
        self.clock = None

    def run_notebook(self, key: str, parameters: dict[str, str], principal: str, task_values: Any,
                     context: dict[str, Any]) -> dict[str, Any]:
        source = self.notebooks.get(key)
        if source is None:
            available = sorted(k.split(':', 1)[1] for k in self.notebooks)
            return {'status': 'error', 'error_code': 'ResourceNotFound',
                    'error': f"Notebook {key.split(':', 1)[1]} was not found in factory/databricks/"
                             + (f" (notebooks: {', '.join(available)})" if available else '')}
        profile = json.loads((SPARK_HOME / 'profiles.json').read_text())['retail']
        session = SparkSession(profile)
        runtime = DatabricksNotebookRuntime(self.catalog, f"job:{context.get('job')}/{context.get('task')}",
                                            self.unity, principal)
        session.notebook_runtime = runtime
        mlflow = MlflowStore(self.state.setdefault('mlflow', empty_state()), self.unity, principal, self.clock,
                             context)
        try:
            run = SafeSparkParser(session).run_notebook(source, parameters, 'databricks', task_values, mlflow)
        except SparkLabSyntaxError as exc:
            message = str(exc)
            code = 'UnauthorizedError' if 'INSUFFICIENT_PERMISSIONS' in message else 'RunExecutionError'
            return {'status': 'error', 'error': message, 'error_code': code, 'tables_written': runtime.written,
                    'notes': runtime.notes}
        notes = list(run.notes) + [n for n in runtime.notes if 'ignored: the lab has one' not in n]
        if mlflow.touched:
            notes.append(f"MLflow: {len(mlflow.touched)} run(s) logged")
        return {'status': 'success', 'exit_value': run.exit_value, 'tables_written': runtime.written, 'notes': notes}

    def run_sql(self, key: str, parameters: dict[str, str], principal: str) -> dict[str, Any]:
        source = self.sql.get(key)
        if source is None:
            return {'status': 'error', 'error_code': 'ResourceNotFound',
                    'error': f"SQL file {key.split(':', 1)[1]} was not found in factory/databricks/"}
        written: list[str] = []
        try:
            text = map_names(bind_parameters(source, parameters))
            columns, rows = [], []
            for statement in validate_sql(text):
                for table in references(statement):
                    self.unity.check_read(principal, table.lower())
                targets = [m.group(1).lower() for m in _WRITTEN.finditer(sql_tokens(statement))]
                existed = {t: self.catalog.exists(t) for t in targets}
                for table in targets:
                    self.unity.check_write(principal, table, existed[table])
                if re.match(r'(?is)\s*(select|with)\b', sql_tokens(statement)):
                    result = self.catalog.query(statement)
                    columns, rows = result['columns'], result['rows']
                else:
                    self.catalog.execute(statement, f"job-sql:{key}")
                    for table in targets:
                        if not existed[table]:
                            self.unity.created(principal, table)
                        if table not in written:
                            written.append(table)
        except PermissionDenied as exc:
            return {'status': 'error', 'error': str(exc), 'error_code': 'UnauthorizedError', 'tables_written': written}
        except Exception as exc:  # DuckDB and validation errors are the task's error
            return {'status': 'error', 'error': str(exc).split('\n')[0], 'error_code': 'RunExecutionError',
                    'tables_written': written}
        return {'status': 'success', 'columns': columns, 'rows': rows, 'tables_written': written}


def load_state(catalog: Catalog) -> dict[str, Any]:
    path = catalog.directory / STATE_FILE
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    return {'owners': dict(data.get('owners') or {}), 'mlflow': data.get('mlflow') or empty_state()}


def save_state(catalog: Catalog, state: dict[str, Any], unity: UnityCatalog) -> None:
    state['owners'] = {k: v for k, v in unity.owners.items() if v != LAB_USER}
    (catalog.directory / STATE_FILE).write_text(json.dumps(state, indent=1, default=str), encoding='utf-8')


def unity_view(catalog: Catalog, unity: UnityCatalog, state: dict[str, Any]) -> dict[str, Any]:
    """Catalog Explorer: main > schemas > tables and models, with owners and grants."""
    listing = {a['name']: a for a in catalog.listing()}
    models = state.get('mlflow', {}).get('models', {})
    schemas = []
    for schema in MODEL_SCHEMAS:
        tables = [{'name': full_name(n), 'table': n, 'rows': a['row_count'], 'owner': unity.owner(full_name(n)),
                   'producer': a.get('producer')} for n, a in listing.items() if n.split('.')[0] == schema]
        schema_models = [{'name': m, 'owner': unity.owner(m), 'versions': len(e['versions']), 'aliases': e['aliases']}
                         for m, e in models.items() if m.split('.')[1] == schema]
        schemas.append({'name': f"{CATALOG}.{schema}", 'tables': tables, 'models': schema_models,
                        'read_only': schema == 'source'})
    return {**unity.describe(), 'schemas': schemas}


def run(catalog: Catalog, request: dict[str, Any]) -> dict[str, Any]:
    """Kernel op databricks_run: validate and simulate a job; its notebook and SQL tasks run on the catalog."""
    files = request.get('files') or {}
    compute = load_compute(files.get('compute'))
    state = load_state(catalog)
    workspace = DatabricksWorkspace(catalog, files, state, request.get('data_plane', 'local') == 'local')
    scenario = JobScenario.model_validate(request.get('scenario') or {})
    workspace.clock = scenario.now
    before = {name: meta.get('version') for name, meta in catalog.versions.items()}
    view: dict[str, Any] = {'truth': TRUTH, 'name': request.get('name'), 'data_plane':
                            'local' if workspace.local else 'simulated', 'compute_catalog': _compute_view(compute),
                            'warnings': list(compute.warnings) + list(workspace.unity.warnings), 'issues': []}
    try:
        job, result = simulate_job(request['document'], compute, scenario, workspace)
    except DatabricksLabError as exc:
        view.update(status='invalid', issues=exc.issues, job=None, run=None)
    else:
        view.update(status='simulated', job=design(job), run=result)
        view['warnings'] += job.warnings
        save_state(catalog, state, workspace.unity)
    changed = [a for a in catalog.listing() if before.get(a['name']) != a.get('version')]
    view['tables_changed'] = [{'name': a['name'], 'rows': a['row_count'], 'producer': a.get('producer')}
                              for a in changed]
    view['unity'] = unity_view(catalog, workspace.unity, state)
    view['mlflow'] = describe_mlflow(state.get('mlflow', {}))
    return view


def explore(catalog: Catalog, request: dict[str, Any]) -> dict[str, Any]:
    """Kernel op databricks_state: Unity Catalog and MLflow as they are, without running anything."""
    files = request.get('files') or {}
    state = load_state(catalog)
    workspace = DatabricksWorkspace(catalog, files, state, local=False)
    compute = load_compute(files.get('compute'))
    return {'truth': TRUTH, 'unity': unity_view(catalog, workspace.unity, state),
            'mlflow': describe_mlflow(state.get('mlflow', {})), 'compute_catalog': _compute_view(compute),
            'warnings': list(compute.warnings) + list(workspace.unity.warnings)}


def _compute_view(compute: ComputeCatalog) -> dict[str, Any]:
    return {'clusters': [{'cluster_id': c.cluster_id, 'name': c.name, 'node_type': c.node_type, 'workers': c.workers,
                          'autotermination_minutes': c.autotermination_minutes, 'running': c.running}
                         for c in compute.clusters.values()],
            'warehouses': [{'id': w.warehouse_id, 'name': w.name, 'size': w.size, 'serverless': w.serverless}
                           for w in compute.warehouses.values()]}

