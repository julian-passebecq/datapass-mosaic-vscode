"""Deterministic task-instance simulation of Airflow DAG runs.

Each run is simulated in logical seconds after its start, with unlimited worker
slots. Runs are independent except through depends_on_past: runs are simulated
in logical-date order, and a depends_on_past task runs only when the same task
succeeded or was skipped in the previous run (PrevDagrunDep: with catchup the
previous scheduled run, otherwise the previous run of any type; the first run
has no previous one). Otherwise it keeps no state, like everything that waits on
it, and its run stays running. Waiting times across runs are not modelled. Task behavior (duration,
failing attempts, sensor arrival, branch choice, short-circuit condition) comes
from the scenario; no task code runs.

Trigger rules follow Airflow's TriggerRuleDep: some rules settle a task as
skipped or upstream_failed as soon as one upstream state decides it (all_success
with a failed upstream), others wait for every upstream task. Retries re-run a
failed attempt after retry_delay while try_number <= retries; execution_timeout
fails an attempt (retryable). A sensor pokes every poke_interval; after a false
poke past `timeout` it fails without retrying, or is skipped with soft_fail.
A branch skips its direct downstream tasks that it did not choose; a false
short-circuit skips all downstream tasks (or only direct ones when
ignore_downstream_trigger_rules=False). The DAG run fails when a leaf task
failed or is upstream_failed, and succeeds otherwise.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .cron import utc
from .model import AirflowLabError, DagSpec, TaskSpec
from .schedule import RunPlan, manual_run, plan_runs
from .templates import context, render

TERMINAL = {'success', 'failed', 'skipped', 'upstream_failed'}


class TaskBehavior(BaseModel):
    model_config = ConfigDict(extra='forbid')
    duration_seconds: float = Field(default=60, ge=0, le=7 * 86400)
    # try_numbers whose attempt fails, or 'all'
    fail_attempts: list[int] | Literal['all'] = Field(default_factory=list)
    # seconds after the sensor starts when its condition becomes true; None: never
    sensor_true_after_seconds: float | None = Field(default=None, ge=0)
    branch: list[str] | None = None
    condition: bool | None = None


class Scenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    now: datetime
    unpaused_at: datetime | None = None
    tasks: dict[str, TaskBehavior] = Field(default_factory=dict)
    # ISO logical date -> task behavior overrides for that run only
    by_logical_date: dict[str, dict[str, TaskBehavior]] = Field(default_factory=dict)
    # Manually triggered runs (logical date = trigger time), added to the scheduled ones.
    manual_runs: list[datetime] = Field(default_factory=list, max_length=20)
    latest_run_only: bool = False
    outcome: Literal['runs', 'task_instances', 'rendered', 'edges', 'tasks'] = 'task_instances'
    columns: list[str] | None = None


@dataclass
class TaskInstance:
    task_id: str
    state: str | None = None
    try_number: int = 0
    start_s: float | None = None
    end_s: float | None = None
    log: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    plan: RunPlan
    state: str
    instances: dict[str, TaskInstance]
    events: list[dict[str, Any]]


def _new_state(rule: str, counts: dict[str, int], upstream: int) -> str | None:
    success, skipped, failed, upstream_failed = (counts['success'], counts['skipped'], counts['failed'],
                                                 counts['upstream_failed'])
    done = success + skipped + failed + upstream_failed
    upstream_done = done == upstream
    if rule == 'all_success':
        if failed or upstream_failed:
            return 'upstream_failed'
        if skipped:
            return 'skipped'
    elif rule == 'all_failed':
        if success or skipped:
            return 'skipped'
    elif rule == 'one_success':
        if upstream_done and done == skipped:
            return 'skipped'
        if upstream_done and success <= 0:
            return 'upstream_failed'
    elif rule == 'one_failed':
        if upstream_done and not (failed or upstream_failed):
            return 'skipped'
    elif rule == 'one_done':
        if upstream_done and not (failed or success):
            return 'skipped'
    elif rule == 'none_failed':
        if failed or upstream_failed:
            return 'upstream_failed'
    elif rule == 'none_failed_min_one_success':
        if failed or upstream_failed:
            return 'upstream_failed'
        if skipped == upstream:
            return 'skipped'
    elif rule == 'none_skipped':
        if skipped:
            return 'skipped'
    elif rule == 'all_skipped':
        if success or failed or upstream_failed:
            return 'skipped'
    return None


def _can_run(rule: str, counts: dict[str, int], upstream: int) -> bool:
    success, skipped, failed, upstream_failed = (counts['success'], counts['skipped'], counts['failed'],
                                                 counts['upstream_failed'])
    done = success + skipped + failed + upstream_failed
    if rule == 'always':
        return True
    if rule == 'one_success':
        return success > 0
    if rule == 'one_failed':
        return failed + upstream_failed > 0
    if rule == 'one_done':
        return success + failed > 0
    if rule == 'all_success':
        return success == upstream
    if rule == 'all_failed':
        return failed + upstream_failed == upstream
    if rule == 'all_done':
        return done == upstream
    if rule in ('none_failed', 'none_failed_min_one_success'):
        return success + skipped == upstream
    if rule == 'none_skipped':
        return done == upstream and skipped == 0
    if rule == 'all_skipped':
        return skipped == upstream
    raise AirflowLabError(f"Unknown trigger rule {rule}")


class _RunSimulator:
    def __init__(self, dag: DagSpec, plan: RunPlan, behaviors: dict[str, TaskBehavior],
                 previous: 'RunResult | None' = None):
        self.dag = dag
        self.plan = plan
        self.behaviors = behaviors
        self.previous = previous
        # depends_on_past tasks held back by the previous run's state (logged once each).
        self.blocked: set[str] = set()
        self.tis = {task_id: TaskInstance(task_id) for task_id in dag.tasks}
        self.events: list[dict[str, Any]] = []
        self.queue: list[tuple[float, int, str, str]] = []
        self.sequence = 0

    def _log(self, time_s: float, task_id: str, message: str) -> None:
        ti = self.tis[task_id]
        self.events.append({'t': time_s, 'task_id': task_id, 'state': ti.state, 'try_number': ti.try_number,
                            'message': message})

    def _schedule(self, time_s: float, kind: str, task_id: str) -> None:
        self.sequence += 1
        heapq.heappush(self.queue, (time_s, self.sequence, kind, task_id))

    def _finish(self, task_id: str, state: str, time_s: float, message: str) -> None:
        ti = self.tis[task_id]
        ti.state = state
        ti.end_s = time_s
        self._log(time_s, task_id, message)

    def _counts(self, task_id: str) -> tuple[dict[str, int], int]:
        upstream = self.dag.upstream(task_id)
        counts = {'success': 0, 'skipped': 0, 'failed': 0, 'upstream_failed': 0}
        for up in upstream:
            state = self.tis[up].state
            if state in counts:
                counts[state] += 1
        return counts, len(upstream)

    def _settle(self, time_s: float) -> None:
        changed = True
        while changed:
            changed = False
            for task_id, task in self.dag.tasks.items():
                ti = self.tis[task_id]
                if ti.state is not None:
                    continue
                counts, upstream = self._counts(task_id)
                if upstream:
                    decided = _new_state(task.trigger_rule, counts, upstream)
                    if decided:
                        self._finish(task_id, decided, time_s,
                                     f"{decided}: trigger_rule={task.trigger_rule} with upstream "
                                     + ', '.join(f"{k}={v}" for k, v in counts.items() if v))
                        changed = True
                        continue
                    if not _can_run(task.trigger_rule, counts, upstream):
                        continue
                if self._held_by_past(task, time_s):
                    continue
                ti.state = 'scheduled'
                self._start_attempt(task, time_s)
                changed = True

    def _held_by_past(self, task: TaskSpec, time_s: float) -> bool:
        if not task.depends_on_past or self.previous is None:
            return False
        before = self.previous.instances.get(task.task_id)
        if before is None or before.state in ('success', 'skipped'):
            return False
        if task.task_id not in self.blocked:
            self.blocked.add(task.task_id)
            self._log(time_s, task.task_id,
                      f"not started: depends_on_past, and {task.task_id} is {before.state or 'not run'} in the "
                      f"previous run ({self.previous.plan.run_id})")
        return True

    def _behavior(self, task_id: str) -> TaskBehavior:
        return self.behaviors.get(task_id) or TaskBehavior()

    def _start_attempt(self, task: TaskSpec, time_s: float) -> None:
        ti = self.tis[task.task_id]
        behavior = self._behavior(task.task_id)
        ti.try_number += 1
        if ti.start_s is None:
            ti.start_s = time_s
        ti.state = 'running'
        if task.kind == 'sensor':
            self._run_sensor(task, behavior, time_s)
            return
        duration = behavior.duration_seconds
        fails = behavior.fail_attempts == 'all' or ti.try_number in behavior.fail_attempts
        timeout = task.execution_timeout_s
        if timeout is not None and duration > timeout:
            self._log(time_s, task.task_id, f"attempt {ti.try_number} started")
            self._schedule(time_s + timeout, 'timeout', task.task_id)
        else:
            self._log(time_s, task.task_id, f"attempt {ti.try_number} started")
            self._schedule(time_s + duration, 'fail' if fails else 'success', task.task_id)

    def _run_sensor(self, task: TaskSpec, behavior: TaskBehavior, time_s: float) -> None:
        interval = task.poke_interval_s
        arrival = behavior.sensor_true_after_seconds
        timeout_poke = math.floor(task.timeout_s / interval) + 1  # first false poke with elapsed > timeout
        success_poke = math.ceil(arrival / interval) if arrival is not None else None
        self._log(time_s, task.task_id, f"sensor started in {task.mode} mode; poke every {interval:g}s, "
                                        f"timeout {task.timeout_s:g}s")
        if success_poke is not None and success_poke <= timeout_poke:
            self._schedule(time_s + success_poke * interval, 'sensor_success', task.task_id)
        else:
            self._schedule(time_s + timeout_poke * interval, 'sensor_timeout', task.task_id)

    def _on_success(self, task: TaskSpec, time_s: float) -> None:
        self._finish(task.task_id, 'success', time_s, f"success on try {self.tis[task.task_id].try_number}")
        behavior = self._behavior(task.task_id)
        downstream = self.dag.downstream(task.task_id)
        if task.kind == 'branch':
            chosen = behavior.branch if behavior.branch is not None else task.static_branch
            if chosen is None:
                raise AirflowLabError(f"Branch `{task.task_id}` has no literal return value; the scenario must say "
                                      "which task(s) it chooses")
            invalid = [c for c in chosen if c not in downstream]
            if invalid:
                raise AirflowLabError(f"Branch `{task.task_id}` chose {', '.join(invalid)}, which is not directly "
                                      "downstream of it (Airflow rejects this)")
            for target in downstream:
                if target not in chosen and self.tis[target].state is None:
                    self._finish(target, 'skipped', time_s, f"skipped: not chosen by branch {task.task_id}")
        elif task.kind == 'short_circuit':
            condition = True if behavior.condition is None else behavior.condition
            if not condition:
                targets = self._all_downstream(task.task_id) if task.ignore_downstream_trigger_rules else downstream
                for target in targets:
                    if self.tis[target].state is None:
                        self._finish(target, 'skipped', time_s, f"skipped: short-circuit {task.task_id} returned False")

    def _all_downstream(self, task_id: str) -> list[str]:
        found: list[str] = []
        stack = list(self.dag.downstream(task_id))
        while stack:
            current = stack.pop()
            if current not in found:
                found.append(current)
                stack.extend(self.dag.downstream(current))
        return found

    def _on_failure(self, task: TaskSpec, time_s: float, reason: str) -> None:
        ti = self.tis[task.task_id]
        if ti.try_number <= task.retries:
            ti.state = 'up_for_retry'
            self._log(time_s, task.task_id, f"{reason} on try {ti.try_number}; retry in {task.retry_delay_s:g}s")
            self._schedule(time_s + task.retry_delay_s, 'retry', task.task_id)
            return
        self._finish(task.task_id, 'failed', time_s, f"{reason} on try {ti.try_number}; no retries left")

    def run(self) -> RunResult:
        self._settle(0.0)
        while self.queue:
            time_s, _, kind, task_id = heapq.heappop(self.queue)
            task = self.dag.tasks[task_id]
            if kind == 'success':
                self._on_success(task, time_s)
            elif kind == 'fail':
                self._on_failure(task, time_s, 'failed')
            elif kind == 'timeout':
                self._on_failure(task, time_s, f"execution_timeout ({task.execution_timeout_s:g}s) exceeded")
            elif kind == 'retry':
                self._start_attempt(task, time_s)
                continue
            elif kind == 'sensor_success':
                self._on_success(task, time_s)
            elif kind == 'sensor_timeout':
                state = 'skipped' if task.soft_fail else 'failed'
                self._finish(task_id, state, time_s, f"sensor timed out after {time_s - (self.tis[task_id].start_s or 0):g}s"
                             + ("; soft_fail skips it" if task.soft_fail else "; sensor timeouts are not retried"))
            self._settle(time_s)
        pending = [t for t, ti in self.tis.items() if ti.state not in TERMINAL]
        if pending and not self.blocked:
            raise AirflowLabError(f"Simulation deadlock: {', '.join(pending)} never became runnable")
        if pending:
            return RunResult(self.plan, 'running', self.tis, self.events)
        leaves = self.dag.leaves()
        failed = any(self.tis[leaf].state in ('failed', 'upstream_failed') for leaf in leaves)
        return RunResult(self.plan, 'failed' if failed else 'success', self.tis, self.events)


def _iso(value: datetime) -> str:
    return value.isoformat()


def planned_runs(dag: DagSpec, scenario: Scenario) -> list[RunPlan]:
    """Scheduled runs up to `now`, plus manual runs triggered at or before `now`, by run_after."""
    runs = plan_runs(dag, scenario.now, scenario.unpaused_at)
    runs += [manual_run(dag, at) for at in scenario.manual_runs if utc(at) <= utc(scenario.now)]
    runs.sort(key=lambda run: (run.run_after, run.run_type))
    return runs[-1:] if scenario.latest_run_only else runs


def simulate(dag: DagSpec, scenario: Scenario, runs: list[RunPlan] | None = None) -> list[RunResult]:
    """Simulate `runs` (default: the scenario's planned runs). With depends_on_past, pass every run since the DAG
    was unpaused: a run left out cannot hold back the next one."""
    unknown = set(scenario.tasks) | {t for overrides in scenario.by_logical_date.values() for t in overrides}
    unknown -= set(dag.tasks)
    if unknown:
        raise AirflowLabError(f"The DAG has no task(s) named {', '.join(sorted(unknown))}, which the scenario expects")
    keep_last = False
    if runs is None:
        keep_last = scenario.latest_run_only and dag.cross_run
        runs = planned_runs(dag, scenario.model_copy(update={'latest_run_only': False}) if keep_last else scenario)
    done: dict[int, RunResult] = {}
    for index in sorted(range(len(runs)), key=lambda i: (runs[i].logical_date, runs[i].run_after)):
        plan = runs[index]
        behaviors = dict(scenario.tasks)
        behaviors.update(scenario.by_logical_date.get(_iso(plan.logical_date), {}))
        done[index] = _RunSimulator(dag, plan, behaviors, _previous_run(dag, plan, done.values())).run()
    results = [done[i] for i in range(len(runs))]
    return results[-1:] if keep_last else results


def _previous_run(dag: DagSpec, plan: RunPlan, earlier: Any) -> RunResult | None:
    """The run PrevDagrunDep compares with: with catchup, the previous scheduled run; otherwise the previous run of
    any type (both by logical date). Only needed when a task depends on the past."""
    if not dag.cross_run:
        return None
    candidates = [r for r in earlier if r.plan.logical_date < plan.logical_date
                  and (not dag.catchup or r.plan.run_type == 'scheduled')]
    return max(candidates, key=lambda r: (r.plan.logical_date, r.plan.run_after), default=None)


def rendered_rows(dag: DagSpec, plan: RunPlan) -> list[dict[str, Any]]:
    rows = []
    for task in dag.tasks.values():
        for field_name, template in task.templates.items():
            ctx = context(dag.dag_id, task.task_id, plan.logical_date, plan.data_interval_start,
                          plan.data_interval_end, plan.run_id)
            rows.append({'logical_date': _iso(plan.logical_date), 'task_id': task.task_id, 'field': field_name,
                         'value': render(template, ctx)})
    return rows


def outcome_rows(dag: DagSpec, scenario: Scenario) -> list[dict[str, Any]]:
    """Rows of the requested outcome table, projected on scenario.columns."""
    if scenario.outcome == 'edges':
        rows = [{'upstream': a, 'downstream': b} for a, b in dag.edges]
    elif scenario.outcome == 'tasks':
        rows = [{'task_id': t.task_id, 'operator': t.operator, 'trigger_rule': t.trigger_rule, 'retries': t.retries,
                 'retry_delay_s': t.retry_delay_s} for t in dag.tasks.values()]
    else:
        results = simulate(dag, scenario)
        if scenario.outcome == 'runs':
            rows = [{'logical_date': _iso(r.plan.logical_date), 'run_after': _iso(r.plan.run_after),
                     'data_interval_start': _iso(r.plan.data_interval_start),
                     'data_interval_end': _iso(r.plan.data_interval_end), 'run_id': r.plan.run_id,
                     'run_type': r.plan.run_type, 'state': r.state}
                    for r in results]
        elif scenario.outcome == 'task_instances':
            rows = [{'logical_date': _iso(r.plan.logical_date), 'task_id': ti.task_id, 'state': ti.state,
                     'try_number': ti.try_number, 'start_s': ti.start_s, 'end_s': ti.end_s}
                    for r in results for ti in r.instances.values()]
        else:
            rows = [row for r in results for row in rendered_rows(dag, r.plan)]
    if scenario.columns:
        rows = [{column: row.get(column) for column in scenario.columns} for row in rows]
    return rows
