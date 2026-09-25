"""Spark SQL in ANSI mode (the default of Apache Spark 4 and Databricks SQL) translated to DuckDB, for a subset.

sqlglot reads it with its Databricks dialect, which keeps ANSI semantics: CAST raises on bad input and division by
zero raises. Arrays, maps, structs, EXPLODE and time zones are not in the subset.
"""
from __future__ import annotations

import re

from sqlglot import exp

from .core import QUERY_SYNTAX, Context, Dialect, DialectError, classes
from .rules import (CastRules, cast, cast_to, duck, first_position_substring, guard_division, map_decimal,
                    sunday_one_weekday, typed, unwrap)

ENGINE = 'Spark SQL'
DIVIDE_BY_ZERO = '[DIVIDE_BY_ZERO] Division by zero.'


class SparkDialectError(DialectError):
    """The SQL is outside the supported Spark SQL subset (or not valid Spark SQL)."""


FUNCTIONS: dict[str, frozenset[type]] = {
    'aggregate': classes('Count', 'CountIf', 'Sum', 'Avg', 'Min', 'Max', 'Stddev', 'StddevSamp', 'StddevPop',
                         'Variance', 'VariancePop', 'Median', 'LogicalAnd', 'LogicalOr'),
    'window': classes('RowNumber', 'Rank', 'DenseRank', 'Ntile', 'Lag', 'Lead', 'FirstValue', 'LastValue',
                      'PercentRank', 'CumeDist'),
    'conditional': classes('If', 'Case', 'Coalesce', 'Nvl2', 'Nullif', 'Greatest', 'Least'),
    'string': classes('Upper', 'Lower', 'Length', 'Trim', 'Left', 'Right', 'Substring', 'StrPosition', 'Replace',
                      'Repeat', 'Reverse', 'Concat', 'ConcatWs', 'Pad', 'StartsWith', 'EndsWith', 'SplitPart',
                      'RegexpExtract', 'RegexpReplace', 'RegexpLike'),
    'date': classes('TsOrDsAdd', 'AddMonths', 'DateDiff', 'TimestampTrunc', 'DateTrunc', 'Year', 'Quarter', 'Month',
                    'Day', 'DayOfMonth', 'DayOfWeek', 'DayOfYear', 'Extract', 'LastDay', 'TimeToStr',
                    'TsOrDsToDate', 'TimeStrToTime'),
    'numeric': classes('Abs', 'Round', 'Ceil', 'Floor', 'Sqrt', 'Pow', 'Ln', 'Log', 'Exp', 'Sign'),
    'conversion': classes('Cast', 'TryCast'),
}
SYNTAX = QUERY_SYNTAX | classes('Qualify', 'NullSafeEQ', 'NullSafeNEQ', 'ILike', 'IntDiv')
# DATE_FORMAT / TO_DATE patterns (as strftime): yyyy yy MM MMM MMMM dd HH mm ss E EEEE and separators.
FORMAT = re.compile(r'^(%[YymbBdHMSaA]|[-/ :.,T])+$')
TRUNC_UNITS = {'YEAR': 'year', 'YYYY': 'year', 'YY': 'year', 'QUARTER': 'quarter', 'MONTH': 'month', 'MM': 'month',
               'MON': 'month', 'WEEK': 'week'}
TIMESTAMP_TRUNC_UNITS = {**TRUNC_UNITS, 'DAY': 'day', 'DD': 'day', 'HOUR': 'hour', 'MINUTE': 'minute',
                         'SECOND': 'second'}
EXTRACT_PARTS = {'YEAR': 'year', 'QUARTER': 'quarter', 'MONTH': 'month', 'DAY': 'day', 'DAYOFYEAR': 'doy',
                 'DOY': 'doy', 'HOUR': 'hour', 'MINUTE': 'minute', 'WEEK': 'week'}
CAST_TYPES = {exp.DataType.Type.INT, exp.DataType.Type.BIGINT, exp.DataType.Type.SMALLINT,
              exp.DataType.Type.TINYINT, exp.DataType.Type.DECIMAL, exp.DataType.Type.DOUBLE,
              exp.DataType.Type.FLOAT, exp.DataType.Type.TEXT, exp.DataType.Type.VARCHAR,
              exp.DataType.Type.BOOLEAN, exp.DataType.Type.DATE, exp.DataType.Type.TIMESTAMP,
              exp.DataType.Type.TIMESTAMPTZ, exp.DataType.Type.TIMESTAMPNTZ}


def _cast_type(data_type: exp.DataType) -> exp.DataType | None:
    kind = data_type.this
    if kind not in CAST_TYPES:
        return None
    if kind == exp.DataType.Type.DECIMAL:
        return map_decimal(data_type, (10, 0))  # Spark's DECIMAL is DECIMAL(10, 0)
    if kind in (exp.DataType.Type.TEXT, exp.DataType.Type.VARCHAR):
        return exp.DataType.build('VARCHAR')
    if kind in (exp.DataType.Type.TIMESTAMP, exp.DataType.Type.TIMESTAMPTZ, exp.DataType.Type.TIMESTAMPNTZ):
        return exp.DataType.build('TIMESTAMP')
    return exp.DataType.build(kind.value)


CAST_RULES = CastRules(engine=ENGINE, types=_cast_type, decimal_to_integer='truncate', float_to_integer='truncate',
                       string_to_integer_error='[CAST_INVALID_INPUT] The value cannot be cast to INT because it is malformed.')


def _unit(node: exp.Expression) -> str:
    unit = node.args.get('unit')
    name = unit.name if isinstance(unit, (exp.Var, exp.Literal, exp.Identifier, exp.Column)) else str(unit or '')
    return name.upper().strip("'")


class Spark(Dialect):
    id = 'spark'
    read = 'databricks'
    name = 'Spark SQL'
    language = 'Spark SQL'
    engine = 'Spark'
    functions = FUNCTIONS
    syntax = SYNTAX
    labels = {exp.Explode: 'EXPLODE and arrays', exp.Array: 'Arrays', exp.Struct: 'STRUCT values',
              exp.Lateral: 'LATERAL VIEW', exp.TableSample: 'TABLESAMPLE', exp.Interval: 'INTERVAL literals'}
    error = SparkDialectError

    def check(self, node: exp.Expression, ctx: Context) -> None:
        if isinstance(node, exp.DataType) and not isinstance(node.parent, exp.DataType) and _cast_type(node) is None:
            raise ctx.refuse_type(node)
        if isinstance(node, exp.TimeToStr) or isinstance(node, exp.TsOrDsToDate) and node.args.get('format') is not None:
            fmt = node.args.get('format')
            text = fmt.this.replace('strict', '') if isinstance(fmt, exp.Literal) and fmt.is_string else None
            if text is None or not FORMAT.fullmatch(text):
                raise self.refuse(f'{self.function_name(node)} with this pattern is not in the supported Spark SQL subset '
                                  '(use yyyy, yy, MM, MMM, MMMM, dd, HH, mm, ss, E, EEEE and separators)')
        if isinstance(node, (exp.RegexpExtract, exp.RegexpReplace, exp.RegexpLike)):
            extra = [k for k, v in node.args.items() if v is not None and k in ('position', 'occurrence', 'parameters', 'modifiers')]
            if extra:
                raise self.refuse(f'{self.function_name(node)} with a position is not in the supported Spark SQL subset')
        if isinstance(node, exp.Count) and isinstance(node.this, exp.Distinct) and len(node.this.expressions) > 1:
            raise self.refuse('COUNT(DISTINCT a, b) is not in the supported Spark SQL subset')

    def rewrite(self, node: exp.Expression, ctx: Context) -> exp.Expression:
        if isinstance(node, (exp.Cast, exp.TryCast)):
            return cast(node, ctx, CAST_RULES)
        if isinstance(node, (exp.Div, exp.IntDiv, exp.Mod)):
            if isinstance(node, exp.Div):
                node.set('safe', None)  # ANSI mode: no NULLIF(divisor, 0)
            guard_division(node, ctx, DIVIDE_BY_ZERO, ENGINE)
            return node
        if isinstance(node, exp.TsOrDsAdd):
            ctx.note('DATE_ADD and DATE_SUB return a DATE, as in Spark')
            return typed(duck('CAST(CAST({d} AS DATE) + INTERVAL ({n}) DAY AS DATE)', d=unwrap(node.this), n=node.expression), 'DATE')
        if isinstance(node, exp.AddMonths):
            ctx.note('ADD_MONTHS returns a DATE, as in Spark')
            return typed(duck('CAST(CAST({d} AS DATE) + INTERVAL ({n}) MONTH AS DATE)', d=unwrap(node.this), n=node.expression), 'DATE')
        if isinstance(node, exp.DateTrunc):
            unit = TRUNC_UNITS.get(_unit(node))
            if unit is None:
                raise self.refuse(f'TRUNC(date, {_unit(node).lower()}) is not in the supported Spark SQL subset')
            return typed(duck("CAST(DATE_TRUNC('" + unit + "', CAST({d} AS DATE)) AS DATE)", d=unwrap(node.this)), 'DATE')
        if isinstance(node, exp.TimestampTrunc):
            unit = TIMESTAMP_TRUNC_UNITS.get(_unit(node))
            if unit is None:
                raise self.refuse(f'DATE_TRUNC({_unit(node).lower()}, ...) is not in the supported Spark SQL subset')
            return typed(duck("DATE_TRUNC('" + unit + "', CAST({d} AS TIMESTAMP))", d=unwrap(node.this)), 'TIMESTAMP')
        if isinstance(node, exp.DayOfWeek):
            ctx.note('DAYOFWEEK counts Sunday as 1, as in Spark')
            return typed(sunday_one_weekday(cast_to(unwrap(node.this), 'DATE')), 'BIGINT')
        if isinstance(node, exp.Extract):
            return self._extract(node, ctx)
        if isinstance(node, exp.TsOrDsToDate):
            return self._to_date(node, ctx)
        if isinstance(node, exp.Substring):
            return first_position_substring(node, ctx)
        return node

    def _extract(self, node: exp.Extract, ctx: Context) -> exp.Expression:
        part = node.this.name.upper()
        value = unwrap(node.expression)
        if part in ('DAYOFWEEK', 'DOW'):
            ctx.note('EXTRACT(DAYOFWEEK) counts Sunday as 1, as in Spark')
            return typed(sunday_one_weekday(value), 'BIGINT')
        if part not in EXTRACT_PARTS:
            raise self.refuse(f'EXTRACT({part}) is not in the supported Spark SQL subset')
        return typed(duck('EXTRACT(' + EXTRACT_PARTS[part] + ' FROM {d})', d=value), 'BIGINT')

    def _to_date(self, node: exp.TsOrDsToDate, ctx: Context) -> exp.Expression:
        fmt = node.args.get('format')
        safe = bool(node.args.get('safe'))
        if fmt is None:
            return typed((exp.TryCast if safe else exp.Cast)(this=node.this, to=exp.DataType.build('DATE')), 'DATE')
        pattern = exp.Literal.string(fmt.this.replace('strict', ''))
        parsed = exp.Anonymous(this='TRY_STRPTIME' if safe else 'STRPTIME', expressions=[node.this, pattern])
        return typed(cast_to(parsed, 'DATE'), 'DATE')
