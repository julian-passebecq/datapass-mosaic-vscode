# Spark

Cheatsheet for the Learning path *Spark and the data platforms* and the concept checks in `learning-checks-v1`.
SparkLab computes result rows locally on a bounded PySpark subset; stages, tasks and shuffle sizes it shows are
simulated teaching data, not Spark telemetry.

## How a query runs

| Term | Meaning |
|---|---|
| Transformation | `filter`, `select`, `withColumn`, `join`, `groupBy`: lazy, extends the plan |
| Action | `count`, `collect`, `show`, `write`: runs a **job** |
| Stage | pipelined narrow work; a new stage starts at every **shuffle** |
| Task | one partition of one stage, on one executor core |
| Narrow | each output partition needs one input partition (`filter`, `select`) |
| Wide | rows move between partitions by key (`groupBy`, `join`, `distinct`, `repartition`) |

## Defaults worth knowing

- `spark.sql.shuffle.partitions` = **200**.
- `spark.sql.autoBroadcastJoinThreshold` = **10 MB**: smaller join sides are broadcast, no shuffle of the large side.
- Adaptive Query Execution (on by default since Spark 3.2): coalesces small shuffle partitions, switches to a broadcast
  join when a side turns out small, splits skewed partitions of sort-merge joins.

## Habits

- Aggregate before joining when the join would fan out rows.
- One `groupBy().agg(...)` computes several metrics in one pass.
- `coalesce(n)` reduces partitions without a shuffle; `repartition(n, col)` shuffles. Use it only when a later step
  needs that distribution.
- `cache()` only pays off when the same DataFrame is reused by several actions.
- Read the plan: `df.explain()`; on a cluster, the Spark UI shows stages, task times and shuffle sizes.

## Symptoms

| You see | Likely cause |
|---|---|
| One task far slower than the others, then OOM | skew on the shuffle key (often NULL or a default value) |
| Thousands of tiny output files | too many partitions at write time |
| A job per line of a loop | an action inside a Python loop |
