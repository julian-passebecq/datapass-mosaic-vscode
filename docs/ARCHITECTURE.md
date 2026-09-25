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
       ├─ dbt emulation (BI Lab) and missions checker (dbt Lab, Terminal Lab)
       └─ catalog handoff to the learner's real dbt Core / dct
```

## Catalog view

The Datapass sidebar has a native VS Code tree view, **Catalog**, next to **Labs**. It reads `GET /api/local/catalog/schema` (kernel op `catalog_schema`): every schema of the local DuckDB file, the catalog layers first (source, bronze, silver, gold, warehouse, features, metrics, even when empty) and then any other schema, such as the ones dbt Core creates. Each table or view shows its row count (a real `COUNT(*)`), its columns and their types; a view that fails to bind still shows, with its error. Clicking a table opens `.datapass/scratch/<schema>.<table>.sql` with `SELECT * ... LIMIT 100` (created once, never overwritten); **Preview Rows** runs that query and shows the result in Mosaic. The tree refreshes when the runtime starts or stops and after any run that changes the catalog listing.

## Projects

Projects (module id `projects`, `datapass.openProjects`) give the labs a story: `content/projects/<id>/project.json`
(schema and checks in `runtime/datapass_runtime/projects.py`, authoring guide in `docs/PROJECT_AUTHORING.md`) holds a
story, goals and 8 to 12 steps. Each step names its lab, an open action (lab tab, a file or a Practice exercise, and
the scaffolds that create the files it needs) and its checks.

```text
Projects UI ── "Verify" ────► POST /api/local/projects/check {project_id, steps}
                                   │  checks come from shipped content only
                                   ├─ kernel op project_state_checks: tables, read-only SQL, SQL pool designs, MLflow models
                                   └─ run journal (.datapass/data/run_journal.json)
lab routes ── record_run() ────────►  written by the API process when a lab answers (exercise Submit, pipelines,
                                      SQL pool, Databricks, BI Lab and lineage, dbt emulation, Airflow, Pipeline Lab...)
host ── applyVerification() ──► .datapass/progress.json (manual ticks, last verification, last passing verification)
```

- The runtime never marks a manual step as verified; the extension (`src/platform/projects.ts`) keeps ticks by hand
  (`manual`) apart from verifications (`verified`: the last run where every check passed; `last`: the latest run) and
  ignores a hand-edited `verified` record that does not pass.
- Mosaic imports (`/api/local/import-csv`, `/api/local/import-file`) send file CONTENT. For Parquet and JSON, the
  runtime writes a temporary copy in `.datapass/data/imports/`, the only folder DuckDB may read after
  `enable_external_access=false` (`allowed_directories`). The copy is deleted after the import, and cell SQL still
  cannot call file functions (`validate_sql`). `/api/local/profile` (SUMMARIZE) and `/api/local/explain`
  (EXPLAIN ANALYZE of one read-only query) are read-only.
- Each check result carries a truth: real, simulated, emulation, hybrid (simulated orchestration, local activities)
  or static (the BI Lab lineage).
- Practice keeps its own section in the same file, `practice.exercises["<pack>/<exercise>/<language>"]`
  (`src/platform/practiceProgress.ts`): `openedAt`, `attempts`, `last` (mode, status, version) and `solved` (the first
  Submit that passed). Run visible never solves, and a later failure never unsolves. Both modules write through
  `updateProgress()` (`src/projectState.ts`), one read-modify-write at a time; a file that does not parse is never
  overwritten.
- `.datapass/project.json` stays the single project manifest; progress is a separate native file.
- A future lab adds steps by recording its runs (`record_run` + a summarizer in `run_journal.py`) and using the generic
  `run` check; see `docs/PROJECT_AUTHORING.md`.
- `scripts/projects_smoke.py` replays a reference walkthrough of every project through the API in one workspace and
  requires every automatic check to fail first and pass after.

## Mosaic

Mosaic is the free-form local workbench. Default execution is real DuckDB SQL; Python/Polars run for real only after the trusted-local-Python opt-in. A `.sql` file whose first line is `-- dialect: <name>` (written by the **SQL: DuckDB ▾** status bar item, `src/sqlDialectStatus.ts`) is sent with that dialect: the runtime translates it with `runtime/sqldialects` (T-SQL, Snowflake, BigQuery, Spark SQL, PostgreSQL; one translator for the whole Workbench, also used by Practice and the SQL pool), runs the DuckDB translation and returns it with its label and rewrites, which Mosaic shows next to the result. It can arrange code/data/charts/docs in flexible panes, while source files remain real VS Code files. Spark simulation is optional, not Mosaic's identity.

Layout durability: inside a Datapass project the block geometry is saved to `.datapass/mosaic.json` (`schemaVersion: 1`, block ids + grid positions only; no source, paths, runtime state or secrets). The host validates every save (known blocks, bounded integers, clamped to 12 columns) and never creates the file outside a project. Missing blocks are completed from defaults; corrupt files or unknown schema versions fall back to the default layout without being overwritten until the next drag/resize. A layout that previously lived only in webview state is migrated once. Without a project the layout stays in webview state for the window only.

## Practice

Practice is the LeetCode-style layer: select challenge, open starter file in native VS Code, run local tests, show pass/fail/hints/explanation/review status.

Practice language `snowflake` takes Snowflake SQL: `runtime/sqldialects` translates it to DuckDB with sqlglot for a
documented subset (functions outside it are refused by name) and the result is graded like `sql` on DuckDB. It is
labelled "Snowflake SQL dialect translated to DuckDB, not Snowflake".

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

## Runtime authentication (loopback)

The runtime binds `127.0.0.1` on a free port, but a loopback port is reachable by any local process and, through DNS rebinding, by a web page. Each launch is therefore authenticated:

- The extension generates a random token per launch (`crypto.randomBytes(32)`, `src/platform/runtimeClient.ts`), keeps it in memory only (never persisted, never logged) and passes it with the port in the child environment (`DATAPASS_RUNTIME_TOKEN`, `DATAPASS_RUNTIME_PORT`, built by `runtimeProcessEnv`, which drops any inherited value).
- Every client call (`requestJson`, `requestGetJson`, the health probe, the dbt Lab catalog release/reattach, missions) sends it in the `X-Datapass-Token` header.
- The runtime's ASGI middleware (`runtime/datapass_runtime/auth.py`) answers 400 unless the Host header is exactly `127.0.0.1:<port>` or `localhost:<port>`, 401 unless the token matches (constant-time comparison), and 503 when the runtime was started without a token or port (it fails closed). `/api/health` is not exempt: the extension always has the token, and a refusal says nothing about the runtime.
- The kernel worker never sees the token: its environment drops every `*TOKEN*` variable. dbt and dct run in a VS Code terminal whose environment comes from the extension host, not from the runtime, so they never see it either.
- TestClient smokes configure the same variables through `scripts/runtime_test_auth.py` and pass `base_url` and the header.

Webviews: CSP nonces come from `crypto.randomBytes` (`src/webview/security.ts`), and `img-src` allows only `webview.cspSource` and `data:` (dct PNG renders are inlined as data URLs); no webview surface loads remote images.

## Trusted local Python

Python/Polars files are real local code. The runtime worker is a separate process for lifecycle management (timeouts, restarts) and is **not** a security sandbox. Trusted Python is therefore effective only when all of these hold:

1. `.datapass/project.json` sets `runtime.trustedLocalPython: true` (default `false`; portable and reviewable);
2. the user confirmed a modal warning on this machine for this workspace (stored in VS Code `workspaceState`, so a cloned repository that sets the manifest flag cannot enable Python by itself);
3. VS Code Workspace Trust is granted.

The extension builds the runtime environment itself and always discards an inherited `DATAPASS_TRUSTED_PYTHON`; it sets `DATAPASS_TRUSTED_PYTHON=1` only when the three conditions hold. After start it verifies the runtime's own report (`GET /api/capabilities` → `runtime.trusted_local_python`) and stops the runtime on any mismatch. Changing the setting restarts a running runtime.

When disabled, SQL and bounded SparkLab work normally; Mosaic's **Run active Python**, Python/Polars Practice exercises and Python/Polars Pipeline activities report that trusted Python is disabled instead of executing. When enabled, trusted Python resolves relative paths from the workspace root.

## dbt Lab

The real-life dbt lab: real dbt Core + dbt-duckdb, run by the learner in a VS Code integrated terminal. Datapass adds
the managed tools environment, the generated profile, the catalog handoff and a view of the artifacts; it never runs
dbt in the runtime and never approximates it (the emulation lives in the BI Lab).

- **Tools** (`src/dbtLab.ts`, `DbtToolsManager`): a venv `dbt-tools-venv` in the extension's global storage, created
  only by **Install dbt tools** (modal confirmation), separate from the runtime venv because dbt pins its own
  dependencies and needs Python 3.10–3.13. Requirements in `src/platform/dbtTools.ts`; DuckDB is pinned to the
  runtime venv's version so both processes share one storage format. Versions come from package metadata.
- **Terminal** (`DbtTerminalSession`): one terminal per project folder, env = managed tools first on `PATH`,
  `VIRTUAL_ENV`, `DBT_PROFILES_DIR=.datapass/dbt`, `DBT_SEND_ANONYMOUS_USAGE_STATS=false`, `DO_NOT_TRACK=1`. Buttons
  build the command line (`buildDbtCommand`, selectors validated, quoted for every shell) and type it through shell
  integration (`executeCommand`), or `sendText` without it.
- **Catalog handoff**: the runtime's kernel worker holds `.datapass/data/workspace.duckdb` open, and DuckDB refuses a
  second writer (and a read-only opener) from another process. `POST /api/local/catalog/release` (holder = the command
  line) waits for the running request, stops the worker gracefully (the connection closes, the lock is freed) and
  makes every catalog request answer HTTP 409 until `POST /api/local/catalog/reattach`, which reopens the catalog or
  answers 409 if the file is still held. `GET /api/local/catalog/lease` reports it. The terminal session releases on
  `onDidStartTerminalShellExecution` for a catalog command (`isCatalogCommand`: dbt and dct, except commands that
  never open the database) and reattaches on `onDidEndTerminalShellExecution` or when the terminal closes; without
  shell integration, new artifacts trigger a reattach attempt and **Reattach catalog** is always available. A lock
  held by a process the runtime did not lend the file to (a dbt run in an outside terminal) is reported as HTTP 409
  with an explanation instead of a raw IO error.
- **dbt Charts**: `dbt-charts>=0.8,<0.9` in the same venv (pre-1.0, so pinned to a minor). Conventions checked on
  dct 0.8.0 itself (`dct --help`, `dct docs`): `dbt_charts.yml` at the project root declares sources (`type:
  dbt_profile`, found through `DBT_PROFILES_DIR`), boards live in `charts/`, queries use `{{ ref('model') }}` resolved
  against `target/manifest.json`, `dct render` writes `renders/<stem>.<ext>` (it does not create the folder of an
  `--output` path, so the lab creates `renders/`), `--format json` gives the resolved board with each chart's data,
  `dct validate --json` needs no database, and dct opens DuckDB read-only (still refused while the runtime holds the
  file, hence the same handoff). `buildDctCommand` builds validate/render/serve lines (board paths confined to the
  project; serve always `--host 127.0.0.1` on a free port). `dct serve` runs in a second terminal of the session (a
  server keeps its terminal busy); commands in one terminal are queued until the previous one ends, because
  `executeCommand` would interrupt it. The PNG reaches the webview as a `data:` image (already allowed by the CSP);
  rendered HTML is never injected: it opens with `vscode.env.openExternal`, and the live server in the Simple Browser.
- **Missions** (`runtime/missionlab`, README there; `content/missions/dbt-v1`; `src/missions.ts`,
  `src/platform/missions.ts`, `src/webview/MissionsPanel.tsx`): ticket-style tasks done with the real tools on a
  project folder `missions/<id>/` (the pack's `base/` project plus the mission's `project/` overlay, copied once,
  never overwritten). The runtime loads each mission's fixture batches into its own raw schema from the shipped SQL
  (`POST /api/local/missions/setup`, kernel op `mission_setup`; the first batch drops the mission's raw and dev
  schemas) and runs the hidden checker (`POST /api/local/missions/check`): read-only SQL through the catalog's query
  contract (kernel op `mission_sql`, the Projects module's `compare_rows`), and, in the API process, the learner's
  `target/manifest.json`, `run_results.json` and `sources.json`, board and render files, and an Airflow DAG parsed and
  simulated by `airflowlab` (never executed). `dct validate` results come from the host, which runs the real dct.
  Missions build with the dbt Lab's profile into `dbt_dev_<custom>` schemas, so they never collide with each other or
  with the catalog layers. Reference solutions and mutants (plausible wrong answers) are excluded from the VSIX and
  played by `scripts/missions_smoke.py` with real dbt Core and dct (CI installs them). The panel is lab-agnostic so
  the Terminal Lab reuses it with its own check kinds (see below), and the future Infra Lab can do the same.
- **Artifacts** (`src/platform/dbtArtifacts.ts`): `target/manifest.json` + `target/run_results.json` of the selected
  project → command (from `args`), counts, DAG, problems, node details; a manifest newer than the results (after
  `dbt parse` or `docs generate`) is flagged. Labelled "dbt Core (real)".

Retired with this rebuild: the regex-based static lineage of the old dbt Lab (use `dbt parse` for a real manifest,
or the BI Lab's emulation), the `dbt --version` probe of a dbt on the user's `PATH` (`src/platform/dbtVersion.ts`), and
the single hard-coded `dbt/retail-dbt` project (the sample remains, as one project among others).

## Terminal Lab

The Terminal Lab (module id `terminal`, `datapass.openTerminalLab`) is the learner's own bash, PowerShell and Git
commands, typed in a real VS Code terminal. Datapass runs none of them; it builds the starting folder, then reads
what the commands left behind. No kernel worker and no catalog are involved.

- **Host** (`src/terminalLab.ts`, `TerminalLabSession`): `detect()` finds bash and PowerShell on this machine
  (`src/platform/terminalShells.ts`, pure functions so `scripts/terminal_lab_smoke.mjs` can test them without
  `vscode`) — Git Bash next to `git.exe` or in the usual Git for Windows folders on Windows (never
  `C:\Windows\System32\bash.exe`, which starts WSL; `datapass.terminalLab.bashPath` overrides), pwsh then Windows
  PowerShell 5.1 — and reads the learner's Git version and global `user.name`/`user.email` (read-only, so the lab
  can warn before `git commit` refuses to run). The learner's shell choice is remembered in global state
  (`datapass.terminalLab.shell`). `open()` creates or shows a VS Code terminal in the mission folder with that shell
  (Git Bash as a login shell with `CHERE_INVOKING=1` so it stays in the folder) and types nothing in it.
- **Start over** (`release()`): before the runtime moves the mission folder aside, the session closes its own
  terminals open in that folder (`closeIn`) and the VS Code Git extension's repository on it (`git.close`), because
  on Windows a terminal or Source Control's `.git` watch keeps the folder from being moved (found by the Playwright
  drive of the packaged extension). The runtime itself builds the new fixture outside the workspace and renames it
  into place, so Source Control never opens a half-built repository; the caller reopens the Git repository
  (`git.openRepository`) once the rebuilt folder is in place.
- **Runtime** (`runtime/missionlab`, README there): `terminal.py`'s `build_fixture` builds the mission folder from
  the pack only — the mission's `project/` overlay, inline `fixture.files` (with CRLF or the executable bit when a
  mission needs it), then a Git history made of fixed git commands (`init -b`, `commit`, `branch`, `switch`,
  `merge --no-ff`, `tag`, `branch -D`, `reset --hard`, `stash push`) with a fixed author and dates, so hashes are
  reproducible and the learner's global/system Git config is never read. `POST /api/local/missions/setup
  {mission_id}` (re)builds it; no `batch_id` and no kernel op, unlike the dbt Lab's missions. `POST
  /api/local/missions/check {mission_id}` runs the checks entirely in the API process: files as text (UTF-8, or
  UTF-16 with a BOM as Windows PowerShell 5.1's `>` writes), CSV, scripts as text (comments stripped, never
  executed), and the repository through read-only git commands with `core.fsmonitor` off, hooks pointed at nothing
  and `GIT_CEILING_DIRECTORIES` set, so a repository around the workspace is never mistaken for the mission's own.
  Thirteen check kinds: `path`, `text`, `listing`, `csv`, `script`, `git_repo`, `git_branch`, `git_log`, `git_file`,
  `git_tag`, `git_ignore`, `git_stash`, `any_of`. Check kinds that need the catalog or dbt (`sql`, `node`, `run`, …)
  are refused in this lab.
- **Content** (`content/missions/terminal-v1`): 8 missions, `mission.json` with a `fixture` instead of a `workspace`
  and `batches`, and `reference`/`mutants` as whole solution scripts (`solution/solve.sh`,
  `solution/solve.ps1`, `mutants/<name>/solve.sh` or `solve.ps1`).
- **Webview** (`src/webview/TerminalSurface.tsx`): shell picker, a Git badge, **Open a terminal** and **Refresh**,
  then the shared `MissionsPanel` (the same component the dbt Lab uses) with a Terminal Lab-specific folder note and
  open label.
- `scripts/terminal_missions_smoke.py` plays every reference with real shells (bash; pwsh, and Windows PowerShell
  5.1 on Windows) through the API: references pass, the untouched fixture and every mutant fail, the fixture's
  hashes are reproducible, and Start over keeps the previous folder in the attic.

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
