"""Reference answer: the daily retail load at 06:00 UTC, caught up since start_date, with retries."""
from datetime import datetime, timedelta

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.providers.standard.sensors.filesystem import FileSensor

with DAG(
    dag_id="retail_daily_load",
    schedule="0 6 * * *",
    start_date=datetime(2026, 3, 1),
    catchup=True,
) as dag:
    wait_for_web_orders = FileSensor(
        task_id="wait_for_web_orders",
        filepath="/exports/web_orders_{{ ds }}.csv",
        poke_interval=timedelta(minutes=5),
        timeout=timedelta(hours=2),
        mode="reschedule",
    )
    run_fabric_pipeline = BashOperator(
        task_id="run_fabric_pipeline",
        bash_command="trigger_fabric_pipeline pl_retail_daily --run-date {{ ds }}",
        retries=2,
        retry_delay=timedelta(minutes=10),
    )
    dbt_build = BashOperator(task_id="dbt_build", bash_command="dbt build --select +fct_sales")
    publish = EmptyOperator(task_id="publish")

    wait_for_web_orders >> run_fabric_pipeline >> dbt_build >> publish
