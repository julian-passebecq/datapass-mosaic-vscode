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

Mosaic is the free-form local workbench. Default execution is real Polars + DuckDB. It can arrange code/data/charts/docs in flexible panes, while source files remain real VS Code files. Spark simulation is optional, not Mosaic's identity.

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

## dbt Lab

Prefer real dbt Core over a fake dbt engine. Datapass adds project scaffolding, manifest lineage, tests/results UI and learning overlays.

## Airflow Lab

Airflow Lab simulates DAG scheduling concepts: dependencies, retries, trigger rules, task states, logical dates, logs and manual runs. It does not need a full Airflow installation for basic learning.

## Pipeline Lab

Pipeline Lab is hybrid. The Python-like pipeline source is parsed by a bounded AST compiler and is **never eval/exec'd**. Supported activity bodies can then execute against the shared local runtime.

Current executable activity bodies:

- SQL — real local DuckDB execution.
- Quality — real local query/assertion execution.
- Python / Polars — only when the explicitly trusted local-Python mode is enabled.
- dbt — accepted by the design compiler, but native pipeline execution is not wired yet; use dbt Lab for real dbt Core execution.

Scheduling remains metadata/teaching semantics; Datapass is not running a production scheduler.

## Standalone WorkNotebook

Keep the standalone React site for cheatsheets, syntax/version references, examples, public/free learning areas and small browser-only playgrounds.

## Outside this repository

Contoso Data Studio remains C#. Datapass can consume datasets it creates, but does not embed that application.
