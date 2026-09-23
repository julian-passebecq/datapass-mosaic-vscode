"""Allowlisted, explicitly trusted local dbt Core adapter over the shared catalog.

Imported artifacts never enter this execution path. Each invocation gets fresh
source/target/profile folders and exact checksummed evidence. No dbt Cloud, shell,
package installation, network fallback or separate analytics database is used.
"""
from __future__ import annotations
from copy import deepcopy
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
from .analytics_contracts import source_path
from .foundation import DbtProjectResource
from .local_jobs import CapabilityUnavailable, JobContext, digest

ACTIONS = ('parse', 'compile', 'seed', 'run', 'build', 'test')
SELECTOR = re.compile(r'^[A-Za-z0-9_.*+,:/@-]{1,200}$')


def selector(value: str) -> str:
    if value and (not SELECTOR.fullmatch(value) or value.startswith('-')):
        raise ValueError('Use one bounded dbt selection expression, not CLI options or shell text.')
    return value


def versions() -> dict[str, str | None]:
    found = {}
    for package in ('dbt-core', 'dbt-duckdb', 'duckdb'):
        try:
            found[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            found[package] = None
    return found


def dbt_capability(mode: str, trusted: bool) -> dict:
    installed = versions()
    executable = sys.executable
    reasons = []
    if not trusted:
        reasons.append('Enable --trusted-local-dbt after reviewing project SQL, macros and hooks. dbt is not sandboxed.')
    if any(v is None for v in installed.values()):
        reasons.append('Install requirements-dbt.txt in the same Python environment as the API.')
    if mode not in {'auto', 'duckdb', 'ducklake'}:
        reasons.append('dbt Project execution requires DuckDB or DuckLake; SQLite compatibility is not a dbt target.')
    return dict(available=not reasons, truth='real_local' if not reasons else 'unavailable',
                reason=' '.join(reasons), actions=list(ACTIONS), versions=installed,
                target='shared workspace DuckLake' if mode == 'ducklake' else 'shared workspace DuckDB',
                trusted_local=trusted, executable=executable,
                warning='Local dbt runs as your OS user. Review macros/hooks. No security sandbox.')


def project_profile(data: Path, mode: str) -> dict:
    """Server-owned profile: all sources, models and notebook SQL share this file."""
    output = dict(type='duckdb', path=str((data / 'workspace.duckdb').resolve()),
                  schema='warehouse', threads=1, settings={'threads': 2, 'memory_limit': '512MB'})
    if mode == 'ducklake':
        legacy, metadata = data / 'lake-catalog.ducklake', data / 'lake-metadata.sqlite'
        use_legacy = legacy.exists() and not metadata.exists()
        path = ('ducklake:' if use_legacy else 'ducklake:sqlite:') + str((legacy if use_legacy else metadata).resolve())
        output.update(database='lake', extensions=['ducklake'] if use_legacy else ['ducklake', 'sqlite'],
                      attach=[{'path': path, 'alias': 'lake', 'options': {
                          'DATA_PATH': str((data / 'lake-files').resolve()), 'DATA_INLINING_ROW_LIMIT': 0}}])
    return {'datapass_local': {'target': 'local', 'outputs': {'local': output}}}


def write_sources(resource: dict, target: Path) -> None:
    validated = DbtProjectResource.model_validate(resource)
    paths = {f.path.casefold() for f in validated.files}
    if 'dbt_project.yml' not in paths:
        raise ValueError('A real dbt project needs dbt_project.yml.')
    if any('/'.join(name.split('/')[:i]) in paths for name in paths for i in range(1, len(name.split('/')))):
        raise ValueError('Source path conflicts with a source directory.')
    target.mkdir(parents=True, exist_ok=False)
    for file in validated.files:
        path = target.joinpath(*source_path(file.path).split('/'))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file.source, encoding='utf-8', newline='\n')


def clean_environment(profile: Path, target: Path, logs: Path) -> dict[str, str]:
    # Strip inherited credentials and dbt configuration, not OS runtime basics.
    env = {k:v for k,v in os.environ.items() if not (k.startswith(('DBT_', 'MOTHERDUCK_', 'AWS_', 'AZURE_', 'GOOGLE_'))
           or any(term in k.upper() for term in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY', 'CREDENTIAL')))}
    env.update(DBT_PROFILES_DIR=str(profile), DBT_TARGET_PATH=str(target), DBT_LOG_PATH=str(logs),
               DBT_SEND_ANONYMOUS_USAGE_STATS='false', DBT_USE_COLORS='false', DBT_PARTIAL_PARSE='false',
               PYTHONUNBUFFERED='1')
    return env


def _read_json(path: Path, root: Path) -> dict | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 2_000_000:
        raise ValueError('Generated artifact exceeds local evidence bounds or is a symlink.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON dbt artifact object.')
    return value


def collect_artifacts(job: JobContext, target: Path, *, prefix: str = '') -> dict:
    manifest = _read_json(target / 'manifest.json', target)
    results = _read_json(target / 'run_results.json', target)
    if manifest is None:
        return {'invocation_id': None, 'warnings': ['No manifest was produced. No lineage or compiled SQL is assumed.'], 'files': {}}
    metadata = manifest.get('metadata', {})
    invocation = metadata.get('invocation_id')
    if not isinstance(invocation, str) or not invocation or len(invocation) > 100:
        raise ValueError('dbt manifest has no bounded invocation_id.')
    schema = metadata.get('dbt_schema_version', '')
    if not re.fullmatch(r'https://schemas\.getdbt\.com/dbt/manifest/v(9|10|11|12)\.json', schema):
        raise ValueError('dbt manifest schema is not qualified (v9-v12). Raw invocation failed evidence validation.')
    if results is not None and results.get('metadata', {}).get('invocation_id') != invocation:
        raise ValueError('Generated manifest and run_results invocation IDs differ. No mismatched result is displayed.')
    if results is not None and not re.fullmatch(r'https://schemas\.getdbt\.com/dbt/run-results/v(4|5|6)\.json', results.get('metadata', {}).get('dbt_schema_version', '')):
        raise ValueError('dbt run_results schema is not qualified (v4-v6).')
    all_nodes = {**manifest.get('nodes', {}), **manifest.get('sources', {})}
    if len(all_nodes) > 400:
        raise ValueError('The local artifact node limit is 400.')
    if results is not None and any(r.get('unique_id') not in all_nodes for r in results.get('results', [])):
        raise ValueError('A run result references a node outside its manifest.')
    files = {'manifest': job.artifact(prefix + 'manifest.json', manifest)}
    if results is not None:
        files['run_results'] = job.artifact(prefix + 'run_results.json', results)
    catalog = _read_json(target / 'catalog.json', target)
    if catalog is not None:
        if catalog.get('metadata', {}).get('invocation_id') != invocation:
            raise ValueError('Catalog belongs to a different invocation.')
        files['catalog'] = job.artifact(prefix + 'catalog.json', catalog)
    # Compiled SQL is read from the manifest, never a browser-provided path.
    return {'invocation_id': invocation, 'generated_at': metadata.get('generated_at'),
            'dbt_version': metadata.get('dbt_version'), 'warnings': [], 'files': files}


class DbtRunner:
    def __init__(self, documents, manager, *, trusted=False):
        self.documents, self.manager, self.trusted = documents, manager, trusted

    def capabilities(self) -> dict:
        return dbt_capability(self.manager.mode, self.trusted)

    def run(self, job: JobContext, resource: dict, workspace: dict, *, action='build', select='', prefix='') -> dict:
        if action not in ACTIONS:
            raise ValueError('Unsupported dbt action.')
        selector(select)
        capability = self.capabilities()
        if not capability['available']:
            raise CapabilityUnavailable(capability['reason'])
        job.check()
        wid = workspace['id']
        data = self.documents.folder(wid) / 'data'
        # Initialization and runtime metadata come from the existing kernel, not
        # a second Catalog object in this process. It is then stopped for dbt.
        try:
            runtime = self.manager.call(wid, data, {'op': 'capabilities'})
        except Exception as error:
            raise CapabilityUnavailable('Shared catalog could not start: ' + str(error)) from error
        if runtime['storage'] not in ('duckdb', 'ducklake'):
            raise CapabilityUnavailable('The active workspace is not backed by DuckDB/DuckLake.')
        self.manager.restart(wid)
        base = job.directory / (prefix + 'dbt')
        base.mkdir(parents=True, exist_ok=False)
        source, profiles, target, logs = (base / n for n in ('source', 'profiles', 'target', 'logs'))
        write_sources(resource, source)
        for folder in (profiles, target, logs):
            folder.mkdir()
        # YAML is a superset of JSON: no unsafe YAML templating is involved.
        (profiles / 'profiles.yml').write_text(json.dumps(project_profile(data, runtime['storage']), indent=2), encoding='utf-8')
        argv = [sys.executable, str(Path(__file__).with_name('dbt_worker.py').resolve()), action, '--project-dir', str(source),
                '--profiles-dir', str(profiles), '--profile', 'datapass_local', '--target', 'local',
                '--target-path', str(target), '--log-path', str(logs), '--no-use-colors', '--no-partial-parse']
        if select:
            if action == 'parse':
                raise ValueError('parse applies to the whole project; selection is unsupported for parse.')
            argv += ['--select', select]
        runtime_identity = {'adapter': 'dbt-core', 'versions': capability['versions'],
                            'storage': runtime['storage'], 'lakehouse': runtime.get('lakehouse'),
                            'process_isolation': 'trusted local subprocess; not a sandbox'}
        if not prefix:
            job.update(runtime=runtime_identity)
        job.log(f'[dbt] {action} / canonical resource {resource["id"]} revision {resource["revision"]}\n')
        code = job.run_process(argv, cwd=source, env=clean_environment(profiles, target, logs))
        evidence = collect_artifacts(job, target, prefix=prefix)
        if evidence.get('dbt_version') and evidence['dbt_version'] != capability['versions']['dbt-core']:
            raise ValueError('Artifact dbt version differs from the invoking Python environment.')
        artifacts = dict(job.record['artifacts'])
        for key, value in evidence['files'].items():
            artifacts[prefix + key] = value
        job.update(artifacts=artifacts)
        result = dict(runtime=runtime_identity, returncode=code, invocation_id=evidence['invocation_id'], warnings=evidence['warnings'],
                      action=action, selector=select, resource_id=resource['id'], resource_revision=resource['revision'],
                      source_hash=digest(resource['files']), files=evidence['files'], truth='real_local')
        if prefix:
            job.log(f'[dbt] task invocation {evidence["invocation_id"] or "none"}: exit {code}\n')
        else:
            job.update(result=result)
        if action in ('seed','run','build') and evidence['invocation_id'] and evidence['files'].get('run_results'):
            manifest = _read_json(target/'manifest.json',target)
            results = _read_json(target/'run_results.json',target)
            nodes = manifest.get('nodes', {})
            lookup = {**nodes, **manifest.get('sources', {})}
            successful = {r['unique_id'] for r in results.get('results',[]) if r.get('status')=='success'}
            pending = {id:n for id,n in nodes.items() if id in successful and n.get('resource_type') in ('model','seed','snapshot')}
            updates = []
            while pending:
                ready = [id for id,n in pending.items() if not set(n.get('depends_on',{}).get('nodes',[])) & pending.keys()]
                if not ready:
                    break
                for id in ready:
                    n = pending.pop(id)
                    name = str(n.get('schema',''))+'.'+str(n.get('alias') or n.get('name',''))
                    inputs = [str(lookup[r].get('schema',''))+'.'+str(lookup[r].get('alias') or lookup[r].get('identifier') or lookup[r].get('name','')) for r in n.get('depends_on',{}).get('nodes',[]) if r in lookup]
                    updates.append({'name':name,'inputs':inputs})
            # Only server-validated artifacts reach this internal worker operation.
            registration = self.manager.call(wid,data,{'op':'register_dbt_outputs','nodes':updates,'invocation_id':evidence['invocation_id']})
            result['catalog_registration'] = registration
            if registration['omitted']:
                result['warnings'].append('Some outputs are outside registered workspace layers: '+', '.join(registration['omitted']))
            if not prefix:
                job.update(result=result)
        if code != 0:
            raise RuntimeError(f'dbt {action} exited {code}. Matching artifacts and bounded stdout/stderr remain available.')
        if not evidence['invocation_id']:
            raise RuntimeError('dbt exited successfully but did not produce a matching manifest. Invocation not qualified.')
        # Catalog restarts lazily: the shared persisted data is then visible to SQL/Polars.
        return result
