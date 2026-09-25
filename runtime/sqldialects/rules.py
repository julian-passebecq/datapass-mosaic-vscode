"""Rewrite rules shared by several dialects. Each keeps the source engine's result where DuckDB's differs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import sqlglot
from sqlglot import exp

from .core import TARGET, Context, category, error_call, keep_type, nonzero_literal, zero_guard

INTEGER_TEXT = r'\s*[+-]?[0-9]+\s*'


def duck(template: str, **parts: exp.Expression) -> exp.Expression:
    """A DuckDB expression from a template; each {name} is the DuckDB SQL of an already rewritten sub-expression."""
    return sqlglot.parse_one(template.format(**{k: v.sql(dialect=TARGET) for k, v in parts.items()}), read=TARGET)


def typed(node: exp.Expression, type_name: str) -> exp.Expression:
    node.meta['dp_type'] = exp.DataType.build(type_name)
    return node


def unwrap(node: exp.Expression) -> exp.Expression:
    """The argument inside sqlglot's own conversion wrappers (TIME_STR_TO_TIME, TS_OR_DS_TO_DATE)."""
    while isinstance(node, (exp.TimeStrToTime, exp.TsOrDsToDate)) and not node.args.get('format'):
        node = node.this
    return node


def guard_division(node: exp.Expression, ctx: Context, message: str, engine: str) -> None:
    """The engines raise on a zero divisor where DuckDB returns NULL or infinity: guard it (in place)."""
    divisor = node.expression
    if not nonzero_literal(divisor):
        ctx.note(f'Division by zero raises an error, as in {engine}')
        node.set('expression', keep_type(divisor, zero_guard(divisor, message)))


def typed_division(node: exp.Div, ctx: Context, engine: str) -> exp.Expression:
    """T-SQL and PostgreSQL divide two integers as integers (7 / 2 = 3, -7 / 2 = -3)."""
    left, right = ctx.category(node.this), ctx.category(node.expression)
    if left == 'integer' and right == 'integer':
        ctx.note(f'Integer / integer is an integer division that truncates, as in {engine}')
        return typed(exp.IntDiv(this=node.this, expression=node.expression), 'BIGINT')
    if left is None or right is None:
        raise ctx.refuse(f'Division needs operands whose types are known here: {engine} divides two integers as '
                         'integers (7 / 2 = 3). Cast one side to DECIMAL (or INT) to say which you mean')
    return node


def standard_substring(node: exp.Substring, ctx: Context) -> exp.Expression:
    """SQL-standard SUBSTRING (T-SQL, PostgreSQL): a start below 1 counts the missing positions against the length;
    DuckDB reads a negative start from the end of the string."""
    start, length = node.args.get('start'), node.args.get('length')
    if start is None or (isinstance(start, exp.Literal) and start.is_number and int(float(start.this)) >= 0):
        return node
    if length is None:
        return duck('SUBSTRING({s}, GREATEST({p}, 1))', s=node.this, p=start)
    ctx.note('SUBSTRING with a start below 1 counts from before the string, as in the SQL standard')
    return duck('CASE WHEN {p} < 1 THEN SUBSTRING({s}, 1, GREATEST({p} + {n} - 1, 0)) ELSE SUBSTRING({s}, {p}, {n}) END',
                s=node.this, p=start, n=length)


def first_position_substring(node: exp.Substring, ctx: Context) -> exp.Expression:
    """BigQuery and Spark read position 0 as position 1; DuckDB's 0 is before the string."""
    start = node.args.get('start')
    if start is None or (isinstance(start, exp.Literal) and start.is_number and int(float(start.this)) != 0):
        return node
    ctx.note('SUBSTR position 0 is read as position 1')
    fixed = exp.Literal.number(1) if isinstance(start, exp.Literal) else duck('CASE WHEN {p} = 0 THEN 1 ELSE {p} END', p=start)
    node.set('start', fixed)
    return node


@dataclass(frozen=True)
class CastRules:
    """How one engine's CAST differs from DuckDB's; `types` maps a parsed type to the DuckDB type (or None: refused)."""
    engine: str
    types: Callable[[exp.DataType], exp.DataType | None]
    decimal_to_integer: str   # 'truncate' or 'plain' (DuckDB rounds half away from zero)
    float_to_integer: str     # 'truncate', 'round' (half away from zero) or 'plain' (DuckDB: half to even)
    string_to_integer_error: str
    string_rules: Callable[['exp.Expression', exp.DataType, exp.DataType, Context], exp.Expression] | None = None


def cast(node: exp.Expression, ctx: Context, rules: CastRules, target: exp.DataType | None = None) -> exp.Expression:
    """CAST / TRY_CAST with the engine's semantics. `target` overrides node.to (CONVERT)."""
    written = target if target is not None else node.to
    mapped = rules.types(written)
    if mapped is None:
        raise ctx.refuse_type(written)
    safe = isinstance(node, exp.TryCast) or bool(node.args.get('safe'))
    value = node.this
    source = ctx.category(value)
    wanted = category(mapped)
    if wanted == 'integer':
        if source == 'decimal' and rules.decimal_to_integer == 'truncate' or source == 'float' and rules.float_to_integer == 'truncate':
            ctx.note(f'CAST of a decimal or float to an integer type truncates, as in {rules.engine}')
            value = exp.Trunc(this=value)
        elif source == 'float' and rules.float_to_integer == 'round':
            ctx.note(f'CAST of a float to an integer type rounds half away from zero, as in {rules.engine}')
            value = exp.Round(this=value)
        elif source == 'string':
            # DuckDB rounds '2.5' to 3; the engines refuse a string that is not a whole number.
            ctx.note(f'CAST of a string to an integer type accepts whole numbers only, as in {rules.engine}')
            converted = (exp.TryCast if safe else exp.Cast)(this=exp.Trim(this=value.copy()), to=mapped)
            otherwise = exp.Null() if safe else error_call(rules.string_to_integer_error)
            return typed(exp.Case(ifs=[exp.If(this=exp.Not(this=exp.Anonymous(
                this='REGEXP_FULL_MATCH', expressions=[value, exp.Literal.string(INTEGER_TEXT)])), true=otherwise)],
                default=converted), mapped.sql(dialect=TARGET))
        elif source is None:
            raise ctx.refuse(f'CAST to {written.sql(dialect=ctx.dialect.read)} needs a value whose type is known here: '
                             f'{rules.engine} and DuckDB convert decimals and strings to integers differently. '
                             'Cast it to DECIMAL (or VARCHAR) first')
    elif wanted == 'string' and rules.string_rules is not None:
        return rules.string_rules(node, written, mapped, ctx)
    result = (exp.TryCast if safe else exp.Cast)(this=value, to=mapped)
    return keep_type(node, result, mapped)


def map_decimal(data_type: exp.DataType, default: tuple[int, int]) -> exp.DataType:
    """DECIMAL(p, s) as written; without parameters, the engine's default (DuckDB's own is DECIMAL(18, 3))."""
    params = [p.this for p in data_type.expressions if isinstance(p, exp.DataTypeParam)]
    values = [int(p.this) for p in params if isinstance(p, exp.Literal) and p.is_number]
    precision = min(values[0], 38) if values else default[0]
    scale = values[1] if len(values) > 1 else (0 if values else default[1])
    return exp.DataType.build(f'DECIMAL({precision}, {min(scale, precision)})')


def length_param(data_type: exp.DataType) -> int | str | None:
    """n of VARCHAR(n), 'max' for VARCHAR(MAX), None without a length."""
    for param in data_type.expressions:
        inner = param.this if isinstance(param, exp.DataTypeParam) else param
        if isinstance(inner, exp.Literal) and inner.is_number:
            return int(inner.this)
        if isinstance(inner, (exp.Var, exp.Identifier)) and inner.name.upper() == 'MAX':
            return 'max'
    return None


def interval(amount: exp.Expression, unit: str) -> exp.Expression:
    return exp.Interval(this=exp.Paren(this=amount) if not isinstance(amount, exp.Literal) else amount,
                        unit=exp.Var(this=unit))


def date_category(ctx: Context, node: exp.Expression) -> str | None:
    """'date', 'timestamp', 'string' (a literal or a text column) or None."""
    found = ctx.category(unwrap(node))
    return found if found in ('date', 'timestamp', 'string') else None


def cast_to(node: exp.Expression, type_name: str) -> exp.Expression:
    return exp.Cast(this=node, to=exp.DataType.build(type_name))


def sunday_week_diff(start: exp.Expression, end: exp.Expression) -> exp.Expression:
    """Week boundaries crossed, weeks starting on Sunday (T-SQL DATEDIFF(week), BigQuery DATE_DIFF(..., WEEK))."""
    return duck("DATE_DIFF('day', DATE_TRUNC('week', CAST({a} AS DATE) + 1), DATE_TRUNC('week', CAST({b} AS DATE) + 1)) // 7",
                a=start, b=end)


def sunday_one_weekday(value: exp.Expression) -> exp.Expression:
    """Day of the week with Sunday = 1 ... Saturday = 7 (T-SQL with DATEFIRST 7, BigQuery, Spark)."""
    return duck('(DAYOFWEEK({d}) + 1)', d=value)


def regexp_group(pattern: exp.Expression) -> int | None:
    """Capturing groups in a literal pattern (None when the pattern is not a literal)."""
    if isinstance(pattern, exp.RawString):
        text = pattern.this
    elif isinstance(pattern, exp.Literal) and pattern.is_string:
        text = pattern.this
    else:
        return None
    count, index = 0, 0
    while index < len(text):
        char = text[index]
        if char == '\\':
            index += 2
            continue
        if char == '(' and not text.startswith('(?', index):
            count += 1
        index += 1
    return count
