# Query performance

Cheatsheet for the Learning paths *Spark and the data platforms* and *BI, governance and performance*. Measure on the
engine you run: the Lakehouse Lab reads pruning from DuckDB's own `EXPLAIN ANALYZE`; SparkLab's stage and shuffle
figures are simulated.

## Read less

| Technique | Works when |
|---|---|
| Column pruning | columnar files (Parquet, Delta): select only needed columns |
| Partition pruning | the filter is on the partition column itself (`WHERE order_date = DATE '2026-10-01'`) |
| File skipping | min/max statistics per file or row group match a selective filter; sorted or clustered data helps |
| Predicate pushdown | the filter reaches the scan instead of running after it |

## File layout

- Target files of roughly 128 MB to 1 GB. Thousands of tiny files spend the time on listing, opening and footers.
- Compact: Delta `OPTIMIZE`, DuckLake compaction, or fewer output partitions at write time.
- Partition on low-cardinality columns that queries filter on (date, region). Never on a key with millions of
  values; cluster or sort by it instead (Z-order, liquid clustering).

## Joins

- Broadcast (replicate) the small side; co-locate large tables on the join key (Synapse `HASH`, bucketing).
- Aggregate before joining when the join fans out.
- Check skew: one key with a large share of rows makes one task slow.

## Reading a plan

| Tool | Gives |
|---|---|
| `EXPLAIN` | the planned operators and estimates |
| `EXPLAIN ANALYZE` (DuckDB, PostgreSQL) | runs the query; actual rows and time per operator |
| Spark UI / `df.explain()` | stages, tasks, shuffle sizes / the physical plan |
| Synapse `EXPLAIN`, DMVs | data movement operations (shuffle, broadcast moves) |

Look for: full scans where you expected pruning, estimates far from actual rows, one slow task, large exchanges.

## Habits

Measure before and after, on the same data, more than once. Change one thing at a time. Caching hides cold-read cost.
