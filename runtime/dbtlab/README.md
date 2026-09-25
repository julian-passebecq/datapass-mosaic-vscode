# dbtlab: the Datapass dbt emulation

The BI Lab's dbt tab and the `dbt-v1` Practice pack run dbt projects without dbt Core. Datapass interprets the
project the way dbt Core with dbt-duckdb does, for the subset below, on the local DuckDB catalog.

## What is real and what is emulated

| Piece | Truth |
| --- | --- |
| Jinja | Rendered by jinja2's `SandboxedEnvironment`: templates cannot reach Python objects, files, the network or modules. Nothing in a project is executed as Python. |
| SQL | The compiled SQL really runs on DuckDB, through the catalog's SQL contract. |
| dbt behaviour | Emulated for the documented subset. `scripts/dbt_oracle_smoke.py` runs the same projects through dbt Core 1.12 + dbt-duckdb 1.11 and compares every node status and every table (columns, types, rows). |

It is not dbt Core: there is no `dbt deps` (packages), no Python models, no hooks, no `run_query`, no adapter
calls and no docs site. Use real dbt Core for those.

## Supported subset

- Project: `dbt_project.yml` (name, paths, vars, config trees for models, seeds, snapshots and tests with `+`
  keys, tags that accumulate), property files (`version: 2`, `models:`, `sources:` with schema and identifier,
  descriptions, column tests, `config:`), macros (`{% macro %}`, `{{ return() }}`), and `generate_schema_name`
  overrides. Without an override, a custom schema is appended to the target schema, as in dbt; the resulting schema
  must be a catalog layer (source, bronze, silver, gold, warehouse, features, metrics).
- Jinja context: `ref` (one or two arguments), `source`, `config`, `var` (project vars and `--vars`), `this`,
  `is_incremental()`, `target` (schema, name, type duckdb), `run_started_at`, `exceptions.raise_compiler_error`,
  `log`. `env_var`, `adapter`, `run_query`, `dbt_utils` and other packages fail with a clear message.
- Parsing: every node is rendered once with `is_incremental()` false to find its refs and sources. A ref only
  reached in an incremental run fails with dbt's "unable to infer all dependencies" error until a
  `-- depends_on: {{ ref('x') }}` hint declares it.
- Materializations:
  - `view` and `table`, replacing a relation of the other type;
  - `incremental`: the first run and `--full-refresh` build the table. Later runs render with
    `is_incremental()` true into `<name>__dbt_tmp`, then insert into the table's existing columns (`on_schema_change`
    is ignore). The strategies are `delete+insert` (dbt-duckdb's default; without `unique_key` it only inserts),
    `append` and `merge` (update all columns on `unique_key`, insert the rest);
  - `ephemeral`: injected as a `__dbt__cte__<name>` CTE into the models that use it.
- Seeds: CSV files with agate-like types (integer or bigint, double, boolean, date, timestamp, text) and
  `column_types`; empty cells are NULL.
- Snapshots: `{% snapshot %}` blocks with `target_schema` (or `schema`), `unique_key` (one or several columns),
  `strategy='timestamp'` (with `updated_at`) or `'check'` (with `check_cols`, or `'all'`). Snapshots add
  `dbt_scd_id` (`md5(key || '|' || updated_at)` as in dbt), `dbt_updated_at`, `dbt_valid_from` and `dbt_valid_to`.
  `hard_deletes` accepts `'ignore'` or `'invalidate'` (and the legacy `invalidate_hard_deletes`), and
  `dbt_valid_to_current` is supported. The check strategy dates versions with the run's clock.
- Tests: `unique`, `not_null`, `accepted_values` and `relationships` generate dbt's SQL. They take arguments in the
  classic form or dbt 1.10's `arguments:` form, and use `severity` (error or warn) and `where`. They run on models,
  seeds, snapshots and sources, and are named like dbt names them. Singular tests live in `tests/*.sql`.
- Commands: `build` (seeds, snapshots, models and tests in DAG order), `run`, `test`, `seed`, `snapshot`, `compile`.
  Selection supports names and globs, `+name`, `name+` and `n+`, `tag:`, `path:`, `resource_type:`, `source:`, and
  `--exclude`. Tests are selected eagerly (when one of their parents is), and `--full-refresh` applies.
- `dbt build` gating: a failing test (severity error) or a failed or skipped node skips every node downstream of
  what the test covers. Warnings do not skip anything.

## Code

- `project.py`: loads the files and the configuration, runs the parse-mode render, and names the generic tests.
- `render.py`: the sandboxed Jinja environment and the dbt context.
- `engine.py`: compilation, materializations, seeds, snapshots, tests, selection and the build order.
- `lab.py`: the BI Lab view, including the column lineage of the compiled models (`bilab.lineage`).
- `exercise.py`: the scenario model of the `dbt-sql` and `dbt-yml` exercise languages, graded by
  `datapass_runtime/dbt_project_grading.py`.
