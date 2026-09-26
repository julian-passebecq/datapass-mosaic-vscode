"""Unity Catalog row filters, column masks and column tags in the lab.

Read from grants.sql, next to GRANT / REVOKE (a documented subset of Databricks SQL):

- CREATE [OR REPLACE] FUNCTION main.<schema>.<name>(<param> <TYPE>, ...) [RETURNS <TYPE>] RETURN <expression>
  (a SQL UDF; the body may use is_account_group_member('<group>'), is_member('<group>') and current_user());
- ALTER TABLE <t> SET ROW FILTER <function> ON (<column>, ...) and ALTER TABLE <t> DROP ROW FILTER;
- ALTER TABLE <t> ALTER COLUMN <c> SET MASK <function> [USING COLUMNS (<column>, ...)] and ... DROP MASK;
- ALTER TABLE <t> ALTER COLUMN <c> SET TAGS ('<key>' = '<value>', ...) and ... UNSET TAGS ('<key>', ...).

Enforcement is real on DuckDB: a SQL task's statement (and a grading probe) is rewritten for its
principal. Every table it reads that has a row filter or masked columns becomes a derived table:
the filter keeps the rows where the function is true and each mask replaces its column. The
function body is Spark SQL, translated to DuckDB by the shared translator after the group and user
functions are resolved for the principal. Row filters and masks apply to every principal, the lab
admin included, unless the function exempts it (as in Databricks). Notebook reads of a filtered
or masked table are refused: query it from a SQL task.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

import sqlglot
from sqlglot import exp

from sqldialects import translate_expression
from sqldialects.core import DialectError

TRUTH_NOTE = ('Unity Catalog row filters and column masks translated to DuckDB, not Databricks: the rows and values '
              'are enforced for real on the lab catalog.')
ALIAS = '__uc'
_FUNCTION = re.compile(r'^CREATE\s+(OR\s+REPLACE\s+)?FUNCTION\s+(IF\s+NOT\s+EXISTS\s+)?([\w.`]+)\s*\((.*?)\)\s*'
                       r'(?:RETURNS\s+\w+\s+)?(?:COMMENT\s+\'(?:[^\']|\'\')*\'\s+)?RETURN\s+(.+)$', re.I | re.S)
_ROW_FILTER = re.compile(r'^ALTER\s+TABLE\s+(\S+)\s+(?:SET\s+ROW\s+FILTER\s+(\S+)\s+ON\s*\((.*)\)|(DROP\s+ROW\s+FILTER))$',
                         re.I | re.S)
_COLUMN = re.compile(r'^ALTER\s+TABLE\s+(\S+)\s+ALTER\s+COLUMN\s+(\S+)\s+(.+)$', re.I | re.S)
_MASK = re.compile(r'^SET\s+MASK\s+(\S+?)(?:\s+USING\s+COLUMNS\s*\((.*)\))?$', re.I | re.S)
_TAGS = re.compile(r'^(SET|UNSET)\s+TAGS\s*\((.*)\)$', re.I | re.S)
_TAG = re.compile(r"^\s*'([^']{1,64})'\s*(?:=\s*'([^']{0,128})')?\s*$")
_PARAM = re.compile(r'^\s*`?([A-Za-z_]\w*)`?\s+[A-Za-z]+(?:\s*\([\d\s,]*\))?\s*$')
GROUP_FUNCTIONS = {'is_account_group_member', 'is_member'}
USER_FUNCTIONS = {'current_user', 'session_user'}


@dataclass
class Udf:
    name: str
    parameters: list[str]
    body: str  # Spark SQL expression


@dataclass
class Governance:
    functions: dict[str, Udf] = field(default_factory=dict)
    row_filters: dict[str, tuple[str, list[str]]] = field(default_factory=dict)  # table -> (function, columns)
    masks: dict[str, dict[str, tuple[str, list[str]]]] = field(default_factory=dict)  # table -> column -> (fn, using)
    tags: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)  # table -> column -> {key: value}

    def secured(self, table: str) -> bool:
        return table in self.row_filters or bool(self.masks.get(table))

    def describe(self) -> dict[str, Any]:
        return {'functions': sorted(self.functions),
                'row_filters': {t: {'function': f, 'columns': c} for t, (f, c) in sorted(self.row_filters.items())},
                'masks': {t: {col: {'function': f, 'using': u} for col, (f, u) in sorted(m.items())}
                          for t, m in sorted(self.masks.items()) if m},
                'tags': {t: {c: dict(v) for c, v in sorted(cols.items()) if v} for t, cols in sorted(self.tags.items())}}


def handles(statement: str) -> bool:
    head = ' '.join(statement.split()[:6]).upper()
    return (head.startswith('CREATE FUNCTION') or head.startswith('CREATE OR REPLACE FUNCTION')
            or (head.startswith('ALTER TABLE') and bool(re.search(r'\b(ROW\s+FILTER|SET\s+MASK|DROP\s+MASK|SET\s+TAGS|'
                                                                   r'UNSET\s+TAGS)\b', statement, re.I))))


def _names(raw: str) -> list[str]:
    return [p.strip().strip('`').lower() for p in raw.split(',') if p.strip()]


def apply(gov: Governance, statement: str, qualify: Callable[[str, str], str],
          columns: Callable[[str], list[str]] | None) -> None:
    """One governance statement of grants.sql. qualify(kind, raw name) -> main.schema.name (raises ValueError)."""
    text = statement.strip()
    match = _FUNCTION.match(text)
    if match:
        replace, if_not_exists, raw, params, body = match.groups()
        name = qualify('FUNCTION', raw)
        if name in gov.functions and not replace:
            if if_not_exists:
                return
            raise ValueError(f"[ROUTINE_ALREADY_EXISTS] Function '{name}' already exists: use CREATE OR REPLACE FUNCTION")
        parameters = []
        for part in [p for p in params.split(',') if p.strip()]:
            param = _PARAM.match(part)
            if not param:
                raise ValueError(f"Function parameters are written '<name> <TYPE>': {part.strip()!r}")
            parameters.append(param.group(1).lower())
        _check_body(body, parameters)
        gov.functions[name] = Udf(name, parameters, body.strip())
        return
    match = _ROW_FILTER.match(text)
    if match:
        table = qualify('TABLE', match.group(1))
        if match.group(4):
            gov.row_filters.pop(table, None)
            return
        function = _function(gov, qualify, match.group(2))
        cols = _names(match.group(3))
        _check_columns(columns, table, cols)
        if len(cols) != len(gov.functions[function].parameters):
            raise ValueError(f"[ROW_FILTER_ARGUMENT_COUNT] {function} takes {len(gov.functions[function].parameters)} "
                             f"argument(s); ON (...) names {len(cols)}")
        gov.row_filters[table] = (function, cols)
        return
    match = _COLUMN.match(text)
    if not match:
        raise ValueError('Unsupported governance statement')
    table = qualify('TABLE', match.group(1))
    column = match.group(2).strip('`').lower()
    _check_columns(columns, table, [column])
    action = match.group(3).strip()
    if re.fullmatch(r'DROP\s+MASK', action, re.I):
        gov.masks.get(table, {}).pop(column, None)
        return
    mask = _MASK.match(action)
    if mask:
        function = _function(gov, qualify, mask.group(1))
        using = _names(mask.group(2) or '')
        _check_columns(columns, table, using)
        if len(gov.functions[function].parameters) != 1 + len(using):
            raise ValueError(f"[MASK_ARGUMENT_COUNT] {function} takes {len(gov.functions[function].parameters)} "
                             f"argument(s): the masked column plus {len(using)} USING COLUMNS")
        gov.masks.setdefault(table, {})[column] = (function, using)
        return
    tags = _TAGS.match(action)
    if tags:
        verb, body = tags.group(1).upper(), tags.group(2)
        current = gov.tags.setdefault(table, {}).setdefault(column, {})
        for part in [p for p in _split(body) if p.strip()]:
            tag = _TAG.match(part)
            if not tag or (verb == 'SET' and tag.group(2) is None):
                raise ValueError(f"Write tags as ('key' = 'value', ...) and UNSET TAGS ('key', ...): {part.strip()!r}")
            if verb == 'SET':
                current[tag.group(1).lower()] = tag.group(2)
            else:
                current.pop(tag.group(1).lower(), None)
        return
    raise ValueError('ALTER COLUMN supports SET MASK, DROP MASK, SET TAGS and UNSET TAGS in the lab')


def _split(body: str) -> list[str]:
    out, current, quoted = [], [], False
    for char in body:
        if char == "'":
            quoted = not quoted
        if char == ',' and not quoted:
            out.append(''.join(current))
            current = []
        else:
            current.append(char)
    out.append(''.join(current))
    return out


def _function(gov: Governance, qualify: Callable[[str, str], str], raw: str) -> str:
    name = qualify('FUNCTION', raw)
    if name not in gov.functions:
        raise ValueError(f"[ROUTINE_NOT_FOUND] Function '{name}' was not found: create it first in grants.sql")
    return name


def _check_columns(columns: Callable[[str], list[str]] | None, table: str, wanted: list[str]) -> None:
    if columns is None:
        return
    present = [c.lower() for c in columns(table.split('.', 1)[1])]
    for column in wanted:
        if column not in present:
            raise ValueError(f"[UNRESOLVED_COLUMN] Column '{column}' does not exist in {table}")


def _check_body(body: str, parameters: list[str]) -> None:
    try:
        tree = sqlglot.parse_one(body, read='databricks')
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"The function body must be one SQL expression: {str(exc).splitlines()[0]}") from None
    if tree.find(exp.Select) or tree.find(exp.Table):
        raise ValueError('The lab reads row filters and masks written as one expression over their parameters '
                         '(no subqueries or tables)')
    for column in tree.find_all(exp.Column):
        if column.name.lower() not in parameters:
            raise ValueError(f"[UNRESOLVED_COLUMN] '{column.name}' is not a parameter of the function")


def _resolved(gov: Governance, function: str, arguments: list[exp.Expression], principal: str,
              groups: set[str]) -> str:
    """The function body as DuckDB SQL, its parameters bound to the arguments and the identity functions resolved."""
    udf = gov.functions[function]
    binding = dict(zip(udf.parameters, arguments))
    tree = sqlglot.parse_one(udf.body, read='databricks')

    def swap(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Column) and not node.table and node.name.lower() in binding:
            return binding[node.name.lower()].copy()
        name = _call_name(node)
        if name in GROUP_FUNCTIONS:
            args = _call_args(node)
            if len(args) != 1 or not isinstance(args[0], exp.Literal) or not args[0].is_string:
                raise ValueError(f"{name}() takes one group name as a string")
            return exp.Boolean(this=args[0].this in groups)
        if name in USER_FUNCTIONS or isinstance(node, exp.CurrentUser):
            return exp.Literal.string(principal)
        return node

    spark = tree.transform(swap).sql(dialect='spark')
    try:
        return translate_expression(spark, 'spark').sql
    except DialectError as error:
        raise ValueError(f"{function}: {error}") from None


def _call_name(node: exp.Expression) -> str | None:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    if isinstance(node, exp.Func) and not isinstance(node, exp.Anonymous):
        return node.sql_name().lower() if node.sql_name().lower() in GROUP_FUNCTIONS | USER_FUNCTIONS else None
    return None


def _call_args(node: exp.Expression) -> list[exp.Expression]:
    return list(node.expressions) or ([node.this] if isinstance(node.this, exp.Expression) else [])


def secure_sql(sql: str, gov: Governance, principal: str, groups: set[str],
               columns: Callable[[str], list[str]]) -> tuple[str, list[str]]:
    """A DuckDB statement as the principal reads it: filtered and masked tables become derived tables."""
    if not gov.row_filters and not any(gov.masks.values()):
        return sql, []
    try:
        tree = sqlglot.parse_one(sql, read='duckdb')
    except sqlglot.errors.ParseError:
        return sql, []
    written = set()
    for kind in (exp.Insert, exp.Create, exp.Merge, exp.Update, exp.Delete):
        for node in tree.find_all(kind):
            target = node.this
            while isinstance(target, exp.Schema):
                target = target.this
            if isinstance(target, exp.Table):
                written.add(id(target))
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    notes: list[str] = []
    changed = False
    for node in list(tree.find_all(exp.Table)):
        if id(node) in written or (not node.db and node.name.lower() in ctes):
            continue
        table = f"main.{node.db.lower()}.{node.name.lower()}" if node.db else None
        if not table or not gov.secured(table):
            continue
        lab = table.split('.', 1)[1]
        present = columns(lab)
        ref = {c.lower(): exp.column(c, table=ALIAS) for c in present}
        projection = []
        masks = gov.masks.get(table, {})
        for column in present:
            mask = masks.get(column.lower())
            if mask:
                function, using = mask
                args = [ref[column.lower()]] + [ref[u] for u in using]
                projection.append(f"({_resolved(gov, function, args, principal, groups)}) AS \"{column}\"")
            else:
                projection.append(f"{ALIAS}.\"{column}\"")
        where = ''
        if table in gov.row_filters:
            function, cols = gov.row_filters[table]
            where = f" WHERE ({_resolved(gov, function, [ref[c] for c in cols], principal, groups)}) IS TRUE"
        inner = f"SELECT {', '.join(projection)} FROM {lab} AS {ALIAS}{where}"
        alias = node.alias or node.name
        node.replace(exp.Subquery(this=sqlglot.parse_one(inner, read='duckdb'),
                                  alias=exp.TableAlias(this=exp.to_identifier(alias))))
        changed = True
        what = [w for w, on in (('row filter', table in gov.row_filters), ('column masks', bool(masks))) if on]
        notes.append(f"{table}: {' and '.join(what)} applied for {principal}.")
    if not changed:
        return sql, []
    return tree.sql(dialect='duckdb'), [TRUTH_NOTE] + notes


def mask_leaks(gov: Governance, table: str, column: str, principal: str, groups: set[str],
               columns: Callable[[str], list[str]], count: Callable[[str], int]) -> int | None:
    """Non-null values of a column the principal still sees unchanged (None: the column has no mask)."""
    mask = gov.masks.get(table, {}).get(column)
    if mask is None:
        return None
    lab = table.split('.', 1)[1]
    ref = {c.lower(): exp.column(c, table=ALIAS) for c in columns(lab)}
    function, using = mask
    masked = _resolved(gov, function, [ref[column]] + [ref[u] for u in using], principal, groups)
    return count(f"SELECT count(*) FROM {lab} AS {ALIAS} WHERE {ALIAS}.\"{column}\" IS NOT NULL AND "
                 f"({masked}) IS NOT DISTINCT FROM {ALIAS}.\"{column}\"")
