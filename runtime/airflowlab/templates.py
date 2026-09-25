"""Render `{{ ... }}` template fields for one DAG run. Never Jinja, never eval.

Expressions are read with Python's AST and a small whitelist: Airflow 3 context
variables (ds, ts, logical_date, data_interval_start/end, run_id, dag, task),
the ds/ts filters, macros.ds_add/ds_format and datetime.strftime. Datetimes
must be formatted with a filter or strftime: their default string form is not
simulated. Variables removed in Airflow 3 (execution_date, prev_ds, next_ds,
yesterday_ds, tomorrow_ds) are reported as removed.
"""
from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta
from typing import Any

from .model import AirflowLabError

_EXPRESSION = re.compile(r'\{\{(.*?)\}\}', re.S)
REMOVED = {'execution_date', 'next_execution_date', 'prev_execution_date', 'prev_ds', 'next_ds', 'prev_ds_nodash',
           'next_ds_nodash', 'yesterday_ds', 'yesterday_ds_nodash', 'tomorrow_ds', 'tomorrow_ds_nodash',
           'prev_execution_date_success'}
FILTERS = {
    'ds': lambda d: d.strftime('%Y-%m-%d'),
    'ds_nodash': lambda d: d.strftime('%Y%m%d'),
    'ts': lambda d: d.isoformat(),
    'ts_nodash': lambda d: d.strftime('%Y%m%dT%H%M%S'),
    'ts_nodash_with_tz': lambda d: d.isoformat().replace('-', '').replace(':', ''),
}


class _Named:
    def __init__(self, **attrs: str):
        self.attrs = attrs


class _Macros:
    pass


MACROS = _Macros()


def context(dag_id: str, task_id: str, logical_date: datetime, interval_start: datetime,
            interval_end: datetime, run_id: str) -> dict[str, Any]:
    ts = logical_date.isoformat()
    return {
        'ds': logical_date.strftime('%Y-%m-%d'),
        'ds_nodash': logical_date.strftime('%Y%m%d'),
        'ts': ts,
        'ts_nodash': logical_date.strftime('%Y%m%dT%H%M%S'),
        'ts_nodash_with_tz': ts.replace('-', '').replace(':', ''),
        'logical_date': logical_date,
        'data_interval_start': interval_start,
        'data_interval_end': interval_end,
        'run_id': run_id,
        'dag': _Named(dag_id=dag_id),
        'task': _Named(task_id=task_id),
        'macros': MACROS,
    }


def _ds_add(ds: Any, days: Any) -> str:
    if not isinstance(ds, str) or not isinstance(days, int) or isinstance(days, bool):
        raise AirflowLabError("macros.ds_add(ds, days) takes a YYYY-MM-DD string and an integer")
    return (datetime.strptime(ds, '%Y-%m-%d') + timedelta(days=days)).strftime('%Y-%m-%d')


def _ds_format(ds: Any, input_format: Any, output_format: Any) -> str:
    if not all(isinstance(v, str) for v in (ds, input_format, output_format)):
        raise AirflowLabError("macros.ds_format(ds, input_format, output_format) takes strings")
    return datetime.strptime(ds, input_format).strftime(output_format)


def _evaluate(node: ast.expr, ctx: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _evaluate(node.operand, ctx)
        if isinstance(value, int):
            return -value
    if isinstance(node, ast.Name):
        if node.id in REMOVED:
            raise AirflowLabError(f"`{node.id}` was removed from the template context in Airflow 3")
        if node.id not in ctx:
            raise AirflowLabError(f"Unknown template variable `{node.id}`; simulated: {', '.join(sorted(ctx))}")
        return ctx[node.id]
    if isinstance(node, ast.Attribute):
        base = _evaluate(node.value, ctx)
        if isinstance(base, _Named) and node.attr in base.attrs:
            return base.attrs[node.attr]
        if base is MACROS and node.attr in {'ds_add', 'ds_format'}:
            return _ds_add if node.attr == 'ds_add' else _ds_format
        if isinstance(base, datetime) and node.attr == 'strftime':
            return base.strftime
        raise AirflowLabError(f"Template attribute `.{node.attr}` is not simulated")
    if isinstance(node, ast.Call) and not node.keywords:
        function = _evaluate(node.func, ctx)
        if function in (_ds_add, _ds_format) or getattr(function, '__name__', '') == 'strftime':
            args = [_evaluate(arg, ctx) for arg in node.args]
            if getattr(function, '__name__', '') == 'strftime' and (len(args) != 1 or not isinstance(args[0], str)):
                raise AirflowLabError("strftime takes one format string")
            return function(*args)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        value = _evaluate(node.left, ctx)
        if isinstance(node.right, ast.Name) and node.right.id in FILTERS:
            if not isinstance(value, datetime):
                raise AirflowLabError(f"The `{node.right.id}` filter applies to a datetime")
            return FILTERS[node.right.id](value)
        raise AirflowLabError("Only the ds, ds_nodash, ts, ts_nodash and ts_nodash_with_tz filters are simulated")
    raise AirflowLabError("Unsupported template expression")


def render(text: str, ctx: dict[str, Any]) -> str:
    if '{%' in text or '{#' in text:
        raise AirflowLabError("Jinja statements and comments are not simulated; use {{ ... }} expressions")

    def replace(match: re.Match[str]) -> str:
        source = match.group(1).strip()
        try:
            tree = ast.parse(source, mode='eval')
        except SyntaxError as exc:
            raise AirflowLabError(f"Invalid template expression {{{{ {source} }}}}") from exc
        value = _evaluate(tree.body, ctx)
        if isinstance(value, datetime):
            raise AirflowLabError(f"Format `{source}` with a filter such as `| ds` or `| ts`, or with strftime")
        if not isinstance(value, (str, int)):
            raise AirflowLabError(f"`{source}` does not render to text")
        return str(value)

    return _EXPRESSION.sub(replace, text)
