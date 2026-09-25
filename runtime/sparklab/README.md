# SparkLab V0.12 compatibility layer

SparkLab is an educational PySpark compatibility and distributed-runtime simulator. It is **not Apache Spark**.

One supported PySpark-style notebook expression can produce two independent forms of evidence:

1. **Semantic evidence** — a relational plan/SQL representation that can be executed against a bounded fixture (and later the real DuckDB/DuckLake case data).
2. **Distributed-learning evidence** — partition counts, stage topology, shuffle boundaries, skew, supported AQE behavior, memory/spill pressure and virtual cost derived from case-specific truth packs.

## Supported training patterns

The subset intentionally focuses on common DE notebook work rather than cloning the whole PySpark API. It includes areas such as:

- table/read access;
- `select`, wildcard `select("*")`, `filter`/`where`;
- `withColumn`, `withColumnRenamed`, `drop`;
- `dropDuplicates`, `distinct`;
- single- and multi-key joins;
- group/aggregate;
- broadcast hints;
- repartition/coalesce;
- common scalar expressions, `when/otherwise`, `cast`, `isin`, `between`;
- ordered windows including `lag`, running aggregates and explicit row frames.

Submitted code is parsed through a whitelist; arbitrary Python execution is not used.

## Cost/runtime accounting

V0.12 virtual jobs expose both useful work and allocated capacity:

- task core-hours;
- worker allocated core-hours;
- driver core-hours;
- worker node-hours;
- memory GB-hours including the driver;
- cluster slot utilization.

This prevents cold-start/driver time and idle allocation from disappearing from cost lessons.

## Static preview generation

Run:

```bash
python services/sparklab/generate_preview.py
```

to regenerate:

```text
services/sparklab/runtime_preview.json
src/runtimePreview.ts
```

A default regression test checks that these checked-in previews still match the current runtime implementation.

## Truth boundary

- **real/deterministic:** parser, supported relational semantics, bounded-fixture results, truth-pack statistics;
- **dataset-grounded simulation:** Spark stages/tasks, shuffle, skew, AQE, spill pressure, virtual duration and cost;
- **not emulated:** JVM GC, actual executor death, real network shuffle, proprietary Fabric/Databricks scheduling, or cloud wall-clock performance.


## Exchange model and plan checks (plan-driven-v2)

`physical.simulate_plan` places shuffle exchanges with Spark's planning rules instead of one shuffle per wide operator:

- an aggregate, window, `dropDuplicates`, `distinct` or join side needs rows clustered by its keys; an existing hash partitioning on a subset of those keys satisfies it and adds no exchange (two windows on the same `partitionBy` share one exchange; a join on an aggregated key reuses the aggregate's partitioning);
- narrow operators keep a hash partitioning while its key columns survive unchanged (`withColumn` over a key, `drop`, a rename or a select without the key lose it; `coalesce` and `limit` lose it);
- `repartition(n)` is a round-robin exchange, `repartition(n, *keys)` a hash exchange, `orderBy` a range exchange, a window without `partitionBy` or a global aggregate a single-partition exchange;
- a broadcast join adds no shuffle and keeps the streamed side's partitioning; a broadcast whose build side is modeled above 8 GB is refused, as real Spark fails it;
- Catalyst's EliminateSorts drops an `orderBy` whose order a later join, `distinct`, `orderBy` or MIN/MAX/COUNT aggregate discards.

`metrics.plan_facts` exposes the result (exchanges with reason, partitioning and keys, shuffle/broadcast joins, windows without `partitionBy`, output partitions, refused broadcasts). `plan_checks.evaluate` grades an exercise's declared `spark_plan` limits against these facts. Filter selectivity, AQE join conversion and column pruning are not modeled, so plan lessons must not depend on them.

## Root Runtime Pass 1

The root uses `physical.py` to turn the submitted safe logical plan into deterministic teaching evidence over the shared catalog. `capabilities.py` is the public support matrix used by API and notebook help. `cluster_profiles.json` has versioned fictional profiles; `cost.py:credits` supplies Datapass Credits without currency or vendor billing. The legacy standalone scheduler/cost APIs remain reference-compatible.

Run the `spark-window` case for the second immutable truth pack, or open the authored Account running balance exercise in shared Interview Practice. The profile/AQE selector changes only distributed estimates. Real local rows, simulated distributed metrics, assumed input statistics and unavailable behavior have separate UI labels.

See `../../docs/SPARKLAB_RUNTIME_PASS_1_HANDOFF.md` for semantics, formulas, known model limits and exact external QA commands. Optional oracle execution: `python scripts/sparklab-oracle.py --fixtures services/sparklab/oracle.json` from the repository root in an externally provisioned PySpark/JVM environment. It runs trusted checked-in developer fixtures and is never an application execution path.
