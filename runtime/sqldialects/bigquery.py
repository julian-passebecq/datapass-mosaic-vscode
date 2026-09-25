"""BigQuery GoogleSQL translated to DuckDB, for a documented subset. Arrays, structs and time zones are not in it."""
from __future__ import annotations

import re

from sqlglot import exp

from .core import QUERY_SYNTAX, Context, Dialect, DialectError, classes
from .rules import (CastRules, cast, cast_to, duck, first_position_substring, guard_division, map_decimal,
                    regexp_group, sunday_one_weekday, sunday_week_diff, typed, unwrap)

ENGINE = 'BigQuery'
DIVIDE_BY_ZERO = 'division by zero'


class BigQueryDialectError(DialectError):
    """The SQL is outside the supported BigQuery subset (or not valid GoogleSQL)."""


FUNCTIONS: dict[str, frozenset[type]] = {
    'aggregate': classes('Count', 'CountIf', 'Sum', 'Avg', 'Min', 'Max', 'Stddev', 'StddevSamp', 'StddevPop',
                         'Variance', 'VariancePop', 'GroupConcat', 'LogicalAnd', 'LogicalOr'),
    'window': classes('RowNumber', 'Rank', 'DenseRank', 'Ntile', 'Lag', 'Lead', 'FirstValue', 'LastValue',
                      'PercentRank', 'CumeDist'),
    'conditional': classes('If', 'Case', 'Coalesce', 'Nullif', 'Greatest', 'Least'),
    'string': classes('Upper', 'Lower', 'Length', 'Trim', 'Left', 'Right', 'Substring', 'StrPosition', 'Replace',
                      'Repeat', 'Reverse', 'Concat', 'Pad', 'StartsWith', 'EndsWith', 'RegexpLike', 'RegexpExtract',
                      'RegexpReplace'),
    'date': classes('DateAdd', 'DateSub', 'DateDiff', 'DateTrunc', 'Extract', 'TimeToStr', 'StrToDate',
                    'DateFromParts', 'Date', 'LastDay', 'TsOrDsToDate'),
    'numeric': classes('Abs', 'Round', 'Ceil', 'Floor', 'Trunc', 'Sqrt', 'Pow', 'Ln', 'Log', 'Exp', 'Sign',
                       'SafeDivide'),
    'conversion': classes('Cast', 'TryCast'),
}
SYNTAX = QUERY_SYNTAX | classes('Qualify', 'NullSafeEQ', 'NullSafeNEQ', 'Interval', 'IntDiv', 'RawString',
                                'WeekStart')
# FORMAT_DATE / PARSE_DATE elements: %Y %y %m %d %b %B %a %A %H %M %S %j and separators.
FORMAT = re.compile(r'^(%[YymdbBaAHMSj]|[-/ :.,T])+$')
DATE_PARTS = {'DAY', 'WEEK', 'MONTH', 'QUARTER', 'YEAR'}
EXTRACT_PARTS = {'YEAR': 'year', 'QUARTER': 'quarter', 'MONTH': 'month', 'DAY': 'day', 'DAYOFYEAR': 'doy',
                 'HOUR': 'hour', 'MINUTE': 'minute', 'SECOND': 'second', 'ISOWEEK': 'week', 'ISOYEAR': 'isoyear'}
CAST_TYPES = {exp.DataType.Type.BIGINT, exp.DataType.Type.INT, exp.DataType.Type.DECIMAL,
              exp.DataType.Type.DOUBLE, exp.DataType.Type.FLOAT, exp.DataType.Type.TEXT, exp.DataType.Type.VARCHAR,
              exp.DataType.Type.BOOLEAN, exp.DataType.Type.DATE, exp.DataType.Type.DATETIME,
              exp.DataType.Type.TIMESTAMP, exp.DataType.Type.TIMESTAMPTZ}


def _cast_type(data_type: exp.DataType) -> exp.DataType | None:
    kind = data_type.this
    if kind not in CAST_TYPES:
        return None
    if kind == exp.DataType.Type.DECIMAL:
        return map_decimal(data_type, (38, 9))  # NUMERIC is DECIMAL(38, 9)
    if kind in (exp.DataType.Type.BIGINT, exp.DataType.Type.INT):
        return exp.DataType.build('BIGINT')
    if kind in (exp.DataType.Type.TEXT, exp.DataType.Type.VARCHAR):
        return exp.DataType.build('VARCHAR')
    if kind in (exp.DataType.Type.DATETIME, exp.DataType.Type.TIMESTAMP, exp.DataType.Type.TIMESTAMPTZ):
        return exp.DataType.build('TIMESTAMP')
    if kind == exp.DataType.Type.FLOAT:
        return exp.DataType.build('DOUBLE')
    return exp.DataType.build(kind.value)


CAST_RULES = CastRules(engine=ENGINE, types=_cast_type, decimal_to_integer='plain', float_to_integer='round',
                       string_to_integer_error='Bad int64 value')


def _part(node: exp.Expression, key: str = 'unit') -> str:
    """The date part, with WEEK(SUNDAY) (sqlglot's WeekStart) as WEEK; WEEK(<another day>) is not in the subset."""
    unit = node.args.get(key)
    if isinstance(unit, exp.WeekStart):
        return 'WEEK' if unit.this.name.upper() == 'SUNDAY' else f'WEEK({unit.this.name.upper()})'
    name = unit.name if isinstance(unit, (exp.Var, exp.Literal, exp.Identifier, exp.Column)) else str(unit or '')
    return name.upper()


class BigQuery(Dialect):
    id = 'bigquery'
    read = 'bigquery'
    name = 'BigQuery'
    language = 'BigQuery SQL'
    engine = 'BigQuery'
    functions = FUNCTIONS
    syntax = SYNTAX
    labels = {exp.Unnest: 'UNNEST and arrays', exp.Array: 'Arrays', exp.Struct: 'STRUCT values',
              exp.Lateral: 'LATERAL joins', exp.TableSample: 'TABLESAMPLE', exp.Parameter: 'Query parameters'}
    decimal_literals = False  # 2.5 is a FLOAT64 in BigQuery
    error = BigQueryDialectError

    def check(self, node: exp.Expression, ctx: Context) -> None:
        if isinstance(node, exp.DataType) and not isinstance(node.parent, exp.DataType) and _cast_type(node) is None:
            raise ctx.refuse_type(node)
        if isinstance(node, exp.Table) and node.args.get('catalog') is not None:
            raise self.refuse('project.dataset.table names are not in the supported BigQuery subset: the local '
                              'catalog has datasets (layers) and tables')
        if isinstance(node, exp.Interval) and not isinstance(node.parent, (exp.DateAdd, exp.DateSub)):
            raise self.refuse('INTERVAL values are in the supported BigQuery subset only inside DATE_ADD and DATE_SUB')
        if isinstance(node, (exp.RegexpExtract, exp.RegexpReplace, exp.RegexpLike)):
            extra = [k for k, v in node.args.items() if v is not None and k in ('position', 'occurrence', 'parameters', 'modifiers')]
            if extra:
                raise self.refuse(f'{self.function_name(node)} with position, occurrence or flags is not in the supported BigQuery subset')
        if isinstance(node, (exp.TimeToStr, exp.StrToDate)):
            fmt = node.args.get('format')
            if not (isinstance(fmt, exp.Literal) and fmt.is_string and FORMAT.fullmatch(fmt.this)):
                raise self.refuse(f'{self.function_name(node)} with this format is not in the supported BigQuery subset '
                                  '(use %Y, %y, %m, %d, %b, %B, %a, %A, %H, %M, %S, %j and separators)')
        if isinstance(node, exp.LastDay) and node.args.get('unit') is not None and _part(node) != 'MONTH':
            raise self.refuse('LAST_DAY is in the supported BigQuery subset for MONTH only')
        if isinstance(node, exp.Count) and isinstance(node.this, exp.Distinct) and len(node.this.expressions) > 1:
            raise self.refuse('COUNT(DISTINCT a, b) is not valid BigQuery SQL')

    def rewrite(self, node: exp.Expression, ctx: Context) -> exp.Expression:
        if isinstance(node, (exp.Cast, exp.TryCast)):
            return cast(node, ctx, CAST_RULES)
        if isinstance(node, (exp.Div, exp.IntDiv, exp.Mod)):
            guard_division(node, ctx, DIVIDE_BY_ZERO, ENGINE)
            return node
        if isinstance(node, (exp.DateAdd, exp.DateSub)):
            return self._date_add(node, ctx)
        if isinstance(node, exp.DateDiff):
            return self._date_diff(node, ctx)
        if isinstance(node, exp.DateTrunc):
            return self._date_trunc(node, ctx)
        if isinstance(node, exp.Extract):
            return self._extract(node, ctx)
        if isinstance(node, exp.RegexpExtract):
            return self._regexp_extract(node, ctx)
        if isinstance(node, exp.Substring):
            return first_position_substring(node, ctx)
        return node

    def _date_add(self, node: exp.Expression, ctx: Context) -> exp.Expression:
        part = _part(node)
        if part not in DATE_PARTS:
            raise self.refuse(f'Date part {part.lower()} in {self.function_name(node)} is not in the supported BigQuery subset')
        amount = node.expression.this if isinstance(node.expression, exp.Interval) else node.expression
        if isinstance(amount, exp.Literal) and amount.is_string:
            amount = exp.Literal.number(amount.this)
        if part == 'QUARTER':
            amount, part = exp.Mul(this=exp.Literal.number(3), expression=exp.Paren(this=amount)), 'MONTH'
        sign = exp.Sub if isinstance(node, exp.DateSub) else exp.Add
        ctx.note('DATE_ADD and DATE_SUB return a DATE, as in BigQuery')
        shifted = sign(this=cast_to(unwrap(node.this), 'DATE'),
                       expression=exp.Interval(this=exp.Paren(this=amount), unit=exp.Var(this=part)))
        return typed(cast_to(shifted, 'DATE'), 'DATE')

    def _date_diff(self, node: exp.DateDiff, ctx: Context) -> exp.Expression:
        part = _part(node)
        end, start = unwrap(node.this), unwrap(node.expression)
        if part == 'WEEK':
            ctx.note('DATE_DIFF(..., WEEK) counts week boundaries, weeks starting on Sunday, as in BigQuery')
            return typed(sunday_week_diff(start, end), 'BIGINT')
        if part == 'ISOWEEK':
            return typed(duck("DATE_DIFF('week', DATE_TRUNC('week', CAST({a} AS DATE)), DATE_TRUNC('week', CAST({b} AS DATE)))",
                              a=start, b=end), 'BIGINT')
        if part not in ('DAY', 'MONTH', 'QUARTER', 'YEAR'):
            raise self.refuse(f'Date part {part.lower()} in DATE_DIFF is not in the supported BigQuery subset')
        return typed(duck("DATE_DIFF('" + part.lower() + "', CAST({a} AS DATE), CAST({b} AS DATE))", a=start, b=end), 'BIGINT')

    def _date_trunc(self, node: exp.DateTrunc, ctx: Context) -> exp.Expression:
        part = _part(node)
        value = unwrap(node.this)
        if part == 'WEEK':
            ctx.note('DATE_TRUNC(..., WEEK) goes back to Sunday, as in BigQuery')
            return typed(duck('CAST({d} AS DATE) - CAST(DAYOFWEEK(CAST({d} AS DATE)) AS INTEGER)', d=value), 'DATE')
        units = {'ISOWEEK': 'week', 'DAY': 'day', 'MONTH': 'month', 'QUARTER': 'quarter', 'YEAR': 'year'}
        if part not in units:
            raise self.refuse(f'Date part {part.lower()} in DATE_TRUNC is not in the supported BigQuery subset')
        ctx.note('DATE_TRUNC of a DATE returns a DATE, as in BigQuery')
        return typed(duck("CAST(DATE_TRUNC('" + units[part] + "', CAST({d} AS DATE)) AS DATE)", d=value), 'DATE')

    def _extract(self, node: exp.Extract, ctx: Context) -> exp.Expression:
        part = node.this.name.upper()
        value = unwrap(node.expression)
        if part == 'DAYOFWEEK':
            ctx.note('EXTRACT(DAYOFWEEK) counts Sunday as 1, as in BigQuery')
            return typed(sunday_one_weekday(value), 'BIGINT')
        if part not in EXTRACT_PARTS:
            raise self.refuse(f'EXTRACT({part}) is not in the supported BigQuery subset (week numbers start on Sunday '
                              'there: use ISOWEEK)')
        return typed(duck('EXTRACT(' + EXTRACT_PARTS[part] + ' FROM {d})', d=value), 'BIGINT')

    def _regexp_extract(self, node: exp.RegexpExtract, ctx: Context) -> exp.Expression:
        groups = regexp_group(node.expression)
        if groups is None:
            raise self.refuse('REGEXP_EXTRACT needs a literal pattern here (its capturing group decides the result)')
        if groups > 1:
            raise self.refuse('REGEXP_EXTRACT with more than one capturing group is an error in BigQuery')
        ctx.note('REGEXP_EXTRACT returns NULL when nothing matches, and the capturing group when there is one, as in BigQuery')
        return duck('CASE WHEN REGEXP_MATCHES({s}, {p}) THEN REGEXP_EXTRACT({s}, {p}, ' + str(groups) + ') END',
                    s=node.this, p=node.expression)
