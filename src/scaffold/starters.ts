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

export function airflowStarter(): string {
  return JSON.stringify({
    schemaVersion: 1,
    dagId: "retail_daily",
    schedule: "@daily",
    tasks: [
      {
        id: "wait_for_orders",
        label: "Wait for orders",
        type: "sensor",
        dependsOn: [],
        retries: 0,
        retryDelaySeconds: 0,
        durationSeconds: 2,
        triggerRule: "all_success",
        failureMode: "none"
      },
      {
        id: "extract",
        label: "Extract orders",
        type: "task",
        dependsOn: ["wait_for_orders"],
        retries: 1,
        retryDelaySeconds: 5,
        durationSeconds: 4,
        triggerRule: "all_success",
        failureMode: "none"
      },
      {
        id: "check_quality",
        label: "Check data quality",
        type: "quality",
        dependsOn: ["extract"],
        retries: 1,
        retryDelaySeconds: 3,
        durationSeconds: 2,
        triggerRule: "all_success",
        failureMode: "transient"
      },
      {
        id: "publish",
        label: "Publish gold",
        type: "task",
        dependsOn: ["check_quality"],
        retries: 0,
        retryDelaySeconds: 0,
        durationSeconds: 3,
        triggerRule: "all_success",
        failureMode: "none"
      }
    ]
  }, null, 2) + "\n";
}
