"""The job run simulator: Databricks task orchestration on a logical clock.

Semantics (Azure Databricks Lakeflow Jobs):
- a task runs when its dependencies are done and its `run_if` holds: ALL_SUCCESS
  (default), AT_LEAST_ONE_SUCCESS, NONE_FAILED, ALL_DONE, AT_LEAST_ONE_FAILED,
  ALL_FAILED. When the condition is not met the task is `Upstream failed`, or
  `Excluded` for the conditions that handle failures;
- an `Excluded` dependency counts as successful; a task whose dependencies are all
  excluded is excluded (this is how the unmet branch of an If/else task is skipped);
- `Upstream failed` counts as failed downstream;
- retries (`max_retries`, `min_retry_interval_millis`, `retry_on_timeout`) and
  `timeout_seconds` per task;
- the job run is Succeeded when every task succeeded, Succeeded with failures when
  some failed but every leaf task (no downstream task) succeeded or was excluded,
  and Failed when a leaf task failed;
- job parameters are pushed down to notebook tasks as widgets and win over a task
  parameter with the same key; dynamic value references are resolved in parameters,
  condition operands and for-each inputs;
- task values set with dbutils.jobs.taskValues are readable by later tasks.

Notebook and SQL tasks really run through the Workspace (the local catalog, as the
job's `run_as` principal under Unity Catalog rules); everything else, the clock and
the compute, is simulated.
"""
from __future__ import annotations

import hashlib
import heapq
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .compute import (NODE_TYPES, ComputeCatalog, Usage, all_purpose_usage, job_cluster_usage, serverless_usage,
                      warehouse_usage)
from .model import CONDITION_OPS, DatabricksLabError, Job, Task, load_job, notebook_key, sql_key
from .refs import RESULT_STATES, TIME_ARGS, ReferenceError_, as_text, resolve, time_value
from .unity import LAB_USER

DEFAULT_DURATION = {'notebook': 120.0, 'sql': 30.0, 'condition': 0.0}
MAX_ITERATIONS = 100
STATE_LABELS = {'success': 'Succeeded', 'failed': 'Failed', 'excluded': 'Excluded',
                'upstream_failed': 'Upstream failed', 'timedout': 'Timed out'}
RESULT_LABELS = {'SUCCESS': 'Succeeded', 'SUCCESS_WITH_FAILURES': 'Succeeded with failures', 'FAILED': 'Failed'}
TRIGGERS = ('one_time', 'periodic', 'run_job_task', 'file_arrival', 'continuous', 'table', 'model')


class TaskBehavior(BaseModel):
    model_config = ConfigDict(extra='forbid')
    duration_seconds: float | None = Field(default=None, ge=0, le=86_400)
    fail_attempts: list[int] | Literal['all'] = Field(default_factory=list)
    error_message: str | None = Field(default=None, max_length=500)
    # Task values the task sets in a dry run, where notebooks do not run (dbutils.jobs.taskValues.set).
    values: dict[str, Any] = Field(default_factory=dict)


class JobScenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    now: datetime = datetime(2026, 3, 5, 6, 0, tzinfo=timezone.utc)
    job_parameters: dict[str, str] = Field(default_factory=dict)
    trigger_type: Literal['one_time', 'periodic', 'run_job_task', 'file_arrival', 'continuous', 'table', 'model'] = 'one_time'
    tasks: dict[str, TaskBehavior] = Field(default_factory=dict)
    cluster_states: dict[str, Literal['RUNNING', 'TERMINATED']] = Field(default_factory=dict)
    run_id: int | None = Field(default=None, ge=1)


class Workspace(Protocol):
    local: bool

    def run_notebook(self, key: str, parameters: dict[str, str], principal: str, task_values: Any,
                     context: dict[str, Any]) -> dict[str, Any]: ...
    def run_sql(self, key: str, parameters: dict[str, str], principal: str) -> dict[str, Any]: ...


@dataclass
class Attempt:
    number: int
    start_s: float
    end_s: float
    status: str  # success | failed | timedout
    error: str = ''


@dataclass
class TaskRun:
    key: str
    kind: str
    state: str = 'pending'
    start_s: float = 0.0
    end_s: float = 0.0
    attempts: list[Attempt] = field(default_factory=list)
    compute: str = ''
    parameters: dict[str, str] = field(default_factory=dict)
    outcome: str | None = None
    condition: dict[str, Any] | None = None
    exit_value: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    error: str = ''
    error_code: str = ''
    tables_written: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    iterations: list[dict[str, Any]] = field(default_factory=list)
    run_id: int = 0
    reason: str = ''

    def to_json(self) -> dict[str, Any]:
        return {'key': self.key, 'kind': self.kind, 'state': self.state,
                'state_label': STATE_LABELS.get(self.state, self.state), 'start_s': round(self.start_s, 1),
                'end_s': round(self.end_s, 1), 'duration_s': round(self.end_s - self.start_s, 1),
                'attempts': [{'number': a.number, 'start_s': round(a.start_s, 1), 'end_s': round(a.end_s, 1),
                              'status': a.status, 'error': a.error} for a in self.attempts],
                'compute': self.compute, 'parameters': self.parameters, 'outcome': self.outcome,
                'condition': self.condition, 'exit_value': self.exit_value, 'values': self.values, 'error': self.error,
                'error_code': self.error_code, 'tables_written': self.tables_written, 'notes': self.notes,
                'columns': self.columns, 'rows': self.rows[:20], 'iterations': self.iterations,
                'run_id': self.run_id, 'reason': self.reason}


class _TaskValues:
    """The dbutils.jobs.taskValues store of one task run."""

    def __init__(self, run: 'JobRun', task: TaskRun):
        self.run, self.task = run, task

    def set(self, key: str, value: Any) -> None:
        self.task.values[key] = value

    def get(self, task_key: str, key: str) -> tuple[bool, Any]:
        other = self.run.results.get(task_key)
        if other is None or other.state == 'pending' or other is self.task or key not in other.values:
            return False, None
        return True, other.values[key]


class JobRun:
    def __init__(self, job: Job, scenario: JobScenario, compute: ComputeCatalog, workspace: Workspace | None):
        self.job, self.scenario, self.compute, self.workspace = job, scenario, compute, workspace
        self.principal = job.run_as or LAB_USER
        self.job_id = int(hashlib.md5(job.name.encode()).hexdigest()[:8], 16) % 900_000_000 + 100_000_000
        seed = hashlib.md5(f"{job.name}:{scenario.now.isoformat()}".encode()).hexdigest()
        self.run_id = scenario.run_id or 10 ** 14 + int(seed[:12], 16) % (9 * 10 ** 14)
        self.results: dict[str, TaskRun] = {}
        self.usages: dict[str, Usage] = {}
        self.notes: list[str] = []
        self.parameters: dict[str, str] = {}
        self.order = {t.key: i for i, t in enumerate(job.tasks)}

    # -- references ---------------------------------------------------------------------------------
    def lookup(self, path: list[str], task: Task | None, item: Any = None) -> Any:
        head, rest = path[0], path[1:]
        text = '{{' + '.'.join(path) + '}}'
        try:
            if head == 'job':
                if rest == ['id']:
                    return str(self.job_id)
                if rest == ['name']:
                    return self.job.name
                if rest == ['run_id']:
                    return str(self.run_id)
                if rest == ['repair_count']:
                    return '0'
                if len(rest) == 2 and rest[0] in ('start_time',) and rest[1] in TIME_ARGS:
                    return time_value(self.scenario.now, rest[1])
                if len(rest) == 3 and rest[:2] == ['trigger', 'time'] and rest[2] in TIME_ARGS:
                    return time_value(self.scenario.now.replace(second=0, microsecond=0), rest[2])
                if rest == ['trigger', 'type']:
                    return self.scenario.trigger_type
                if len(rest) == 2 and rest[0] == 'parameters':
                    if rest[1] not in self.parameters:
                        raise ReferenceError_(f"the job has no parameter '{rest[1]}'")
                    return self.parameters[rest[1]]
            elif head == 'task' and task is not None:
                result = self.results.get(task.key)
                if rest == ['name']:
                    return task.key
                if rest == ['run_id']:
                    return str(result.run_id if result else 0)
                if rest == ['execution_count']:
                    return str(len(result.attempts) + 1 if result else 1)
                if rest == ['notebook_path'] and task.kind == 'notebook':
                    return task.notebook_path
            elif head == 'tasks' and len(rest) >= 2:
                other = self.results.get(rest[0])
                if rest[0] not in self.order:
                    raise ReferenceError_(f"there is no task '{rest[0]}' in this job")
                if other is None or other.state == 'pending':
                    raise ReferenceError_(f"task '{rest[0]}' has not run yet in this run (make it an upstream "
                                          "dependency)")
                field_ = rest[1]
                if rest[1:] == ['result_state']:
                    return other.state
                if rest[1:] == ['error_code']:
                    return other.error_code
                if rest[1:] == ['run_id']:
                    return str(other.run_id)
                if rest[1:] == ['execution_count']:
                    return str(len(other.attempts))
                if rest[1:] == ['notebook_path']:
                    return self.job.task(rest[0]).notebook_path
                if field_ == 'values' and len(rest) == 3:
                    if rest[2] not in other.values:
                        raise ReferenceError_(f"task '{rest[0]}' did not set the task value '{rest[2]}'")
                    return other.values[rest[2]]
                if field_ == 'output' and other.kind == 'sql':
                    if rest[2:] == ['rows']:
                        return other.rows
                    if rest[2:3] == ['first_row']:
                        if not other.rows:
                            raise ReferenceError_(f"SQL task '{rest[0]}' returned no rows")
                        if len(rest) == 3:
                            return other.rows[0]
                        if len(rest) == 4 and rest[3] in other.rows[0]:
                            return other.rows[0][rest[3]]
            elif head == 'workspace':
                if rest == ['id']:
                    return '1234567890123456'
                if rest == ['url']:
                    return 'https://adb-1234567890123456.7.azuredatabricks.net'
            elif head == 'input':
                if item is None:
                    raise ReferenceError_('{{input}} is only available in the task nested in a for_each_task')
                if not rest:
                    return item
                if isinstance(item, dict) and len(rest) == 1 and rest[0] in item:
                    return item[rest[0]]
            elif head == 'backfill':
                raise ReferenceError_('backfill runs are not simulated')
        except ReferenceError_ as exc:
            raise ReferenceError_(f"Invalid dynamic value reference {text}: {exc}") from None
        raise ReferenceError_(f"Invalid dynamic value reference {text}")

    def resolve(self, text: str, task: Task | None, item: Any = None) -> str:
        return resolve(text, lambda path: self.lookup(path, task, item))

    # -- run ----------------------------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        self._parameters()
        pending = {t.key: t for t in self.job.tasks}
        ready: list[tuple[float, int, str]] = []
        for task in self.job.tasks:
            self.results[task.key] = TaskRun(task.key, task.kind)
            self.results[task.key].run_id = self.run_id + 1 + self.order[task.key]
            if not task.depends_on:
                heapq.heappush(ready, (0.0, self.order[task.key], task.key))
        queued = {key for _, _, key in ready}
        while ready:
            at, _, key = heapq.heappop(ready)
            task = pending.pop(key)
            self._run_task(task, at)
            for other in self.job.tasks:
                if other.key in pending and other.key not in queued and all(
                        self.results[d].state != 'pending' for d, _ in other.depends_on):
                    start = max(self.results[d].end_s for d, _ in other.depends_on)
                    heapq.heappush(ready, (start, self.order[other.key], other.key))
                    queued.add(other.key)
        return self._summary()

    def _parameters(self) -> None:
        for name, default in self.job.parameters.items():
            self.parameters[name] = self.resolve(default, None)
        for name, value in self.scenario.job_parameters.items():
            if name not in self.job.parameters:
                self.notes.append(f"Job parameter '{name}' is not defined by the job; this run adds it")
            self.parameters[name] = value

    def _gate(self, task: Task) -> tuple[str | None, str]:
        """None when the task runs, else the state it gets without running, and why."""
        if not task.depends_on:
            return None, ''
        effective = []
        for dep, outcome in task.depends_on:
            result = self.results[dep]
            if outcome is not None and result.state == 'success' and result.outcome != outcome:
                effective.append('excluded')
            else:
                effective.append(result.state)
        if all(s == 'excluded' for s in effective):
            return 'excluded', 'all its dependencies were excluded'
        succeeded = [s in ('success', 'excluded') for s in effective]
        failed = [s in ('failed', 'timedout', 'upstream_failed') for s in effective]
        rule = task.run_if
        met = {'ALL_SUCCESS': all(succeeded), 'AT_LEAST_ONE_SUCCESS': any(succeeded),
               'NONE_FAILED': not any(failed), 'ALL_DONE': True,
               'AT_LEAST_ONE_FAILED': any(failed), 'ALL_FAILED': all(failed)}[rule]
        if met:
            return None, ''
        state = 'excluded' if rule in ('AT_LEAST_ONE_FAILED', 'ALL_FAILED') else 'upstream_failed'
        detail = ', '.join(f"{d} {STATE_LABELS.get(s, s).lower()}" for (d, _), s in zip(task.depends_on, effective))
        return state, f"run_if {rule} not met ({detail})"

    def _run_task(self, task: Task, at: float) -> None:
        result = self.results[task.key]
        state, reason = self._gate(task)
        result.start_s = result.end_s = at
        if state:
            result.state, result.reason = state, reason
            return
        behavior = self.scenario.tasks.get(task.key, TaskBehavior())
        if task.kind == 'condition':
            self._condition(task, result, at)
        elif task.kind == 'for_each':
            self._for_each(task, result, at, behavior)
        else:
            self._attempts(task, result, at, behavior, None)

    # -- one task with its attempts --------------------------------------------------------------------
    def _usage(self, task: Task, at: float) -> Usage | None:
        kind, key = task.compute
        if kind == 'none':
            return None
        usage_key = f"{kind}:{key}"
        usage = self.usages.get(usage_key)
        if usage is None:
            if kind == 'job_cluster':
                usage = job_cluster_usage(self.job.clusters[key], at)
            elif kind == 'existing':
                cluster = self.compute.clusters[key]
                state = self.scenario.cluster_states.get(key)
                if state is not None:
                    cluster.running = state == 'RUNNING'
                usage = all_purpose_usage(cluster, at)
            elif kind == 'warehouse':
                usage = warehouse_usage(self.compute.warehouses[key], at)
            else:
                usage = serverless_usage(key, at)
            self.usages[usage_key] = usage
        return usage

    def _attempts(self, task: Task, result: TaskRun, at: float, behavior: TaskBehavior, item: Any,
                  record: TaskRun | None = None) -> None:
        record = record or result
        usage = self._usage(task, at)
        start = max(at, usage.ready_s) if usage else at
        if usage and task.key not in usage.tasks:
            usage.tasks.append(task.key)
        record.compute = usage.label if usage else ''
        record.start_s = start
        try:
            record.parameters = self._task_parameters(task, item, record)
        except ReferenceError_ as exc:
            record.state, record.error, record.error_code = 'failed', str(exc), 'InvalidParameterValue'
            record.end_s = start
            record.attempts.append(Attempt(1, start, start, 'failed', str(exc)))
            return
        duration = behavior.duration_seconds if behavior.duration_seconds is not None else DEFAULT_DURATION[task.kind]
        attempt, clock = 0, start
        while True:
            attempt += 1
            planned_fail = behavior.fail_attempts == 'all' or attempt in behavior.fail_attempts
            timed_out = bool(task.timeout_seconds) and duration > task.timeout_seconds
            if planned_fail:
                end = clock + (min(duration, task.timeout_seconds) if timed_out else duration)
                status, error, code = 'failed', behavior.error_message or 'Task failed (scenario)', 'RunExecutionError'
            elif timed_out:
                end = clock + task.timeout_seconds
                status, error, code = 'timedout', (f"Timed out after {task.timeout_seconds} s (timeout_seconds); the "
                                                   "run was cut before it finished, so its writes are not applied"), ''
            else:
                end = clock + duration
                status, error, code = self._execute(task, record, item, behavior)
            record.attempts.append(Attempt(attempt, clock, end, status, error))
            if usage:
                usage.end_s = max(usage.end_s, end)
                usage.busy_s += end - clock
            clock = end
            retry = status != 'success' and attempt <= task.max_retries and (
                status != 'timedout' or task.retry_on_timeout)
            if not retry:
                break
            clock += task.min_retry_interval_s
        record.end_s = clock
        record.state = 'success' if status == 'success' else status
        record.error, record.error_code = (error, code) if status != 'success' else ('', '')
        if task.max_retries and len(record.attempts) > 1:
            record.notes.append(f"{len(record.attempts)} attempts (max_retries {task.max_retries})")

    def _task_parameters(self, task: Task, item: Any, record: TaskRun) -> dict[str, str]:
        if task.kind == 'notebook':
            params = {k: self.resolve(v, task, item) for k, v in task.base_parameters.items()}
            overridden = [k for k in params if k in self.parameters]
            params.update(self.parameters)  # job parameters are pushed down and win over task parameters
            if overridden:
                record.notes.append(
                    f"Job parameter{'s' if len(overridden) > 1 else ''} {', '.join(overridden)} "
                    f"override{'' if len(overridden) > 1 else 's'} the task parameter with the same key")
            return params
        if task.kind == 'sql':
            return {k: self.resolve(v, task, item) for k, v in task.sql_parameters.items()}
        return {}

    def _execute(self, task: Task, record: TaskRun, item: Any, behavior: TaskBehavior) -> tuple[str, str, str]:
        if self.workspace is None or not self.workspace.local:
            record.notes.append('Dry run: the task is simulated, nothing ran on the catalog')
            if behavior.values:
                record.values.update(behavior.values)
                record.notes.append(f"Task values from the run settings: {', '.join(sorted(behavior.values))}")
            return 'success', '', ''
        if task.kind == 'notebook':
            context = {'job': self.job.name, 'task': task.key, 'job_run_id': self.run_id,
                       'notebook': task.notebook_path}
            outcome = self.workspace.run_notebook(notebook_key(task.notebook_path), record.parameters,
                                                  self.principal, _TaskValues(self, record), context)
            record.exit_value = outcome.get('exit_value')
        else:
            outcome = self.workspace.run_sql(sql_key(task.sql_path), record.parameters, self.principal)
            record.columns = outcome.get('columns', [])
            record.rows = outcome.get('rows', [])
        for table in outcome.get('tables_written', []):
            if table not in record.tables_written:
                record.tables_written.append(table)
        for note in outcome.get('notes', []):
            if note not in record.notes:
                record.notes.append(note)
        if outcome.get('status') == 'success':
            return 'success', '', ''
        return 'failed', str(outcome.get('error', 'Task failed')), str(outcome.get('error_code') or 'RunExecutionError')

    # -- control-flow tasks -------------------------------------------------------------------------------
    def _condition(self, task: Task, result: TaskRun, at: float) -> None:
        op, left_raw, right_raw = task.condition
        result.start_s = result.end_s = at
        try:
            left, right = self.resolve(left_raw, task), self.resolve(right_raw, task)
        except ReferenceError_ as exc:
            result.state, result.error, result.error_code = 'failed', str(exc), 'InvalidParameterValue'
            result.attempts.append(Attempt(1, at, at, 'failed', str(exc)))
            return
        symbol = CONDITION_OPS[op]
        if symbol in ('==', '!='):
            value = (left == right) == (symbol == '==')  # == and != compare the operands as strings
        else:
            try:
                a, b = float(left), float(right)
            except ValueError:
                message = (f"{op} compares numbers: '{left}' {symbol} '{right}' cannot be evaluated")
                result.state, result.error, result.error_code = 'failed', message, 'RunExecutionError'
                result.attempts.append(Attempt(1, at, at, 'failed', message))
                return
            value = {'>': a > b, '>=': a >= b, '<': a < b, '<=': a <= b}[symbol]
        result.outcome = 'true' if value else 'false'
        result.condition = {'left': left, 'op': symbol, 'right': right, 'left_expression': left_raw,
                            'right_expression': right_raw, 'result': value}
        result.state = 'success'
        result.attempts.append(Attempt(1, at, at, 'success'))

    def _for_each(self, task: Task, result: TaskRun, at: float, behavior: TaskBehavior) -> None:
        result.start_s = result.end_s = at
        try:
            raw = self.resolve(task.inputs, task)
            items = json.loads(raw)
            if not isinstance(items, list):
                raise ValueError
        except ReferenceError_ as exc:
            result.state, result.error, result.error_code = 'failed', str(exc), 'InvalidParameterValue'
            return
        except ValueError:
            result.state, result.error = 'failed', f"for_each_task inputs must be a JSON array, got {task.inputs!r}"
            result.error_code = 'InvalidParameterValue'
            return
        if len(items) > MAX_ITERATIONS:
            result.state, result.error = 'failed', f"The lab runs at most {MAX_ITERATIONS} iterations"
            return
        inner = task.inner
        slots = [at] * task.concurrency
        failed = False
        for index, item in enumerate(items):
            slot = min(range(len(slots)), key=lambda s: (slots[s], s))
            record = TaskRun(f"{inner.key}[{index}]", inner.kind)
            inner_behavior = self.scenario.tasks.get(f"{task.key}[{index}]", behavior)
            self._attempts(inner, result, slots[slot], inner_behavior, item, record)
            slots[slot] = record.end_s
            failed = failed or record.state != 'success'
            result.iterations.append({**record.to_json(), 'input': item})
            for table in record.tables_written:
                if table not in result.tables_written:
                    result.tables_written.append(table)
        result.end_s = max([at] + [i['end_s'] for i in result.iterations])
        result.state = 'failed' if failed else 'success'
        if failed:
            result.error = 'At least one iteration failed'
            result.error_code = 'RunExecutionError'
        result.notes.append(f"{len(items)} iteration(s), concurrency {task.concurrency}")

    # -- the run ------------------------------------------------------------------------------------------
    def _summary(self) -> dict[str, Any]:
        tasks = [self.results[t.key] for t in self.job.tasks]
        leaves = [t.key for t in self.job.tasks if not self.job.downstream(t.key)]
        leaf_failed = [k for k in leaves if self.results[k].state in ('failed', 'timedout', 'upstream_failed')]
        any_failed = [t.key for t in tasks if t.state in ('failed', 'timedout', 'upstream_failed')]
        state = 'FAILED' if leaf_failed else 'SUCCESS_WITH_FAILURES' if any_failed else 'SUCCESS'
        end = max([t.end_s for t in tasks] + [0.0])
        usages = [u.to_json() for u in self.usages.values()]
        explanation = {
            'SUCCESS': 'Succeeded: every task succeeded (excluded tasks count as successful).',
            'SUCCESS_WITH_FAILURES': (f"Succeeded with failures: {', '.join(any_failed)} failed, but every leaf task "
                                      f"({', '.join(leaves)}) succeeded or was excluded."),
            'FAILED': (f"Failed: the leaf task{'s' if len(leaf_failed) > 1 else ''} {', '.join(leaf_failed)} "
                       "did not succeed. Databricks decides the run status from the leaf tasks (tasks with no "
                       "downstream task)."),
        }[state]
        return {
            'run_id': self.run_id, 'job_id': self.job_id, 'result_state': state, 'status_label': RESULT_LABELS[state],
            'explanation': explanation, 'leaves': leaves, 'duration_s': round(end, 1), 'principal': self.principal,
            'start_time': self.scenario.now.isoformat(), 'trigger_type': self.scenario.trigger_type,
            'parameters': self.parameters, 'tasks': [t.to_json() for t in tasks], 'compute': usages,
            'cost': {'dbu': round(sum(u['dbu'] for u in usages), 4), 'cost': round(sum(u['cost'] for u in usages), 4),
                     'idle_dbu': round(sum(u['idle_dbu'] for u in usages), 4),
                     'idle_cost': round(sum(u['idle_cost'] for u in usages), 4)},
            'notes': self.notes,
        }


def simulate_job(document: Any, compute: ComputeCatalog, scenario: JobScenario,
                 workspace: Workspace | None) -> tuple[Job, dict[str, Any]]:
    job = load_job(document, set(compute.clusters), set(compute.warehouses), set(NODE_TYPES))
    return job, JobRun(job, scenario, compute, workspace).run()


def design(job: Job) -> dict[str, Any]:
    """The job as the canvas shows it."""
    def task_view(task: Task) -> dict[str, Any]:
        detail = {'notebook': task.notebook_path, 'sql': task.sql_path,
                  'condition': f"{task.condition[1]} {CONDITION_OPS.get(task.condition[0], '?')} {task.condition[2]}",
                  'for_each': f"for each in {task.inputs}"}[task.kind]
        return {'key': task.key, 'kind': task.kind, 'detail': detail, 'run_if': task.run_if,
                'depends_on': [{'task_key': d, 'outcome': o} for d, o in task.depends_on],
                'compute': f"{task.compute[0]}:{task.compute[1]}" if task.compute[0] != 'none' else '',
                'max_retries': task.max_retries, 'timeout_seconds': task.timeout_seconds,
                'parameters': task.base_parameters or task.sql_parameters, 'description': task.description,
                'inner': task_view(task.inner) if task.inner else None}
    return {'name': job.name, 'parameters': job.parameters, 'run_as': job.run_as,
            'schedule': job.schedule, 'tags': job.tags, 'warnings': job.warnings,
            'clusters': [{'key': c.key, 'label': c.label(), 'spark_version': c.spark_version} for c in job.clusters.values()],
            'tasks': [task_view(t) for t in job.tasks]}


__all__ = ['DatabricksLabError', 'JobScenario', 'TaskBehavior', 'simulate_job', 'design', 'RESULT_STATES']
