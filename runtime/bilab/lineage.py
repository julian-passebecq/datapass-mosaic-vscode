"""SQL lineage of warehouse scripts: where each column comes from, and which columns decide the rows.

This is a static analysis of the SQL text with sqlglot (DuckDB dialect). Statements are parsed and qualified
against the catalog's column names; nothing is executed here.

- Column lineage: for every column a statement writes (CREATE TABLE/VIEW AS, INSERT ... SELECT, UPDATE SET,
  MERGE), the columns its value is computed from, through CTEs, subqueries, UNION branches and window
  functions. `sources` are the tables the statement reads; `origins` follow the tables the analyzed scripts
  build themselves back to the tables nobody builds (the sources of the warehouse).
- Row influence: the columns used in WHERE, JOIN ... ON, GROUP BY, HAVING, QUALIFY and a MERGE's conditions.
  They do not flow into a value but decide which rows exist, so a change to them changes the table too.
- Transform: copy (same name), rename, expression, aggregate, window, constant or generated (a table
  function such as generate_series).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

TRANSFORM_RANK = {'copy': 0, 'rename': 1, 'constant': -1, 'generated': 2, 'expression': 3, 'window': 4, 'aggregate': 5}
ROW_CLAUSES = (('where', 'filter'), ('having', 'filter'), ('qualify', 'filter'), ('group', 'group'))

Ref = tuple[str, str]  # (layer.table, column)


def available() -> bool:
    try:
        import sqlglot  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class ColumnInfo:
    sources: set[Ref] = field(default_factory=set)
    transforms: set[str] = field(default_factory=set)
    expressions: list[str] = field(default_factory=list)

    @property
    def transform(self) -> str:
        known = [t for t in self.transforms if t != 'constant'] or list(self.transforms) or ['constant']
        return max(known, key=lambda t: TRANSFORM_RANK[t])


@dataclass
class TableInfo:
    name: str
    kind: str = 'table'
    columns: dict[str, ColumnInfo] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    statements: list[dict[str, Any]] = field(default_factory=list)
    inputs: set[str] = field(default_factory=set)
    influence: set[tuple[str, str, str]] = field(default_factory=set)

    def column(self, name: str) -> ColumnInfo:
        if name not in self.columns:
            self.columns[name] = ColumnInfo()
            self.order.append(name)
        return self.columns[name]


class Lineage:
    """Accumulates statements in order; `view()` gives the lineage of everything analyzed so far."""

    def __init__(self, schema: dict[str, list[str]] | None = None):
        self.schema: dict[str, list[str]] = {k.lower(): [c.lower() for c in v] for k, v in (schema or {}).items()}
        self.tables: dict[str, TableInfo] = {}
        self.issues: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []
        self.notes: list[str] = []

    # -- statements -------------------------------------------------------------------------------------------
    def add_script(self, path: str, text: str) -> None:
        from .script import ScriptError, split_script
        try:
            statements = split_script(text)
        except ScriptError as error:
            self.issues.append({'path': path, 'line': 1, 'message': str(error)})
            return
        for statement in statements:
            self.add_statement(path, statement.line, statement.text)

    def add_statement(self, path: str, line: int, text: str) -> None:
        if not available():
            if not any(i.get('code') == 'sqlglot' for i in self.issues):
                self.issues.append({'path': path, 'line': line, 'code': 'sqlglot',
                                    'message': 'SQL lineage needs the sqlglot package: run Setup runtime again.'})
            return
        import sqlglot
        from sqlglot import exp
        try:
            tree = sqlglot.parse_one(text, read='duckdb')
        except Exception as error:
            self.issues.append({'path': path, 'line': line, 'message': f'Not parsed: {_first_line(error)}'})
            return
        where = {'path': path, 'line': line}
        try:
            if isinstance(tree, exp.Create):
                self._create(tree, where)
            elif isinstance(tree, exp.Insert):
                self._insert(tree, where)
            elif isinstance(tree, exp.Update):
                self._update(tree, where)
            elif isinstance(tree, exp.Merge):
                self._merge(tree, where)
            elif isinstance(tree, exp.Delete):
                self._delete(tree, where)
            elif isinstance(tree, exp.Query):
                self.queries.append({**where, 'outputs': self._query_outputs(tree)[0]})
        except Exception as error:  # an unusual statement must not hide the lineage of the others
            self.issues.append({**where, 'message': f'Lineage not computed: {_first_line(error)}'})
        for note in dict.fromkeys(self.notes):
            self.issues.append({**where, 'message': note})
        self.notes.clear()

    def add_query(self, text: str) -> dict[str, ColumnInfo]:
        """Lineage of a standalone SELECT (for example a report query), by output column."""
        import sqlglot
        outputs, _, _ = self._query_outputs(sqlglot.parse_one(text, read='duckdb'))
        return outputs

    def _create(self, tree, where) -> None:
        from sqlglot import exp
        target = tree.this.this if isinstance(tree.this, exp.Schema) else tree.this
        name = _table_name(target)
        if not name:
            return
        kind = 'view' if str(tree.args.get('kind', '')).upper() == 'VIEW' else 'table'
        query = tree.expression
        info = self._fresh_table(name, kind, 'CREATE ' + kind.upper(), where)
        if isinstance(query, exp.Query):
            outputs, inputs, influence = self._query_outputs(query)
            self._apply(info, outputs, inputs, influence)
            self.schema[name] = list(outputs)
        elif isinstance(tree.this, exp.Schema):
            columns = [c.name.lower() for c in tree.this.expressions if isinstance(c, exp.ColumnDef)]
            for column in columns:
                info.column(column)
            self.schema[name] = columns

    def _insert(self, tree, where) -> None:
        from sqlglot import exp
        target = tree.this
        listed = [c.name.lower() for c in target.expressions] if isinstance(target, exp.Schema) else None
        name = _table_name(target.this if isinstance(target, exp.Schema) else target)
        if not name:
            return
        info = self._table(name, 'INSERT', where)
        query = tree.expression
        if not isinstance(query, exp.Query):
            return
        outputs, inputs, influence = self._query_outputs(query)
        if tree.args.get('by_name'):
            mapped = outputs
        else:
            names = listed or self.schema.get(name) or list(outputs)
            mapped = {names[i]: info_ for i, info_ in enumerate(outputs.values()) if i < len(names)}
        self._apply(info, mapped, inputs, influence)

    def _update(self, tree, where) -> None:
        from sqlglot import exp
        name = _table_name(tree.this)
        if not name:
            return
        info = self._table(name, 'UPDATE', where)
        select = exp.select(*[exp.alias_(e.expression.copy(), e.this.name) for e in tree.expressions]) \
            .from_(tree.this.copy())
        if tree.args.get('from_'):
            for source in [tree.args['from_'].this, *tree.args['from_'].expressions]:
                select = select.join(source.copy(), join_type='cross')
        if tree.args.get('where'):
            select = select.where(tree.args['where'].this.copy())
        outputs, inputs, influence = self._query_outputs(select)
        inputs.discard(name)
        self._apply(info, outputs, inputs, influence, self_name=name)

    def _merge(self, tree, where) -> None:
        from sqlglot import exp
        name = _table_name(tree.this)
        if not name:
            return
        info = self._table(name, 'MERGE', where)
        using = tree.args['using'].copy()
        assignments: list[tuple[str, Any]] = []
        conditions = [tree.args['on'].copy()]
        for when in tree.args['whens'].expressions:
            then = when.args.get('then')
            if when.args.get('condition') is not None:
                conditions.append(when.args['condition'].copy())
            if isinstance(then, exp.Update):
                assignments += [(e.this.name.lower(), e.expression) for e in then.expressions]
            elif isinstance(then, exp.Insert) and isinstance(then.this, exp.Tuple) \
                    and isinstance(then.expression, exp.Tuple):
                assignments += [(c.name.lower(), v) for c, v in zip(then.this.expressions, then.expression.expressions)]
        select = exp.select(*[exp.alias_(value.copy(), f'_c{i}') for i, (_, value) in enumerate(assignments)] or ['1'])
        select = select.from_(using).join(tree.this.copy(), join_type='cross').where(exp.and_(*conditions))
        outputs, inputs, influence = self._query_outputs(select)
        values = list(outputs.values())
        mapped: dict[str, ColumnInfo] = {}
        for (column, _), value in zip(assignments, values):
            transforms = set(value.transforms)
            if transforms == {'rename'} and {c for _, c in value.sources} == {column}:
                transforms = {'copy'}  # the synthetic query aliases every value _c<n>
            mapped.setdefault(column, ColumnInfo()).sources |= value.sources
            mapped[column].transforms |= transforms
            mapped[column].expressions += value.expressions
        inputs.discard(name)
        self._apply(info, mapped, inputs, {(t, c, 'merge') for t, c, _ in influence}, self_name=name)

    def _delete(self, tree, where) -> None:
        from sqlglot import exp
        name = _table_name(tree.this)
        if not name:
            return
        info = self._table(name, 'DELETE', where)
        if tree.args.get('where'):
            select = exp.select('1').from_(tree.this.copy()).where(tree.args['where'].this.copy())
            _, inputs, influence = self._query_outputs(select)
            inputs.discard(name)
            info.inputs |= inputs
            info.influence |= {x for x in influence if x[0] != name}

    # -- helpers ----------------------------------------------------------------------------------------------
    def _fresh_table(self, name: str, kind: str, statement: str, where) -> TableInfo:
        previous = self.tables.get(name)
        info = TableInfo(name, kind, statements=(previous.statements if previous else []))
        info.statements.append({**where, 'kind': statement})
        self.tables[name] = info
        return info

    def _table(self, name: str, statement: str, where) -> TableInfo:
        info = self.tables.get(name)
        if info is None:
            info = self.tables[name] = TableInfo(name, 'table')
            for column in self.schema.get(name, []):
                info.column(column)
        info.statements.append({**where, 'kind': statement})
        return info

    def _apply(self, info: TableInfo, outputs: dict[str, ColumnInfo], inputs: set[str],
               influence: set[tuple[str, str, str]], self_name: str | None = None) -> None:
        for column, value in outputs.items():
            target = info.column(column)
            target.sources |= {ref for ref in value.sources if ref[0] != self_name or ref[1] != column}
            target.transforms |= value.transforms
            target.expressions += [e for e in value.expressions if e not in target.expressions][:3]
        info.inputs |= {i for i in inputs if i != info.name}
        info.influence |= influence

    def _schema_for_sqlglot(self) -> dict[str, dict[str, dict[str, str]]]:
        nested: dict[str, dict[str, dict[str, str]]] = {}
        for name, columns in self.schema.items():
            if '.' in name and columns:
                layer, table = name.split('.', 1)
                nested.setdefault(layer, {})[table] = {c: 'TEXT' for c in columns}
        return nested

    def _query_outputs(self, query) -> tuple[dict[str, ColumnInfo], set[str], set[tuple[str, str, str]]]:
        from sqlglot import exp
        from sqlglot.optimizer.qualify import qualify
        from sqlglot.optimizer.scope import build_scope, traverse_scope
        qualified = qualify(query.copy(), dialect='duckdb', schema=self._schema_for_sqlglot(),
                            validate_qualify_columns=False, identify=False, quote_identifiers=False)
        root = build_scope(qualified)
        if root is None:
            return {}, set(), set()
        resolver = _Resolver()
        outputs: dict[str, ColumnInfo] = {}
        for index, column in enumerate(resolver.output_names(root)):
            if column == '*':
                self.notes.append('SELECT * over a table whose columns are unknown: build that table first.')
                continue
            info = outputs.setdefault(column, ColumnInfo())
            for projection, scope in resolver.projections(root, index):
                sources, transform = resolver.projection(scope, projection)
                info.sources |= sources
                info.transforms.add(transform)
                if transform != 'constant':
                    text = _expression_text(projection)
                    if text not in info.expressions:
                        info.expressions.append(text)
        inputs: set[str] = set()
        influence: set[tuple[str, str, str]] = set()
        for scope in traverse_scope(qualified):
            tables = [_table_name(s) for s in scope.sources.values() if isinstance(s, exp.Table)]
            inputs |= {t for t in tables if t}
            select = scope.expression
            if not isinstance(select, exp.Select):
                continue
            for key, role in ROW_CLAUSES:
                clause = select.args.get(key)
                if clause is not None:
                    influence |= {(t, c, role) for t, c in resolver.columns_in(scope, clause)}
            for join in select.args.get('joins') or []:
                if join.args.get('on') is not None:
                    influence |= {(t, c, 'join') for t, c in resolver.columns_in(scope, join.args['on'])}
                for using in join.args.get('using') or []:
                    influence |= {(t, using.name.lower(), 'join') for t in tables if t}
        return outputs, inputs, influence

    # -- results ----------------------------------------------------------------------------------------------
    def origins(self, ref: Ref, seen: frozenset = frozenset()) -> set[Ref]:
        table, column = ref
        info = self.tables.get(table)
        # A column with no sources (typed in, generated) is where the data enters: it is its own origin.
        if info is None or column not in info.columns or ref in seen or not info.columns[column].sources:
            return {ref}
        found: set[Ref] = set()
        for source in info.columns[column].sources:
            found |= self.origins(source, seen | {ref})
        return found

    def impact(self, ref: Ref) -> list[dict[str, str]]:
        """What a change to `ref` reaches: column values computed from it (value), and tables whose rows it
        decides through a filter, join or grouping (rows). A table whose rows change reaches everything that
        reads it."""
        reached: dict[Ref, str] = {}
        rows: set[str] = set()
        frontier = [ref]
        while frontier:
            current = frontier.pop()
            for table in self.tables.values():
                if table.name not in rows and any((t, c) == current for t, c, _ in table.influence):
                    rows.add(table.name)
                    frontier += [(table.name, column) for column in table.order]
                for column, info in table.columns.items():
                    target = (table.name, column)
                    if current in info.sources and target not in reached:
                        reached[target] = 'value'
                        frontier.append(target)
        out = [{'table': t, 'column': c, 'effect': e} for (t, c), e in sorted(reached.items()) if t not in rows]
        out += [{'table': t, 'column': '*', 'effect': 'rows'} for t in sorted(rows)]
        return sorted(out, key=lambda r: (r['table'], r['column']))

    def view(self) -> dict[str, Any]:
        built = set(self.tables)
        referenced: set[str] = set()
        for info in self.tables.values():
            referenced |= info.inputs
        tables = []
        for name in sorted(referenced - built):
            tables.append({'name': name, 'kind': 'source', 'columns': self.schema.get(name, []),
                           'statements': [], 'inputs': []})
        for info in self.tables.values():
            tables.append({'name': info.name, 'kind': info.kind, 'columns': list(info.order),
                           'statements': info.statements, 'inputs': sorted(info.inputs)})
        columns = []
        for info in self.tables.values():
            for column in info.order:
                value = info.columns[column]
                columns.append({
                    'table': info.name, 'column': column, 'transform': value.transform,
                    'expression': value.expressions[0] if value.expressions else '',
                    'sources': sorted(f'{t}.{c}' for t, c in value.sources),
                    'origins': sorted(f'{t}.{c}' for t, c in set().union(*[self.origins(s) for s in value.sources])
                                      ) if value.sources else [],
                })
        influence = []
        for info in self.tables.values():
            for table, column, role in sorted(info.influence):
                influence.append({'table': info.name, 'source': f'{table}.{column}', 'role': role,
                                  'origins': sorted(f'{t}.{c}' for t, c in self.origins((table, column)))})
        return {'tables': tables, 'columns': columns, 'influence': influence, 'issues': self.issues,
                'truth': 'static analysis of the SQL text (sqlglot, DuckDB dialect); nothing executed'}


class _Resolver:
    """Resolves qualified columns through sqlglot scopes down to physical tables."""

    def __init__(self):
        self.seen: set[tuple[int, str]] = set()

    def output_names(self, scope) -> list[str]:
        if scope.set_operation_scopes:
            return self.output_names(scope.set_operation_scopes[0])
        return [p.alias_or_name.lower() for p in scope.expression.selects]

    def projections(self, scope, index: int) -> Iterable[tuple[Any, Any]]:
        if scope.set_operation_scopes:
            for branch in scope.set_operation_scopes:
                yield from self.projections(branch, index)
            return
        selects = scope.expression.selects
        if index < len(selects):
            yield selects[index], scope

    def projection(self, scope, projection) -> tuple[set[Ref], str]:
        from sqlglot import exp
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        sources = self.columns_in(scope, inner)
        generated = any(self._generated(scope, c) for c in inner.find_all(exp.Column))
        if inner.find(exp.Window) is not None:  # before aggregates: LEAD, LAG and SUM OVER are aggregate classes
            transform = 'window'
        elif inner.find(exp.AggFunc) is not None:
            transform = 'aggregate'
        elif isinstance(inner, exp.Column):
            transform = self._column_transform(scope, inner, projection.alias_or_name.lower())
        elif not list(inner.find_all(exp.Column)):
            transform = 'constant'
        else:
            transform = 'expression'
        if generated and not sources:
            transform = 'generated'
        return sources, transform

    def _column_transform(self, scope, column, target_name: str) -> str:
        source = self._source(scope, column)
        if source is None:
            return 'expression'
        kind, value = source
        if kind == 'table':
            return 'copy' if column.name.lower() == target_name else 'rename'
        if kind == 'generated':
            return 'generated'
        transforms = set()
        for index, name in enumerate(self.output_names(value)):
            if name != column.name.lower():
                continue
            for projection, branch in self.projections(value, index):
                transforms.add(self.projection(branch, projection)[1])
        known = [t for t in transforms if t != 'constant'] or ['expression']
        best = max(known, key=lambda t: TRANSFORM_RANK[t])
        if best == 'copy' and column.name.lower() != target_name:
            return 'rename'
        return best

    def columns_in(self, scope, node) -> set[Ref]:
        from sqlglot import exp
        found: set[Ref] = set()
        subqueries = {id(s.expression): s for s in scope.subquery_scopes}
        for column in node.find_all(exp.Column):
            enclosing = column.find_ancestor(exp.Subquery)
            if enclosing is not None and id(enclosing.this) in subqueries and _is_within(enclosing, node):
                continue
            found |= self.resolve(scope, column)
        for subquery in node.find_all(exp.Subquery):
            inner = subqueries.get(id(subquery.this))
            if inner is not None:
                for index in range(len(self.output_names(inner))):
                    for projection, branch in self.projections(inner, index):
                        found |= self.projection(branch, projection)[0]
                for key, _ in ROW_CLAUSES:
                    clause = inner.expression.args.get(key)
                    if clause is not None:
                        found |= self.columns_in(inner, clause)
        return found

    def resolve(self, scope, column) -> set[Ref]:
        source = self._source(scope, column)
        if source is None:
            return set()
        kind, value = source
        if kind == 'table':
            return {(value, column.name.lower())}
        if kind == 'generated':
            return set()
        key = (id(value), column.name.lower())
        if key in self.seen:
            return set()
        self.seen.add(key)
        try:
            found: set[Ref] = set()
            for index, name in enumerate(self.output_names(value)):
                if name == column.name.lower():
                    for projection, branch in self.projections(value, index):
                        found |= self.projection(branch, projection)[0]
            return found
        finally:
            self.seen.discard(key)

    def _generated(self, scope, column) -> bool:
        source = self._source(scope, column)
        return source is not None and source[0] == 'generated'

    def _source(self, scope, column):
        from sqlglot import exp
        alias = column.table
        current = scope
        while current is not None:
            sources = current.sources
            if alias and alias in sources:
                break
            if not alias and len(sources) == 1:
                alias = next(iter(sources))
                break
            current = current.parent
        if current is None:
            return None
        source = current.sources[alias]
        if isinstance(source, exp.Table):
            name = _table_name(source)
            return ('table', name) if name else ('generated', None)
        return ('scope', source)


def _is_within(child, ancestor) -> bool:
    node = child
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def _table_name(table) -> str | None:
    from sqlglot import exp
    if not isinstance(table, exp.Table) or not isinstance(table.this, exp.Identifier):
        return None
    name = table.name.lower()
    return f'{table.db.lower()}.{name}' if table.db else name


def _expression_text(projection) -> str:
    from sqlglot import exp
    inner = projection.this if isinstance(projection, exp.Alias) else projection
    text = inner.sql(dialect='duckdb')
    return text if len(text) <= 160 else text[:157] + '...'


def _first_line(error: Exception) -> str:
    return str(error).strip().splitlines()[0][:300] if str(error).strip() else type(error).__name__
