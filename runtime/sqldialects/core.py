"""The one SQL dialect translator of the Workbench: a dialect's SQL translated to DuckDB for a documented subset.

sqlglot parses the source with the dialect's reader. Every syntax node and every function must be on the dialect's
allowlist; anything else is refused by name, never approximated. The constructs whose plain DuckDB translation would
change the engine's result are rewritten (types come from the catalog schema when the caller gives one) or refused
when the rewrite would need a type the query does not make known. sqlglot then generates DuckDB SQL, with
`unsupported_level=RAISE`, and the caller really runs it on the local catalog. Nothing here executes SQL.

Modes:
- `query`: one SELECT/WITH query (Practice, Explain).
- `script`: up to 20 statements: queries, CREATE TABLE/VIEW ... AS query, INSERT INTO ... query/VALUES, DROP
  TABLE/VIEW (Mosaic's Run active SQL).
- `statement`: one SELECT, INSERT, UPDATE, DELETE or MERGE (the Cloud Lab SQL pool, which splits its own batches).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError, TokenError, UnsupportedError

MAX_SOURCE = 40_000
MAX_STATEMENTS = 20
TARGET = 'duckdb'
Type = exp.DataType.Type

# sqlglot logs unsupported T-SQL query options (OPTION (LABEL = ...)) as warnings; the translator reports its own notes.
logging.getLogger('sqlglot').setLevel(logging.ERROR)


class DialectError(ValueError):
    """The SQL is outside the dialect's supported subset (or does not parse)."""


@dataclass(frozen=True)
class Translation:
    sql: str
    rewrites: list[str] = field(default_factory=list)
    dialect: str = ''
    label: str = ''
    statements: list[str] = field(default_factory=list)


class Hooks(Protocol):
    """Caller-specific resolution (the SQL pool): variables, the lab's fixed clock and its schema names."""

    default_schema: str | None  # the schema of unqualified table names, for types

    def parameter(self, node: exp.Parameter) -> exp.Expression: ...

    def now(self) -> exp.Expression | None: ...

    def table(self, node: exp.Table) -> None: ...


def classes(*names: str) -> frozenset[type]:
    return frozenset(getattr(exp, name) for name in names)


# Query syntax shared by every dialect (not functions). Dialects add their own.
QUERY_SYNTAX = classes(
    'Select', 'From', 'Join', 'Where', 'Group', 'Having', 'Order', 'Ordered', 'Limit', 'Offset', 'Distinct', 'With',
    'CTE', 'Subquery', 'Union', 'Except', 'Intersect', 'Table', 'TableAlias', 'Alias', 'Column', 'Identifier', 'Star',
    'Literal', 'Null', 'Boolean', 'Paren', 'Tuple', 'And', 'Or', 'Not', 'EQ', 'NEQ', 'GT', 'GTE', 'LT', 'LTE', 'Is',
    'In', 'Between', 'Like', 'Exists', 'Add', 'Sub', 'Mul', 'Div', 'Mod', 'Neg', 'DPipe', 'Window', 'WindowSpec', 'Var',
    'DataType', 'DataTypeParam',
)
SCRIPT_SYNTAX = classes('Create', 'Insert', 'Drop', 'Schema', 'Values')
STATEMENT_SYNTAX = classes('Insert', 'Update', 'Delete', 'Merge', 'When', 'Whens', 'Schema', 'Values')
# Table functions read files or the network: the catalog is the only data source.
TABLE_FUNCTIONS = ('READ_', 'SCAN', 'GLOB', 'HTTP', 'SQLITE', 'POSTGRES', 'PARQUET', 'CSV', 'JSON')
# The clock and random numbers: refused so a result can be reproduced and graded (the SQL pool fixes its clock).
NONDETERMINISTIC = frozenset(getattr(exp, name) for name in (
    'CurrentDate', 'CurrentTimestamp', 'CurrentTime', 'CurrentDatetime', 'Localtimestamp', 'Localtime', 'Rand',
    'Randn', 'Uuid', 'UnixSeconds', 'StrToUnix') if hasattr(exp, name))

INTEGER = {Type.TINYINT, Type.UTINYINT, Type.SMALLINT, Type.USMALLINT, Type.INT, Type.UINT, Type.BIGINT, Type.UBIGINT,
           Type.INT128, Type.UINT128, Type.MEDIUMINT}
DECIMAL = {Type.DECIMAL, Type.BIGDECIMAL, Type.MONEY, Type.SMALLMONEY, Type.UDECIMAL}
FLOAT = {Type.FLOAT, Type.DOUBLE}
STRING = {Type.VARCHAR, Type.NVARCHAR, Type.CHAR, Type.NCHAR, Type.TEXT, Type.NAME}
DATE = {Type.DATE, Type.DATE32}
TIMESTAMP = {Type.TIMESTAMP, Type.TIMESTAMPNTZ, Type.DATETIME, Type.DATETIME2, Type.SMALLDATETIME, Type.TIMESTAMP_S,
             Type.TIMESTAMP_MS, Type.TIMESTAMP_NS, Type.DATETIME64}


# Return types sqlglot's annotation may leave unknown (T-SQL's LEFT and RIGHT, for example).
STRING_RESULTS = tuple(getattr(exp, name) for name in (
    'Left', 'Right', 'Substring', 'Upper', 'Lower', 'Trim', 'Replace', 'Concat', 'ConcatWs', 'DPipe', 'Repeat',
    'Reverse', 'Pad', 'TimeToStr', 'GroupConcat', 'Chr', 'SplitPart', 'RegexpExtract', 'RegexpReplace', 'Stuff',
    'Space') if hasattr(exp, name))
INTEGER_RESULTS = tuple(getattr(exp, name) for name in (
    'Length', 'StrPosition', 'Count', 'CountIf', 'Year', 'Month', 'Day', 'Quarter', 'DayOfWeek', 'DayOfYear',
    'DateDiff', 'RowNumber', 'Rank', 'DenseRank', 'Ntile', 'Ascii', 'Unicode', 'IntDiv') if hasattr(exp, name))


def category(data_type: exp.DataType | None) -> str | None:
    """integer, decimal, float, string, date, timestamp, boolean, or None when the type is not known."""
    if data_type is None:
        return None
    kind = data_type.this
    for name, members in (('integer', INTEGER), ('decimal', DECIMAL), ('float', FLOAT), ('string', STRING),
                          ('date', DATE), ('timestamp', TIMESTAMP)):
        if kind in members:
            return name
    return 'boolean' if kind == Type.BOOLEAN else None


class Context:
    """One translation: the dialect, the caller's hooks, the rewrites made."""

    def __init__(self, dialect: 'Dialect', hooks: Hooks | None, mode: str):
        self.dialect = dialect
        self.hooks = hooks
        self.mode = mode
        self.rewrites: list[str] = []

    def refuse(self, message: str) -> DialectError:
        return self.dialect.refuse(message)

    def refuse_type(self, data_type: exp.DataType) -> DialectError:
        return self.refuse(f'Type {data_type.sql(dialect=self.dialect.read)} is not in the supported {self.dialect.name} subset')

    def note(self, text: str) -> None:
        self.rewrites.append(text)

    def type_of(self, node: exp.Expression | None) -> exp.DataType | None:
        """The node's type from the schema annotation, or from its syntax (literals, casts)."""
        while isinstance(node, exp.Paren):
            node = node.this
        if node is None:
            return None
        if isinstance(node, exp.Literal):
            if node.is_string:
                return exp.DataType.build('VARCHAR')
            return literal_type(node.this, self.dialect.decimal_literals)
        known = node.meta.get('dp_type') if node.meta else None
        if known is not None:
            return known
        if isinstance(node, exp.National):
            return exp.DataType.build('VARCHAR')
        if isinstance(node, (exp.Cast, exp.TryCast)):
            return node.to
        if isinstance(node, exp.Neg):
            return self.type_of(node.this)
        if isinstance(node, STRING_RESULTS):
            return exp.DataType.build('VARCHAR')
        if isinstance(node, INTEGER_RESULTS):
            return exp.DataType.build('BIGINT')
        if isinstance(node, (exp.Coalesce, exp.Abs, exp.Nullif)):
            return self.type_of(node.this)
        return None

    def category(self, node: exp.Expression | None) -> str | None:
        return category(self.type_of(node))


def literal_type(text: str, decimal_literals: bool) -> exp.DataType:
    """INT for 7, DECIMAL(p, s) for 2.345 (DOUBLE where the dialect reads decimal literals as floats: BigQuery)."""
    if re.fullmatch(r'\d+', text):
        return exp.DataType.build('INT')
    match = re.fullmatch(r'(\d*)\.(\d+)', text)
    if not decimal_literals or match is None:
        return exp.DataType.build('DOUBLE')
    whole, fraction = match.group(1).lstrip('0'), match.group(2)
    return exp.DataType.build(f'DECIMAL({min(max(len(whole) + len(fraction), 1), 38)}, {len(fraction)})')


def keep_type(old: exp.Expression, new: exp.Expression, data_type: exp.DataType | None = None) -> exp.Expression:
    """Carry the original node's type to its replacement, so a parent's rewrite can still read it."""
    kept = data_type if data_type is not None else (old.meta.get('dp_type') if old.meta else None)
    if kept is not None:
        new.meta['dp_type'] = kept
    return new


def error_call(message: str) -> exp.Expression:
    return exp.Anonymous(this='ERROR', expressions=[exp.Literal.string(message)])


def nonzero_literal(node: exp.Expression) -> bool:
    return isinstance(node, exp.Literal) and node.is_number and float(node.this) != 0


def zero_guard(divisor: exp.Expression, message: str) -> exp.Expression:
    """divisor, or an error when it is zero (DuckDB returns NULL or infinity where the engines raise)."""
    return exp.Case(ifs=[exp.If(this=exp.EQ(this=divisor.copy(), expression=exp.Literal.number(0)),
                                true=error_call(message))], default=divisor)


class Dialect:
    """One source dialect: its reader, allowlists and rules. Subclasses override `check` and `rewrite`."""

    id = ''
    read = ''
    name = ''         # short name in messages: "the supported T-SQL subset"
    language = ''     # "T-SQL could not be parsed"
    engine = ''       # "not SQL Server"
    functions: dict[str, frozenset[type]] = {}
    syntax: frozenset[type] = frozenset()
    labels: dict[type, str] = {}
    uses_types = True
    decimal_literals = True  # 2.5 is an exact DECIMAL (BigQuery: a FLOAT64)
    error: type[DialectError] = DialectError

    def __init__(self) -> None:
        self.allowed_functions = frozenset().union(*self.functions.values()) if self.functions else frozenset()

    @property
    def label(self) -> str:
        return f'{self.language} dialect translated to DuckDB, not {self.engine}'

    def refuse(self, message: str) -> DialectError:
        return self.error(f'{message} ({self.label}; see the supported subset in the {self.name} dialect notes.)')

    def function_name(self, node: exp.Expression) -> str:
        if isinstance(node, exp.Anonymous):
            return str(node.name).upper()
        text = node.sql(dialect=self.read)
        match = re.match(r'\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\(', text)
        return match.group(1).upper() if match else type(node).__name__

    def not_in_subset(self, what: str) -> DialectError:
        return self.refuse(f'{what} is not in the supported {self.name} subset')

    # -- hooks for subclasses ------------------------------------------------------------------------------------
    def prepare(self, tree: exp.Expression, ctx: Context) -> exp.Expression:
        """Structural steps before types are computed (the SQL pool's names and variables, stripped hints)."""
        return tree

    def check(self, node: exp.Expression, ctx: Context) -> None:
        """Dialect rules for one node, after the allowlists."""

    def rewrite(self, node: exp.Expression, ctx: Context) -> exp.Expression:
        """Dialect rewrite of one node; its children are already rewritten."""
        return node


# -- parsing and statement shapes ----------------------------------------------------------------------------------
def _parse(source: str, dialect: Dialect) -> list[exp.Expression]:
    if len(source) > MAX_SOURCE:
        raise dialect.refuse('The query exceeds the 40,000-character limit')
    try:
        return [s for s in sqlglot.parse(source, read=dialect.read) if s is not None]
    except (ParseError, TokenError) as error:
        first = str(error).splitlines()[0] if str(error) else 'syntax error'
        raise dialect.error(f'{dialect.language} could not be parsed: {first}') from error


def _statement_kind(node: exp.Expression) -> str:
    if isinstance(node, exp.Command):
        return str(node.this).upper()
    return node.key.upper()


def _check_shape(statements: list[exp.Expression], ctx: Context) -> None:
    dialect = ctx.dialect
    if ctx.mode == 'query':
        if len(statements) != 1:
            raise dialect.refuse('Write exactly one query')
        if not isinstance(statements[0], exp.Query):
            raise dialect.refuse(f'Only a SELECT query is supported; {_statement_kind(statements[0])} statements are refused')
        return
    if ctx.mode == 'statement':
        if len(statements) != 1:
            raise dialect.refuse('Write exactly one statement')
        if not isinstance(statements[0], (exp.Query, exp.Insert, exp.Update, exp.Delete, exp.Merge)):
            raise dialect.refuse(f'{_statement_kind(statements[0])} statements are not translated here')
        return
    if not 1 <= len(statements) <= MAX_STATEMENTS:
        raise dialect.refuse(f'Write between 1 and {MAX_STATEMENTS} statements')
    for statement in statements:
        _check_script_statement(statement, ctx)


def _check_script_statement(node: exp.Expression, ctx: Context) -> None:
    dialect = ctx.dialect
    supported = 'Supported: SELECT/WITH queries, CREATE [OR REPLACE] TABLE or VIEW ... AS a query, INSERT INTO ... a query or VALUES, DROP TABLE or VIEW'
    if isinstance(node, exp.Query):
        return
    if isinstance(node, exp.Create):
        kind = str(node.args.get('kind') or '').upper()
        if kind not in ('TABLE', 'VIEW'):
            raise dialect.refuse(f'CREATE {kind} is not translated. {supported}')
        if not isinstance(node.expression, exp.Query) or not isinstance(node.this, exp.Table):
            raise dialect.refuse(f'CREATE {kind} with column definitions is not translated: use CREATE {kind} ... AS SELECT')
        properties = node.args.get('properties')
        if properties is not None and properties.expressions:
            raise dialect.refuse(f'CREATE {kind} options ({properties.sql(dialect=dialect.read)[:60]}) are not translated')
        return
    if isinstance(node, exp.Insert):
        target = node.this.this if isinstance(node.this, exp.Schema) else node.this
        if not isinstance(target, exp.Table) or not isinstance(node.expression, (exp.Query, exp.Values)):
            raise dialect.refuse(f'This INSERT form is not translated. {supported}')
        if node.args.get('overwrite') or node.args.get('conflict') or node.args.get('alternative'):
            raise dialect.refuse('INSERT OVERWRITE, OR REPLACE and ON CONFLICT are not translated')
        return
    if isinstance(node, exp.Drop):
        if str(node.args.get('kind') or '').upper() not in ('TABLE', 'VIEW'):
            raise dialect.refuse(f'This DROP is not translated. {supported}')
        return
    raise dialect.refuse(f'{_statement_kind(node)} statements are not translated. {supported}')


# -- types ------------------------------------------------------------------------------------------------------------
def _schema(schema: dict[str, Any] | None, read: str) -> Any:
    """A sqlglot MappingSchema from {table: {column: DuckDB type}} or {schema: {table: {...}}}."""
    if not schema:
        return None
    from sqlglot.schema import MappingSchema

    def convert(columns: dict[str, str]) -> dict[str, str]:
        out = {}
        for column, text in columns.items():
            try:
                out[column] = exp.DataType.build(str(text), dialect=TARGET).sql(dialect=read)
            except Exception:  # an unknown type stays unknown: rules that need it refuse
                continue
        return out

    nested = {}
    for key, value in schema.items():
        if value and all(isinstance(v, dict) for v in value.values()):
            nested[key] = {table: convert(columns) for table, columns in value.items()}
        else:
            nested[key] = convert(value)
    try:
        return MappingSchema(nested, dialect=read)
    except Exception:
        return None


def _annotate(tree: exp.Expression, schema: Any, read: str, decimal_literals: bool, db: str | None = None) -> None:
    """Store each node's type in node.meta['dp_type'] (a copy is qualified and annotated; ids map it back).
    `db` is the schema of unqualified table names (the SQL pool's warehouse); only the typed copy is qualified."""
    from sqlglot.optimizer.annotate_types import annotate_types
    from sqlglot.optimizer.qualify import qualify

    for index, node in enumerate(tree.walk()):
        node.meta['dp_id'] = index
    copy = tree.copy()
    # sqlglot types 2.5 as DOUBLE; most engines read it as an exact DECIMAL, and the types above it follow.
    for literal in list(copy.find_all(exp.Literal)):
        if literal.is_number and not isinstance(literal.parent, (exp.DataTypeParam, exp.Cast)):
            kind = literal_type(literal.this, decimal_literals)
            if kind.this == Type.DECIMAL:
                literal.replace(exp.Cast(this=literal.copy(), to=kind))
    try:
        if schema is not None:
            # The queries of a statement (CREATE TABLE ... AS, INSERT ... SELECT) are qualified one by one.
            queries = [copy] if isinstance(copy, exp.Query) else [
                q for q in copy.find_all(exp.Query) if not isinstance(q.parent, (exp.Query, exp.Subquery, exp.CTE, exp.Union))]
            for query in queries:
                qualified = qualify(query, schema=schema, dialect=read, db=db, validate_qualify_columns=False,
                                    quote_identifiers=False, identify=False, infer_schema=True)
                if query is copy:
                    copy = qualified
                elif qualified is not query:
                    query.replace(qualified)
        annotated = annotate_types(copy, schema=schema, dialect=read)
    except Exception:
        try:
            annotated = annotate_types(tree.copy(), dialect=read)
        except Exception:
            return
    types = {}
    for node in annotated.walk():
        data_type = node.type
        if 'dp_id' in node.meta and data_type is not None and data_type.this not in (Type.UNKNOWN, Type.NULL):
            types[node.meta['dp_id']] = data_type
    for node in tree.walk():
        found = types.get(node.meta.pop('dp_id', None))
        if found is not None:
            node.meta['dp_type'] = found
    if schema is not None:
        _column_fallback(tree, schema, db)


def _column_fallback(tree: exp.Expression, schema: Any, db: str | None) -> None:
    """Columns the annotation left untyped (UPDATE, DELETE, MERGE): the type of the one table of the statement that
    has that column (or the table its qualifier names)."""
    tables = list(tree.find_all(exp.Table))
    for column in tree.find_all(exp.Column):
        if 'dp_type' in column.meta or not column.name:
            continue
        candidates = [t for t in tables if not column.table or column.table.lower() in (t.alias_or_name.lower(), t.name.lower())]
        found = []
        for table in candidates:
            if db and not table.db:
                table = exp.table_(table.name, db=db)
            try:
                if column.name.lower() in [c.lower() for c in schema.column_names(table)]:
                    found.append(schema.get_column_type(table, column.name))
            except Exception:  # a table the schema does not know
                continue
        if len(found) == 1 and found[0] is not None and found[0].this != Type.UNKNOWN:
            column.meta['dp_type'] = found[0]


# -- check and rewrite ----------------------------------------------------------------------------------------------
def _check(tree: exp.Expression, ctx: Context, extra: frozenset[type]) -> None:
    dialect = ctx.dialect
    allowed = dialect.syntax | extra
    for node in tree.walk():
        kind = type(node)
        if kind in allowed:
            pass
        elif isinstance(node, exp.Func):
            if kind not in dialect.allowed_functions:
                name = dialect.function_name(node)
                if isinstance(node.parent, exp.Table) or name.startswith(TABLE_FUNCTIONS):
                    raise dialect.refuse(f'{name}: use the workspace catalog, not filesystem or network table functions')
                if kind in NONDETERMINISTIC:
                    raise dialect.refuse(f'{name} is not in the supported {dialect.name} subset: the clock and random '
                                         'values would make results impossible to reproduce')
                raise dialect.refuse(f'{name} is not in the supported {dialect.name} subset; it is refused rather than approximated')
        else:
            label = dialect.labels.get(kind, kind.__name__)
            raise dialect.not_in_subset(label)
        dialect.check(node, ctx)


def _rewrite(tree: exp.Expression, ctx: Context) -> exp.Expression:
    """Post-order: every node is rewritten after its children, so rules see rewritten operands."""
    nodes = list(tree.dfs())
    root = tree
    for node in reversed(nodes):
        # A rule may wrap the node (CAST(node AS DATE)): its place in the tree is taken before the rule runs.
        parent, key, index = node.parent, node.arg_key, node.index
        new = ctx.dialect.rewrite(node, ctx)
        if new is node:
            continue
        if 'dp_type' not in new.meta:
            keep_type(node, new)
        if parent is None:
            root = new
        else:
            parent.set(key, new, index)
    return root


def _generate(tree: exp.Expression, ctx: Context) -> str:
    try:
        return tree.sql(dialect=TARGET, unsupported_level=ErrorLevel.RAISE, comments=False)
    except UnsupportedError as error:
        raise ctx.refuse(f'This query uses a form DuckDB cannot express faithfully: {str(error).splitlines()[0]}') from error


def _translate_tree(tree: exp.Expression, ctx: Context, schema: Any, extra: frozenset[type]) -> str:
    tree = ctx.dialect.prepare(tree, ctx)
    if ctx.dialect.uses_types:
        _annotate(tree, schema, ctx.dialect.read, ctx.dialect.decimal_literals, getattr(ctx.hooks, 'default_schema', None))
    _check(tree, ctx, extra)
    return _generate(_rewrite(tree, ctx), ctx)


def translate_with(dialect: Dialect, source: str, *, mode: str = 'query', schema: dict[str, Any] | None = None,
                   hooks: Hooks | None = None) -> Translation:
    if mode not in ('query', 'script', 'statement'):
        raise ValueError(f'Unknown translation mode {mode!r}')
    ctx = Context(dialect, hooks, mode)
    statements = _parse(source, dialect)
    _check_shape(statements, ctx)
    extra = {'query': frozenset(), 'script': SCRIPT_SYNTAX, 'statement': STATEMENT_SYNTAX}[mode]
    mapping = _schema(schema, dialect.read) if dialect.uses_types else None
    parts = [_translate_tree(statement, ctx, mapping, extra) for statement in statements]
    sql = ';\n'.join(parts) + (';' if mode == 'script' else '')
    return Translation(sql=sql, rewrites=sorted(set(ctx.rewrites)), dialect=dialect.id, label=dialect.label,
                       statements=parts)


def translate_expression_with(dialect: Dialect, source: str, *, schema: dict[str, Any] | None = None,
                              hooks: Hooks | None = None) -> Translation:
    """One scalar expression (the SQL pool's DECLARE, SET and PRINT values)."""
    ctx = Context(dialect, hooks, 'statement')
    if len(source) > MAX_SOURCE:
        raise dialect.refuse('The expression exceeds the 40,000-character limit')
    try:
        tree = sqlglot.parse_one(f'SELECT {source}', read=dialect.read)
    except (ParseError, TokenError) as error:
        first = str(error).splitlines()[0] if str(error) else 'syntax error'
        raise dialect.error(f'{dialect.language} could not be parsed: {first}') from error
    if not isinstance(tree, exp.Select) or len(tree.expressions) != 1 or tree.args.get('from'):
        raise dialect.refuse('Write one expression')
    sql = _translate_tree(tree, ctx, _schema(schema, dialect.read), STATEMENT_SYNTAX)
    return Translation(sql=sql[len('SELECT '):], rewrites=sorted(set(ctx.rewrites)), dialect=dialect.id,
                       label=dialect.label, statements=[sql])
