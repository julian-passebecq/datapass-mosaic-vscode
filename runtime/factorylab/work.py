"""Work activities: run locally when the lab workspace can resolve them, otherwise from the scenario.

Local resolution uses the shared catalog, whose schemas are the lab's lakehouse and
warehouse layers (source, bronze, silver, gold, warehouse, ...):

- Copy: the source query, or the source table named by Fabric datasetSettings or
  a Data Factory dataset (schema + table), is copied into the sink table.
  Overwrite (Fabric tableActionOption) replaces the table; Append / insert
  inserts (creating the table if needed); an ADF upsert (writeBehavior upsert
  with upsertSettings.keys) runs a MERGE; preCopyScript runs first.
- Lookup: the source query or table is read; firstRowOnly returns output.firstRow
  (absent when there are no rows) or output.count / output.value.
- Script: each script runs; Query scripts return result sets.
- Stored procedure: `factory/sql/procedures/<schema>.<name>.sql` in the lab
  folder. Its body is DuckDB SQL with T-SQL style @parameters; an optional
  `CREATE PROCEDURE name @p TYPE [= default] AS` header declares parameters and
  is checked like SQL Server does (missing / too many arguments). A procedure
  that does not exist fails the activity, as it would in the service.
- Notebooks (TridentNotebook, SynapseNotebook, DatabricksNotebook): the lab
  notebook with that reference runs on SparkLab, the bounded fake Spark; a
  missing notebook fails the activity.

A source or sink that is not a local table, and any other work activity, is
simulated: its output comes from the scenario. In a dry run (workspace not
local) every work activity is simulated.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .activities import TYPES

if TYPE_CHECKING:
    from .engine import Simulator
    from .model import Activity

LAYERS = ('source', 'bronze', 'silver', 'gold', 'warehouse', 'features', 'metrics')
_IDENT = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,62}$')
_PROC_HEADER = re.compile(r'^\s*CREATE\s+(?:OR\s+ALTER\s+)?PROC(?:EDURE)?\s+([\[\]\w.]+)(.*?)\bAS\b(.*)$', re.I | re.S)
_PROC_PARAM = re.compile(r'@(\w+)\s+([A-Za-z]+(?:\s*\([\d\s,]+\))?)(?:\s*=\s*(\'(?:\'\'|[^\'])*\'|[-\d.]+|NULL))?', re.I)
_LEADING_COMMENTS = re.compile(r'^(?:\s*--[^\n]*(?:\n|$)|\s*/\*.*?\*/)*', re.S)
_AT_NAME = re.compile(r"'(?:''|[^'])*'|--[^\n]*|@(\w+)")


def _bare(name: Any) -> str:
    return str(name or '').replace('[', '').replace(']', '').strip()


def local_table(schema: Any, table: Any) -> str | None:
    schema, table = _bare(schema).lower(), _bare(table)
    if schema in LAYERS and _IDENT.fullmatch(table or ''):
        return f"{schema}.{table}"
    return None


def _dataset_table(sim: 'Simulator', settings: Any, reference: Any) -> str | None:
    """Table named by Fabric inline datasetSettings, or by a Data Factory dataset reference."""
    if isinstance(settings, dict):
        props = settings.get('typeProperties') or {}
        found = local_table(props.get('schema'), props.get('table'))
        if found:
            return found
    if isinstance(reference, dict) and reference.get('referenceName') and sim.workspace is not None:
        document = sim.workspace.dataset_document(str(reference['referenceName']))
        if isinstance(document, dict):
            props = (document.get('properties') or document).get('typeProperties') or {}
            if props.get('tableName') and '.' in _bare(props['tableName']):
                schema, table = _bare(props['tableName']).split('.', 1)
                return local_table(schema, table)
            # SQL datasets name schema + table; Azure Databricks Delta Lake datasets name database + table.
            return local_table(props.get('schema') or props.get('database'), props.get('table'))
    return None


def _sql_literal(value: Any) -> str:
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _local(sim: 'Simulator') -> bool:
    return sim.workspace is not None and bool(getattr(sim.workspace, 'local', True))


def _fail(message: str, code: str = '2200') -> Exception:
    from .engine import ActivityFailure
    return ActivityFailure(message, code)


def _query(sim: 'Simulator', sql: str) -> dict[str, Any]:
    try:
        return sim.workspace.query(sql)
    except Exception as exc:  # the catalog reports SQL errors as exceptions
        raise _fail(f"Query failed: {exc}", '2011') from exc


def _execute(sim: 'Simulator', sql: str, producer: str) -> dict[str, Any]:
    try:
        return sim.workspace.execute(sql, producer)
    except Exception as exc:
        raise _fail(f"SQL failed: {exc}", '2011') from exc


def _copy(sim: 'Simulator', activity: 'Activity', props: dict[str, Any]) -> tuple[Any, str, str] | None:
    source, sink = props.get('source') or {}, props.get('sink') or {}
    inputs, outputs = props.get('_inputs') or [None], props.get('_outputs') or [None]
    query = source.get('sqlReaderQuery') or source.get('query')
    source_table = _dataset_table(sim, source.get('datasetSettings'), inputs[0])
    sink_table = _dataset_table(sim, sink.get('datasetSettings'), outputs[0])
    if not _local(sim) or not sink_table or not (query or source_table):
        return None
    select = str(query).strip().rstrip(';') if query else f"SELECT * FROM {source_table}"
    producer = f"pipeline:{sim.pipeline.name}/{activity.name}"
    if sink.get('preCopyScript'):
        _execute(sim, str(sink['preCopyScript']), producer)
    count = _query(sim, f"SELECT COUNT(*) AS n FROM ({select}) AS copy_source")['rows'][0]['n']
    mode = str(sink.get('tableActionOption') or sink.get('writeBehavior') or 'Append').lower()
    exists = sim.workspace.table_exists(sink_table)
    if mode == 'overwrite' or not exists:
        _execute(sim, f"CREATE OR REPLACE TABLE {sink_table} AS {select}", producer)
    elif mode == 'upsert':
        keys = ((sink.get('upsertSettings') or {}).get('keys') or [])
        if not keys or not all(_IDENT.fullmatch(str(k)) for k in keys):
            raise _fail("An upsert sink needs upsertSettings.keys (column names)")
        columns = _query(sim, f"SELECT * FROM ({select}) AS s LIMIT 0")['columns']
        on = ' AND '.join(f't."{k}" = s."{k}"' for k in keys)
        updates = ', '.join(f'"{c}" = s."{c}"' for c in columns if c not in keys) or f'"{keys[0]}" = s."{keys[0]}"'
        _execute(sim, f"MERGE INTO {sink_table} AS t USING ({select}) AS s ON {on} "
                      f"WHEN MATCHED THEN UPDATE SET {updates} WHEN NOT MATCHED THEN INSERT BY NAME", producer)
    else:
        _execute(sim, f"INSERT INTO {sink_table} BY NAME {select}", producer)
    output = {'rowsRead': count, 'rowsCopied': count, 'dataRead': count * 128, 'dataWritten': count * 128,
              'copyDuration': 0, 'effectiveIntegrationRuntime': 'DatapassLocal', 'sinkTable': sink_table,
              'writeMode': mode}
    return output, 'local', f"Copied {count} row(s) into {sink_table} on the local catalog ({mode})"


def _lookup(sim: 'Simulator', props: dict[str, Any]) -> tuple[Any, str, str] | None:
    source = props.get('source') or {}
    inputs = props.get('_inputs') or [None]
    query = source.get('sqlReaderQuery') or source.get('query')
    table = _dataset_table(sim, props.get('datasetSettings') or source.get('datasetSettings'), inputs[0])
    if not _local(sim) or not (query or table):
        return None
    result = _query(sim, str(query).strip().rstrip(';') if query else f"SELECT * FROM {table}")
    if result.get('truncated'):
        raise _fail("Lookup returned more than the lab limit of 200 rows (Data Factory's limit is 5,000 rows / 4 MB)")
    rows = result['rows']
    if props.get('firstRowOnly', True):
        output = {'firstRow': rows[0]} if rows else {}
        note = 'first row' if rows else 'no rows: output.firstRow is absent'
    else:
        output = {'count': len(rows), 'value': rows}
        note = f"{len(rows)} row(s)"
    return output, 'local', f"Lookup read the local catalog: {note}"


def _script(sim: 'Simulator', activity: 'Activity', props: dict[str, Any]) -> tuple[Any, str, str] | None:
    scripts = props.get('scripts') or []
    if not _local(sim):
        return None
    result_sets = []
    for script in scripts:
        text = str((script or {}).get('text') or '').strip()
        if not text:
            raise _fail("A script entry has no text")
        if str(script.get('type', 'Query')).lower() == 'query' and re.match(r'^\s*(select|with)\b', text, re.I):
            result = _query(sim, text)
            result_sets.append({'rowCount': len(result['rows']), 'rows': result['rows']})
        else:
            _execute(sim, text, f"pipeline:{sim.pipeline.name}/{activity.name}")
    return ({'resultSetCount': len(result_sets), 'resultSets': result_sets}, 'local',
            f"{len(scripts)} script(s) ran on the local catalog")


def _typed_parameter(value: Any, kind: str, procedure: str, parameter: str) -> Any:
    """Stored procedure parameters carry a type (Int32, Decimal, Boolean, String, ...); values arrive as text."""
    k = kind.lower()
    if value is None or k in {'', 'string', 'guid', 'datetime', 'datetimeoffset', 'timespan'}:
        return value
    try:
        if k in {'int16', 'int32', 'int64'}:
            if isinstance(value, bool):
                raise ValueError
            return int(value)
        if k in {'decimal', 'double', 'single'}:
            return float(value)
        if k == 'boolean':
            if isinstance(value, bool):
                return value
            if str(value).strip().lower() in {'true', 'false'}:
                return str(value).strip().lower() == 'true'
            raise ValueError
    except (TypeError, ValueError):
        raise _fail(f"Error converting data type for parameter @{parameter} of {procedure}: '{value}' is not "
                    f"{kind}", '2402') from None
    return value


def parse_procedure(source: str) -> tuple[list[tuple[str, str, str | None]] | None, str]:
    """(declared parameters or None, body). Parameters: (name, type, default literal)."""
    header = _LEADING_COMMENTS.sub('', source)
    match = _PROC_HEADER.match(header)
    if not match:
        return None, source
    params = [(m.group(1), m.group(2).upper(), m.group(3)) for m in _PROC_PARAM.finditer(match.group(2))]
    body = match.group(3).strip()
    body = re.sub(r'^\s*BEGIN\b', '', body, flags=re.I)
    body = re.sub(r'\bEND\s*;?\s*$', '', body, flags=re.I).strip()
    return params, body


def _procedure(sim: 'Simulator', activity: 'Activity', props: dict[str, Any]) -> tuple[Any, str, str] | None:
    name = _bare(props.get('storedProcedureName'))
    if not _local(sim) or not name:
        return None
    source = sim.workspace.procedure_source(name)
    if source is None:
        raise _fail(f"Could not find stored procedure '{name}' (lab procedures live in "
                    "factory/sql/procedures/<schema>.<name>.sql)", '2402')
    declared, body = parse_procedure(source)
    supplied: dict[str, Any] = {}
    for key, spec in (props.get('storedProcedureParameters') or {}).items():
        value = spec.get('value') if isinstance(spec, dict) else spec
        kind = str(spec.get('type') or '') if isinstance(spec, dict) else ''
        supplied[key.lstrip('@')] = _typed_parameter(value, kind, name, key.lstrip('@'))
    if declared is not None:
        names = {p[0].lower() for p in declared}
        extra = [k for k in supplied if k.lower() not in names]
        if extra:
            raise _fail(f"Procedure or function {name} has too many arguments specified (@{', @'.join(extra)})", '2402')
        for pname, _, default in declared:
            if not any(k.lower() == pname.lower() for k in supplied):
                if default is None:
                    raise _fail(f"Procedure or function '{name}' expects parameter '@{pname}', which was not supplied.",
                                '2402')
                supplied[pname] = None if default.upper() == 'NULL' else default.strip("'") if default.startswith("'") else float(default) if '.' in default else int(default)

    lookup = {k.lower(): v for k, v in supplied.items()}

    def substitute(match: re.Match[str]) -> str:
        if match.group(1) is None:
            return match.group(0)
        key = match.group(1).lower()
        if key not in lookup:
            raise _fail(f"Must declare the scalar variable \"@{match.group(1)}\" (not supplied to {name})", '2402')
        return _sql_literal(lookup[key])

    sql = _AT_NAME.sub(substitute, body)
    _execute(sim, sql, f"procedure:{name}")
    return {}, 'local', f"{name} ran as DuckDB SQL on the local catalog (T-SQL syntax is not emulated)"


NOTEBOOK_KINDS = {'TridentNotebook': 'fabric', 'SynapseNotebook': 'synapse', 'DatabricksNotebook': 'databricks'}


def _notebook(sim: 'Simulator', activity: 'Activity', props: dict[str, Any]) -> tuple[Any, str, str] | None:
    if not _local(sim):
        return None
    kind = NOTEBOOK_KINDS[activity.type]
    if kind == 'fabric':
        reference = props.get('notebookId')
        parameters = {k: (v.get('value') if isinstance(v, dict) else v) for k, v in (props.get('parameters') or {}).items()}
    elif kind == 'synapse':
        reference = (props.get('notebook') or {}).get('referenceName')
        parameters = {k: (v.get('value') if isinstance(v, dict) else v) for k, v in (props.get('parameters') or {}).items()}
    else:
        path = str(props.get('notebookPath') or '').strip()
        reference = '/' + path.strip('/') if path else ''
        parameters = dict(props.get('baseParameters') or {})
    if not reference:
        return None
    result = sim.workspace.run_notebook(kind, str(reference), parameters)
    if result is None:
        return None
    if result.get('status') != 'success':
        written = result.get('tables_written') or []
        raise _fail(f"Notebook {reference} failed on SparkLab: {result.get('error') or 'unknown error'}"
                    + (f" (already written: {', '.join(written)})" if written else ''), '6002')
    exit_value = result.get('exit_value')
    if kind == 'fabric':
        output = {'result': {'runId': sim.run_id, 'exitValue': exit_value, 'error': None}}
    elif kind == 'synapse':
        output = {'status': {'Output': {'result': {'exitValue': exit_value}}}}
    else:
        output = {'runOutput': exit_value, 'runPageUrl': f"datapass-lab://databricks/job/run/{sim.run_id[:8]}"}
    parts = [f"Notebook {reference} ran on SparkLab (fake Spark; results computed locally)"]
    written = result.get('tables_written') or []
    if written:
        parts.append(f"wrote {', '.join(written)}")
    parts.extend(result.get('notes') or [])
    return output, 'local', '; '.join(parts)


def run_work(sim: 'Simulator', activity: 'Activity', props: dict[str, Any]) -> tuple[Any, str, str]:
    kind = activity.type
    handled = None
    if kind == 'Copy':
        handled = _copy(sim, activity, props)
    elif kind == 'Lookup':
        handled = _lookup(sim, props)
    elif kind == 'Script':
        handled = _script(sim, activity, props)
    elif kind in {'SqlServerStoredProcedure', 'SqlPoolStoredProcedure'}:
        handled = _procedure(sim, activity, props)
    elif kind in {'TridentNotebook', 'SynapseNotebook', 'DatabricksNotebook'}:
        handled = _notebook(sim, activity, props)
    if handled is not None:
        return handled
    defaults: dict[str, Any] = {
        'Copy': {'rowsRead': 0, 'rowsCopied': 0, 'copyDuration': 0},
        'Lookup': {'firstRow': {}} if props.get('firstRowOnly', True) else {'count': 0, 'value': []},
        'GetMetadata': {'exists': True, 'itemName': 'lab-item', 'childItems': []},
        'WebActivity': {'Response': 'OK', 'ADFWebActivityResponseHeaders': {}},
        'TridentNotebook': {'result': {'exitValue': None}},
        'DatabricksNotebook': {'runOutput': None},
        'SynapseNotebook': {'status': {'Output': {'result': {'exitValue': None}}}},
    }
    return (dict(defaults.get(kind, {})), 'simulated',
            f"{TYPES[kind].label} simulated: output from the scenario, nothing reached an external service")
