"""Shared execution engine. Instantiated inside a disposable kernel process."""
from __future__ import annotations

import ast
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import math
import re
from pathlib import Path
import time
from typing import Any
import uuid

from .catalog import Catalog, json_value, references, statements
from .content import compile_dbt, get_case, topological_steps
from sparklab.safe_parser import SafeSparkParser, SparkLabSyntaxError
from sparklab.sparklab import SparkSession
from sparklab.runtime import load_cluster_profiles

SPARK_HOME = Path(__file__).resolve().parents[1] / 'sparklab'


def subquery_body(sql: str) -> str:
    """A submission made safe to wrap as `(...) AS submitted`.

    Trailing semicolons (and comments after them) are dropped, and the result
    ends with a newline so a trailing `-- comment` cannot swallow the closing
    parenthesis of the wrapper.
    """
    try:
        parts = statements(sql)
    except ValueError:
        parts = [sql]
    body = (parts[0] if len(parts) == 1 else sql).rstrip()
    while body.endswith(';'):
        body = body[:-1].rstrip()
    return body + '\n'


class BoundedText(io.StringIO):
    def write(self, value):
        remaining = 32_000 - self.tell()
        if remaining > 0:
            super().write(value[:remaining])
        return len(value)


def compare_rows(actual: list[dict], expected: list[dict]) -> bool:
    """Order independent, exact columns and cardinality, tolerance for numbers."""
    if len(actual) != len(expected):
        return False
    pending = list(expected)
    for row in actual:
        match = None
        for index, candidate in enumerate(pending):
            if set(row) != set(candidate):
                continue
            valid = True
            for key, value in row.items():
                other = candidate[key]
                if isinstance(value, (int, float)) and isinstance(other, (int, float)):
                    valid &= math.isclose(value, other, rel_tol=1e-9, abs_tol=1e-8)
                else:
                    valid &= value == other
            if valid:
                match = index
                break
        if match is None:
            return False
        pending.pop(match)
    return not pending


class Engine:
    def __init__(self, directory: Path, mode='auto', trusted_python=False):
        self.catalog = Catalog(directory, mode)
        self.trusted_python = trusted_python
        self.generation = uuid.uuid4().hex
        self.sequence = 0
        self.parsers: dict[str, SafeSparkParser] = {}
        self.python_namespaces: dict[str, dict] = {}
        self.directory = directory

    def capabilities(self):
        lakehouse = self.catalog.runtime_contract()
        return {
            'storage': self.catalog.kind,
            'storage_truth': lakehouse['truth'],
            'ducklake_active': bool(lakehouse['active']),
            'lakehouse': lakehouse,
            'motherduck': {
                'enabled': False,
                'mode': 'optional_remote',
                'reason': 'Optional future remote DuckDB/DuckLake adapter; no hidden network fallback and no credentials required for local use.',
            },
            'kernels': [
                {'id':'sql','available':True,'truth':'real SQL execution'},
                {'id':'sparklab','available':True,'truth':'supported AST compiled to local SQL; distributed compute simulated'},
                {'id':'python','available':self.trusted_python,'truth':'trusted local CPython worker; not a security sandbox'},
                {'id':'polars','available':self.trusted_python and importlib.util.find_spec('polars') is not None,'truth':'real Polars when installed; no substitute'},
                {'id':'dbt','available':True,'truth':'literal ref/source teaching adapter; SQL executes; not dbt Core'},
                {'id':'airflow','available':True,'truth':'DAG file parsed, never executed; deterministic Airflow 3 scheduler/task simulation'},
                {'id':'factory','available':self.catalog.kind != 'sqlite','truth':'Data Factory orchestration simulated; Copy, Lookup, Script, procedures and SparkLab notebooks run on the local catalog'},
            ],
            'session_generation': self.generation,
            'distributed_spark': False,
            'sparklab': __import__('sparklab.capabilities', fromlist=['SUPPORT']).SUPPORT,
        }

    def parser(self, notebook_id: str):
        if notebook_id not in self.parsers:
            profile = json.loads((SPARK_HOME / 'profiles.json').read_text())['retail']
            self.parsers[notebook_id] = SafeSparkParser(SparkSession(profile))
        return self.parsers[notebook_id]

    def check(self, spec: dict | None) -> dict:
        if not spec:
            return {'status': 'not_configured', 'passed': None, 'message': 'No automatic acceptance check is defined for this step.'}
        try:
            result = self.catalog.query(spec['sql'])
            inputs = references(spec['sql'])
            fresh = all(self.catalog.fresh(asset) for asset in inputs)
            passed = not result['truncated'] and fresh and compare_rows(result['rows'], spec['expected'])
            return {'status': 'passed' if passed else 'failed', 'passed': passed, 'fresh': fresh, 'actual': result['rows'], 'expected': spec['expected'], 'message': 'Actual rows match and their inputs are fresh.' if passed else 'Rows differ, an input is stale, or the result is truncated.'}
        except Exception as error:
            return {'status':'failed','passed':False,'message':str(error)}

    def _python(self, request: dict) -> tuple[dict, str, list[str]]:
        if not self.trusted_python:
            raise ValueError('Trusted local Python is disabled for this workspace. Enable it explicitly in Datapass Workbench only for code you trust; it runs as real local code and the worker is not a security sandbox.')
        if request['language'] == 'polars' and importlib.util.find_spec('polars') is None:
            raise ValueError('Polars is not installed. Install requirements-engines.txt. No simulated Polars output was returned.')
        notebook_id = request['notebook_id']
        env = self.python_namespaces.setdefault(notebook_id, {'__name__':'__datapass_notebook__'})
        output = BoundedText()
        shown: list[Any] = []
        shown_columns: list[str] = []
        dependencies: set[str] = set()
        def query(sql):
            dependencies.update(references(sql))
            result = self.catalog.query(sql)
            if result['truncated']:
                raise ValueError('query() would truncate input. Use SQL aggregation or a registered bounded fixture instead.')
            return result['rows']
        def normalize(value):
            if hasattr(value, 'to_dicts'):
                return value.to_dicts()
            if hasattr(value, 'to_dict'):
                return value.to_dict(orient='records')
            if isinstance(value, list) and all(isinstance(r, dict) for r in value):
                return value
            if isinstance(value, dict):
                return [value]
            return [{'value': json_value(value)}]
        def display(value, columns=None):
            rows = normalize(value)
            shown.append(rows)
            shown_columns[:] = list(columns if columns is not None else getattr(value, 'columns', list(rows[0]) if rows else []))
        def publish(name, value):
            return self.catalog.publish_rows(name, normalize(value), request['cell_id'], sorted(dependencies))
        env.update(query=query, display=display, publish=publish)
        tree = ast.parse(request['code'], mode='exec')
        # This is deliberate trusted code execution inside the worker, never the API process.
        with redirect_stdout(output), redirect_stderr(output):
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                final = tree.body.pop()
                exec(compile(tree, '<notebook>', 'exec'), env, env)
                value = eval(compile(ast.Expression(final.value), '<notebook>', 'eval'), env, env)
                if value is not None:
                    display(value)
            else:
                exec(compile(tree, '<notebook>', 'exec'), env, env)
        rows = shown[-1] if shown else []
        if request.get('output_asset'):
            result = self.catalog.publish_rows(request['output_asset'], rows, request['cell_id'], sorted(dependencies))
        else:
            result = {'columns':shown_columns, 'rows':json_value(rows[:200]),'truncated':len(rows)>200,'total_rows':len(rows)}
        return result, output.getvalue(), sorted(dependencies)

    def _partition_pruning_hints(self, frame) -> dict[str, tuple[str, str]]:
        """Find only directly provable source equality filters.

        A hint is emitted only when the first relational operation on a source
        is a simple column = scalar filter. More complex predicates are left
        unmodeled rather than guessed.
        """
        hints: dict[str, tuple[str, str]] = {}

        def visit(current):
            for op in current.ops:
                if op.kind == 'join':
                    visit(op.detail['other'])
            if not current.ops or current.ops[0].kind != 'filter':
                return
            sql = str(current.ops[0].detail['expr'].sql)
            match = re.fullmatch(
                r'\("([A-Za-z_][A-Za-z0-9_]*)" = (\'(?:\'\'|[^\'])*\'|-?\d+(?:\.\d+)?|TRUE|FALSE)\)',
                sql,
                re.I,
            )
            if not match:
                return
            raw = match.group(2)
            if raw.startswith("'") and raw.endswith("'"):
                value = raw[1:-1].replace("''", "'")
            else:
                value = raw.lower() if raw.upper() in {'TRUE', 'FALSE'} else raw
            hints[current.source] = (match.group(1), value)

        visit(frame)
        return hints

    def simulate(self, request: dict, parsed, result: dict):
        from sparklab.physical import simulate_plan, credits, logical_plan
        profiles = load_cluster_profiles(str(SPARK_HOME / 'cluster_profiles.json'))
        profile_id = request.get('profile', 'generic_8x8')
        if profile_id not in profiles:
            raise ValueError('Unknown virtual cluster profile.')
        profile = profiles[profile_id]
        aqe = request.get('aqe', profile.aqe_default)
        statistics = {}
        catalog_assets = {asset['name']: asset for asset in self.catalog.listing()}
        pruning_hints = self._partition_pruning_hints(parsed.dataframe)
        measured_ducklake_inputs = False
        measured_partition_pruning = False
        for node in logical_plan(parsed.dataframe):
            if node['operation'] == 'scan':
                name = node['source']
                fixture_counts = request.get('_exercise_table_counts') or {}
                if name in fixture_counts or (name == 'input' and request.get('_exercise_fixture_sql')):
                    count = fixture_counts.get(name, request.get('_exercise_input_count', 0))
                    statistics[name] = {
                        'rows': count,
                        'bytes': count * 128,
                        'input_truth': 'bounded exercise fixture; bytes estimated at 128 bytes/row',
                    }
                    continue
                asset = catalog_assets.get(name)
                count = asset['row_count'] if asset is not None else self.catalog.query(f'SELECT COUNT(*) AS n FROM {name}')['rows'][0]['n']
                storage = asset.get('storage') if asset else None
                has_physical_files = bool(storage and int(storage.get('file_count') or 0) > 0)
                if storage and storage.get('truth') == 'measured_ducklake_metadata' and (has_physical_files or count == 0):
                    measured_ducklake_inputs = True
                    full_bytes = int(storage.get('size_bytes') or 0)
                    full_files = int(storage.get('file_count') or 0)
                    stat = {
                        'rows': count,
                        'table_rows': count,
                        'bytes': full_bytes,
                        'full_bytes': full_bytes,
                        'partitions': max(1, full_files),
                        'source_files': full_files,
                        'full_source_files': full_files,
                        'small_file_count': int(storage.get('small_file_count') or 0),
                        'min_file_size_bytes': int(storage.get('min_file_size_bytes') or 0),
                        'max_file_size_bytes': int(storage.get('max_file_size_bytes') or 0),
                        'average_file_size_bytes': round(full_bytes / max(full_files, 1)),
                        'snapshot_id': storage.get('snapshot_id'),
                        'input_truth': 'rows measured from table; bytes/files measured from DuckLake metadata',
                    }
                    hint = pruning_hints.get(name)
                    if hint:
                        pruning = self.catalog.partition_pruning_evidence(name, hint[0], hint[1])
                        if pruning.get('eligible'):
                            measured_partition_pruning = True
                            stat.update(
                                rows=int(pruning.get('candidate_records') or 0),
                                bytes=int(pruning.get('candidate_bytes') or 0),
                                partitions=max(1, int(pruning.get('candidate_files') or 0)),
                                candidate_files=int(pruning.get('candidate_files') or 0),
                                pruned_files=int(pruning.get('pruned_files') or 0),
                                pruned_bytes=int(pruning.get('pruned_bytes') or 0),
                                partition_pruning=pruning,
                                input_truth='DuckLake rows/files/bytes measured; equality partition candidate set derived exactly from catalog metadata, not runtime scan telemetry',
                            )
                    statistics[name] = stat
                else:
                    statistics[name] = {
                        'rows': count,
                        'bytes': count * 128,
                        'input_truth': 'rows measured from catalog; bytes estimated at 128 bytes/row because physical file evidence is unavailable',
                    }
        pack_id = request.get('truth_pack')
        pack = None
        if pack_id:
            if pack_id not in {'retail_broadcast_join_03','finance_account_window_03'}:
                return {'status':'unavailable','reason':'No registered immutable truth pack.'}
            pack = json.loads((SPARK_HOME / 'exercises' / f'{pack_id}.json').read_text())
            from services.semantic.executor import _execute_sqlite
            tables = (['silver.orders','silver.dim_customer_segment'] if pack_id.startswith('retail') else ['silver.transactions'])
            for table in tables:
                expected = _execute_sqlite(f'SELECT * FROM {table}', pack.get('case', 'retail'), 200)[2]
                actual = self.catalog.query(f'SELECT * FROM {table}')
                if actual['truncated'] or not compare_rows(actual['rows'], expected):
                    return {'status':'unavailable','reason':'Immutable reference input changed; scenario metrics withheld.'}
            if not set(statistics).issubset(tables):
                return {'status':'unavailable','reason':'Submitted plan reads inputs outside this truth pack.'}
            fact = tables[0]
            if fact in statistics:
                stats = pack['statistics']
                statistics[fact] = {'rows':stats['fact_rows'], 'bytes':stats['fact_bytes_gb']*1073741824,
                                    'partitions':stats['source_files'],
                                    'hot_fraction':stats['largest_partition_mb']/(stats['fact_bytes_gb']*1024),
                                    'input_truth':'authored immutable truth-pack scale; not physically processed rows'}
            if len(tables)>1 and tables[1] in statistics:
                statistics[tables[1]].update(bytes=pack['statistics'].get('dimension_bytes_mb', 2)*1048576,
                                             rows=pack['statistics'].get('dimension_rows',4),
                                             catalog_statistics_available=pack['statistics'].get('catalog_statistics_available',True),
                                             input_truth='authored immutable truth-pack scale; not physically processed rows')
        job, metrics, nodes = simulate_plan(parsed.dataframe, statistics, profile, aqe, result.get('total_rows'))
        comparisons = []
        for other in profiles.values():
            for adaptive in (False, True):
                variant, _, _ = simulate_plan(parsed.dataframe, statistics, other, adaptive)
                comparisons.append({'profile_id':other.id,'aqe':adaptive,'duration_s':variant.total_duration_s,
                                    'credits':credits(variant, other)['total'],
                                    'duration_delta_s':round(variant.total_duration_s-job.total_duration_s,3),
                                    'reason':'Same logical plan and input assumptions; virtual slots, throughput, startup and AQE task grouping differ.'})
        return {'status':'modeled','schema_version':1, 'truth':'Local semantic result + simulated distributed execution',
                'profile_id':profile_id, 'aqe':aqe, 'metrics':metrics, 'logical_plan':nodes,
                'action':parsed.action, 'datapass_credits':credits(job, profile), 'comparisons':comparisons,
                'assumptions':{'input_statistics':statistics,
                               'kind':'authored virtual scale' if pack else ('catalog rows + exact DuckLake identity-partition candidate files/bytes' if measured_partition_pruning else ('catalog rows + measured DuckLake Parquet files/bytes' if measured_ducklake_inputs else 'catalog row counts; assumed 128 bytes per row')),
                               'calibration':'No real Spark benchmark calibration',
                               'intermediates':'Cardinality and bytes carried forward without selectivity estimates; serial operator-stage dispatch, not Spark codegen fusion; scan counts are real only outside virtual truth-pack scale',
                               'cache':'Unavailable; cache/reuse not modeled',
                               'storage_note':'DuckLake source file counts/sizes are measured when available. Identity-partition equality candidate files are exact catalog evidence; this is planning evidence, not runtime scan telemetry. Other pruning/selectivity is not claimed.'},
                'semantic_match':(not result['truncated'] and compare_rows(result['rows'],pack['fixture_truth']['rows'])) if pack else None}

    def execute(self, request: dict):
        start = time.perf_counter()
        self.sequence += 1
        run = {
            'id':uuid.uuid4().hex, 'cell_id':request['cell_id'], 'notebook_id':request['notebook_id'],
            'source_hash':hashlib.sha256(request['code'].encode()).hexdigest(),
            'session_generation':self.generation, 'sequence':self.sequence,
            'created_at':datetime.now(timezone.utc).isoformat(),
            'engine':self.catalog.kind,'language':request['language'],
            'status':'error','stdout':'','output_asset':request.get('output_asset'),
            'simulation':None,'check':None,
        }
        try:
            language = request['language']
            compiled_sql = None
            parsed = None
            python_inputs = []
            if language in {'sql', 'dbt'}:
                compiled_sql = request['code']
                if language == 'dbt':
                    if request.get('_exercise_fixture_sql'):
                        from .dbt_drills import compile_fixture_sql
                        compiled_sql = compile_fixture_sql(compiled_sql)
                    else:
                        compiled_sql = compile_dbt(compiled_sql, get_case(request['case_id']))
            elif language == 'sparklab':
                # A rejected cell cannot partially overwrite earlier Spark symbols.
                candidate = deepcopy(self.parser(request['notebook_id']))
                # Refresh schemas from the shared catalog, including saved notebook symbols.
                tables = candidate.spark.profile.setdefault('tables', {})
                for asset in self.catalog.listing():
                    tables[asset['name']] = {'columns':self.catalog.query(f"SELECT * FROM {asset['name']} LIMIT 0")['columns']}
                if request.get('_exercise_columns'):
                    tables['input'] = {'columns':request['_exercise_columns']}
                for name, fixture_columns in (request.get('_exercise_tables') or {}).items():
                    tables[name] = {'columns':fixture_columns}
                parsed = candidate.parse(request['code'])
                if request.get('profile', 'generic_8x8') not in load_cluster_profiles(str(SPARK_HOME / 'cluster_profiles.json')):
                    raise ValueError('Unknown virtual cluster profile.')
                columns = parsed.dataframe.current_columns()
                if columns is not None and len(columns) != len(set(columns)):
                    raise ValueError('Duplicate result column names cannot be represented faithfully; select distinct aliases.')
                compiled_sql = parsed.dataframe.sql
            elif language in {'python', 'polars'}:
                result, run['stdout'], python_inputs = self._python(request)
            else:
                raise ValueError('Unsupported kernel. Markdown is not executable.')
            if compiled_sql is not None:
                # Server-owned exercise fixture scope; never accepted by API models.
                if request.get('_exercise_fixture_ctes'):
                    compiled_sql = f"WITH {request['_exercise_fixture_ctes']} SELECT * FROM ({subquery_body(compiled_sql)}) AS submitted"
                elif request.get('_exercise_fixture_sql'):
                    compiled_sql = f"WITH input AS ({request['_exercise_fixture_sql']}) SELECT * FROM ({subquery_body(compiled_sql)}) AS submitted"
                if request.get('output_asset'):
                    result = self.catalog.materialize(request['output_asset'], compiled_sql, request['cell_id'])
                elif language in {'sparklab','dbt'}:
                    result = self.catalog.query(compiled_sql)
                else:
                    result = self.catalog.execute(compiled_sql, request['cell_id'])
                run['compiled_sql'] = compiled_sql
            if parsed is not None:
                self.parsers[request['notebook_id']] = candidate
                # Physical evidence failure cannot invalidate a successfully computed semantic result.
                try:
                    run['simulation'] = self.simulate(request, parsed, result)
                except Exception as error:
                    run['simulation'] = {'status':'unavailable','reason':str(error)}
                run['training_plan'] = {'truth':'structured teaching plan', 'nodes':run['simulation'].get('logical_plan', [])}
            run.update(status='success', result=result)
            if request.get('check'):
                run['check'] = self.check(request['check'])
                if not request.get('output_asset'):
                    output_matches = not result['truncated'] and compare_rows(result['rows'], request['check']['expected'])
                    if not output_matches:
                        run['check'].update(status='failed',passed=False,message='This cell output differs from the expected result, even if a prior catalog asset is correct.')
            run['input_versions'] = {asset:self.catalog.versions.get(asset,{}).get('version') for asset in sorted(set(references(compiled_sql or '')+python_inputs))}
            run['catalog'] = self.catalog.listing()
        except Exception as error:
            run['error'] = {'type':type(error).__name__, 'message':str(error)}
        run['elapsed_ms'] = round((time.perf_counter() - start) * 1000, 3)
        return run

    def spark_verify_fixture(self, request: dict):
        """Prepare exact bounded workspace inputs for the real-Spark oracle.

        This does not execute submitted Python. The existing SafeSparkParser
        identifies source scans. Verification is withheld when a source would
        be truncated by the bounded local catalog preview, because silently
        sampling would make the remote result semantically misleading.
        """
        code = request.get('code', '')
        if not code or len(code) > 20_000:
            raise ValueError('Real Spark verification code must be 1..20,000 characters.')
        notebook_id = request.get('notebook_id') or 'case-notebook'
        candidate = deepcopy(self.parser(notebook_id))
        tables = candidate.spark.profile.setdefault('tables', {})
        for asset in self.catalog.listing():
            tables[asset['name']] = {
                'columns': self.catalog.query(f"SELECT * FROM {asset['name']} LIMIT 0")['columns']
            }
        parsed = candidate.parse(code)
        from sparklab.physical import logical_plan
        sources = []
        for node in logical_plan(parsed.dataframe):
            if node['operation'] == 'scan' and node.get('source') not in sources:
                sources.append(node.get('source'))
        if not sources:
            raise ValueError('No Spark source table was found for real verification.')
        if len(sources) > 8:
            raise ValueError('Real Spark verification supports at most eight source tables.')

        fixtures = []
        for source in sources:
            if source == 'input':
                raise ValueError('Exercise-only input fixtures are not exported to remote Spark in Pass 1.')
            result = self.catalog.query(f'SELECT * FROM {source}')
            if result['truncated']:
                raise ValueError(
                    f'Real Spark verification withheld: {source} exceeds the bounded fixture limit. '
                    'Use SparkLab for modeled scale or a dedicated remote dataset pass.'
                )
            if not result['rows']:
                raise ValueError(f'Real Spark verification Pass 1 requires non-empty source table: {source}.')
            fixtures.append({'name': source, 'rows': result['rows']})
        return {
            'code': code,
            'tables': fixtures,
            'sources': sources,
            'truth': 'exact bounded workspace rows prepared locally; no silent sampling',
        }

    def workflow(self, request: dict):
        case = get_case(request['case_id'])
        ordered = topological_steps(case['steps'])
        runs, failed = [], set()
        overrides = request.get('overrides', {})
        unknown = set(overrides) - {step['id'] for step in ordered}
        if unknown:
            raise ValueError('Unknown workflow override: '+', '.join(sorted(unknown)))
        for step in ordered:
            if any(parent in failed for parent in step['depends_on']):
                failed.add(step['id'])
                runs.append({'cell_id':step['id'],'status':'skipped','reason':'An upstream task failed.'})
                continue
            run_request = {
                'case_id':case['id'],'notebook_id':request['notebook_id'],'cell_id':step['id'],
                'code':overrides.get(step['id'], step['code']), 'language':step['language'],
                'output_asset':step.get('output_asset'),'check':step.get('check'),
                'truth_pack':step.get('truth_pack'),'profile':request.get('profile','generic_8x8'),'aqe':request.get('aqe',True),
            }
            run = self.execute(run_request)
            runs.append(run)
            if run['status'] == 'error' or (run.get('check') and run['check']['passed'] is False):
                failed.add(step['id'])
        return {'status':'failed' if failed else 'success','runs':runs,'catalog':self.catalog.listing(), 'scheduler_truth':'portable dependency runner, not Airflow or Data Factory'}

    def handle(self, request: dict):
        op = request['op']
        if op == 'capabilities':
            return self.capabilities()
        if op == 'import_csv':
            from .local_data import import_csv
            return {**import_csv(self.catalog,request['asset'],request['text']),'session_generation':self.generation}
        if op == 'catalog_preview':
            from .catalog import asset_name
            name=asset_name(request['asset'])
            cursor=self.catalog.db.execute('SELECT * FROM '+name+' LIMIT 0')
            schema=[{'name':c[0],'type':str(c[1]) if c[1] is not None else 'not reported by compatibility engine'} for c in cursor.description]
            return {'asset':name,'schema':schema,'result':self.catalog.query('SELECT * FROM '+name),'fresh':self.catalog.fresh(name),'engine':self.catalog.kind}
        if op == 'read_query':
            result = self.catalog.query(request['query'])
            return {'result':result,'engine':self.catalog.kind,'session_generation':self.generation,
                    'input_versions':{a:self.catalog.versions.get(a,{}).get('version') for a in references(request['query'])}}
        if op == 'register_dbt_outputs':
            from .catalog import ASSET
            registered, omitted = [], []
            for node in request['nodes']:
                name = node['name']
                if not ASSET.fullmatch(name) or not self.catalog.exists(name):
                    omitted.append(name)
                    continue
                self.catalog._touch(name, [ref for ref in node['inputs'] if ASSET.fullmatch(ref)], 'dbt:'+request['invocation_id'])
                registered.append(name)
            return {'registered':registered,'omitted':omitted}
        if op == 'catalog':
            return self.catalog.listing()
        if op == 'lakehouse':
            return self.catalog.lakehouse_overview()
        if op == 'spark_verify_fixture':
            return self.spark_verify_fixture(request)
        if op == 'execute':
            return self.execute(request)
        if op == 'exercise':
            from .exercises import grade
            return grade(self, request)
        if op == 'workflow':
            return self.workflow(request)
        if op == 'factory_simulate':
            from .factory_workspace import simulate as factory_simulate
            return factory_simulate(self.catalog, request)
        if op == 'check':
            case = get_case(request['case_id'])
            return {step['id']:self.check(step.get('check')) for step in case['steps']}
        if op == 'reset_namespace':
            key = request['notebook_id']
            self.parsers.pop(key, None)
            self.python_namespaces.pop(key, None)
            self.generation = uuid.uuid4().hex
            return {'session_generation':self.generation,'message':'Variables reset; persisted tables retained.'}
        raise ValueError('Unknown kernel command.')
