# missionlab: missions and their hidden checker

A mission is a ticket, not an exercise. Someone on the team writes with context and a request; the learner gets
acceptance criteria, hints one at a time on request, and no pre-chewed starter: the work happens in a real project
folder with real tools (or, in the Infra Lab, simulated ones). A hidden checker then looks at what happened. Three
labs ship packs: the dbt Lab (`content/missions/dbt-v1`), the Terminal Lab (`content/missions/terminal-v1`) and the
Infra Lab (`content/missions/infra-v1`), both described below.

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

- `id`, `version`, `lab` (`dbt`, `terminal` or `infra`), `title`, `level` (`intro`, `intermediate`, `advanced`), `estimate`, `skills`.
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
| `node` | A node of `target/manifest.json` (model, seed or snapshot): materialization, `unique_key`, tags, words its SQL must use, an enforced contract and each column's declared `data_type`. |
| `unit_test` | The dbt unit tests of a model in the manifest: how many, the columns their expected rows pin, and each one's status (`pass`) in `run_results.json`. |
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

- `POST /api/local/missions/setup {mission_id, batch_id}` (kernel op `mission_setup`). For a Terminal Lab mission,
  `{mission_id}` alone (re)builds the mission folder instead; no kernel involved.
- `POST /api/local/missions/check {mission_id, dct}` (kernel op `mission_sql` for the SQL checks; the rest is read
  in the API process from `<workspace>/missions/<id>/`).

`scripts/missions_smoke.py` plays every mission with real dbt Core and dct (`DATAPASS_DBT_PYTHON`): the reference
passes, the untouched project and every mutant fail.

## Terminal Lab missions (`lab: "terminal"`)

The learner's own bash, PowerShell and Git commands, typed in a real VS Code terminal opened in the mission folder.
Datapass runs none of them: it builds the starting folder, then reads what the commands left behind.

| Piece | Truth |
| --- | --- |
| The learner's work | Real: their commands in their shell (Git Bash or bash, pwsh or Windows PowerShell). |
| Fixture | Built by the runtime from the pack only (`terminal.py` `build_fixture`): the mission's `project/` overlay, the inline `fixture.files` (with CRLF or the executable bit when a mission needs them), then a Git history made of fixed git commands (`init -b`, `commit`, `branch`, `switch`, `merge --no-ff`, `tag`, `branch -D`, `reset --hard`, `stash push`). The author and dates are fixed and the learner's global and system Git config is not read, so the fixture's hashes are the same on every machine. |
| Start over | The existing folder is moved to `.datapass/missions/attic/<id>-<time>/`, never deleted; the new one is built next to it and renamed into place. |
| Checks | Real, read-only: files as text (UTF-8, or UTF-16 with a BOM as Windows PowerShell 5.1 writes with `>`), CSV, scripts as **text** (comments removed; never executed), and the repository through read-only git commands with `core.fsmonitor` off, hooks pointed at nothing and `GIT_CEILING_DIRECTORIES` so a repository around the workspace is never used. Ignore rules are the repository's own (the learner's global excludes file is left out, since it would not travel with the repository). |

A mission.json of this lab has a `fixture` (`files`, `git: {path, branch, author, start, steps}`) instead of
`workspace` and `batches`, and its `reference` steps are whole solution scripts: `{bash: "solution/solve.sh"}`,
`{powershell: "solution/solve.ps1"}`. Mutants are `mutants/<name>/solve.sh` or `solve.ps1`. Check kinds that need
the catalog or dbt (`sql`, `node`, `run`, …) are refused in this lab.

| Kind | Looks at |
| --- | --- |
| `path` | A path is a file (optionally non-empty), a folder, or absent. |
| `text` | A file's exact lines (line endings and trailing spaces normalized), texts it contains or not, regexes, LF or CRLF. |
| `listing` | A folder's entries (optionally recursive, `.git` skipped) matching a name pattern: exactly, includes, excludes, a count. |
| `csv` | Header and rows, in order or not; a `#TYPE` line (Export-Csv without `-NoTypeInformation`) fails. |
| `script` | A bash or PowerShell script's text without comments: shebang, constructs it must or must not use. Never run. |
| `git_repo` | The folder is the top of its own repository; current branch; clean tree; no merge, rebase, cherry-pick or revert in progress. |
| `git_branch` | A branch exists, or is gone. |
| `git_log` | The commits of a ref (or `since..ref`): exact subjects, included and excluded subjects, counts, linear or with merges, ancestors, a subject regex (Conventional Commits), texts a message body records (`cherry-pick -x`). |
| `git_file` | A file as committed at a ref: exists or not, contents, no conflict markers, mode `100755`, LF or CRLF. |
| `git_tag` | A tag exists, annotated or lightweight, points at a revision, its message. |
| `git_ignore` | Paths the repository ignores or not (`check-ignore --no-index`), paths tracked or not. |
| `git_stash` | The number of stash entries, an entry's message. |
| `any_of` | One of its checks passes (a script in bash or in PowerShell). |

`scripts/terminal_missions_smoke.py` plays every reference with real shells (bash; pwsh, and Windows PowerShell 5.1
on Windows) in a fixture built through the API: the references pass, the untouched fixtures and every mutant fail,
the fixture's hashes are reproducible, and Start over keeps the previous folder in the attic.

## Infra Lab missions (`lab: "infra"`)

Tickets done with terraform, docker, kubectl and az typed in the Infra Lab shell, a simulated terminal
(`runtime/infralab`, README there). **Everything is simulated**: nothing is provisioned, built or deployed, and the
learner's files are read, never executed.

| Piece | Truth |
| --- | --- |
| The learner's work | Real files edited in VS Code; commands typed in the Infra Lab shell, which the runtime simulates. |
| Fixture | Built by the runtime from the pack only (`infra.py` `build_fixture`): the mission's `project/` overlay, the inline `infra.files`, the simulated world `infra.world` (merged over the lab's default subscription, Docker engine and cluster), then the fixture's own simulated commands `infra.setup` (for example `kubectl apply -f k8s/` to deploy yesterday's version). Start over moves the previous folder to the attic, as in the Terminal Lab. |
| Checks | Read the simulation: `terraform.tfstate`, `.infralab/world.json` (subscription, Docker, cluster), the shell's journal and the files. Some re-run a simulation: a fresh `terraform plan`, the build after a pretend code change, an alert rule replayed over the metric scenario. None runs a real tool. |

A mission.json of this lab has `infra` (`files`, `world`, `setup`) instead of `workspace`, `batches` or `fixture`, and
its `reference` steps are shell lines: `{infra: "terraform apply -auto-approve"}`. The smoke copies `solution/` over
the fixture before playing them (a mission answered by commands alone has no `solution/`). Mutants are
`mutants/<name>/` overlays on the solution, with an optional `commands.txt` that replaces the reference lines. Check
kinds that need the catalog, dbt or Git are refused in this lab; `path`, `text`, `listing` and `any_of` are allowed.

| Kind | Looks at |
| --- | --- |
| `tf_state` | `terraform.tfstate`: addresses present or absent (module addresses included), attribute values, the instance keys of a count / for_each resource, root outputs and their values. |
| `tf_plan` | A fresh simulated plan of the files as they are now (with the -var options of the last successful apply): it succeeds, and shows no changes. |
| `tf_config` | The `.tf` files: a resource and its for_each / count / prevent_destroy, the names its arguments refer to (through locals), variables (type, validation, default), outputs, module calls (source, inputs set), whether the root module declares resources itself, and whether every `.tf` file passes `terraform fmt -check -recursive`. |
| `azure_resource` | A resource of the simulated subscription: exists or not, created by Terraform or in the portal (an imported resource keeps its portal origin; a recreated one does not), attribute values, a count. |
| `journal` | The shell's journal: commands run (regular expressions), commands ruled out, an order between two commands. |
| `docker_image` | An image: built from the current Dockerfile, its base, non-root, size, lint findings it must not have, a HEALTHCHECK. |
| `docker_build` | The build simulated again: steps that stay CACHED after a pretend change to given files, paths `.dockerignore` keeps out of the context. |
| `docker_container` | A container by name or compose service: running, health, answering through a published port, waiting for dependencies to be healthy, the compose networks it is (not) on, internal only, publishing a reachable port, a named volume at a path, the rows its database holds. |
| `azure_alert` | A metric alert rule on a resource and metric (any name): enabled, severity, action group, and replayed over the scenario: fires inside given windows, silent inside others. |
| `k8s_deployment` | A Deployment: image, ready pods, readiness probe, strategy, no crashing pod, and its last rollout: complete, target image, the fewest pods that really answered traffic. |
| `k8s_service` | A Service: its endpoints, and whether traffic reaches the port the app listens on. |
| `k8s_ingress` | An Ingress: its class is served, and GET http://host/path is routed by it to a given Service and answered with a given status. |
| `k8s_hpa` | The HorizontalPodAutoscaler of a Deployment: min / max replicas and CPU target within ranges, able to compute a replica count, and the last `lab load replay` (made after the last change): overloaded minutes, peak and final replicas. |

`scripts/infra_missions_smoke.py` plays every reference through the API: the references pass; the untouched fixture,
the starter project played with the reference commands, and every mutant fail; two builds of a fixture give the same
world.
