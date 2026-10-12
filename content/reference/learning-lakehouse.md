# Lakehouse storage cheatsheet

Reference for the Learning path "Lakehouse storage". The Lakehouse Lab is real and local: your SQL runs on DuckDB
inside the mission folder, DuckLake and Delta go through DuckDB's official extensions, and the checker measures the
files on disk. Iceberg is explained, never handled. The `table-formats` reference sheet compares the three formats.

## Parquet

- Columnar: a query reads only the columns it uses; each column is compressed and typed.
- Row groups carry min/max statistics per column, so readers skip groups that cannot match a filter.
- Files are immutable: an update writes new files.

```sql
SELECT * FROM parquet_metadata('lake/orders/part-0.parquet');     -- row groups and statistics
SELECT * FROM parquet_schema('lake/orders/part-0.parquet');
COPY (SELECT * FROM orders) TO 'out/orders.parquet' (FORMAT parquet);
```

## Hive partitions and pruning

```
orders/order_date=2026-10-11/part-0.parquet
orders/order_date=2026-10-12/part-0.parquet
```

```sql
COPY orders TO 'orders' (FORMAT parquet, PARTITION_BY (order_date));
SELECT count(*) FROM read_parquet('orders/*/*.parquet', hive_partitioning = true)
WHERE order_date = DATE '2026-10-12';          -- reads one folder
EXPLAIN ANALYZE SELECT ...;                    -- check how many files were actually scanned
```

- Partition by a low-cardinality column used in filters (a date, a region).
- Too many partitions mean many tiny files: listing and opening them costs more than pruning saves.
- Compaction rewrites many small files into fewer large ones with the same rows.

## Table formats

| | Delta Lake | Apache Iceberg | DuckLake |
|---|---|---|---|
| Metadata | `_delta_log/` JSON commits + checkpoints | `metadata.json` → manifest list → manifests | tables in a SQL database |
| Commit | write the next log file | swap the metadata pointer in a catalog | one database transaction |
| Multi-table commit | no | no | yes |

All three give ACID commits, snapshots, time travel and schema evolution over Parquet files. Writers use optimistic
concurrency: a commit that conflicts with a newer one fails and is retried.

## DuckLake

```sql
-- Outside the lab: INSTALL ducklake; ATTACH 'ducklake:metadata.ducklake' AS lake (DATA_PATH 'data/');
-- The Lakehouse Lab attaches each mission's lake itself and refuses ATTACH, INSTALL and LOAD.
CREATE TABLE lake.orders (id INTEGER, amount INTEGER);
INSERT INTO lake.orders VALUES (1, 40), (2, 15);
ALTER TABLE lake.orders ADD COLUMN currency VARCHAR;     -- schema evolution: a new snapshot
SELECT * FROM lake.snapshots();                          -- snapshot ids and times
SELECT * FROM lake.orders AT (VERSION => 2);             -- time travel by snapshot id
SELECT * FROM lake.orders AT (TIMESTAMP => now() - INTERVAL 1 HOUR);
SELECT * FROM lake.table_changes('orders', 2, 3);        -- rows inserted, deleted, updated
```

- Every committed change is a snapshot; snapshot ids depend on the lake's history.
- `ducklake_expire_snapshots` then `ducklake_cleanup_old_files` free the space of old versions; expired versions can
  no longer be read.

## Delta Lake

- `VERSION AS OF n` / `TIMESTAMP AS OF ...` (Spark SQL) read an older version; `DESCRIBE HISTORY` lists them.
- `OPTIMIZE` compacts small files; Z-order or liquid clustering group related rows.
- `VACUUM` deletes unreferenced files older than the retention period (7 days by default); time travel to versions
  that needed them stops working.
- Deletion vectors mark deleted rows without rewriting the file at once.
- In DuckDB: `SELECT * FROM delta_scan('path/to/table')`.

## Iceberg (concepts only in Datapass)

- Hidden partitioning: partitions come from transforms such as `day(ts)`; queries filter on `ts` directly.
- Partition evolution: change the partitioning for new data without rewriting old files.
- Delta UniForm writes Iceberg metadata for a Delta table so Iceberg readers can read the same files.
