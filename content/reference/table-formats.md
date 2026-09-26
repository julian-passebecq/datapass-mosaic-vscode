# Table formats: Delta Lake, Apache Iceberg, DuckLake

Reference sheet for the concept checks (pack `concepts-v1`). The Lakehouse Lab reads and appends real Delta tables and
works with real DuckLake lakes through DuckDB's official extensions; Iceberg is explained, never handled. Checked
against each project's documentation on 2026-09-26.

All three store data in **Parquet** files and add a metadata layer for ACID commits, snapshots and time travel.

| | Delta Lake | Apache Iceberg | DuckLake |
|---|---|---|---|
| Metadata | `_delta_log/`: one JSON file per commit, Parquet checkpoints | a tree: `metadata.json` → manifest list → manifests → data files | a **SQL database** (DuckDB, SQLite, PostgreSQL, MySQL) |
| Finding files | replay the log from the latest checkpoint | walk the tree (no folder listing) | query the catalog tables |
| Partitioning | partition columns, or **liquid clustering** instead of partitions | **hidden partitioning** (transforms such as `day(ts)`), **partition evolution** without rewriting | partitioning declared on the table |
| Multi-table transactions | no | no (per table) | yes: a commit is one database transaction |

## Maintenance (Delta)

- **`OPTIMIZE`** merges small files (compaction); Z-order or liquid clustering keep related rows together.
- **`VACUUM`** deletes data files no current version references and older than the retention period (**7 days** by
  default); time travel to versions needing those files stops working.
- **Deletion vectors** mark deleted rows without rewriting files.

## Interoperability

- **UniForm** writes Iceberg metadata for a Delta table from the same Parquet files, so Iceberg readers can read it; no
  data is copied.
