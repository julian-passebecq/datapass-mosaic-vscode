"""Airflow Lab panel view: parse a DAG file, simulate a scenario, return what the panel shows.

The DAG file is parsed, never executed. Unlike grading scenarios, a sensor the
Lab scenario does not configure sees its condition on the first poke, so a plain
simulation shows the normal path. A simulation error (for example a branch
whose choice is unknown) still returns the parsed DAG so the panel can show the
graph and let the learner complete the scenario.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from .model import AirflowLabError, DagSpec
from .parser import parse_dag
from .simulate import Scenario, TaskBehavior, planned_runs, rendered_rows, simulate

TRUTH = ("Simulated Airflow 3 semantics for the supported subset. The DAG file is parsed, never executed; "
         "no Airflow scheduler, executor or worker runs.")
SCHEDULE_NOTES = {
    'none': "No schedule: the DAG runs only when triggered manually.",
    'once': "@once: a single run at start_date.",
    'cron_trigger': ("CronTriggerTimetable, the Airflow 3 default for cron strings and presets: one run per cron tick; "
                     "the logical date is the tick and the data interval is empty."),
    'cron_interval': ("CronDataIntervalTimetable: one run per complete interval between two ticks; the logical date is "
                      "the interval start and the run starts when the interval ends."),
}
RUN_LIMIT = 40


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dag_view(dag: DagSpec) -> dict[str, Any]:
    tasks = []
    for task in dag.tasks.values():
        item: dict[str, Any] = {
            'task_id': task.task_id, 'operator': task.operator, 'kind': task.kind, 'line': task.line,
            'trigger_rule': task.trigger_rule, 'retries': task.retries, 'retry_delay_s': task.retry_delay_s,
            'execution_timeout_s': task.execution_timeout_s, 'upstream': dag.upstream(task.task_id),
            'downstream': dag.downstream(task.task_id), 'templated_fields': list(task.templates),
            'static_branch': task.static_branch,
        }
        if task.kind == 'sensor':
            item['sensor'] = {'poke_interval_s': task.poke_interval_s, 'timeout_s': task.timeout_s,
                              'mode': task.mode, 'soft_fail': task.soft_fail}
        tasks.append(item)
    return {
        'dag_id': dag.dag_id,
        'schedule': {'kind': dag.schedule.kind, 'label': dag.schedule.label, 'note': SCHEDULE_NOTES[dag.schedule.kind]},
        'start_date': _iso(dag.start_date), 'end_date': _iso(dag.end_date), 'catchup': dag.catchup,
        'tasks': tasks, 'edges': [{'upstream': a, 'downstream': b} for a, b in dag.edges],
    }


def lab_view(source: str, scenario: dict[str, Any], run_limit: int = RUN_LIMIT) -> dict[str, Any]:
    scenario = dict(scenario)
    scenario.setdefault('now', datetime.now(timezone.utc).replace(second=0, microsecond=0))
    view: dict[str, Any] = {'status': 'invalid', 'truth': TRUTH, 'error': None, 'dag': None, 'runs': [],
                            'total_runs': 0}
    try:
        dag = parse_dag(source)
    except AirflowLabError as exc:
        view['error'] = {'message': str(exc), 'line': exc.line}
        return view
    view['dag'] = _dag_view(dag)
    try:
        parsed = Scenario.model_validate(scenario)
        # Lab default: a sensor the scenario says nothing about sees its condition on the first poke.
        for task in dag.tasks.values():
            if task.kind != 'sensor':
                continue
            behavior = parsed.tasks.get(task.task_id)
            if behavior is None:
                parsed.tasks[task.task_id] = TaskBehavior(sensor_true_after_seconds=0)
            elif 'sensor_true_after_seconds' not in behavior.model_fields_set:
                parsed.tasks[task.task_id] = behavior.model_copy(update={'sensor_true_after_seconds': 0})
        view.update(now=_iso(parsed.now), unpaused_at=_iso(parsed.unpaused_at))
        runs = planned_runs(dag, parsed)
        view['total_runs'] = len(runs)
        # depends_on_past needs every earlier run: the first shown run may be held back by one that is not shown.
        results = simulate(dag, parsed, runs if dag.cross_run else runs[-run_limit:])[-run_limit:]
    except (AirflowLabError, ValidationError) as exc:
        view.update(status='simulation_error', error={'message': str(exc), 'line': getattr(exc, 'line', None)})
        return view
    for result in results:
        run: dict[str, Any] = {
            'run_id': result.plan.run_id, 'run_type': result.plan.run_type,
            'logical_date': _iso(result.plan.logical_date), 'run_after': _iso(result.plan.run_after),
            'data_interval_start': _iso(result.plan.data_interval_start),
            'data_interval_end': _iso(result.plan.data_interval_end), 'state': result.state,
            'duration_s': max((ti.end_s or 0.0 for ti in result.instances.values()), default=0.0),
            'instances': [{'task_id': ti.task_id, 'state': ti.state, 'try_number': ti.try_number,
                           'start_s': ti.start_s, 'end_s': ti.end_s} for ti in result.instances.values()],
            'events': result.events, 'rendered': [], 'render_error': None,
        }
        try:
            run['rendered'] = [{k: row[k] for k in ('task_id', 'field', 'value')} for row in rendered_rows(dag, result.plan)]
        except AirflowLabError as exc:
            run['render_error'] = str(exc)
        view['runs'].append(run)
    view['status'] = 'simulated'
    return view
