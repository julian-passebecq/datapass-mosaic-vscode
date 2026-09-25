"""Snowflake SQL: the documented subset of PR #19, unchanged, as one dialect of the shared translator."""
from __future__ import annotations

import re

from sqlglot import exp

from .core import QUERY_SYNTAX, Context, Dialect, DialectError, classes, nonzero_literal, zero_guard


class SnowflakeDialectError(DialectError):
    """The query is outside the supported Snowflake subset (or not valid Snowflake SQL)."""


# Functions whose sqlglot translation keeps Snowflake's result (each one is checked in scripts/runtime_smoke.py).
FUNCTIONS: dict[str, frozenset[type]] = {
    'aggregate': classes('Count', 'Sum', 'Avg', 'Min', 'Max', 'Median', 'Variance', 'VariancePop', 'Stddev',
                         'StddevSamp', 'StddevPop', 'CountIf', 'GroupConcat'),
    'window': classes('RowNumber', 'Rank', 'DenseRank', 'Lag', 'Lead', 'FirstValue', 'LastValue', 'Ntile'),
    'conditional': classes('If', 'Case', 'Coalesce', 'Nvl2', 'Nullif', 'Greatest', 'Least', 'DecodeCase',
                           'EqualNull'),
    'string': classes('Upper', 'Lower', 'Length', 'Trim', 'Substring', 'Left', 'Right', 'Concat', 'ConcatWs',
                      'Replace', 'SplitPart', 'StrPosition', 'Pad', 'Reverse', 'RegexpReplace', 'RegexpLike',
                      'RegexpExtract', 'Contains', 'StartsWith', 'EndsWith'),
    'date': classes('TsOrDsToDate', 'StrToDate', 'TimeToStr', 'DateDiff', 'DateAdd', 'TimestampTrunc',
                    'DateTrunc', 'Year', 'Month', 'Day', 'Quarter', 'DayOfWeek', 'DayOfWeekIso', 'LastDay',
                    'Extract'),
    'numeric': classes('Abs', 'Round', 'Ceil', 'Floor', 'Trunc', 'Sqrt', 'Pow', 'Ln', 'Exp', 'Sign'),
    'conversion': classes('Cast', 'TryCast'),
}

# Query syntax (not functions) that means the same thing in Snowflake and DuckDB.
SYNTAX = QUERY_SYNTAX | classes('Qualify', 'NullSafeEQ', 'NullSafeNEQ', 'ILike', 'RawString', 'Any')

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


class Snowflake(Dialect):
    id = 'snowflake'
    read = 'snowflake'
    name = 'Snowflake'
    language = 'Snowflake SQL'
    engine = 'Snowflake'
    functions = FUNCTIONS
    syntax = SYNTAX
    labels = {exp.Lateral: 'LATERAL / FLATTEN', exp.TableSample: 'SAMPLE', exp.Parameter: '$ column references',
              exp.Placeholder: 'bind variables', exp.Interval: 'INTERVAL literals',
              exp.JSONExtract: 'semi-structured paths (col:field)'}
    uses_types = False
    error = SnowflakeDialectError

    def check(self, node: exp.Expression, ctx: Context) -> None:
        refuse = self.refuse
        if type(node) is exp.Any and not isinstance(node.parent, (exp.Like, exp.ILike)):
            raise refuse('ANY is only in the supported Snowflake subset as LIKE ANY / ILIKE ANY')
        if isinstance(node, exp.DataType) and node.this not in TYPES and not isinstance(node.parent, exp.DataType):
            raise refuse(f'Type {node.sql(dialect="snowflake")} is not in the supported Snowflake subset')
        if isinstance(node, exp.Join) and (node.args.get('kind') or '').upper() in {'ASOF', 'LATERAL'}:
            raise refuse(f"{node.args['kind'].upper()} JOIN is not in the supported Snowflake subset")
        if isinstance(node, exp.Count) and isinstance(node.this, exp.Distinct) and len(node.this.expressions) > 1:
            raise refuse('COUNT(DISTINCT a, b) with several columns is not in the supported Snowflake subset')
        if isinstance(node, (exp.RegexpLike, exp.RegexpReplace, exp.RegexpExtract)):
            defaults = {'this', 'expression', 'replacement', 'full_match', 'null_if_pos_overflow'}
            extra = [k for k, v in node.args.items() if v is not None and k not in defaults
                     and not (k == 'group' and isinstance(v, exp.Literal) and v.this == '0')]
            if extra:
                raise refuse(f'{self.function_name(node)} with position, occurrence, group or parameter arguments is not in the supported Snowflake subset')
        if isinstance(node, (exp.StrToDate, exp.TimeToStr, exp.TsOrDsToDate)) and (
                'format' in node.args and node.args['format'] is not None or not isinstance(node, exp.TsOrDsToDate)):
            fmt = node.args.get('format')
            text = fmt.this if isinstance(fmt, exp.Literal) and fmt.is_string else None
            if text is None or not FORMAT.fullmatch(text):
                raise refuse(f'{self.function_name(node)} with this format is not in the supported Snowflake subset '
                             '(use a literal made of YYYY, YY, MM, MON, MMMM, DD, DY, HH24, MI, SS and separators)')
        if isinstance(node, exp.Mod) and not nonzero_literal(node.expression):
            raise refuse('MOD and % need a non-zero number literal as divisor here (Snowflake does not document MOD by zero)')
        if isinstance(node, (exp.DateDiff, exp.DateAdd, exp.TimestampTrunc, exp.DateTrunc, exp.Extract)):
            unit = _unit(node) if not isinstance(node, exp.Extract) else node.this.name.lower()
            allowed = (EXTRACT_PARTS if isinstance(node, exp.Extract) else DIFF_PARTS if isinstance(node, exp.DateDiff)
                       else DATE_ADD_PARTS)
            if unit not in allowed:
                raise refuse(f'Date part {unit or "?"} in {self.function_name(node)} is not in the supported Snowflake subset')
        if isinstance(node, (exp.DateAdd, exp.TimestampTrunc, exp.DateTrunc)) and _date_typed(node.this) is None:
            raise refuse(f'{self.function_name(node)} needs an argument whose type is explicit here: write TO_DATE(col) or col::DATE '
                         '(or ::TIMESTAMP). Snowflake keeps a DATE a DATE; DuckDB would return a TIMESTAMP')
        if isinstance(node, exp.Trunc) and node.args.get('decimals') is not None and not isinstance(node.args['decimals'], (exp.Literal, exp.Neg)):
            raise refuse('TRUNC(value, scale) needs a numeric scale; TRUNC of a date is DATE_TRUNC')

    def rewrite(self, node: exp.Expression, ctx: Context) -> exp.Expression:
        if isinstance(node, exp.Identifier) and not node.quoted:
            # Snowflake resolves unquoted identifiers case-insensitively (folded to upper case); lower case keeps
            # that resolution and shows result columns like the other Datapass engines.
            node.set('this', node.this.lower())
        elif isinstance(node, exp.RegexpExtract):
            # REGEXP_SUBSTR returns NULL when nothing matches; DuckDB's regexp_extract returns ''.
            subject, pattern = node.this, node.expression
            ctx.note('REGEXP_SUBSTR returns NULL when nothing matches')
            return exp.Case(ifs=[exp.If(this=exp.Anonymous(this='REGEXP_MATCHES', expressions=[subject.copy(), pattern.copy()]),
                                        true=exp.Anonymous(this='REGEXP_EXTRACT', expressions=[subject, pattern]))])
        elif isinstance(node, exp.Div):
            if not nonzero_literal(node.expression):
                # Snowflake raises "Division by zero"; DuckDB would return NULL or infinity.
                ctx.note('Division by zero raises an error, as in Snowflake')
                node.set('expression', zero_guard(node.expression, 'Division by zero'))
        elif isinstance(node, (exp.DateAdd, exp.TimestampTrunc, exp.DateTrunc)) and _date_typed(node.this) == 'date':
            if not isinstance(node.parent, exp.Cast):
                ctx.note(f'{self.function_name(node)} of a DATE stays a DATE')
                return exp.Cast(this=node, to=exp.DataType.build('DATE'))
        return node
