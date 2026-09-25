"""PostgreSQL translated to DuckDB, for a documented subset. Arrays, JSON, set-returning functions and time zones are
not in it."""
from __future__ import annotations

import re

from sqlglot import exp

from .core import QUERY_SYNTAX, Context, Dialect, DialectError, classes
from .rules import (CastRules, cast, duck, guard_division, length_param, map_decimal, standard_substring, typed,
                    typed_division)

ENGINE = 'PostgreSQL'
DIVIDE_BY_ZERO = 'division by zero'


class PostgresDialectError(DialectError):
    """The SQL is outside the supported PostgreSQL subset (or not valid PostgreSQL)."""


FUNCTIONS: dict[str, frozenset[type]] = {
    'aggregate': classes('Count', 'Sum', 'Avg', 'Min', 'Max', 'Stddev', 'StddevSamp', 'StddevPop', 'Variance',
                         'VariancePop', 'GroupConcat', 'LogicalAnd', 'LogicalOr', 'PercentileCont'),
    'window': classes('RowNumber', 'Rank', 'DenseRank', 'Ntile', 'Lag', 'Lead', 'FirstValue', 'LastValue',
                      'PercentRank', 'CumeDist'),
    'conditional': classes('Case', 'Coalesce', 'Nullif', 'Greatest', 'Least'),
    'string': classes('Upper', 'Lower', 'Length', 'Trim', 'Left', 'Right', 'Substring', 'StrPosition', 'Replace',
                      'Repeat', 'Reverse', 'Concat', 'ConcatWs', 'Pad', 'SplitPart', 'RegexpReplace', 'RegexpLike',
                      'RegexpILike', 'StartsWith'),
    'date': classes('TimeToStr', 'StrToDate', 'TimestampTrunc', 'Extract'),
    'numeric': classes('Abs', 'Round', 'Ceil', 'Floor', 'Trunc', 'Sqrt', 'Pow', 'Ln', 'Log', 'Exp', 'Sign'),
    'conversion': classes('Cast'),
}
SYNTAX = QUERY_SYNTAX | classes('ILike', 'NullSafeEQ', 'NullSafeNEQ', 'Interval', 'Filter', 'WithinGroup', 'Fetch',
                                'IntDiv')
# TO_CHAR / TO_DATE patterns (as strftime): YYYY YY MM DD HH24 MI SS and separators (names differ in case and padding).
FORMAT = re.compile(r'^(%[YymdHMS]|[-/ :.,T])+$')
EXTRACT_PARTS = {'YEAR': 'year', 'QUARTER': 'quarter', 'MONTH': 'month', 'DAY': 'day', 'DAYOFWEEK': 'dow',
                 'DOW': 'dow', 'ISODOW': 'isodow', 'DAYOFYEAR': 'doy', 'DOY': 'doy', 'HOUR': 'hour',
                 'MINUTE': 'minute', 'WEEK': 'week'}
TRUNC_UNITS = {'YEAR', 'QUARTER', 'MONTH', 'WEEK', 'DAY', 'HOUR', 'MINUTE', 'SECOND'}
INTERVAL_UNITS = {'YEAR', 'MONTH', 'WEEK', 'DAY', 'HOUR', 'MINUTE', 'SECOND'}
CAST_TYPES = {exp.DataType.Type.INT, exp.DataType.Type.BIGINT, exp.DataType.Type.SMALLINT,
              exp.DataType.Type.DECIMAL, exp.DataType.Type.DOUBLE, exp.DataType.Type.FLOAT,
              exp.DataType.Type.TEXT, exp.DataType.Type.VARCHAR, exp.DataType.Type.BOOLEAN, exp.DataType.Type.DATE,
              exp.DataType.Type.TIMESTAMP}


def _cast_type(data_type: exp.DataType) -> exp.DataType | None:
    kind = data_type.this
    if kind not in CAST_TYPES:
        return None
    if kind == exp.DataType.Type.DECIMAL:
        return map_decimal(data_type, (38, 10))  # NUMERIC without a precision: 38 digits, 10 after the point here
    if kind in (exp.DataType.Type.TEXT, exp.DataType.Type.VARCHAR):
        return exp.DataType.build('VARCHAR')
    return exp.DataType.build(kind.value)


def _string_cast(node: exp.Expression, written: exp.DataType, mapped: exp.DataType, ctx: Context) -> exp.Expression:
    value = exp.Cast(this=node.this, to=exp.DataType.build('VARCHAR'))
    size = length_param(written)
    if isinstance(size, int):
        ctx.note('CAST to VARCHAR(n) keeps the first n characters, as in PostgreSQL')
        return typed(exp.Left(this=value, expression=exp.Literal.number(size)), 'VARCHAR')
    return typed(value, 'VARCHAR')


CAST_RULES = CastRules(engine=ENGINE, types=_cast_type, decimal_to_integer='plain', float_to_integer='plain',
                       string_to_integer_error='invalid input syntax for type integer', string_rules=_string_cast)


def _unit(node: exp.Expression) -> str:
    unit = node.args.get('unit')
    name = unit.name if isinstance(unit, (exp.Var, exp.Literal, exp.Identifier, exp.Column)) else str(unit or '')
    return name.upper().strip("'")


class Postgres(Dialect):
    id = 'postgres'
    read = 'postgres'
    name = 'PostgreSQL'
    language = 'PostgreSQL'
    engine = 'PostgreSQL'
    functions = FUNCTIONS
    syntax = SYNTAX
    labels = {exp.Array: 'Arrays', exp.Unnest: 'UNNEST', exp.Lateral: 'LATERAL joins',
              exp.JSONExtract: 'JSON operators', exp.JSONExtractScalar: 'JSON operators',
              exp.TableSample: 'TABLESAMPLE', exp.ExplodingGenerateSeries: 'GENERATE_SERIES',
              exp.Placeholder: 'Parameters ($1)'}
    error = PostgresDialectError

    def check(self, node: exp.Expression, ctx: Context) -> None:
        if isinstance(node, exp.DataType) and not isinstance(node.parent, exp.DataType) and _cast_type(node) is None:
            raise ctx.refuse_type(node)
        if isinstance(node, (exp.TimeToStr, exp.StrToDate)):
            fmt = node.args.get('format')
            if not (isinstance(fmt, exp.Literal) and fmt.is_string and FORMAT.fullmatch(fmt.this)):
                raise self.refuse(f'{self.function_name(node)} with this pattern is not in the supported PostgreSQL subset '
                                  '(use YYYY, YY, MM, DD, HH24, MI, SS and separators)')
        if isinstance(node, exp.Interval) and _unit(node) not in INTERVAL_UNITS:
            raise self.refuse(f'INTERVAL {node.sql(dialect="postgres")} is not in the supported PostgreSQL subset '
                              '(one unit: year, month, week, day, hour, minute or second)')
        if isinstance(node, exp.RegexpReplace):
            modifiers = node.args.get('modifiers')
            if modifiers is not None and not (isinstance(modifiers, exp.Literal) and modifiers.this == 'g'):
                raise self.refuse('REGEXP_REPLACE flags other than \'g\' are not in the supported PostgreSQL subset')
            if node.args.get('position') is not None or node.args.get('occurrence') is not None:
                raise self.refuse('REGEXP_REPLACE with a start or an occurrence is not in the supported PostgreSQL subset')
        if isinstance(node, exp.Substring) and isinstance(node.args.get('start'), exp.Literal) \
                and node.args['start'].is_string:
            raise self.refuse('SUBSTRING(text FROM pattern) is not in the supported PostgreSQL subset')

    def rewrite(self, node: exp.Expression, ctx: Context) -> exp.Expression:
        if isinstance(node, exp.Identifier) and not node.quoted:
            # PostgreSQL folds unquoted identifiers to lower case: result columns are named in lower case.
            node.set('this', node.this.lower())
            return node
        if isinstance(node, exp.Cast):
            return cast(node, ctx, CAST_RULES)
        if isinstance(node, exp.Div):
            guard_division(node, ctx, DIVIDE_BY_ZERO, ENGINE)
            return typed_division(node, ctx, ENGINE)
        if isinstance(node, (exp.Mod, exp.IntDiv)):
            guard_division(node, ctx, DIVIDE_BY_ZERO, ENGINE)
            return node
        if isinstance(node, exp.Sub) and ctx.category(node.this) == 'timestamp' and ctx.category(node.expression) == 'timestamp':
            raise self.refuse('Subtracting timestamps gives an INTERVAL, which is not in the supported PostgreSQL subset')
        if isinstance(node, exp.Round):
            return self._round(node, ctx)
        if isinstance(node, exp.Extract):
            part = node.this.name.upper()
            if part not in EXTRACT_PARTS:
                raise self.refuse(f'EXTRACT({part}) is not in the supported PostgreSQL subset')
            return typed(duck('EXTRACT(' + EXTRACT_PARTS[part] + ' FROM {d})', d=node.expression), 'BIGINT')
        if isinstance(node, exp.TimestampTrunc):
            unit = _unit(node)
            if unit not in TRUNC_UNITS:
                raise self.refuse(f'DATE_TRUNC(\'{unit.lower()}\', ...) is not in the supported PostgreSQL subset')
            return typed(duck("DATE_TRUNC('" + unit.lower() + "', CAST({d} AS TIMESTAMP))", d=node.this), 'TIMESTAMP')
        if isinstance(node, exp.Substring):
            return standard_substring(node, ctx)
        return node

    def _round(self, node: exp.Round, ctx: Context) -> exp.Expression:
        kind = ctx.category(node.this)
        if kind == 'float':
            if node.args.get('decimals') is not None:
                raise self.refuse('ROUND(double precision, n) does not exist in PostgreSQL: cast the value to NUMERIC')
            ctx.note('ROUND of a double precision value rounds half to even, as in PostgreSQL')
            return typed(duck('ROUND_EVEN({x}, 0)', x=node.this), 'DOUBLE')
        if kind is None:
            raise self.refuse('ROUND needs a value whose type is known here: PostgreSQL rounds NUMERIC half away '
                              'from zero and double precision half to even')
        return node
