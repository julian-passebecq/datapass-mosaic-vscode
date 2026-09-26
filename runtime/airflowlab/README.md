# Airflow Lab simulator

A bounded, deterministic Airflow teaching simulator. It is **not Airflow**: no scheduler, executor, worker, metadata database or task code runs.

## DAG files: parsed, never executed

`parser.py` reads a real-looking Airflow DAG file with a whitelisted AST walk. Supported:

- one DAG per file: `with DAG(...)`, `dag = DAG(...)` with `with dag:` or `dag=dag`, or `@dag`;
- operators: `EmptyOperator`, `BashOperator`, `PythonOperator`, `BranchPythonOperator`, `ShortCircuitOperator`, `SQLExecuteQueryOperator`, `FileSensor`, `PythonSensor`, imported from Airflow 3 (`airflow.providers.standard...`, `airflow.sdk`) or the Airflow 2 paths;
- TaskFlow: `@task`, `@task.branch`, `@task.short_circuit`, `@task.sensor`, `.override(...)`; passing a task's result to another task creates the dependency;
- dependencies: `>>`, `<<`, lists, `set_upstream`/`set_downstream`, `chain`, `cross_downstream`;
- `default_args` (explicit operator arguments win), `retries`, `retry_delay`, `execution_timeout`, `trigger_rule` (strings or `TriggerRule.X`), `depends_on_past` (and `ignore_first_depends_on_past`, which changes nothing here since the first run has no previous run), sensor `poke_interval`, `timeout`, `mode`, `soft_fail`;
- schedules: `None`, `"@once"`, cron strings and presets, `CronTriggerTimetable(cron, timezone="UTC")`, `CronDataIntervalTimetable(cron, timezone="UTC")`; `start_date`/`end_date` in UTC; `catchup`.

Everything else is rejected with a line number: other imports, loops and comprehensions that generate tasks, f-strings, `**kwargs`, `wait_for_downstream`, callbacks, exponential backoff, `timedelta` schedules, non-UTC timezones, and Airflow 2 arguments removed in Airflow 3 (`schedule_interval`, `timetable=`). Function bodies are never run; a branch's choice comes from the scenario, or from a single literal `return`.

## Semantics (Airflow 3 defaults)

- **Runs** (`schedule.py`): cron strings and presets use CronTriggerTimetable (one run per tick; logical date = run_after = tick; zero-length data interval). CronDataIntervalTimetable creates one run per complete interval (logical date = interval start; the run starts at the interval end). `catchup` defaults to False: the first run is the latest one at unpause time. The scheduler is assumed to run continuously until `now`.
- **Task instances** (`simulate.py`): trigger rules as in Airflow's TriggerRuleDep (all_success, all_failed, all_done, all_skipped, one_success, one_failed, one_done, none_failed, none_failed_min_one_success, none_skipped, always); retries while `try_number <= retries`, after `retry_delay`; `execution_timeout` fails an attempt (retryable); a sensor pokes every `poke_interval` and times out at the first false poke past `timeout` (not retried; skipped with `soft_fail`); a branch skips its unchosen direct downstream tasks; a false short-circuit skips all downstream tasks. The DAG run fails when a leaf task failed or is upstream_failed.
- **Across runs** (`depends_on_past`): runs are simulated in logical-date order. A `depends_on_past` task starts only when the same task succeeded or was skipped in the previous run (Airflow's PrevDagrunDep: with `catchup`, the previous scheduled run; otherwise the previous run of any type). Otherwise it keeps no state, like every task waiting on it, and the DAG run stays `running`, as in Airflow until someone clears the failed day. The Lab and grading simulate every run since the unpause so the first shown run sees its predecessor. Waiting times across runs are not modelled: each run's times stay relative to its own start.
- **Templates** (`templates.py`): `{{ ... }}` with `ds`, `ds_nodash`, `ts`, `ts_nodash`, `logical_date`, `data_interval_start/end`, `run_id`, `dag.dag_id`, `task.task_id`, the ds/ts filters, `macros.ds_add`, `macros.ds_format` and `strftime`. No Jinja engine and no eval. Variables removed in Airflow 3 (`execution_date`, `prev_ds`, `next_ds`, `yesterday_ds`, ...) are reported as removed.

Not modeled: pools, concurrency limits, `max_active_runs`, `wait_for_downstream`, waiting times between runs, asset triggers, timezones other than UTC, DST, XCom values, executors and worker failures. Each run is simulated to completion with free worker slots.

## Scenarios

`Scenario` gives the scheduler clock (`now`, optional `unpaused_at`), optional `manual_runs` (logical date = trigger time; CronDataIntervalTimetable infers the last complete interval before it, other timetables a zero-length interval) and per-task behavior: `duration_seconds`, `fail_attempts` (try numbers, or `"all"`), `sensor_true_after_seconds`, `branch`, `condition`, optionally per logical date. `outcome_rows` returns one of five tables for grading: `runs`, `task_instances`, `rendered`, `edges`, `tasks`.

## Airflow Lab panel

`lab.py` builds the panel view behind `POST /api/local/airflow/simulate`: the parsed DAG, the number of runs, the latest 40 runs simulated with their task instances, timed events (state and try number after each step, for replay) and rendered templates. Parse errors return a line; a simulation error still returns the parsed DAG. In the Lab only, a sensor the scenario does not configure sees its condition on the first poke, so a plain simulation shows the normal path; grading scenarios default to "never".
