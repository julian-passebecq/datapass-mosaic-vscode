# Datapass Workbench — current state

Read this before a substantial change. It is kept short on purpose and updated in place when a fact changes.

- **What happened, tranche by tranche** (with each tranche's "Checked" / "Not checked" notes): docs/HANDOFF_HISTORY.md.
- **What comes next**: the roadmap artifact, https://claude.ai/artifact/RhQMPGxeuNo9GTFzH5B8aJ (items V1-x, V2-x,
  T-x, and the code-debt audit D-1…D-10).
- **Rules** (product boundary, truth model, security, gates): CLAUDE.md, which wins over this file.

Last updated: 2026-09-26.

## Baseline and workflow

- `main` is the baseline. The old implementation branch `codex/bootstrap-datapass-workbench` was merged by PR #1
  (`f35dbe4`, 2026-09-24) and is history only.
- One branch per tranche from an up-to-date `main`, one pull request, merged on green CI. Several Claude sessions
  often work in parallel worktrees: keep changes inside the files your item owns (a lab's host code is in
  `src/labs/<lab>/` and its contract in `src/webview/contracts/<lab>.ts`).
- CI (`.github/workflows/ci.yml`) has four jobs: `extension` (compile, Node smokes, package), `runtime` (install,
  compileall, Pylance stubs check, runtime / exercise packs / missions / projects / terminal missions smokes),
  `extension-host` (`npm run test:host` with the dbt tools) and `vscode-ui` (the packaged VSIX driven by Playwright).
- Record each tranche as a new dated section at the top of docs/HANDOFF_HISTORY.md (`## YYYY-MM-DD · Title`, never
  numbered or lettered), and update this file when what exists, where it lives, or a known gap changes.

## What exists

One VS Code extension (webview Workbench + native editors, terminals, Explorer and Git) and one local FastAPI
runtime on loopback. Eleven Workbench modules, each with a `datapass.open…` command, grouped in two families in the
navigation ("Learn": Practice, Mosaic, SparkLab, Airflow, Pipeline, BI, Cloud Lab; "Real work": Projects, dbt,
Terminal, Infra), behind a "Today" home (`datapass.openHome`: Projects and Practice progress from
`.datapass/progress.json`, the next suggested step, the runtime with its Setup/Start action):

| Module (id) | What it does | Execution truth | Code |
| --- | --- | --- | --- |
| Projects (`projects`) | 3 end-to-end stories (`retail-fabric`, `databricks-ml`, `synapse-to-fabric`) whose steps are done in the labs and verified on the workspace | checks run on the catalog and the run journal; a hand tick is never a verification | `runtime/datapass_runtime/projects.py`, `run_journal.py`, `src/platform/projects.ts`, `content/projects/` |
| Mosaic (`mosaic`) | grid of native SQL/Python/Markdown files; Run/Explain active SQL, Profile, Import file (CSV, Parquet, JSON), query history, SQL dialect picker | real DuckDB; Python/Polars real only with trusted Python; dialects translated to DuckDB | `src/webview/MosaicSurface.tsx`, `runtime/sqldialects` |
| Practice (`practice`) | LeetCode-style arena over the exercise packs: one card per problem with a language switch, Run visible, Submit, feedback diff, hints, reference after a pass, progress per variant; Review (Leitner spaced review) and Interview (timed random series, no hints, summary) modes | real grading through the shared runtime (emulations labelled) | `runtime/datapass_runtime/exercises.py`, `content/exercise-packs/`, `src/platform/practice*.ts`, `src/webview/Practice*.tsx` |
| Cloud Lab (`fabric`) | Fabric-inspired lakehouse demo; Pipelines (Fabric / ADF / Synapse JSON), SQL pool (Synapse dedicated pool, Fabric Warehouse), Databricks (jobs, compute, Unity Catalog, MLflow) | orchestration simulated; Copy, Lookup, Script, procedures, SQL on local DuckDB; notebooks on SparkLab | `runtime/factorylab`, `sqlpoollab`, `databrickslab` |
| BI Lab (`bi`) | warehouse scripts, star model checks, SQL lineage, Concepts, dbt tab | scripts and model checks real on DuckDB; lineage static (sqlglot); dbt tab is the Datapass dbt emulation, "not dbt Core" | `runtime/bilab`, `runtime/dbtlab` |
| SparkLab (`sparklab`) | bounded PySpark-style files, teaching plans, simulated stages/shuffle/cost; a Polars engine runs the active file as real Polars and shows Polars' own optimized plan | bounded semantics on DuckDB; distributed behaviour simulated; Polars real, trusted Python only | `runtime/sparklab`, `src/labs/sparklab` |
| dbt Lab (`dbt`) | real dbt Core + dbt-duckdb + dbt Charts (`dct`) typed by the learner in a terminal; catalog handoff; artifacts view; missions | real; installed only by **Install dbt tools** | `src/dbtLab.ts`, `src/dbtState.ts`, `runtime/missionlab`, `content/missions/dbt-v1` |
| Terminal Lab (`terminal`) | real bash, PowerShell and Git missions; Datapass checks the resulting folder and repository | real shells; Datapass runs none of the learner's commands | `src/terminalLab.ts`, `runtime/missionlab/terminal.py`, `content/missions/terminal-v1` |
| Infra Lab (`infra`) | Terraform on a simulated azurerm subscription, Docker and compose, VM monitoring (az, Azure Monitor alerts), Kubernetes; typed in one simulated terminal (a Pseudoterminal, no process); missions | simulation only: HCL, Dockerfiles and manifests read, never executed; no real terraform, docker, kubectl or az | `src/infraLab.ts`, `runtime/infralab`, `runtime/missionlab/infra.py`, `content/missions/infra-v1` |
| Airflow Lab (`airflow`) | Airflow 3 DAG files read by a whitelisted AST reader; scheduler, runs, retries simulated | simulation, never eval/exec | `runtime/airflowlab` |
| Pipeline Lab (`pipeline`) | Python-like pipeline source compiled to a graph; supported activity bodies run | source never eval/exec'd; SQL, quality, Python, Polars bodies real; dbt activity declared only; schedule is metadata | `runtime/datapass_runtime/pipeline_compiler.py`, `native_pipeline.py` |

Also: a native **Catalog** tree view (`src/catalogTree.ts`), managed runtime setup (uv when available, else venv +
pip; Setup records a fingerprint of the bundled `runtime/` in the venv's `datapass-runtime.json`, and a mismatch after
an extension update shows "needs update" / **Update runtime** and is never started as is,
`src/platform/runtimeFingerprint.ts`), explicit trusted-Python opt-in (manifest flag + per-machine modal + Workspace Trust), per-launch runtime token
(`X-Datapass-Token`, Host check, `runtime/datapass_runtime/auth.py`).

Practice packs: `sql-lab-v1`, `engine-lab-v1` (incl. T-SQL and BigQuery variants), `python-lab-v1`,
`de-patterns-v1`, `spark-lab-v1` (PySpark + Polars), `spark-sql-v1` (Spark SQL), `airflow-lab-v1`, `cloud-pipelines-v1`, `sqlpool-v1`, `databricks-v1`, `dwh-v1`,
`dbt-v1`, `zilla-v1` (52 ZillaCode problems in six languages), plus `guided-spark-v1` (needs a qualified remote
connection, not graded locally), `unified-retail-v1`, `pipeline-design-v1`, `sparklab-runtime` and `internal-demo`. Languages include SQL dialects `snowflake`, `tsql`,
`bigquery`, translated to DuckDB (`runtime/sqldialects`, README there).

## Truth model in one paragraph

Never blur real execution and simulation. Real: Mosaic SQL on DuckDB, trusted Python/Polars, Practice grading, dbt
Lab commands, Terminal Lab shells, BI warehouse scripts and model checks, Projects checks. Translated: SQL dialects
("<dialect> dialect translated to DuckDB, not <engine>"). Emulated: the BI Lab dbt tab ("not dbt Core"). Simulated:
Airflow scheduling, the whole Infra Lab (Terraform, Docker, monitoring, Kubernetes), Cloud Lab orchestration, distributions and data movement, Databricks compute and DBU cost,
SparkLab distributed behaviour. Static: SQL lineage. No cloud connection anywhere. Details: CLAUDE.md.

## Where things live

- `src/` extension host: `extension.ts`; `workbenchPanel.ts` (the webview, the state it posts, the message table,
  no lab code); `runtimeManager.ts` (runtime process, setup, token, shared catalog; lab calls go through
  `runtimeManager.labs.<lab>`); `platform/` pure helpers; `workspaceFiles.ts` (`exists`, `writeIfMissing`,
  `copyWithoutOverwrite`) and `platform/workspacePaths.ts` (`safeRelativeParts`), one copy each.
- `src/labs/<lab>/` one folder per lab (module id, plus `workbench` for the shell and `missions` for the shared
  missions): `controller.ts` answers that lab's webview messages (typed `MessageHandlers`), keeps its host state and
  adds its part of the Workbench state (`contribute`); `client.ts` is its runtime HTTP client. `src/labs/controllers.ts`
  and `src/labs/clients.ts` register them (the few cross-lab actions are wired there; labs import no other lab, which
  `message_table_smoke.mjs` checks), and a message type no controller handles fails the typecheck.
- `src/webview/contracts/` one contract file per lab (its views, its slice of the runtime and Workbench state, its
  message union), composed in `contracts/index.ts` (imported as `webview/contracts`); `src/webview/` React surfaces
  (`WorkbenchApp.tsx`, one `*Surface.tsx` per module, `SharedGraphCanvas.tsx`); `src/test/hostSuite.ts` host E2E.
- A new lab registers with one entry in `content/modules.json` (id, family, label, command, execution, mode, icon;
  the file's `about` says it all), its id in `ModuleId` (`src/modules.ts`), its command in `package.json` and its
  surface in `SURFACES` (`src/webview/WorkbenchApp.tsx`, a `Record<ModuleId, …>`, so a missing surface fails the
  typecheck); `scripts/home_smoke.mjs` checks the four agree. The nav, the Labs view and Today follow the registry.
- A new webview message: add it to the lab's union in `contracts/<lab>.ts` and a handler in
  `src/labs/<lab>/controller.ts`; a new runtime call goes in `src/labs/<lab>/client.ts`.
- `runtime/datapass_runtime/` FastAPI app (`main.py`), kernels, catalog, grading; one package per lab:
  `sparklab`, `airflowlab`, `factorylab`, `sqlpoollab`, `databrickslab`, `bilab`, `dbtlab`, `sqldialects`,
  `snowflakesql`, `missionlab`, `infralab` (each with a README where the contract is non-trivial).
- `content/`: `exercise-packs/<pack>/` (manifest, exercises or scenarios, `grading.server.json`, and the test-only
  `quality.json` with mutants and gate flags), `projects/<id>/` (reference walkthroughs excluded from the VSIX),
  `missions/<pack>/<id>/` (solutions and mutants excluded from the VSIX), `pylance-stubs/`, `modules.json` (the module
  registry and its families).
- `samples/` sample projects copied into a learner's workspace (dbt, factory-lab, bi-lab).
- `scripts/`: every smoke and gate; `scripts/authoring/` pack generators (README there).
- `docs/`: ARCHITECTURE, QUICKSTART, LOCAL_TEST, EXERCISE_AUTHORING, PROJECT_AUTHORING, HARVEST_AUDIT, this file
  and the history. `workbench-core/`, `migration-sources/`, `legacy-donors/` are donor material, not a runtime.
- Workspace state a learner gets: `.datapass/project.json` (the one manifest), `.datapass/progress.json` (Projects;
  Practice per variant with its review box, and the last 20 interview summaries), `.datapass/mosaic.json`, `.datapass/data/` (catalog, run journal, lab state),
  `.datapass/missions/`, `.datapass/dbt/profiles.yml`.

## How to test

The gates are listed in CLAUDE.md "Required quality gates"; run them all before a PR. Notes that save time:

- `pip install ./runtime` before the Python smokes: the kernel worker imports the installed runtime, not the
  source tree (a stale install fails with errors such as "Unqualified semantic language adapter").
- `exercise_packs_smoke.py` takes several minutes (about 400 s locally) and must report the same counts unless
  exercises or mutants changed; current counts are 584 reference solutions, 584 starters and 549 mutants rejected.
- `npm run test:host` with `DATAPASS_E2E_PYTHON` (and `DATAPASS_DBT_PYTHON` for the dbt steps); `npm run test:ui`
  after `npm run package` for the packaged VSIX pass (docs/LOCAL_TEST.md).
- `infra_missions_smoke.py` needs nothing but the runtime (every tool is simulated); `infra_lab_smoke.mjs` is part of
  `npm test`.
- `dbt_oracle_smoke.py` when changing `runtime/dbtlab`, `missions_smoke.py` for missions: both need a Python with
  the dbt tools. `terminal_missions_smoke.py` needs bash and pwsh.
- Real VS Code checks: install the VSIX with `code --install-extension <file> --force` and drive it with Playwright
  `_electron.launch` with a fresh `--user-data-dir` on a **short** path (long paths broke DuckDB's DLL load, venv
  creation and the webview bundle). Write files on disk rather than typing into Monaco; use a new file name per run
  (hot exit restores old buffers).
- Windows: a smoke can hit a transient file lock (antivirus) on a temp-file rename; rerun before debugging.

## Known gaps and open points

Verification:
- The Cloud Lab tabs (Pipelines, SQL pool, Databricks) and the BI Lab tabs (Warehouse, Star model, Lineage,
  Concepts, dbt) were checked button by button only in a browser harness with a real runtime response. Real VS Code
  passes covered opening each lab, grading one exercise per pack and rendering every tab at a narrow width, not every
  button.
- The pack generators were not rerun after they started writing `quality.json` (several need CodeDELeet or dbt Core).

Labs:
- dbt Lab: `dct serve` keeps the catalog lent while it runs; without shell integration (cmd.exe) the end of a command
  is not reported, so use **Reattach catalog**; `dbt deps` downloads packages when a project declares them; dbt
  Charts is pre-1.0 and pinned to 0.8.x (re-check its conventions before moving the pin).
- Infra Lab (first tranche, 2026-09-26): a thin slice of four simulators with one mission each. Not simulated yet:
  Terraform modules, remote backends and `fmt`; VM creation from Terraform; compose volumes and networks; Kubernetes
  Ingress, HPA, StatefulSets and namespaces beyond apply. The simulated terminal has no cursor movement (history
  only). Real tools stay out on purpose (user decision): real-tool exercises may come once the app is finished.
- Terminal Lab: checks read the resulting state, so Datapass cannot tell whether the terminal or the editor produced
  it; scripts are read as text, never executed. A reported overlap in dbt Lab › Missions did not reproduce.
- SQL dialects: T-SQL comparisons are case-sensitive (SQL Server's default collation is not); the translated SQL is
  one line in the read-only tab; PostgreSQL has no Practice content yet (`PRACTICE_DIALECTS`); Spark SQL has a light first track (`spark-sql-v1`, 9 cards); the
  Snowflake subset lacks typed `DATEADD` on fixture columns, `ARRAY`/`SPLIT` and `REGEXP_SUBSTR` groups.
- Pipeline Lab: the dbt activity is declared only and fails fast; wiring it needs the trusted-local opt-in extended
  to dbt, the project path validated against `assets.dbt`, and a qualified manifest/run_results pair before success.
- Fabric's pipeline "dbt job" activity has no documented JSON `type` string: verify it before writing exercises.
- `zilla-v1` keeps ZillaCode's company names; the NOTICE is not a legal review. The runtime CI job is long because
  the packs smoke grades every submission.

Security (by design, keep it so): the kernel worker isolates lifecycle, it is not a sandbox; trusted Python is an
explicit choice; dbt and dct run as the learner's own terminal commands.

## Next

The roadmap artifact is the source of truth for order and status. Named directions so far: Infra Lab depth (more
missions per simulator, Terraform modules, Kubernetes Ingress/HPA), BI-3 (KPIs, a DAX-like measure layer translated to
SQL, charts), the Cloud Lab dbt layer (Databricks `dbt_task`, Fabric dbt job).

## What not to do

- Do not restart the project, add another app shell, editor, notebook runtime or Spark engine, or copy whole donor
  repositories into the VSIX.
- Do not commit to `main` directly or rewrite its history; do not continue the historical branch.
- Do not claim a simulation or emulation is the real product (Spark, Airflow, Fabric, Synapse, Databricks, dbt Core,
  dbt Charts, Snowflake, Power BI), and do not enable trusted Python or install the dbt tools silently.
- Do not eval/exec Pipeline Lab source, Airflow DAG files or Cloud Lab notebooks.
