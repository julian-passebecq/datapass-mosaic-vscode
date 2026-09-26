# lakehouselab: the Lakehouse Lab

Storage layout, taught on real local files: Parquet and Hive-style partitions, partition pruning, the small-files
problem and compaction, DuckLake tables (snapshots, time travel, schema evolution, MERGE-style changes), and a Delta
table read and appended through DuckDB's own `delta` extension. Everything is real and local. No `deltalake`,
`pyiceberg` or other new Python dependency (Julian's decision, 2026-09-26); Apache Iceberg is explained in the
Workbench, not handled.

## Truth

| Piece | Truth |
| --- | --- |
| The learner's SQL | Real DuckDB, run by **Run** in a child process whose working directory is the mission folder. DuckDB's own settings bound it to that folder (`allowed_directories`, `enable_external_access=false`, then `lock_configuration`); extension auto-install and auto-load are off; ATTACH, DETACH, INSTALL, LOAD, SET, PRAGMA, EXPORT, COPY FROM DATABASE and PREPARE/EXECUTE are refused before anything runs. It is a bound, not a security sandbox. |
| The learner's Polars file | Real Polars, run as trusted local Python (`python <file>` in the mission folder) only while trusted Python is on (`DATAPASS_TRUSTED_PYTHON=1`); refused otherwise, never a fallback. Not a sandbox. |
| DuckLake | The official DuckDB `ducklake` extension. Each DuckLake mission has its own lake in `lakehouse/<id>/lake/`: metadata `catalog.ducklake` (a DuckDB file), Parquet under `lake/data/`, data inlining off so every change is a visible file. The lab attaches it as `lake` and makes it the default database. |
| Delta | The official DuckDB `delta` extension (delta-kernel-rs inside DuckDB, no Python package). A mission's `delta` folders are attached by folder name (`ATTACH '<folder>' AS <name> (TYPE delta)`) before the connection is bounded. |
| Fixtures | Built by the runtime from the pack only (`project/` files and the mission's fixture SQL), never from a request. |
| Checks | Files measured on disk (paths, counts, bytes); rows, Parquet schemas, DuckLake snapshots and time travel read by DuckDB in the same bounded process, with the lake attached READ_ONLY; partition pruning read from DuckDB's own `EXPLAIN ANALYZE` ("Total Files Read"). |

The child process never gets the runtime's token (`DATAPASS_RUNTIME_TOKEN` and any `*TOKEN*` / `*SECRET*` variable are
removed from its environment). Runs time out (120 s for DuckDB, 180 s for Polars).

## What DuckDB's delta extension does (checked 2026-09-26, DuckDB 1.5.5, delta 45c4087)

Offline once installed: `delta_scan('<folder>')` reads; `ATTACH '<folder>' AS t (TYPE delta)` reads and **appends**
(`INSERT INTO t …` writes a Parquet file and the next `_delta_log` commit); `ATTACH … (TYPE delta, VERSION n)` reads
version n (time travel); all of it inside the mission folder's bounds. It cannot create a table
(`CREATE TABLE … AS` on a Delta catalog: "Not implemented"; no `COPY … (FORMAT delta)`), so the Delta mission ships its
`_delta_log` (two JSON commits; the file `size` fields are not used for reading) and its fixture SQL writes the
Parquet files those commits add. UPDATE, DELETE, MERGE, OPTIMIZE and VACUUM on Delta are not attempted: they are
Spark / Fabric / Databricks features. Iceberg stays out (a later option).

## The ducklake and delta extensions

DuckDB keeps extensions per user and DuckDB version (`~/.duckdb/extensions/<version>/<platform>/`). **Setup runtime**
installs `ducklake` and `delta` in its verify step (`extensions.setup_install()`, called from `runtimeVerifyArgs`); offline it
prints that the DuckLake and Delta missions need a Setup online and Setup still succeeds. Afterwards the lab only `LOAD`s it, so
it works offline. The Parquet missions (partitioning, pruning, compaction) never need it. The Workbench shows its
status; starting a DuckLake mission without it is refused with that explanation.

## Pack layout

```text
content/lakehouse/<pack>/
  pack.json                 id, title, lab, the missions in order
  fixtures/*.sql            fixture SQL, run by the runtime in the new mission folder
  <mission>/
    mission.json            the contract below (model.py)
    project/                the starter files the learner finds (solution.sql, solution.py, report.sql, …)
    solution/               one reference file per engine: scripts/lakehouse_smoke.py only, not in the VSIX
    mutants/<name>/<file>   one plausible wrong file each, which the checker must reject
```

`mission.json`: `id`, `version`, `lab: "lakehouse"`, `title`, `level`, `estimate`, `skills`, `ticket`, `engines`
(`duckdb`, `polars`), `files` (the learner's file per engine), `ducklake` (a DuckLake mission, DuckDB only),
`delta` (Delta table folders the lab attaches by name, DuckDB only), `fixture` (`sql`: paths relative to the pack; `snapshots`: the DuckLake snapshot count the fixture leaves, verified
when the folder is built), `acceptance` (criteria with hidden checks), `hints`, `concepts`.

## Check kinds (`checks.py`)

| Kind | Looks at |
| --- | --- |
| `layout` | A folder's data files: all Parquet, each in Hive folders `key=value` for exactly the given keys, in order; the number of partitions. |
| `files` | The Parquet files under a folder: count, average size (measured). |
| `untouched` | A folder still holds its fixture's file count (the source of a compaction). |
| `parquet_columns` | Columns the files must not store (partition values live in the folder names). |
| `sql` | A read-only query on the files, the lake or the Delta tables (after optional pack `before` statements, such as attaching a Delta version), compared to expected rows or to an `expected_query` (order-independent, numbers with a tolerance). |
| `pruning` | The learner's query file: its last SELECT returns the `expected_query`'s rows, and `EXPLAIN ANALYZE` of it reads at most `max_files_read` files. |
| `snapshots` | The DuckLake history: new snapshots since the fixture (`min_new`, `max_new`), snapshots still readable with time travel, the table created once (a DROP or CREATE OR REPLACE starts a new history). |

## API (`api.py`, registered in `datapass_runtime.main`)

`POST /api/local/lakehouse/missions` (the missions without their checks, the ducklake status, trusted Python),
`/extension` (re-read the ducklake status, no download), `/start {mission_id}` (build `lakehouse/<id>/`; an existing
folder moves to `.datapass/lakehouse/attic/`), `/run {mission_id, engine}`, `/check {mission_id}`,
`/storage {mission_id}` (data files and bytes per folder, DuckLake snapshots and table files).

## SparkLab

SparkLab's bounded interpreter works on catalog tables, not on files and folders, so these missions are done in
DuckDB SQL or Polars.

`scripts/lakehouse_smoke.py` plays every mission through the API: the references (every engine) pass, the untouched
starters and every mutant fail, the Run bounds refuse INSTALL / ATTACH / SET / LOAD and a file outside the folder,
Start over keeps the previous folder in the attic. `DATAPASS_REQUIRE_DUCKLAKE=1` (CI) fails instead of skipping the
DuckLake missions when the extension cannot be installed.
