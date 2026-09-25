"""Intermediate representation of a parsed Airflow DAG file."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


class AirflowLabError(ValueError):
    """A DAG file the simulator cannot represent faithfully. Carries the source line."""

    def __init__(self, message: str, line: int | None = None):
        super().__init__(f"line {line}: {message}" if line else message)
        self.line = line


TRIGGER_RULES = (
    'all_success', 'all_failed', 'all_done', 'all_skipped', 'one_success', 'one_failed', 'one_done',
    'none_failed', 'none_failed_min_one_success', 'none_skipped', 'always',
)


@dataclass
class Schedule:
    # 'none': manual only; 'once': OnceTimetable; 'cron_trigger': CronTriggerTimetable
    # (Airflow 3 default for cron strings and presets); 'cron_interval': CronDataIntervalTimetable.
    kind: str
    cron: str | None = None
    label: str = 'None'


@dataclass
class TaskSpec:
    task_id: str
    operator: str
    # 'task' | 'branch' | 'short_circuit' | 'sensor'
    kind: str
    line: int
    trigger_rule: str = 'all_success'
    retries: int = 0
    retry_delay_s: float = 300.0
    execution_timeout_s: float | None = None
    # Sensor settings (Airflow BaseSensorOperator defaults).
    poke_interval_s: float = 60.0
    timeout_s: float = 604800.0
    mode: str = 'poke'
    soft_fail: bool = False
    # ShortCircuitOperator default: skip every downstream task regardless of trigger rules.
    ignore_downstream_trigger_rules: bool = True
    # Templated field name -> raw template text (rendered per run, never executed).
    templates: dict[str, str] = field(default_factory=dict)
    # Literal task id(s) a branch callable returns, when statically obvious.
    static_branch: list[str] | None = None


@dataclass
class DagSpec:
    dag_id: str
    schedule: Schedule
    start_date: datetime | None
    end_date: datetime | None
    catchup: bool
    tasks: dict[str, TaskSpec]
    edges: list[tuple[str, str]]
    line: int

    def upstream(self, task_id: str) -> list[str]:
        return [a for a, b in self.edges if b == task_id]

    def downstream(self, task_id: str) -> list[str]:
        return [b for a, b in self.edges if a == task_id]

    def leaves(self) -> list[str]:
        sources = {a for a, _ in self.edges}
        return [task_id for task_id in self.tasks if task_id not in sources]
