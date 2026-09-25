"""Snowflake SQL dialect translated to DuckDB, for a documented subset. This is not Snowflake.

The learner writes one Snowflake query. sqlglot parses it with the Snowflake dialect; this module refuses anything
outside the subset (every function and every syntax node is allowlisted), rewrites the few constructs whose DuckDB
translation would not give Snowflake's result, and sqlglot generates DuckDB SQL that really runs on the local
catalog. Unsupported functions are refused with their name, never approximated. See README.md for the subset and the
known differences.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError, TokenError, UnsupportedError

LABEL = 'Snowflake SQL dialect translated to DuckDB, not Snowflake'
MAX_SOURCE = 40_000


class SnowflakeDialectError(ValueError):
    """The query is outside the supported Snowflake subset (or not valid Snowflake SQL)."""


@dataclass(frozen=True)
class Translation:
    sql: str
    rewrites: list[str] = field(default_factory=list)


def _classes(*names: str) -> frozenset[type]:
    return frozenset(getattr(exp, name) for name in names)


# Functions whose sqlglot translation keeps Snowflake's result (each one is checked in scripts/runtime_smoke.py).
FUNCTIONS: dict[str, frozenset[type]] = {
    'aggregate': _classes('Count', 'Sum', 'Avg', 'Min', 'Max', 'Median', 'Variance', 'VariancePop', 'Stddev',
                          'StddevSamp', 'StddevPop', 'CountIf', 'GroupConcat'),
    'window': _classes('RowNumber', 'Rank', 'DenseRank', 'Lag', 'Lead', 'FirstValue', 'LastValue', 'Ntile'),
    'conditional': _classes('If', 'Case', 'Coalesce', 'Nvl2', 'Nullif', 'Greatest', 'Least', 'DecodeCase',
                            'EqualNull'),
    'string': _classes('Upper', 'Lower', 'Length', 'Trim', 'Substring', 'Left', 'Right', 'Concat', 'ConcatWs',
                       'Replace', 'SplitPart', 'StrPosition', 'Pad', 'Reverse', 'RegexpReplace', 'RegexpLike',
                       'RegexpExtract', 'Contains', 'StartsWith', 'EndsWith'),
    'date': _classes('TsOrDsToDate', 'StrToDate', 'TimeToStr', 'DateDiff', 'DateAdd', 'TimestampTrunc',
                     'DateTrunc', 'Year', 'Month', 'Day', 'Quarter', 'DayOfWeek', 'DayOfWeekIso', 'LastDay',
                     'Extract'),
    'numeric': _classes('Abs', 'Round', 'Ceil', 'Floor', 'Trunc', 'Sqrt', 'Pow', 'Ln', 'Exp', 'Sign'),
    'conversion': _classes('Cast', 'TryCast'),
}
ALLOWED_FUNCTIONS = frozenset().union(*FUNCTIONS.values())

# Query syntax (not functions) that means the same thing in Snowflake and DuckDB.
SYNTAX = _classes(
    'Select', 'From', 'Join', 'Where', 'Group', 'Having', 'Qualify', 'Order', 'Ordered', 'Limit', 'Offset',
    'Distinct', 'With', 'CTE', 'Subquery', 'Union', 'Except', 'Intersect', 'Table', 'TableAlias', 'Alias', 'Column',
    'Identifier', 'Star', 'Literal', 'Null', 'Boolean', 'Paren', 'Tuple', 'And', 'Or', 'Not', 'EQ', 'NEQ', 'GT',
    'GTE', 'LT', 'LTE', 'NullSafeEQ', 'NullSafeNEQ', 'Is', 'In', 'Between', 'Like', 'ILike', 'Exists', 'Add', 'Sub',
    'Mul', 'Div', 'Mod', 'Neg', 'DPipe', 'Window', 'WindowSpec', 'Var', 'DataType', 'DataTypeParam', 'RawString',
    'Any',
)

# CAST targets: Snowflake types with a DuckDB type of the same meaning.
TYPES = {
    exp.DataType.Type.INT, exp.DataType.Type.BIGINT, exp.DataType.Type.SMALLINT, exp.DataType.Type.TINYINT,
    exp.DataType.Type.DECIMAL, exp.DataType.Type.DOUBLE, exp.DataType.Type.FLOAT, exp.DataType.Type.VARCHAR,
    exp.DataType.Type.TEXT, exp.DataType.Type.CHAR, exp.DataType.Type.BOOLEAN, exp.DataType.Type.DATE,
    exp.DataType.Type.TIMESTAMP, exp.DataType.Type.TIMESTAMPNTZ, exp.DataType.Type.DATETIME,
}
# Date parts per function (Snowflake's default WEEK_START and WEEK_OF_YEAR_POLICY; week numbers are not in the subset).
DIFF_PARTS = {'year', 'quarter', 'month', 'week', 'day', 'hour', 'minute', 'second'}
EXTRACT_PARTS = {'year', 'quarter', 'month', 'day', 'dayofweek', 'dow', 'dayofweekiso', 'hour', 'minute', 'second'}
DATE_ADD_PARTS = {'year', 'quarter', 'month', 'week', 'day'}
# TO_DATE / TO_CHAR formats, as sqlglot maps them to strftime: YYYY %Y, YY %y, MM %m, MON %b, MMMM %B, DD %d, DY %a,
# HH24 %H, MI %M, SS %S, and separators. Other Snowflake format elements are refused.
FORMAT = re.compile(r"^(%[YymbBdaHMS]|[-/ :.,])+$")


def _refuse(message: str) -> SnowflakeDialectError:
    return SnowflakeDialectError(f'{message} ({LABEL}; see the supported subset in the Snowflake dialect notes.)')


def _name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).upper()
    text = node.sql(dialect='snowflake')
    match = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(', text)
    return match.group(1).upper() if match else type(node).__name__


def _unit(node: exp.Expression) -> str:
    unit = node.args.get('unit')
    return (unit.name if isinstance(unit, (exp.Var, exp.Literal, exp.Identifier, exp.Column)) else str(unit or '')).lower()


def _date_typed(node: exp.Expression | None) -> str | None:
    """'date', 'timestamp' or None: the type of an expression when its syntax makes it explicit."""
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, (exp.Cast, exp.TryCast)):
        kind = node.to.this
        if kind == exp.DataType.Type.DATE:
            return 'date'
        if kind in (exp.DataType.Type.TIMESTAMP, exp.DataType.Type.TIMESTAMPNTZ, exp.DataType.Type.DATETIME):
            return 'timestamp'
        return None
    if isinstance(node, (exp.TsOrDsToDate, exp.StrToDate, exp.LastDay)):
        return 'date'
    if isinstance(node, (exp.DateAdd, exp.TimestampTrunc, exp.DateTrunc)):
        return _date_typed(node.this)
    return None


def _check(tree: exp.Expression) -> None:
    for node in tree.walk():
        kind = type(node)
        if kind is exp.Any and not isinstance(node.parent, (exp.Like, exp.ILike)):
            raise _refuse('ANY is only in the supported Snowflake subset as LIKE ANY / ILIKE ANY')
        if kind in SYNTAX:
            pass
        elif isinstance(node, exp.Func) and kind not in ALLOWED_FUNCTIONS:
            raise _refuse(f'{_name(node)} is not in the supported Snowflake subset; it is refused rather than approximated')
        elif not isinstance(node, exp.Func):
            label = {exp.Lateral: 'LATERAL / FLATTEN', exp.TableSample: 'SAMPLE', exp.Parameter: '$ column references',
                     exp.Placeholder: 'bind variables', exp.Interval: 'INTERVAL literals',
                     exp.JSONExtract: 'semi-structured paths (col:field)'}.get(kind, kind.__name__)
            raise _refuse(f'{label} is not in the supported Snowflake subset')
        if isinstance(node, exp.DataType) and node.this not in TYPES and not isinstance(node.parent, exp.DataType):
            raise _refuse(f'Type {node.sql(dialect="snowflake")} is not in the supported Snowflake subset')
        if isinstance(node, exp.Join) and (node.args.get('kind') or '').upper() in {'ASOF', 'LATERAL'}:
            raise _refuse(f"{node.args['kind'].upper()} JOIN is not in the supported Snowflake subset")
        if isinstance(node, exp.Count) and isinstance(node.this, exp.Distinct) and len(node.this.expressions) > 1:
            raise _refuse('COUNT(DISTINCT a, b) with several columns is not in the supported Snowflake subset')
        if isinstance(node, (exp.RegexpLike, exp.RegexpReplace, exp.RegexpExtract)):
            defaults = {'this', 'expression', 'replacement', 'full_match', 'null_if_pos_overflow'}
            extra = [k for k, v in node.args.items() if v is not None and k not in defaults
                     and not (k == 'group' and isinstance(v, exp.Literal) and v.this == '0')]
            if extra:
                raise _refuse(f'{_name(node)} with position, occurrence, group or parameter arguments is not in the supported Snowflake subset')
        if isinstance(node, (exp.StrToDate, exp.TimeToStr, exp.TsOrDsToDate)) and (
                'format' in node.args and node.args['format'] is not None or not isinstance(node, exp.TsOrDsToDate)):
            fmt = node.args.get('format')
            text = fmt.this if isinstance(fmt, exp.Literal) and fmt.is_string else None
            if text is None or not FORMAT.fullmatch(text):
                raise _refuse(f'{_name(node)} with this format is not in the supported Snowflake subset '
                              '(use a literal made of YYYY, YY, MM, MON, MMMM, DD, DY, HH24, MI, SS and separators)')
        if isinstance(node, exp.Mod) and not (isinstance(node.expression, exp.Literal) and node.expression.is_number
                                              and float(node.expression.this) != 0):
            raise _refuse('MOD and % need a non-zero number literal as divisor here (Snowflake does not document MOD by zero)')
        if isinstance(node, (exp.DateDiff, exp.DateAdd, exp.TimestampTrunc, exp.DateTrunc, exp.Extract)):
            unit = _unit(node) if not isinstance(node, exp.Extract) else node.this.name.lower()
            allowed = (EXTRACT_PARTS if isinstance(node, exp.Extract) else DIFF_PARTS if isinstance(node, exp.DateDiff)
                       else DATE_ADD_PARTS)
            if unit not in allowed:
                raise _refuse(f'Date part {unit or "?"} in {_name(node)} is not in the supported Snowflake subset')
        if isinstance(node, (exp.DateAdd, exp.TimestampTrunc, exp.DateTrunc)) and _date_typed(node.this) is None:
            raise _refuse(f'{_name(node)} needs an argument whose type is explicit here: write TO_DATE(col) or col::DATE '
                          '(or ::TIMESTAMP). Snowflake keeps a DATE a DATE; DuckDB would return a TIMESTAMP')
        if isinstance(node, exp.Trunc) and node.args.get('decimals') is not None and not isinstance(node.args['decimals'], (exp.Literal, exp.Neg)):
            raise _refuse('TRUNC(value, scale) needs a numeric scale; TRUNC of a date is DATE_TRUNC')


def _rewrite(tree: exp.Expression, rewrites: list[str]) -> exp.Expression:
    def visit(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Identifier) and not node.quoted:
            # Snowflake resolves unquoted identifiers case-insensitively (folded to upper case); lower case keeps
            # that resolution and shows result columns like the other Datapass engines.
            node.set('this', node.this.lower())
        elif isinstance(node, exp.RegexpExtract):
            # REGEXP_SUBSTR returns NULL when nothing matches; DuckDB's regexp_extract returns ''.
            subject, pattern = node.this, node.expression
            rewrites.append('REGEXP_SUBSTR returns NULL when nothing matches')
            return exp.Case(ifs=[exp.If(this=exp.Anonymous(this='REGEXP_MATCHES', expressions=[subject.copy(), pattern.copy()]),
                                        true=exp.Anonymous(this='REGEXP_EXTRACT', expressions=[subject, pattern]))])
        elif isinstance(node, exp.Div):
            divisor = node.expression
            if not (isinstance(divisor, exp.Literal) and divisor.is_number and float(divisor.this) != 0):
                # Snowflake raises "Division by zero"; DuckDB would return NULL or infinity.
                rewrites.append('Division by zero raises an error, as in Snowflake')
                guarded = exp.Case(ifs=[exp.If(this=exp.EQ(this=divisor.copy(), expression=exp.Literal.number(0)),
                                               true=exp.Anonymous(this='ERROR', expressions=[exp.Literal.string('Division by zero')]))],
                                   default=divisor)
                node.set('expression', guarded)
        elif isinstance(node, (exp.DateAdd, exp.TimestampTrunc, exp.DateTrunc)) and _date_typed(node.this) == 'date':
            if not isinstance(node.parent, exp.Cast):
                rewrites.append(f'{_name(node)} of a DATE stays a DATE')
                return exp.Cast(this=node, to=exp.DataType.build('DATE'))
        return node
    return tree.transform(visit, copy=False)


def translate(source: str) -> Translation:
    """Translate one Snowflake query to DuckDB SQL, or raise SnowflakeDialectError."""
    if len(source) > MAX_SOURCE:
        raise _refuse('The query exceeds the 40,000-character limit')
    try:
        statements = [s for s in sqlglot.parse(source, read='snowflake') if s is not None]
    except (ParseError, TokenError) as error:
        first = str(error).splitlines()[0] if str(error) else 'syntax error'
        raise SnowflakeDialectError(f'Snowflake SQL could not be parsed: {first}') from error
    if len(statements) != 1:
        raise _refuse('Write exactly one query')
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise _refuse(f'Only a SELECT query is supported; {tree.key.upper()} statements are refused')
    _check(tree)
    rewrites: list[str] = []
    tree = _rewrite(tree, rewrites)
    try:
        sql = tree.sql(dialect='duckdb', unsupported_level=ErrorLevel.RAISE)
    except UnsupportedError as error:
        raise _refuse(f'This query uses a form DuckDB cannot express faithfully: {str(error).splitlines()[0]}') from error
    return Translation(sql=sql, rewrites=sorted(set(rewrites)))
