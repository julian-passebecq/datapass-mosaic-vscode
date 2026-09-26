# Changelog

All notable changes to the Datapass Workbench extension. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).
Each version's section becomes the notes of its GitHub Release (see docs/RELEASE.md).

## [Unreleased]

## [0.2.0] - 2026-09-26

The first version built on the full plan's V1: a Today home, and the Lakehouse, API and deeper Infra labs.

### Added

- **Home and navigation**: a Today home and module navigation grouped by family (#60).
- **Mosaic**: Import CSV, Parquet and JSON into the catalog; data profiles, `EXPLAIN ANALYZE` and query history; SQL
  dialects chosen like a kernel with a `-- dialect:` header and the translated SQL shown (#4, #34, #41).
- **SQL dialects**: one translator for T-SQL, Snowflake, BigQuery, Spark SQL and PostgreSQL, run on DuckDB and
  labelled as translated (#19, #38, #39, #42).
- **Practice**: packs for data-engineering SQL, Spark, Airflow, cloud pipelines, Databricks, warehousing, dbt,
  ZillaCode (52 problems in six languages) and Spark SQL; expected-vs-actual feedback with hints; progress and filters;
  an arena with one card per problem; spaced review; interview mode (#6, #7, #11, #14, #15, #16, #27, #29, #31, #44,
  #48, #49, #57).
- **Labs**:
  - Airflow Lab: an Airflow 3 scheduling simulator on Python DAG files, including `depends_on_past` (#8, #9, #56).
  - Cloud Lab: simulated Fabric, Data Factory and Synapse pipelines, a Synapse / Fabric Warehouse SQL pool, and
    Databricks jobs, compute, Unity Catalog and MLflow (#10, #12, #13).
  - BI Lab: warehouse SQL, SQL lineage, star models and the Datapass dbt emulation (#15, #16).
  - dbt Lab: real dbt Core and dbt Charts in a VS Code terminal with a catalog handoff, and missions checked by a
    hidden checker, including snapshots and model contracts (#18, #22, #25, #32, #33, #55).
  - Terminal Lab: real bash, PowerShell and Git missions (#35, #37, #43).
  - Infra Lab: simulated Terraform, Docker, monitoring and Kubernetes, then modules, `fmt`, Ingress/HPA and compose
    volumes and networks (#50, #52, #61).
  - Spark Lab: Polars as a lightweight alternative to PySpark (#54).
  - Lakehouse Lab: Parquet, partitions, compaction, DuckLake and Delta on real local files (#62).
  - API Lab: REST ingestion into bronze from a simulated API on its own loopback port (#63).
- **Projects**: end-to-end stories whose steps are verified on the workspace (retail, Databricks lakehouse and ML,
  Synapse to Fabric Warehouse) (#20, #21, #23, #28).
- A catalog tree in the Datapass sidebar (#18).

### Changed

- Setup runtime uses uv when installed (pip otherwise), shows its progress, and updates a stale managed runtime after
  an extension update (#3, #26, #47).
- The Workbench is split per lab (one controller, contract and runtime client each) and keeps its tabs usable at
  narrow widths (#17, #53).
- Faster CI: uv caching, one build, parallel pack grading (#59).

### Fixed

- An empty catalog after the first Start runtime on Windows (#30).
- Exercise tabs readable, without false Pylance warnings (#24).

### Security

- Every runtime request carries a per-launch token and a loopback Host; webview CSP hardened (#36).

### Removed

- The unwired dbt adapter, the unused `packages/` and two caller-less runtime routes (#33, #59).

## [0.1.0] - 2026-09-24

- First VS Code extension: Mosaic, Practice and the local runtime, packaged as a VSIX from CI (#1, #2, #5).

[Unreleased]: https://github.com/julian-passebecq/datapass-mosaic-vscode/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/julian-passebecq/datapass-mosaic-vscode/releases/tag/v0.2.0
