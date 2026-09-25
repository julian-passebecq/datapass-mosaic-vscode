# Exercise authoring

Practice exercises live in versioned packs under `content/exercise-packs/<pack>/`. The runtime registry (`runtime/datapass_runtime/exercise_packs.py`) validates every pack at import; the extension catalog (`src/exerciseCatalog.ts`) reads the same files for the Practice UI.

## Pack formats

- **Per-language pack**: `manifest.json`, `exercises.json` (public definitions), `grading.server.json` (reference solution + fixtures per exercise id). Example: `sql-lab-v1`, `internal-demo`.
- **Semantic pack**: `manifest.json`, `scenarios.json`, `grading.server.json`. One scenario and one fixture set expand into several language variants (`sql`, `python`, `polars`, `sparklab`, `dbt`) registered as `<scenario>-<language>`. Example: `unified-retail-v1`.

Every exercise needs exactly one visible, and any number of hidden and edge fixtures; the public `visible_checks` / `hidden_check_refs` / `edge_check_refs` must match the private fixture ids. **Run visible** grades only visible fixtures; **Submit** grades all of them. Grading compares complete result rows (`validation`: exact schema, bag semantics, numeric tolerance, optional `ordered`); truncated results never pass.

## Fixture tables

- Single table: fixtures use `input_rows`; the submission reads the table `input`. This works for every language.
- Named tables: declare one `data_context` entry per table (`name`, `columns`, `sample_rows`) and give every fixture `"input_rows": []` plus `"tables": {"<name>": [rows...]}` with exactly the declared tables. Binding per language:
  - SQL: one typed CTE per table (`FROM orders`);
  - SparkLab: the same CTEs plus parser schemas (`spark.table("orders")`); simulated scan statistics use the fixture row counts;
  - Python/Polars: each table is a variable holding a list of row dicts (`orders`), and all of them are in `tables`;
  - dbt drills: not supported (they bind only `ref("input")`); the registry rejects them rather than approximating.
  Names are lowercase identifiers and cannot be a catalog layer (`source`, `bronze`, ...) or a Python grading helper (`display`, `query`, `publish`, `tables`, `input_rows`).
- Python results: `display(rows)` a list of row dicts (or a DataFrame). An empty list has no columns, so pass `display(rows, columns=[...])` when a result can be empty. Keep dates as `YYYY-MM-DD` strings so SQL DATE output and Python strings compare equal.
- Column types are applied with `CAST`, so dates, decimals and empty fixtures stay typed. Allowed: `INTEGER`, `BIGINT`, `DOUBLE`, `VARCHAR`, `BOOLEAN`, `DATE`, `TIMESTAMP`, `DECIMAL(p,s)`. Write dates as `YYYY-MM-DD` strings; results serialize dates the same way.
- At most 200 rows per table and per expected result.

## SparkLab plan checks

A SparkLab exercise may add `spark_plan` to its public definition. Grading then also checks the plan SparkLab models for the submission (`runtime/sparklab/physical.py`), next to the result-row fixtures:

```json
"spark_plan": {
  "profile": "generic_8x8",
  "aqe": true,
  "scale": {
    "sales": {"rows": 600000000, "bytes": 77309411328, "partitions": 576},
    "stores": {"rows": 40000, "bytes": 50331648, "partitions": 1, "catalog_statistics_available": true}
  },
  "checks": [
    {"id": "plan-broadcast-join", "description": "The sales-stores join is a broadcast hash join.", "rule": "min_broadcast_joins", "value": 1},
    {"id": "plan-single-shuffle", "description": "Only the groupBy(\"region\") shuffle exchange remains.", "rule": "max_exchanges", "value": 1}
  ]
}
```

- `scale` gives authored sizes per table read (optional `hot_fraction` for skew). The model plans at these sizes; the fixture rows are still what executes. Sizes are shown in the brief and labeled as not processed.
- Rules: `max_exchanges`, `min_broadcast_joins`, `max_shuffle_joins`, `max_global_windows` (windows without `partitionBy`), `max_output_partitions`. Check ids start with `plan-` and cannot reuse a fixture id.
- The exercise fixes `profile` and `aqe`, so the learner's SparkLab panel selection never changes a grade.
- Plan checks are public and run on **Run visible** and **Submit**. They are graded once, on the first successful run; a submission that does not run fails them.
- Only build a plan lesson on behavior real Spark shares. The model counts one exchange per unsatisfied clustering requirement (hash, range, round-robin or single partition), reuses an existing hash partitioning on a subset of the required keys, keeps the streamed side's partitioning through a broadcast join, refuses a broadcast above 8 GB, and applies EliminateSorts under joins and MIN/MAX/COUNT aggregates. It does not model filter selectivity, AQE join conversion or column pruning, so do not grade on those.

## Quality gate

`python scripts/exercise_packs_smoke.py` (CI runtime job) grades every installed exercise through the real worker:

1. the reference solution must pass a full submission;
2. the starter must not pass;
3. each **mutant** in `MUTANTS` must run successfully and still fail. A mutant is the plausible wrong answer the lesson is about (INNER instead of LEFT JOIN, RANK instead of DENSE_RANK, a filter in WHERE instead of ON, ...). If a mutant passes, the hidden/edge fixtures do not discriminate the mistake: add a fixture that does.

When adding an exercise: design the hidden and edge fixtures around the pitfall, compute expected rows by running the reference solution, **review every expected row by hand**, then add at least one mutant.

For a SparkLab plan lesson whose starter already returns the right rows, add the exercise to `PLAN_ONLY_STARTERS`: the gate then requires the starter to pass every result check and fail at least one plan check, so the lesson stays about the plan.

## Installed packs

| Pack | Language(s) | Exercises | Notes |
| --- | --- | --- | --- |
| `sql-lab-v1` | SQL | 60 | All 60 donor SQL lab challenges |
| `engine-lab-v1` | SQL, pandas (`python`), Polars, SparkLab | 20 scenarios / 68 variants | Donor engine lab; SparkLab only where its bounded API supports the operation |
| `python-lab-v1` | Python | 12 | Donor curriculum lessons that transform data |
| `de-patterns-v1` | SQL | 16 | Authored data-engineering patterns: typing imported CSV text, CDC dedup, NULL-safe anti-join, gaps and islands, sessionization, ASOF joins, SCD2 ranges, upsert results, data-quality rules, calendar spines, funnels, medians, cohorts, delimited lists, watermarks, COUNT FILTER |
| `spark-lab-v1` | SparkLab | 12 | Authored Spark lessons. Result pitfalls: left-join filter placement, semi joins, `count(col)` vs `count("*")`, `eqNullSafe` change detection, full outer reconciliation, join fan-out, RANGE vs ROWS running totals. Plan lessons (graded on `spark_plan`): `coalesce` vs `repartition`, one-pass aggregation, broadcasting a dimension above the threshold, removing a random repartition before a window, a window instead of an aggregate self-join |
| `unified-retail-v1`, `internal-demo`, `sparklab-runtime`, `guided-spark-v1`, `pipeline-design-v1` | mixed | earlier packs | |

Donor content deliberately **not** promoted (grading compares result rows, so these cannot be graded honestly here): syntax-only Python drills (variables, printing, file/JSON I/O, pathlib, type hints), DDL/UPDATE SQL (PK/FK, SCD2), Spark I/O (`SparkSession`, `read.parquet`, `write.partitionBy`), donor `repartition` drills (partitioning is now taught through `spark-lab-v1` plan checks instead), Airflow DAG code (Airflow Lab is a simulator), pandas `validate=` errors, BigQuery `SAFE_DIVIDE` (DuckDB already returns NULL on division by zero), and the DAX, C#, bash, PowerShell, git, cron, Docker, Kubernetes, cloud and gateway tracks. Those belong to reference/cheat-sheet material (the standalone WorkNotebook), not graded Practice.

## Provenance

Record `origin` (`authored` or `migrated`) and a `provenance.source`. `sql-lab-v1` adapts the Datapass `leetcodedataeng` SQL lab (T-SQL rewritten for DuckDB) with newly authored fixtures. Do not import third-party question corpora.

## Known limitation

`grading.server.json` ships inside the VSIX, so a determined learner can read reference solutions and hidden fixtures. Grading integrity is a teaching aid, not an exam control.
