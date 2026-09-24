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
3. Choose **Fabric Lab**.
4. Click **Create retail end-to-end demo**.

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
│  └─ main.dag.json
├─ dbt/
│  └─ retail-dbt/
└─ README_DATAPASS_RETAIL.md
```

## 3. Suggested learning path

### Fabric Lab

Use the flow diagram to understand the whole project:

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

Fabric Lab is a local teaching experience. It does not require or impersonate a Microsoft Fabric workspace.

### Mosaic

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

Open `airflow/main.dag.json`.

Use **Step** or **Run to end** to inspect:

- dependencies;
- retries;
- retry delay;
- trigger rules;
- upstream failures;
- simulated logs.

This is a deterministic scheduler simulator, not an Airflow installation.

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
| Fabric Lab | local files, DuckDB/DuckLake | Fabric UI/orchestration semantics |
| SparkLab | whitelist parser, compiled SQL and result rows computed locally | stages, shuffle, duration, credits, cluster behavior |
| dbt Lab | dbt Core + DuckDB when installed | static lineage fallback is not execution |
| Airflow Lab | project DAG definition | scheduler/executor/task runtime |
| Pipeline Lab | source files, bounded compiler, supported local activity execution | scheduler/service semantics; dbt pipeline activity not wired yet |

The UI should always preserve this distinction.
