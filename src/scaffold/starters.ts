/** Starter files written by the Workbench. Pure so smoke/E2E tests run the exact text. */
import type { ScratchKind } from "../webview/contracts";

export function scratchSpec(kind: ScratchKind): { fileName: string; content: string } {
  switch (kind) {
    case "sql":
      return {
        fileName: "mosaic.sql",
        content: "-- Datapass Mosaic SQL scratch\n-- Run locally with DuckDB / DuckLake.\n\nselect 1 as datapass_ready;\n"
      };
    case "python":
      return {
        fileName: "mosaic.py",
        content: [
          "# Datapass Mosaic Python scratch",
          "# Runs as real local Python only after you enable trusted local Python for this workspace.",
          "# Relative paths resolve from the workspace root. print() output is captured and",
          "# the last expression is previewed in Mosaic.",
          "import polars as pl",
          "",
          "df = pl.DataFrame({\"value\": [1, 2, 3]})",
          "print(df.shape)",
          "df",
          ""
        ].join("\n")
      };
    case "sparklab":
      return {
        fileName: "sparklab.py",
        content: [
          "# Datapass SparkLab scratch: bounded PySpark-style DataFrame API.",
          "# Parsed by a whitelist AST interpreter and compiled to local SQL. It is never",
          "# executed as Python and needs no trusted-Python opt-in. Results are computed",
          "# locally from the shared catalog; stages, shuffle and credits are SIMULATED.",
          "from pyspark.sql import functions as F",
          "",
          "orders = spark.table(\"source.orders\")",
          "revenue = orders.filter(F.col(\"net_amount\") > 0).groupBy(\"customer_id\").agg(F.sum(\"net_amount\").alias(\"revenue\"))",
          ""
        ].join("\n")
      };
    case "notes":
      return {
        fileName: "mosaic.md",
        content: "# Mosaic notes\n\nUse this file for dataset grain, assumptions, checks and observations.\n"
      };
  }
}

export function pipelineStarter(): string {
  return [
    'pipeline("retail_quality", schedule="@daily")',
    'extract = sql("extract", "CREATE OR REPLACE TABLE bronze.sample AS SELECT 1 AS id")',
    'check = quality("check", "SELECT * FROM bronze.sample WHERE id IS NULL", retries=1, retry_delay=1)',
    'publish = sql("publish", "SELECT COUNT(*) AS rows FROM bronze.sample")',
    "extract >> check >> publish",
    ""
  ].join("\n");
}

/** Airflow Lab starter: a real Airflow 3 DAG file. Datapass parses and simulates it; it never runs it. */
export function airflowStarter(): string {
  return [
    '"""Airflow Lab starter DAG (Airflow 3).',
    "",
    "Datapass parses this file and simulates it (Airflow Lab -> Simulate active DAG file).",
    "Nothing in it is executed: task behavior comes from the Lab's scenario form.",
    '"""',
    "from datetime import datetime, timedelta",
    "",
    "from airflow.sdk import DAG",
    "from airflow.providers.standard.operators.bash import BashOperator",
    "from airflow.providers.standard.operators.empty import EmptyOperator",
    "from airflow.providers.standard.operators.python import BranchPythonOperator",
    "from airflow.providers.standard.sensors.filesystem import FileSensor",
    "",
    "",
    "def choose_load(**context):",
    '    return "incremental_load"',
    "",
    "",
    "with DAG(",
    '    dag_id="retail_daily",',
    '    schedule="@daily",',
    "    start_date=datetime(2026, 3, 1),",
    "    catchup=False,",
    '    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},',
    ") as dag:",
    "    wait_for_orders = FileSensor(",
    '        task_id="wait_for_orders",',
    '        filepath="/data/orders/{{ ds }}.csv",',
    "        poke_interval=timedelta(minutes=5),",
    "        timeout=timedelta(hours=1),",
    '        mode="reschedule",',
    "        soft_fail=True,",
    "    )",
    '    choose = BranchPythonOperator(task_id="choose_load", python_callable=choose_load)',
    '    full_load = BashOperator(task_id="full_load", bash_command="load_orders --all")',
    '    incremental_load = BashOperator(task_id="incremental_load", bash_command="load_orders --day {{ ds }}")',
    '    publish = EmptyOperator(task_id="publish", trigger_rule="none_failed_min_one_success")',
    '    cleanup = BashOperator(task_id="cleanup", bash_command="rm -rf /tmp/orders/{{ ds }}", trigger_rule="all_done")',
    "",
    "    wait_for_orders >> choose >> [full_load, incremental_load] >> publish >> cleanup",
    ""
  ].join("\n");
}
