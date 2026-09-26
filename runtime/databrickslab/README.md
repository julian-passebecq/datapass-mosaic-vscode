# Databricks Lab (databrickslab)

A local, deterministic simulator of Azure Databricks for learning: jobs, compute,
Unity Catalog and MLflow. Nothing connects to Azure Databricks.

## Truth model

| Part | What happens |
| --- | --- |
| Jobs | Jobs API JSON (`factory/databricks/jobs/<name>.json`) validated with Databricks' design-time rules and simulated on a logical clock: `depends_on`, `run_if` (ALL_SUCCESS, AT_LEAST_ONE_SUCCESS, NONE_FAILED, ALL_DONE, AT_LEAST_ONE_FAILED, ALL_FAILED), If/else condition tasks and their `outcome` branches, for each tasks with `concurrency`, `max_retries`, `min_retry_interval_millis`, `retry_on_timeout`, `timeout_seconds`, job parameters and dynamic value references. |
| Run status | Task states: Succeeded, Failed, Timed out, Upstream failed, Excluded. The run is Succeeded, Succeeded with failures (a task failed but every leaf task succeeded or was excluded) or Failed (a leaf task failed), as Databricks decides it from the leaf tasks. |
| Notebook tasks | Run on SparkLab's whitelisted interpreter (never eval/exec) against the local catalog: `spark.table`, DataFrame API, `saveAsTable`, `spark.sql`, `dbutils.widgets`, `dbutils.jobs.taskValues`, `dbutils.notebook.exit`, the bounded `pyspark.ml` subset (see `sparklab/ml.py`) and MLflow (see `sparklab/mlflow_api.py`). |
| SQL tasks | The task's `.sql` file runs on DuckDB (the SQL warehouse is simulated); `:name` parameters are bound as text and `{{tasks.<t>.output.first_row.<col>}}` / `.rows` are available downstream. |
| Unity Catalog | One catalog, `main`; schemas are the lab's layers plus `ml` (models). Owners, grants from `grants.sql` and groups from `unity_catalog.json`; every read and write of a job running `run_as` a principal is checked (USE CATALOG, USE SCHEMA, SELECT, MODIFY, CREATE TABLE, CREATE MODEL, EXECUTE, ownership). Row filters, column masks (SQL UDFs) and column tags from `grants.sql` are enforced for real on SQL tasks ("Unity Catalog row filters and column masks translated to DuckDB, not Databricks", see `governance.py`). |
| MLflow | Experiments, runs (params, metrics, tags, logged models) and a Unity Catalog model registry (three-level names, versions, aliases, signature required) kept as data in `databricks_state.json`. |
| Compute | Modelled: job clusters, all-purpose clusters (`compute.json`), serverless compute and SQL warehouses. Start times and DBU rates are teaching values; the cost is in lab units whose order is real (all-purpose costs more per DBU than jobs compute; an all-purpose cluster keeps billing while idle until auto-termination). The Azure VM bill is not counted; Photon is recorded, not modelled. |

Job parameters are pushed down to notebook tasks as widgets and win over a task
parameter with the same key. Parameter values are text. Dynamic value references
(`{{job.parameters.x}}`, `{{job.start_time.iso_date}}`, `{{job.run_id}}`,
`{{tasks.<t>.values.<k>}}`, `{{tasks.<t>.result_state}}`, `{{input}}`, ...) are
resolved in task parameters, condition operands and for each inputs; an unknown
namespace stays literal text, an invalid reference in a known namespace fails the task.
If/else conditions compare as text with `==`/`!=` and as numbers with the other operators.

A dry run (`data_plane: simulated`) runs no notebook or SQL; the scenario can set
task values for it.

## Lab files

Under `factory/databricks/`:

- `<path>.py` notebooks in Databricks source format (`# Databricks notebook source`,
  `# COMMAND ----------`); `/Workspace/Shared/x` in a job is `factory/databricks/Shared/x.py`;
- `<path>.sql` files for SQL tasks;
- `jobs/<name>.json`: jobs;
- `compute.json`: all-purpose clusters and SQL warehouses of the workspace;
- `unity_catalog.json`: groups and their members;
- `grants.sql`: `GRANT`, `REVOKE` and `ALTER ... OWNER TO` statements, SQL UDFs, row filters, column masks and
  column tags, applied before each run.

## Row filters, column masks and tags (`governance.py`)

`CREATE [OR REPLACE] FUNCTION main.<schema>.<name>(<param> <TYPE>, ...) [RETURNS <TYPE>] RETURN <expression>`
(one expression over the parameters: no subquery), `ALTER TABLE <t> SET ROW FILTER <function> ON (<columns>)` /
`DROP ROW FILTER`, `ALTER TABLE <t> ALTER COLUMN <c> SET MASK <function> [USING COLUMNS (...)]` / `DROP MASK`,
and `ALTER TABLE <t> ALTER COLUMN <c> SET TAGS ('key' = 'value', ...)` / `UNSET TAGS ('key', ...)`.
`is_account_group_member('<group>')`, `is_member('<group>')` and `current_user()` are resolved for the principal
(groups from `unity_catalog.json`); the body is Spark SQL translated to DuckDB by the shared translator. A SQL
task's statements read filtered and masked tables through a derived table built for the job's `run_as`
principal; filters and masks apply to every principal, you included, unless the function exempts it. Notebook
reads of a filtered or masked table are refused (query it from a SQL task). Practice adds two outcomes:
`principal_rows` (read-only queries run as each principal) and `pii` (for every column tagged `pii`, whether the
principal sees none of its non-null values unchanged).

Jobs without `run_as` run as you (`you@datapass.lab`), the workspace admin who owns
the objects that already exist; a table a principal creates is owned by it.

## Not simulated

Other task types (Python scripts, wheels, JARs, pipelines, Run Job, dbt), Git
sources, Delta Live Tables / Lakeflow pipelines, streaming, job repair and queueing,
cluster policies, secrets, volumes, row filters and column masks in notebooks, ABAC policies, model serving,
feature engineering, pandas and scikit-learn in notebooks.
