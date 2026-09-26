# Azure Synapse dedicated SQL pool

Reference sheet for the concept checks (pack `concepts-v1`). The Cloud Lab's SQL pool tab translates a T-SQL subset to
DuckDB and models distributions for teaching; it is not Synapse. Checked against Microsoft Learn on 2026-09-26.

## DWUs and nodes

- Size is set in **data warehouse units**: DW100c to DW30000c.
- Every pool always has **60 distributions**. Scaling changes how many **compute nodes** serve them:
  DW100c-DW500c run on **1** node (all 60 distributions), DW30000c runs **60** nodes (one distribution each).
- **Pausing** stops the compute (DWU) charge; **storage is still billed** and the data is kept.

## Table distributions

| Distribution | Rows go to | Use for |
|---|---|---|
| `HASH(column)` | the distribution chosen by the column's hash | large fact tables; pick a column with many distinct, evenly spread values that you join or group on |
| `ROUND_ROBIN` | spread evenly, no key | staging tables, no obvious key |
| `REPLICATE` | a full copy on every compute node | small dimensions (Microsoft suggests under about 2 GB compressed): joins need no data movement |

A join or aggregation on columns that do not match the distribution causes **data movement** (shuffle or broadcast),
visible in `EXPLAIN` and in the request steps.

## Indexes

- **Clustered columnstore** (the default) compresses best with about **1 million rows per row group**. Each of the 60
  distributions builds its own row groups, so a table needs about **60 million rows** before every distribution fills
  one; partitioning multiplies this by the number of partitions.
- **Heap** suits staging loads; a **clustered index** suits small lookups.
