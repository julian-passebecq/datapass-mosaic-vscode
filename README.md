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

See `docs/ARCHITECTURE.md`.
