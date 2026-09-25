# missionlab: missions and their hidden checker

A mission is a ticket, not an exercise. Someone on the team writes with context and a request; the learner gets
acceptance criteria, hints one at a time on request, and no pre-chewed starter: the work happens in a real project
folder with real tools. A hidden checker then looks at what really happened. The dbt Lab ships the first pack
(`content/missions/dbt-v1`); the Terminal and Infra labs are meant to reuse the contract with their own check kinds.

## Truth

| Piece | Truth |
| --- | --- |
| The learner's work | Real: dbt Core and dbt Charts run by the learner in the dbt Lab terminal, files edited in VS Code. |
| Fixtures | Real tables in the catalog, loaded from the pack's SQL (never from a request). |
| Checks | Real: read-only SQL on the catalog, the learner's own dbt artifacts (`target/manifest.json`, `run_results.json`, `sources.json`), files in the mission folder, the real `dct validate` (run by the host and passed in). |
| Airflow | The DAG file is parsed by the Airflow Lab's whitelisted reader and its schedule simulated with Airflow 3 semantics. Nothing in it is executed. |

## Pack layout

```text
content/missions/<pack>/
  pack.json                 id, title, lab, the missions in order
  base/                     the project every mission starts from (the team's codebase)
  fixtures/                 SQL shared by the missions' batches (${raw} = the mission's raw schema)
  <mission>/
    mission.json            the contract below
    project/                overlay on base/: the project as the learner finds it
    fixtures/*.sql          the mission's own batches
    solution/               the reference answer (overlay): scripts/missions_smoke.py only, not in the VSIX
    mutants/<name>/         plausible wrong answers (overlays on the solution) the checker must reject
```

The dbt Lab copies `base/` then `project/` into `missions/<id>/` once (existing files are never overwritten) and
writes `TICKET.md` there.

## mission.json

- `id`, `version`, `lab` (`dbt`), `title`, `level` (`intro`, `intermediate`, `advanced`), `estimate`, `skills`.
- `ticket`: `from`, `subject`, `body` (Markdown; a list of lines is joined).
- `acceptance`: criteria, each `{id, text, checks: [...]}`; a criterion passes when all its checks pass.
- `requires`: preconditions (`{message, check}`), such as "the second day's data was loaded". Unmet ones are shown
  first and the mission cannot pass.
- `hints`: revealed one at a time.
- `workspace`: `raw_schema` (where the fixtures land) and `dev_schema` (where dbt builds, with the dbt Lab's profile:
  target schema `dbt_dev` plus the project's custom schema).
- `batches`: `{id, label, sql: [paths relative to the pack]}`. The first batch starts the mission over: it drops the
  raw and dev schemas first. Later batches simulate time passing (tomorrow's export).
- `reference`: how the smoke plays the answer: `{batch}`, `{dbt: "build ..."}`, `{dct: "render ..."}`,
  `{dct_validate: board}`, each command with an optional expected `exit_code`.

## Check kinds (`model.py`)

| Kind | Looks at |
| --- | --- |
| `sql` | A read-only query on the catalog, compared to the expected rows (order-independent, numbers with a tolerance). |
| `node` | A node of `target/manifest.json`: materialization, `unique_key`, tags, words its SQL must use. |
| `test` | A generic test on a model's column, still there, still an error, not filtered with `where`. |
| `run` | `target/run_results.json` of the last command: command, node statuses, no failures, `--select`, `--full-refresh`, `--vars`. |
| `freshness_config` | A source's `loaded_at_field` and `warn_after` / `error_after` in the manifest. |
| `freshness_result` | `target/sources.json` written by `dbt source freshness`. |
| `dct_validate` | The real `dct validate --json` result of a board. |
| `board` | The board YAML: a query on `ref(model)`, a filter variable on a column, a chart type. |
| `render` | A `dct render --format json` output: a chart's values add up to a SQL total. |
| `file` | A file exists (for example the PNG render). |
| `airflow` | The DAG's simulated runs up to a time, each rendered `bash_command` containing given text. |

A failed check shows its `fail` sentence and what it found, never the expected answer.

## API

- `POST /api/local/missions/setup {mission_id, batch_id}` (kernel op `mission_setup`).
- `POST /api/local/missions/check {mission_id, dct}` (kernel op `mission_sql` for the SQL checks; the rest is read
  in the API process from `<workspace>/missions/<id>/`).

`scripts/missions_smoke.py` plays every mission with real dbt Core and dct (`DATAPASS_DBT_PYTHON`): the reference
passes, the untouched project and every mutant fail.
