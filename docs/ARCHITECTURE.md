# Architecture

## Product boundary

Datapass Workbench is a teaching product hosted inside VS Code. It teaches modern data-engineering workflows without requiring Fabric, Databricks, Airflow or a Spark cluster.

### Keep real

- VS Code editor, Explorer, tabs, split views, terminal and Git.
- Microsoft Python and Jupyter extensions.
- Polars.
- DuckDB / DuckLake.
- dbt Core + dbt-duckdb where practical.
- Workspace files.

### Simulate

- Fabric-style notebook/lakehouse UI and orchestration semantics.
- Spark session/DataFrame behavior for targeted PySpark exercises.
- Airflow scheduler/executor state.
- Fabric/Data Factory-style pipeline service.
- Stored-procedure activities when no server database exists.

## One runtime, multiple teaching UIs

FastAPI is the local IPC/control plane between VS Code/webviews and Python data tooling. It is **not** a fake FastAPI product.

```text
React / Fluent / React Flow views
             │
             ▼
       FastAPI runtime
       ├─ DuckDB/DuckLake
       ├─ Polars
       ├─ SparkLab
       ├─ workflow engine
       ├─ Airflow simulator
       └─ dbt adapter
```

## Mosaic

Mosaic is the free-form local workbench. Default execution is real DuckDB SQL; Python/Polars run for real only after the trusted-local-Python opt-in. It can arrange code/data/charts/docs in flexible panes, while source files remain real VS Code files. Spark simulation is optional, not Mosaic's identity.

Layout durability: inside a Datapass project the block geometry is saved to `.datapass/mosaic.json` (`schemaVersion: 1`, block ids + grid positions only; no source, paths, runtime state or secrets). The host validates every save (known blocks, bounded integers, clamped to 12 columns) and never creates the file outside a project. Missing blocks are completed from defaults; corrupt files or unknown schema versions fall back to the default layout without being overwritten until the next drag/resize. A layout that previously lived only in webview state is migrated once. Without a project the layout stays in webview state for the window only.

## Practice

Practice is the LeetCode-style layer: select challenge, open starter file in native VS Code, run local tests, show pass/fail/hints/explanation/review status.

## Cloud Lab (module id `fabric`, formerly Fabric Lab)

Cloud Lab is separate from Mosaic. Its **Pipelines** tab is the Factory Lab (`runtime/factorylab`): real pipeline JSON for Microsoft Fabric Data Factory, Azure Data Factory and Azure Synapse. The files are read from `factory/` in each product's git layout, with notebooks under `fabric/*.Notebook`, `databricks/` and `synapse/notebook/`, and procedures under `sql/procedures/`.

- The loader validates the documents with design-time rules:
  - activity availability per product, naming the equivalent;
  - required settings;
  - sibling-only dependencies, cycles and loop nesting;
  - declared parameters and variables;
  - `activity()` readable only from ancestors.
- The simulator orchestrates deterministically: dependency conditions, skip propagation, the leaf rule for the run status, retries and timeouts, Inactive activities, ForEach/If/Switch/Until/Filter, variables, and Execute/Invoke pipeline. Expressions go through a bounded parser.
- Through `datapass_runtime/factory_workspace.py`, Copy, Lookup, Script and stored procedures run on the shared catalog. Notebooks run on SparkLab in *pipeline notebook* mode: parameters cell injection, `dbutils.widgets`, `saveAsTable` save modes, `spark.sql`, `count()` and `notebook.exit`. Nothing is eval'd or exec'd.
- Every other activity follows the scenario. A dry run simulates all of them.
- The host sends the pipeline and the files it references with each run (`POST /api/local/factory/simulate`, kernel op `factory_simulate`). The webview renders the canvas from its own parse of the JSON, so the canvas shows even when the runtime is stopped.

The **SQL pool** tab is the SQL pool Lab (`runtime/sqlpoollab`): a simulated Azure Synapse dedicated SQL pool and Microsoft Fabric Data Warehouse.

- `tsql.py` splits scripts (`;`, `GO` batches; a procedure takes its batch) and translates a documented T-SQL subset to DuckDB SQL. Nothing is eval'd; every data statement still goes through the catalog's SQL validation (`datapass_runtime/sqlpool_database.py`), so file and network functions stay blocked.
- `engine.py` runs statements one by one and keeps table designs (distribution, index, partitions, CLUSTER BY, constraints, statistics, scale) in `sqlpool.json` next to the catalog. Platform rules are enforced per flavor with the platform's messages.
- `physical.py` models the 60 distributions (skew), partitions and columnstore rowgroups from the real rows; `planner.py` decides the data movement of a SELECT from DuckDB's parse tree (`json_serialize_sql`).
- The host reads scripts from `factory/sql/pool/` (an open editor wins) or the active `.sql` editor and sends the text (`POST /api/local/sqlpool/run`, kernel op `sqlpool_run`). The webview shows statements, plans, the distribution chart and partitions.
- Practice language `sqlpool` grades scripts on an isolated temporary catalog (`datapass_runtime/sqlpool_grading.py`).

The **Databricks** tab is the Databricks Lab (`runtime/databrickslab`, README there):

- `model.py` reads Jobs API JSON with design-time rules (task types, dependencies and cycles, If/else outcomes, compute
  references, parameters); `engine.py` runs the job on a logical clock: `run_if`, Excluded and Upstream failed, retries
  and timeouts, If/else, for each, job parameters pushed down as widgets, dynamic value references (`refs.py`), task
  values, and the leaf-task rule for the run status.
- `compute.py` models job clusters, all-purpose clusters, serverless and SQL warehouses (start times, DBU, lab cost
  units); `unity.py` holds the Unity Catalog model (catalog `main`, layers as schemas, owners, grants, privilege checks);
  `mlflow_store.py` the MLflow tracking and Unity Catalog registry state.
- `datapass_runtime/databricks_workspace.py` runs notebook tasks on SparkLab (with `dbutils.jobs.taskValues`, the
  bounded `pyspark.ml` of `sparklab/ml.py` and the MLflow API of `sparklab/mlflow_api.py`) and SQL tasks on DuckDB,
  checking every read and write for the job's principal; state persists in `databricks_state.json`.
- The host sends the job and the files it needs (`POST /api/local/databricks/run`, kernel op `databricks_run`;
  `/api/local/databricks/state` for the explorer).

The **BI Lab** module (`bi`, `runtime/bilab`, README there) teaches data warehousing without pipelines:

- `script.py` splits warehouse scripts into statements with their line numbers and runs each one through the catalog's
  SQL contract on DuckDB; a script stops at its first error.
- `lineage.py` parses the same SQL with sqlglot (DuckDB dialect), qualifies it against the catalog's columns and
  resolves every written column through CTEs, subqueries, UNION branches and window functions to its source columns;
  WHERE/JOIN/GROUP BY/HAVING/QUALIFY and MERGE conditions are row influence. `impact()` follows both to answer "what
  does a change to this column reach". Nothing is executed for lineage.
- `model.py` validates the star model file (`bi/model.json`: roles, keys, grain, SCD settings, relationships with
  cardinality, cross-filter direction and active flag) and runs its checks as real queries (key uniqueness, grain,
  SCD2 validity, orphans, 'one' side uniqueness, one active path, bridges and cross-filtering).
- The host sends the scripts of `bi/warehouse/` (name order; open editors win) and the model (`POST /api/local/bi/lab`,
  kernel op `bi_lab`); the webview (`BiSurface.tsx`) shows statements, tables, the star, the checks, column lineage,
  impact analysis and a concepts sheet linked to the exercises.
- Practice languages `warehouse` (a SQL script) and `bi-model` (a model file) grade on an isolated temporary catalog
  (`datapass_runtime/warehouse_grading.py`), with outcomes result, table, checks, relationships, lineage and impact.

The BI Lab's **dbt** tab runs `bi/dbt/` with the Datapass dbt emulation (`runtime/dbtlab`, README there):

- `project.py` reads `dbt_project.yml`, property files, sources, models, seeds, snapshots, tests and macros, and
  renders every node once in parse mode (is_incremental() false) to find its refs and sources, as dbt parses.
- `render.py` renders project Jinja in jinja2's `SandboxedEnvironment` with a dbt context (ref, source, config, var,
  this, is_incremental, target, macros); packages, env_var, run_query and adapter calls fail explicitly.
- `engine.py` compiles (ephemeral CTE injection) and runs build/run/test/seed/snapshot with dbt-duckdb's
  materializations (view, table, incremental with delete+insert, append or merge, ephemeral), seeds, snapshots
  (timestamp and check, hard deletes, dbt_valid_to_current), generic and singular tests, selection and dbt build's
  test gating, on the shared catalog.
- `lab.py` adds the column lineage of the compiled models through `bilab.lineage`; the route is
  `POST /api/local/bi/dbt` (kernel op `bi_dbt`). Practice languages `dbt-sql` and `dbt-yml` grade one project
  file on an isolated catalog (`datapass_runtime/dbt_project_grading.py`).
- `scripts/dbt_oracle_smoke.py` runs the same projects through real dbt Core + dbt-duckdb and compares node
  statuses and every table; `scripts/authoring/gen_dbt.py` cross-checks each exercise fixture the same way.

The **Lakehouse and notebooks** tab keeps the original workflow of lakehouse + notebook + pipeline, reproduced locally:

- Fabric-inspired notebook surface.
- Lakehouse explorer backed by DuckDB/DuckLake.
- SparkLab kernel for PySpark practice.
- SQL endpoint concepts backed by DuckDB.
- React Flow pipeline canvas.
- Notebook, SQL, copy and stored-procedure-like activities.
- Run history, activity states and logs.

It does not connect to Microsoft Fabric by default.

## SparkLab / ZilaCode

SparkLab implements an explicit subset of the PySpark DataFrame API and maps supported operations to local execution. Unsupported distributed semantics must be shown clearly rather than silently approximated.

Direct workflow: the learner edits a native `.py` file (e.g. `notebooks/sparklab.py`) and chooses **Run active SparkLab file**. The source is parsed by the whitelist `SafeSparkParser` (never eval/exec'd, no trusted-Python opt-in needed), compiled to SQL and computed locally on the shared catalog. The UI separates:

- result rows and compiled SQL — real local computation;
- logical plan — structured teaching plan;
- stages, shuffle, spill, virtual duration and Datapass Credits — simulated for the selected virtual cluster profile/AQE setting, labeled as such, never presented as Spark telemetry.

Unsupported syntax (SQL-string filters, arbitrary imports, file access, ...) is rejected with a `SparkLabSyntaxError`.

Shuffle exchanges are placed by Spark's planning rules (`runtime/sparklab/physical.py`, model `plan-driven-v2`): an operator whose required clustering is already satisfied by an existing hash partitioning adds no exchange, a broadcast join keeps the streamed side's partitioning, a broadcast above 8 GB is refused, and Catalyst's EliminateSorts drops a sort under a join or an order-insensitive aggregate. The resulting `plan_facts` (exchanges and their reasons, join strategies, windows without `partitionBy`, output partitions) feed the SparkLab panel and Practice **plan checks**: a SparkLab exercise can declare `spark_plan` limits that are graded on the modeled plan at authored input sizes, next to the real result-row checks. Plan checks are labeled as the SparkLab model, not Apache Spark.

## Trusted local Python

Python/Polars files are real local code. The runtime worker is a separate process for lifecycle management (timeouts, restarts) and is **not** a security sandbox. Trusted Python is therefore effective only when all of these hold:

1. `.datapass/project.json` sets `runtime.trustedLocalPython: true` (default `false`; portable and reviewable);
2. the user confirmed a modal warning on this machine for this workspace (stored in VS Code `workspaceState`, so a cloned repository that sets the manifest flag cannot enable Python by itself);
3. VS Code Workspace Trust is granted.

The extension builds the runtime environment itself and always discards an inherited `DATAPASS_TRUSTED_PYTHON`; it sets `DATAPASS_TRUSTED_PYTHON=1` only when the three conditions hold. After start it verifies the runtime's own report (`GET /api/capabilities` → `runtime.trusted_local_python`) and stops the runtime on any mismatch. Changing the setting restarts a running runtime.

When disabled, SQL and bounded SparkLab work normally; Mosaic's **Run active Python**, Python/Polars Practice exercises and Python/Polars Pipeline activities report that trusted Python is disabled instead of executing. When enabled, trusted Python resolves relative paths from the workspace root.

## dbt Lab

Prefer real dbt Core over a fake dbt engine. Datapass adds project scaffolding, manifest lineage, tests/results UI and learning overlays.

## Airflow Lab

Airflow Lab simulates DAG scheduling concepts: dependencies, retries, trigger rules, task states, logical dates, logs and manual runs. It does not need a full Airflow installation for basic learning.

Practice `airflow` exercises use the runtime simulator in `runtime/airflowlab` (see its README). The learner writes a real-looking Airflow DAG file; a whitelisted AST reader turns it into a DAG model and **never executes it**. The simulator then creates the DAG runs a scheduler would create (Airflow 3 timetables, catchup, `start_date`) and simulates task instances (trigger rules, retries, execution timeouts, sensors, branching, short-circuits) and rendered templates for each fixture's scenario. Grading compares the simulated outcome rows: runs, task instances, rendered templates, edges or tasks.

The Airflow Lab surface uses the same simulator through `POST /api/local/airflow/simulate` (`airflowlab/lab.py`): the host sends the active DAG file's TEXT and the learner's scenario, and gets back the parsed DAG, the runs (the latest 40 are simulated), task instances, timed events for the step-by-step replay and rendered templates. There is one Airflow implementation; the earlier webview simulator and its `main.dag.json` spec were removed.

## Pipeline Lab

Pipeline Lab is hybrid. The Python-like pipeline source is parsed by a bounded AST compiler and is **never eval/exec'd**. Supported activity bodies can then execute against the shared local runtime.

Current executable activity bodies:

- SQL — real local DuckDB execution.
- Quality — real local query/assertion execution.
- Python / Polars — only when trusted local Python is effective (see above).
- dbt — accepted by the design compiler but deliberately **not executed**. A run fails that task once (no retries), states that nothing was run, and skips its downstream tasks; the graph labels the node *Declared only · not executed*. Use dbt Lab for real dbt Core execution. Wiring it later requires the trusted-local opt-in to cover dbt macros/hooks and strict project/resource validation; the donor `dbt_runner.py` depends on job/document infrastructure that is not part of this runtime.

Scheduling remains metadata/teaching semantics; Datapass is not running a production scheduler.

## Standalone WorkNotebook

Keep the standalone React site for cheatsheets, syntax/version references, examples, public/free learning areas and small browser-only playgrounds.

## Outside this repository

Contoso Data Studio remains C#. Datapass can consume datasets it creates, but does not embed that application.
