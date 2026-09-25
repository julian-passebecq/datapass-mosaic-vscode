# Exercise pack generators

These scripts wrote the authored Practice packs. Each one holds the exercises as
Python specs (prompt, starter, reference solution, fixture scenarios, mutants),
computes the expected rows by running the reference through the pack's real grader,
checks that the starter and every mutant run and fail, validates the pack with the
registry, and writes `content/exercise-packs/<pack>/`.

| Script | Pack | Grader |
| --- | --- | --- |
| `gen_airflow_lab.py` | `airflow-lab-v1` | Airflow Lab simulator (`runtime/airflowlab`) |
| `gen_cloud_pipelines.py` | `cloud-pipelines-v1` | `datapass_runtime/factory_grading.py` |
| `gen_sqlpool.py` | `sqlpool-v1` | `datapass_runtime/sqlpool_grading.py` |
| `gen_databricks.py` | `databricks-v1` | `datapass_runtime/databricks_grading.py` |
| `gen_dwh.py` | `dwh-v1` | `datapass_runtime/warehouse_grading.py` (BI Lab) |
| `gen_dbt.py` | `dbt-v1` | `datapass_runtime/dbt_project_grading.py` (BI Lab dbt emulation; cross-checked with dbt Core when `DATAPASS_DBT_PYTHON` is set) |
| `gen_zilla.py` | `zilla-v1` | Every language's grader through `datapass_runtime.exercises.grade` (SQL, Snowflake, pandas, Polars, SparkLab, dbt emulation); reads CodeDELeet's normalized ZillaCode import (`CODEDELEET`, default `D:/PROJ/CodeDELeet`); specs in `scripts/authoring/zilla/`; writes the pack's LICENSE and NOTICE; replaces the whole mutant list of `zilla-v1/quality.json`; `--only 1,2` checks some problems without writing |
| `gen_spark_lab.py` | `spark-lab-v1` | SparkLab grader; the pack and its grading changes come with PR #7, which is not in this branch's history |
| `gen_pylance_stubs.py` | `content/pylance-stubs/` (not a pack) | the SparkLab and Airflow Lab readers' import tables; CI runs it with `--check` |

Run from the repository root, against the repository's runtime:

```bash
PYTHONPATH=runtime python scripts/authoring/gen_databricks.py
```

The script prints the expected rows of every fixture and ends with `PROBLEMS:` if a
reference is rejected or a starter or mutant passes. It also writes the mutants of its
exercises to `content/exercise-packs/<pack>/quality.json` (`pack_quality.write_mutants`: flags,
notes and other exercises' mutants are kept), which `scripts/exercise_packs_smoke.py`, the gate CI
runs, reads. See docs/EXERCISE_AUTHORING.md "Quality gate".

Rules:

- Review every expected row by hand before committing: the generator computes them
  from the reference, so a wrong reference produces wrong expectations.
- Regenerating can reorder rows of aggregations without ORDER BY. Grading ignores
  row order (`ordered: false`), so that diff is noise: keep the committed file.
- Changing an existing exercise's expected rows changes what learners are graded
  on. Bump the exercise `version` when its meaning changes.
