"""A dbt project read from its files: dbt_project.yml, models, property files, sources, seeds, snapshots, tests,
macros. The node graph (ref and source dependencies) comes from a parse-mode render, like dbt's parse."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from .render import Hooks, Relation, RenderError, Renderer, Target

LAYERS = ('source', 'bronze', 'silver', 'gold', 'warehouse', 'features', 'metrics')
IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')
SNAPSHOT_BLOCK = re.compile(r'{%-?\s*snapshot\s+([A-Za-z_][A-Za-z0-9_]*)\s*-?%}(.*?){%-?\s*endsnapshot\s*-?%}', re.S)
CONFIG_KEYS = {'materialized', 'schema', 'alias', 'tags', 'enabled', 'unique_key', 'incremental_strategy',
               'on_schema_change', 'full_refresh', 'severity', 'where', 'target_schema', 'strategy', 'updated_at',
               'check_cols', 'hard_deletes', 'invalidate_hard_deletes', 'dbt_valid_to_current', 'column_types',
               'docs', 'meta', 'persist_docs', 'quote_columns', 'description', 'grants', 'contract', 'pre-hook',
               'post-hook', 'pre_hook', 'post_hook', 'database', 'store_failures', 'limit', 'error_if', 'warn_if',
               'fail_calc', 'snapshot_meta_column_names', 'group', 'access', 'delimiter'}
UNSUPPORTED_CONFIG = {'pre-hook', 'post-hook', 'pre_hook', 'post_hook', 'contract', 'store_failures', 'database',
                      'snapshot_meta_column_names', 'group', 'access', 'grants'}
GENERIC_TESTS = ('unique', 'not_null', 'accepted_values', 'relationships')
MATERIALIZATIONS = ('view', 'table', 'incremental', 'ephemeral')
MAX_FILES = 200


class DbtProjectError(ValueError):
    pass


@dataclass
class Node:
    unique_id: str
    name: str
    resource_type: str  # model, seed, snapshot, test
    path: str
    raw: str = ''
    fqn: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    refs: list[str] = field(default_factory=list)
    sources: list[tuple[str, str]] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    description: str = ''
    columns: dict[str, str] = field(default_factory=dict)
    test: dict[str, Any] | None = None  # generic tests: {name, column, kwargs, attached}
    relation: Relation | None = None
    problem: str | None = None

    @property
    def materialized(self) -> str:
        return self.config.get('materialized') or ('seed' if self.resource_type == 'seed' else
                                                   'snapshot' if self.resource_type == 'snapshot' else
                                                   'test' if self.resource_type == 'test' else 'view')


@dataclass
class SourceTable:
    source: str
    name: str
    schema: str
    identifier: str
    description: str = ''
    columns: dict[str, str] = field(default_factory=dict)


@dataclass
class Project:
    name: str
    target: Target
    variables: dict[str, Any]
    renderer: Renderer
    nodes: dict[str, Node] = field(default_factory=dict)
    sources: dict[tuple[str, str], SourceTable] = field(default_factory=dict)
    seeds_csv: dict[str, str] = field(default_factory=dict)
    issues: list[dict[str, str]] = field(default_factory=list)

    def by_name(self, name: str, resource_types=('model', 'seed', 'snapshot')) -> Node | None:
        return next((n for n in self.nodes.values() if n.name == name and n.resource_type in resource_types), None)


def _yaml(text: str, path: str) -> Any:
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as error:
        mark = getattr(error, 'problem_mark', None)
        line = f', line {mark.line + 1}' if mark else ''
        raise DbtProjectError(f'{path}{line}: invalid YAML ({getattr(error, "problem", None) or error})') from error


def _paths(config: dict, key: str, default: str) -> list[str]:
    value = config.get(key, [default])
    return [str(v).strip('/') for v in (value if isinstance(value, list) else [value])]


def _under(path: str, roots: list[str]) -> str | None:
    for root in roots:
        if path.startswith(root + '/'):
            return root
    return None


def _tree_config(tree: Any, fqn: list[str]) -> dict[str, Any]:
    """dbt_project.yml configs for a node: walk models > project > folders, deeper wins, tags accumulate."""
    found: dict[str, Any] = {}
    tags: list[str] = []

    def apply(level: dict):
        for key, value in level.items():
            name = key[1:] if key.startswith('+') else key
            if key.startswith('+') or (name in CONFIG_KEYS and not isinstance(value, dict)):
                if name == 'tags':
                    tags.extend([value] if isinstance(value, str) else list(value or []))
                else:
                    found[name] = value

    level = tree if isinstance(tree, dict) else {}
    apply(level)
    for part in fqn[:-1]:
        nxt = level.get(part)
        if not isinstance(nxt, dict):
            break
        level = nxt
        apply(level)
    if tags:
        found['tags'] = tags
    return found


def load_project(files: dict[str, str], target_schema: str = 'silver', variables: dict[str, Any] | None = None) -> Project:
    """Read a project from {relative path: text}. Paths use '/' and are relative to the project root."""
    if len(files) > MAX_FILES:
        raise DbtProjectError(f'A lab project has at most {MAX_FILES} files.')
    files = {k.replace('\\', '/').lstrip('./'): v for k, v in files.items()}
    if 'dbt_project.yml' not in files:
        raise DbtProjectError('dbt_project.yml is missing at the project root.')
    config = _yaml(files['dbt_project.yml'], 'dbt_project.yml')
    name = config.get('name')
    if not isinstance(name, str) or not IDENT.fullmatch(name):
        raise DbtProjectError('dbt_project.yml needs a name made of letters, digits and _.')
    if target_schema not in LAYERS:
        raise DbtProjectError(f'The target schema must be a catalog layer: {", ".join(LAYERS)}.')
    model_paths = _paths(config, 'model-paths', 'models')
    seed_paths = _paths(config, 'seed-paths', 'seeds')
    snapshot_paths = _paths(config, 'snapshot-paths', 'snapshots')
    test_paths = _paths(config, 'test-paths', 'tests')
    macro_paths = _paths(config, 'macro-paths', 'macros')
    project_vars = dict(config.get('vars') or {})
    project_vars.update(variables or {})
    macros = [(path, text) for path, text in sorted(files.items())
              if _under(path, macro_paths) and path.endswith('.sql')]
    target = Target(schema=target_schema)
    project = Project(name, target, project_vars, Renderer(macros, target))
    for key in ('on-run-start', 'on-run-end'):
        if config.get(key):
            project.issues.append({'path': 'dbt_project.yml', 'message': f'{key} hooks are not run by the emulation.'})

    properties = _properties(files, model_paths + seed_paths + snapshot_paths, project)

    for path, text in sorted(files.items()):
        if path.endswith('.sql') and _under(path, model_paths):
            root = _under(path, model_paths)
            parts = path[len(root) + 1:-4].split('/')
            node = Node(f'model.{name}.{parts[-1]}', parts[-1], 'model', path, text, [name, *parts])
            node.config = _tree_config((config.get('models') or {}), node.fqn)
            _add(project, node)
        elif path.endswith('.csv') and _under(path, seed_paths):
            root = _under(path, seed_paths)
            parts = path[len(root) + 1:-4].split('/')
            node = Node(f'seed.{name}.{parts[-1]}', parts[-1], 'seed', path, '', [name, *parts])
            node.config = _tree_config((config.get('seeds') or {}), node.fqn)
            project.seeds_csv[node.unique_id] = text
            _add(project, node)
        elif path.endswith('.sql') and _under(path, snapshot_paths):
            for block in SNAPSHOT_BLOCK.finditer(text):
                snap = block.group(1)
                node = Node(f'snapshot.{name}.{snap}', snap, 'snapshot', path, block.group(2),
                            [name, *path[len(_under(path, snapshot_paths)) + 1:-4].split('/')[:-1], snap])
                node.config = _tree_config((config.get('snapshots') or {}), node.fqn)
                _add(project, node)
            if not SNAPSHOT_BLOCK.search(text):
                project.issues.append({'path': path, 'message': 'No {% snapshot name %} ... {% endsnapshot %} block.'})
        elif path.endswith('.sql') and _under(path, test_paths):
            test_name = path.rsplit('/', 1)[-1][:-4]
            node = Node(f'test.{name}.{test_name}', test_name, 'test', path, text, [name, test_name])
            node.config = _tree_config((config.get('data_tests') or config.get('tests') or {}), node.fqn)
            _add(project, node)

    for node in list(project.nodes.values()):
        props = properties.get((node.resource_type, node.name))
        if props:
            node.description = str(props.get('description') or '')
            node.config.update({k: v for k, v in (props.get('config') or {}).items()})
            for column in props.get('columns') or []:
                if isinstance(column, dict) and column.get('name'):
                    node.columns[str(column['name'])] = str(column.get('description') or '')
    _parse(project)
    _generic_tests(project, properties)
    _resolve(project)
    return project


def _add(project: Project, node: Node) -> None:
    if not IDENT.fullmatch(node.name):
        project.issues.append({'path': node.path, 'message': f'{node.name}: node names use letters, digits and _.'})
        return
    clash = project.by_name(node.name, ('model', 'seed', 'snapshot')) if node.resource_type != 'test' else None
    if clash is not None or node.unique_id in project.nodes:
        raise DbtProjectError(f'Two resources are named {node.name} ({clash.path if clash else node.path} and {node.path}).')
    project.nodes[node.unique_id] = node


def _properties(files: dict[str, str], roots: list[str], project: Project) -> dict[tuple[str, str], dict]:
    found: dict[tuple[str, str], dict] = {}
    for path, text in sorted(files.items()):
        if not (path.endswith('.yml') or path.endswith('.yaml')) or not _under(path, roots):
            continue
        document = _yaml(text, path)
        if not isinstance(document, dict):
            continue
        for kind, key in (('model', 'models'), ('seed', 'seeds'), ('snapshot', 'snapshots')):
            for entry in document.get(key) or []:
                if isinstance(entry, dict) and entry.get('name'):
                    found[(kind, str(entry['name']))] = {**entry, '_path': path}
        for source in document.get('sources') or []:
            if not isinstance(source, dict) or not source.get('name'):
                continue
            schema = str(source.get('schema') or source['name'])
            for table in source.get('tables') or []:
                if not isinstance(table, dict) or not table.get('name'):
                    continue
                identifier = str(table.get('identifier') or table['name'])
                entry = SourceTable(str(source['name']), str(table['name']), schema, identifier,
                                    str(table.get('description') or ''))
                for column in table.get('columns') or []:
                    if isinstance(column, dict) and column.get('name'):
                        entry.columns[str(column['name'])] = str(column.get('description') or '')
                project.sources[(entry.source, entry.name)] = entry
                if table.get('columns'):
                    found[('source', f'{entry.source}.{entry.name}')] = {**table, '_path': path, '_source': entry}
    return found


def _parse(project: Project) -> None:
    """Parse-mode render: collect config() calls and the refs and sources each node depends on."""
    for node in project.nodes.values():
        if node.resource_type == 'seed' or node.test:
            continue
        refs: list[str] = []
        sources: list[tuple[str, str]] = []
        configs: dict[str, Any] = {}

        def ref(*args, _refs=refs):
            name = str(args[-1]) if args else ''
            _refs.append(name)
            return Relation(project.target.schema, name)

        def source(source_name, table_name, _sources=sources):
            _sources.append((str(source_name), str(table_name)))
            return Relation('source', str(table_name))

        def config(**kwargs):
            configs.update(kwargs)
            return ''

        hooks = Hooks(ref, source, config, Relation(project.target.schema, node.name), False, project.variables)
        try:
            project.renderer.render(node.raw, hooks, node.path)
        except RenderError as error:
            node.problem = str(error)
        node.config.update(configs)
        node.refs = list(dict.fromkeys(refs))
        node.sources = list(dict.fromkeys(sources))


def _test_kwargs(value: Any) -> tuple[dict, dict]:
    """A generic test's arguments and config, in the classic form or dbt 1.10's `arguments:` form."""
    if not isinstance(value, dict):
        return {}, {}
    body = dict(value)
    config = dict(body.pop('config', None) or {})
    for key in ('severity', 'where'):
        if key in body:
            config[key] = body.pop(key)
    arguments = body.pop('arguments', None)
    if isinstance(arguments, dict):
        body.update(arguments)
    return body, config


def _generic_tests(project: Project, properties: dict) -> None:
    for (kind, name), props in properties.items():
        attached = props.get('_source') if kind == 'source' else project.by_name(name, (kind,))
        if attached is None:
            continue
        columns = props.get('columns') or []
        for column in columns:
            if not isinstance(column, dict):
                continue
            for test in (column.get('data_tests') or []) + (column.get('tests') or []):
                test_name, value = (test, {}) if isinstance(test, str) else next(iter(test.items())) if isinstance(test, dict) and test else (None, None)
                if test_name is None:
                    continue
                _add_test(project, props['_path'], kind, name, attached, str(column['name']), str(test_name), value)
        for test in (props.get('data_tests') or []) + (props.get('tests') or []):
            if isinstance(test, dict) and test:
                test_name, value = next(iter(test.items()))
                column_name = value.get('column_name') if isinstance(value, dict) else None
                _add_test(project, props['_path'], kind, name, attached, column_name, str(test_name), value)


def _add_test(project, path, kind, name, attached, column, test_name, value) -> None:
    if test_name not in GENERIC_TESTS:
        project.issues.append({'path': path, 'message': f'Generic test {test_name} is not emulated (supported: {", ".join(GENERIC_TESTS)}).'})
        return
    kwargs, config = _test_kwargs(value)
    clean = lambda text: re.sub(r'[^A-Za-z0-9_]+', '_', str(text))
    # dbt's generated names: <test>_<model>_<column>[__<arguments>], source tests prefixed with source_.
    parts = [('source_' if kind == 'source' else '') + test_name, clean(name), column or '']
    if test_name == 'accepted_values':
        parts.append('_' + '__'.join(clean(v) for v in kwargs.get('values') or []))
    elif test_name == 'relationships':
        parts.append('_' + clean(kwargs.get('field', '')) + '__' + clean(kwargs.get('to', '')))
    test_id = '_'.join(p for p in parts if p != '')
    node = Node(f'test.{project.name}.{test_id}', test_id, 'test', path, '', [project.name, test_id])
    node.config = config
    node.test = {'name': test_name, 'column': column, 'kwargs': kwargs, 'kind': kind, 'attached': name}
    if kind == 'source':
        node.sources = [(attached.source, attached.name)]
    else:
        node.refs = [name]
    if test_name == 'relationships':
        target = re.fullmatch(r"\s*ref\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\)\s*", str(kwargs.get('to', '')))
        source = re.fullmatch(r"\s*source\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]\s*\)\s*", str(kwargs.get('to', '')))
        if target:
            node.refs.append(target.group(1))
        elif source:
            node.sources.append((source.group(1), source.group(2)))
        else:
            node.problem = "relationships needs to: ref('model') or source('source', 'table')"
    if node.unique_id in project.nodes:
        return
    project.nodes[node.unique_id] = node


def _resolve(project: Project) -> None:
    """Dependencies, relations and schemas (dbt's generate_schema_name, or the project's override)."""
    for node in project.nodes.values():
        deps = []
        for ref in node.refs:
            other = project.by_name(ref)
            if other is None:
                node.problem = node.problem or f"ref('{ref}') does not match a model, seed or snapshot"
            else:
                deps.append(other.unique_id)
        for source in node.sources:
            if source not in project.sources:
                node.problem = node.problem or f"source('{source[0]}', '{source[1]}') is not declared in a sources: file"
        node.depends_on = list(dict.fromkeys(deps))
        if node.resource_type in ('model', 'seed', 'snapshot'):
            node.relation = _relation(project, node)
        if node.resource_type == 'model' and node.materialized not in MATERIALIZATIONS:
            node.problem = node.problem or f"materialized='{node.materialized}' is not emulated ({', '.join(MATERIALIZATIONS)})"
        unsupported = sorted(set(node.config) & UNSUPPORTED_CONFIG)
        if unsupported:
            project.issues.append({'path': node.path, 'message': f"{node.name}: {', '.join(unsupported)} not emulated (ignored)."})


def _relation(project: Project, node: Node) -> Relation:
    identifier = str(node.config.get('alias') or node.name)
    if node.resource_type == 'model' and node.materialized == 'ephemeral':
        return Relation('', f'__dbt__cte__{node.name}', cte=True)
    if node.resource_type == 'snapshot' and node.config.get('target_schema'):
        schema = str(node.config['target_schema'])
    else:
        custom = node.config.get('schema')
        if project.renderer.has_macro('generate_schema_name'):
            hooks = Hooks(lambda *a: Relation('', ''), lambda *a: Relation('', ''), variables=project.variables)
            try:
                schema = project.renderer.call_macro('generate_schema_name', hooks, custom, None)
            except RenderError as error:
                node.problem = str(error)
                schema = project.target.schema
        else:
            schema = project.target.schema if custom is None else f'{project.target.schema}_{str(custom).strip()}'
    if schema not in LAYERS:
        node.problem = node.problem or (
            f"{node.name} would be built in schema '{schema}', which is not a catalog layer ({', '.join(LAYERS)}). "
            f"dbt appends a custom schema to the target schema by default; override generate_schema_name to use it as is.")
    if not IDENT.fullmatch(identifier):
        node.problem = node.problem or f'{identifier} is not a simple table name'
    return Relation(schema, identifier)


def read_seed(text: str) -> tuple[list[str], list[list[str | None]]]:
    reader = csv.reader(io.StringIO(text.lstrip('﻿')))
    rows = [row for row in reader if row]
    if not rows:
        raise DbtProjectError('A seed needs a header row.')
    header = [h.strip() for h in rows[0]]
    if any(not IDENT.fullmatch(h) for h in header) or len(set(header)) != len(header):
        raise DbtProjectError('Seed columns must be unique simple names.')
    body = [[cell if cell != '' else None for cell in row] for row in rows[1:]]
    if any(len(row) != len(header) for row in body):
        raise DbtProjectError('Every seed row needs as many values as the header.')
    if len(body) > 5000:
        raise DbtProjectError('A lab seed has at most 5,000 rows.')
    return header, body
