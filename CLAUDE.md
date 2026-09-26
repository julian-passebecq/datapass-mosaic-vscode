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
- the dbt Lab: real dbt Core and dbt Charts run by the learner in a VS Code terminal on the local catalog (managed tools installed on request, generated profile, catalog handoff, artifacts view) and its missions;
- missions: ticket-style tasks checked by a hidden checker (`runtime/missionlab`), shared by the dbt Lab, the
  Terminal Lab and the Infra Lab, reusable by later labs;
- the Terminal Lab: real bash, PowerShell and Git skills, practised with the learner's own commands in a VS Code
  terminal opened in a mission folder, and its missions;
- the Infra Lab: simulated Terraform (a subset of the azurerm provider on a simulated subscription), Docker and
  compose, VM monitoring with Azure Monitor alerts, and Kubernetes, typed in one simulated terminal, and its missions;
- the API Lab: REST API ingestion into bronze by the learner's own Python against a simulated API served locally, and its missions;
- the BI Lab: data warehousing on the local catalog (dimensional modeling, slowly changing dimensions, SQL lineage, star model checks);
- the Lakehouse Lab: storage layout on real local files (Parquet, Hive partitions, pruning, compaction) and DuckLake
  tables (snapshots, time travel, schema evolution, MERGE), and its missions;
- Airflow scheduling simulation;
- Pipeline Lab design/execution UX;
- the single local FastAPI control plane.

The standalone Datapass WorkNotebook and Contoso Data Studio are separate products. Historical code under `workbench-core/`, `migration-sources/`, and `legacy-donors/` is donor/reference material, not a second runtime.

## Non-negotiable truth model

Never blur real execution and simulation.

- Projects (module id `projects`): a step is "verified" only when the runtime verified every one of its checks on the workspace: state checks run on the catalog (tables, read-only SQL assertions, SQL pool designs, MLflow models) and run checks read the run journal the runtime writes itself when a lab answers (`.datapass/data/run_journal.json`). Each check reports what it saw: real, simulated, emulation, hybrid, or static (SQL lineage). A learner's tick is "ticked by hand", counted apart and NEVER turned into a verification; steps without checks are manual. Projects run nothing of their own; `.datapass/project.json` stays the single project manifest.
- Mosaic SQL: real local DuckDB execution (or a translated dialect, see SQL dialects).
- Mosaic Python/Polars: real local execution only when explicitly trusted local Python is enabled.
- Practice: native VS Code solution files with real local grading through the shared runtime.
- Cloud Lab (module id `fabric`, formerly Fabric Lab): Fabric-inspired UX; local DuckDB/DuckLake and selected real-local operations; no implicit Microsoft Fabric, Azure or Databricks connection. Its Pipelines tab (`runtime/factorylab`) reads real Fabric / Azure Data Factory / Synapse pipeline JSON and simulates the orchestration deterministically (dependency conditions, leaf rule, retries, containers, expressions); Copy, Lookup, Script, stored procedures and notebooks run on the local catalog, notebooks through SparkLab's whitelisted AST interpreter (NEVER eval/exec'd); every other activity follows the scenario. Its SQL pool tab (`runtime/sqlpoollab`) translates a documented T-SQL subset to DuckDB and really runs the data statements on the local catalog; distributions, partitions, columnstore rowgroups and data movement plans are modelled teaching data, not Synapse or Fabric telemetry. Its Databricks tab (`runtime/databrickslab`) reads Jobs API JSON and simulates the orchestration (run_if, If/else, for each, retries, task values) and the compute and its cost (lab DBU figures); notebook tasks run on SparkLab (NEVER eval/exec'd, including the bounded pyspark.ml and MLflow subset) and SQL tasks on DuckDB, both under Unity Catalog privilege checks for the job's run_as principal.
- BI Lab (module id `bi`, `runtime/bilab`): warehouse SQL scripts really run on the local DuckDB catalog; column lineage and impact are a static analysis of the SQL text (sqlglot), never execution; star model checks (keys, grain, SCD2 validity, relationships) are real queries. The star model file is Datapass's own format with Power BI's relationship vocabulary; there is no Power BI or DAX engine and no connection to one. Its dbt tab and the `dbt-v1` Practice pack use the Datapass dbt emulation (`runtime/dbtlab`): project Jinja is rendered in jinja2's sandbox and NEVER executed as Python, the compiled SQL really runs on DuckDB, and dbt Core + dbt-duckdb semantics are reproduced for a documented subset and checked with `scripts/dbt_oracle_smoke.py` against real dbt Core. It is labelled "not dbt Core"; packages, Python models, hooks and adapter calls are refused, not approximated.
- SQL dialects (`runtime/sqldialects`, one translator for the whole Workbench): T-SQL, Snowflake, BigQuery, Spark SQL (ANSI) and PostgreSQL are translated to DuckDB with sqlglot and really run on DuckDB, each labelled "<dialect> dialect translated to DuckDB, not <engine>" (for example "Snowflake SQL dialect translated to DuckDB, not Snowflake"). Callers: Mosaic `.sql` files whose first line is `-- dialect: <name>` (Run and Explain active SQL; the translated SQL is shown next to the result), Practice language `snowflake`. Only a documented subset per dialect is accepted: every function and syntax node is allowlisted, constructs whose DuckDB translation would change the engine's result are rewritten (with the catalog's types) or refused when a type is unknown, and unsupported functions are refused by name, never approximated. The translated SQL goes through the same catalog validation as DuckDB SQL. There is no connection to any of these engines.
- Practice concept checks (language `quiz`, `concepts-v1`): "Concept check (no execution)": questions about what cannot run locally (Fabric capacities, Synapse DWUs, Databricks compute, Unity Catalog, table formats); the learner's answer line is compared by the runtime with the private answer in `grading.server.json`, whose answer and explanation reach the webview only through a submission. Truth `concept-check`.
- Practice pytest exercises (language `pytest`, `python-prod-v1`): the learner's module and its tests run under real pytest (a child `python -m pytest` of the worker, temporary folder, timeout, plugin autoload off, no Datapass or secret-looking environment variables), then hidden tests import it as `solution`; trusted local Python only, refused while it is off, never a fallback; not a security sandbox.
- Spark SQL (Practice language `sparksql`, `spark-sql-v1`): "Spark SQL dialect translated to DuckDB, not Spark", the same translator and rules as the Snowflake SQL line above (dialect `spark`, ANSI mode).
- SparkLab/ZilaCode: bounded PySpark-style semantics; distributed Spark behavior and telemetry are simulated/teaching data. Its Polars engine is real Polars run as trusted local Python (refused while trusted Python is off, never a SparkLab fallback); the plan it shows is Polars' own `LazyFrame.explain()`.
- dbt Lab (module id `dbt`): real dbt Core + dbt-duckdb and real dbt Charts (`dct`), installed only by an explicit Install dbt tools into a managed venv, and run by the learner in a VS Code integrated terminal; nothing is emulated or approximated there and there is no static-lineage fallback (the emulation belongs to the BI Lab). While a dbt or dct command runs, the runtime lends it the catalog file (DuckDB allows one writer) and reattaches it afterwards. The DAG, statuses and failures come from the run's own `target/` artifacts, labelled "dbt Core (real)". Rendered dbt Charts HTML never enters the Workbench webview; `dct serve` binds 127.0.0.1. Missions (`runtime/missionlab`) are the learner's own real runs, checked by real read-only queries on the catalog, the learner's dbt artifacts and files, the real `dct validate`, and an Airflow DAG parsed and simulated by `runtime/airflowlab` (never executed).
- Terminal Lab (module id `terminal`): the learner's own real commands. Datapass opens a VS Code terminal in
  `missions/<id>/` with the shell the learner chose (bash, Git Bash on Windows; pwsh or Windows PowerShell) and types
  nothing in it. The runtime builds the mission folder from the shipped pack only (files, and a Git history made of
  fixed git commands with a fixed author and dates); Start over moves the previous folder to
  `.datapass/missions/attic/`, never deletes it. The checker (`runtime/missionlab/terminal.py`) reads the resulting
  state: files, CSV, scripts as TEXT (never executed), and the repository through read-only git commands (fsmonitor
  off, no hooks, `GIT_CEILING_DIRECTORIES`). Datapass executes nothing of the learner's.
- Infra Lab (module id `infra`, `runtime/infralab`): simulation only; nothing is provisioned, built, pulled, run or
  deployed, and no real `terraform`, `docker`, `kubectl` or `az` is started, even when installed. The learner types in
  a VS Code Pseudoterminal owned by the extension (no process is spawned) that sends each line to the runtime; pipes,
  redirections, variables and real programs are refused. HCL is parsed by a whitelisted reader and evaluated over plain
  values with a function whitelist; plans and applies run against a simulated azurerm provider (a documented subset of
  real resource types and arguments) and a simulated subscription, and `terraform.tfstate` is marked as simulated.
  Dockerfiles and compose files are read, never executed: builds, the layer cache, containers and health checks are
  simulated. Metrics are recorded scenarios and alert rules are replayed with Azure Monitor semantics. Kubernetes
  manifests are validated strictly and applied to a simulated cluster (scheduling, readiness, rollouts). Everything
  lives in `<folder>/.infralab/world.json`; missions check that simulated world, the state file, the shell's journal
  and the files.
- Lakehouse Lab (module id `lakehouse`, `runtime/lakehouselab`): real and local. The learner's SQL runs on DuckDB in a
  child process bounded to `lakehouse/<id>/` (DuckDB's `allowed_directories` + external access off + locked
  configuration; ATTACH, INSTALL, LOAD, SET, PRAGMA refused; not a security sandbox); their Polars file runs as trusted
  local Python only while trusted Python is on. DuckLake is the official DuckDB `ducklake` extension on the mission's
  own lake, installed once by Setup runtime and only loaded afterwards (offline-safe). The checker measures files on
  disk, reads rows, Parquet schemas, snapshots and time travel with DuckDB (lake attached read-only) and pruning from
  DuckDB's own `EXPLAIN ANALYZE`. Delta tables are read (any version) and appended through DuckDB's official `delta`
  extension, installed by Setup like ducklake (it cannot create a Delta table: the mission ships its `_delta_log`);
  no deltalake or pyiceberg. Iceberg is explained, never handled or emulated.
- API Lab (module id `apilab`, `runtime/apilab`): "Simulated API (Datapass), your ingestion code runs for real". The REST
  API is simulated: a small server the runtime starts on 127.0.0.1, on its own port, for the active mission, with
  deterministic seeded data and faults (pagination, `updated_since`, 429 + Retry-After, transient 5xx, duplicates,
  schema drift). The learner's `missions/<id>/ingest.py` is real Python (requests/httpx) run as trusted local Python
  in the kernel worker, refused while trusted Python is off; it writes real DuckDB tables in the bronze layer through
  `bronze.append/merge/overwrite` (schema enforcement: a new column needs `evolve=True`). Checks are real read-only
  SQL on bronze plus the simulated API's request log and run history.
- Airflow Lab: deterministic scheduling simulator; it is not an Airflow scheduler/executor. Airflow DAG files (the Airflow Lab panel and Practice `airflow` exercises) are parsed by a whitelisted AST reader (`runtime/airflowlab`) and NEVER eval/exec'd; scheduler and task outcomes are simulated with Airflow 3 semantics.
- Pipeline Lab: the Python-like pipeline source is parsed by a bounded AST compiler and is NEVER eval/exec'd. Supported activity bodies may execute locally. Scheduling remains metadata/simulation.

## Security boundaries

- Never eval/exec Pipeline Lab source, Airflow Lab DAG files or Cloud Lab notebooks (Fabric, Synapse or Databricks).
- Never silently enable arbitrary Python execution.
- Never install the dbt tools (dbt Core, dbt-duckdb, dbt Charts) without the learner's explicit action; the generated `.datapass/dbt/profiles.yml` holds a local DuckDB path only, never secrets. dbt and dct run as the learner's own terminal commands, not in a sandbox.
- Mission fixtures and checks come from the shipped content only, never from a request.
- Never execute Infra Lab files (HCL, Dockerfile, compose, Kubernetes YAML) or start a real infrastructure tool from
  the Infra Lab shell; it simulates terraform, docker, kubectl and az, and stays inside the workspace folder it is
  given.
- Never run a Terminal Lab learner's commands or scripts: the checker reads files and Git state only. Its git calls
  stay read-only and must not start anything the repository's config names (fsmonitor, hooks, pager).
- API Lab: the simulated API server binds 127.0.0.1 on its own port (never the runtime's), checks its own Host header
  (`127.0.0.1:<port>` / `localhost:<port>`, else 400) and its own fictitious per-mission bearer key (else 401), and
  starts with an allowlisted environment: the runtime's launch token never reaches it, its log, its answers or the
  learner's code. Its request log never records header values. Its scenarios come from the shipped pack only.
- The local Python worker is process-isolated for lifecycle reasons; it is NOT a security sandbox.
- Trusted Python/Polars must remain an explicit user choice.
- Do not add cloud credentials, tokens, secrets, or copied local environment state.
- Preserve CSP/nonce-protected webviews.
- Keep runtime requests loopback/local by default.
- Every runtime request carries the per-launch token (`X-Datapass-Token`, generated by the extension, passed as `DATAPASS_RUNTIME_TOKEN`, never persisted or logged) and a loopback Host (`127.0.0.1:<port>` / `localhost:<port>`); the runtime refuses anything else, `/api/health` included, and fails closed without a token. New client calls go through `src/platform/runtimeClient.ts`.
- Webview images load only from `webview.cspSource` and `data:`; never add `https:` to the CSP.

## Architecture constraints

Prefer one implementation of each capability:

- one FastAPI local runtime;
- one shared local data catalog;
- one bounded SparkLab runtime;
- one SQL dialect translator (`runtime/sqldialects`);
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
python -m compileall -q runtime/datapass_runtime runtime/sparklab runtime/airflowlab runtime/factorylab runtime/sqlpoollab runtime/databrickslab runtime/bilab runtime/dbtlab runtime/sqldialects runtime/missionlab runtime/infralab runtime/apilab
python scripts/runtime_smoke.py
python scripts/exercise_packs_smoke.py
python scripts/projects_smoke.py
python scripts/terminal_missions_smoke.py   # Terminal Lab: references pass with real bash and PowerShell; untouched fixtures and mutants fail
python scripts/infra_missions_smoke.py      # Infra Lab: references pass in the simulated shell; untouched fixtures, starters and mutants fail
python -m compileall -q runtime/lakehouselab && python scripts/lakehouse_smoke.py   # Lakehouse Lab: references (DuckDB and Polars) pass; untouched starters and mutants fail
PYTHONPATH=runtime python scripts/authoring/gen_json_schemas.py --check   # schemas/ match the runtime's pydantic contracts
python scripts/api_lab_smoke.py             # API Lab: references pass; untouched missions, starters and mutants fail; mock API auth, Host check, no runtime token
DATAPASS_DBT_PYTHON=<python with dbt-core + dbt-duckdb> python scripts/dbt_oracle_smoke.py   # when changing runtime/dbtlab
DATAPASS_DBT_PYTHON=<python with dbt-core + dbt-duckdb + dbt-charts> python scripts/missions_smoke.py   # missions: references pass, untouched projects and mutants fail
npm run test:host   # with DATAPASS_E2E_PYTHON set; see docs/LOCAL_TEST.md
npm run package && npm run test:ui   # the packaged VSIX in a real VS Code window (Playwright); see docs/LOCAL_TEST.md
```

Also manually inspect the Extension Development Host for user-facing changes when possible.

## Branching

`main` is the baseline. The former implementation branch `codex/bootstrap-datapass-workbench` was merged through PR #1 (merge commit `f35dbe4`, 2026-09-24) and is kept only as history; do not continue work on it.

- Start each tranche on a new branch from an up-to-date `main`.
- Merge back through a pull request once CI (extension, runtime, extension-host) is green; CI runs on every pull request.
- Do not force-push or rewrite `main` history.

## Current continuation point

Before a substantial change, read:

- `docs/HANDOFF.md`: the current state (what exists, truth model, where things live, how to test, known gaps), kept
  under 200 lines and updated in place;
- the roadmap artifact (https://claude.ai/artifact/RhQMPGxeuNo9GTFzH5B8aJ) for what comes next;
- `docs/HANDOFF_HISTORY.md` when you need how something came to be: one dated `## YYYY-MM-DD · Title` section per
  tranche, newest first, with its "Checked" / "Not checked" notes. Add yours at the top; never number or letter
  sections.
