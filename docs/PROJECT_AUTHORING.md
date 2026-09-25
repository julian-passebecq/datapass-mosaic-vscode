# Authoring Workbench projects

A project is a story whose steps are done in the existing labs. Datapass verifies each step on the learner's
workspace, or the learner ticks it by hand. Projects add no execution of their own: they read what the labs
really did.

## Files

```text
content/projects/<id>/
  project.json                 the project (schema: runtime/datapass_runtime/projects.py)
  files/<workspace path>       starter files, copied into the workspace (never overwriting) by the "project" scaffold
  reference/walkthrough.json   the scripted reference walkthrough (scripts/projects_smoke.py); not shipped in the VSIX
  reference/*                  reference answers the walkthrough writes into the workspace
```

Files under `files/` mirror workspace paths and must stay under `projects/<id>/`, `factory/`, `bi/`,
`airflow/dags/`, `pipelines/`, `notebooks/`, `notes/` or `datasets/`.

## project.json

| Field | Meaning |
| --- | --- |
| `id`, `version`, `order` | Stable id (folder name), content version, position in the list |
| `title`, `summary`, `level`, `duration_minutes` | Shown in the project list (`level`: beginner, intermediate, advanced) |
| `story`, `goals` | Shown on the project page. Markdown text can be one string or a list of lines |
| `steps` | 8 to 12 ordered steps (the smoke enforces it) |

A step:

| Field | Meaning |
| --- | --- |
| `id`, `title` | Stable id and title |
| `module` | The Workbench module where the step happens (`src/modules.ts`) |
| `optional` | Not counted in the progress bar (for example a step that needs trusted Python) |
| `instructions` | Markdown subset: paragraphs, `-` and `1.` lists, `**bold**`, `` `code` ``, fenced code |
| `open` | What **Open in <lab>** does: `module`, optional `tab` (Cloud Lab: pipelines, sqlpool, databricks, lakehouse; BI Lab: warehouse, model, lineage, dbt, concepts), `file` to open beside the Workbench, `exercise` (Practice key `pack/id/language`), and `scaffold`: files to create first |
| `checks` | What Datapass verifies. No checks: a manual step |

Scaffolds never overwrite a file: `project` (this project's `files/`), `factory` (Cloud Lab samples),
`bi` (BI Lab samples), `retail_demo`, `airflow`, `pipeline` and `sparklab` (the Workbench starters). A step's
`file` must be created by its own scaffolds, so any step opens in any order.

## Checks and their truth

State checks run in the kernel, on the workspace catalog, when the learner clicks **Verify**:

| Kind | Passes when | Truth |
| --- | --- | --- |
| `table` | the table exists with `columns`, DuckDB `types` and at least `min_rows` rows | real |
| `sql` | the read-only query returns exactly `expected` (order-independent, numeric tolerance) | real |
| `sqlpool_table` | the SQL pool design has the `distribution`, `hash_columns` or partitioning | simulated |
| `mlflow_model` | the Databricks lab registry has the model, `min_versions` and the `alias` | simulated |

Run checks read the **run journal** (`.datapass/data/run_journal.json`). The runtime records it itself when a
lab route answers (`runtime/datapass_runtime/run_journal.py`); the extension never writes it. A run check
passes when a recorded run of that lab succeeded and its facts match:

| Kind | Lab and subject | Truth |
| --- | --- | --- |
| `exercise` | Practice: the exercise passed on **Submit** | the exercise's truth |
| `cloud_pipeline` | Cloud Lab pipeline (flavor, name, data plane, `activities` that succeeded, `min_attempts`) | hybrid (simulated on a dry run) |
| `sqlpool_run` | SQL pool script (flavor, workspace path of the script, `tables` left in the pool) | hybrid |
| `databricks_job` | Databricks job (name, `principal`, `tasks` that succeeded, `min_attempts`) | hybrid |
| `bi_model` | the last BI Lab run or analysis: every star model check passed, `facts` declared | real |
| `bi_lineage` | a BI Lab run or analysis traced `column` (table.column) back to every column of `origins` | static (analysis of the SQL text) |
| `dbt` | BI Lab dbt tab: `nodes` succeeded in a run of `command` | emulation |
| `airflow` | Airflow Lab simulation of `dag_id`: `schedule`, `catchup`, `min_runs` all successful, `min_try_number` | simulated |
| `pipeline_lab` | Pipeline Lab run of `pipeline`, with `min_quality_tasks` and `tasks` | real |
| `sparklab` | SparkLab run with `columns`, `max_exchanges`, `min_broadcast_joins` (simulated plan) | emulation |
| `mosaic` | Mosaic run of `language` (sql, python, polars) with `columns` | real |
| `lakehouse_demo` | Cloud Lab › Lakehouse **Run local medallion flow** | real |
| `run` | generic: any journal `lab`, `subject`, `expect`, `at_least`, `at_most`, `includes` | the run's truth |

A manual step is never verified: the learner ticks it and the Projects UI shows "ticked by hand", apart
from "verified". Labels, instructions and messages are written in English, like the rest of the Workbench.

## Adding a lab later

A future lab (a dbt Core + dbt Charts lab, a Terminal Lab, a simulated Infra Lab) adds steps without new
project machinery:

1. add the module to `src/modules.ts` and to `MODULES` in `projects.py` (and its tabs to `TABS`);
2. record its runs: call `record_run("<lab>", request, response)` in its route and add a summarizer to
   `SUMMARIZERS` in `run_journal.py` (lab, subject, ok, status, truth, facts);
3. write steps with the generic `run` check, or add a named check kind in `projects.py` when it reads better;
4. extend the walkthrough runner in `scripts/projects_smoke.py` with the lab's action.

## The reference walkthrough

`reference/walkthrough.json` has one list of actions per step (`steps`) and optional `starters`. The smoke
creates one workspace and, project after project, runs each step's scaffolds, then its starter actions (the
untouched starter must leave the step unverified), then its actions, through the runtime API with the payloads
the extension sends. It first checks that every automatic check fails in a fresh workspace, and at the end of
each project that every automatic check passes.

Actions: `write`, `append`, `replace`, `json_insert`, `json_set` (edit workspace files as a learner would),
`import_csv`, `sql`, `sparklab`, `python`, `exercise` (submits the pack's reference solution), `factory`,
`sqlpool`, `databricks`, `bi`, `dbt`, `airflow`, `pipeline_lab`, `retail_demo`.

```bash
python scripts/projects_smoke.py
```
