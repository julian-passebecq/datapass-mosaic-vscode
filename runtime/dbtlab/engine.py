"""Run dbt commands (build, run, test, seed, snapshot) on the local catalog, the way dbt Core with dbt-duckdb does.

- Compilation: refs, sources and {{ this }} resolve to schema.table; ephemeral models are injected as
  `__dbt__cte__<name>` CTEs; config(), var() and project macros as in dbt.
- Materializations: view, table (replacing a relation of the other type), incremental (first run and
  --full-refresh build the table; later runs render with is_incremental() true into `<name>__dbt_tmp`, then
  delete+insert on unique_key (dbt-duckdb's default; without unique_key it only inserts), append or merge),
  ephemeral. Inserts use the existing table's columns, as dbt does.
- Seeds: CSV with agate-like types (integer, double, boolean, date, timestamp, text), column_types override.
- Snapshots: timestamp and check strategies, dbt's dbt_scd_id / dbt_updated_at / dbt_valid_from /
  dbt_valid_to columns, hard_deletes ignore or invalidate (and the legacy invalidate_hard_deletes), and
  dbt_valid_to_current.
- Tests: unique, not_null, accepted_values, relationships (dbt's SQL), singular tests; severity and where.
- build: tests run after the resources they test, and a failing test (or a failed or skipped parent) skips
  everything downstream that the test's resources feed, as in dbt build.
- Selection: names, +name / name+, tag:, path:, resource_type:, source:, with --exclude; tests are selected
  eagerly (when one of their parents is), like dbt's default indirect selection.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .project import DbtProjectError, Node, Project, read_seed
from .render import Hooks, Relation, RenderError

RESOURCE_TYPES = {'build': ('seed', 'snapshot', 'model', 'test'), 'run': ('model',), 'test': ('test',),
                  'seed': ('seed',), 'snapshot': ('snapshot',), 'compile': ('model', 'snapshot', 'test')}
INT = re.compile(r'^-?\d{1,18}$')
NUM = re.compile(r'^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
STAMP = re.compile(r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$')
BOOL = {'true': True, 'false': False}
SELECTOR = re.compile(r'^(\d*\+)?([A-Za-z_]+:)?([A-Za-z0-9_./*-]+)(\+\d*)?$')


class DbtRunError(ValueError):
    pass


@dataclass
class NodeResult:
    unique_id: str
    name: str
    resource_type: str
    status: str  # success, error, skipped, pass, fail, warn
    message: str = ''
    materialized: str = ''
    relation: str | None = None
    rows_affected: int | None = None
    failures: int | None = None
    compiled: str = ''
    failing_rows: list[dict[str, Any]] = field(default_factory=list)
    path: str = ''

    def view(self) -> dict[str, Any]:
        return {'unique_id': self.unique_id, 'name': self.name, 'resource_type': self.resource_type,
                'status': self.status, 'message': self.message, 'materialized': self.materialized,
                'relation': self.relation, 'rows_affected': self.rows_affected, 'failures': self.failures,
                'compiled': self.compiled, 'failing_rows': self.failing_rows[:20], 'path': self.path}


class Runner:
    def __init__(self, catalog, project: Project, now: str | None = None):
        self.catalog = catalog
        self.db = catalog.db
        self.project = project
        self.now = now or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.compiled: dict[str, str] = {}

    # -- selection ----------------------------------------------------------------------------------------------
    def _children(self) -> dict[str, set[str]]:
        children: dict[str, set[str]] = {uid: set() for uid in self.project.nodes}
        for node in self.project.nodes.values():
            for parent in node.depends_on:
                children.setdefault(parent, set()).add(node.unique_id)
        return children

    def _walk(self, start: str, edges: dict[str, set[str]], depth: int | None) -> set[str]:
        seen, frontier, level = {start}, [start], 0
        while frontier and (depth is None or level < depth):
            frontier = [n for node in frontier for n in edges.get(node, ()) if n not in seen]
            seen.update(frontier)
            level += 1
        return seen

    def _match(self, method: str | None, value: str) -> set[str]:
        nodes = self.project.nodes.values()
        pattern = re.compile('^' + re.escape(value).replace(r'\*', '.*') + '$')
        if method in (None, 'fqn'):
            return {n.unique_id for n in nodes if pattern.match(n.name) or pattern.match('.'.join(n.fqn))}
        if method == 'tag':
            return {n.unique_id for n in nodes if value in (n.config.get('tags') or [])}
        if method == 'path':
            prefix = value.rstrip('/')
            return {n.unique_id for n in nodes if n.path == prefix or n.path.startswith(prefix + '/')}
        if method == 'resource_type':
            return {n.unique_id for n in nodes if n.resource_type == value}
        if method == 'source':
            source, _, table = value.partition('.')
            return {n.unique_id for n in nodes
                    if any(s == source and (not table or t == table) for s, t in n.sources)}
        raise DbtRunError(f'Selector method {method}: is not emulated (use a name, tag:, path:, resource_type: or source:).')

    def select(self, select: list[str] | None, exclude: list[str] | None) -> set[str]:
        parents = {uid: set(n.depends_on) for uid, n in self.project.nodes.items()}
        children = self._children()

        def resolve(expressions: list[str]) -> set[str]:
            chosen: set[str] = set()
            for expression in expressions:
                for part in expression.split():
                    match = SELECTOR.fullmatch(part)
                    if not match or part.startswith('-'):
                        raise DbtRunError(f'Cannot read the selector {part!r}.')
                    up, method, value, down = match.groups()
                    base = self._match(method[:-1] if method else None, value)
                    if not base:
                        continue
                    found = set(base)
                    for uid in base:
                        if up:
                            found |= self._walk(uid, parents, int(up[:-1]) if up[:-1] else None)
                        if down:
                            found |= self._walk(uid, children, int(down[1:]) if down[1:] else None)
                    chosen |= found
            return chosen

        chosen = resolve(select) if select else set(self.project.nodes)
        # Eager indirect selection: a test runs when one of the resources it tests is selected.
        for node in self.project.nodes.values():
            if node.resource_type == 'test' and node.depends_on and any(p in chosen for p in node.depends_on):
                chosen.add(node.unique_id)
        if exclude:
            chosen -= resolve(exclude)
        return chosen

    def _order(self, chosen: set[str], command: str) -> list[Node]:
        """Topological order. In build, a test also comes before everything downstream of all it tests, since
        its failure skips those nodes (dbt build's test edges)."""
        ancestors = self._ancestors()
        deps = {uid: set(self.project.nodes[uid].depends_on) for uid in self.project.nodes}
        if command == 'build':
            tests = [uid for uid in chosen if self.project.nodes[uid].resource_type == 'test' and self.project.nodes[uid].depends_on]
            for uid in chosen:
                if self.project.nodes[uid].resource_type != 'test':
                    deps[uid] |= {t for t in tests if set(self.project.nodes[t].depends_on) <= ancestors[uid]}
        depth: dict[str, int] = {}

        def level(uid: str, stack=()) -> int:
            if uid in depth:
                return depth[uid]
            if uid in stack:
                raise DbtRunError(f'Dependency cycle through {self.project.nodes[uid].name}.')
            value = 1 + max([level(p, stack + (uid,)) for p in deps[uid]] or [-1])
            depth[uid] = value
            return value

        for uid in self.project.nodes:
            level(uid)
        rank = {'seed': 0, 'snapshot': 1, 'model': 1, 'test': 2}
        nodes = [self.project.nodes[uid] for uid in chosen]
        return sorted(nodes, key=lambda n: (depth[n.unique_id], rank[n.resource_type], n.name))

    # -- compilation ----------------------------------------------------------------------------------------------
    def _hooks(self, node: Node, ctes: list[str], incremental: bool = False) -> Hooks:
        def ref(*args):
            name = str(args[-1])
            other = self.project.by_name(name)
            if other is None:
                raise RenderError(f"ref('{name}') does not match a model, seed or snapshot")
            if name not in node.refs:
                # dbt parses with is_incremental() false: a ref only reached in an incremental run is unknown.
                raise RenderError(
                    f'Compilation Error: dbt was unable to infer all dependencies for the model "{node.name}". '
                    'This typically happens when ref() is placed within a conditional block. To fix this, add the '
                    f"following hint to the top of the model: -- depends_on: {{{{ ref('{name}') }}}}")
            if other.materialized == 'ephemeral':
                if other.unique_id not in ctes:
                    self.compile(other, ctes)
                    ctes.append(other.unique_id)
            return other.relation

        def source(source_name, table_name):
            entry = self.project.sources.get((str(source_name), str(table_name)))
            if entry is None:
                raise RenderError(f"source('{source_name}', '{table_name}') is not declared")
            return Relation(entry.schema, entry.identifier)

        return Hooks(ref, source, lambda **kwargs: '', node.relation, incremental, self.project.variables, self.now)

    def compile(self, node: Node, ctes: list[str] | None = None, incremental: bool = False) -> str:
        own = ctes is None
        ctes = [] if ctes is None else ctes
        if node.problem:
            raise RenderError(node.problem)
        if node.test:
            sql = self._generic_test_sql(node)
        else:
            sql = self.project.renderer.render(node.raw, self._hooks(node, ctes, incremental), node.path).strip()
        if node.resource_type == 'model' and node.materialized == 'ephemeral':
            self.compiled[node.unique_id] = sql
            return sql
        if own and ctes:
            sql = _inject_ctes(sql, [(self.project.nodes[uid].relation.identifier, self.compiled[uid]) for uid in ctes])
        self.compiled[node.unique_id] = sql
        return sql

    def _generic_test_sql(self, node: Node) -> str:
        test = node.test
        kwargs = test['kwargs']
        if test['kind'] == 'source':
            entry = self.project.sources[tuple(test['attached'].split('.', 1))] if '.' in test['attached'] else None
            model = f'{entry.schema}.{entry.identifier}' if entry else test['attached']
        else:
            model = str(self.project.by_name(test['attached']).relation)
        where = node.config.get('where')
        if where:
            model = f'(select * from {model} where {where}) dbt_subquery'
        column = test['column']
        if test['name'] == 'unique':
            return (f'select {column} as unique_field, count(*) as n_records from {model} '
                    f'where {column} is not null group by {column} having count(*) > 1')
        if test['name'] == 'not_null':
            return f'select {column} from {model} where {column} is null'
        if test['name'] == 'accepted_values':
            values = ', '.join(_literal(v, kwargs.get('quote', True)) for v in kwargs.get('values') or [])
            return (f'with all_values as (select {column} as value_field, count(*) as n_records from {model} '
                    f'group by {column}) select * from all_values where value_field not in ({values})')
        target = str(kwargs.get('to', ''))
        field_name = kwargs.get('field')
        found = re.fullmatch(r"\s*ref\(\s*['\"](\w+)['\"]\s*\)\s*", target)
        source = re.fullmatch(r"\s*source\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]\s*\)\s*", target)
        if found:
            parent = str(self.project.by_name(found.group(1)).relation)
        elif source and (source.group(1), source.group(2)) in self.project.sources:
            entry = self.project.sources[(source.group(1), source.group(2))]
            parent = f'{entry.schema}.{entry.identifier}'
        else:
            raise RenderError('relationships needs to: and field:')
        return (f'with child as (select {column} as from_field from {model} where {column} is not null), '
                f'parent as (select {field_name} as to_field from {parent}) '
                f'select from_field from child left join parent on child.from_field = parent.to_field '
                f'where parent.to_field is null')

    # -- catalog helpers --------------------------------------------------------------------------------------------
    def _kind(self, relation: Relation) -> str | None:
        row = self.db.execute('SELECT table_type FROM information_schema.tables WHERE table_catalog = current_database() '
                              'AND table_schema = ? AND table_name = ?', [relation.schema, relation.identifier]).fetchone()
        return None if row is None else ('view' if row[0] == 'VIEW' else 'table')

    def _columns(self, relation: Relation) -> list[str]:
        return [r[0] for r in self.db.execute(
            'SELECT column_name FROM information_schema.columns WHERE table_catalog = current_database() '
            'AND table_schema = ? AND table_name = ? ORDER BY ordinal_position', [relation.schema, relation.identifier]).fetchall()]

    def _sql(self, sql: str, producer: str) -> dict:
        return self.catalog.execute(sql, producer)

    def _count(self, relation: Relation | str) -> int:
        return int(self.db.execute(f'SELECT COUNT(*) FROM {relation}').fetchone()[0])

    def _drop_other(self, relation: Relation, wanted: str) -> None:
        kind = self._kind(relation)
        if kind and kind != wanted:
            self._sql(f'DROP {kind.upper()} IF EXISTS {relation}', 'dbt')

    # -- materializations -------------------------------------------------------------------------------------------
    def _model(self, node: Node, full_refresh: bool) -> NodeResult:
        result = NodeResult(node.unique_id, node.name, 'model', 'success', materialized=node.materialized,
                            relation=str(node.relation), path=node.path)
        producer = f'dbt:{node.name}'
        relation = node.relation
        if node.materialized == 'view':
            sql = self.compile(node)
            self._drop_other(relation, 'view')
            self._sql(f'CREATE OR REPLACE VIEW {relation} AS (\n{sql}\n)', producer)
            result.message = f'OK created sql view model {relation}'
        elif node.materialized == 'table' or (node.materialized == 'incremental' and
                                               (full_refresh or self._kind(relation) != 'table')):
            sql = self.compile(node)
            self._drop_other(relation, 'table')
            self._sql(f'CREATE OR REPLACE TABLE {relation} AS (\n{sql}\n)', producer)
            result.rows_affected = self._count(relation)
            result.message = f'OK created sql {node.materialized} model {relation}'
        else:
            sql = self.compile(node, incremental=True)
            temp = Relation(relation.schema, f'{relation.identifier}__dbt_tmp')
            self._sql(f'CREATE OR REPLACE TABLE {temp} AS (\n{sql}\n)', producer)
            try:
                result.rows_affected = self._incremental(node, relation, temp, producer)
            finally:
                self._sql(f'DROP TABLE IF EXISTS {temp}', producer)
            result.message = f'OK created sql incremental model {relation}'
        return result

    def _incremental(self, node: Node, relation: Relation, temp: Relation, producer: str) -> int:
        strategy = node.config.get('incremental_strategy') or 'delete+insert'
        unique_key = node.config.get('unique_key')
        keys = [unique_key] if isinstance(unique_key, str) else list(unique_key or [])
        columns = self._columns(relation)
        incoming = set(self._columns(temp))
        missing = [c for c in columns if c not in incoming]
        if missing:
            raise DbtRunError(f'The incremental query no longer returns {", ".join(missing)} (on_schema_change is ignore).')
        names = ', '.join(f'"{c}"' for c in columns)
        rows = self._count(temp)
        if strategy not in ('append', 'delete+insert', 'merge'):
            raise DbtRunError(f"incremental_strategy '{strategy}' is not emulated (append, delete+insert, merge).")
        if strategy == 'merge':
            if not keys:
                raise DbtRunError('The merge strategy needs a unique_key.')
            on = ' AND '.join(f't."{k}" = s."{k}"' for k in keys)
            updates = ', '.join(f'"{c}" = s."{c}"' for c in columns if c not in keys)
            values = ', '.join(f's."{c}"' for c in columns)
            self._sql(f'MERGE INTO {relation} AS t USING {temp} AS s ON {on} '
                      + (f'WHEN MATCHED THEN UPDATE SET {updates} ' if updates else '')
                      + f'WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({values})', producer)
            return rows
        if strategy == 'delete+insert' and keys:
            key_list = ', '.join(f'"{k}"' for k in keys)
            self._sql(f'DELETE FROM {relation} WHERE ({key_list}) IN (SELECT ({key_list}) FROM {temp})', producer)
        self._sql(f'INSERT INTO {relation} ({names}) (SELECT {names} FROM {temp})', producer)
        return rows

    def _seed(self, node: Node) -> NodeResult:
        header, body = read_seed(self.project.seeds_csv[node.unique_id])
        overrides = {str(k): str(v) for k, v in (node.config.get('column_types') or {}).items()}
        types = [overrides.get(name) or _seed_type([row[i] for row in body]) for i, name in enumerate(header)]
        for kind in types:
            if not re.fullmatch(r'[A-Za-z]+(\(\d+(,\s*\d+)?\))?', kind):
                raise DbtRunError(f'Unsupported column type {kind!r} in column_types.')
        relation = node.relation
        self._drop_other(relation, 'table')
        columns = ', '.join(f'"{name}" {kind}' for name, kind in zip(header, types))
        self.db.execute('BEGIN TRANSACTION')
        try:
            self.db.execute(f'CREATE OR REPLACE TABLE {relation} ({columns})')
            if body:
                placeholders = ', '.join(f'CAST(? AS {kind})' for kind in types)
                self.db.executemany(f'INSERT INTO {relation} VALUES ({placeholders})',
                                    [[_seed_value(v, k) for v, k in zip(row, types)] for row in body])
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        self.catalog._touch(str(relation), [], f'dbt seed {node.name}')
        return NodeResult(node.unique_id, node.name, 'seed', 'success', f'OK loaded seed file {relation}', 'seed',
                          str(relation), len(body), path=node.path)

    def _snapshot(self, node: Node) -> NodeResult:
        config = node.config
        strategy = config.get('strategy')
        key = config.get('unique_key')
        if strategy not in ('timestamp', 'check') or not key:
            raise DbtRunError("A snapshot needs strategy='timestamp' or 'check' and a unique_key.")
        keys = [key] if isinstance(key, str) else list(key)
        key_sql = " || '|' || ".join(f"coalesce(cast({k} as varchar), '')" for k in keys) if len(keys) > 1 else \
            f"coalesce(cast({keys[0]} as varchar), '')"
        hard = config.get('hard_deletes') or ('invalidate' if config.get('invalidate_hard_deletes') else 'ignore')
        if hard not in ('ignore', 'invalidate'):
            raise DbtRunError(f"hard_deletes='{hard}' is not emulated (ignore, invalidate).")
        current_to = config.get('dbt_valid_to_current')
        open_end = str(current_to) if current_to else 'null'
        stamp = f"cast('{self.now}' as timestamp)"
        if strategy == 'timestamp':
            updated_at = config.get('updated_at')
            if not updated_at:
                raise DbtRunError("The timestamp strategy needs updated_at.")
            valid = f'cast({updated_at} as timestamp)'
        else:
            valid = stamp
        sql = self.compile(node)
        relation = node.relation
        producer = f'dbt:{node.name}'
        scd = f"md5({key_sql} || '|' || coalesce(cast({valid} as varchar), ''))"
        new_columns = (f"{scd} as dbt_scd_id, {valid} as dbt_updated_at, {valid} as dbt_valid_from, "
                       f"cast({open_end} as timestamp) as dbt_valid_to")
        if self._kind(relation) != 'table':
            self._drop_other(relation, 'table')
            self._sql(f'CREATE OR REPLACE TABLE {relation} AS (SELECT *, {new_columns} FROM (\n{sql}\n) sbq)', producer)
            return NodeResult(node.unique_id, node.name, 'snapshot', 'success', f'OK snapshotted {relation}', 'snapshot',
                              str(relation), self._count(relation), compiled=sql, path=node.path)
        def is_current(alias: str) -> str:
            column = f'{alias}.dbt_valid_to'
            return f'({column} is null' + (f' or {column} = cast({open_end} as timestamp))' if current_to else ')')

        join = ' AND '.join(f'c."{k}" = s."{k}"' for k in keys)
        if strategy == 'timestamp':
            changed = f'c.dbt_valid_from < cast(s.{config["updated_at"]} as timestamp)'
            close_at = f'cast(s.{config["updated_at"]} as timestamp)'
        else:
            source_columns = self._query_columns(sql)
            check = config.get('check_cols')
            if check == 'all' or check is None:
                check = [c for c in source_columns if c not in keys]
            check = [check] if isinstance(check, str) else list(check)
            changed = ' OR '.join(f'c."{c}" IS DISTINCT FROM s."{c}"' for c in check) or 'false'
            close_at = stamp
        payload = [c for c in self._columns(relation) if not c.startswith('dbt_')]
        staged = f'(\n{sql}\n)'
        before = self._count(relation)
        temp = Relation(relation.schema, f'{relation.identifier}__dbt_tmp')
        self._sql(f'CREATE OR REPLACE TABLE {temp} AS SELECT s.*, {close_at} AS dbt_close_at FROM {staged} AS s '
                  f'JOIN (SELECT * FROM {relation} AS c WHERE {is_current("c")}) AS c ON {join} WHERE {changed}', producer)
        try:
            # Close the changed versions, then open a version for every key without a current one.
            match = ' AND '.join(f't."{k}" = x."{k}"' for k in keys)
            self._sql(f'UPDATE {relation} AS t SET dbt_valid_to = x.dbt_close_at FROM {temp} AS x '
                      f'WHERE {match} AND {is_current("t")}', producer)
            names = ', '.join(f'"{c}"' for c in payload)
            values = ', '.join(f's."{c}"' for c in payload)
            self._sql(f'INSERT INTO {relation} ({names}, dbt_scd_id, dbt_updated_at, dbt_valid_from, dbt_valid_to) '
                      f'SELECT {values}, {scd}, {valid}, {valid}, cast({open_end} as timestamp) FROM {staged} AS s '
                      f'WHERE NOT EXISTS (SELECT 1 FROM {relation} AS c WHERE {join} AND {is_current("c")})', producer)
            if hard == 'invalidate':
                gone = ' AND '.join(f's."{k}" = t."{k}"' for k in keys)
                self._sql(f'UPDATE {relation} AS t SET dbt_valid_to = {stamp} WHERE {is_current("t")} '
                          f'AND NOT EXISTS (SELECT 1 FROM {staged} AS s WHERE {gone})', producer)
        finally:
            self._sql(f'DROP TABLE IF EXISTS {temp}', producer)
        return NodeResult(node.unique_id, node.name, 'snapshot', 'success', f'OK snapshotted {relation}', 'snapshot',
                          str(relation), self._count(relation) - before, compiled=sql, path=node.path)

    def _query_columns(self, sql: str) -> list[str]:
        return [d[0] for d in self.db.execute(f'SELECT * FROM (\n{sql}\n) q LIMIT 0').description]

    def _test(self, node: Node) -> NodeResult:
        sql = self.compile(node)
        result = NodeResult(node.unique_id, node.name, 'test', 'pass', materialized='test', compiled=sql, path=node.path)
        rows = self.catalog.query(f'SELECT * FROM (\n{sql}\n) dbt_internal_test LIMIT 21')['rows'] if sql else []
        failures = int(self.db.execute(f'SELECT COUNT(*) FROM (\n{sql}\n) dbt_internal_test').fetchone()[0])
        result.failures = failures
        result.failing_rows = rows[:20]
        severity = str(node.config.get('severity') or 'error').lower()
        if failures:
            result.status = 'warn' if severity == 'warn' else 'fail'
            result.message = f'Got {failures} result{"s" if failures != 1 else ""}, configured to {"warn" if severity == "warn" else "fail"} if != 0'
        else:
            result.message = 'PASS'
        return result

    # -- commands ---------------------------------------------------------------------------------------------------
    def run(self, command: str = 'build', select: list[str] | None = None, exclude: list[str] | None = None,
            full_refresh: bool = False) -> dict[str, Any]:
        if command not in RESOURCE_TYPES:
            raise DbtRunError(f'dbt {command} is not emulated (build, run, test, seed, snapshot, compile).')
        start = time.perf_counter()
        types = RESOURCE_TYPES[command]
        chosen = {uid for uid in self.select(select, exclude) if self.project.nodes[uid].resource_type in types}
        order = [n for n in self._order(chosen, command) if not (n.resource_type == 'model' and n.materialized == 'ephemeral')]
        ancestors = self._ancestors()
        results: dict[str, NodeResult] = {}
        for node in order:
            blocked = self._blocked(node, results, ancestors, command)
            if blocked:
                results[node.unique_id] = NodeResult(node.unique_id, node.name, node.resource_type, 'skipped',
                                                     f'SKIP (upstream {blocked})', node.materialized,
                                                     str(node.relation) if node.relation else None, path=node.path)
                continue
            try:
                if command == 'compile':
                    sql = self.compile(node)
                    results[node.unique_id] = NodeResult(node.unique_id, node.name, node.resource_type, 'success',
                                                         'compiled', node.materialized, str(node.relation) if node.relation else None,
                                                         compiled=sql, path=node.path)
                    continue
                if node.resource_type == 'seed':
                    outcome = self._seed(node)
                elif node.resource_type == 'snapshot':
                    outcome = self._snapshot(node)
                elif node.resource_type == 'test':
                    outcome = self._test(node)
                else:
                    outcome = self._model(node, full_refresh)
                outcome.compiled = outcome.compiled or self.compiled.get(node.unique_id, '')
                results[node.unique_id] = outcome
            except (RenderError, DbtRunError, DbtProjectError) as error:
                results[node.unique_id] = self._error(node, str(error))
            except Exception as error:  # DuckDB's message is the lesson (Binder Error, Catalog Error...)
                results[node.unique_id] = self._error(node, _first_line(error))
        ordered = [results[n.unique_id] for n in order]
        counts = {status: sum(1 for r in ordered if r.status == status)
                  for status in ('success', 'pass', 'warn', 'fail', 'error', 'skipped')}
        failed = counts['error'] + counts['fail']
        return {'command': command, 'status': 'error' if failed else 'success', 'results': [r.view() for r in ordered],
                'counts': counts, 'elapsed_ms': round((time.perf_counter() - start) * 1000, 1), 'now': self.now}

    def _error(self, node: Node, message: str) -> NodeResult:
        return NodeResult(node.unique_id, node.name, node.resource_type, 'error', message, node.materialized,
                          str(node.relation) if node.relation else None,
                          compiled=self.compiled.get(node.unique_id, ''), path=node.path)

    def _ancestors(self) -> dict[str, set[str]]:
        memo: dict[str, set[str]] = {}

        def of(uid: str) -> set[str]:
            if uid not in memo:
                memo[uid] = set()
                for parent in self.project.nodes[uid].depends_on:
                    memo[uid] |= {parent} | of(parent)
            return memo[uid]

        for uid in self.project.nodes:
            of(uid)
        return memo

    def _blocked(self, node: Node, results: dict[str, NodeResult], ancestors: dict[str, set[str]], command: str) -> str | None:
        for parent in node.depends_on:
            done = results.get(parent)
            if done and done.status in ('error', 'skipped'):
                return done.name
        if command != 'build' or node.resource_type == 'test':
            return None
        # dbt build: a test on an upstream resource blocks what that resource feeds.
        mine = ancestors[node.unique_id]
        for uid, done in results.items():
            test = self.project.nodes[uid]
            if test.resource_type == 'test' and done.status in ('fail', 'error') and test.depends_on \
                    and set(test.depends_on) <= mine:
                return done.name
        return None


def _inject_ctes(sql: str, ctes: list[tuple[str, str]]) -> str:
    block = ',\n'.join(f'{name} as (\n{body}\n)' for name, body in ctes)
    stripped = re.sub(r'^(\s|--[^\n]*\n|/\*.*?\*/)*', '', sql, flags=re.S)
    if re.match(r'with\b', stripped, re.I):
        return f'with {block},\n' + stripped[4:].lstrip()
    return f'with {block}\n{sql}'


def _literal(value: Any, quote: bool = True) -> str:
    if not quote or isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _seed_type(values: list[str | None]) -> str:
    present = [v.strip() for v in values if v is not None and v.strip() != '']
    if not present:
        return 'INTEGER'
    if all(INT.match(v) for v in present):
        return 'INTEGER' if all(-2**31 <= int(v) < 2**31 for v in present) else 'BIGINT'
    if all(NUM.match(v) for v in present):
        return 'DOUBLE'
    if all(v.lower() in BOOL for v in present):
        return 'BOOLEAN'
    if all(DATE.match(v) for v in present):
        return 'DATE'
    if all(STAMP.match(v) for v in present):
        return 'TIMESTAMP'
    return 'VARCHAR'


def _seed_value(value: str | None, kind: str) -> Any:
    if value is None or (kind != 'VARCHAR' and value.strip() == ''):
        return None
    if kind == 'BOOLEAN':
        return BOOL.get(value.strip().lower(), value)
    return value


def _first_line(error: Exception) -> str:
    text = str(error).strip()
    return re.split(r'\n\s*LINE \d+:', text)[0].strip()[:500] or type(error).__name__
