# Exercise authoring

Practice exercises live in versioned packs under `content/exercise-packs/<pack>/`. The runtime registry (`runtime/datapass_runtime/exercise_packs.py`) validates every pack at import; the extension catalog (`src/exerciseCatalog.ts`) reads the same files for the Practice UI.

## Pack formats

- **Per-language pack**: `manifest.json`, `exercises.json` (public definitions), `grading.server.json` (reference solution + fixtures per exercise id). Example: `sql-lab-v1`, `internal-demo`.
- **Semantic pack**: `manifest.json`, `scenarios.json`, `grading.server.json`. One scenario and one fixture set expand into several language variants (`sql`, `snowflake`, `tsql`, `bigquery`, `python`, `polars`, `sparklab`, `dbt`, `dbt-sql`) registered as `<scenario>-<language>`. Examples: `unified-retail-v1`, `engine-lab-v1`, `zilla-v1`.
  - A `dbt-sql` variant is a real dbt model on the Datapass dbt emulation: the registry turns each shared fixture into a dbt scenario whose tables are the sources of a small project (`{{ source('zilla', '<table>') }}`), builds the model (`models/<model>.sql`, from the variant's optional `model` name) and grades its table. An ordered result cannot be a model, so ordered scenarios have no `dbt-sql` variant.
  - A `snowflake` variant is graded like `sql` after the Snowflake-to-DuckDB translation (see below).

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

## Snowflake SQL exercises

Language `snowflake` (the learner writes Snowflake SQL, `solution.sql`), truth `semantic-emulation`, labelled
"Snowflake SQL dialect translated to DuckDB, not Snowflake". The query is translated with sqlglot by
`runtime/sqldialects` (see its README for the subset) and graded exactly like a `sql` exercise: the same fixtures, the
same typed CTEs, the same result contract. A query outside the subset fails the check with the refusal message (the
function's name), so references, starters and mutants must stay inside it.

Languages `tsql` ("T-SQL dialect translated to DuckDB, not SQL Server") and `bigquery` ("BigQuery SQL dialect translated
to DuckDB, not BigQuery") work the same way through the same translator. Their type-aware rules (T-SQL integer division
and integer `AVG`, CAST to integers) read the exercise's `data_context` types, so declare every fixture column's type.
Good mutants use the dialect's own semantics: `CAST(amount AS INT) / CAST(total AS INT)` is 0 in T-SQL, BigQuery's
`CONCAT` keeps a NULL (see the `eng-*-tsql` and `eng-*-bigquery` mutants).

- Only give a problem a `snowflake`, `tsql` or `bigquery` variant when its natural answer in that dialect is inside the subset.
- Unquoted identifiers are folded to lower case: keep fixture tables and columns in lower case.
- In a semantic pack the variant's runtime is `snowflake-dialect-duckdb-v1`.

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

## Airflow Lab exercises

Language `airflow`, runtime `datapass-airflow-sim-v1`, truth `simulated`. The learner's solution is an Airflow DAG file; `runtime/airflowlab` parses it (never executes it) and simulates it. There is no `data_context`. Each private fixture has `"input_rows": []`, a `scenario` and `expected` rows:

```json
{"id": "full-load-fails", "visibility": "hidden", "input_rows": [],
 "scenario": {"now": "2026-03-05T12:00:00Z", "outcome": "task_instances", "columns": ["task_id", "state"],
              "tasks": {"choose": {"branch": ["full_load"]}, "full_load": {"fail_attempts": "all"}}},
 "expected": [{"task_id": "choose", "state": "success"}, "..."]}
```

- `now` is the scheduler clock; `unpaused_at` (default `now`) matters with `catchup=False`.
- Task behavior: `duration_seconds` (default 60), `fail_attempts` (try numbers or `"all"`), `sensor_true_after_seconds` (default: never), `branch` (chosen task ids), `condition` (short-circuit result); `by_logical_date` overrides them per run; `latest_run_only` keeps the last run.
- `outcome` selects the graded table: `runs` (logical_date, run_after, data_interval_start/end, run_id, state), `task_instances` (logical_date, task_id, state, try_number, start_s, end_s, in seconds after the run starts), `rendered` (logical_date, task_id, field, value), `edges` (upstream, downstream) or `tasks`. `columns` projects it; keep one projection per exercise when you set `exact_schema`.
- The registry validates every scenario and rejects scenarios on other languages. A scenario naming a task the DAG does not have is a simulation error, so starters must keep those tasks.
- Only grade what the simulator models with Airflow 3 semantics (see `runtime/airflowlab/README.md`); describe the scenario kinds in the public sections, since hidden scenarios are not shown.

## Cloud Lab pipeline exercises

Languages `factory` (the learner writes the pipeline JSON, `solution.json`) and `factory-notebook` (the learner writes a notebook that a given pipeline runs, `solution.py`). Runtime `datapass-factory-sim-v1`, truth `simulated`. Grading goes through `runtime/factorylab` (see its README). Each private fixture has `"input_rows": []`, a `scenario` (`factorylab.exercise.ExerciseScenario`) and `expected` rows:

```json
{"id": "boundary-row", "visibility": "hidden", "input_rows": [],
 "scenario": {"flavor": "adf", "pipeline": "pl_orders_incremental", "data_plane": "local", "runs": 2,
              "files": {"datasets": {"ds_bronze_orders": {"...": "..."}}},
              "tables": [{"name": "source.orders", "rows": ["..."]}, {"name": "bronze.orders", "rows": ["..."]}],
              "outcome": "table", "table": "bronze.orders", "columns": ["order_id", "amount"]},
 "expected": [{"order_id": "O1", "amount": 10.0}, "..."]}
```

- `flavor` is `fabric`, `adf` or `synapse`: the learner's JSON is validated with that product's activities.
- `pipeline` is the pipeline name. For `factory-notebook`, it is also the key of `files.pipelines` to run, and `notebook` names the notebook reference the learner's code replaces (`fabric:<name>`, `synapse:<name>` or `databricks:/<path>`).
- The run can be shaped with:
  - `now` (the trigger time), `parameters` and `trigger_type`;
  - `activities`: per-activity behavior with `duration_seconds`, `fail_attempts` (attempt numbers or `"all"`), `fail_on_items` (ForEach items), `output` (merged into the output) and `outputs` (one output per run of the activity, the last one repeats, for polling loops);
  - `files`: the pipelines, datasets, procedures and notebooks the pipeline references.
- `data_plane: "local"` runs Copy, Lookup, Script, stored procedures and notebooks on an isolated DuckDB catalog.
  - The catalog is created in a temporary folder for each check and seeded from `tables` (at most 200 rows each).
  - Types are inferred, or set with `types` from the same allowlist as `data_context`.
  - The learner's workspace catalog is never touched.
  - `runs` (1-3) repeats the pipeline, which is how rerun-safety is graded.
- `outcome` selects the graded table:

  | Outcome | Columns |
  | --- | --- |
  | `activity_runs` | pipeline, name, type, status, attempts, start_s, end_s, iteration, parent, error_code, error |
  | `run` | status, duration_s, evaluated, return_value |
  | `variables` | name, value (as text) |
  | `inputs` / `outputs` | the `fields` paths of each activity run |
  | `table` | a table of the isolated catalog |

  `only` keeps named activities and `columns` projects the table.
- An invalid pipeline or JSON makes the check fail with "Pipeline rejected: ...". Starters and mutants must be valid pipelines that run and give wrong rows (`runnable_starters` in the pack's `quality.json`).
- Authoring: `cloud-pipelines-v1` was generated by `scripts/authoring/gen_cloud_pipelines.py`, which computes the expected rows with `datapass_runtime.factory_grading.run_fixture` on the reference, and checks that starters and mutants run and fail. Review every expected row by hand, as for the other packs.

## Cloud Lab SQL pool exercises

Language `sqlpool` (the learner writes a T-SQL script, `solution.sql`). Runtime `datapass-sqlpool-sim-v1`, truth `simulated`. Grading goes through `runtime/sqlpoollab` (see its README). Each private fixture has `"input_rows": []`, a `scenario` (`sqlpoollab.exercise.PoolScenario`) and `expected` rows:

```json
{"id": "report-movement", "visibility": "visible", "input_rows": [],
 "scenario": {"flavor": "synapse",
              "tables": [{"name": "bronze.stores", "rows": ["..."]},
                         {"name": "dbo.fact_sales", "rows": ["..."], "represented_rows": 1.2e9,
                          "design": "DISTRIBUTION = HASH(order_id), CLUSTERED COLUMNSTORE INDEX",
                          "types": {"order_id": "INTEGER"}}],
              "query": "SELECT s.region, SUM(f.amount) AS revenue FROM dbo.fact_sales AS f JOIN dbo.dim_store AS s ...",
              "outcome": "movement"},
 "expected": [{"operation": "ShuffleMoveOperation", "tables": "dbo.dim_store, dbo.fact_sales", "columns": "region"}]}
```

- `flavor` is `synapse` (dedicated SQL pool) or `fabric` (Fabric Data Warehouse): the platform rules differ (see the README).
- Each check runs on a DuckDB catalog in a temporary folder, seeded from `tables` (at most 8, 200 rows each). A table can carry the design it already has (`design`, as T-SQL table options) and how many real rows it stands for (`represented_rows`), which drives the distribution, partition and rowgroup model.
- `setup` runs T-SQL before the learner's script, `after` runs T-SQL after it (for example `EXEC` of the learner's procedure, twice for rerun-safety), and `query` is the graded query. Without `query`, the script's last SELECT or EXPLAIN is graded.
- `outcome` selects the graded table:

  | Outcome | Columns |
  | --- | --- |
  | `designs` | table, distribution, distribution_columns, index, index_columns, partition_column, partition_range, partitions, cluster_by |
  | `distribution` | table, distribution, skew_pct, skew_over_10pct, max_share_pct, empty_distributions |
  | `partitions` | table, partition_number, rows, rows_per_distribution, columnstore_ok |
  | `partition_health` | table, partitions, populated_partitions, min_rows_per_distribution, columnstore_ok |
  | `movement` | operation, tables, columns (the graded query's data movement) |
  | `scans` | table, partitions_scanned, partitions_total |
  | `result` / `table` | the graded query's rows / a table's rows |
  | `constraints` | table, kind, columns, enforced |

  `only` names the tables to report and `columns` projects the table. Grade model outputs that are robust to small data (booleans such as `skew_over_10pct`, counts of populated partitions) rather than exact percentages.
- A statement the pool refuses fails the check with "Statement n (line l) failed: ...". Starters and mutants must run and give wrong rows; `sp-fabric-port` is the exception, since its lesson is that Fabric refuses the Synapse script (`starters_refused_by_design` in `sqlpool-v1/quality.json`).
- Authoring: `sqlpool-v1` was generated by `scripts/authoring/gen_sqlpool.py`, which computes the expected rows with `datapass_runtime.sqlpool_grading.run_fixture` on the reference, and checks that starters and mutants run and fail. Every expected row was reviewed by hand.

## Cloud Lab Databricks exercises

Languages `databricks-job` (the learner writes the job, Jobs API JSON, `solution.json`), `databricks-notebook` (a
notebook a given job runs, `solution.py`) and `databricks-grants` (the workspace's Unity Catalog grants, `solution.sql`).
Runtime `datapass-databricks-sim-v1`, truth `simulated`. Grading goes through `runtime/databrickslab` (see its README).
Each private fixture has `"input_rows": []`, a `scenario` (`databrickslab.exercise.DbxScenario`) and `expected` rows:

```json
{"id": "empty-load", "visibility": "hidden", "input_rows": [],
 "scenario": {"files": {"notebooks": {"databricks:/Shared/nb_ingest_orders": "..."}, "jobs": {}},
              "tables": [{"name": "bronze.orders_raw", "rows": [], "columns": ["order_id", "net_amount"]}],
              "outcome": "task_runs", "columns": ["task", "state", "outcome"]},
 "expected": [{"task": "has_new_rows", "state": "success", "outcome": "false"}, "..."]}
```

- `files` holds the notebooks, SQL files, jobs, `compute`, `unity_catalog` (groups) and `grants` the job needs. For
  `databricks-notebook`, `job` names the job of `files.jobs` to run and `notebook` the notebook key the learner's code
  replaces; for `databricks-grants`, the learner's SQL becomes the grants (`job` is optional: access probes can run
  without a job).
- Each check runs on a DuckDB catalog in a temporary folder seeded from `tables`, with its own Unity Catalog owners and
  MLflow state. `setup_jobs` run first (for example to register model versions); `runs` (1-3) repeats the job.
- The run is shaped with `now`, `job_parameters`, `trigger_type`, per-task `tasks` behavior (`fail_attempts`,
  `duration_seconds`, dry-run `values`) and `cluster_states`.
- `outcome` selects the graded table:

  | Outcome | Columns |
  | --- | --- |
  | `task_runs` | task, kind, state, attempts, start_s, end_s, outcome, error_code |
  | `run` | result_state, duration_s, leaves |
  | `values` | task, key, value (task values as text) |
  | `compute` | kind, key, tasks, startup_s, billed_s, dbu, cost, idle_cost |
  | `table` | a table of the isolated catalog (no table: no rows) |
  | `models` | name, version, aliases, owner, inputs |
  | `mlflow_runs` | experiment, run_name, status, params, metrics |
  | `access` | principal, action, object, allowed (probes run after the job: read, write, create, register_model, load_model) |

  `only` keeps named tasks and `columns` projects the table.
- An invalid job or JSON, or a grants statement that cannot apply, fails the check with "Job rejected: ..." or
  "Grants rejected: ...". Starters and mutants must run and give wrong rows (`runnable_starters` in the pack's `quality.json`).
- Authoring: `databricks-v1` was generated by `scripts/authoring/gen_databricks.py`, which computes the expected rows with
  `datapass_runtime.databricks_grading.run_fixture` on the reference, and checks that starters and mutants run and
  fail. Every expected row was reviewed by hand.

## BI Lab warehouse exercises

Languages `warehouse` (the learner writes a DuckDB SQL script, `solution.sql`) and `bi-model` (the learner writes the
star model file, `solution.json`). Runtime `datapass-warehouse-v1`, truth `real`: SQL really runs on DuckDB, model
checks are real queries and column lineage is a static analysis of the SQL text (see `runtime/bilab/README.md`). Each
private fixture has `"input_rows": []`, a `scenario` (`bilab.exercise.WarehouseScenario`) and `expected` rows:

```json
{"id": "second-day", "visibility": "hidden", "input_rows": [],
 "scenario": {"tables": [{"name": "gold.dim_customer", "rows": ["..."], "types": {"customer_key": "INTEGER"}}],
              "runs": [{"tables": [{"name": "silver.customer_snapshot", "rows": ["day 1"]}]},
                       {"tables": [{"name": "silver.customer_snapshot", "rows": ["day 2"]}]}],
              "outcome": "table", "table": "gold.dim_customer"},
 "expected": [{"customer_key": 1, "customer_id": "C001", "...": "..."}]}
```

- Each check runs on a DuckDB catalog in a temporary folder seeded from `tables` (at most 10, 200 rows each; columns
  whose values all look like `YYYY-MM-DD` are typed DATE by the generator). `setup` SQL runs first.
- `runs` (1-3) runs the learner's script once per entry; each entry can first replace tables (the day's batch). This
  is how incremental loads and rerun-safety are graded. `after` SQL runs after the last run.
- `outcome` selects the graded table:

  | Outcome | Columns |
  | --- | --- |
  | `result` | the rows of `query`, or of the script's last SELECT |
  | `table` | the rows of `table` |
  | `checks` | check, subject, status (the model's checks; `detail` can be projected too) |
  | `relationships` | relationship, cardinality, cross_filter, active, observed, from_rows, orphans, null_keys |
  | `lineage` | table, column, source, transform for the tables or columns in `lineage_of` (`lineage_depth`: sources or origins) |
  | `impact` | table, column, effect for `impact_of` |

  `only` keeps named checks or relationships and `columns` projects the table. A `warehouse` fixture grading checks
  gives the `model`; a `bi-model` fixture takes it from the learner and grades checks or relationships only.
- Grade lineage with `lineage_depth: "origins"` and without `transform` unless the lesson is the transform: learners
  may stage data in their own tables, and origins follow them back to the fixture tables.
- A statement that fails, or a model that is not valid, fails the check with "Statement n (line l) failed: ..." or
  "Model rejected: ...". Starters and mutants must run and give wrong rows (`runnable_starters` in the pack's `quality.json`).
- Authoring: `dwh-v1` was generated by `scripts/authoring/gen_dwh.py`, which computes the expected rows with
  `datapass_runtime.warehouse_grading.run_fixture` on the reference, and checks that starters and mutants run and fail
  and that no mutant equals its reference. Every expected row was reviewed by hand.

## BI Lab dbt exercises

Languages `dbt-sql` (a model, snapshot, singular test or macro: `solution.sql`) and `dbt-yml` (a properties file:
`solution.yml`). Runtime `datapass-dbt-emulation-v1`, truth `semantic-emulation`: the Datapass dbt emulation
renders the project's Jinja in a sandbox and runs the SQL on DuckDB (see `runtime/dbtlab/README.md`). Each private
fixture has `"input_rows": []`, a `scenario` (`dbtlab.exercise.DbtScenario`) and `expected` rows:

```json
{"id": "two-days", "visibility": "visible", "input_rows": [],
 "scenario": {"file": "snapshots/customers_snapshot.sql",
              "files": {"dbt_project.yml": "...", "models/staging/_sources.yml": "...", "macros/generate_schema_name.sql": "..."},
              "runs": [{"command": "snapshot", "now": "2026-03-01 06:00:00", "tables": [{"name": "source.customers", "rows": ["..."]}]},
                       {"command": "snapshot", "now": "2026-03-02 06:00:00", "tables": [{"name": "source.customers", "rows": ["..."]}]}],
              "outcome": "table", "table": "silver.customers_snapshot", "columns": ["customer_id", "city", "dbt_valid_from", "dbt_valid_to"]},
 "expected": [{"customer_id": "C1", "city": "Paris", "...": "..."}]}
```

- `files` is the rest of the project (it must contain `dbt_project.yml`); the learner's code becomes `file`, whose
  extension matches the language. Keep a `generate_schema_name` override in `files` so custom schemas are catalog
  layers (the target schema is silver).
- Each check runs on a DuckDB catalog in a temporary folder seeded from `tables`. `runs` (1-3) are dbt commands
  (`build`, `run`, `test`, `seed`, `snapshot`) with `select`, `exclude`, `full_refresh`, `vars` and `now` (the clock
  of `run_started_at` and of check-strategy snapshots); each run can first replace tables or run `setup` SQL.
- `outcome`: `nodes` (name, resource_type, status; also failures, materialized, relation) of the last run, with
  `only` to keep some names; `table` (a relation's rows); `result` (the rows of `query`); `lineage` (table,
  column, source of `lineage_of`, origins through the project's own models).
- With a `table` or `result` outcome, a node that fails in the last run fails the check with its dbt message.
  Wrong answers of this pack may fail to build (a compile error or a missing relation is the outcome the lesson is
  about): `build_errors_are_answers` in `dbt-v1/quality.json`.
- Authoring: `dbt-v1` was generated by `scripts/authoring/gen_dbt.py`, which computes the expected rows with the
  emulation and, with `DATAPASS_DBT_PYTHON` set, runs every reference fixture through real dbt Core and compares the
  graded rows (clock-dependent snapshot columns aside). Every expected row was reviewed by hand.

## Quality gate

The pack generators live in `scripts/authoring/` (see its README).

`python scripts/exercise_packs_smoke.py` (CI runtime job) grades every installed exercise through the real worker:

1. the reference solution must pass a full submission;
2. the starter must not pass;
3. each **mutant** listed in the pack's `quality.json` must run successfully and still fail. A mutant is the plausible wrong answer the lesson is about (INNER instead of LEFT JOIN, RANK instead of DENSE_RANK, a filter in WHERE instead of ON, ...). If a mutant passes, the hidden/edge fixtures do not discriminate the mistake: add a fixture that does.

When adding an exercise: design the hidden and edge fixtures around the pitfall, compute expected rows by running the reference solution, **review every expected row by hand**, then add at least one mutant.

Mutants and gate flags live next to the pack, in `content/exercise-packs/<pack>/quality.json` (test-only: `.vscodeignore` leaves it out of the VSIX and `scripts/package_smoke.mjs` checks that it does). Adding a pack or a mutant touches only that pack's folder:

```json
{
  "flags": { "runnable_starters": true },
  "notes": { "eng-null-fill-bigquery": "BigQuery CONCAT keeps NULL." },
  "mutants": { "eng-null-fill-bigquery": ["SELECT customer_id, CONCAT(country, '') AS country_clean FROM customers"] }
}
```

| Key | Meaning |
| --- | --- |
| `mutants` | `{exercise_id: [code, ...]}`: plausible wrong answers; each must run and fail. |
| `notes` | `{exercise_id: text}`: why a mutant is wrong, when the code does not say it (JSON has no comments). |
| `flags.runnable_starters` | Starters must run cleanly and fail only on their results, so a learner never starts from a parse error. |
| `flags.plan_only_starters` | SparkLab plan lessons whose starter already returns the right rows: the gate requires the starter to pass every result check and fail at least one plan check, so the lesson stays about the plan. |
| `flags.starters_refused_by_design` | Starters whose lesson is that the platform refuses them (`sp-fabric-port`): they must fail with the platform's error. |
| `flags.build_errors_are_answers` | Wrong answers may fail to build (a dbt model that does not compile or reads a relation that was never built). |
| `flags.skip` | A reason string: the pack is not graded here (`guided-spark-v1` requires an explicitly qualified remote connection). |

The smoke refuses unknown keys, a `quality.json` whose pack is not installed and exercise ids from another pack. The generators in `scripts/authoring/` write the `mutants` of their pack with `pack_quality.write_mutants`, keeping flags and notes; for hand-written packs (`sql-lab-v1`, `engine-lab-v1`, `python-lab-v1`, `de-patterns-v1`), edit the file.

## Feedback in Practice (hints, diff, reference solution)

- `hints` are shown in Practice one at a time (**Show a hint**); the brief only says how many there are. Order them from
  a nudge to the near-answer.
- On a failed **visible** fixture, Practice diffs `expected` against the learner's rows with the exercise's own
  `validation` (`ordered`, `duplicate_sensitive`, tolerances, `forbidden_extra_columns`, `exact_schema`), the rules
  `exercise_validation.py` grades with. Graders attach rows to visible checks only; keep it that way.
- `solution.available: true` lets the learner open the reference solution from the pack's `grading.server.json`
  (`solution`, or `solutions[language]` in a scenario pack) with `explanation`, after a pass or three failed gradings.
  `scripts/practice_feedback_smoke.mjs` fails when an exercise offers a solution its pack does not ship.

## Problems, languages and spaced review in Practice

- Practice shows one card per problem. Exercises whose keys share `<pack>/<problem>` are one problem: the variants of
  a scenario pack (`<scenario>-<language>`, grouped by `semantic.id`) and, in a plain pack, exercises that share an
  `id` across languages. Languages are ordered SQL, Snowflake, T-SQL, BigQuery, Python, Polars, PySpark, dbt
  (`src/platform/practiceProblems.ts`). Give every variant of a scenario the same title and prompt: the card shows
  them once.
- Progress stays per language variant in `.datapass/progress.json` (`practice.exercises["<pack>/<problem>/<language>"]`).
- Spaced review is a Leitner schedule per variant (`src/platform/practiceReview.ts`), stored as
  `review: { "box": 1-6, "due": "YYYY-MM-DD" }` in the variant's record:
  - a passed Submit on a variant that is due, or never reviewed, moves it up one box; it is due again after 1, 3, 7,
    14, 30 or 60 days (box 1 to 6, box 6 stays at 60);
  - a Submit that fails or errors sends it back to box 1, due the next day;
  - a passed Submit before the due day changes nothing, and Run visible never moves a box;
  - a variant opened or graded before the schedule existed is due the day after its last activity.
  Days are the learner's local calendar days. Practice › Review lists the problems due today, most overdue first.
- Interview mode (`src/platform/practiceInterview.ts`) draws a series by pattern family: the first family, in
  `PATTERN_FAMILIES` order, that one of the problem's `topics` belongs to (window functions, time series,
  deduplication, joins, aggregation, nulls and quality, strings, filtering and logic). Tag problems with those topic
  names (for example `window-functions`, `gaps-and-islands`, `deduplication`, `left-join`, `group-by`, `nulls`) so
  they reach mixed interviews; a problem without a family is drawn only when nothing else fits. Interview cards hide
  hints, reference solutions and topics.

## Editor support (tab labels and Pylance)

Opening an exercise (src/exerciseWorkspace.ts) also prepares the learner's VS Code, never the grading:

- `workbench.editor.customLabels.patterns` in the workspace settings shows `<exercise> · <language>` on the tab
  instead of `solution.py`, and `<exercise> · brief` for its README;
- for Python-file languages, a `__builtins__.pyi` next to the solution declares the names the runtime injects for
  that exercise (`spark`, `dbutils`, `display`, `query`, the fixture tables, the Pipeline Lab calls). Pylance reads
  it from the file's own folder; `files.exclude` hides it from the Explorer;
- `content/pylance-stubs/` is copied to `.datapass/pylance-stubs/` and added to `python.analysis.extraPaths`, so
  `pyspark`, `airflow`, `pendulum` and `mlflow` imports resolve without installing those packages.

The stubs are generated from the readers' own import tables: after SparkLab or the Airflow Lab reader accepts a
new module or name, run `PYTHONPATH=runtime python scripts/authoring/gen_pylance_stubs.py` (CI runs it with
`--check`). `scripts/exercise_workspace_smoke.mjs` fails when a starter imports a simulated module or name that
has no stub. They are `.py` modules, not `.pyi`: Pylance reports a `.pyi` without a source as "could not be
resolved from source".

## Installed packs

| Pack | Language(s) | Exercises | Notes |
| --- | --- | --- | --- |
| `sql-lab-v1` | SQL | 60 | All 60 donor SQL lab challenges |
| `engine-lab-v1` | SQL, T-SQL, BigQuery, pandas (`python`), Polars, SparkLab | 20 scenarios / 103 variants | Donor engine lab; SparkLab only where its bounded API supports the operation; T-SQL and BigQuery re-surfaced from the donor where the reference translates and passes (not `eng-split-explode`: arrays) |
| `python-lab-v1` | Python | 12 | Donor curriculum lessons that transform data |
| `de-patterns-v1` | SQL | 16 | Authored data-engineering patterns: typing imported CSV text, CDC dedup, NULL-safe anti-join, gaps and islands, sessionization, ASOF joins, SCD2 ranges, upsert results, data-quality rules, calendar spines, funnels, medians, cohorts, delimited lists, watermarks, COUNT FILTER |
| `spark-lab-v1` | SparkLab | 12 | Authored Spark lessons. Result pitfalls: left-join filter placement, semi joins, `count(col)` vs `count("*")`, `eqNullSafe` change detection, full outer reconciliation, join fan-out, RANGE vs ROWS running totals. Plan lessons (graded on `spark_plan`): `coalesce` vs `repartition`, one-pass aggregation, broadcasting a dimension above the threshold, removing a random repartition before a window, a window instead of an aggregate self-join |
| `airflow-lab-v1` | Airflow (simulated) | 13 | Authored Airflow 3 lessons graded on simulated outcomes: fan-in/fan-out, TaskFlow data dependencies, catchup on and off, weekday cron, CronDataIntervalTimetable data intervals, `ds_add` under the Airflow 3 `@daily` default, retries, an all_done cleanup, a one_failed watcher that fails the run, a branch join, a soft-fail sensor, `default_args` overrides |
| `cloud-pipelines-v1` | Cloud Lab pipelines (`factory`, `factory-notebook`; simulated) | 16 | Authored Data Factory lessons for Fabric, Azure Data Factory and Synapse: failure alerts, always-run cleanup (Completed + Skipped), retries, timeouts, ForEach batchCount, If on a Lookup, notebook exit values, .NET date formats, an Until polling loop, the leaf rule for the run status, an ADF → Fabric port; on an isolated local catalog: a watermark incremental load, a rerun-safe upsert and a SQL pool procedure with typed parameters; notebooks in pipelines: the Fabric parameters cell and Databricks widgets with save modes |
| `sqlpool-v1` | Cloud Lab SQL pool (`sqlpool`; simulated Synapse dedicated SQL pool and Fabric Warehouse) | 12 | Authored table-design lessons: a replicated dimension, co-locating facts on the join key with CTAS + RENAME OBJECT (same data type), a skew-free distribution column, a round-robin heap for staging, RANGE LEFT vs RIGHT, partition elimination with sargable predicates, partitions big enough for columnstore rowgroups, the CTAS upsert, loading a month with a partition switch (TRUNCATE_TARGET), deduplicating under a NOT ENFORCED primary key, a rerun-safe stored procedure, porting a dedicated pool table to Fabric Warehouse |
| `databricks-v1` | Cloud Lab Databricks (`databricks-job`, `databricks-notebook`, `databricks-grants`; simulated) | 13 | Authored Azure Databricks lessons: fan-in dependencies, a failure alert with run_if (and why the run then ends Succeeded with failures), an If/else gate on a task value, setting task values in a notebook, job parameters with {{job.start_time.iso_date}}, retries without retrying timeouts, a shared job cluster instead of an all-purpose one, least-privilege grants for a job's service principal, schema-level grants that cover future tables, MLflow tracking, registering a model in Unity Catalog with the champion alias, batch scoring by alias, a for-each task over a job parameter |
| `dwh-v1` | BI Lab (`warehouse`, `bi-model`; real DuckDB) | 20 | Authored data warehousing lessons (Kimball): flattening a snowflake, surrogate keys and the unknown member, a date dimension with a fiscal calendar, a junk dimension, SCD types 1, 2 and 3, a type 1 attribute in a type 2 dimension, point-in-time joins, late arriving dimensions (inferred members), allocating an order-level amount to the grain, periodic and accumulating snapshots, a factless fact, drilling across conformed dimensions, a weighted bridge; column lineage as a control (certified revenue, personal data); star models with a role-playing date and a bridge |
| `dbt-v1` | BI Lab dbt (`dbt-sql`, `dbt-yml`; Datapass dbt emulation) | 12 | Authored dbt lessons, cross-checked with dbt Core: ref and source build the DAG (selection), a staging model, generic tests (unique, not_null, relationships, accepted_values), a singular test, test severity and where with dbt build's gating, incremental models (append filter, unique_key replacing rows), snapshots (timestamp; check with hard deletes), a type 2 dimension from a snapshot, generate_schema_name, and a ref inside is_incremental() that needs a depends_on hint |
| `zilla-v1` | SQL, Snowflake SQL (translated to DuckDB), pandas, Polars, SparkLab, dbt (`dbt-sql`) | 52 scenarios / 278 variants | The 52 ZillaCode problems (Apache-2.0, LICENSE and NOTICE in the pack), from CodeDELeet's normalized import: snake_case contracts, explicit output order and NULL/tie rules, ZillaCode's two tests as visible and hidden fixtures plus authored edge fixtures, 118 mutants. Snowflake variants for all 52, SparkLab for the 25 its subset covers, dbt for the 45 unordered ones. Generated by `scripts/authoring/gen_zilla.py` |
| `unified-retail-v1`, `internal-demo`, `sparklab-runtime`, `guided-spark-v1`, `pipeline-design-v1` | mixed | earlier packs | |

Donor content deliberately **not** promoted (grading compares result rows, so these cannot be graded honestly here): syntax-only Python drills (variables, printing, file/JSON I/O, pathlib, type hints), DDL/UPDATE SQL (PK/FK, SCD2), Spark I/O (`SparkSession`, `read.parquet`, `write.partitionBy`), donor `repartition` drills (partitioning is now taught through `spark-lab-v1` plan checks instead), donor Airflow DAG code (Airflow is now taught through the authored `airflow-lab-v1` simulator pack), pandas `validate=` errors, BigQuery `SAFE_DIVIDE` (DuckDB already returns NULL on division by zero), and the DAX, C#, bash, PowerShell, git, cron, Docker, Kubernetes, cloud and gateway tracks. Those belong to reference/cheat-sheet material (the standalone WorkNotebook), not graded Practice.

## Provenance

Record `origin` (`authored` or `migrated`) and a `provenance.source`. `sql-lab-v1` adapts the Datapass `leetcodedataeng` SQL lab (T-SQL rewritten for DuckDB) with newly authored fixtures.

Third-party question corpora are imported only when their license allows it and the user decided it. `zilla-v1` adapts ZillaCode (Apache-2.0): the pack carries the license (`LICENSE`) and a `NOTICE` with the source, the checksums of the normalized import and the modifications; every scenario keeps `provenance.source` (the ZillaCode problem), `upstream_changes` (CodeDELeet's documented corrections) and `datapass_changes`, and a visible **Source** section.

## Known limitation

`grading.server.json` ships inside the VSIX, so a determined learner can read reference solutions and hidden fixtures. Grading integrity is a teaching aid, not an exam control.
