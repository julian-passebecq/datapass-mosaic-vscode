# Datapass Workbench

Local-first VS Code data-engineering practice environment.

## Product split

- **Datapass Workbench (this repository):** Mosaic, LeetCode-style practice, local Fabric-style notebooks/pipelines, SparkLab/ZilaCode, a real-life dbt Lab (real dbt Core and dbt Charts in a VS Code terminal, with missions), a Terminal Lab (real bash, PowerShell and Git, with missions), an Infra Lab (simulated Terraform, Docker, VM monitoring and Kubernetes, with missions), Airflow simulation and pipeline orchestration.
- **Datapass WorkNotebook (standalone web):** cheatsheets, references, lightweight playgrounds and public/free learning areas.
- **Contoso Data Studio:** separate C# application and optional dataset/case-study source.

## Core rule

VS Code owns editing, files, terminals, Git and Jupyter. Datapass owns the teaching experiences and one local Python runtime.

```text
VS Code
├─ Native editor / Explorer / Terminal / Git / Jupyter
├─ Datapass activity bar (Labs, Catalog)
│  ├─ Mosaic
│  ├─ Practice
│  ├─ Fabric Lab
│  ├─ SparkLab / ZilaCode
│  ├─ dbt Lab (real dbt Core + dbt Charts, missions)
│  ├─ Terminal Lab (real bash, PowerShell, Git, missions)
│  ├─ Infra Lab (simulated terraform/docker/kubectl/az, missions)
│  ├─ Airflow Lab
│  └─ Pipeline Lab
└─ Datapass local runtime
   ├─ FastAPI control plane
   ├─ DuckDB / DuckLake
   ├─ Polars
   ├─ catalog handoff to the learner's dbt Core / dct runs
   ├─ missions checker (dbt Lab, Terminal Lab and Infra Lab)
   ├─ SparkLab simulation
   └─ workflow/scheduler simulation
```

## Harvested foundation

The branch already preserves the useful parts of the previous Datapass work rather than restarting them:

- `workbench-core/` — consolidated prior Workbench implementation/reference.
- `runtime/sparklab/` — SparkLab/ZilaCode training runtime.
- `content/` — connected cases and exercise packs.
- `migration-sources/` — Fabric, Airflow/dbt and previous Workbench UI donors.
- `legacy-donors/` — selected unique curriculum/visual logic that should be promoted deliberately.
- `src/platform/` — VS Code tool/status/detection patterns.
- `src/project/` — portable local `.datapass/project.json` workspace contract.
- `src/webview/` — VS Code webview security helpers.

See `docs/ARCHITECTURE.md` for the target architecture and `docs/HARVEST_AUDIT.md` for exactly what was reused or deliberately excluded.

## Practice packs

Practice grades native solution files on the local runtime (see `docs/EXERCISE_AUTHORING.md` for every pack). `zilla-v1` brings the 52 ZillaCode problems (Apache-2.0) with one result contract per problem in DuckDB SQL, Snowflake SQL, pandas, Polars, SparkLab and dbt. The Snowflake variant is labelled "Snowflake SQL dialect translated to DuckDB, not Snowflake": the query is translated with sqlglot for a documented subset (`runtime/sqldialects/README.md`) and runs on local DuckDB; nothing connects to Snowflake.

Practice shows one card per problem: the languages of a semantic scenario (`<scenario>-<language>` variants) are grouped by `semantic.id` behind a language switch. Progress is kept per language variant in the `practice` section of `.datapass/progress.json`, and the card summarizes it. **Review** re-proposes variants on a Leitner schedule (1, 3, 7, 14, 30, 60 days; a failed Submit comes back tomorrow). **Interview** draws a timed series (mixed SQL, Python and PySpark on different classic patterns, or one language), hides hints and reference solutions, and keeps a summary of the last 20 series.

## Terminal Lab

The Terminal Lab is a real bash, PowerShell and Git terminal, opened by VS Code in a mission folder. The learner types
every command; Datapass runs none of them and checks only the resulting files and Git repository afterward.

`terminal-v1` has 8 missions:

| Mission | Level | Skills |
| --- | --- | --- |
| Tidy the landing folder | intro | cd and ls, mkdir -p, globs, mv and rm, quoting file names |
| Pull the errors out of three nights of logs | intro | grep / Select-String, find / Get-ChildItem -Recurse, pipes, sort -u, redirection |
| Stop the load when a partner file is empty | intermediate | shell scripts, arguments, stderr, exit codes, set -euo pipefail |
| Three reports from the server inventory | intermediate | PowerShell objects, Import-Csv / Export-Csv, Where-Object/Sort-Object/Group-Object, calculated properties, numbers read as text |
| Put the loader under Git, properly | intro | git init, .gitignore, git add / commit, Conventional Commits, annotated tags, line endings, the executable bit |
| Merge the EUR branch through its conflict | intermediate | git switch, git merge --no-ff, resolving a conflict, git log --graph, deleting a merged branch |
| Rebase the batch API branch, and ship its fix in 1.2 | advanced | git rebase, interactive rebase (drop), linear history, git cherry-pick -x, reading git log --graph |
| Rescue a deleted branch, a reset commit and a stash | advanced | git reflog, recreating a branch, undoing reset --hard, git stash list / pop, reading history |

Requires Git, and one shell: Git Bash (installed with Git for Windows) on Windows, or PowerShell 7 (`pwsh`) or Windows
PowerShell 5.1. The Git missions also need a Git identity (`git config --global user.name` / `user.email`); the lab
warns when one is missing.

## Infra Lab

The Infra Lab teaches Terraform, Docker, VM monitoring and Kubernetes without a cloud account, a Docker daemon or a
cluster. The learner types `terraform`, `docker`, `kubectl` and `az` in a simulated terminal (a VS Code
Pseudoterminal that starts no process; each line is sent to the runtime's simulators, `runtime/infralab`). Nothing is
provisioned, built, pulled or deployed, and no real `terraform`, `docker`, `kubectl` or `az` is started, even when
one is installed. The learner's HCL, Dockerfiles, compose YAML and Kubernetes YAML are read by whitelisted readers
and never executed.

`infra-v1` has 4 missions:

| Mission | Level | Skills |
| --- | --- | --- |
| Bring the sales lake under Terraform | intermediate | terraform init/plan/apply, import, for_each on a set, azurerm storage, locals and outputs |
| Make the ingest API image and its compose stack production-ready | intermediate | Dockerfile layering, non-root images, HEALTHCHECK, Docker Compose dependencies |
| Page the on-call when the self-hosted integration runtime goes down | intermediate | az monitor metric alerts, action groups, replaying an alert over a metric scenario |
| Fix the orders service and release 1.5.1 without downtime | intermediate | Kubernetes Deployments, rolling updates, readiness probes, Services |

Requires nothing beyond the extension: no Azure subscription, Docker daemon or Kubernetes cluster.

## Try the connected demo

Open **Fabric Lab** and choose **Create / repair demo files** to scaffold a small connected project across CSV, SQL/Polars, Pipeline Lab, Airflow Lab and dbt Lab.

See `docs/QUICKSTART.md` for the exact local test flow.

## Install from a VSIX

Build the package (it compiles first):

```bash
npm ci
npm run package
```

This writes `datapass-mosaic-vscode-<version>.vsix` (about 1.2 MB). Install it with **Extensions → … → Install from VSIX…**, or:

```bash
code --install-extension datapass-mosaic-vscode-0.1.0.vsix
```

The Workbench is an extension pack, so VS Code also installs the Microsoft Python and Jupyter extensions. You need Python 3.11+ on your PATH: on first use, **Setup runtime** creates a private venv for the local runtime and installs its dependencies. When [uv](https://docs.astral.sh/uv/) is installed (on your PATH, or in `~/.local/bin` or `~/.cargo/bin`), Setup uses it and takes well under a minute; otherwise it uses pip, which can take several minutes on Windows. The VSIX contains the runtime source, content packs and samples; donor trees, TypeScript sources, source maps and contributor docs are excluded (see `.vscodeignore`).
