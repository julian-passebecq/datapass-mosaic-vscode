export interface RetailDemoPaths {
  dataset: string;
  sqlNotebook: string;
  pythonNotebook: string;
  pipeline: string;
  airflow: string;
  dbtProject: string;
}

export function retailOrdersCsv(): string {
  return [
    "order_id,customer_id,order_date,amount,status",
    "1001,C001,2026-09-01,420.00,completed",
    "1002,C002,2026-09-01,275.00,completed",
    "1003,C001,2026-09-02,-10.00,refund",
    "1004,C003,2026-09-02,980.00,completed",
    "1005,C004,2026-09-03,0.00,cancelled",
    "1006,C002,2026-09-03,315.00,completed",
    "1007,C005,2026-09-04,1250.00,completed",
    "1008,C003,2026-09-04,640.00,completed",
    "1009,C004,2026-09-05,310.00,completed",
    "1010,C005,2026-09-05,795.00,completed",
    ""
  ].join("\n");
}

export function retailSqlStarter(datasetPath: string): string {
  const sqlPath = datasetPath.replaceAll("'", "''");
  return [
    "-- Datapass retail medallion starter",
    "-- Goal: raw CSV -> bronze -> silver -> gold using DuckDB/DuckLake concepts.",
    "",
    "create or replace table bronze_orders as",
    `select * from read_csv_auto('${sqlPath}');`,
    "",
    "create or replace table silver_orders as",
    "select *",
    "from bronze_orders",
    "where amount > 0 and status = 'completed';",
    "",
    "create or replace table gold_customer_revenue as",
    "select customer_id, count(*) as orders, sum(amount) as revenue",
    "from silver_orders",
    "group by customer_id",
    "order by revenue desc;",
    "",
    "select * from gold_customer_revenue;",
    ""
  ].join("\n");
}

export function retailPythonStarter(datasetPath: string): string {
  const pythonPath = JSON.stringify(datasetPath);
  return [
    "import polars as pl",
    "",
    `orders = pl.read_csv(${pythonPath})`,
    "silver = orders.filter((pl.col('amount') > 0) & (pl.col('status') == 'completed'))",
    "quality = silver.select(",
    "    pl.len().alias('rows'),",
    "    pl.col('customer_id').n_unique().alias('customers'),",
    "    pl.col('amount').sum().alias('revenue'),",
    ")",
    "print(quality)",
    ""
  ].join("\n");
}

export function retailDemoReadme(paths: RetailDemoPaths): string {
  return [
    "# Datapass Retail End-to-End Demo",
    "",
    "This workspace is intentionally small but connected.",
    "",
    "## Flow",
    "",
    `1. ${paths.dataset} — raw source rows.`,
    `2. ${paths.sqlNotebook} — Bronze/Silver/Gold SQL transformations.`,
    `3. ${paths.pythonNotebook} — Polars quality/KPI check.`,
    `4. ${paths.pipeline} — local orchestration design.`,
    `5. ${paths.airflow} — deterministic scheduling/retry simulation.`,
    `6. ${paths.dbtProject} — real dbt + DuckDB sample when dbt is installed.`,
    "",
    "Use Fabric Lab to understand the overall workflow, then move into Mosaic, SparkLab, Pipeline Lab, Airflow Lab and dbt Lab for the specialist views.",
    "",
    "Truth boundary: DuckDB/Polars/dbt are real local execution where available; Fabric orchestration, Airflow scheduling and Spark distributed behavior are explicitly simulated.",
    ""
  ].join("\n");
}
