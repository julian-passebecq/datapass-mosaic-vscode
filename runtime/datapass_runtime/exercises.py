"""Server-owned exercise registry and bounded result grading on the shared worker.

Only public definitions cross the API. These are internal demo fixtures, not
CodeDELeet content. SQL fixture CTEs do not mutate workspace catalog tables.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import uuid
import sqlite3
from importlib.metadata import version

from .catalog import validate_sql
from .content import content_root

def _registry():
    from .exercise_packs import PackRegistry
    registry = PackRegistry()
    root = content_root() / 'exercise-packs'
    for manifest in sorted(root.glob('*/manifest.json')):
        registry.load(manifest.parent)
    return registry


PACKS = _registry()


def definition(id):
    return PACKS.get(id)[0].model_dump(exclude_none=True)


def definitions():
    return PACKS.definitions()


def solution(id):
    spec, private = PACKS.get(id)
    return {'exercise_id': id, 'exercise_version': spec.version, 'source': private.solution}


def _fixture_sql(rows, columns, types=None):
    """Literal fixture relation. Declared data_context types (registry-allowlisted)
    are applied with CAST so dates, decimals and empty fixtures stay typed."""
    types = types or {}
    def literal(value):
        if value is None: return 'NULL'
        if isinstance(value, bool): return 'TRUE' if value else 'FALSE'
        if isinstance(value, float): return f'CAST({value!r} AS DOUBLE)'
        if isinstance(value, int): return str(value)
        return "'" + str(value).replace("'", "''") + "'"
    def identifier(name):
        return '"' + name.replace('"', '""') + '"'
    def typed(value, column):
        text = literal(value)
        return f'CAST({text} AS {types[column]})' if column in types else text
    if not rows:
        return 'SELECT ' + ', '.join(typed(None, c)+' AS '+identifier(c) for c in columns) + ' WHERE 1=0'
    return ' UNION ALL '.join('SELECT '+', '.join(typed(row.get(c), c)+' AS '+identifier(c) for c in columns) for row in rows)


def _fixture_ctes(spec, fixture):
    """One CTE per named fixture table (multi-table SQL exercises)."""
    return ', '.join(
        '"' + context.name + '" AS (' + _fixture_sql(fixture.tables[context.name], list(context.columns), context.columns) + ')'
        for context in spec.data_context
    )


def grade(engine, request):
    from .exercise_validation import validate_result
    import platform
    spec, private = PACKS.get(request['exercise_id'])
    if spec.runtime == 'fastapispark-guided-v1':
        raise ValueError('Guided Spark requires explicit connection qualification; no local fallback.')
    if request['exercise_version'] != spec.version or request['language'] != spec.language:
        raise ValueError('Exercise version or kernel changed. Reopen the installed exercise.')
    code = request['code']
    if spec.runtime == 'datapass-dag-design-v1':
        from .pipeline_grading import grade_design
        return grade_design(engine, request, spec, private)
    fixtures = [f for f in private.fixtures if request['mode'] == 'submit' or f.visibility == 'visible']
    evidence, runs = [], []
    available = next(k['available'] for k in engine.capabilities()['kernels'] if k['id'] == spec.language)
    for fixture in fixtures:
        namespace = 'grading-' + uuid.uuid4().hex
        internal = {**request, 'notebook_id':namespace, 'output_asset':None}
        columns = list(spec.data_context[0].columns) if spec.data_context else list(fixture.input_rows[0]) if fixture.input_rows else ['value']
        types = dict(spec.data_context[0].columns) if spec.data_context else {}
        if fixture.tables is not None:
            internal['_exercise_fixture_ctes'] = _fixture_ctes(spec, fixture)
            try:
                validate_sql(code, read_only=True)
            except ValueError:
                internal['code'] = 'INVALID SUBMISSION'
        elif spec.language in {'sql','sparklab','dbt'}:
            internal['_exercise_fixture_sql'] = _fixture_sql(fixture.input_rows, columns, types)
            internal['_exercise_columns'] = columns
            internal['_exercise_input_count'] = len(fixture.input_rows)
            if spec.language == 'sql':
                try:
                    validate_sql(code, read_only=True)
                except ValueError:
                    internal['code'] = 'INVALID SUBMISSION'
        else:
            engine.python_namespaces[namespace] = {'__name__':'__datapass_exercise__','input_rows':deepcopy(fixture.input_rows)}
        try:
            run = engine.execute(internal)
        finally:
            engine.python_namespaces.pop(namespace, None)
            engine.parsers.pop(namespace, None)
        run['notebook_id'] = request['notebook_id']
        run['source_hash'] = hashlib.sha256(code.encode()).hexdigest()
        run.pop('compiled_sql', None)
        result = run.get('result', {})
        fresh = all(engine.catalog.fresh(name) for name in run.get('input_versions',{}))
        passed = run['status']=='success' and fresh and validate_result(result,fixture.expected,spec.validation,code,spec.language)
        check = dict(id=fixture.id, visibility=fixture.visibility, passed=passed,
                     status='passed' if passed else 'failed', execution_id=run['id'],
                     message='Result matches declared contract.' if passed else 'Result differs or execution failed.',
                     execution_status=run['status'], elapsed_ms=run['elapsed_ms'],input_versions=run.get('input_versions',{}) if fixture.visibility=='visible' else {})
        if fixture.visibility == 'visible':
            check.update(actual=result.get('rows',[]),expected=fixture.expected)
            if run.get('error'): check['message'] = run['error']['message']
            runs.append(run)
        evidence.append(check)
    runtime_engine = 'python' if spec.language == 'python' else 'polars' if spec.language == 'polars' else engine.catalog.kind
    if runtime_engine == 'python':
        engine_version = platform.python_version()
    elif runtime_engine == 'sqlite':
        engine_version = sqlite3.sqlite_version
    elif runtime_engine == 'polars':
        engine_version = version('polars') if available else 'unavailable'
    else:
        engine_version = version('duckdb')
    return dict(checks=evidence, runs=runs, status='error' if not available else 'passed' if all(c['passed'] for c in evidence) else 'failed',
                truth='unsupported' if not available else 'semantic-emulation' if spec.language in {'sparklab','dbt'} else 'real',
                runtime={'adapter':spec.runtime,'engine':runtime_engine,'engine_version':engine_version,'session_generation':engine.generation},
                elapsed_ms=round(sum(c['elapsed_ms'] for c in evidence),3))


def attempt(request, result):
    return dict(schema_version=1,id=uuid.uuid4().hex,created_at=datetime.now(timezone.utc).isoformat(),
                exercise_id=request['exercise_id'],exercise_version=request['exercise_version'],
                notebook_id=request['notebook_id'],cell_id=request['cell_id'],
                source=request['code'],source_hash=hashlib.sha256(request['code'].encode()).hexdigest(),
                source_revision=request['source_revision'],validator_version=definition(request['exercise_id'])['validator_version'],
                fixtures=definition(request['exercise_id'])['fixtures'],language=request['language'],
                **{key:result[key] for key in ('status','checks','truth','runtime','elapsed_ms')})
