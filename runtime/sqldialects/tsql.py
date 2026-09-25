"""T-SQL (SQL Server, Azure SQL, Synapse dedicated SQL pool, Fabric Warehouse) translated to DuckDB.

Defaults assumed: SET DATEFIRST 7 (us_english: Sunday is weekday 1), CONCAT_NULL_YIELDS_NULL ON, ANSI_NULLS ON.
The Cloud Lab SQL pool uses this dialect for every expression and query (`runtime/sqlpoollab/tsql.py` keeps only the
Synapse-specific statements); it passes hooks for its variables, its fixed clock and its schema names.
"""
from __future__ import annotations

import re

from sqlglot import exp

from .core import QUERY_SYNTAX, Context, Dialect, DialectError, category, classes, error_call, keep_type
from .rules import (CastRules, cast, cast_to, date_category, duck, guard_division, interval, length_param,
                    map_decimal, standard_substring, sunday_one_weekday, sunday_week_diff, typed, typed_division,
                    unwrap)

ENGINE = 'T-SQL'
DIVIDE_BY_ZERO = 'Divide by zero error encountered.'


class TsqlDialectError(DialectError):
    """The SQL is outside the supported T-SQL subset (or not valid T-SQL)."""


FUNCTIONS: dict[str, frozenset[type]] = {
    'aggregate': classes('Count', 'Sum', 'Avg', 'Min', 'Max', 'Stddev', 'StddevPop', 'Variance', 'VariancePop',
                         'GroupConcat'),
    'window': classes('RowNumber', 'Rank', 'DenseRank', 'Ntile', 'Lag', 'Lead', 'FirstValue', 'LastValue',
                      'PercentRank', 'CumeDist'),
    'conditional': classes('If', 'Case', 'Coalesce', 'Nullif', 'Greatest', 'Least'),
    'string': classes('Upper', 'Lower', 'Length', 'Trim', 'Left', 'Right', 'Substring', 'StrPosition', 'Replace',
                      'Repeat', 'Reverse', 'Stuff', 'Concat', 'ConcatWs', 'Space', 'Ascii', 'Chr', 'Unicode'),
    'date': classes('DateAdd', 'DateDiff', 'Extract', 'TimeToStr', 'Year', 'Month', 'Day', 'LastDay',
                    'DateFromParts', 'TimestampTrunc', 'TsOrDsToDate', 'TimeStrToTime'),
    'numeric': classes('Abs', 'Round', 'Ceil', 'Floor', 'Sqrt', 'Pow', 'Ln', 'Log', 'Exp', 'Sign', 'Pi'),
    'conversion': classes('Cast', 'TryCast', 'Convert'),
}
SYNTAX = QUERY_SYNTAX | classes('Fetch', 'LimitOptions', 'National', 'Escape')

# T-SQL type name -> DuckDB type (also the SQL pool's column types). decimal/numeric and float take parameters.
DUCKDB_TYPES = {
    'bigint': 'BIGINT', 'int': 'INTEGER', 'integer': 'INTEGER', 'smallint': 'SMALLINT', 'tinyint': 'UTINYINT',
    'bit': 'BOOLEAN', 'money': 'DECIMAL(19,4)', 'smallmoney': 'DECIMAL(10,4)', 'real': 'FLOAT', 'date': 'DATE',
    'time': 'TIME', 'datetime': 'TIMESTAMP', 'datetime2': 'TIMESTAMP', 'smalldatetime': 'TIMESTAMP',
    'datetimeoffset': 'TIMESTAMPTZ', 'char': 'VARCHAR', 'varchar': 'VARCHAR', 'nchar': 'VARCHAR',
    'nvarchar': 'VARCHAR', 'uniqueidentifier': 'UUID', 'binary': 'BLOB', 'varbinary': 'BLOB',
}
# Types an expression may CAST or CONVERT to here (time zones and binary data are not in the subset).
CAST_TYPES = {exp.DataType.Type.INT, exp.DataType.Type.BIGINT, exp.DataType.Type.SMALLINT,
              exp.DataType.Type.UTINYINT, exp.DataType.Type.TINYINT, exp.DataType.Type.BIT,
              exp.DataType.Type.BOOLEAN, exp.DataType.Type.DECIMAL, exp.DataType.Type.MONEY,
              exp.DataType.Type.SMALLMONEY, exp.DataType.Type.FLOAT, exp.DataType.Type.DOUBLE,
              exp.DataType.Type.DATE, exp.DataType.Type.TIME, exp.DataType.Type.DATETIME,
              exp.DataType.Type.DATETIME2, exp.DataType.Type.SMALLDATETIME, exp.DataType.Type.VARCHAR,
              exp.DataType.Type.NVARCHAR, exp.DataType.Type.CHAR, exp.DataType.Type.NCHAR, exp.DataType.Type.TEXT,
              exp.DataType.Type.UUID}
# CONVERT styles for dates and times: style -> strftime format; time styles need a DATETIME value.
STYLES = {23: '%Y-%m-%d', 101: '%m/%d/%Y', 103: '%d/%m/%Y', 104: '%d.%m.%Y', 112: '%Y%m%d',
          120: '%Y-%m-%d %H:%M:%S', 121: '%Y-%m-%d %H:%M:%S.%g'}
TIME_STYLES = {120, 121}
ADD_PARTS = {'YEAR', 'QUARTER', 'MONTH', 'WEEK', 'DAY', 'HOUR', 'MINUTE', 'SECOND'}
DAY_ALIASES = {'DAYOFYEAR': 'DAY', 'DAYOFWEEK': 'DAY', 'WEEKDAY': 'DAY'}
DATEPART_PARTS = {'YEAR': 'year', 'QUARTER': 'quarter', 'MONTH': 'month', 'DAYOFYEAR': 'doy', 'DAY': 'day',
                  'HOUR': 'hour', 'MINUTE': 'minute', 'SECOND': 'second'}
TRUNC_PARTS = {'YEAR', 'QUARTER', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND'}
AGGREGATE_NAMES = {'STDEVP': exp.StddevPop, 'VAR': exp.Variance, 'VARP': exp.VariancePop}
NOW_NAMES = {'GETDATE', 'SYSDATETIME', 'GETUTCDATE', 'SYSUTCDATETIME'}


def duckdb_type(name: str, params: list[str] | None = None) -> str:
    """The DuckDB type of a T-SQL type name and its parameters; ValueError when the type is not in the subset."""
    name, params = name.lower(), params or []
    if name in ('decimal', 'numeric'):
        precision = int(params[0]) if params and params[0].isdigit() else 18
        scale = int(params[1]) if len(params) > 1 and params[1].isdigit() else 0
        return f'DECIMAL({min(precision, 38)},{scale})'
    if name == 'float':
        return 'FLOAT' if params and params[0].isdigit() and int(params[0]) <= 24 else 'DOUBLE'
    if name in DUCKDB_TYPES:
        return DUCKDB_TYPES[name]
    raise ValueError(name)


def _cast_type(data_type: exp.DataType) -> exp.DataType | None:
    if data_type.this not in CAST_TYPES:
        return None
    if data_type.this == exp.DataType.Type.DECIMAL:
        return map_decimal(data_type, (18, 0))
    if data_type.this == exp.DataType.Type.FLOAT:
        size = length_param(data_type)
        return exp.DataType.build('FLOAT' if isinstance(size, int) and size <= 24 else 'DOUBLE')
    text = data_type.sql(dialect='tsql')
    name = re.match(r'[A-Za-z0-9_]+', text).group().lower()
    try:
        return exp.DataType.build(duckdb_type(name))
    except ValueError:
        return None


def _string_cast(node: exp.Expression, written: exp.DataType, mapped: exp.DataType, ctx: Context) -> exp.Expression:
    safe = isinstance(node, exp.TryCast) or bool(node.args.get('safe'))
    source = ctx.category(node.this)
    if source is None:
        raise ctx.refuse('CAST to text needs a value whose type is known here: T-SQL writes dates, times, floats '
                         'and BIT values differently from DuckDB')
    if source == 'timestamp':
        raise ctx.refuse('CAST of a date and time to text follows T-SQL style 0 (Jan 31 2024 10:15AM): use '
                         'CONVERT(VARCHAR(19), value, 120) for yyyy-mm-dd hh:mi:ss')
    if source == 'float':
        raise ctx.refuse('CAST of a float to text uses T-SQL\'s scientific notation: cast it to DECIMAL(p, s) first')
    if source == 'boolean':
        raise ctx.refuse('CAST of a BIT to text gives 1 or 0 in T-SQL: use CASE WHEN ... THEN \'1\' ELSE \'0\' END')
    value = (exp.TryCast if safe else exp.Cast)(this=node.this, to=exp.DataType.build('VARCHAR'))
    return typed(_limit_length(value, written, ctx, source), 'VARCHAR')


def _limit_length(value: exp.Expression, written: exp.DataType, ctx: Context, source: str | None = None) -> exp.Expression:
    """VARCHAR(n) keeps n characters, CHAR(n) pads to n, no length means 30 (CAST and CONVERT). A number that does
    not fit gives '*' (integers) or an overflow error (decimals), as in T-SQL."""
    size = length_param(written)
    if size == 'max' or written.this == exp.DataType.Type.TEXT:
        return value
    if size is None:
        ctx.note('CAST or CONVERT to VARCHAR without a length keeps 30 characters, as in T-SQL')
        size = 30
    if source in ('integer', 'decimal'):
        too_long = exp.GT(this=exp.Length(this=value.copy()), expression=exp.Literal.number(size))
        ctx.note('A number too long for VARCHAR(n) gives * (integers) or an overflow error (decimals), as in T-SQL')
        overflow = exp.Literal.string('*') if source == 'integer' else error_call(
            'Arithmetic overflow error converting numeric to data type varchar.')
        return exp.Case(ifs=[exp.If(this=too_long, true=overflow)], default=value)
    kept = exp.Left(this=value, expression=exp.Literal.number(size))
    if written.this in (exp.DataType.Type.CHAR, exp.DataType.Type.NCHAR):
        ctx.note('CHAR(n) pads with spaces to n characters, as in T-SQL')
        return exp.Pad(this=kept, expression=exp.Literal.number(size), fill_pattern=exp.Literal.string(' '),
                       is_left=False)
    ctx.note('CAST or CONVERT to VARCHAR(n) keeps the first n characters, as in T-SQL')
    return kept


CAST_RULES = CastRules(engine=ENGINE, types=_cast_type, decimal_to_integer='truncate', float_to_integer='truncate',
                       string_to_integer_error='Conversion failed when converting the varchar value to data type int.',
                       string_rules=_string_cast)


def _unit(node: exp.Expression) -> str:
    unit = node.args.get('unit')
    name = unit.name if isinstance(unit, (exp.Var, exp.Literal, exp.Identifier, exp.Column)) else str(unit or '')
    return name.upper().strip("'")


class Tsql(Dialect):
    id = 'tsql'
    read = 'tsql'
    name = 'T-SQL'
    language = 'T-SQL'
    engine = 'SQL Server'
    functions = FUNCTIONS
    syntax = SYNTAX
    labels = {exp.Into: 'SELECT ... INTO (write CREATE TABLE ... AS SELECT)', exp.Lateral: 'CROSS APPLY / OUTER APPLY',
              exp.Pivot: 'PIVOT / UNPIVOT', exp.Parameter: 'Variables', exp.Interval: 'INTERVAL literals'}
    error = TsqlDialectError

    # -- structure: the caller's hooks, stripped hints, internal casts ----------------------------------------------
    def prepare(self, tree: exp.Expression, ctx: Context) -> exp.Expression:
        hooks = ctx.hooks
        for node in list(tree.walk()):
            if isinstance(node, exp.Identifier) and node.args.get('temporary'):
                raise self.refuse(f'Temporary tables (#{node.name}) are not in the supported T-SQL subset: '
                                  'create a regular table')
            if isinstance(node, exp.QueryOption):
                ctx.note('OPTION (...) query hints are ignored: they do not change the result')
                node.pop()
            elif isinstance(node, exp.WithTableHint):
                ctx.note('Table hints such as WITH (NOLOCK) are ignored: they do not change the result')
                node.pop()
            elif isinstance(node, exp.Table) and hooks is not None:
                hooks.table(node)
            elif isinstance(node, exp.Parameter) and not isinstance(node.parent, exp.Parameter):
                if isinstance(node.this, exp.Parameter):
                    raise self.refuse(f'System variable @@{node.this.name} is not in the supported T-SQL subset')
                if hooks is None:
                    raise self.refuse(f'Variables (@{node.name}) are not in the supported T-SQL subset here: '
                                      'write the value, or use a CTE')
                node.replace(hooks.parameter(node))
            elif isinstance(node, exp.CurrentTimestamp) or (
                    isinstance(node, exp.Anonymous) and node.name.upper() in NOW_NAMES and not node.expressions):
                now = hooks.now() if hooks is not None else None
                if now is not None:
                    node.replace(now)
            elif isinstance(node, exp.Anonymous) and node.name.upper() in AGGREGATE_NAMES and len(node.expressions) == 1:
                node.replace(AGGREGATE_NAMES[node.name.upper()](this=node.expressions[0]))
            elif isinstance(node, (exp.Length, exp.Left, exp.Right)) and isinstance(node.this, exp.Cast) \
                    and node.this.to.this == exp.DataType.Type.TEXT:
                node.this.meta['dp_internal'] = True  # sqlglot's own conversion for LEN/LEFT/RIGHT
        return tree

    # -- the subset -------------------------------------------------------------------------------------------------
    def check(self, node: exp.Expression, ctx: Context) -> None:
        if isinstance(node, exp.DataType) and not isinstance(node.parent, exp.DataType) and node.this not in CAST_TYPES:
            raise ctx.refuse_type(node)
        if isinstance(node, exp.LimitOptions) and (node.args.get('percent') or node.args.get('with_ties')):
            raise self.not_in_subset('TOP ... PERCENT and TOP ... WITH TIES')
        if isinstance(node, exp.Round):
            if node.args.get('truncate') is not None:
                raise self.refuse('ROUND with a third (function) argument is not in the supported T-SQL subset')
            if node.args.get('decimals') is None:
                raise self.refuse('ROUND needs its length argument in T-SQL: ROUND(value, 0)')
        if isinstance(node, exp.TimeToStr) and not isinstance(node.args.get('format'), exp.Literal) \
                or isinstance(node, exp.TimeToStr) and node.args['format'].this not in ('%B', '%A'):
            raise self.refuse('FORMAT and DATENAME are in the supported T-SQL subset only for month and weekday '
                              'names; use CONVERT with a style for dates')
        if isinstance(node, exp.Like) and isinstance(node.expression, exp.Literal) and '[' in node.expression.this:
            raise self.refuse('LIKE patterns with [character classes] are not in the supported T-SQL subset')
        if isinstance(node, exp.Count) and isinstance(node.this, exp.Distinct) and len(node.this.expressions) > 1:
            raise self.refuse('COUNT(DISTINCT a, b) is not valid T-SQL')
        if isinstance(node, exp.StrPosition) and node.args.get('occurrence') is not None:
            raise self.not_in_subset('CHARINDEX with an occurrence')

    # -- rewrites ---------------------------------------------------------------------------------------------------
    def rewrite(self, node: exp.Expression, ctx: Context) -> exp.Expression:
        if isinstance(node, (exp.Cast, exp.TryCast)):
            if node.meta.get('dp_internal'):
                return typed(cast_to(node.this, 'VARCHAR'), 'VARCHAR')
            return cast(node, ctx, CAST_RULES)
        if isinstance(node, exp.Convert):
            return self._convert(node, ctx)
        if isinstance(node, exp.Div):
            guard_division(node, ctx, DIVIDE_BY_ZERO, ENGINE)
            return typed_division(node, ctx, ENGINE)
        if isinstance(node, exp.Mod):
            guard_division(node, ctx, DIVIDE_BY_ZERO, ENGINE)
            return node
        if isinstance(node, (exp.Add, exp.Sub)):
            return self._arithmetic(node, ctx)
        if isinstance(node, exp.Avg) and not isinstance(node.parent, exp.Window):
            return self._integer_avg(node, node, ctx)
        if isinstance(node, exp.Window) and isinstance(node.this, exp.Avg):
            return self._integer_avg(node.this, node, ctx)
        if isinstance(node, exp.Length):
            ctx.note('LEN ignores trailing spaces, as in T-SQL')
            return typed(duck('LENGTH(RTRIM(CAST({s} AS VARCHAR)))', s=unwrap_internal(node.this)), 'BIGINT')
        if isinstance(node, exp.DateAdd):
            return self._date_add(node, ctx)
        if isinstance(node, exp.DateDiff):
            return self._date_diff(node, ctx)
        if isinstance(node, exp.Extract):
            return self._datepart(node, ctx)
        if isinstance(node, exp.TimestampTrunc):
            return self._datetrunc(node, ctx)
        if isinstance(node, exp.Pow):
            return self._power(node, ctx)
        if isinstance(node, exp.Substring):
            return standard_substring(node, ctx)
        return node

    def _arithmetic(self, node: exp.Expression, ctx: Context) -> exp.Expression:
        left, right = ctx.category(node.this), ctx.category(node.expression)
        if left in ('date', 'timestamp') or right in ('date', 'timestamp'):
            raise self.refuse('Adding or subtracting numbers and dates is not in the supported T-SQL subset: '
                              'use DATEADD and DATEDIFF')
        if isinstance(node, exp.Add) and left == 'string' and right == 'string':
            ctx.note('+ between strings concatenates, as in T-SQL (NULL makes the result NULL)')
            return typed(exp.DPipe(this=node.this, expression=node.expression, safe=False), 'VARCHAR')
        return node

    def _integer_avg(self, avg: exp.Avg, node: exp.Expression, ctx: Context) -> exp.Expression:
        argument = avg.this.expressions[0] if isinstance(avg.this, exp.Distinct) else avg.this
        kind = ctx.category(argument)
        if kind == 'integer':
            ctx.note('AVG of integers is an integer that truncates, as in T-SQL')
            return typed(duck('CAST(TRUNC({a}) AS BIGINT)', a=node), 'BIGINT')
        if kind is None:
            raise self.refuse('AVG needs a value whose type is known here: T-SQL averages integers as integers. '
                              'Cast it to DECIMAL (or INT) to say which you mean')
        return node

    def _convert(self, node: exp.Convert, ctx: Context) -> exp.Expression:
        written, value, style = node.this, node.expression, node.args.get('style')
        safe = bool(node.args.get('safe'))
        if style is None:
            as_cast = (exp.TryCast if safe else exp.Cast)(this=value, to=written)
            keep_type(value, as_cast)
            return cast(as_cast, ctx, CAST_RULES)
        if not (isinstance(style, exp.Literal) and style.is_number and int(style.this) in STYLES):
            raise self.refuse(f'CONVERT style {style.sql(dialect="tsql")} is not in the supported T-SQL subset '
                              f'(supported: {", ".join(map(str, sorted(STYLES)))})')
        number = int(style.this)
        mapped = _cast_type(written)
        if mapped is None:
            raise ctx.refuse_type(written)
        source, wanted = date_category(ctx, value), category(mapped)
        fmt = exp.Literal.string(STYLES[number])
        if wanted == 'string':
            if source not in ('date', 'timestamp') or source == 'date' and number in TIME_STYLES:
                raise self.refuse(f'CONVERT with style {number} formats a {"DATETIME" if number in TIME_STYLES else "DATE or DATETIME"} '
                                  'value here; the value\'s type must be known to be one')
            ctx.note(f'CONVERT style {number} formats the date as T-SQL does')
            return typed(_limit_length(exp.TimeToStr(this=value, format=fmt), written, ctx), 'VARCHAR')
        if wanted in ('date', 'timestamp') and source == 'string':
            ctx.note(f'CONVERT style {number} reads the text as T-SQL does')
            parsed = exp.Anonymous(this='TRY_STRPTIME' if safe else 'STRPTIME', expressions=[value, fmt])
            return typed(cast_to(parsed, 'DATE') if wanted == 'date' else parsed, 'DATE' if wanted == 'date' else 'TIMESTAMP')
        raise self.refuse('CONVERT with a style converts between text and dates only in the supported T-SQL subset')

    def _date_add(self, node: exp.DateAdd, ctx: Context) -> exp.Expression:
        unit = DAY_ALIASES.get(_unit(node), _unit(node))
        if unit not in ADD_PARTS:
            raise self.refuse(f'Date part {unit.lower()} in DATEADD is not in the supported T-SQL subset')
        value, amount = unwrap(node.this), node.expression
        if ctx.category(amount) in ('decimal', 'float'):
            amount = exp.Trunc(this=amount)
        if unit == 'QUARTER':
            amount, unit = exp.Mul(this=exp.Literal.number(3), expression=exp.Paren(this=amount)), 'MONTH'
        kind = date_category(ctx, value)
        if kind == 'date':
            if unit in ('HOUR', 'MINUTE', 'SECOND'):
                raise self.refuse(f'DATEADD({unit.lower()}, ...) of a DATE is an error in T-SQL: cast it to DATETIME2 first')
            ctx.note('DATEADD of a DATE stays a DATE, as in T-SQL')
            return typed(cast_to(exp.Add(this=cast_to(value, 'DATE'), expression=interval(amount, unit)), 'DATE'), 'DATE')
        if kind in ('timestamp', 'string'):
            if kind == 'string':
                ctx.note('A string date in DATEADD is read as a DATETIME, as in T-SQL')
            return typed(exp.Add(this=cast_to(value, 'TIMESTAMP'), expression=interval(amount, unit)), 'TIMESTAMP')
        raise self.refuse('DATEADD needs a date whose type is known here (a DATE, a DATETIME or a date string)')

    def _date_diff(self, node: exp.DateDiff, ctx: Context) -> exp.Expression:
        unit = DAY_ALIASES.get(_unit(node), _unit(node))
        if unit not in ADD_PARTS:
            raise self.refuse(f'Date part {unit.lower()} in DATEDIFF is not in the supported T-SQL subset')
        start, end = unwrap(node.expression), unwrap(node.this)
        if date_category(ctx, start) is None or date_category(ctx, end) is None:
            raise self.refuse('DATEDIFF needs dates whose type is known here (DATE, DATETIME or date strings)')
        if unit == 'WEEK':
            ctx.note('DATEDIFF(week) counts week boundaries, weeks starting on Sunday, as in T-SQL')
            return typed(sunday_week_diff(start, end), 'BIGINT')
        if unit == 'QUARTER':
            return typed(duck("DATE_DIFF('quarter', CAST({a} AS TIMESTAMP), CAST({b} AS TIMESTAMP))", a=start, b=end), 'BIGINT')
        return typed(duck("DATE_DIFF('" + unit.lower() + "', CAST({a} AS TIMESTAMP), CAST({b} AS TIMESTAMP))",
                          a=start, b=end), 'BIGINT')

    def _datepart(self, node: exp.Extract, ctx: Context) -> exp.Expression:
        part = node.this.name.upper()
        value = unwrap(node.expression)
        if date_category(ctx, value) == 'string':
            value = cast_to(value, 'TIMESTAMP')
        if part == 'DAYOFWEEK':
            ctx.note('DATEPART(weekday) counts Sunday as 1, as in T-SQL with DATEFIRST 7')
            return typed(sunday_one_weekday(value), 'BIGINT')
        if part == 'WEEKISO':
            return typed(duck('EXTRACT(week FROM {d})', d=value), 'BIGINT')
        if part not in DATEPART_PARTS:
            raise self.refuse(f'Date part {part.lower()} in DATEPART is not in the supported T-SQL subset '
                              '(week numbers depend on DATEFIRST: use iso_week)')
        return typed(duck('EXTRACT(' + DATEPART_PARTS[part] + ' FROM {d})', d=value), 'BIGINT')

    def _datetrunc(self, node: exp.TimestampTrunc, ctx: Context) -> exp.Expression:
        unit = _unit(node)
        if unit not in TRUNC_PARTS:
            raise self.refuse(f'Date part {unit.lower()} in DATETRUNC is not in the supported T-SQL subset')
        value = unwrap(node.this)
        kind = date_category(ctx, value)
        truncated = duck("DATE_TRUNC('" + unit.lower() + "', {d})", d=cast_to(value, 'TIMESTAMP') if kind == 'string' else value)
        if kind == 'date':
            if unit in ('HOUR', 'MINUTE', 'SECOND'):
                raise self.refuse(f'DATETRUNC({unit.lower()}, ...) of a DATE is an error in T-SQL')
            return typed(cast_to(truncated, 'DATE'), 'DATE')
        if kind is None:
            raise self.refuse('DATETRUNC needs a date whose type is known here')
        return typed(truncated, 'TIMESTAMP')

    def _power(self, node: exp.Pow, ctx: Context) -> exp.Expression:
        kind = ctx.category(node.this)
        if kind == 'integer':
            ctx.note('POWER returns the type of its first argument, as in T-SQL (POWER(2, 0.5) = 1)')
            return typed(duck('CAST(TRUNC({p}) AS BIGINT)', p=node), 'BIGINT')
        if kind is None:
            raise self.refuse('POWER needs a first argument whose type is known here: T-SQL returns its type')
        return node


def unwrap_internal(node: exp.Expression) -> exp.Expression:
    """The argument of sqlglot's own CAST(x AS TEXT) around LEN's argument, once rewritten to CAST(x AS VARCHAR)."""
    if isinstance(node, exp.Cast) and node.to.this == exp.DataType.Type.VARCHAR and not node.to.expressions:
        return node.this
    return node
