"""The BI Lab panel: run the warehouse scripts, then describe the tables, their lineage and the star model checks."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .lineage import Lineage
from .model import StarModel, check_model
from .script import ScriptError, run_script

LAYERS = ('source', 'bronze', 'silver', 'gold', 'warehouse', 'features', 'metrics')
TRUTH = {
    'sql': 'real: the scripts run on the local DuckDB catalog',
    'lineage': 'static analysis of the SQL text (sqlglot, DuckDB dialect)',
    'model': 'real queries on the tables; the model file is Datapass\'s own format, not a Power BI file',
}


def catalog_schema(catalog) -> dict[str, list[dict[str, str]]]:
    """Columns and types of every table of the catalog's layers, in order."""
    rows = catalog.db.execute(
        'SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns '
        'WHERE table_catalog = current_database() ORDER BY table_schema, table_name, ordinal_position').fetchall()
    schema: dict[str, list[dict[str, str]]] = {}
    for layer, table, column, kind in rows:
        if layer in LAYERS:
            schema.setdefault(f'{layer}.{table}'.lower(), []).append({'name': column.lower(), 'type': str(kind)})
    return schema


def lab_view(catalog, scripts: list[dict[str, str]], model: dict[str, Any] | None, run: bool) -> dict[str, Any]:
    statements: list[dict[str, Any]] = []
    stopped = None
    if run:
        for script in scripts:
            try:
                results = run_script(catalog, script['text'], f"bi:{script['path']}")
            except ScriptError as error:
                stopped = {'path': script['path'], 'line': 1, 'message': str(error)}
                break
            statements += [{**r.view(), 'path': script['path']} for r in results]
            failed = next((r for r in results if r.status == 'error'), None)
            if failed:
                stopped = {'path': script['path'], 'line': failed.line, 'message': failed.message}
                break
    schema = catalog_schema(catalog)
    lineage = Lineage({name: [c['name'] for c in columns] for name, columns in schema.items()})
    for script in scripts:
        lineage.add_script(script['path'], script['text'])
    lineage_view = lineage.view()
    lineage_view['impact'] = {f"{c['table']}.{c['column']}": lineage.impact((c['table'], c['column']))
                              for c in lineage_view['columns']}
    for table in lineage_view['tables']:
        if table['kind'] == 'source':
            for column in table['columns']:
                lineage_view['impact'][f"{table['name']}.{column}"] = lineage.impact((table['name'], column))
    counts = {item['name']: item['row_count'] for item in catalog.listing()}
    tables = [{'name': name, 'layer': name.split('.')[0], 'rows': counts.get(name), 'columns': columns}
              for name, columns in sorted(schema.items())]
    model_view = None
    if model is not None:
        try:
            parsed = StarModel.model_validate(model)
        except ValidationError as error:
            model_view = {'error': _validation_message(error)}
        else:
            checked = check_model(catalog, parsed)
            model_view = {'name': parsed.name, 'description': parsed.description,
                          'tables': [t.model_dump() for t in parsed.tables],
                          'relationships': [r.model_dump(by_alias=True) for r in parsed.relationships],
                          'checks': checked['checks'], 'profiles': checked['relationships']}
    return {'status': 'error' if stopped else 'ok', 'ran': run, 'stopped': stopped, 'statements': statements,
            'tables': tables, 'lineage': lineage_view, 'model': model_view, 'truth': TRUTH}


def _validation_message(error: ValidationError) -> str:
    parts = []
    for item in error.errors()[:5]:
        where = '.'.join(str(p) for p in item['loc'])
        parts.append(f"{where}: {item['msg']}" if where else item['msg'])
    return '; '.join(parts)
