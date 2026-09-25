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

### Mosaic

After **Run local medallion flow** (Cloud Lab › Lakehouse and notebooks) has loaded the CSV into `bronze.orders`, open `notebooks/retail_medallion.sql` and choose **Run active SQL**: it builds `silver.mosaic_orders` and `gold.mosaic_customer_revenue` on real DuckDB. Mosaic SQL works on the shared catalog only; file and network table functions such as `read_csv_auto` are blocked by design.

To bring your own data, use **Import CSV…** in Mosaic's *Local data runtime* block: pick a UTF-8 `.csv` (up to 1 MB / 5,000 rows, simple unique headers) and name a **new** `bronze.<table>`. The extension reads the file and sends its text to the runtime, so the runtime never gets a file path. Imports never overwrite an existing table, and every column is stored as text, so `CAST` in SQL when you build silver tables, e.g. `SELECT CAST(amount AS DOUBLE) AS amount FROM bronze.my_orders`.

Open the SQL and Python scratch files and compare:

- DuckDB SQL transformations;
- Polars transformations;
- project notes;
- local runtime status.

Files remain normal VS Code files.

### SparkLab

Use **SparkLab / ZilaCode** for bounded PySpark DataFrame practice.

1. Start the runtime.
2. Click **Open SparkLab scratch** (creates `notebooks/sparklab.py`).
3. Pick a virtual cluster profile and AQE setting, then **Run active SparkLab file**.

The source is parsed by a whitelist, never executed as Python. Result rows and compiled SQL are real local computation; the logical plan is a teaching plan; stages, shuffle, virtual duration and credits are explicitly simulated. The supported API is deliberately narrower than PySpark and unsupported syntax is rejected.

### Trusted local Python (opt-in)

Python/Polars files are not executed by default. To run them from Mosaic (**Run active Python**), Practice or Pipeline Lab, choose **Enable trusted local Python…** in Mosaic's Python / Polars block and confirm the warning. This executes real local code with your permissions; the runtime worker is not a sandbox. The choice is stored as `runtime.trustedLocalPython` in `.datapass/project.json` plus a confirmation on this machine, and requires VS Code Workspace Trust.

### Pipeline Lab

Open `pipelines/main.pipeline.py`.

The source is compiled through a bounded AST into the shared graph view. Source code is **not executed by the compiler**.

Start the Datapass runtime from the Workbench header before compiling the pipeline.

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

Open the retained `dbt/retail-dbt` sample.

Without dbt installed, Datapass can show static project lineage.

With `dbt-core` and `dbt-duckdb` available, choose **Run dbt build**. Datapass then prefers the real `target/manifest.json` artifact for lineage.

## 4. Runtime

The extension starts one loopback FastAPI runtime at:

```text
127.0.0.1:8765
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
| Mosaic | VS Code files, DuckDB SQL; Python/Polars only after trusted-Python opt-in | optional teaching overlays |
| Practice | VS Code files, local tests/runners | exercise scenarios where explicitly marked |
| Cloud Lab | local files, DuckDB/DuckLake; pipeline Copy, Lookup, Script, stored procedures and SparkLab notebooks on the local catalog | Fabric UI, pipeline orchestration (Data Factory semantics), every other activity (Web, Teams, Outlook, dataflows...) |
| SparkLab | whitelist parser, compiled SQL and result rows computed locally | stages, shuffle, duration, credits, cluster behavior |
| dbt Lab | dbt Core + DuckDB when installed | static lineage fallback is not execution |
| Airflow Lab | DAG files (Lab and Practice) are parsed, never executed | scheduler/executor/task runtime, runs, task states, logs, rendered templates |
| Pipeline Lab | source files, bounded compiler, SQL/quality execution; Python/Polars after trusted-Python opt-in | scheduler/service semantics; dbt activity declared only, never executed or reported as success |

The UI should always preserve this distinction.
