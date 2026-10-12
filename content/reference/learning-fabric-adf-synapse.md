# Fabric, Data Factory and Synapse

Cheatsheet for the Learning path *Spark and the data platforms*; see also `fabric-capacities.md` and
`synapse-dedicated-sql-pool.md`. The Cloud Lab reads real pipeline JSON and simulates the orchestration; its SQL pool
tab translates a T-SQL subset to DuckDB. There is no connection to Azure or Microsoft Fabric.

## Pipelines (Azure Data Factory, Synapse, Fabric)

| Piece | Remember |
|---|---|
| Activity | Copy, Lookup, Script, Stored procedure, Notebook, ForEach, If Condition, Until, Wait, Fail... |
| Dependency condition | Succeeded, Failed, Completed (either), Skipped |
| Linked service / connection | how to reach a store; not network access by itself |
| Integration runtime | Azure IR (cloud), **self-hosted IR** (private networks), Azure-SSIS IR; Fabric uses the on-premises data gateway |
| Parameters, variables | `@pipeline().parameters.x`, `@variables('x')`, `@activity('Lookup').output` |

**The leaf rule**: a run fails when a leaf activity fails. `Copy -> (Failed) -> Log` ends **Succeeded** if Log
succeeds: the failure was handled. Add a Fail activity to keep the run red after logging.

Common patterns: retry and timeout on each activity; ForEach with `batchCount` for parallel copies; a watermark
Lookup before an incremental Copy; Upon Completion for clean-up.

## Fabric

- One **OneLake** per tenant; Lakehouse tables are **Delta Lake**. Spark, the SQL analytics endpoint and Power BI
  Direct Lake read the same files.
- **Shortcuts** point to data elsewhere (OneLake, ADLS Gen2, S3...) without copying.
- Capacities (F SKUs) are shared by all workloads; background jobs are smoothed over 24 hours.
- **Fabric Warehouse** is T-SQL with managed distribution: no `DISTRIBUTION =` option.

## Synapse SQL

| Pool | Billing | Use |
|---|---|---|
| Dedicated | DWUs per hour; pause stops compute billing | large modelled warehouse, 60 distributions |
| Serverless | per TB processed | ad hoc queries over files in the lake |

Distribution: `HASH(col)` for large facts (high-cardinality, evenly spread, join key), `REPLICATE` for small
dimensions (under about 2 GB compressed), `ROUND_ROBIN` for staging. Prefer Parquet over CSV for serverless.
