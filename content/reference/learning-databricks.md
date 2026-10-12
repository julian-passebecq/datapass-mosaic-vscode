# Databricks

Cheatsheet for the Learning path *Spark and the data platforms*; compute details are in `databricks-compute.md`
and Unity Catalog in `unity-catalog.md`. The Cloud Lab's Databricks tab simulates jobs and compute (lab DBU figures);
notebook tasks run on SparkLab and SQL tasks on local DuckDB. Nothing connects to Databricks.

## Jobs (Lakeflow Jobs)

| Piece | Remember |
|---|---|
| Task | notebook, Python script, SQL, dbt, pipeline, or `for_each_task` over inputs |
| `depends_on` | draws the DAG; `run_if` (`ALL_SUCCESS`, `AT_LEAST_ONE_FAILED`, `ALL_DONE`...) sets when a task runs |
| `job_clusters` | one cluster per run shared by tasks via `job_cluster_key`; cheaper than all-purpose |
| Task values | `dbutils.jobs.taskValues.set/get` pass small values between tasks |
| Job parameters | `{{job.start_time.iso_date}}` and friends make a run date follow the run |
| Retries | `max_retries`, `min_retry_interval_millis`, `retry_on_timeout`, `timeout_seconds` |

## Delta and the medallion layers

- Delta table = Parquet files + `_delta_log` of JSON commits: atomic writes, time travel, `MERGE`, schema enforcement.
- `OPTIMIZE` compacts small files; `VACUUM` deletes unreferenced files older than the retention (7 days by default).
- **Liquid clustering** (`CLUSTER BY`) replaces partitioning and `ZORDER`; keys can change without rewriting data.
- Bronze = raw as ingested, silver = cleaned and conformed, gold = business aggregates and models.
- **Auto Loader** (`cloudFiles`) ingests new files incrementally and remembers which were processed.

## Lakeflow Declarative Pipelines (formerly Delta Live Tables)

| Expectation | Effect |
|---|---|
| `EXPECT (cond)` | keep invalid rows, count them in metrics |
| `... ON VIOLATION DROP ROW` | drop invalid rows, count them |
| `... ON VIOLATION FAIL UPDATE` | stop the update |

## Engines and compute

- **Photon**: vectorized C++ engine for Spark SQL and DataFrames; unsupported operations fall back to Spark.
- SQL warehouses serve BI tools; job compute serves schedules; all-purpose clusters serve people.
