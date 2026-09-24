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
  // Mosaic SQL runs on the shared catalog; filesystem/network table functions
  // (read_csv_auto, read_parquet, ...) are blocked by design. The CSV is loaded
  // into bronze.orders by the retail demo run, so this notebook starts there.
  const commentPath = datasetPath.replace(/[\r\n]+/g, " ");
  return [
    "-- Datapass retail medallion (DuckDB SQL on the shared local catalog)",
    `-- 1. Fabric Lab -> Run retail demo loads ${commentPath} into bronze.orders.`,
    "--    Mosaic SQL cannot read files directly: file and network table functions are blocked.",
    "-- 2. Mosaic -> Run active SQL builds your own Silver/Gold tables from bronze.orders.",
    "",
    "create or replace table silver.mosaic_orders as",
    "select *",
    "from bronze.orders",
    "where amount > 0 and status = 'completed';",
    "",
    "create or replace table gold.mosaic_customer_revenue as",
    "select customer_id, count(*) as orders, sum(amount) as revenue",
    "from silver.mosaic_orders",
    "group by customer_id;",
    "",
    "select * from gold.mosaic_customer_revenue order by revenue desc;",
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
    `2. ${paths.sqlNotebook} — Silver/Gold SQL built on bronze.orders (run the retail demo first; Mosaic SQL does not read files directly).`,
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
