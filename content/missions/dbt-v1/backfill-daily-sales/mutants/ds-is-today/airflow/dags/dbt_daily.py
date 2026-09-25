from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

with DAG(dag_id="dbt_daily", schedule="@daily", start_date=datetime(2026, 3, 11), catchup=True) as dag:
    BashOperator(
        task_id="dbt_build_daily",
        bash_command="cd missions/backfill-daily-sales && dbt build --select tag:daily --vars '{run_date: {{ ds }}}'",
    )
