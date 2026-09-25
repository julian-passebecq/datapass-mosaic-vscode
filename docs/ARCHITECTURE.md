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

## Fabric Lab

Fabric Lab is separate from Mosaic. It reproduces the learning workflow of lakehouse + notebook + pipeline locally:

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
