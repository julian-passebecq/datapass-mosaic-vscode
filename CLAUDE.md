# CLAUDE.md — Datapass Workbench

This repository is the authoritative implementation target for the Datapass Workbench VS Code extension.

## Product boundary

Do not turn this repository into another standalone IDE or browser notebook.

VS Code owns:

- source editing and tabs;
- Explorer/files;
- terminals;
- Git;
- Microsoft Python/Jupyter integration.

Datapass owns:

- Projects: end-to-end stories whose steps are done in the labs, verified on the workspace, with progress in `.datapass/progress.json` (Practice keeps its solved/attempted exercises in the same file);
- Mosaic workspace composition;
- Practice/exercise UX and grading;
- Cloud Lab (formerly Fabric Lab): Fabric-inspired local learning UX, the Fabric / Azure Data Factory / Synapse pipeline simulator, the SQL pool simulator (Synapse dedicated SQL pool, Fabric Warehouse) and the Databricks simulator (jobs, compute, Unity Catalog, MLflow);
- bounded SparkLab/ZilaCode semantics;
- dbt learning/lineage integration;
- the BI Lab: data warehousing on the local catalog (dimensional modeling, slowly changing dimensions, SQL lineage, star model checks);
- Airflow scheduling simulation;
- Pipeline Lab design/execution UX;
- the single local FastAPI control plane.

The standalone Datapass WorkNotebook and Contoso Data Studio are separate products. Historical code under `workbench-core/`, `migration-sources/`, and `legacy-donors/` is donor/reference material, not a second runtime.

## Non-negotiable truth model

Never blur real execution and simulation.

- Projects (module id `projects`): a step is "verified" only when the runtime verified every one of its checks on the workspace: state checks run on the catalog (tables, read-only SQL assertions, SQL pool designs, MLflow models) and run checks read the run journal the runtime writes itself when a lab answers (`.datapass/data/run_journal.json`). Each check reports what it saw: real, simulated, emulation, hybrid, or static (SQL lineage). A learner's tick is "ticked by hand", counted apart and NEVER turned into a verification; steps without checks are manual. Projects run nothing of their own; `.datapass/project.json` stays the single project manifest.
- Mosaic SQL: real local DuckDB execution.
- Mosaic Python/Polars: real local execution only when explicitly trusted local Python is enabled.
- Practice: native VS Code solution files with real local grading through the shared runtime.
- Cloud Lab (module id `fabric`, formerly Fabric Lab): Fabric-inspired UX; local DuckDB/DuckLake and selected real-local operations; no implicit Microsoft Fabric, Azure or Databricks connection. Its Pipelines tab (`runtime/factorylab`) reads real Fabric / Azure Data Factory / Synapse pipeline JSON and simulates the orchestration deterministically (dependency conditions, leaf rule, retries, containers, expressions); Copy, Lookup, Script, stored procedures and notebooks run on the local catalog, notebooks through SparkLab's whitelisted AST interpreter (NEVER eval/exec'd); every other activity follows the scenario. Its SQL pool tab (`runtime/sqlpoollab`) translates a documented T-SQL subset to DuckDB and really runs the data statements on the local catalog; distributions, partitions, columnstore rowgroups and data movement plans are modelled teaching data, not Synapse or Fabric telemetry. Its Databricks tab (`runtime/databrickslab`) reads Jobs API JSON and simulates the orchestration (run_if, If/else, for each, retries, task values) and the compute and its cost (lab DBU figures); notebook tasks run on SparkLab (NEVER eval/exec'd, including the bounded pyspark.ml and MLflow subset) and SQL tasks on DuckDB, both under Unity Catalog privilege checks for the job's run_as principal.
- BI Lab (module id `bi`, `runtime/bilab`): warehouse SQL scripts really run on the local DuckDB catalog; column lineage and impact are a static analysis of the SQL text (sqlglot), never execution; star model checks (keys, grain, SCD2 validity, relationships) are real queries. The star model file is Datapass's own format with Power BI's relationship vocabulary; there is no Power BI or DAX engine and no connection to one. Its dbt tab and the `dbt-v1` Practice pack use the Datapass dbt emulation (`runtime/dbtlab`): project Jinja is rendered in jinja2's sandbox and NEVER executed as Python, the compiled SQL really runs on DuckDB, and dbt Core + dbt-duckdb semantics are reproduced for a documented subset and checked with `scripts/dbt_oracle_smoke.py` against real dbt Core. It is labelled "not dbt Core"; packages, Python models, hooks and adapter calls are refused, not approximated.
- Snowflake SQL (Practice language `snowflake`, `runtime/snowflakesql`): "Snowflake SQL dialect translated to DuckDB, not Snowflake". The learner's Snowflake query is parsed and translated with sqlglot (read `snowflake`, write `duckdb`) and really runs on DuckDB. Only a documented subset is accepted: every function and syntax node is allowlisted, constructs whose DuckDB translation would change Snowflake's result are rewritten or refused, and unsupported functions are refused by name, never approximated. There is no Snowflake connection.
- SparkLab/ZilaCode: bounded PySpark-style semantics; distributed Spark behavior and telemetry are simulated/teaching data.
- dbt Lab: prefer real dbt Core + dbt-duckdb; static lineage is a fallback, not execution.
- Airflow Lab: deterministic scheduling simulator; it is not an Airflow scheduler/executor. Airflow DAG files (the Airflow Lab panel and Practice `airflow` exercises) are parsed by a whitelisted AST reader (`runtime/airflowlab`) and NEVER eval/exec'd; scheduler and task outcomes are simulated with Airflow 3 semantics.
- Pipeline Lab: the Python-like pipeline source is parsed by a bounded AST compiler and is NEVER eval/exec'd. Supported activity bodies may execute locally. Scheduling remains metadata/simulation.

## Security boundaries

- Never eval/exec Pipeline Lab source, Airflow Lab DAG files or Cloud Lab notebooks (Fabric, Synapse or Databricks).
- Never silently enable arbitrary Python execution.
- The local Python worker is process-isolated for lifecycle reasons; it is NOT a security sandbox.
- Trusted Python/Polars must remain an explicit user choice.
- Do not add cloud credentials, tokens, secrets, or copied local environment state.
- Preserve CSP/nonce-protected webviews.
- Keep runtime requests loopback/local by default.

## Architecture constraints

Prefer one implementation of each capability:

- one FastAPI local runtime;
- one shared local data catalog;
- one bounded SparkLab runtime;
- one shared React Flow graph foundation;
- one project manifest at `.datapass/project.json`;
- native VS Code files instead of embedded Monaco/editor clones.

Do not copy whole historical applications into the extension. Promote only proven contracts, content, runtime mechanics, or UI components.

## Required quality gates

Before declaring a change complete:

```bash
npm install --no-audit --no-fund
npm run compile
npm test
python -m pip install ./runtime
python -m compileall -q runtime/datapass_runtime runtime/sparklab runtime/airflowlab runtime/factorylab runtime/sqlpoollab runtime/databrickslab runtime/bilab runtime/dbtlab runtime/snowflakesql
python scripts/runtime_smoke.py
python scripts/exercise_packs_smoke.py
python scripts/projects_smoke.py
DATAPASS_DBT_PYTHON=<python with dbt-core + dbt-duckdb> python scripts/dbt_oracle_smoke.py   # when changing runtime/dbtlab
npm run test:host   # with DATAPASS_E2E_PYTHON set; see docs/LOCAL_TEST.md
```

Also manually inspect the Extension Development Host for user-facing changes when possible.

## Branching

`main` is the baseline. The former implementation branch `codex/bootstrap-datapass-workbench` was merged through PR #1 (merge commit `f35dbe4`, 2026-09-24) and is kept only as history; do not continue work on it.

- Start each tranche on a new branch from an up-to-date `main`.
- Merge back through a pull request once CI (extension, runtime, extension-host) is green; CI runs on every pull request.
- Do not force-push or rewrite `main` history.

## Current continuation point

Read `docs/CLAUDE_HANDOFF_2026-09-24.md` before making substantial changes. It records the implemented execution bridge, known gaps, and prioritized continuation plan; its §0 sections are the newest state.
