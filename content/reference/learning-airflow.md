# Airflow

Cheatsheet for the Learning path *Orchestration in production* and the concept checks in `learning-checks-v1`.
The Airflow Lab parses DAG files with a whitelisted AST reader (never executed) and simulates the scheduler with
Airflow 3 semantics; it is not an Airflow scheduler or executor.

## Scheduling

| Concept | Remember |
|---|---|
| Logical date | the date a run is "for"; use it (or the data interval) in tasks, never `datetime.now()` |
| Data-interval timetable | Airflow 2 default for cron/presets: the run for 1 Oct covers 1 Oct 00:00 to 2 Oct 00:00 and starts after it ends |
| `CronTriggerTimetable` | Airflow 3 default for cron strings: runs at the cron time; logical date = that time |
| `catchup` | one run per missed interval since `start_date`; **default False in Airflow 3**, True in Airflow 2 |
| Backfill | an explicit rerun of past intervals; requires idempotent tasks |
| Assets (Datasets in Airflow 2) | schedule a DAG when a producer task updates an asset |

## Tasks

- Default `trigger_rule` = `all_success`. Others: `all_done`, `one_failed`, `none_failed`, `none_failed_min_one_success`.
- A cleanup task with `all_done` runs in every case; a run still fails if a leaf task failed. A watcher task with
  `one_failed` that is downstream of every task keeps a failure visible.
- `retries`, `retry_delay`, `retry_exponential_backoff`, and `execution_timeout` so a hung attempt ends.
- XComs live in the metadata database: pass small metadata (paths, counts), never data frames or secrets.
- `depends_on_past=True`: a run waits for the same task of the previous run to have succeeded.

## Waiting and sharing

- Sensors: `mode="poke"` holds a worker slot; `mode="reschedule"` frees it between checks; deferrable sensors wait in the
  triggerer. `soft_fail=True` marks a timed-out sensor as skipped.
- Pools cap concurrent tasks across DAGs (a rate-limited API); `max_active_runs` caps runs of one DAG.

## DAG file hygiene

- No database or API calls at module top level: the DAG processor parses files continuously.
- Keep heavy imports inside tasks. Set `start_date` as a fixed, timezone-aware date.
