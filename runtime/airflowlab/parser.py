"""Whitelisted AST reader for Airflow DAG files. Nothing in the file is executed.

Supported: one DAG per file declared with `with DAG(...)`, `dag = DAG(...)` or
`@dag`; Empty/Bash/Python/Branch/ShortCircuit/SQL operators, File/Python
sensors and TaskFlow `@task` functions; dependencies with >>, <<, lists,
set_upstream/set_downstream, chain and cross_downstream; literal arguments,
datetimes, timedeltas, TriggerRule constants and cron/timetable schedules.
Anything else is rejected with a line number instead of being approximated.
Function bodies are never run: a branch callable's choice comes from the
simulation scenario, or from a single literal `return` when it has one.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .cron import Cron, CronError, utc
from .model import AirflowLabError, DagSpec, Schedule, TaskSpec, TRIGGER_RULES


@dataclass(frozen=True)
class _Builtin:
    name: str


DAG = _Builtin('DAG')
DAG_DECORATOR = _Builtin('dag')
TASK_DECORATOR = _Builtin('task')
CHAIN = _Builtin('chain')
CROSS_DOWNSTREAM = _Builtin('cross_downstream')
TRIGGER_RULE = _Builtin('TriggerRule')
CRON_TRIGGER = _Builtin('CronTriggerTimetable')
CRON_INTERVAL = _Builtin('CronDataIntervalTimetable')
DATETIME = _Builtin('datetime')
TIMEDELTA = _Builtin('timedelta')
TIMEZONE = _Builtin('timezone')
PENDULUM = _Builtin('pendulum')
PENDULUM_DATETIME = _Builtin('pendulum.datetime')
PENDULUM_DURATION = _Builtin('pendulum.duration')
DATETIME_MODULE = _Builtin('datetime module')
UTC = _Builtin('UTC')

# Operator class -> (task kind, templated fields)
OPERATORS: dict[str, tuple[str, tuple[str, ...]]] = {
    'EmptyOperator': ('task', ()),
    'BashOperator': ('task', ('bash_command', 'env')),
    'PythonOperator': ('task', ('op_args', 'op_kwargs', 'templates_dict')),
    'SQLExecuteQueryOperator': ('task', ('sql', 'parameters')),
    'BranchPythonOperator': ('branch', ('op_args', 'op_kwargs', 'templates_dict')),
    'ShortCircuitOperator': ('short_circuit', ('op_args', 'op_kwargs', 'templates_dict')),
    'FileSensor': ('sensor', ('filepath',)),
    'PythonSensor': ('sensor', ('op_args', 'op_kwargs', 'templates_dict')),
}
OPERATOR_ARGS: dict[str, set[str]] = {
    'EmptyOperator': set(),
    'BashOperator': {'bash_command', 'env', 'append_env', 'cwd', 'output_encoding', 'skip_on_exit_code'},
    'PythonOperator': {'python_callable', 'op_args', 'op_kwargs', 'templates_dict', 'show_return_value_in_logs'},
    'SQLExecuteQueryOperator': {'sql', 'conn_id', 'parameters', 'autocommit', 'split_statements', 'return_last', 'database'},
    'BranchPythonOperator': {'python_callable', 'op_args', 'op_kwargs', 'templates_dict'},
    'ShortCircuitOperator': {'python_callable', 'op_args', 'op_kwargs', 'templates_dict', 'ignore_downstream_trigger_rules'},
    'FileSensor': {'filepath', 'fs_conn_id', 'recursive'},
    'PythonSensor': {'python_callable', 'op_args', 'op_kwargs', 'templates_dict'},
}
REQUIRED_ARGS = {
    'BashOperator': 'bash_command', 'PythonOperator': 'python_callable', 'SQLExecuteQueryOperator': 'sql',
    'BranchPythonOperator': 'python_callable', 'ShortCircuitOperator': 'python_callable',
    'FileSensor': 'filepath', 'PythonSensor': 'python_callable',
}
SENSOR_ARGS = {'poke_interval', 'timeout', 'mode', 'soft_fail'}
# BaseOperator arguments the simulator models, or accepts as metadata with no effect on the outcome.
MODELED_ARGS = {'task_id', 'trigger_rule', 'retries', 'retry_delay', 'execution_timeout', 'depends_on_past',
                'ignore_first_depends_on_past'}
METADATA_ARGS = {'owner', 'email', 'email_on_failure', 'email_on_retry', 'pool', 'pool_slots', 'priority_weight',
                 'weight_rule', 'queue', 'doc', 'doc_md', 'max_active_tis_per_dag', 'do_xcom_push'}
UNSUPPORTED_ARGS = {
    'wait_for_downstream': 'wait_for_downstream (waiting for the direct downstream tasks of the previous run) is not '
                           'simulated; depends_on_past is',
    'retry_exponential_backoff': 'exponential backoff uses a jittered delay the simulator does not reproduce',
    'max_retry_delay': 'exponential backoff is not simulated',
    'exponential_backoff': 'exponential sensor backoff is not simulated',
    'sla': 'SLAs were removed in Airflow 3',
    'on_failure_callback': 'callbacks are Python code and are never executed',
    'on_success_callback': 'callbacks are Python code and are never executed',
    'on_retry_callback': 'callbacks are Python code and are never executed',
    'start_date': 'task-level start_date is not simulated; set start_date on the DAG',
    'end_date': 'task-level end_date is not simulated; set end_date on the DAG',
}
DAG_ARGS = {'dag_id', 'schedule', 'start_date', 'end_date', 'catchup', 'default_args'}
DAG_LEVEL_DEFAULTS = {'start_date', 'end_date'}
DAG_METADATA_ARGS = {'description', 'tags', 'doc_md', 'max_active_runs', 'max_active_tasks', 'dagrun_timeout',
                     'owner_links', 'params', 'is_paused_upon_creation', 'render_template_as_native_obj'}
DAG_REMOVED_ARGS = {
    'schedule_interval': 'schedule_interval was removed in Airflow 3; use schedule',
    'timetable': 'timetable= was removed in Airflow 3; pass the timetable to schedule',
    'concurrency': 'concurrency was removed; use max_active_tasks',
}
IMPORTS: dict[str, dict[str, Any]] = {
    'airflow': {'DAG': DAG},
    'airflow.sdk': {'DAG': DAG, 'dag': DAG_DECORATOR, 'task': TASK_DECORATOR, 'chain': CHAIN,
                    'cross_downstream': CROSS_DOWNSTREAM},
    'airflow.models': {'DAG': DAG},
    'airflow.models.dag': {'DAG': DAG},
    'airflow.decorators': {'dag': DAG_DECORATOR, 'task': TASK_DECORATOR},
    'airflow.models.baseoperator': {'chain': CHAIN, 'cross_downstream': CROSS_DOWNSTREAM},
    'airflow.utils.trigger_rule': {'TriggerRule': TRIGGER_RULE},
    'airflow.task.trigger_rule': {'TriggerRule': TRIGGER_RULE},
    'airflow.timetables.trigger': {'CronTriggerTimetable': CRON_TRIGGER},
    'airflow.timetables.interval': {'CronDataIntervalTimetable': CRON_INTERVAL},
    'datetime': {'datetime': DATETIME, 'timedelta': TIMEDELTA, 'timezone': TIMEZONE},
    'pendulum': {'datetime': PENDULUM_DATETIME, 'duration': PENDULUM_DURATION, 'UTC': UTC},
}
for _module, _names in (
    ('empty', ('EmptyOperator',)), ('bash', ('BashOperator',)),
    ('python', ('PythonOperator', 'BranchPythonOperator', 'ShortCircuitOperator')),
):
    for _prefix in ('airflow.operators', 'airflow.providers.standard.operators'):
        IMPORTS[f'{_prefix}.{_module}'] = {name: _Builtin('operator:' + name) for name in _names}
for _module, _names in (('filesystem', ('FileSensor',)), ('python', ('PythonSensor',))):
    for _prefix in ('airflow.sensors', 'airflow.providers.standard.sensors'):
        IMPORTS[f'{_prefix}.{_module}'] = {name: _Builtin('operator:' + name) for name in _names}
IMPORTS['airflow.providers.common.sql.operators.sql'] = {
    'SQLExecuteQueryOperator': _Builtin('operator:SQLExecuteQueryOperator')}


@dataclass(frozen=True)
class _TaskRef:
    task_id: str


@dataclass
class _Function:
    name: str
    static_return: list[str] | None


@dataclass
class _TaskFactory:
    name: str
    kind: str
    options: dict[str, Any]
    static_return: list[str] | None
    line: int


@dataclass
class _DagFactory:
    node: ast.FunctionDef
    options: dict[str, Any]


@dataclass
class _DagBuilder:
    dag_id: str
    options: dict[str, Any]
    line: int
    tasks: dict[str, TaskSpec] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)


def _static_return(node: ast.FunctionDef) -> list[str] | None:
    returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
    if len(returns) != 1 or returns[0].value is None:
        return None
    value = returns[0].value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return [value.value]
    if isinstance(value, (ast.List, ast.Tuple)) and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts):
        return [e.value for e in value.elts]
    return None


def _seconds(value: Any, what: str, line: int) -> float:
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    raise AirflowLabError(f"{what} must be a timedelta or a number of seconds", line)


class DagParser:
    def __init__(self) -> None:
        self.symbols: dict[str, Any] = {}
        self.current: _DagBuilder | None = None
        self.dags: list[_DagBuilder] = []

    # -- entry point -------------------------------------------------------------------------
    def parse(self, source: str) -> DagSpec:
        try:
            tree = ast.parse(source, mode='exec')
        except SyntaxError as exc:
            raise AirflowLabError(f"Python syntax error: {exc.msg}", exc.lineno) from exc
        for stmt in tree.body:
            self._stmt(stmt)
        if not self.dags:
            raise AirflowLabError("No DAG found: declare one with `with DAG(...)`, `DAG(...)` or `@dag`.")
        if len(self.dags) > 1:
            raise AirflowLabError("The simulator reads one DAG per file.", self.dags[1].line)
        return self._finish(self.dags[0])

    # -- statements ------------------------------------------------------------------------------
    def _stmt(self, node: ast.stmt) -> None:
        line = node.lineno
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if module == '__future__':
                return
            names = IMPORTS.get(module)
            if names is None:
                raise AirflowLabError(f"Unsupported import `from {module} import ...` in the Airflow Lab simulator", line)
            for alias in node.names:
                if alias.name not in names:
                    raise AirflowLabError(f"`{alias.name}` from {module} is not supported by the simulator", line)
                self.symbols[alias.asname or alias.name] = names[alias.name]
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'pendulum':
                    self.symbols[alias.asname or 'pendulum'] = PENDULUM
                elif alias.name == 'datetime':
                    self.symbols[alias.asname or 'datetime'] = DATETIME_MODULE
                else:
                    raise AirflowLabError(f"Unsupported import `import {alias.name}` in the Airflow Lab simulator", line)
            return
        if isinstance(node, ast.FunctionDef):
            self._function(node)
            return
        if isinstance(node, ast.With):
            self._with(node)
            return
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise AirflowLabError("Only simple `name = value` assignments are supported", line)
            self.symbols[node.targets[0].id] = self._eval(node.value)
            return
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return  # docstring
            self._eval(node.value)
            return
        if isinstance(node, ast.Pass):
            return
        if isinstance(node, ast.If) and self._is_main_guard(node.test):
            return  # `if __name__ == "__main__": dag.test()` is local tooling, not DAG structure
        if isinstance(node, (ast.For, ast.While, ast.ListComp)):
            raise AirflowLabError("Loops that generate tasks are not simulated; declare each task explicitly", line)
        raise AirflowLabError(f"Unsupported statement `{type(node).__name__}` in the Airflow Lab simulator", line)

    @staticmethod
    def _is_main_guard(test: ast.expr) -> bool:
        return (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == '__name__'
                and len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == '__main__')

    def _function(self, node: ast.FunctionDef) -> None:
        line = node.lineno
        if not node.decorator_list:
            self.symbols[node.name] = _Function(node.name, _static_return(node))
            return
        if len(node.decorator_list) != 1:
            raise AirflowLabError("Stacked decorators are not supported", line)
        decorator = node.decorator_list[0]
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        options = self._call_kwargs(decorator) if isinstance(decorator, ast.Call) else {}
        if isinstance(decorator, ast.Call) and decorator.args:
            raise AirflowLabError("Decorator arguments must be keywords", line)
        base = self._eval(target.value) if isinstance(target, ast.Attribute) else self._eval(target)
        variant = target.attr if isinstance(target, ast.Attribute) else None
        if base is DAG_DECORATOR and variant is None:
            self.symbols[node.name] = _DagFactory(node, options)
            return
        if base is TASK_DECORATOR:
            kinds = {None: 'task', 'branch': 'branch', 'short_circuit': 'short_circuit', 'sensor': 'sensor'}
            if variant not in kinds:
                raise AirflowLabError(f"@task.{variant} is not supported by the simulator", line)
            self.symbols[node.name] = _TaskFactory(node.name, kinds[variant], options, _static_return(node), line)
            return
        raise AirflowLabError("Only @dag and @task decorators are supported", line)

    def _with(self, node: ast.With) -> None:
        line = node.lineno
        if len(node.items) != 1:
            raise AirflowLabError("Use one DAG per `with` block", line)
        item = node.items[0]
        builder = self._eval(item.context_expr)
        if not isinstance(builder, _DagBuilder):
            raise AirflowLabError("`with` is only supported around a DAG", line)
        if item.optional_vars is not None:
            if not isinstance(item.optional_vars, ast.Name):
                raise AirflowLabError("Use `with DAG(...) as name:`", line)
            self.symbols[item.optional_vars.id] = builder
        self._in_dag(builder, node.body)

    def _in_dag(self, builder: _DagBuilder, body: list[ast.stmt]) -> None:
        if self.current is not None:
            raise AirflowLabError("Nested DAG contexts are not supported", body[0].lineno if body else None)
        self.current = builder
        try:
            for stmt in body:
                self._stmt(stmt)
        finally:
            self.current = None

    # -- expressions ----------------------------------------------------------------------------
    def _eval(self, node: ast.expr) -> Any:
        line = getattr(node, 'lineno', None)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in self.symbols:
                raise AirflowLabError(f"Unknown name `{node.id}`", line)
            return self.symbols[node.id]
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self._eval(e) for e in node.elts]
        if isinstance(node, ast.Dict):
            if any(k is None for k in node.keys):
                raise AirflowLabError("`**` unpacking in dict literals is not supported", line)
            return {self._eval(k): self._eval(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            value = self._eval(node.operand)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return -value
            raise AirflowLabError("Unary minus is only supported for numbers", line)
        if isinstance(node, ast.JoinedStr):
            raise AirflowLabError("f-strings are not evaluated; use a plain string with Jinja `{{ ... }}`", line)
        if isinstance(node, ast.Attribute):
            return self._attribute(self._eval(node.value), node.attr, line)
        if isinstance(node, ast.Subscript):
            base = self._eval(node.value)
            if isinstance(base, _TaskRef):
                return base  # XCom item of a TaskFlow result: same upstream task
            raise AirflowLabError("Subscripts are only supported on TaskFlow results", line)
        if isinstance(node, ast.BinOp):
            return self._binop(node)
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.DictComp)):
            raise AirflowLabError("Comprehensions that generate tasks are not simulated; declare each task explicitly", line)
        raise AirflowLabError(f"Unsupported expression `{type(node).__name__}`", line)

    def _attribute(self, base: Any, attr: str, line: int | None) -> Any:
        if base is TRIGGER_RULE:
            value = attr.lower()
            if value not in TRIGGER_RULES:
                raise AirflowLabError(f"TriggerRule.{attr} is not simulated", line)
            return value
        if base is PENDULUM:
            members = {'datetime': PENDULUM_DATETIME, 'duration': PENDULUM_DURATION, 'UTC': UTC}
            if attr not in members:
                raise AirflowLabError(f"pendulum.{attr} is not supported by the simulator", line)
            return members[attr]
        if base is DATETIME_MODULE:
            members = {'datetime': DATETIME, 'timedelta': TIMEDELTA, 'timezone': TIMEZONE}
            if attr not in members:
                raise AirflowLabError(f"datetime.{attr} is not supported by the simulator", line)
            return members[attr]
        if base is TIMEZONE and attr == 'utc':
            return UTC
        if base is DATETIME and attr in {'now', 'utcnow', 'today'}:
            raise AirflowLabError("A dynamic start_date such as datetime.now() moves every time the file is "
                                  "parsed; use a fixed date", line)
        if isinstance(base, _TaskRef) and attr in {'set_downstream', 'set_upstream'}:
            return ('method', attr, base)
        if isinstance(base, _TaskFactory) and attr == 'override':
            return ('override', base)
        raise AirflowLabError(f"Attribute `.{attr}` is not supported here", line)

    def _binop(self, node: ast.BinOp) -> Any:
        line = node.lineno
        left, right = self._eval(node.left), self._eval(node.right)
        if isinstance(node.op, (ast.RShift, ast.LShift)):
            if isinstance(left, list) and isinstance(right, list):
                raise AirflowLabError("A list cannot be linked to a list with >> or <<; use cross_downstream() "
                                      "(Python raises TypeError here)", line)
            upstream, downstream = (left, right) if isinstance(node.op, ast.RShift) else (right, left)
            self._link(upstream, downstream, line)
            return right
        numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (left, right))
        if isinstance(node.op, ast.Add) and isinstance(left, str) and isinstance(right, str):
            return left + right
        if numbers and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            return {ast.Add: left + right, ast.Sub: left - right, ast.Mult: left * right}[type(node.op)]
        if isinstance(node.op, (ast.Add, ast.Sub)) and isinstance(left, timedelta) and isinstance(right, timedelta):
            return left + right if isinstance(node.op, ast.Add) else left - right
        raise AirflowLabError("Unsupported operator; only >>, <<, string + and number arithmetic are read", line)

    def _call(self, node: ast.Call) -> Any:
        line = node.lineno
        func = self._eval(node.func)
        if isinstance(func, tuple) and func[0] == 'method':
            _, method, ref = func
            if node.keywords or len(node.args) != 1:
                raise AirflowLabError(f"{method}() takes one task or list", line)
            other = self._eval(node.args[0])
            if method == 'set_downstream':
                self._link(ref, other, line)
            else:
                self._link(other, ref, line)
            return None
        if isinstance(func, tuple) and func[0] == 'override':
            if node.args:
                raise AirflowLabError("override() arguments must be keywords", line)
            base: _TaskFactory = func[1]
            return replace(base, options={**base.options, **self._call_kwargs(node)})
        if func is DATETIME or func is PENDULUM_DATETIME:
            return self._datetime(node, pendulum=func is PENDULUM_DATETIME)
        if func is TIMEDELTA or func is PENDULUM_DURATION:
            return self._timedelta(node)
        if func is DAG:
            return self._dag(node, self._args(node), self._call_kwargs(node), None)
        if func in (CRON_TRIGGER, CRON_INTERVAL):
            return self._timetable(node, func)
        if func is CHAIN:
            self._chain([self._eval(a) for a in node.args], line)
            return None
        if func is CROSS_DOWNSTREAM:
            if len(node.args) != 2 or node.keywords:
                raise AirflowLabError("cross_downstream(from_tasks, to_tasks) takes two lists", line)
            sources, targets = (self._as_refs(self._eval(a), line) for a in node.args)
            for source in sources:
                for target in targets:
                    self._edge(source, target, line)
            return None
        if isinstance(func, _Builtin) and func.name.startswith('operator:'):
            return self._operator(func.name.split(':', 1)[1], node)
        if isinstance(func, _TaskFactory):
            return self._taskflow_call(func, node)
        if isinstance(func, _DagFactory):
            if node.args or node.keywords:
                raise AirflowLabError("@dag functions are called without arguments in the simulator", line)
            options = dict(func.options)
            builder = self._dag(node, [], options, func.node.name)
            self._in_dag(builder, func.node.body)
            return builder
        raise AirflowLabError("Unsupported call in the Airflow Lab simulator", line)

    def _args(self, node: ast.Call) -> list[Any]:
        if any(isinstance(a, ast.Starred) for a in node.args):
            raise AirflowLabError("`*args` unpacking is not supported", node.lineno)
        return [self._eval(a) for a in node.args]

    def _call_kwargs(self, node: ast.Call) -> dict[str, Any]:
        if any(k.arg is None for k in node.keywords):
            raise AirflowLabError("`**kwargs` unpacking is not supported; write the arguments explicitly", node.lineno)
        return {k.arg: self._eval(k.value) for k in node.keywords}

    # -- values -----------------------------------------------------------------------------------
    def _datetime(self, node: ast.Call, pendulum: bool) -> datetime:
        line = node.lineno
        args = self._args(node)
        kwargs = self._call_kwargs(node)
        tz = kwargs.pop('tz' if pendulum else 'tzinfo', UTC if pendulum else None)
        if tz not in (None, UTC, 'UTC', 'utc'):
            raise AirflowLabError("Only UTC is simulated; use tz=\"UTC\" / timezone.utc", line)
        allowed = {'year', 'month', 'day', 'hour', 'minute', 'second'}
        if set(kwargs) - allowed or not all(isinstance(v, int) and not isinstance(v, bool) for v in [*args, *kwargs.values()]):
            raise AirflowLabError("Datetimes take integer year, month, day, hour, minute, second", line)
        try:
            return datetime(*args, **kwargs, tzinfo=timezone.utc)
        except (TypeError, ValueError) as exc:
            raise AirflowLabError(f"Invalid datetime: {exc}", line) from exc

    def _timedelta(self, node: ast.Call) -> timedelta:
        line = node.lineno
        args, kwargs = self._args(node), self._call_kwargs(node)
        allowed = {'weeks', 'days', 'hours', 'minutes', 'seconds'}
        if len(args) > 1 or set(kwargs) - allowed or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in [*args, *kwargs.values()]):
            raise AirflowLabError("timedelta takes days (positional) or weeks/days/hours/minutes/seconds keywords", line)
        return timedelta(*args, **kwargs)

    def _timetable(self, node: ast.Call, kind: _Builtin) -> Schedule:
        line = node.lineno
        args, kwargs = self._args(node), self._call_kwargs(node)
        cron = args[0] if args else kwargs.pop('cron', None)
        if len(args) > 1:
            raise AirflowLabError(f"{kind.name}(cron, timezone=\"UTC\") takes one positional cron", line)
        tz = kwargs.pop('timezone', None)
        if tz not in ('UTC', 'utc', UTC):
            raise AirflowLabError(f"{kind.name} needs timezone=\"UTC\"; other timezones are not simulated", line)
        interval = kwargs.pop('interval', None)
        if interval not in (None, timedelta(0)):
            raise AirflowLabError("CronTriggerTimetable(interval=...) is not simulated; use CronDataIntervalTimetable "
                                  "for runs that cover a data interval", line)
        if kwargs:
            raise AirflowLabError(f"Unsupported {kind.name} argument(s): {', '.join(sorted(kwargs))}", line)
        self._cron(cron, line)
        return Schedule('cron_trigger' if kind is CRON_TRIGGER else 'cron_interval', cron,
                        f"{kind.name}({cron!r}, timezone='UTC')")

    @staticmethod
    def _cron(cron: Any, line: int | None) -> None:
        if not isinstance(cron, str):
            raise AirflowLabError("A cron schedule must be a string", line)
        try:
            Cron(cron)
        except CronError as exc:
            raise AirflowLabError(str(exc), line) from exc

    def _schedule(self, value: Any, line: int | None) -> Schedule:
        if value is None:
            return Schedule('none')
        if isinstance(value, Schedule):
            return value
        if isinstance(value, timedelta):
            raise AirflowLabError("timedelta schedules are not simulated; use a cron expression or a timetable", line)
        if isinstance(value, str):
            if value == '@once':
                return Schedule('once', None, "'@once'")
            if value == '@continuous':
                raise AirflowLabError("@continuous is not simulated", line)
            self._cron(value, line)
            return Schedule('cron_trigger', value, repr(value))
        raise AirflowLabError("schedule must be None, a cron string/preset or a supported timetable", line)

    # -- DAG and tasks -----------------------------------------------------------------------------
    def _dag(self, node: ast.Call, args: list[Any], kwargs: dict[str, Any], default_id: str | None) -> _DagBuilder:
        line = node.lineno
        for name, reason in DAG_REMOVED_ARGS.items():
            if name in kwargs:
                raise AirflowLabError(reason, line)
        unknown = set(kwargs) - DAG_ARGS - DAG_METADATA_ARGS
        if unknown:
            raise AirflowLabError(f"Unsupported DAG argument(s): {', '.join(sorted(unknown))}", line)
        if len(args) > 1:
            raise AirflowLabError("DAG() takes dag_id as its only positional argument", line)
        dag_id = args[0] if args else kwargs.get('dag_id', default_id)
        if not isinstance(dag_id, str) or not dag_id:
            raise AirflowLabError("DAG needs a dag_id string", line)
        default_args = kwargs.get('default_args') or {}
        if not isinstance(default_args, dict):
            raise AirflowLabError("default_args must be a dict literal", line)
        builder = _DagBuilder(dag_id, kwargs, line)
        self.dags.append(builder)
        return builder

    def _task_options(self, operator: str, kind: str, options: dict[str, Any], defaults: dict[str, Any],
                      line: int) -> dict[str, Any]:
        """Merge default_args under explicit arguments, as BaseOperator does, and validate both."""
        allowed = MODELED_ARGS | METADATA_ARGS | OPERATOR_ARGS.get(operator, set()) | (SENSOR_ARGS if kind == 'sensor' else set())
        for source, values in (('default_args', defaults), (operator, options)):
            for name in values:
                if source == 'default_args' and name in DAG_LEVEL_DEFAULTS:
                    continue  # read as the DAG's start/end date fallback, as Airflow does
                if name in UNSUPPORTED_ARGS:
                    raise AirflowLabError(f"{name}: {UNSUPPORTED_ARGS[name]}", line)
                if source == 'default_args':
                    if name not in MODELED_ARGS | METADATA_ARGS | SENSOR_ARGS or name == 'task_id':
                        raise AirflowLabError(f"default_args key `{name}` is not supported by the simulator", line)
                elif name not in allowed | {'dag'}:
                    raise AirflowLabError(f"{operator}: unsupported argument `{name}` in the simulator", line)
        merged = {k: v for k, v in defaults.items()
                  if k != 'task_id' and k not in DAG_LEVEL_DEFAULTS and (k not in SENSOR_ARGS or kind == 'sensor')}
        merged.update(options)
        return merged

    def _make_task(self, builder: _DagBuilder, task_id: Any, operator: str, kind: str, options: dict[str, Any],
                   line: int, static_branch: list[str] | None) -> _TaskRef:
        if not isinstance(task_id, str) or not task_id or len(task_id) > 250 or not all(
                c.isalnum() or c in '_.-' for c in task_id):
            raise AirflowLabError("task_id must be a string of letters, digits, _ . or -", line)
        if task_id in builder.tasks:
            raise AirflowLabError(f"Duplicate task_id `{task_id}` (Airflow raises DuplicateTaskIdFound)", line)
        spec = TaskSpec(task_id=task_id, operator=operator, kind=kind, line=line, static_branch=static_branch)
        rule = options.get('trigger_rule', 'all_success')
        if rule not in TRIGGER_RULES:
            raise AirflowLabError(f"trigger_rule {rule!r} is not simulated; supported: {', '.join(TRIGGER_RULES)}", line)
        spec.trigger_rule = rule
        retries = options.get('retries', 0)
        if not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= 100:
            raise AirflowLabError("retries must be an integer from 0 to 100", line)
        spec.retries = retries
        if 'retry_delay' in options:
            spec.retry_delay_s = _seconds(options['retry_delay'], 'retry_delay', line)
        if options.get('execution_timeout') is not None:
            spec.execution_timeout_s = _seconds(options['execution_timeout'], 'execution_timeout', line)
        for name in ('depends_on_past', 'ignore_first_depends_on_past'):
            if name in options and not isinstance(options[name], bool):
                raise AirflowLabError(f"{name} must be True or False", line)
        spec.depends_on_past = options.get('depends_on_past', False)
        if kind == 'sensor':
            if 'poke_interval' in options:
                spec.poke_interval_s = _seconds(options['poke_interval'], 'poke_interval', line)
            if 'timeout' in options:
                spec.timeout_s = _seconds(options['timeout'], 'timeout', line)
            mode = options.get('mode', 'poke')
            if mode not in ('poke', 'reschedule'):
                raise AirflowLabError("Sensor mode must be 'poke' or 'reschedule'", line)
            spec.mode = mode
            spec.soft_fail = bool(options.get('soft_fail', False))
            if spec.poke_interval_s <= 0:
                raise AirflowLabError("poke_interval must be positive", line)
        if kind == 'short_circuit':
            spec.ignore_downstream_trigger_rules = bool(options.get('ignore_downstream_trigger_rules', True))
        for name in OPERATORS.get(operator, ('task', ()))[1]:
            self._collect_templates(spec, name, options.get(name), line)
        builder.tasks[task_id] = spec
        return _TaskRef(task_id)

    @staticmethod
    def _collect_templates(spec: TaskSpec, name: str, value: Any, line: int) -> None:
        if value is None:
            return
        if isinstance(value, str):
            spec.templates[name] = value
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str):
                    spec.templates[f"{name}.{key}"] = item
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    spec.templates[f"{name}[{index}]"] = item
        elif not isinstance(value, (int, float, bool)):
            raise AirflowLabError(f"{name} must be a literal string, list or dict", line)

    def _builder_for(self, options: dict[str, Any], line: int) -> _DagBuilder:
        explicit = options.pop('dag', None)
        if explicit is not None:
            if not isinstance(explicit, _DagBuilder):
                raise AirflowLabError("dag= must name a DAG", line)
            return explicit
        if self.current is None:
            raise AirflowLabError("Tasks must be created inside a DAG (with DAG(...), @dag or dag=...)", line)
        return self.current

    def _operator(self, operator: str, node: ast.Call) -> _TaskRef:
        line = node.lineno
        if node.args:
            raise AirflowLabError(f"{operator} arguments must be keywords", line)
        options = self._call_kwargs(node)
        builder = self._builder_for(options, line)
        kind = OPERATORS[operator][0]
        if REQUIRED_ARGS.get(operator) and REQUIRED_ARGS[operator] not in options:
            raise AirflowLabError(f"{operator} needs {REQUIRED_ARGS[operator]}=", line)
        options = self._task_options(operator, kind, options, builder.options.get('default_args') or {}, line)
        static_branch = None
        callable_ = options.get('python_callable')
        if callable_ is not None:
            if not isinstance(callable_, _Function):
                raise AirflowLabError("python_callable must name a function defined in this file", line)
            static_branch = callable_.static_return
        return self._make_task(builder, options.get('task_id'), operator, kind, options, line, static_branch)

    def _taskflow_call(self, factory: _TaskFactory, node: ast.Call) -> _TaskRef:
        line = node.lineno
        if self.current is None:
            raise AirflowLabError("TaskFlow tasks must be called inside a DAG", line)
        builder = self.current
        upstream: list[_TaskRef] = []
        for value in [*self._args(node), *self._call_kwargs(node).values()]:
            for item in (value if isinstance(value, list) else [value]):
                if isinstance(item, _TaskRef):
                    upstream.append(item)
        options = dict(factory.options)
        base_id = options.pop('task_id', factory.name)
        task_id = base_id
        suffix = 0
        while task_id in builder.tasks:
            suffix += 1
            task_id = f"{base_id}__{suffix}"
        operator = {'task': '@task', 'branch': '@task.branch', 'short_circuit': '@task.short_circuit',
                    'sensor': '@task.sensor'}[factory.kind]
        taskflow_args = {'multiple_outputs'}
        options = {k: v for k, v in options.items() if k not in taskflow_args}
        options = self._task_options(operator, factory.kind, options, builder.options.get('default_args') or {}, line)
        ref = self._make_task(builder, task_id, operator, factory.kind, options, line, factory.static_return)
        for item in upstream:
            self._edge(item, ref, line)
        return ref

    # -- dependencies ------------------------------------------------------------------------------
    def _as_refs(self, value: Any, line: int | None) -> list[_TaskRef]:
        items = value if isinstance(value, list) else [value]
        if not items or not all(isinstance(item, _TaskRef) for item in items):
            raise AirflowLabError("Dependencies link tasks or lists of tasks", line)
        return items

    def _link(self, upstream: Any, downstream: Any, line: int | None) -> None:
        for source in self._as_refs(upstream, line):
            for target in self._as_refs(downstream, line):
                self._edge(source, target, line)

    def _chain(self, items: list[Any], line: int) -> None:
        for left, right in zip(items, items[1:]):
            if isinstance(left, list) and isinstance(right, list):
                if len(left) != len(right):
                    raise AirflowLabError("chain() needs adjacent lists of the same length", line)
                for source, target in zip(self._as_refs(left, line), self._as_refs(right, line)):
                    self._edge(source, target, line)
            else:
                self._link(left, right, line)

    def _edge(self, source: _TaskRef, target: _TaskRef, line: int | None) -> None:
        dags = [d for d in self.dags if source.task_id in d.tasks and target.task_id in d.tasks]
        if not dags:
            raise AirflowLabError("Both tasks of a dependency must belong to the same DAG", line)
        if source.task_id == target.task_id:
            raise AirflowLabError(f"`{source.task_id}` cannot depend on itself", line)
        edge = (source.task_id, target.task_id)
        if edge not in dags[0].edges:
            dags[0].edges.append(edge)

    # -- finish --------------------------------------------------------------------------------------
    def _finish(self, builder: _DagBuilder) -> DagSpec:
        options, line = builder.options, builder.line
        default_args = options.get('default_args') or {}
        start = options.get('start_date', default_args.get('start_date'))
        end = options.get('end_date', default_args.get('end_date'))
        for name, value in (('start_date', start), ('end_date', end)):
            if value is not None and not isinstance(value, datetime):
                raise AirflowLabError(f"{name} must be a datetime", line)
        schedule = self._schedule(options.get('schedule'), line)
        catchup = options.get('catchup', False)
        if not isinstance(catchup, bool):
            raise AirflowLabError("catchup must be True or False", line)
        if schedule.kind != 'none' and start is None:
            raise AirflowLabError("A scheduled DAG needs a start_date in the simulator", line)
        if not builder.tasks:
            raise AirflowLabError("The DAG has no tasks", line)
        order = self._topological(builder)
        tasks = {task_id: builder.tasks[task_id] for task_id in order}
        return DagSpec(builder.dag_id, schedule, utc(start) if start else None, utc(end) if end else None,
                       catchup, tasks, list(builder.edges), line)

    @staticmethod
    def _topological(builder: _DagBuilder) -> list[str]:
        remaining = list(builder.tasks)
        done: list[str] = []
        while remaining:
            ready = [t for t in remaining if all(a in done for a, b in builder.edges if b == t)]
            if not ready:
                raise AirflowLabError(f"The DAG has a dependency cycle through: {', '.join(remaining)}", builder.line)
            done.extend(ready)
            remaining = [t for t in remaining if t not in ready]
        return done


def parse_dag(source: str) -> DagSpec:
    if len(source) > 60_000:
        raise AirflowLabError("DAG files are limited to 60,000 characters in the simulator")
    return DagParser().parse(source)
