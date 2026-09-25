"""Generate content/exercise-packs/airflow-lab-v1 from authored specs.

Expected rows are computed by running each reference DAG through the Airflow Lab
simulator with the fixture scenario; review them by hand. Run from the
repository root with PYTHONPATH=runtime.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from pack_quality import write_mutants

ROOT = Path.cwd()
PACK = ROOT / "content" / "exercise-packs" / "airflow-lab-v1"
EXERCISES: list[dict] = []


def code(text: str) -> str:
    return textwrap.dedent(text).strip("\n") + "\n"


def exercise(**spec):
    EXERCISES.append(spec)


SIMULATOR = ("Your DAG file is read by a whitelisted parser and never executed. Grading simulates the Airflow 3 "
             "scheduler and task instances for each check's scenario (scheduler clock, task durations, failures, "
             "file arrival, branch choice). Times are UTC; each run is simulated to completion with free worker "
             "slots.")

# 1 ---------------------------------------------------------------------------
FAN_TASKS = '''
    extract_orders = EmptyOperator(task_id="extract_orders")
    extract_customers = EmptyOperator(task_id="extract_customers")
    transform = EmptyOperator(task_id="transform")
    load_warehouse = EmptyOperator(task_id="load_warehouse")
    load_search = EmptyOperator(task_id="load_search")
    notify = EmptyOperator(task_id="notify")
'''
FAN_HEAD = '''
from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.empty import EmptyOperator

with DAG(dag_id="customer_360", schedule="@daily", start_date=datetime(2026, 3, 1)) as dag:
'''
exercise(
    id="af-fan-in-fan-out",
    title="Fan-in and fan-out dependencies",
    difficulty="easy",
    topics=["dependencies", "fan-in", "fan-out"],
    prompt=("Wire customer_360: extract_orders and extract_customers both feed transform; transform feeds "
            "load_warehouse and load_search; notify runs after both loads. The two extracts, and the two loads, run "
            "in parallel."),
    sections=[
        ("Graded", "The dependency edges, when each task starts in a normal run (every task takes 60 s, "
                   "extract_customers 120 s), and the task states on a day when extract_customers fails."),
    ],
    outcome_note="edges, then start times, then states",
    starter=code(FAN_HEAD + FAN_TASKS + '''
    # Wrong: everything runs one after another.
    extract_orders >> extract_customers >> transform >> load_warehouse >> load_search >> notify
'''),
    solution=code(FAN_HEAD + FAN_TASKS + '''
    [extract_orders, extract_customers] >> transform >> [load_warehouse, load_search] >> notify
'''),
    fixtures=[
        ("edges", "visible", {"now": "2026-03-01T12:00:00Z", "outcome": "edges"}),
        ("start-times", "hidden", {"now": "2026-03-01T12:00:00Z", "outcome": "task_instances",
                                   "columns": ["task_id", "state", "start_s"],
                                   "tasks": {"extract_customers": {"duration_seconds": 120}}}),
        ("extract-fails", "edge", {"now": "2026-03-01T12:00:00Z", "outcome": "task_instances",
                                   "columns": ["task_id", "state"],
                                   "tasks": {"extract_customers": {"fail_attempts": "all"}}}),
    ],
    exact_schema=None,
    hints=["A list on either side of >> links every task in it.",
           "`[a, b] >> c >> [d, e] >> f` reads left to right."],
    explanation=("Lists express fan-in and fan-out: `[a, b] >> c` makes c wait for both, `c >> [d, e]` starts both "
                 "after c. Airflow cannot link a list directly to a list with >>; the task in the middle (or "
                 "cross_downstream) does that."),
    follow_ups=["How would you link [a, b] to [c, d] with every pair connected?"],
    mutants=[
        code(FAN_HEAD + FAN_TASKS + '''
    extract_orders >> extract_customers >> transform >> [load_warehouse, load_search] >> notify
'''),
        code(FAN_HEAD + FAN_TASKS + '''
    [extract_orders, extract_customers] >> transform >> [load_warehouse, load_search]
    load_warehouse >> notify
'''),
    ],
)

# 2 ---------------------------------------------------------------------------
TF_HEAD = '''
import pendulum

from airflow.sdk import dag, task


@dag(schedule="@daily", start_date=pendulum.datetime(2026, 3, 1, tz="UTC"))
def orders_taskflow():
    @task
    def extract():
        return [{"order_id": 1, "amount": 10.0}]

    @task
    def transform(rows):
        return [row for row in rows if row["amount"] > 0]

    @task
    def load(rows):
        print(f"loading {len(rows)} rows")

    @task
    def audit():
        print("audit done")

'''
exercise(
    id="af-taskflow-data-dependencies",
    title="TaskFlow: dependencies come from passing return values",
    difficulty="medium",
    topics=["taskflow", "xcom", "dependencies"],
    prompt=("In orders_taskflow, extract's result feeds transform, transform's result feeds load, and audit runs "
            "after load (it takes no input). Wire it with TaskFlow calls: passing a task's return value to another "
            "task creates the dependency."),
    sections=[
        ("Graded", "The dependency edges, the task states when transform fails, and the task states in a normal run."),
    ],
    outcome_note="edges, then states",
    starter=code(TF_HEAD + '''    raw = extract()
    clean = transform(raw)
    # Wrong: load receives the raw rows, and audit is not linked at all.
    load(raw)
    audit()


orders_taskflow()
'''),
    solution=code(TF_HEAD + '''    raw = extract()
    clean = transform(raw)
    load(clean) >> audit()


orders_taskflow()
'''),
    fixtures=[
        ("edges", "visible", {"now": "2026-03-01T12:00:00Z", "outcome": "edges"}),
        ("transform-fails", "hidden", {"now": "2026-03-01T12:00:00Z", "outcome": "task_instances",
                                       "columns": ["task_id", "state"],
                                       "tasks": {"transform": {"fail_attempts": "all"}}}),
        ("normal-run", "edge", {"now": "2026-03-01T12:00:00Z", "outcome": "task_instances",
                                "columns": ["task_id", "state", "start_s"]}),
    ],
    exact_schema=None,
    hints=["Calling a @task with another task's result as an argument adds an edge.",
           "A TaskFlow call returns a reference you can also use with >>."],
    explanation=("With TaskFlow, `transform(raw)` both passes the XCom value and declares extract >> transform. "
                 "A task that consumes nothing (audit) still needs an explicit >> to run after load."),
    follow_ups=["What happens if you call extract() twice in the same DAG?"],
    mutants=[
        code(TF_HEAD + '''    raw = extract()
    clean = transform(raw)
    load(clean)
    audit()


orders_taskflow()
'''),
        code(TF_HEAD + '''    raw = extract()
    clean = transform(raw)
    load(raw) >> audit()


orders_taskflow()
'''),
    ],
)

# 3 ---------------------------------------------------------------------------
CATCH_HEAD = '''
from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

'''
exercise(
    id="af-catchup-backfill",
    title="Catch up every day since start_date",
    difficulty="easy",
    topics=["scheduling", "catchup", "backfill"],
    prompt=("daily_sales starts on 2026-03-01 and runs daily at midnight UTC. It is deployed and unpaused later. "
            "When it is unpaused, the scheduler must create one run for every day since March 1, not only the latest "
            "one."),
    sections=[
        ("Airflow 3 defaults", "catchup is False by default in Airflow 3. A cron string or preset such as @daily "
                               "uses CronTriggerTimetable: one run per tick, and the logical date is the tick itself."),
        ("Graded", "The runs created by a given scheduler time (logical date and run_after)."),
    ],
    outcome_note="runs",
    starter=code(CATCH_HEAD + '''with DAG(
    dag_id="daily_sales",
    schedule="@daily",
    start_date=datetime(2026, 3, 1),
) as dag:
    BashOperator(task_id="load", bash_command="load_sales --day {{ ds }}")
'''),
    solution=code(CATCH_HEAD + '''with DAG(
    dag_id="daily_sales",
    schedule="@daily",
    start_date=datetime(2026, 3, 1),
    catchup=True,
) as dag:
    BashOperator(task_id="load", bash_command="load_sales --day {{ ds }}")
'''),
    fixtures=[
        ("unpaused-march-5", "visible", {"now": "2026-03-05T12:00:00Z", "outcome": "runs",
                                         "columns": ["logical_date", "run_after"]}),
        ("unpaused-march-3-early", "hidden", {"now": "2026-03-03T06:00:00Z", "outcome": "runs",
                                              "columns": ["logical_date", "run_after"]}),
        ("before-start-date", "edge", {"now": "2026-02-28T23:00:00Z", "outcome": "runs",
                                       "columns": ["logical_date", "run_after"]}),
    ],
    exact_schema=["logical_date", "run_after"],
    hints=["Which DAG argument decides whether past ticks since start_date get runs?"],
    explanation=("catchup=True makes the scheduler create a run for every tick between start_date and now. With "
                 "Airflow 3's default CronTriggerTimetable, the run for March 3 has logical date 2026-03-03 00:00 and "
                 "starts at that tick. Before start_date there is nothing to run."),
    follow_ups=["How would you reprocess only March 2 later, without enabling catchup? (airflow dags backfill)"],
    mutants=[
        code(CATCH_HEAD + '''with DAG(
    dag_id="daily_sales",
    schedule="@daily",
    start_date=datetime(2026, 3, 2),
    catchup=True,
) as dag:
    BashOperator(task_id="load", bash_command="load_sales --day {{ ds }}")
'''),
        code(CATCH_HEAD + '''with DAG(
    dag_id="daily_sales",
    schedule="0 6 * * *",
    start_date=datetime(2026, 3, 1),
    catchup=True,
) as dag:
    BashOperator(task_id="load", bash_command="load_sales --day {{ ds }}")
'''),
    ],
)

# 4 ---------------------------------------------------------------------------
exercise(
    id="af-no-accidental-backfill",
    title="Deploy without an accidental backfill",
    difficulty="easy",
    topics=["scheduling", "catchup"],
    prompt=("inventory_snapshot keeps a historical start_date of 2025-01-01, but it only makes sense for the current "
            "day. When it is unpaused, the scheduler must create a run for the latest tick only, then one run per "
            "new day, instead of hundreds of past runs."),
    sections=[
        ("Graded", "The runs created by a given scheduler time, for the unpause times in each scenario."),
    ],
    outcome_note="runs",
    starter=code(CATCH_HEAD + '''with DAG(
    dag_id="inventory_snapshot",
    schedule="@daily",
    start_date=datetime(2025, 1, 1),
    catchup=True,  # copied from an Airflow 2 template
) as dag:
    BashOperator(task_id="snapshot", bash_command="snapshot_inventory --day {{ ds }}")
'''),
    solution=code(CATCH_HEAD + '''with DAG(
    dag_id="inventory_snapshot",
    schedule="@daily",
    start_date=datetime(2025, 1, 1),
    catchup=False,
) as dag:
    BashOperator(task_id="snapshot", bash_command="snapshot_inventory --day {{ ds }}")
'''),
    fixtures=[
        ("unpaused-today", "visible", {"now": "2026-03-05T12:00:00Z", "outcome": "runs",
                                       "columns": ["logical_date", "run_after"]}),
        ("running-for-three-days", "hidden", {"now": "2026-03-07T08:00:00Z", "unpaused_at": "2026-03-05T10:00:00Z",
                                              "outcome": "runs", "columns": ["logical_date", "run_after"]}),
        ("unpaused-at-midnight", "edge", {"now": "2026-03-06T00:00:00Z", "unpaused_at": "2026-03-06T00:00:00Z",
                                          "outcome": "runs", "columns": ["logical_date", "run_after"]}),
    ],
    exact_schema=["logical_date", "run_after"],
    hints=["Airflow 3 already defaults to catchup=False; the template overrides it."],
    explanation=("With catchup=False the first run is the latest tick at or before the unpause time; from then on "
                 "the scheduler creates one run per tick. Removing the catchup argument gives the same result in "
                 "Airflow 3, where the default is False (it was True in Airflow 2)."),
    follow_ups=["Why is moving start_date to the deployment day a fragile alternative?"],
    mutants=[
        code(CATCH_HEAD + '''with DAG(
    dag_id="inventory_snapshot",
    schedule=None,
    start_date=datetime(2025, 1, 1),
) as dag:
    BashOperator(task_id="snapshot", bash_command="snapshot_inventory --day {{ ds }}")
'''),
        code(CATCH_HEAD + '''with DAG(
    dag_id="inventory_snapshot",
    schedule="@once",
    start_date=datetime(2025, 1, 1),
) as dag:
    BashOperator(task_id="snapshot", bash_command="snapshot_inventory --day {{ ds }}")
'''),
    ],
)

# 5 ---------------------------------------------------------------------------
exercise(
    id="af-cron-weekdays",
    title="Cron schedule: 06:30 UTC on weekdays",
    difficulty="easy",
    topics=["scheduling", "cron"],
    prompt=("market_prices must run at 06:30 UTC from Monday to Friday, and never on weekends. Write the schedule "
            "as a cron expression. catchup is on so the checks can list the runs of a whole week."),
    sections=[
        ("Cron fields", "minute hour day-of-month month day-of-week; day-of-week 0 or 7 is Sunday, 1 is Monday."),
        ("Graded", "The runs (logical dates) created between start_date (Monday 2026-03-02) and the scheduler time."),
    ],
    outcome_note="runs",
    starter=code(CATCH_HEAD + '''with DAG(
    dag_id="market_prices",
    schedule="30 6 * * *",  # also runs on Saturday and Sunday
    start_date=datetime(2026, 3, 2),
    catchup=True,
) as dag:
    BashOperator(task_id="fetch", bash_command="fetch_prices --ts {{ ts }}")
'''),
    solution=code(CATCH_HEAD + '''with DAG(
    dag_id="market_prices",
    schedule="30 6 * * 1-5",
    start_date=datetime(2026, 3, 2),
    catchup=True,
) as dag:
    BashOperator(task_id="fetch", bash_command="fetch_prices --ts {{ ts }}")
'''),
    fixtures=[
        ("first-week", "visible", {"now": "2026-03-09T07:00:00Z", "outcome": "runs", "columns": ["logical_date"]}),
        ("monday-before-0630", "hidden", {"now": "2026-03-16T06:29:00Z", "outcome": "runs",
                                          "columns": ["logical_date"]}),
        ("first-morning", "edge", {"now": "2026-03-02T06:30:00Z", "outcome": "runs", "columns": ["logical_date"]}),
    ],
    exact_schema=["logical_date"],
    hints=["Use a range in the day-of-week field."],
    explanation=("`30 6 * * 1-5` fires at 06:30 on Monday (1) through Friday (5). A run exists once its tick has "
                 "passed: at 06:29 on a Monday that day's run has not been created yet."),
    follow_ups=["How would you also skip public holidays? (a custom timetable or a short-circuit task)"],
    mutants=[
        code(CATCH_HEAD + '''with DAG(
    dag_id="market_prices",
    schedule="30 6 * * 0-4",
    start_date=datetime(2026, 3, 2),
    catchup=True,
) as dag:
    BashOperator(task_id="fetch", bash_command="fetch_prices --ts {{ ts }}")
'''),
        code(CATCH_HEAD + '''with DAG(
    dag_id="market_prices",
    schedule="0 6 * * 1-5",
    start_date=datetime(2026, 3, 2),
    catchup=True,
) as dag:
    BashOperator(task_id="fetch", bash_command="fetch_prices --ts {{ ts }}")
'''),
        code(CATCH_HEAD + '''with DAG(
    dag_id="market_prices",
    schedule="30 6 * * 1-6",
    start_date=datetime(2026, 3, 2),
    catchup=True,
) as dag:
    BashOperator(task_id="fetch", bash_command="fetch_prices --ts {{ ts }}")
'''),
    ],
)

# 6 ---------------------------------------------------------------------------
SQL_HEAD = '''
from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
'''
SQL_QUERY = ('"INSERT INTO daily_sales SELECT * FROM sales "\n'
             '            "WHERE sold_at >= \'{{ data_interval_start | ds }}\' AND sold_at < \'{{ data_interval_end | ds }}\'"')
exercise(
    id="af-data-interval-timetable",
    title="Load exactly one day with a data-interval timetable",
    difficulty="medium",
    topics=["scheduling", "data-interval", "templating"],
    prompt=("daily_sales_load reads sales between data_interval_start and data_interval_end. Each run must cover "
            "one full day, and the run for a day must start once that day is over (its logical date is the day it "
            "loads). With the plain \"@daily\" schedule the interval is empty. Make the DAG use data intervals."),
    sections=[
        ("Airflow 3 timetables", "A cron string or preset uses CronTriggerTimetable: logical date = trigger time, and "
                                 "data_interval_start = data_interval_end. CronDataIntervalTimetable (Airflow 2's "
                                 "default) creates one run per interval between two ticks; logical date = interval "
                                 "start, and the run starts at the interval end. Import it from "
                                 "airflow.timetables.interval and pass timezone=\"UTC\"."),
        ("Graded", "The rendered SQL of each run created by a given scheduler time (catchup is on)."),
    ],
    outcome_note="rendered",
    starter=code(SQL_HEAD + '''
with DAG(
    dag_id="daily_sales_load",
    schedule="@daily",
    start_date=datetime(2026, 3, 1),
    catchup=True,
) as dag:
    SQLExecuteQueryOperator(
        task_id="load_day",
        conn_id="warehouse",
        sql=(
            ''' + SQL_QUERY + '''
        ),
    )
'''),
    solution=code(SQL_HEAD + '''from airflow.timetables.interval import CronDataIntervalTimetable

with DAG(
    dag_id="daily_sales_load",
    schedule=CronDataIntervalTimetable("0 0 * * *", timezone="UTC"),
    start_date=datetime(2026, 3, 1),
    catchup=True,
) as dag:
    SQLExecuteQueryOperator(
        task_id="load_day",
        conn_id="warehouse",
        sql=(
            ''' + SQL_QUERY + '''
        ),
    )
'''),
    fixtures=[
        ("first-days", "visible", {"now": "2026-03-03T12:00:00Z", "outcome": "rendered",
                                   "columns": ["logical_date", "value"]}),
        ("one-interval-exactly", "hidden", {"now": "2026-03-02T00:00:00Z", "outcome": "rendered",
                                            "columns": ["logical_date", "value"]}),
        ("first-day-not-over", "edge", {"now": "2026-03-01T23:59:00Z", "outcome": "rendered",
                                        "columns": ["logical_date", "value"]}),
    ],
    exact_schema=["logical_date", "value"],
    hints=["Keep the SQL; change what schedule= receives.",
           "CronDataIntervalTimetable(\"0 0 * * *\", timezone=\"UTC\") makes daily intervals."],
    explanation=("With CronDataIntervalTimetable the run whose logical date is March 1 covers [March 1, March 2) and "
                 "starts at midnight on March 2, so a run only exists once its day is complete. The same SQL rendered "
                 "under CronTriggerTimetable reads from '2026-03-01' to '2026-03-01': nothing."),
    follow_ups=["What does the run for March 1 read if you keep @daily and write {{ macros.ds_add(ds, -1) }}?"],
    mutants=[
        code(SQL_HEAD + '''from airflow.timetables.trigger import CronTriggerTimetable

with DAG(
    dag_id="daily_sales_load",
    schedule=CronTriggerTimetable("0 0 * * *", timezone="UTC"),
    start_date=datetime(2026, 3, 1),
    catchup=True,
) as dag:
    SQLExecuteQueryOperator(
        task_id="load_day",
        conn_id="warehouse",
        sql=(
            ''' + SQL_QUERY + '''
        ),
    )
'''),
        code(SQL_HEAD + '''from airflow.timetables.interval import CronDataIntervalTimetable

with DAG(
    dag_id="daily_sales_load",
    schedule=CronDataIntervalTimetable("0 0 * * *", timezone="UTC"),
    start_date=datetime(2026, 3, 1),
    catchup=True,
) as dag:
    SQLExecuteQueryOperator(
        task_id="load_day",
        conn_id="warehouse",
        sql="INSERT INTO daily_sales SELECT * FROM sales WHERE sold_at >= '{{ ds }}' AND sold_at < '{{ ds }}'",
    )
'''),
    ],
)

# 7 ---------------------------------------------------------------------------
BASH_HEAD = '''
from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

with DAG(
    dag_id="partition_loader",
    schedule="@daily",
    start_date=datetime(2026, 3, 1),
    catchup=True,
) as dag:
'''
exercise(
    id="af-airflow3-previous-day-partition",
    title="Airflow 3 @daily: load yesterday's partition",
    difficulty="medium",
    topics=["templating", "macros", "scheduling"],
    prompt=("partition_loader keeps schedule=\"@daily\". The run triggered at midnight must load the partition of the "
            "day that just ended: the run with logical date 2026-03-05 loads dt=2026-03-04. Fix the templated "
            "command without changing the schedule."),
    sections=[
        ("Airflow 3 @daily", "A preset uses CronTriggerTimetable: the run triggered at 2026-03-05 00:00 has logical "
                             "date 2026-03-05, so {{ ds }} is 2026-03-05. Airflow 2's default gave it logical date "
                             "2026-03-04."),
        ("Graded", "The rendered bash_command of each run (catchup is on)."),
    ],
    outcome_note="rendered",
    starter=code(BASH_HEAD + '''    BashOperator(
        task_id="load_partition",
        bash_command="load_partition --table events --dt {{ ds }}",  # loads today's, still empty, partition
    )
'''),
    solution=code(BASH_HEAD + '''    BashOperator(
        task_id="load_partition",
        bash_command="load_partition --table events --dt {{ macros.ds_add(ds, -1) }}",
    )
'''),
    fixtures=[
        ("first-runs", "visible", {"now": "2026-03-02T12:00:00Z", "outcome": "rendered",
                                   "columns": ["logical_date", "value"]}),
        ("month-boundary", "hidden", {"now": "2026-04-01T00:30:00Z", "outcome": "rendered",
                                      "columns": ["logical_date", "value"]}),
        ("first-run-only", "edge", {"now": "2026-03-01T00:00:00Z", "outcome": "rendered",
                                    "columns": ["logical_date", "value"]}),
    ],
    exact_schema=["logical_date", "value"],
    hints=["macros.ds_add(ds, days) shifts a YYYY-MM-DD string by whole days."],
    explanation=("Under Airflow 3's default timetable, {{ ds }} is the trigger day. The day that just ended is "
                 "{{ macros.ds_add(ds, -1) }}, which also handles month boundaries (2026-04-01 loads 2026-03-31)."),
    follow_ups=["When is switching to CronDataIntervalTimetable and {{ data_interval_start | ds }} the better fix?"],
    mutants=[
        code(BASH_HEAD + '''    BashOperator(
        task_id="load_partition",
        bash_command="load_partition --table events --dt {{ macros.ds_add(ds, 1) }}",
    )
'''),
        code(BASH_HEAD + '''    BashOperator(
        task_id="load_partition",
        bash_command="load_partition --table events --dt {{ data_interval_start | ds }}",
    )
'''),
    ],
)

# 8 ---------------------------------------------------------------------------
RETRY_HEAD = '''
from datetime import datetime, timedelta

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

with DAG(dag_id="exchange_rates", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:
'''
exercise(
    id="af-retries-flaky-api",
    title="Retry a flaky API call",
    difficulty="easy",
    topics=["retries", "task-states"],
    prompt=("fetch_rates calls an API that sometimes fails for a few minutes. Give it at most 3 tries in total, "
            "10 minutes apart, so a transient outage does not fail the run. publish_rates runs after it."),
    sections=[
        ("Graded", "Task states, try numbers and end times (seconds after the run starts; every attempt takes 60 s) "
                   "when the API fails on the first two tries, when it never recovers, and on a normal day."),
    ],
    outcome_note="task instances",
    starter=code(RETRY_HEAD + '''    fetch = BashOperator(task_id="fetch_rates", bash_command="fetch_rates --day {{ ds }}")
    publish = BashOperator(task_id="publish_rates", bash_command="publish_rates --day {{ ds }}")
    fetch >> publish
'''),
    solution=code(RETRY_HEAD + '''    fetch = BashOperator(
        task_id="fetch_rates",
        bash_command="fetch_rates --day {{ ds }}",
        retries=2,
        retry_delay=timedelta(minutes=10),
    )
    publish = BashOperator(task_id="publish_rates", bash_command="publish_rates --day {{ ds }}")
    fetch >> publish
'''),
    fixtures=[
        ("recovers-on-third-try", "visible", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                              "columns": ["task_id", "state", "try_number", "end_s"],
                                              "tasks": {"fetch_rates": {"fail_attempts": [1, 2]}}}),
        ("never-recovers", "hidden", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                      "columns": ["task_id", "state", "try_number", "end_s"],
                                      "tasks": {"fetch_rates": {"fail_attempts": "all"}}}),
        ("normal-day", "edge", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                "columns": ["task_id", "state", "try_number", "end_s"]}),
    ],
    exact_schema=["task_id", "state", "try_number", "end_s"],
    hints=["retries counts retries, not tries: 3 tries means retries=2.",
           "retry_delay takes a timedelta."],
    explanation=("retries=2 allows try 1 plus two retries. Each failed try waits retry_delay before the next one, so "
                 "the third try starts at 60 + 600 + 60 + 600 = 1320 s and ends at 1380 s. When the API never "
                 "recovers, fetch_rates fails after its third try and publish_rates is upstream_failed."),
    follow_ups=["Why not set retries=10 to be safe?"],
    mutants=[
        code(RETRY_HEAD + '''    fetch = BashOperator(
        task_id="fetch_rates",
        bash_command="fetch_rates --day {{ ds }}",
        retries=3,
        retry_delay=timedelta(minutes=10),
    )
    publish = BashOperator(task_id="publish_rates", bash_command="publish_rates --day {{ ds }}")
    fetch >> publish
'''),
        code(RETRY_HEAD + '''    fetch = BashOperator(
        task_id="fetch_rates",
        bash_command="fetch_rates --day {{ ds }}",
        retries=2,
    )
    publish = BashOperator(task_id="publish_rates", bash_command="publish_rates --day {{ ds }}")
    fetch >> publish
'''),
        code(RETRY_HEAD + '''    fetch = BashOperator(
        task_id="fetch_rates",
        bash_command="fetch_rates --day {{ ds }}",
        retries=1,
        retry_delay=timedelta(minutes=10),
    )
    publish = BashOperator(task_id="publish_rates", bash_command="publish_rates --day {{ ds }}")
    fetch >> publish
'''),
    ],
)

# 9 ---------------------------------------------------------------------------
CLEAN_HEAD = '''
from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

with DAG(dag_id="staging_refresh", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:
    create_tmp = BashOperator(task_id="create_tmp", bash_command="create_tmp_tables")
    transform = BashOperator(task_id="transform", bash_command="run_transform --day {{ ds }}")
'''
exercise(
    id="af-cleanup-trigger-rule",
    title="A cleanup task that always runs",
    difficulty="easy",
    topics=["trigger-rules", "task-states"],
    prompt=("drop_tmp removes the temporary tables that create_tmp builds. It must run after transform whether "
            "transform succeeds or fails."),
    sections=[
        ("Graded", "Task states on a normal day, on a day when transform fails, and on a day when create_tmp fails."),
    ],
    outcome_note="task instances",
    starter=code(CLEAN_HEAD + '''    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables")
    create_tmp >> transform >> drop_tmp
'''),
    solution=code(CLEAN_HEAD + '''    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="all_done")
    create_tmp >> transform >> drop_tmp
'''),
    fixtures=[
        ("normal-day", "visible", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                   "columns": ["task_id", "state"]}),
        ("transform-fails", "hidden", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                       "columns": ["task_id", "state"],
                                       "tasks": {"transform": {"fail_attempts": "all"}}}),
        ("create-fails", "edge", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                  "columns": ["task_id", "state"],
                                  "tasks": {"create_tmp": {"fail_attempts": "all"}}}),
    ],
    exact_schema=["task_id", "state"],
    hints=["The default trigger rule all_success needs every upstream task to succeed."],
    explanation=("trigger_rule=\"all_done\" runs the task once every upstream task has finished, whatever its state. "
                 "When create_tmp fails, transform is upstream_failed, which also counts as finished, so drop_tmp "
                 "still runs."),
    follow_ups=["After this change the DAG run is marked success even when transform fails. Why? (see the watcher "
                "exercise)"],
    mutants=[
        code(CLEAN_HEAD + '''    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="one_success")
    create_tmp >> transform >> drop_tmp
'''),
        code(CLEAN_HEAD + '''    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="none_failed")
    create_tmp >> transform >> drop_tmp
'''),
        code(CLEAN_HEAD + '''    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="one_failed")
    create_tmp >> transform >> drop_tmp
'''),
    ],
)

# 10 --------------------------------------------------------------------------
WATCH_HEAD = '''
from datetime import datetime

from airflow.sdk import DAG, task
from airflow.providers.standard.operators.bash import BashOperator


@task
def watcher():
    raise RuntimeError("An upstream task failed; failing the DAG run on purpose.")


with DAG(dag_id="staging_refresh", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:
    create_tmp = BashOperator(task_id="create_tmp", bash_command="create_tmp_tables")
    transform = BashOperator(task_id="transform", bash_command="run_transform --day {{ ds }}")
    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="all_done")
    create_tmp >> transform >> drop_tmp
'''
exercise(
    id="af-watcher-fails-the-run",
    title="Watcher task: a failure must still fail the DAG run",
    difficulty="hard",
    topics=["trigger-rules", "dag-run-state"],
    prompt=("Because drop_tmp (all_done) is the only leaf and succeeds, the DAG run is marked success even when "
            "transform fails. Add the provided watcher task so that the run fails whenever any other task fails, "
            "and stays successful otherwise. watcher raises whenever it runs."),
    sections=[
        ("DAG run state", "Airflow sets the run state from its leaf tasks: failed if any leaf failed or is "
                          "upstream_failed, success otherwise."),
        ("Graded", "The DAG run state on a normal day, when transform fails, and when create_tmp fails. In every "
                   "scenario watcher fails when it runs."),
    ],
    outcome_note="runs",
    starter=code(WATCH_HEAD + '''    # Not wired yet: as a root task with all_success, watcher runs first and fails every run.
    watcher()
'''),
    solution=code(WATCH_HEAD + '''    [create_tmp, transform, drop_tmp] >> watcher.override(trigger_rule="one_failed")()
'''),
    fixtures=[
        ("normal-day", "visible", {"now": "2026-03-05T12:00:00Z", "outcome": "runs",
                                   "columns": ["logical_date", "state"],
                                   "tasks": {"watcher": {"fail_attempts": "all"}}}),
        ("transform-fails", "hidden", {"now": "2026-03-05T12:00:00Z", "outcome": "runs",
                                       "columns": ["logical_date", "state"],
                                       "tasks": {"watcher": {"fail_attempts": "all"},
                                                 "transform": {"fail_attempts": "all"}}}),
        ("create-fails", "edge", {"now": "2026-03-05T12:00:00Z", "outcome": "runs",
                                  "columns": ["logical_date", "state"],
                                  "tasks": {"watcher": {"fail_attempts": "all"},
                                            "create_tmp": {"fail_attempts": "all"}}}),
    ],
    exact_schema=["logical_date", "state"],
    hints=["watcher must be downstream of every task whose failure matters.",
           "Which trigger rule fires as soon as one upstream task has failed?"],
    explanation=("watcher is downstream of every task with trigger_rule=\"one_failed\": on a normal day it is "
                 "skipped (a skipped leaf keeps the run successful); when any task fails it runs, fails, and as a "
                 "failed leaf it fails the run. one_failed also counts upstream_failed tasks. Hanging watcher only under "
                 "drop_tmp does not work: drop_tmp succeeds even when transform fails."),
    follow_ups=["Why does all_failed not work here?"],
    mutants=[
        code(WATCH_HEAD + '''    [create_tmp, transform, drop_tmp] >> watcher.override(trigger_rule="all_failed")()
'''),
        code(WATCH_HEAD + '''    drop_tmp >> watcher.override(trigger_rule="one_failed")()
'''),
        code(WATCH_HEAD + '''    [create_tmp, transform, drop_tmp] >> watcher.override(trigger_rule="all_done")()
'''),
    ],
)

# 11 --------------------------------------------------------------------------
BRANCH_HEAD = '''
from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.python import BranchPythonOperator


def choose_load(**context):
    return "full_load" if context["logical_date"].day == 1 else "incremental_load"


with DAG(dag_id="warehouse_load", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:
    choose = BranchPythonOperator(task_id="choose", python_callable=choose_load)
    full = BashOperator(task_id="full_load", bash_command="load --full")
    incremental = BashOperator(task_id="incremental_load", bash_command="load --since {{ ds }}")
'''
exercise(
    id="af-branch-join",
    title="Join after a branch without skipping the join",
    difficulty="medium",
    topics=["branching", "trigger-rules"],
    prompt=("choose picks full_load or incremental_load; the other path is skipped. publish must run after "
            "whichever load ran, must not run if that load failed, and is skipped when choose selects nothing."),
    sections=[
        ("Branching", "A branch task skips its direct downstream tasks that it did not choose. With the default "
                      "all_success, a join after both paths sees one skipped upstream and is skipped too."),
        ("Graded", "Task states when choose selects incremental_load, when it selects full_load and full_load fails, "
                   "when it selects both loads and one fails, and when it selects no task."),
    ],
    outcome_note="task instances",
    starter=code(BRANCH_HEAD + '''    publish = BashOperator(task_id="publish", bash_command="publish_marts")
    choose >> [full, incremental] >> publish
'''),
    solution=code(BRANCH_HEAD + '''    publish = BashOperator(task_id="publish", bash_command="publish_marts",
                           trigger_rule="none_failed_min_one_success")
    choose >> [full, incremental] >> publish
'''),
    fixtures=[
        ("incremental-day", "visible", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                        "columns": ["task_id", "state"],
                                        "tasks": {"choose": {"branch": ["incremental_load"]}}}),
        ("full-load-fails", "hidden", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                       "columns": ["task_id", "state"],
                                       "tasks": {"choose": {"branch": ["full_load"]},
                                                 "full_load": {"fail_attempts": "all"}}}),
        ("both-chosen-one-fails", "hidden", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                             "columns": ["task_id", "state"],
                                             "tasks": {"choose": {"branch": ["full_load", "incremental_load"]},
                                                       "full_load": {"duration_seconds": 30},
                                                       "incremental_load": {"fail_attempts": "all"}}}),
        ("nothing-to-load", "edge", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                     "columns": ["task_id", "state"],
                                     "tasks": {"choose": {"branch": []}}}),
    ],
    exact_schema=["task_id", "state"],
    hints=["Look for the trigger rule that tolerates skipped upstream tasks but not failed ones, and needs at least "
           "one success."],
    explanation=("none_failed_min_one_success runs publish when no upstream failed and at least one succeeded: after "
                 "the chosen path. A failed load makes publish upstream_failed; if every upstream was skipped, publish "
                 "is skipped. none_failed would still run it when both paths were skipped, all_done would run it after a "
                 "failure, and one_success would start it as soon as one chosen load succeeded, even if another one "
                 "then failed."),
    follow_ups=["What if publish also depended directly on choose?"],
    mutants=[
        code(BRANCH_HEAD + '''    publish = BashOperator(task_id="publish", bash_command="publish_marts", trigger_rule="all_done")
    choose >> [full, incremental] >> publish
'''),
        code(BRANCH_HEAD + '''    publish = BashOperator(task_id="publish", bash_command="publish_marts", trigger_rule="none_failed")
    choose >> [full, incremental] >> publish
'''),
        code(BRANCH_HEAD + '''    publish = BashOperator(task_id="publish", bash_command="publish_marts", trigger_rule="one_success")
    choose >> [full, incremental] >> publish
'''),
    ],
)

# 12 --------------------------------------------------------------------------
SENSOR_HEAD = '''
from datetime import datetime, timedelta

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.sensors.filesystem import FileSensor

with DAG(dag_id="partner_feed", schedule="0 6 * * *", start_date=datetime(2026, 3, 5)) as dag:
'''
SENSOR_TAIL = '''    load = BashOperator(task_id="load_feed", bash_command="load_feed --day {{ ds }}")
    wait >> load
'''
exercise(
    id="af-sensor-soft-fail",
    title="A file sensor that gives up without failing the run",
    difficulty="hard",
    topics=["sensors", "timeouts", "soft-fail"],
    prompt=("wait_for_feed waits for a partner file. Check every 10 minutes, give up after 2 hours, and when the "
            "file never arrives end the run without a failure: the sensor and load_feed are skipped. Use reschedule "
            "mode so the sensor does not hold a worker slot between checks."),
    sections=[
        ("Sensor timing", "A sensor pokes at start, then every poke_interval. After a false poke, if more than "
                          "timeout seconds have passed it times out: failed (timeouts are not retried), or skipped "
                          "with soft_fail=True."),
        ("Graded", "States and end times (seconds after the run starts; load_feed takes 60 s) when the file arrives "
                   "after 50 minutes, when it never arrives, and when it arrives exactly at 2 hours. The mode does "
                   "not change these outcomes and is not graded."),
    ],
    outcome_note="task instances",
    starter=code(SENSOR_HEAD + '''    wait = FileSensor(task_id="wait_for_feed", filepath="/data/partner/{{ ds }}.csv")
''' + SENSOR_TAIL),
    solution=code(SENSOR_HEAD + '''    wait = FileSensor(
        task_id="wait_for_feed",
        filepath="/data/partner/{{ ds }}.csv",
        poke_interval=timedelta(minutes=10),
        timeout=timedelta(hours=2),
        mode="reschedule",
        soft_fail=True,
    )
''' + SENSOR_TAIL),
    fixtures=[
        ("arrives-after-50-min", "visible", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                             "columns": ["task_id", "state", "end_s"],
                                             "tasks": {"wait_for_feed": {"sensor_true_after_seconds": 3000}}}),
        ("never-arrives", "hidden", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                     "columns": ["task_id", "state", "end_s"]}),
        ("arrives-at-two-hours", "edge", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                          "columns": ["task_id", "state", "end_s"],
                                          "tasks": {"wait_for_feed": {"sensor_true_after_seconds": 7200}}}),
    ],
    exact_schema=["task_id", "state", "end_s"],
    hints=["poke_interval and timeout accept timedelta values.",
           "soft_fail=True turns a sensor timeout into a skip."],
    explanation=("With a 600 s poke interval the sensor sees the file at the poke at 3000 s. When the file never "
                 "arrives, the false poke at 7200 s is not yet past the 7200 s timeout, so the sensor times out at "
                 "the next false poke, at 7800 s, and soft_fail skips it and load_feed. The default timeout is 7 "
                 "days, and without soft_fail a timeout fails the run."),
    follow_ups=["When is poke mode the better choice?"],
    mutants=[
        code(SENSOR_HEAD + '''    wait = FileSensor(
        task_id="wait_for_feed",
        filepath="/data/partner/{{ ds }}.csv",
        poke_interval=timedelta(minutes=10),
        timeout=timedelta(hours=2),
        mode="reschedule",
    )
''' + SENSOR_TAIL),
        code(SENSOR_HEAD + '''    wait = FileSensor(
        task_id="wait_for_feed",
        filepath="/data/partner/{{ ds }}.csv",
        poke_interval=timedelta(minutes=5),
        timeout=timedelta(hours=2),
        mode="reschedule",
        soft_fail=True,
    )
''' + SENSOR_TAIL),
        code(SENSOR_HEAD + '''    wait = FileSensor(
        task_id="wait_for_feed",
        filepath="/data/partner/{{ ds }}.csv",
        poke_interval=timedelta(minutes=10),
        timeout=timedelta(hours=1),
        mode="reschedule",
        soft_fail=True,
    )
''' + SENSOR_TAIL),
    ],
)

# 13 --------------------------------------------------------------------------
DEFAULTS_HEAD = '''
from datetime import datetime, timedelta

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

'''
DEFAULTS_BODY = '''    extract = BashOperator(task_id="extract", bash_command="extract --day {{ ds }}")
    transform = BashOperator(task_id="transform", bash_command="transform --day {{ ds }}")
'''
exercise(
    id="af-default-args-override",
    title="default_args for every task, with one exception",
    difficulty="medium",
    topics=["default-args", "retries"],
    prompt=("Every task of billing_export should retry twice, 1 minute apart, through default_args. send_invoices "
            "is not idempotent: a retry would email customers twice, so it must never retry."),
    sections=[
        ("default_args", "default_args apply to every task in the DAG; an argument passed to an operator "
                         "overrides the default."),
        ("Graded", "States and try numbers when every task fails its first try, on a normal day, and when "
                   "send_invoices fails."),
    ],
    outcome_note="task instances",
    starter=code(DEFAULTS_HEAD + '''with DAG(
    dag_id="billing_export",
    schedule="@daily",
    start_date=datetime(2026, 3, 5),
    default_args={"retries": 2, "retry_delay": timedelta(minutes=1)},
) as dag:
''' + DEFAULTS_BODY + '''    send = BashOperator(task_id="send_invoices", bash_command="send_invoices --day {{ ds }}")
    extract >> transform >> send
'''),
    solution=code(DEFAULTS_HEAD + '''with DAG(
    dag_id="billing_export",
    schedule="@daily",
    start_date=datetime(2026, 3, 5),
    default_args={"retries": 2, "retry_delay": timedelta(minutes=1)},
) as dag:
''' + DEFAULTS_BODY + '''    send = BashOperator(task_id="send_invoices", bash_command="send_invoices --day {{ ds }}", retries=0)
    extract >> transform >> send
'''),
    fixtures=[
        ("first-tries-fail", "visible", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                         "columns": ["task_id", "state", "try_number"],
                                         "tasks": {"extract": {"fail_attempts": [1]}, "transform": {"fail_attempts": [1]},
                                                   "send_invoices": {"fail_attempts": [1]}}}),
        ("normal-day", "hidden", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                  "columns": ["task_id", "state", "try_number"]}),
        ("transform-needs-third-try", "edge", {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances",
                                               "columns": ["task_id", "state", "try_number"],
                                               "tasks": {"transform": {"fail_attempts": [1, 2]}}}),
    ],
    exact_schema=["task_id", "state", "try_number"],
    hints=["An operator argument overrides the same key in default_args."],
    explanation=("default_args gives extract and transform retries=2; retries=0 on send_invoices overrides it, so a "
                 "failed send is final (the run fails) instead of sending invoices again."),
    follow_ups=["How would you make send_invoices safe to retry instead?"],
    mutants=[
        code(DEFAULTS_HEAD + '''with DAG(
    dag_id="billing_export",
    schedule="@daily",
    start_date=datetime(2026, 3, 5),
    default_args={"retries": 0, "retry_delay": timedelta(minutes=1)},
) as dag:
''' + DEFAULTS_BODY + '''    send = BashOperator(task_id="send_invoices", bash_command="send_invoices --day {{ ds }}")
    extract >> transform >> send
'''),
        code(DEFAULTS_HEAD + '''with DAG(
    dag_id="billing_export",
    schedule="@daily",
    start_date=datetime(2026, 3, 5),
    default_args={"retries": 1, "retry_delay": timedelta(minutes=1)},
) as dag:
''' + DEFAULTS_BODY + '''    send = BashOperator(task_id="send_invoices", bash_command="send_invoices --day {{ ds }}", retries=0)
    extract >> transform >> send
'''),
    ],
)


# -----------------------------------------------------------------------------
def definition(spec: dict, rank: int) -> dict:
    by_visibility = {"visible": [], "hidden": [], "edge": []}
    for fid, visibility, _ in spec["fixtures"]:
        by_visibility[visibility].append(fid)
    sections = [{"title": "Simulator", "body": SIMULATOR}]
    sections += [{"title": title, "body": body} for title, body in spec["sections"]]
    validation = {
        "kind": "rows", "ordered": False, "duplicate_sensitive": True,
        "relative_tolerance": 1e-09, "absolute_tolerance": 1e-06,
        "required_columns": spec["exact_schema"] or [], "exact_schema": spec["exact_schema"],
        "forbidden_extra_columns": True, "null_semantics": "equal",
    }
    return {
        "schema_version": 1,
        "id": spec["id"],
        "version": "1",
        "title": spec["title"],
        "difficulty": spec["difficulty"],
        "topics": spec["topics"],
        "tags": ["airflow-lab", "airflow", "simulated"],
        "origin": "authored",
        "language": "airflow",
        "runtime": "datapass-airflow-sim-v1",
        "prompt": spec["prompt"],
        "sections": sections,
        "starter_source": spec["starter"],
        "fixtures": [{"id": f"{spec['id']}-fixtures", "version": "1"}],
        "visible_checks": [{"id": fid, "description": f"Simulated {spec['outcome_note']} for the public scenario."}
                           for fid in by_visibility["visible"]],
        "hidden_check_refs": by_visibility["hidden"],
        "edge_check_refs": by_visibility["edge"],
        "hints": spec["hints"],
        "solution": {"available": True, "reveal": "explicit"},
        "explanation": spec["explanation"],
        "follow_ups": spec["follow_ups"],
        "canonical_placement": {"domain": "airflow", "topic": spec["topics"][0]},
        "related_associations": ["airflow/orchestration"],
        "recommendation": {"rank": rank, "reason": "Airflow lab progression"},
        "validator_version": "rows-v2",
        "validation": validation,
        "runtime_requirements": ["airflow-simulator"],
        "provenance": {
            "source": "Authored for Datapass Workbench: Airflow 3 scheduling and task semantics on the Airflow Lab simulator",
            "fixtures": "Authored scenarios; expected rows computed by simulating the reference DAG and reviewed",
        },
        "constraints": {
            "truth": ("Simulated: the DAG file is parsed, never executed, and no Airflow scheduler, executor or "
                      "worker runs. Semantics follow Airflow 3 for the supported subset."),
        },
        "truth": "simulated",
    }


def main() -> None:
    from airflowlab.parser import parse_dag
    from airflowlab.simulate import Scenario, outcome_rows
    from datapass_runtime.exercise_packs import PackRegistry
    ids = [spec["id"] for spec in EXERCISES]
    assert len(ids) == len(set(ids))
    definitions, grading = [], {}
    for rank, spec in enumerate(EXERCISES, start=1):
        definitions.append(definition(spec, rank))
        dag = parse_dag(spec["solution"])
        parse_dag(spec["starter"])
        for mutant in spec["mutants"]:
            parse_dag(mutant)
        fixtures = []
        for fid, visibility, scenario in spec["fixtures"]:
            rows = outcome_rows(dag, Scenario.model_validate(scenario))
            fixtures.append({"id": fid, "visibility": visibility, "input_rows": [], "scenario": scenario,
                             "expected": rows})
        grading[spec["id"]] = {"solution": spec["solution"], "fixtures": fixtures}
    manifest = {
        "schema_version": 1, "id": "airflow-lab-v1", "version": "1",
        "title": "Airflow lab: scheduling, dependencies and task states (simulated Airflow 3)",
        "enabled": True,
        "provenance": {"source": "Authored for Datapass Workbench"},
    }
    PackRegistry().register(manifest, definitions, grading)
    PACK.mkdir(parents=True, exist_ok=True)
    for name, data in (("manifest.json", manifest), ("exercises.json", definitions), ("grading.server.json", grading)):
        (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_mutants(PACK, {spec["id"]: spec["mutants"] for spec in EXERCISES})
    for spec in EXERCISES:
        print(f"== {spec['id']}")
        for fixture in grading[spec["id"]]["fixtures"]:
            print(f"   {fixture['id']:26s}", json.dumps(fixture["expected"]))


if __name__ == "__main__":
    main()
