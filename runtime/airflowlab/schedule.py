"""Which DAG runs the scheduler creates, following Airflow 3 timetables.

- A cron string or preset uses CronTriggerTimetable (the Airflow 3 default):
  one run per cron tick; logical date = run_after = the tick, and the data
  interval has zero length.
- CronDataIntervalTimetable (the Airflow 2 default for cron schedules): one run
  per complete interval between two ticks; logical date = interval start, and the
  run starts once the interval has ended.
- '@once': one run at start_date. None: no scheduled runs.

catchup=True creates every run since start_date; catchup=False (the Airflow 3
default) starts from the latest one at the time the DAG is unpaused. The
scheduler is assumed to run continuously from then until `now`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .cron import Cron, utc
from .model import AirflowLabError, DagSpec

MAX_RUNS = 5000


@dataclass(frozen=True)
class RunPlan:
    logical_date: datetime
    run_after: datetime
    data_interval_start: datetime
    data_interval_end: datetime
    run_type: str = 'scheduled'

    @property
    def run_id(self) -> str:
        return f"{self.run_type}__{self.logical_date.isoformat()}"


def _skip_to_latest(cron: Cron, current: datetime) -> datetime:
    """Start of the latest complete interval at `current` (CronDataIntervalTimetable, catchup=False)."""
    last_start = cron.prev_tick(current)
    next_start = cron.next_tick(last_start)
    return last_start if next_start == current else cron.prev_tick(last_start)


def manual_run(dag: DagSpec, at: datetime) -> RunPlan:
    """A run triggered at `at` with logical date `at`; its data interval is inferred as Airflow's timetables do.

    CronDataIntervalTimetable infers the last complete interval before the trigger;
    the other timetables use a zero-length interval at the trigger time.
    """
    at = utc(at)
    if dag.schedule.kind == 'cron_interval':
        cron = Cron(dag.schedule.cron or '')
        end = cron.prev_tick(at, inclusive=True)
        return RunPlan(at, at, cron.prev_tick(end), end, 'manual')
    return RunPlan(at, at, at, at, 'manual')


def plan_runs(dag: DagSpec, now: datetime, unpaused_at: datetime | None = None) -> list[RunPlan]:
    now = utc(now)
    unpaused = utc(unpaused_at) if unpaused_at else now
    if unpaused > now:
        raise AirflowLabError("The scenario unpauses the DAG after `now`")
    kind, start, end = dag.schedule.kind, dag.start_date, dag.end_date
    if kind == 'none':
        return []
    assert start is not None
    if kind == 'once':
        return [RunPlan(start, start, start, start)] if start <= now else []
    cron = Cron(dag.schedule.cron or '')
    runs: list[RunPlan] = []
    if kind == 'cron_trigger':
        earliest = cron.next_tick(start, inclusive=True)
        tick = earliest if dag.catchup else max(cron.prev_tick(unpaused, inclusive=True), earliest)
        while tick <= now and (end is None or tick <= end):
            runs.append(RunPlan(tick, tick, tick, tick))
            if len(runs) > MAX_RUNS:
                raise AirflowLabError(f"The schedule creates more than {MAX_RUNS} runs; the simulator stops there")
            tick = cron.next_tick(tick)
        return runs
    if kind == 'cron_interval':
        earliest = cron.next_tick(start, inclusive=True)
        interval_start = earliest if dag.catchup else max(_skip_to_latest(cron, unpaused), earliest)
        while end is None or interval_start <= end:
            interval_end = cron.next_tick(interval_start)
            if interval_end > now:
                break
            runs.append(RunPlan(interval_start, interval_end, interval_start, interval_end))
            if len(runs) > MAX_RUNS:
                raise AirflowLabError(f"The schedule creates more than {MAX_RUNS} runs; the simulator stops there")
            interval_start = interval_end
        return runs
    raise AirflowLabError(f"Unknown schedule kind {kind}")
