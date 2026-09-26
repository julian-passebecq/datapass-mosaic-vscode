# Datapass Workbench quickstart

## 1. Run the extension

```bash
npm install
npm run compile
```

Open this repository in VS Code and press **F5** to start an Extension Development Host.

In the new VS Code window:

1. Open a folder that can hold a learning workspace.
2. Open the **Datapass** Activity Bar.
3. Choose **Cloud Lab**.
4. Click **Create / repair demo files**, start the runtime, then **Run local medallion flow**.

Datapass creates only missing files. Existing learner files are not overwritten.

## 2. What the demo creates

```text
your-workspace/
├─ .datapass/
│  ├─ project.json
│  └─ dbt/
│     └─ profiles.yml
├─ datasets/
│  └─ retail_orders.csv
├─ notebooks/
│  ├─ retail_medallion.sql
│  └─ retail_quality.py
├─ pipelines/
│  └─ main.pipeline.py
├─ airflow/
│  └─ dags/
│     └─ retail_daily.py
├─ dbt/
│  └─ retail-dbt/
└─ README_DATAPASS_RETAIL.md
```

## 3. Suggested learning path

### Projects

Start here to see how the labs fit together. **Projects** holds three end-to-end stories, each with 10 to 12 steps
done in the existing labs:

- **Retail end to end on Fabric / Azure Data Factory**: a web-shop CSV imported and typed in Mosaic, a SparkLab
  prototype, a second Copy activity in the Fabric pipeline, an SCD2 star in the BI Lab, dbt, a daily Airflow schedule
  and a Pipeline Lab quality gate;
- **Databricks lakehouse and machine learning**: the lakehouse demo, SparkLab exploration, a Databricks job under
  least-privilege Unity Catalog grants, MLflow training and promotion, retries, and an optional trusted-Python check;
- **Synapse warehouse to Fabric Warehouse**: SQL pool distributions, partitions and procedures, a Synapse pipeline,
  SQL lineage and star model checks, and a port to Fabric Warehouse.

Open a project, then for each step: **Open in <lab>** creates the files the step needs (never overwriting yours),
opens the file or exercise beside the Workbench and shows the right lab tab. Do the step there, come back to
**Projects** and click **Verify** (the runtime must be running). **Verify remaining steps** checks every
step not verified yet; the next suggested step is shown above the list.

- **verified**: Datapass checked the step on your workspace (catalog tables, read-only SQL, or what the lab really ran,
  recorded by the runtime). Each check shows its truth: real, simulated, emulated, hybrid or static analysis.
- **ticked by hand**: you ticked the step yourself. It counts in your progress, drawn apart, and is never shown as
  verified. Steps without an automatic check (runbooks, notes) are ticked this way.

Progress is a normal workspace file, `.datapass/progress.json` (**Open progress.json**). A verified step stays
verified if a later project changes the same tables; the latest verification is shown next to it.

### Cloud Lab

**Pipelines** tab: Data Factory pipelines for Microsoft Fabric, Azure Data Factory and Azure Synapse, simulated on your machine.

1. Choose **Create lab files**. A `factory/` folder appears. It is laid out like each product's git integration:
   - `fabric/<name>.DataPipeline/pipeline-content.json` and `fabric/<name>.Notebook/notebook-content.py`;
   - `adf/pipeline`, `adf/dataset` and `adf/linkedService`;
   - `synapse/pipeline`;
   - `databricks/Shared/*.py` (Databricks source notebooks);
   - `sql/procedures/<schema>.<name>.sql`.
2. Choose a product and a pipeline. The canvas shows the activities, with their dependencies colored by condition: green Succeeded, red Failed, blue Completed, grey Skipped. Click an activity for its details, or open a container such as If, ForEach or Switch to see the activities inside it.
3. Set the parameters and trigger. You can also make an activity fail on some attempts, change its duration or add to its output.
4. Choose a run mode:
   - **Run on local lakehouse**: Copy, Lookup, Script, stored procedures and notebooks really run on the local catalog (DuckDB, SparkLab).
   - **Dry run**: simulates every activity and changes no table.

The result explains the run status with Data Factory's leaf rule and lists every activity run with its input, output and error. It also names the tables written.

The same daily retail load exists for the three products, so you can compare them:

- Fabric: Copy → Notebook → Stored procedure → Lookup → If → Teams, plus an Outlook alert on notebook failure.
- Azure Data Factory: upsert Copy → Azure Databricks notebook → Stored procedure → Web activity.
- Synapse: CTAS in a Script activity → SQL pool stored procedure → Lookup.

The **Fabric, Azure Data Factory and Synapse: what differs** table summarizes the differences. **Pipeline exercises** opens Practice, where the `cloud-pipelines-v1` pack has 16 guided exercises: you edit a pipeline JSON (or a notebook the pipeline runs), and **Run visible** / **Submit** run it in simulated scenarios. Exercises with local data use an isolated catalog, never your lakehouse. Notebooks run on SparkLab statement by statement and are never executed as Python. Parameters work like in each product: Fabric and Synapse inject them after the parameters cell, Databricks reads them with `dbutils.widgets.get`.

**SQL pool** tab: T-SQL on a simulated Azure Synapse dedicated SQL pool or Microsoft Fabric Data Warehouse.

1. **Create lab files** (or **Restore sample files**) also writes `factory/sql/pool/*.sql`: a star schema, monthly partitions with a partition switch, a stored procedure, and the same kind of tables in Fabric Warehouse. A `-- flavor: synapse|fabric` comment at the top of a script selects its product.
2. Choose the product, a script and the scale (how many real rows one lab row stands for), then **Run script**, or **Run active .sql** for the editor you are working in. **Describe tables** only refreshes the tables.
3. Each statement shows its result. SELECT and EXPLAIN also show a distributed plan: the data movement (ShuffleMove, BroadcastMove, PartitionMove) and the partitions scanned. The tables panel shows each table's design, its rows on the 60 distributions with the skew, its partitions and whether columnstore rowgroups can be full.

Data statements really run on the local catalog (`dbo` is the `warehouse` layer), translated from T-SQL for a documented subset. Distributions, partitions and plans are modelled from the dedicated SQL pool's design rules; they are not Synapse telemetry. **SQL pool exercises** opens Practice, where the `sqlpool-v1` pack has 12 guided exercises graded on an isolated catalog.

**Databricks** tab: a simulated Azure Databricks workspace.

1. **Create lab files** also writes `factory/databricks/`: notebooks in Databricks source format, SQL files, three jobs in
   Jobs API JSON (`jobs/*.json`), the workspace compute (`compute.json`), Unity Catalog groups (`unity_catalog.json`) and
   grants (`grants.sql`).
2. **Jobs**: pick a job. The canvas shows its tasks and dependencies: If/else branches as `(true)` / `(false)`, failure
   handlers in red. Set the job parameters, the trigger, the start time and task behavior (fail on some attempts,
   duration), then **Run now** (notebook and SQL tasks really run on your lakehouse) or **Dry run** (nothing runs; you
   give the task values). The result lists every task state (Succeeded, Failed, Timed out, Upstream failed, Excluded),
   explains the run status with the leaf-task rule, and shows the compute used and its modelled cost.
3. **Catalog**: Unity Catalog `main` with one schema per layer and `ml` for models, owners and grants. Jobs with
   `run_as` run as that principal: a missing grant fails the task with `INSUFFICIENT_PERMISSIONS`.
4. **Experiments and models**: MLflow runs (parameters, metrics) and models registered in Unity Catalog, with their
   versions and aliases (`@champion`).
5. **Compute**: all-purpose clusters and SQL warehouses, and which compute fits which work (serverless, job cluster,
   all-purpose cluster, SQL warehouse).

The samples: `retail_daily_dbx` (ingest → If/else on a task value → silver → gold → SQL check on a warehouse, with a
failure alert), `power_model_training` (train a Spark ML model with MLflow as the service principal `sp-ml-training`,
gate on RMSE, promote `@champion`, batch score) and `segment_reports` (a for-each task on an all-purpose cluster).
**Databricks exercises** opens Practice, where the `databricks-v1` pack has 13 guided exercises: you write a job's JSON,
a notebook a job runs, or Unity Catalog grants, and each check runs the job on an isolated catalog.

**Lakehouse and notebooks** tab: use the flow diagram to understand the whole project:

```text
Raw orders
   ↓
Lakehouse / Bronze
   ↓
SQL or Polars transformation
   ↓
Silver
   ↓
Pipeline / scheduling
   ↓
Gold customer revenue
```

Cloud Lab is a local teaching experience. It does not require or impersonate a Microsoft Fabric workspace, an Azure subscription or a Databricks workspace, and nothing it runs leaves your machine.

### Practice

**Open solution** creates `exercises/<exercise>/<language>/solution.*` and its brief, then opens the file beside the
Workbench. The first time, Datapass also adds to the workspace settings (`.vscode/settings.json`): tab labels such
as `spark-semi-join-existence · sparklab` instead of `solution.py`, and, for Python files, the folder
`.datapass/pylance-stubs` in `python.analysis.extraPaths`. Pylance then stops flagging `pyspark` and `airflow`
imports, which Datapass simulates without installing them. Settings you already have are kept.

Your progress is saved in `.datapass/progress.json`, next to the Projects progress. An exercise is **solved** once a
**Submit** passes (Run visible never solves), **attempted** once you open or grade it, and **not started** otherwise.
The toolbar counts each status. Filter the list by difficulty, topic, language and status; the filters are kept when
you come back to Practice.

When a visible check fails, the card shows the expected rows next to yours, compared the way the grader compares them:
`−` a missing row, `+` an unexpected one, `≠` a row whose marked cells differ when row order matters. Missing, extra or
reordered columns are named. Hidden and edge-case checks stay hidden: their rows never leave the runtime.
**Show a hint** reveals the hints one at a time (the brief no longer lists them). **Show the reference solution** opens
the pack's solution and its explanation once you solve the exercise, or after three gradings that do not pass;
**Compare with my solution** opens it next to your file in VS Code's diff editor.

### Mosaic

After **Run local medallion flow** (Cloud Lab › Lakehouse and notebooks) has loaded the CSV into `bronze.orders`, open `notebooks/retail_medallion.sql` and choose **Run active SQL**: it builds `silver.mosaic_orders` and `gold.mosaic_customer_revenue` on real DuckDB. Mosaic SQL works on the shared catalog only; file and network table functions such as `read_csv_auto` are blocked by design.

To bring your own data, use **Import file…** in Mosaic's *Local data runtime* block and name a **new** `bronze.<table>`. The extension reads the file and sends its content to the runtime, so the runtime never gets a file path, and imports never overwrite an existing table.

- **CSV** (UTF-8, up to 1 MB / 5,000 rows, simple unique headers): every column is stored as text, so `CAST` in SQL when you build silver tables, e.g. `SELECT CAST(amount AS DOUBLE) AS amount FROM bronze.my_orders`.
- **Parquet** (up to 10 MB / 100,000 rows): the column types come from the file.
- **JSON** or JSON Lines (`.json`, `.jsonl`, `.ndjson`, same limits): DuckDB's `read_json_auto` infers the types; nested objects become `STRUCT` columns.

Three tools help you explore and tune, all real DuckDB on your local catalog:

- **Profile** on a catalog row runs `SUMMARIZE`: per column the type, min, max, approximate distinct count, average, standard deviation, quartiles, count and share of NULLs.
- **Explain active SQL** runs `EXPLAIN ANALYZE` on the active SQL file, or only on its selection. The query runs once, and the plan shows each operator with its rows and time. Read it from the scans at the bottom up to the result; **Open in editor** shows it full width in a read-only tab.
- **Query history** in the SQL block keeps your last 30 runs and plans in this workspace (VS Code workspace state, not a project file), with **Run again** and **Open file**.

### SQL dialects: write T-SQL, Snowflake, BigQuery, Spark SQL or PostgreSQL

A `.sql` file can be written in another dialect, like choosing a notebook's kernel. The status bar shows
**SQL: DuckDB ▾** on SQL files: pick T-SQL, Snowflake, BigQuery, Spark SQL (ANSI) or PostgreSQL and it writes the first
line `-- dialect: tsql` (DuckDB removes the line). **Run active SQL** and **Explain active SQL** then translate the file
to DuckDB and run the translation on the local catalog. Mosaic shows the translated SQL next to the result, the rules
that kept the dialect's result (for example "Integer / integer is an integer division that truncates, as in T-SQL"),
and the label **"T-SQL dialect translated to DuckDB, not SQL Server"**: it is not the real engine and nothing connects
to one. Each dialect accepts a documented subset (`runtime/sqldialects/README.md`); anything outside it is refused by
name, for example `PATINDEX is not in the supported T-SQL subset`. **Open translated SQL** shows the DuckDB SQL in a
read-only tab.

Open the SQL and Python scratch files and compare:

- DuckDB SQL transformations;
- Polars transformations;
- project notes;
- local runtime status.

Files remain normal VS Code files.

The **Catalog** view in the Datapass sidebar lists every table and view of the local catalog by layer, with columns, types and row counts. Click a table to open a SQL scratch (`SELECT * ... LIMIT 100`) or use the ▶ **Preview Rows** action to see its first rows in Mosaic.

### SparkLab

Use **SparkLab / ZilaCode** for bounded PySpark DataFrame practice.

1. Start the runtime.
2. Click **Open SparkLab scratch** (creates `notebooks/sparklab.py`).
3. Pick a virtual cluster profile and AQE setting, then **Run active SparkLab file**.

The source is parsed by a whitelist, never executed as Python. Result rows and compiled SQL are real local computation; the logical plan is a teaching plan; stages, shuffle, virtual duration and credits are explicitly simulated. The supported API is deliberately narrower than PySpark and unsupported syntax is rejected.

For targeted Spark practice, filter Practice on **Spark lab**: 12 exercises on DataFrame pitfalls (left-join filters, semi joins, `eqNullSafe`, join fan-out, RANGE vs ROWS frames, ...) and plan choices (broadcast joins, `coalesce` vs `repartition`, one-pass aggregation, windows instead of self-joins). Plan exercises are also graded on the simulated Spark plan at the input sizes shown in their brief, for example "at most one shuffle exchange".

### Trusted local Python (opt-in)

Python/Polars files are not executed by default. To run them from Mosaic (**Run active Python**), Practice or Pipeline Lab, choose **Enable trusted local Python…** in Mosaic's Python / Polars block and confirm the warning. This executes real local code with your permissions; the runtime worker is not a sandbox. The choice is stored as `runtime.trustedLocalPython` in `.datapass/project.json` plus a confirmation on this machine, and requires VS Code Workspace Trust.

### Pipeline Lab

Open `pipelines/main.pipeline.py`.

The source is compiled through a bounded AST into the shared graph view. Source code is **not executed by the compiler**.

Start the Datapass runtime from the Workbench header before compiling the pipeline.

### BI Lab

Open **BI Lab** and choose **Create lab files**: `bi/warehouse/` gets scripts that build a small star schema from CRM,
ERP and shop sources (a date dimension, a type 2 customer dimension, a flattened product hierarchy, a junk dimension,
sales and returns facts) and `bi/model.json` describes the star. **Build warehouse** runs the scripts on the local
DuckDB catalog, then:

- **Star model** draws the star and checks it on the data: keys, grain, SCD2 validity, orphans, relationship
  cardinality, one active path between two tables (the ship date is an inactive, role-playing relationship);
- **Lineage** traces every column back to its source columns, shows which columns decide the rows, and answers
  "what does a change to this column reach?";
- **dbt** runs `bi/dbt/`, the same warehouse built the dbt way (staging views, an ephemeral intermediate
  model, marts with an incremental fact, a snapshot, tests and macros), with the Datapass dbt emulation: pick
  build, run, test, seed or snapshot, a selection (`+fct_sales`, `tag:daily`) and `--full-refresh`, then read the
  DAG, each node's status, failing test rows, compiled SQL and column lineage. No dbt install is needed; it
  follows dbt Core and dbt-duckdb for a documented subset but is not dbt Core (the README in `bi/dbt` shows how to
  run the same project with dbt Core);
- **Concepts** is a data warehousing sheet (SCD types, fact table types, keys, dimension patterns, additivity), each
  item linked to a Practice exercise of the `dwh-v1` pack.

### Airflow Lab

Choose **Create starter DAG** (writes `airflow/dags/retail_daily.py`, a real Airflow 3 DAG file), start the runtime, then **Simulate active DAG file**. Datapass parses the file without executing it and shows:

- the runs the scheduler would create at the chosen scheduler clock (timetable, `start_date`, `catchup`, manual runs);
- a grid of task states per run, as in Airflow's Grid view;
- the graph, the task instances and a timed log of the selected run, with **Start** / **Step** / **End** replay;
- the rendered `{{ ds }}`-style templated fields.

The **Scenario** form decides what the simulated world does: a task fails once, twice or always, how long it takes, when a sensor's file arrives, which path a branch chooses. A parser error shows its line with **Go to line**. The old `airflow/main.dag.json` spec is no longer simulated.

This is a deterministic scheduler simulator with Airflow 3 semantics, not an Airflow installation: no task code, connection or worker runs.

For targeted Airflow practice, filter Practice on **Airflow**: 13 exercises where you write a real Airflow 3 DAG file (dependencies, TaskFlow, catchup, cron, data intervals, `{{ ds }}` templates, retries, trigger rules, a failure watcher, branching, sensors, `default_args`). The file is parsed, never executed, and graded on simulated runs and task states.

### dbt Lab

The dbt Lab is the real-life dbt lab: real dbt Core and dbt-duckdb, typed in a real VS Code terminal, on the local
catalog. (The BI Lab keeps the guided dbt emulation.)

1. **Install dbt tools** (once). Datapass asks first, then creates a separate Python environment in its extension
   storage with dbt Core and dbt-duckdb, DuckDB pinned to the runtime's version. It needs Python 3.10–3.13 (found with
   `py -3.13` … on Windows, `python3.13` … elsewhere, or set `datapass.dbtTools.python`). Nothing is installed silently.
2. Pick a project: every folder with a `dbt_project.yml` is listed. **Create retail sample** copies `dbt/retail-dbt`.
3. Choose a command (`build`, `run`, `test`, `seed`, `snapshot`, `compile`, `deps`, `docs generate`, `debug`, `parse`),
   `--select`, `--exclude` and `--full-refresh`, then **Run in terminal**. Datapass opens a terminal in the project
   folder, with the managed tools first on `PATH` and `DBT_PROFILES_DIR` set to `.datapass/dbt/`, and types the real
   command. Edit it and press Enter to run it again, or type any other dbt command there.
4. `.datapass/dbt/profiles.yml` is generated: one DuckDB output per project profile, on
   `.datapass/data/workspace.duckdb`, schema `dbt_dev` (projects with their own `generate_schema_name` build into the
   catalog layers). No secrets, never inside the project. dbt's anonymous usage statistics are turned off.
5. **Catalog handoff.** DuckDB lets one process write the file. When a `dbt` (or `dct`) command starts in that
   terminal, the runtime closes the catalog ("Catalog lent to dbt" in the lab and in the Catalog view); when it ends,
   the runtime reattaches it and the Catalog view shows what dbt built. VS Code's shell integration reports both
   moments (bash, zsh, fish, PowerShell). In a shell without it, such as cmd.exe, click **Reattach catalog** when the
   command has finished. You no longer stop the runtime by hand.
6. After a run the lab reads `target/manifest.json` and `target/run_results.json`, labelled **dbt Core (real)**: the
   command, dbt version, invocation, status counts, the DAG colored by status (tests optional), failures and warnings,
   and each node's message, file and compiled SQL. `dbt parse` shows the DAG without touching the database.
7. **dbt Charts.** The same tools include dbt Charts (`dct`, Apache-2.0, pre-1.0, pinned to 0.8.x). A project with a
   `dbt_charts.yml` (a `dbt_profile` source) lists its boards (`charts/*.yml`, whose queries `ref()` the dbt models).
   **Validate** types `dct validate <board>` (no database) and shows the result next to the board; **Render PNG**,
   **Render data (JSON)** and **Render HTML** type `dct render <board> --format …` (output in `renders/`, the catalog is
   lent like for dbt). The PNG shows in the lab, the JSON shows each chart's data, and the HTML (which carries scripts)
   opens in your browser, never inside the Workbench. **dct serve** starts the live preview on a free loopback port
   (`--host 127.0.0.1`) in its own terminal and opens it in VS Code's Simple Browser; **Stop dct serve** closes it and
   the catalog comes back. Build the models first: boards read what dbt built. If you installed the dbt tools before
   dbt Charts was added, use **Update dbt tools**.
8. **Missions** (the dbt Lab's second tab). Five tickets from the analytics team, less guided than Practice: context
   and a request, acceptance criteria, hints one at a time when you ask, no pre-chewed starter.
   - *Last night's build failed on a unique test* (intro): reproduce, diagnose, fix without weakening the test.
   - *Know when a source stops arriving* (intro): source freshness, then `dbt source freshness`.
   - *Keep order history when the shop exports only what changed* (intermediate): an incremental model, then
     **Load next batch** (tomorrow's export) and run it again.
   - *Backfill three days the scheduler missed, then schedule the job* (intermediate): `--select tag:daily --vars`, then
     an Airflow 3 DAG file that the Airflow Lab's simulator replays (parsed, never executed).
   - *A sales board in dbt Charts* (intermediate): a board on the mart that validates and renders.

   **Start mission** copies the team's project to `missions/<id>/` (never overwriting your files), writes `TICKET.md`,
   loads the mission's data into its own schemas and selects the project. Work with the real tools, then **Check my
   work**: a hidden checker runs read-only SQL on your catalog and reads your own dbt artifacts, your files, the real
   `dct validate` and the simulated Airflow schedule. **Start over** reloads the data and drops what dbt built for the
   mission; your files stay. Progress lives in `.datapass/missions/progress.json`.

### Terminal Lab

The Terminal Lab is a real bash, PowerShell and Git terminal opened by VS Code. Datapass never types or runs a
command in it; a hidden checker reads the folder and the Git repository the learner leaves behind.

1. Open **Terminal Lab**. Pick a shell: bash (Git Bash on Windows) or PowerShell (pwsh, or Windows PowerShell 5.1 if
   that is all you have). The choice is remembered. **Refresh** looks again if you just installed one.
2. Pick a mission and **Start mission**. Datapass builds the mission folder under `missions/<id>/` from the pack
   (files, and for the Git missions a small repository with a fixed history) and writes the ticket to
   `.datapass/missions/tickets/<id>.md`.
3. **Open terminal and ticket** opens the ticket beside the Workbench and a terminal in `missions/<id>/` with the
   shell you chose. Work there with your own commands; nothing is pre-typed.
4. **Check my work** asks the hidden checker to read the folder and, for the Git missions, the repository (read-only
   Git commands). It reports which acceptance criteria pass. **Show a hint** reveals the mission's hints one at a
   time.
5. **Start over** rebuilds the mission from scratch. The old folder is moved to
   `.datapass/missions/attic/<id>-<time>/`, never deleted, so earlier attempts stay on disk if you want to compare.

Git commits made in the Terminal Lab use your global Git identity; the lab shows a warning banner if
`git config --global user.name`/`user.email` are not set, since `git commit` would otherwise refuse to run.

### Infra Lab

The Infra Lab is a simulated terminal: Terraform, Docker, `kubectl` and `az` all answer from Datapass's simulators.
Nothing is provisioned, built or deployed, and no real `terraform`, `docker`, `kubectl` or `az` is needed or run,
even if you have one installed.

1. Open **Infra Lab**, start the runtime, and pick a mission.
2. **Start mission** builds the mission folder under `missions/<id>/` (files, and the mission's simulated starting
   world: a subscription, a Docker engine, a cluster), opens the ticket, and opens the simulated terminal.
3. Type `terraform`, `docker`, `kubectl` or `az` commands in that terminal, exactly as you would in a real one; type
   `help` for what the shell accepts. Your files (HCL, Dockerfiles, compose YAML, Kubernetes manifests) are edited in
   VS Code as normal.
4. **Check my work** reads the simulated world your commands built (Terraform state, the simulated subscription,
   Docker images and containers, the cluster) and reports which acceptance criteria pass. **Show a hint** reveals the
   mission's hints one at a time.
5. **Start over** rebuilds the mission from scratch; the old folder is moved to `.datapass/missions/attic/`, never
   deleted.

## 4. Runtime

**Setup runtime** creates a private Python environment for the runtime and installs its engines, once per machine. It uses [uv](https://docs.astral.sh/uv/) when it is installed and pip otherwise; the setup card says which one it uses. On Windows, uv made the first setup about ten times faster (about 14 s instead of about 146 s).

The extension starts one loopback FastAPI runtime on a free local port:

```text
127.0.0.1:<free port>
```

The runtime currently owns local services such as:

- DuckDB / DuckLake-oriented data work;
- Polars/Python support;
- bounded SparkLab support;
- pipeline compilation and local workflow services;
- dbt adapters.

The runtime is a local IPC/control plane, not a separate Datapass web application.

## 5. Truth model

| Surface | What is real | What is simulated |
| --- | --- | --- |
| Projects | checks on the workspace catalog (tables, read-only SQL) and the runtime's own journal of what the labs ran | nothing of its own: each check carries the truth of the lab it reads; ticks by hand are declarations, never verifications |
| Mosaic | VS Code files, DuckDB SQL; Python/Polars only after trusted-Python opt-in | optional teaching overlays |
| Practice | VS Code files, local tests/runners | exercise scenarios where explicitly marked |
| Cloud Lab | local files, DuckDB/DuckLake; pipeline Copy, Lookup, Script, stored procedures and SparkLab notebooks on the local catalog; SQL pool data statements (T-SQL translated to DuckDB); Databricks notebook and SQL tasks, Spark ML fits, Unity Catalog checks | Fabric UI, pipeline orchestration (Data Factory semantics), every other activity (Web, Teams, Outlook, dataflows...); SQL pool distributions, partitions, rowgroups and data movement; Databricks job orchestration, compute, start times and cost; MLflow as local data |
| SparkLab | whitelist parser, compiled SQL and result rows computed locally | stages, shuffle exchanges, duration, credits, cluster behavior; Practice plan checks grade this model |
| BI Lab | warehouse SQL scripts and model checks on DuckDB; the SQL of dbt models | column lineage is a static analysis of the SQL text; dbt's behaviour is emulated (not dbt Core); no Power BI |
| dbt Lab | dbt Core + DuckDB when installed | static lineage fallback is not execution |
| Airflow Lab | DAG files (Lab and Practice) are parsed, never executed | scheduler/executor/task runtime, runs, task states, logs, rendered templates |
| Pipeline Lab | source files, bounded compiler, SQL/quality execution; Python/Polars after trusted-Python opt-in | scheduler/service semantics; dbt activity declared only, never executed or reported as success |

The UI should always preserve this distinction.
