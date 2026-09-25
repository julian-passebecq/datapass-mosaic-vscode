"""Nightly dbt build of the daily models. Airflow 3's @daily runs at midnight with the logical date of that
midnight, so each run loads the day that just ended; catchup replays the nights the scheduler missed."""
from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

with DAG(
    dag_id="dbt_daily",
    schedule="@daily",
    start_date=datetime(2026, 3, 11),
    catchup=True,
    max_active_runs=1,
    tags=["dbt"],
) as dag:
    BashOperator(
        task_id="dbt_build_daily",
        bash_command="cd missions/backfill-daily-sales && dbt build --select tag:daily --vars '{run_date: {{ macros.ds_add(ds, -1) }}}'",
    )
