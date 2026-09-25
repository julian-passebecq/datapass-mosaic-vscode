# SQL pool Lab (sqlpoollab)

A local simulator of an Azure Synapse dedicated SQL pool (`synapse`) and of
Microsoft Fabric Data Warehouse (`fabric`), for learning table design: CTAS,
distributions, indexes, partitions, data movement and stored procedures.
Nothing connects to Azure or Fabric.

## Truth model

| Part | What happens |
| --- | --- |
| Data statements | Really run on the shared local catalog (DuckDB). Every query, DML statement and expression is translated by the shared T-SQL dialect (`runtime/sqldialects`, "T-SQL dialect translated to DuckDB, not SQL Server"): its documented subset, refusals by name and T-SQL semantics (integer division, `LEN`, `+` on strings, `DATEADD` keeping a `DATE`, `DATEPART(weekday)` with DATEFIRST 7, `CONVERT` styles, NULLs first when sorting). The pool adds its hooks: `@variables` (DECLARE/SET values), `GETDATE` and its family (a fixed lab clock), `dbo` (the warehouse layer). `OPTION (...)` hints are dropped. |
| Table designs | Kept as metadata (`sqlpool.json` next to the catalog): distribution, index, partitions, `CLUSTER BY`, constraints, statistics, identity, and how many real rows one lab row stands for. |
| Distributions | Modelled: 60 distributions. Key values that repeat in the lab rows and hold at least 1% of them are placed by a stable hash; NULL keys share one distribution; values seen once and rarer values spread evenly, since each stands for many distinct values at scale. Skew is (max - min) / max rows per distribution. |
| Partitions and rowgroups | Computed from the real rows and the boundaries (`RANGE LEFT` by default). A clustered columnstore partition is healthy with at least 1 million rows per distribution, counted at scale. |
| Plans | `SELECT` and `EXPLAIN` get a plan from the lab's planner (DuckDB parses the query; the rules below decide the data movement). The operations use Synapse's names; they are not Synapse telemetry. |

Planner rules:

- A join runs locally when one side is replicated (unless it is the preserved side of an outer join), or when both sides
  are hash distributed on the join columns, joined with `=` and of the same data type.
- Otherwise the smaller side is broadcast when it has at most 1/100 of the other side's rows, else the sides that are
  not distributed on the join column are shuffled on it (with different data types, the smaller side is shuffled).
- `GROUP BY` runs locally when the stream is distributed on a grouping column, else it shuffles. A global aggregate
  gathers the partial results (`PartitionMoveOperation`).
- Partition elimination needs predicates on the bare partition column against constants (`=`, `<`, `>=`, `BETWEEN`,
  `IN`). A function around the column scans every partition.

## Statements

`CREATE TABLE` (with `WITH (...)` options, `IDENTITY`, `NOT ENFORCED` constraints) and CTAS, `INSERT`, `UPDATE`,
`DELETE`, `MERGE`, `SELECT`, `EXPLAIN`, `CREATE VIEW`, `DROP` (`TABLE`, `VIEW`, `PROCEDURE`, `INDEX`, `STATISTICS`),
`IF OBJECT_ID(...) IS NOT NULL DROP TABLE`, `TRUNCATE TABLE`, `RENAME OBJECT`, `ALTER TABLE ... SWITCH` (with
`TRUNCATE_TARGET`), `SPLIT RANGE`, `MERGE RANGE`, `ADD CONSTRAINT`, `ALTER INDEX ... REBUILD`, `CREATE INDEX`,
`CREATE` and `UPDATE STATISTICS`, `CREATE [OR ALTER] PROCEDURE` and `EXEC`, `DECLARE`, `SET`, `PRINT`.

Statements end with `;` or a `GO` line. A procedure takes its whole batch. A script stops at its first error, as a
batch does. Tables live in `dbo` (the warehouse layer) and the lakehouse layers (`bronze`, `silver`, `gold`, ...);
temporary `#tables` and three-part names are not simulated.

## Differences between the flavors

| Topic | Synapse dedicated SQL pool | Fabric Data Warehouse |
| --- | --- | --- |
| Layout | `DISTRIBUTION = HASH(...)`, `ROUND_ROBIN` (the default) or `REPLICATE`; 60 distributions | Managed: no `DISTRIBUTION` option |
| Storage | `CLUSTERED COLUMNSTORE INDEX` (the default), ordered CCI, `HEAP`, `CLUSTERED INDEX` | Delta/Parquet in OneLake; no user indexes |
| Partitions | `PARTITION (col RANGE LEFT/RIGHT FOR VALUES (...))`, switching, split, merge | No partitioned tables; `WITH (CLUSTER BY (...))` clusters data |
| CTAS | Requires a `DISTRIBUTION` option | No table options besides `CLUSTER BY` |
| Keys | `PRIMARY KEY NONCLUSTERED ... NOT ENFORCED`, `UNIQUE ... NOT ENFORCED`, no foreign keys | The same, plus `FOREIGN KEY ... NOT ENFORCED` |
| Types | T-SQL types | `money`, `smallmoney`, `datetime`, `smalldatetime`, `datetimeoffset`, `nchar`, `nvarchar`, `tinyint`, `binary` are refused with their migration type |
| Rename | `RENAME OBJECT` | `sp_rename` (not simulated) |
| Statistics | Single and multi-column | Single-column only |

## Practice exercises

`exercise.py` defines the fixture scenario of the `sqlpool` Practice language: the flavor, seeded tables (rows, types,
their design and how many real rows they stand for), T-SQL to run before and after the learner's script, and the outcome
table that is graded (designs, distribution, partitions, partition health, data movement, scans, a query's rows, a
table's rows or constraints). `datapass_runtime/sqlpool_grading.py` runs each check on an isolated temporary catalog;
the `sqlpool-v1` pack uses it (see `docs/EXERCISE_AUTHORING.md`).

## Limits

- At most 200 statements per script; procedures nest at most 8 levels.
- Query results show at most 200 rows.
- Security, workload management, resource classes, result-set caching, materialized views and external tables
  (PolyBase, `COPY INTO`) are not simulated.
