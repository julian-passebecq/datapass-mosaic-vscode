# Datapass Workbench

Local-first VS Code data-engineering practice environment.

## Product split

- **Datapass Workbench (this repository):** Mosaic, LeetCode-style practice, local Fabric-style notebooks/pipelines, SparkLab/ZilaCode, dbt lineage, Airflow simulation and pipeline orchestration.
- **Datapass WorkNotebook (standalone web):** cheatsheets, references, lightweight playgrounds and public/free learning areas.
- **Contoso Data Studio:** separate C# application and optional dataset/case-study source.

## Core rule

VS Code owns editing, files, terminals, Git and Jupyter. Datapass owns the teaching experiences and one local Python runtime.

```text
VS Code
├─ Native editor / Explorer / Terminal / Git / Jupyter
├─ Datapass activity bar
│  ├─ Mosaic
│  ├─ Practice
│  ├─ Fabric Lab
│  ├─ SparkLab / ZilaCode
│  ├─ dbt Lab
│  ├─ Airflow Lab
│  └─ Pipeline Lab
└─ Datapass local runtime
   ├─ FastAPI control plane
   ├─ DuckDB / DuckLake
   ├─ Polars
   ├─ dbt adapter
   ├─ SparkLab simulation
   └─ workflow/scheduler simulation
```

## Harvested foundation

The branch already preserves the useful parts of the previous Datapass work rather than restarting them:

- `workbench-core/` — consolidated prior Workbench implementation/reference.
- `packages/notebook-core/` — Mosaic notebook/layout + ipynb/project contracts.
- `packages/contracts/` — shared case/workbench contracts.
- `runtime/sparklab/` — SparkLab/ZilaCode training runtime.
- `content/` — connected cases and exercise packs.
- `migration-sources/` — Fabric, Airflow/dbt and previous Workbench UI donors.
- `legacy-donors/` — selected unique curriculum/visual logic that should be promoted deliberately.
- `src/platform/` — VS Code tool/status/detection patterns.
- `src/project/` — portable local `.datapass/project.json` workspace contract.
- `src/webview/` — VS Code webview security helpers.

See `docs/ARCHITECTURE.md` for the target architecture and `docs/HARVEST_AUDIT.md` for exactly what was reused or deliberately excluded.

## Try the connected demo

Open **Fabric Lab** and choose **Create / repair demo files** to scaffold a small connected project across CSV, SQL/Polars, Pipeline Lab, Airflow Lab and dbt Lab.

See `docs/QUICKSTART.md` for the exact local test flow.
