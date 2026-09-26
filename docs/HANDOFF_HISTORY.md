# Datapass Workbench — handoff history

Dated record of every tranche, newest first. The current state (what exists, the truth model, where things
live, how to test, known gaps) is in docs/HANDOFF.md; what comes next is in the roadmap artifact
(https://claude.ai/artifact/RhQMPGxeuNo9GTFzH5B8aJ). Branch names, tips and gate counts in these sections are
historical.

Add a tranche as a new `## YYYY-MM-DD · Title` section at the top, under this paragraph. Never number or letter
sections, and refer to another section by its heading, not by a position. Keep the "Checked" and "Not checked"
notes: they say what was really run.

## 2026-09-26 · Version 0.2.0, changelog and release workflow (T-6)

- `package.json` / `package-lock.json` at 0.2.0 (the plan's V1 shipped). `CHANGELOG.md` (Keep a Changelog) has one
  0.2.0 section summarising PRs #1 to #63 by theme.
- `.github/workflows/release.yml`: a pushed tag `v*` that equals `v` + `package.json`'s version builds like the CI
  extension job and publishes a GitHub Release with the VSIX and that version's changelog section as notes.
  Steps in `docs/RELEASE.md`. No tag was pushed: publishing waits for Julian.
- `scripts/package_smoke.mjs` fails when `package.json`'s version has no `## [<version>]` section in `CHANGELOG.md`.

Checked: `npm run compile`, `npm test`, `npm run package` (datapass-mosaic-vscode-0.2.0.vsix); the notes extraction
(awk) locally on CHANGELOG.md; release.yml read and YAML-parsed (actionlint not installed).
Not checked: the Release workflow itself, which runs only on a pushed tag.

## 2026-09-26 · API Lab: REST API ingestion into bronze (V3-4)

A new "Real work" module, the API Lab (`apilab`): the learner writes `missions/<id>/ingest.py` (real Python, httpx or
requests) that ingests a simulated REST API into the bronze layer. Julian's transport decision: the API is served by
a small server (`runtime/apilab/server.py`) on 127.0.0.1, on its own port, one per active mission, started and
stopped by the runtime, with a fictitious bearer key made at each mission start and shown in the Workbench. The
server checks its own Host header and key, starts with an allowlisted environment (never the runtime's launch token)
and writes a JSON-lines request log. The learner's file runs as trusted local Python in the kernel worker (kernel op
`apilab_run`, refused while trusted Python is off) with `API_BASE_URL`, `API_KEY` and `bronze`
(`append / merge / overwrite / query / columns`, schema enforcement unless `evolve=True`) in scope. Five missions
(`content/missions/api-v1`): page pagination, cursor + transient 502/503, 429 + Retry-After with at-least-once
duplicates, incremental load with a watermark over two API days, schema drift (v2 renames `price`, adds `currency`).
Checks: read-only SQL on bronze, the request log and the run history (`runtime/apilab/check.py`). The missions reuse
the shared missions panel and progress (`src/missions.ts` routes `lab: "apilab"` to `src/labs/apilab/client.ts`);
missionlab skips the pack (`OTHER_PACKS`). Registered in `content/modules.json` (family "work") after T-1.

Checked: `scripts/api_lab_smoke.py` (5 references pass; 5 untouched missions, 5 starters and 10 mutants fail; 401
without the key, 400 on a foreign Host, 200 with both; the runtime token in no server environment, file, answer,
state or learner `os.environ`; a run with trusted Python off refused and not recorded); `npm run compile`, `npm test`,
`infra_missions_smoke.py`, `terminal_missions_smoke.py`, `projects_smoke.py`; `npm run package && npm run test:ui` in
a real VS Code (58/58 after the rebase on T-1, the tab reached through "Real work"): the API Lab mission started, trusted Python enabled through its real
confirmation dialog, the reference `ingest.py` run, Check my work passed.

Not checked locally: `runtime_smoke.py` (its first kernel call has an 8 s budget and the worker's cold start took 9 to
16 s on this machine while other sessions built; CI runs it), `exercise_packs_smoke.py`, `missions_smoke.py` and
`npm run test:host` (the new host test "API Lab: a mission starts its simulated API…" runs in CI). Pylance flags
`API_BASE_URL`, `API_KEY` and `bronze` in `ingest.py` as undefined (they are injected at run time).

## 2026-09-26 · Lakehouse Lab: Parquet, partitions, compaction and DuckLake (V3-3)

A twelfth Workbench module, the Lakehouse Lab (`lakehouse`, command **Datapass: Open Lakehouse Lab**), teaches storage
layout on real local files. Julian's decisions (2026-09-26): Parquet and DuckLake, plus Delta only through what DuckDB
gives (its `delta` extension), no `deltalake`, `pyiceberg` or other new dependency; Iceberg is explained in the lab's
Concepts, labelled "not handled here".

- `runtime/lakehouselab` (README there): its own mission model, fixture builder, checker and routes
  (`/api/local/lakehouse/*`, one `include_router` line in `main.py`). The learner's SQL runs on DuckDB in a child
  process bounded to `lakehouse/<id>/`; the Polars file runs as trusted local Python only. DuckLake missions attach
  the mission's own lake (`lake/catalog.ducklake`, Parquet under `lake/data/`).
- Delta: DuckDB's `delta` extension reads Delta tables (any version) and appends to them, but cannot create one. The
  seventh mission (append April to a shared Delta table as one commit, older versions unchanged) ships its
  `_delta_log` and builds the Parquet files it lists; UPDATE / DELETE / MERGE / OPTIMIZE on Delta are not attempted.
- The `ducklake` and `delta` extensions are installed by **Setup runtime** (`runtimeVerifyArgs` calls
  `lakehouselab.extensions.setup_install()`); offline, Setup says so and succeeds, the Parquet missions work and the
  DuckLake missions are refused with that explanation. The lab only LOADs it afterwards.
- `content/lakehouse/lakehouse-v1`: seven missions: the Delta one above, and partition the sales by month (DuckDB or Polars), make the March
  report read one month (pruning read from `EXPLAIN ANALYZE`), compact 210 small files (DuckDB or Polars), undo a bad
  update with time travel, evolve a table's schema, apply supplier changes in one commit (DuckLake's MERGE takes a
  single UPDATE/DELETE action, so the reference is a DELETE and a MERGE in one transaction).
- Kept apart from the shared missionlab on purpose: a pack under `content/missions/` would break its loader and its
  model, checker and host service were being changed by the Infra Lab work at the same time. The host reuses the
  mission views and progress helpers of `platform/missions.ts` and `MissionsPanel` (two optional props: `send`,
  `extra`); progress is in `.datapass/lakehouse/progress.json`, the attic in `.datapass/lakehouse/attic/`.
- SparkLab is not an engine here: its interpreter works on catalog tables, and these missions are about files.

Checked: `npm run compile`, `npm test`, compileall, `runtime_smoke.py`, `projects_smoke.py`,
`infra_missions_smoke.py`, `terminal_missions_smoke.py`, `exercise_packs_smoke.py` (601 / 601 / 569),
`lakehouse_smoke.py` (34 plays: 9 references on DuckDB and Polars pass, 7 untouched starters and 25 mutants fail, the
Run bounds refuse INSTALL, ATTACH, SET, LOAD and a file outside the folder; about 5 min on Windows), and
`npm run package && npm run test:ui` in a real VS Code: the Lakehouse steps pass (mission started, SQL run from the
lab, Check my work passes; the tab's layout at 478 px). That local UI run was before the rebase on the families
navigation and before the Delta mission; one unrelated step ("BI Lab builds its warehouse", a notification wait)
failed there under load.

Not checked: `npm run test:host` and `missions_smoke.py` locally (CI runs them; the new host test builds, runs and
checks `partition-sales`); the Polars Run button by hand in VS Code (the smoke runs every Polars reference through
the same route).

## 2026-09-26 · Infra Lab depth: Terraform modules and fmt, Ingress and HPA, compose volumes and networks

Package D of `handoff/PLAN.md`. Each simulator gets a second mission, and the simulators grow what those missions need.
Everything stays simulated: no real terraform, docker, kubectl or az, files read and never executed or rewritten.

- Terraform (`terraform.py`, new `tffmt.py`): local `module` blocks (source inside the folder, inputs checked against
  the child's variables, outputs as `module.<call>.<output>`, nested calls, `depends_on`), flattened into one graph
  with per-module scopes; addresses and `terraform.tfstate` carry `module.<call>.` as Terraform writes them; `init`
  installs modules ("Module not installed" / "Module source has changed" until it runs again). `terraform fmt -check
  | -diff | -recursive | -list=false` follows hclwrite's rules for a documented subset (indentation, `=` and comment
  alignment, spacing, block headers); plain `fmt` lists the files and rewrites nothing. Mission *One data lake
  module, two teams* (`datalake-module`): finish a module, call it twice, pass `fmt -check -recursive`; six mutants
  (copy-paste, hard-coded global name, `count` instead of `for_each`, missing tag merge, registry source,
  unformatted).
- Kubernetes (`kube.py`, new `ingress.py`, `autoscale.py`): Ingress and HPA validated strictly with the API server's
  messages; `apply` reports an invalid object and applies the others; namespaces: `create namespace`, `-A`,
  namespace-aware `describe`/`logs`/`delete`, a deleted namespace takes its objects. `curl http://<host>/<path>`
  goes through the mission's ingress controller (class, host, `Exact`/`Prefix`, longest match, Service port by
  number or name). `lab load replay` plays a recorded CPU curve against the HPA in 15-second syncs (tolerance,
  default behaviours, stabilization, min/max, scheduling by requests, overload above the CPU limit). Mission *Get
  orders-api through Black Friday* (`black-friday-autoscale`); nine mutants.
- Compose (`docker.py`): top-level `networks` (`internal`) and `volumes`, per-service `networks` and `volumes`
  (short and long syntax), names resolved per shared network, no reachable port for an internal-only container,
  database rows kept in a named volume or bind mount (else in the anonymous volume that `down` throws away),
  `down -v`, `docker volume` / `docker network`. Mission *Stop losing the dev database* (`compose-keep-the-data`);
  eight mutants.
- Monitoring: a second mission on the existing engine, *Catch the ETL VM before it runs out of memory*
  (`etl-vm-memory-leak`): fix an existing rule (same name), add an availability alert; eight command mutants.
- Checks (`runtime/missionlab`): `tf_state.outputs`, `tf_config.modules | root_resources | formatted`,
  `docker_container.networks | not_networks | internal | published | volume_at | data_rows`, new `k8s_ingress` and
  `k8s_hpa`. The Infra Lab panel lists volumes, networks, ingresses and HPAs.

Checked: `infra_missions_smoke.py` (8 references pass; untouched fixtures, 6 starters and 54 mutants fail),
`runtime_smoke.py`, `npm run compile`, `npm test`, a new mission played in the simulated terminal of a real VS Code.
Not checked: real Terraform's `fmt` output on the same files (the rules come from hclwrite's source; the shipped
`.tf` files were written to pass both).
## 2026-09-26 · Today home and navigation by families

The flat tab bar of eleven modules became two rows: "Today" and the two families ("Learn", "Real work"), then the
modules of the selected family; switching family comes back to the module last shown in it. `content/modules.json`
is now the module registry (families, then modules with their family and codicon; the old persona list it held was
only read by the `workbench-core/` donor), and `src/modules.ts` exposes it as `MODULES` / `MODULE_FAMILIES`. The
split: Learn = guided labs and simulators (Practice, Mosaic, SparkLab, Airflow, Pipeline, BI, Cloud Lab); Real work =
Projects and ticket-style missions with real tools or a full simulated platform (dbt, Terminal, Infra). Today
(`HomeSurface.tsx`, `datapass.openHome`, state from `src/labs/workbench/home.ts`) shows the next suggested step
(open a folder; the next step of the first started, unfinished project; Practice reviews due; the first project not
started; else Practice), Projects and Practice progress, the runtime with the same Setup/Start buttons as the top
bar (`RuntimeActions`), and every lab by family. The Labs view groups modules by family under a Today entry. Surfaces
are a `SURFACES: Record<ModuleId, …>` map in `WorkbenchApp.tsx`, so a module without a surface fails the typecheck.

Checked: `npm run compile`, `npm test` (new `scripts/home_smoke.mjs`: registry consistency, next-step order), the
Python gates of CLAUDE.md, `npm run package && npm run test:ui` (the layout pass now opens Today, then every module
through the family tabs at 520 px, and asserts every registry module was reached).
Not checked: `npm run test:host` (no host-side flow changed beyond the `datapass.openHome` registration it lists).

## 2026-09-26 · Faster CI and debt cleanup (D-3, D-4, D-7)

- CI: uv with a cached download store replaces pip; the extension job builds once (`npm run package` runs
  `vscode:prepublish`, then `npm test`); a new push to a pull request cancels its previous run; the dbt missions smoke
  moved from `runtime` to `extension-host`, which already installs the dbt tools.
- `scripts/exercise_packs_smoke.py` grades in parallel processes (`DATAPASS_PACKS_JOBS`, default one per CPU, at most
  8), each with its own workspace and worker, and puts the results back in exercise order.
- Removed `packages/` (contracts, notebook-core: no importer) and the caller-less `/api/local/capabilities` and
  `/api/local/restart` routes.
- D-4 needed no change: the regex `ref()`/`source()` reader left `src/dbtState.ts` with the real dbt Core rebuild;
  the dbt Lab reads only the run's `target/` artifacts.

Checked: the four CI jobs green on PR #59; packs smoke 601 references / 601 starters / 569 mutants, as on main;
runtime job 135 s against a 452 s median of the last five main runs (516, 456, 452, 434, 350), whole run 377 s
against 452 s (extension-host, now 377 s, is the longest job); `npm run compile`, `npm test` locally.
Not checked: 22 local workers on a busy Windows desktop hit the 60 s kernel timeout, hence the cap of 8.

## 2026-09-27 · Airflow Lab: depends_on_past across runs

The simulator ran every DAG run on its own and refused `depends_on_past`. It now simulates runs in logical-date order
and applies Airflow's PrevDagrunDep: a `depends_on_past` task starts only when the same task succeeded or was skipped
in the previous run (with `catchup`, the previous scheduled run; otherwise the previous run of any type). Otherwise it
keeps no state, like everything waiting on it, and the run stays `running`, which is what a learner sees in Airflow
after a failed day until it is cleared. `ignore_first_depends_on_past` is accepted (no effect: the first run has no
previous run). The Lab and `latest_run_only` grading simulate every run since the unpause when a DAG depends on the
past, so the first shown run sees its predecessor. Waiting times between runs and `wait_for_downstream` are still not
modelled (the latter is refused by name).

- `runtime/airflowlab`: `TaskSpec.depends_on_past`, `DagSpec.cross_run`, `simulate()` chaining runs; README updated.
- `airflow-lab-v1`: a 14th exercise, *A running balance must not skip a failed day* (`af-depends-on-past`): only the
  task that carries state between days depends on the past. Mutants: the flag in `default_args` (holds back the
  independent export too), on the wrong task, retries instead. Generated by `scripts/authoring/gen_airflow_lab.py`;
  the 13 existing exercises are unchanged.

Checked: `runtime_smoke.py` (new depends_on_past assertions: states, run states, `latest_run_only`, a failure in the
last run), `exercise_packs_smoke.py`, `npm run compile`, `npm test`.

Not checked: the Airflow Lab panel with a depends_on_past DAG in a real VS Code window (the panel already renders
`none` task states and `running` runs).

## 2026-09-27 · dbt Lab: snapshot and contract missions

Two warehouse tickets join the dbt Lab's `dbt-v1` missions (seven now), both done with real dbt Core:

- **Keep every list price the ERP ever had** (`product-price-history`): a YAML snapshot (dbt Core 1.9+) of
  `erp_products`, SCD type 2. The weekly export stamps every row with a new `loaded_at`, so the timestamp strategy
  (or `check_cols: all`) makes a version per product per week; the check strategy on the business columns keeps one
  per real change, and `hard_deletes: invalidate` closes a discontinued product. Two batches (this week, next week).
  Mutants: timestamp on `loaded_at`, `check_cols: all`, no hard deletes.
- **Promise finance the shape of fct_order_lines** (`order-lines-contract`): an enforced model contract with a
  `data_type` per column (`net_amount` as `decimal(12,2)`, which needs a cast) and a dbt unit test on
  `stg_shop__order_lines` that pins the line-discount rule. Mutants: contract not enforced, `net_amount` as double,
  the discount applied per unit (the unit test must catch it).

Checker (`runtime/missionlab`): the `node` check also reads `contract.enforced` and each column's declared
`data_type`; a new `unit_test` kind reads the model's unit tests in the manifest (count, the columns their expected
rows pin) and their status in `run_results.json`. `scripts/missions_smoke.py` accepts `DATAPASS_MISSIONS_ONLY` (ids,
comma-separated) to play only some missions.

Checked:
- `missions_smoke.py` with dbt-core 1.12, dbt-duckdb and dbt-charts: all seven references pass; the untouched
  projects and every mutant fail (the two new missions: 6 mutants);
- `runtime_smoke.py`, compileall on `runtime/missionlab`, `npm run compile`, `npm test`.

Not checked: the two missions played by hand in a real VS Code window (the Missions tab lists them from the pack; no
UI code changed).

## 2026-09-26 · Spark SQL Practice track, light first version

Branch `feature/spark-sql-practice`. Julian's preference: a handful of cards across the key topics rather than one
deep area.

- New Practice language `sparksql` (label "Spark SQL"): Spark SQL in ANSI mode, translated to DuckDB by the existing
  translator (`runtime/sqldialects`, dialect `spark`) and really run on the fixtures, truth `semantic-emulation`,
  labelled "Spark SQL dialect translated to DuckDB, not Spark". It is the first Practice language whose id differs
  from its dialect id (`PRACTICE_DIALECT_OF` in `runtime/datapass_runtime/sql_dialects.py`), so it does not clash with
  the `sparklab` DataFrame language. Wired like `tsql`/`bigquery`: contracts, pack registry, capabilities kernel,
  API model, Practice file extension, card notice, exercise README.
- New pack `spark-sql-v1`, 9 cards, one per topic: NULL filters, `COUNT_IF` + `HAVING`, `LEFT ANTI JOIN` vs
  `NOT IN` with NULLs, `QUALIFY ROW_NUMBER` dedup, `LAG` per partition, `DATEDIFF(end, start)`, `TRUNC(date, 'MM')`
  month buckets across years, `DENSE_RANK` top-N with ties, case-insensitive email domains. Starters are runnable
  buggy queries; one mutant each. Generated by `scripts/authoring/gen_spark_sql.py`; expected rows computed through
  the same grading path and reviewed by hand.

Checked: `npm run compile`, `npm test` (277 cards for 601 variants), the packs gate on `spark-sql-v1` (9 references
pass, 9 starters and 9 mutants rejected), `runtime_smoke.py`.

Not checked: the new `test:host` step (grades one Spark SQL exercise, NOT IN starter fails, EXPLODE refused) and
`test:ui` ran in CI only; no real-VS Code click-through of a Spark SQL card.

## 2026-09-26 · Spark Lab: Polars as the lightweight alternative to PySpark

Branch `feature/spark-lab-polars`. Julian's direction: Polars available in the Spark Lab next to PySpark.

- **Engine choice** in the SparkLab module: PySpark (SparkLab, bounded, plans simulated) or Polars. Polars runs the
  active file through `/api/local/execute` with `language: "polars"`: real local Python, refused while trusted Python
  is off (the Run button stays disabled until the running runtime reports it), never a SparkLab fallback. When the
  file ends with (or `display`s) a LazyFrame, the shared Python runner collects it and returns `polars_plan`, Polars'
  own `LazyFrame.explain()`, labelled real (`runtime/datapass_runtime/execution.py`). New **Open Polars scratch**
  (`polars.py`, same revenue query as the SparkLab scratch), a PySpark → Polars column in the operation cards, and a
  truth row.
- **Practice**: `spark-lab-v1` gains 7 Polars variants (`<spark id>-polars`) of the 7 result lessons; the 5 plan
  lessons have no Polars equivalent. Each carries a `semantic` block whose `id` is the Spark exercise id, so it lands
  on the same card (`src/exerciseCatalog.ts`: a plain-pack exercise's key uses `semantic.id` when present; keys of
  exercises without one, and so saved progress, are unchanged). Expected rows come from the SparkLab reference;
  starters build typed frames from the fixture tables (empty tables keep their columns). Polars-specific pitfalls:
  `coalesce=True` on full joins, `pl.lit` inside `when/then`, `ne_missing`, `pl.len()` vs `count()`, and window order
  following row order (an extra `unsorted-input` hidden fixture). Generated by `scripts/authoring/gen_spark_lab.py`.

Checked: `npm run compile`, `npm test` (arena smoke: 268 cards for 592 variants, the Spark cards carry PySpark and
Polars), `runtime_smoke.py` (new LazyFrame plan check), compileall, the packs gate on `spark-lab-v1` (19 references
pass, 19 starters and 24 mutants rejected) and `engine-lab-v1` (103/103/69), and `npm run test:ui` in real VS Code
1.139.1: 53/53 steps, including the SparkLab tab switched to the Polars engine at 521 px without overflow.

Not checked: a Polars run clicked in real VS Code with trusted Python on (the UI pass does not enable trusted Python;
the runtime path is covered by `runtime_smoke.py`); the full packs gate and `test:host` ran in CI only.

## 2026-09-26 · One controller, one contract and one runtime client per lab (roadmap D-6)

`src/workbenchPanel.ts` (2,161 lines, 84 message types, every lab in one class), `src/webview/contracts.ts` (1,344
lines) and `src/runtimeManager.ts` (1,179 lines) caused most merge conflicts between parallel sessions. They are split
per lab, with no behaviour change. This is the base of the per-lab template (roadmap T-2), which is not built here.

- **Controllers** (`src/labs/<lab>/controller.ts`, one per module id plus `workbench` for the shell and `missions` for
  the missions the dbt, Terminal and Infra Labs share): each answers its lab's messages through a typed
  `MessageHandlers` map, keeps its host state (the dbt Lab's `dct validate` results, Practice's revealed solutions,
  the Projects verification in flight, the last files to reveal a line in) and adds its part of the Workbench state
  (`contribute`). The dbt artifact watcher and the Infra Lab's command subscription moved into their controllers.
  Missions take per-lab hooks (restart warning, what to close before a rebuild, what to open), replacing the
  `terminal ? … : infra ? … : dbt` branches.
- **Message table**: `src/labs/controllers.ts` builds the controllers and wires the four cross-lab actions (the retail
  demo opens the Pipeline, Airflow and dbt starters; a project step opens an exercise and writes the retail demo
  files); `buildMessageTable` (`src/labs/messageTable.ts`) routes each message type to its one controller and refuses
  two controllers for one type. A message type that no controller handles fails the typecheck
  (`UnhandledMessageTypes`). `workbenchPanel.ts` (194 lines) keeps only the webview, the state it posts, the editors
  it remembers and the table; which modules refresh on save comes from the controllers (`refreshOnSave`).
- **Contracts**: `src/webview/contracts/<lab>.ts` holds each lab's views, its slice of `RuntimeViewState` and
  `WorkbenchViewState` and its message union; `contracts/index.ts` composes them, so every `webview/contracts` import
  is unchanged. The old and new composed types were checked mutually assignable with the TypeScript compiler, and the
  mission list type (three inline copies) is one `MissionListView`.
- **Runtime clients**: `src/labs/<lab>/client.ts` (Mosaic, SparkLab, Practice, Pipeline, Airflow, Cloud Lab, BI, Infra,
  missions, Projects) on a `RuntimeConnection` the manager hands out (running URL, token-carrying requests, the shared
  state); callers use `runtimeManager.labs.<lab>.<method>` with the old method names. `runtimeManager.ts` (583 lines)
  keeps the process, setup, token, state and the shared catalog (list, lend, reattach, schema). `runtimeErrorDetail`
  moved to `src/platform/runtimeClient.ts`.
- **Helpers, one copy each**: `exists` (five copies), `safeRelativeParts` (three left), `writeIfMissing` and
  `copyWithoutOverwrite` (two) now live in `src/workspaceFiles.ts` and `src/platform/workspacePaths.ts`.
- **Tests**: `scripts/message_table_smoke.mjs` (in `npm test`) checks the routing, the duplicate refusal, one contract
  file per lab folder, and that no lab imports another lab (the registry wires them). The packaged-VSIX UI pass has a
  new step that clicks one real button per lab (Cloud Lab retail demo across four controllers and its run, Cloud Lab
  samples, BI build, Airflow simulation, Pipeline run, Projects prepare, Terminal Lab terminal) and checks the result
  on disk or in the runtime's answer.

Checked: `npm run compile`; `npm test` (27 smokes, with `message_table_smoke.mjs`); the old and new composed contract
types mutually assignable (a throwaway compiler check against the old `contracts.ts`); every string literal of the old
panel and runtime manager (messages, endpoints, labels) still present, and the same numeric timeouts; the
unhandled-message check fails when a controller is left out of the registry; `pip install ./runtime`, compileall,
`runtime_smoke.py`, `exercise_packs_smoke.py` (584 / 584 / 549, unchanged), `projects_smoke.py`,
`infra_missions_smoke.py`, `terminal_missions_smoke.py`, `missions_smoke.py` with a dbt venv; `npm run test:host`
with `DATAPASS_E2E_PYTHON` and `DATAPASS_DBT_PYTHON` (40 steps, including the dbt Core, dbt Charts, missions,
Terminal Lab and Infra Lab steps); the packaged VSIX in a real VS Code window (`npm run test:ui`, 51/51 with the new
per-lab step).

Not checked: the webview buttons that the UI pass does not click (for example the Databricks and SQL pool runs, dct
render and serve, the dbt install) went through the message table only in the typecheck and the host suite's direct
calls. Found on the way, left for its own task: once the labs hold data (after the new per-lab step), the Cloud Lab
Pipelines and Databricks tabs and the BI Lab Lineage tab overflow at 520 px (`.factory-toolbar`); the layout checks
still run on a fresh workspace, as before.

## 2026-09-26 · Infra Lab, first tranche: simulated Terraform, Docker, monitoring and Kubernetes

Decided with the user before coding: pure simulation (no real terraform, docker, kubectl or az, even when installed;
real-tool exercises may come once the app is finished, and a real `terraform fmt` was mentioned as a possible later
option), a fake Azure that uses real azurerm type names with a documented subset of arguments, one simulated
terminal tab for the four simulators, and a thin slice of all four (one mission each) rather than Terraform alone.

- **Runtime** (PR #50, `runtime/infralab`): a whitelisted HCL reader and evaluator; a Terraform CLI simulator
  (init, validate, plan, apply with the "Enter a value" prompt, destroy, import, state, output, show; count,
  for_each, lifecycle, moved and import blocks, tfvars) on a simulated azurerm provider and subscription, with
  azurerm's errors (already exists → import, globally unique names, a resource group still holding resources);
  a Docker engine simulator (Dockerfile reader, BuildKit-style cache on the real context files, hadolint-style
  lint, run, ports, health checks, compose); `az` + Azure Monitor alert replay on recorded metric scenarios; a
  Kubernetes simulator (strict validation, scheduling, readiness, rolling updates recording the fewest pods really
  serving, services and endpoints). A shell routes one line at a time and journals it. API:
  `/api/local/infra/command`, `/api/local/infra/state`.
- **Missions** (`lab: "infra"`, `runtime/missionlab/infra.py`, `content/missions/infra-v1`): fixture = files +
  simulated world + setup commands; references are shell lines; 11 check kinds on the simulated world. Missions:
  `lake-landing-zone` (import a portal-made resource group, ADLS Gen2, for_each containers, converged plan),
  `containerize-ingest-api` (slim non-root image, cached dependencies, .dockerignore, healthy compose stack),
  `page-on-shir-outage` (ADF self-hosted IR outage: two alerts that page in time and stay quiet for the backup
  spike), `zero-downtime-rollout` (service selector, readiness probe, maxUnavailable 0, release 1.5.1).
- **Workbench** (module `infra`, `datapass.openInfraLab`): `src/infraLab.ts` opens one VS Code Pseudoterminal per
  mission folder (no process; `src/platform/infraShell.ts` edits the line); `InfraSurface.tsx` shows the simulated
  world of the selected mission folder and the shared MissionsPanel. The Self-hosted IR VM is a Windows VM, as the
  real SHIR requires (the roadmap said "Linux VM").

Checked: `infra_missions_smoke.py` (4 references pass; 4 untouched fixtures, 3 starters played with the reference
commands and 23 mutants fail; fixtures deterministic; Start over → attic); `runtime_smoke.py` (infra section:
fixtures, untouched never pass, shell refusals, folder confinement, contract validation); compileall; Pylance stubs
check; `npm run compile`; `npm test` (with `infra_lab_smoke.mjs`); `npm run test:host` with the new Infra Lab step
(lines typed in a real Pseudoterminal reach the simulators and the mission passes); the packaged VSIX in a real VS
Code window (`npm run test:ui`, step 5b: the SHIR mission typed in the simulated terminal and passed). A second valid
route for the Terraform mission (`terraform import` command instead of an import block) was played by hand and
passes.

Not checked: the other three missions were not played through the webview (the smoke plays them through the API);
Linux CI runs the UI pass's new step for the first time with this PR.
## 2026-09-26 · Practice arena: problems, spaced review, interview mode (roadmap V2-1)

Three PRs, each merged on green CI.

- **#44 One card per problem.** `src/platform/practiceProblems.ts` groups the catalog by `<pack>/<problem>` (the
  semantic id of `<scenario>-<language>` variants): 268 problems for 585 variants. `PracticeProblemCard.tsx` shows the
  prompt once and a language switch (SQL, Snowflake, T-SQL, BigQuery, Python, Polars, PySpark, dbt) with ✓ / • per
  language. The card remembers its language, and the last language picked becomes the default elsewhere. A project
  step opening an exercise selects its language. Progress stays per variant; the card summarizes it ("solved in 2 of
  6"). The language filter keeps problems offered in it, and the status filter then reads that variant.
- **#48 Spaced review** (the user chose Leitner boxes). `src/platform/practiceReview.ts`:
  `review: { box, due }` in the variant's record. A passed Submit on a due or never-reviewed variant climbs one box
  (1, 3, 7, 14, 30, 60 days); a failed or erroring Submit goes back to box 1 (tomorrow); a pass before the due day
  and Run visible change nothing. Older records are due the day after their last activity. Practice › Review lists
  due problems, most overdue first, then the weakest box, and keeps a reviewed card on screen.
- **This PR: interview mode.** `src/platform/practiceInterview.ts` and `PracticeInterview.tsx`.
  - Formats (the user asked for both): **Mixed interview**, which cycles SQL, Python and PySpark, and **One
    language**, with an optional pattern.
  - Each problem gets a pattern family from its topics (window functions, time series, deduplication, joins,
    aggregation, nulls and quality, strings, filtering and logic). The draw avoids repeating a family while it can,
    and draws only locally graded problems.
  - Options: count (1–8), difficulty, and a time limit (default 15 minutes a problem). The timer runs into overtime
    (the user's choice).
  - The cards drop hints, reference solutions and topics (they name the pattern), and the language is locked.
  - Submits are normal gradings: they solve the variant and move its review (the user's choice). The series is
    followed through the variants' progress records.
  - **Finish** shows the summary (score, time, overtime, the pattern and result of each problem). The host validates
    it and appends it to `practice.interviews` (last 20). Past interviews are listed under the setup.
  - The Practice modes are a `lab-subtabs` TabList, so `npm run test:ui` checks their layout.

Checked:
- `npm run compile`, `npm test`. The new `practice_arena_smoke.mjs` runs over the shipped packs and covers:
  - grouping: every scenario is one card;
  - the whole Leitner climb, with month and year boundaries, failures and same-day passes;
  - 40 seeded mixed draws: SQL/Python/PySpark on three different patterns;
  - fixed draws with difficulty and pattern filters;
  - tracking, the summary, and parsing and trimming of the history.
- The runtime gates, `exercise_packs_smoke.py`, `projects_smoke.py`, `npm run test:host`.
- The packaged VSIX in real VS Code, driven by Playwright `_electron.launch` with a fresh profile under `C:\dpa`:
  - zilla-001 as one card with six languages; the Snowflake starter failed, then the reference passed ("solved in 1
    of 6", only the Snowflake record written);
  - with `progress.json` aged, Review showed the card due on SQL and Snowflake; a Snowflake pass moved it from box 2
    to box 3 (due in 7 days);
  - a 1-minute mixed interview (eng-cross-merge SQL, zilla-024 Python, zilla-001 PySpark): languages locked, no
    hints or topics; SQL solved at 0:09, the PySpark starter failed; overtime shown in red; the summary was saved in
    `progress.json` and listed under Past interviews.
  - Screenshots reviewed.

Not checked: an interview kept across a VS Code window reload (the series lives in the webview state, which
survives hiding the Workbench, not a restart).

## 2026-09-26 · Stale managed runtime after an extension update

Bug found by the packaged-VSIX UI pass (roadmap T-3): installing a newer VSIX over a profile kept the managed venv's
runtime package from the OLD VSIX, and `RuntimeManager` called the environment "ready" as soon as the venv's Python
existed. The kernel worker imports the installed package, so a Practice Submit got 400 from the old runtime.

- `src/platform/runtimeFingerprint.ts`: a `sha256:` content hash of the bundled `runtime/` sources (path + content of
  every file; bytecode, `build/`, `dist/`, `*.egg-info` and hidden folders ignored, like `.vscodeignore`), the
  `datapass-runtime.json` marker in the venv (fingerprint, extension version, time), and the missing / ready / stale
  decision. A venv without a marker (set up before this change) is stale. The runtime keeps version 0.1.0, so the
  version is shown in messages only.
- `RuntimeManager`: the environment is `stale` when the marker differs; Setup fingerprints the sources before the
  install, removes the marker before installing and writes it after the verify step (a half-installed venv never
  looks current). The same Setup path updates an existing venv ("Datapass runtime update" notification, same step
  progress; uv `--reinstall-package`, pip reinstalls a local directory). `start()` re-checks and updates a stale venv
  before starting; it never runs the old install. Unmanaged interpreters (no managed venv) are not checked.
- Workbench: Environment "needs update", the reason in the Local runtime card, **Update runtime** in the top bar
  instead of **Start runtime**.
- Tests: `scripts/runtime_fingerprint_smoke.mjs` (in `npm test`); a host E2E step for the missing / stale / ready
  decision; the UI pass's new upgrade step (tampered marker and installed module, window reload, Update runtime,
  start), and `DATAPASS_UI_KEEP=1` now takes the Update runtime path instead of failing.

## 2026-09-26 · Short handoff: current state split from the history (roadmap T-5)

`docs/CLAUDE_HANDOFF_2026-09-24.md` (1,300 lines) was split:

- `docs/HANDOFF.md`: the current state, under 200 lines (what exists per module with its truth and code, the truth
  model, where things live, how to test with the time-saving notes, known gaps gathered from every tranche's open
  points, the next directions with a link to the roadmap artifact, what not to do).
- This file (`git mv` of the old handoff, so `git log --follow` keeps its history): every dated tranche, newest
  first; the old "Current status" block became two dated sections ("PR #1 ..." and "Stack merged ..."); the old
  reference sections 1–11 are kept whole under "2026-09-24 · Original handoff reference sections".
- CLAUDE.md "Current continuation point" points at both files and the roadmap.

Checked: a script compared the files: every non-heading line of the old handoff is in this file (0 missing); the
module ids, paths and packs named in HANDOFF.md were checked against `src/modules.ts`, the tree and the manifests.
Docs only; the quality gates were run for the conflict-reduction PR just before.

## 2026-09-26 · Conflict reduction: per-pack quality files, dated handoff sections (roadmap V1-7)

- **Exercise gate data per pack.** The central `MUTANTS` dict and the flag sets of `scripts/exercise_packs_smoke.py`
  (`RUNNABLE_STARTER_PACKS`, `PLAN_ONLY_STARTERS`, `BUILD_ERRORS_ARE_ANSWERS`, `STARTERS_REFUSED_BY_DESIGN`,
  `SKIP_RUNTIMES`) moved to `content/exercise-packs/<pack>/quality.json` (`flags`, `notes`, `mutants`). The smoke
  went from 1,250 to about 150 lines and refuses unknown keys, unknown packs and exercise ids from another pack.
  `quality.json` is test-only: `.vscodeignore` leaves it out and `package_smoke.mjs` checks the rule (`vsce ls`
  lists none). The generators write their pack's mutants through `scripts/authoring/pack_quality.py`; `gen_zilla.py`
  no longer rewrites the smoke script. Format: docs/EXERCISE_AUTHORING.md "Quality gate".
- **Handoff headings.** Tranche sections are `## YYYY-MM-DD · Title`; the `§0x` cross-references (several already
  pointed at the wrong section after renumbering) now name the section.

Checked: `exercise_packs_smoke.py` gives the same counts before and after (584 reference solutions, 584 starters and
549 mutants rejected); `write_mutants` round-trips every `quality.json` byte for byte; `npm run compile`; `npm test`;
`pip install ./runtime`; compileall; `runtime_smoke.py` (a first run hit a transient Windows lock renaming a temp file
in the SQL pool block; the rerun passed); `projects_smoke.py`; `npm run test:host` with `DATAPASS_E2E_PYTHON`. The
generators were not rerun (several need CodeDELeet or dbt Core); their change is the final write call only.

## 2026-09-25 · Packaged VSIX UI pass in the repository (roadmap T-3)

The Playwright pass that earlier sessions ran from a scratch file is now `scripts/vscode_ui_pass.mjs` (`npm run test:ui`, after `npm run package`) and the CI job `vscode-ui` (Linux, `xvfb-run` with a 1600×1000 screen, screenshots uploaded as `vscode-ui-pass`). See docs/LOCAL_TEST.md, "Packaged VSIX UI pass".

- **Covers.** Fresh-profile VSIX install; Create .datapass project; Setup/Start runtime; raw 401/400 against the live port and no token in the log; Mosaic Run active SQL result; Practice Open solution + Submit graded; every module tab and lab sub-tab at a 520 px Workbench with an overflow probe; Stop runtime and a closed port; no uncaught webview errors.
- **Overflow probe.** Flags any element whose right edge passes the webview unless an ancestor scrolls or clips it; it must first catch a planted 2000 px block, so it cannot pass blind. First run: all 17 tab/sub-tab layouts (9 module tabs, 8 more lab sub-tabs) clean at 521 px.
- **Gotchas.** Typing into Monaco through Electron did not reach the editor; the script writes the scratch file on disk and waits for the editor to show it. The first Practice Submit on an exercise without a starter only creates the file, so the pass clicks Open solution first. `locator.evaluate(fn, arg)` passes the element first. The exercise editor tab is titled `<exercise> · <language>`, not `solution.*`.

## 2026-09-25 · Terminal Lab: real bash, PowerShell and Git

Third lab of the map approved on 2026-09-25 (BI Lab, dbt Lab, **Terminal Lab**, then Infra Lab). The learner types
their own commands in a real VS Code terminal; Datapass runs none of them and checks the resulting folder and Git
repository. Built on `runtime/missionlab` (README there has the full contract).

- **#35 Runtime and pack.** `lab: "terminal"` missions: a `fixture` (the pack's `project/` overlay, inline files with
  CRLF or the executable bit, a Git history of fixed git commands with a fixed author and dates, so the hashes are
  reproducible; the learner's global/system Git config is not read) built by `POST /api/local/missions/setup
  {mission_id}`. Start over moves the old folder to `.datapass/missions/attic/<id>-<time>/`. Thirteen check kinds in
  `missionlab/terminal.py`: path, text (UTF-8, or UTF-16 with a BOM as Windows PowerShell 5.1's `>` writes), listing,
  csv (a `#TYPE` line fails), script (text without comments, never executed), git_repo, git_branch, git_log, git_file,
  git_tag, git_ignore (the repository's own rules, not the learner's global excludes), git_stash, any_of. Git is read
  with read-only commands, `core.fsmonitor` off, hooks pointed at nothing, `GIT_CEILING_DIRECTORIES`.
  `content/missions/terminal-v1`: 8 missions (tidy a landing folder; grep an error report; a guard script with exit
  codes; PowerShell objects; first repository with .gitignore, executable bit, LF and an annotated tag; a merge
  conflict; interactive rebase + cherry-pick -x; reflog rescue of a deleted branch, a reset commit and a stash).
  `scripts/terminal_missions_smoke.py` plays every reference with real bash, pwsh and (on Windows) Windows PowerShell
  5.1: 18 reference plays pass, 8 untouched fixtures and 35 mutants fail; in CI (runtime job, pwsh required).
- **This PR: the Workbench module** (`terminal`, `datapass.openTerminalLab`). `src/terminalLab.ts` finds the shells
  (Git Bash next to git.exe or in the Git for Windows folders, never WSL's System32 bash; pwsh, then Windows
  PowerShell 5.1; `datapass.terminalLab.bashPath` overrides) and Git (version and the global identity, so the lab can
  warn before `git commit` fails). The learner picks the shell (remembered in global state); the terminal opens in
  `missions/<id>/` (Git Bash as a login shell with `CHERE_INVOKING=1` so it stays there) and nothing is typed in it.
  The ticket goes to `.datapass/missions/tickets/<id>.md`, outside the folder the checks read. `MissionsPanel` is
  lab-neutral (open label, folder note). A terminal mission's setup and check do not need the catalog, so a lent
  catalog does not block them. Start over first releases the folder (`TerminalLabSession.release`): the lab's
  terminals close and the VS Code Git extension's repository is closed, then reopened on the rebuilt folder. On
  Windows, its `.git` watch made the move fail in a real window (found by the Playwright drive); the runtime also
  builds fixtures outside the workspace now, so Source Control never opens a half-built repository.
  CLAUDE.md: truth model, product boundary, security, gates.

Checked:
- `npm run compile`, `npm test` (new `terminal_lab_smoke`), runtime gates as in #35;
- `npm run test:host`: a Terminal Lab step starts merge-conflict, opens the real bash terminal in the folder, types
  the reference there (as a learner would), and polls the checker until it passes; Start over puts the folder in the
  attic; with a PowerShell present, server-inventory-report is played the same way;
- the packaged VSIX installed in a fresh profile and driven with Playwright `_electron.launch`: Setup and Start
  runtime, Start mission (tidy-landing-folder) typed in Git Bash, a partial answer checked "not yet", then passed;
  merge-conflict resolved in the terminal and passed; Start over through the modal. Screenshots looked at.

Open points:
- Datapass cannot tell *how* a result was produced (a learner could edit files in the editor instead of the
  terminal); the checks read state, as the lab's truth model says. Scripts are read as text; their behaviour is
  checked through the evidence the learner's own run leaves (for example `logs/check.status`).
- The dbt Lab › Missions overlap reported after the dbt Lab rebuild (runtime card over a ticket when scrolled) did not
  reproduce in the Playwright drive, wide or narrow: nothing in workbench.css is sticky or fixed, and the side column
  scrolls with the page. Left as is; a screenshot of it happening would help.
- Next: **Infra Lab** (simulated Terraform, Docker, VM + monitoring, Kubernetes), reusing missionlab with its own
  check kinds.

## 2026-09-25 · V2-2 + D-5: one SQL dialect translator for the whole Workbench

The user asked for a "dialect button like a kernel". Before this, three SQL translation paths coexisted: the SQL pool's
hand-written T-SQL tokenizer, `runtime/snowflakesql` (sqlglot, Practice) and `runtime/bilab`'s lineage (sqlglot, static
analysis, unchanged). Delivered as four PRs, each merged on green CI:

- **#38 `runtime/sqldialects`** (README there: subsets, rules, refusals, known differences).
  - Dialects: T-SQL, Snowflake (the PR #19 subset, unchanged), BigQuery, Spark SQL (ANSI mode, read with sqlglot's
    Databricks dialect), PostgreSQL.
  - Label: "<dialect> dialect translated to DuckDB, not <engine>".
  - Every syntax node and function is allowlisted; anything else is refused by name. The clock, random values and
    file/network table functions are refused everywhere.
  - Rules keep the engine's result where DuckDB differs: integer division, CAST to integers, T-SQL
    `AVG`/`LEN`/`+`/`CONVERT` styles/`VARCHAR(n)`, dates staying `DATE`, Sunday weeks, weekday numbers,
    `REGEXP_EXTRACT`, `SUBSTRING` starts, zero divisors raising, NULL order.
  - Type-dependent rules read the caller's schema: a qualified copy is annotated by sqlglot and the types are mapped
    back by node id, with a return-type table for functions sqlglot leaves untyped. A type that stays unknown is a
    refusal that says how to make it explicit.
  - Rule of thumb: where DuckDB would silently return another value, rewrite or refuse; where DuckDB raises and the
    engine returns a value, document it as a known difference.
  - `/api/local/execute` (language `sql`) and `/api/local/explain` take `dialect`. The translated SQL goes through the
    catalog's own validation. The run journal records dialect runs as `emulation`.
  - The kernel worker now reports ValueError subclasses as rejected requests (400, not 500).
- **#39 SQL pool delegation.** `sqlpoollab/tsql.py` keeps GO batches, CREATE TABLE types, WITH options (distribution,
  columnstore, HEAP, partitions, CLUSTER BY), procedures, DECLARE/SET and names.
  - Every query, DML statement and expression goes through the shared T-SQL dialect, with hooks: variables, the fixed
    lab clock, `dbo`→warehouse, unqualified names typed as warehouse tables.
  - Every pool script of the repository gave identical statuses, messages, plans and rows before and after.
  - sqlpool-v1 gate counts unchanged.
- **#41 Mosaic.** Status bar "SQL: DuckDB ▾" on `.sql` files (`src/sqlDialectStatus.ts`, `src/platform/sqlDialect.ts`).
  - The picker writes, replaces or removes the first line `-- dialect: <name>`.
  - Run and Explain active SQL send it.
  - Mosaic shows the translated DuckDB SQL, its label and rewrites; **Open translated SQL** opens a read-only tab.
  - The query history keeps the dialect.
- **Practice (the last PR).** Languages `tsql` and `bigquery`, graded like `snowflake` with the fixture types.
  - `engine-lab-v1` re-surfaces the donor engine lab's T-SQL and BigQuery variants (leetcodedataeng, `dbo.` dropped):
    17 + 18 variants, each with a passing reference, a failing starter and a mutant. Several mutants are dialect traps.
  - `eng-split-explode` has no variant: arrays are outside both subsets.

Checked:
- `npm run compile`, `npm test` (new `sql_dialect_smoke`: header parsing, and dialect ids and labels equal to the
  runtime's);
- compileall, `runtime_smoke.py`: pinned results per dialect (Snowflake 41, T-SQL 32, BigQuery 20, Spark SQL 15,
  PostgreSQL 16), about 80 refusals, script mode, the API, the pool through the shared dialect;
- `projects_smoke.py`;
- `exercise_packs_smoke.py`: 584 reference solutions, 584 starters and 549 mutants rejected (549/549/514 before the
  35 new variants);
- `npm run test:host`: new Mosaic dialect and engine-lab dialect steps;
- the packaged VSIX in real VS Code (Playwright `_electron.launch`, fresh short profile `C:\dpsq`, runtime venv
  prebuilt at the profile's globalStorage): status bar, picker, header, Start runtime, Run, the translated panel,
  Explain, Open translated SQL, back to DuckDB. Screenshots reviewed.
  - The pass found two UI problems, fixed in #41: the panel widened the narrow SQL block, and the picker was offered
    on the read-only translated tab.
  - Harness note: write the SQL file under a new name on each run, or VS Code's hot exit restores the old buffer.

Open points:
- T-SQL collation: SQL Server's default compares strings case-insensitively; here comparisons are case-sensitive. This
  is documented as a known difference, not emulated.
- The translated SQL is one line: the Mosaic panel wraps it, but the read-only tab does not pretty-print it.
- Spark SQL and PostgreSQL have no Practice content yet; adding the languages would take two lines each (see
  `PRACTICE_DIALECTS`).

## 2026-09-25 · Runtime loopback authentication (audit D-2, D-9)

Audit finding: the runtime declared no middleware, so any local process or a DNS-rebinding web page could call it, including `POST /api/local/execute` with trusted Python on.

- **Token.** `RuntimeManager.start` generates a token per launch (`newRuntimeToken`, `src/platform/runtimeClient.ts`, 32 random bytes), keeps it in memory, and passes it with the port as `DATAPASS_RUNTIME_TOKEN` / `DATAPASS_RUNTIME_PORT` (`runtimeProcessEnv` drops inherited values). All HTTP helpers moved to `runtimeClient.ts` and send `X-Datapass-Token`; the class routes every call through `postJson` / `getJson`.
- **Runtime.** `runtime/datapass_runtime/auth.py` (pure ASGI middleware): Host must be `127.0.0.1:<port>` or `localhost:<port>` (400), token must match (401, `hmac.compare_digest`), no token or port configured → 503 on everything. Decision: `/api/health` is not exempt (the extension always has the token; the refusal leaks nothing).
- **Callers.** TestClient smokes use `scripts/runtime_test_auth.py` (`client_kwargs()`); the host E2E injects a hostile inherited `DATAPASS_RUNTIME_TOKEN`. The kernel worker drops `*TOKEN*` variables; dbt/dct terminals take the extension host's environment, so neither sees the token.
- **D-9.** `makeNonce` uses `crypto.randomBytes` (unbiased); the webview CSP `img-src` is `webview.cspSource data:` (no `https:`). The only webview image is the dct PNG render, inlined as a data URL.
- **Tests.** `scripts/runtime_auth_smoke.mjs` (client header on every helper, env, nonce, CSP); `runtime_smoke.py` (401 without/with a wrong token, 400 for a rebound or other-port Host, `localhost:<port>` accepted).

## 2026-09-25 · dbt Lab rebuild: real dbt Core, dbt Charts, missions

The user approved a lab map on 2026-09-25: the BI Lab stays the guided place to learn data warehousing (with the dbt
emulation, labelled "not dbt Core"), and the **dbt Lab** is rebuilt as the real-life lab. Terminal Lab (real shells)
and Infra Lab (simulated Terraform, Docker, VM + monitoring, Kubernetes) come later. Every lab is a package of the one
local FastAPI runtime. Delivered as five PRs, each merged on green CI:

- **#18 Catalog tree view.** A native TreeView (`datapass.catalog`, `src/catalogTree.ts`): catalog layers first,
  then any other schema of the DuckDB file (the ones dbt builds); tables and views with a real `COUNT(*)`, columns
  and types. Click opens `.datapass/scratch/<schema>.<table>.sql` (`SELECT * ... LIMIT 100`, never overwritten);
  Preview Rows runs it into Mosaic. Runtime: `GET /api/local/catalog/schema`.
- **#22 Real dbt Core runner and the catalog handoff.**
  - Managed tools: `dbt-tools-venv` in global storage (Python 3.10–3.13; `py -3.13` … or `datapass.dbtTools.python`),
    created only by **Install dbt tools** after a modal; DuckDB pinned to the runtime's version.
  - `.datapass/dbt/profiles.yml` generated: one output per project profile, target schema `dbt_dev`, no secrets.
  - Buttons type the real command in a terminal in the project folder (tools on PATH, `DBT_PROFILES_DIR`, telemetry
    off); the learner retypes or edits it. Commands in a terminal are queued (shell integration's `executeCommand`
    would interrupt a running one).
  - Handoff (investigated first): the kernel worker holds `workspace.duckdb` open and dbt fails with an IO error.
    `POST /api/local/catalog/release` stops the worker gracefully and answers 409 to every catalog request until
    `/reattach`, which reopens it (409 again while the file is held). The terminal session releases on shell
    integration's command start (dbt and dct commands that open the database) and reattaches on its end, with retries
    (Windows frees the file a moment after the process exits); **Reattach catalog** in the lab and the Catalog view.
    A lock held by an outside process maps to a clear 409.
  - Artifacts: `target/manifest.json` + `run_results.json` → command, counts, DAG by status, failures, node details,
    labelled "dbt Core (real)".
- **#25 Real dbt Charts.** `dbt-charts>=0.8,<0.9` in the same venv. Conventions checked on dct 0.8.0 itself (`dct
  --help`, `dct docs`) and on github.com/dbt-labs/dbt-charts: `dbt_charts.yml` sources (`type: dbt_profile`, found
  through `DBT_PROFILES_DIR`), boards in `charts/`, `{{ ref() }}` resolved against the manifest, `dct render` →
  `renders/<stem>.<ext>` (it does not create the `--output` folder), `--format json` = resolved board with data,
  `dct validate --json` without a database, DuckDB opened read-only (so the handoff applies too). Validate / Render
  PNG · JSON · HTML in the lab; the PNG as a `data:` image (CSP unchanged); HTML opens in the system browser;
  `dct serve --host 127.0.0.1` in its own terminal, opened in the Simple Browser. The retail sample board was
  rewritten for dct 0.8.
- **#32 Missions** (`runtime/missionlab`, README there; `content/missions/dbt-v1`; dbt Lab › Missions):
  ticket, acceptance criteria, hints on demand, no pre-chewed starter; the project is copied to `missions/<id>/`
  (never overwritten) with `TICKET.md`; fixture batches load into the mission's own raw schema; a hidden checker with
  11 check kinds (SQL, manifest node and test, run results, freshness config and result, dct validate, board, render,
  file, Airflow). Five missions on the BI warehouse sources: prod unique-test failure, source freshness, incremental
  over a changes-only export (with **Load next batch**), a 3-day backfill scheduled from an Airflow 3 DAG (the
  simulator replays the three nights; `macros.ds_add(ds, -1)` because Airflow 3's `@daily` logical date is the
  midnight that starts), a sales board in dbt Charts. Progress in `.datapass/missions/progress.json`.
- **This PR: truth model and docs.** CLAUDE.md (product boundary, truth model, security), QUICKSTART, ARCHITECTURE,
  LOCAL_TEST, this section.

Retired with the rebuild: the dbt Lab's regex static lineage (use `dbt parse` for a real manifest, or the BI Lab's
emulation), the PATH `dbt --version` probe (`src/platform/dbtVersion.ts`), the single hard-coded `dbt/retail-dbt`
project (the sample stays, as one project among others), and the unwired in-runtime dbt adapter of the old API layer
(`runtime/datapass_runtime/dbt_runner.py`, `dbt_worker.py`, `local_routes.py` and `pipeline_runner.py`, which nothing
imported). The BI Lab's emulation (`runtime/dbtlab`) is unchanged, so `dbt_oracle_smoke.py` was not needed.

Checked:
- `npm run compile`, `npm test` (new `catalog_tree_smoke`, `dbt_lab_smoke`, `missions_ui_smoke`);
- `pip install ./runtime`, compileall with `runtime/missionlab`, `runtime_smoke.py` (catalog schema; handoff with a
  second process writing the file; every mission batch and an untouched check), `exercise_packs_smoke.py`,
  `projects_smoke.py`;
- `scripts/missions_smoke.py` with real dbt Core 1.12.5 + dbt-duckdb 1.11.0 + dct 0.8.0: 5 references pass, 5
  untouched projects and 7 mutants fail (in CI: the runtime job installs the dbt tools);
- `npm run test:host` with `DATAPASS_DBT_PYTHON` (in CI too): `dbt build` of the BI project in a real terminal with
  the catalog lent and reattached through shell integration; `dct render` of the retail board; the prod-unique
  mission reproduced, fixed and passed through the missions service;
- the packaged VSIX installed with `code --install-extension` and driven in the user's VS Code build (Playwright
  `_electron.launch`, fresh `--user-data-dir` and `--extensions-dir`): Setup runtime → Catalog tree → Install dbt
  tools (the real install) → dbt build in the terminal → artifacts → dct render → a mission checked (not yet, then
  passed after the fix). Screenshots looked at.

Open points:
- `dct serve` keeps the catalog lent while it runs (the runtime cannot reopen a file dct holds read-only); stop it to
  get the catalog back. A later option: serve from a copy of the file.
- Without shell integration (cmd.exe) the end of a command is not reported: new artifacts trigger a reattach attempt
  and **Reattach catalog** is always there.
- `dbt deps` downloads packages (hub.getdbt.com or Git) when a project declares them; the shipped projects declare
  none. dbt Charts is pre-1.0 and pinned to 0.8.x: re-check its conventions before moving the pin.
- Next: **Terminal Lab** (real bash, PowerShell and Git; Datapass checks the resulting folder and repository state)
  can reuse `missionlab` with new check kinds, then Infra Lab.

## 2026-09-25 · Stack merged, installed VSIX checked in VS Code

- **Merge.** PRs #8–#16 (Airflow; Cloud Lab pipelines, SQL pool and Databricks with their packs; BI Lab and its dbt tab) were merged into `main` bottom-up with merge commits, after resolving their conflicts with the Spark lab (#7). Every section below is now on `main`.
- **Smoke.** The packaged VSIX was installed and driven in a real VS Code window by Playwright (`_electron.launch`, fresh profile). 22/22 steps passed:
  1. Labs view, then Workbench, then **Create .datapass project**.
  2. **Setup runtime**: steps 1/3, 2/3 and 3/3, about 3 minutes.
  3. **Start runtime**: the badge shows running.
  4. One exercise per new lab opened and graded, with the starter rejected: spark-lab-v1, airflow-lab-v1, cloud-pipelines-v1, sqlpool-v1, databricks-v1, dwh-v1, dbt-v1.
  5. The SparkLab, Airflow Lab, Cloud Lab and BI Lab tabs rendered.
  6. **Stop runtime**.
- **What it covers.** This replaces the "Not checked in a real F5 session" notes below for these flows, not for every button of each lab.
- **Bug found.** The Cloud Lab sub-tabs and the execution badge overflowed a narrow Workbench. Fixed in PR #17.
- **Stacked PRs.** Retarget the next PR to `main` before merging its base with `--delete-branch`. Otherwise GitHub closes it.

## 2026-09-25 · Vague 1: Practice and Mosaic quick wins

Roadmap artifact: https://claude.ai/artifact/RhQMPGxeuNo9GTFzH5B8aJ (items V1-x; section "Dette technique" D-1…D-10
holds the code-debt audit of 2026-09-25). One PR per item, merged on green CI.

- **V1-3 + V1-4 + D-1** (`feature/exercise-editor-polish`): opening an exercise writes tab labels
  (`workbench.editor.customLabels.patterns`), a per-exercise `__builtins__.pyi` (hidden by `files.exclude`) and the
  generated `content/pylance-stubs` (copied to `.datapass/pylance-stubs`, added to `python.analysis.extraPaths`).
  See EXERCISE_AUTHORING.md → "Editor support". Pyright over all 104 Python starters: 120 warnings before, 0 after;
  in a real VS Code window with Pylance, 0 problems on five exercises while a control file with a missing import
  was flagged. `.vscodeignore` now excludes `.claude/**` and `.venv/**`: from the main checkout, `vsce` would
  otherwise have packaged the parallel sessions' worktrees (185 040 files).
- **V1-5** (`feature/setup-runtime-uv`): Setup runtime uses uv when it answers `uv --version` (PATH, `~/.local/bin`,
  `~/.cargo/bin`): `uv venv --seed` from the absolute path of the configured Python, then `uv pip install` with
  `--refresh-package/--reinstall-package datapass-runtime` (the runtime keeps version 0.1.0 across releases). Any uv
  failure falls back to `python -m venv` + pip. Real VS Code, fresh profile, this Windows machine: Setup runtime
  162 s with pip, 23 s with uv. Harness note: keep the Playwright profile path short; a deep scratch path pushed
  DuckDB's DLL past MAX_PATH ("DLL load failed ... filename or extension is too long").
- **V1-2** (`feature/practice-progress`): Practice progress in the `practice` section of `.datapass/progress.json`
  (Projects' parser now keeps it; `updateProgress()` serializes writes from both modules). Solved = a passed Submit;
  attempted = opened or graded. Toolbar counts, filters by difficulty, topic, language and status (kept in the webview
  state; a Projects focus clears them). Checked in a real VS Code window: submit → solved, starter run → "attempted ·
  1 run", counts 1/1/270, status and language filters, progress.json content.
- **V1-1** (`feature/practice-feedback`): on a failed visible check, expected vs actual rows diffed with the exercise's
  `validation` (`src/platform/practiceFeedback.ts`, the grader's rules incl. bipartite matching and tolerances); hidden
  and edge rows never leave the runtime (host E2E asserts it). Hints one at a time (`hintsRevealed` in progress.json;
  the brief no longer lists them). Reference solution + explanation after a pass or 3 failed gradings (`failures`),
  served by a `datapass-reference:` read-only document provider for **Compare with my solution** (VS Code diff).
  Real VS Code: wrong cross join → 4 matching · 12 missing; hint 1 of 2; locked at 1 failure, unlocked at 3; diff tab.
- **Fix** (`fix/first-catalog-timeout`): the first catalog listing after Start runtime takes ~4 s on Windows (kernel
  start + DuckDB seeding) and hit the 3 s client timeout; now 30 s.
- **V1-6** (`feature/mosaic-data-tools`): Mosaic **Profile** (DuckDB SUMMARIZE, `/api/local/profile`), **Explain
  active SQL** (EXPLAIN ANALYZE of the file or its selection, `/api/local/explain`; **Open in editor** shows it in a
  read-only `datapass-plan:` tab), **Import file…** for CSV (text,
  unchanged), Parquet (file types) and JSON (read_json_auto types) via `/api/local/import-file` (base64 content,
  10 MB / 100,000 rows, new bronze tables only, journaled as `file_import`), and a query history (last 30, workspace
  state). The catalog connection now sets `allowed_directories` to `.datapass/data/imports/` before disabling
  external access; runtime_smoke checks that cell SQL still cannot read files there or anywhere else.

## 2026-09-25 · ZillaCode pack (`zilla-v1`) and the Snowflake SQL dialect

The user asked for the 52 ZillaCode problems (Apache-2.0), which so far lived only in the standalone CodeDELeet app. They
are now a Practice pack built on our engines, with a Snowflake SQL variant. There are two PRs: #19 (the Snowflake
dialect, merged) and the pack PR.

- **Snowflake SQL dialect** (`runtime/snowflakesql`, README there, PR #19). Practice language `snowflake`, labelled
  "Snowflake SQL dialect translated to DuckDB, not Snowflake".
  - sqlglot translates the query (read `snowflake`, write `duckdb`) and it really runs on DuckDB. sqlglot is pinned
    to `>=30.19,<31`.
  - Every function and syntax node is allowlisted; anything else is refused by name.
  - Rewrites keep Snowflake's results where DuckDB differs:
    - `REGEXP_SUBSTR` returns NULL when nothing matches;
    - division by zero raises;
    - `DATEADD`/`DATE_TRUNC` of a DATE stay a DATE (refused when the argument's type is not explicit);
    - unquoted identifiers fold case-insensitively.
  - The generator runs with `unsupported_level=RAISE`, because sqlglot silently dropped `TO_CHAR`'s format on an
    untyped column.
  - `runtime_smoke.py` pins 41 Snowflake results (Snowflake's documented behavior, not DuckDB's) and 24 refusals.
- **Semantic packs** gained two variant languages:
  - `snowflake`;
  - `dbt-sql`: the registry turns each shared fixture into a dbt emulation scenario (the fixture tables are sources of
    a small project, the model is built as a table and graded), and ordered scenarios cannot have one.
  - The dbt grader now keeps a relation's columns when the model builds an empty table (an empty result used to fail
    `exact_schema`).
- **Pack `zilla-v1`**: 52 scenarios, 278 variants.

  | Language | Variants |
  | --- | --- |
  | `sql`, `snowflake`, `python` (pandas), `polars` | 52 each |
  | `dbt-sql` | 45 (the unordered problems) |
  | `sparklab` | 25 (where its bounded API covers the problem) |

  - Generated by `scripts/authoring/gen_zilla.py` from CodeDELeet's normalized `v3-zilla.json` (set `CODEDELEET`;
    specs in `scripts/authoring/zilla/`). The private ZillaCode archive was not used.
  - Contracts are ours:
    - snake_case tables and columns;
    - statement column order;
    - explicit NULL, tie and order rules;
    - where ZillaCode's statement and reference disagreed, the statement wins and the exercise's Source section says
      so (for example 2, 13, 14, 20, 22, 24, 30, 33, 45).
  - Fixtures: ZillaCode's tests 1 and 2 are the visible and hidden fixtures (11's hidden test is authored: its data did
    not fit the column type), plus an authored edge fixture per problem.
  - Every expected row was recomputed from the SQL reference, and the generator compares it with ZillaCode's own
    rows. They match except where the contract changed on purpose. Every row was reviewed by hand.
  - 118 mutants are in `MUTANTS`, written by the generator between markers. Several are language-specific:
    - Snowflake: NULLS FIRST, `REGEXP_SUBSTR` without `COALESCE`;
    - DuckDB: `concat`/`concat_ws` skipping NULLs, `regexp_replace` without `g`;
    - Polars: `nulls_last`, `str.replace`;
    - pandas: NaN keys matching in `merge`.
  - Licensing: `LICENSE` (Apache-2.0) and `NOTICE` (source, checksums, modifications) are in the pack. Each scenario
    carries `provenance` (source, upstream_changes from CodeDELeet's ledger, datapass_changes) and a visible Source
    section.
- **Extension**:
  - solution files `.sql` for `snowflake`;
  - a Snowflake grading note in the exercise brief and a notice on the Practice card;
  - a host step grades zilla-001 in all six languages (the starter fails, the reference passes), the Snowflake NULL
    order trap on zilla-015, and a refusal message.

Checked: `npm run compile`, `npm test` (the scaffold smoke covers the Snowflake brief; the package smoke covers the pack's LICENSE and NOTICE), `pip install ./runtime`, compileall including `runtime/snowflakesql`, `runtime_smoke.py`, `projects_smoke.py`, `exercise_packs_smoke.py` (549 references pass, 549 starters and 514 mutants rejected, zilla-v1 starters must run), `npm run test:host` (26 steps). The VSIX was packaged (1.22 MB) and installed with `code --install-extension --force`. Real VS Code (1.139.1, fresh profile, Playwright `_electron.launch`, the VSIX rebuilt after the rebase on main): Setup runtime, Start runtime, trusted Python confirmed in VS Code's dialog, then zilla-001 opened and submitted in `sql`, `snowflake`, `python`, `polars`, `sparklab` and `dbt-sql`: each starter failed and each reference passed its example, hidden and edge checks (truth `real` or `semantic-emulation` as expected). The screenshots were reviewed: the Snowflake notice shows on its card, and the Python solutions show no Pylance problems. The managed venv could not be created from a very long profile path (Windows path limit during `ensurepip`); from a short path it took about 5 minutes.

Open points:
- CI time: the runtime job grades 674 more submissions (399 s for the whole packs smoke locally).
- The Snowflake subset could grow when a lesson needs it: typed `DATEADD` on fixture columns (with the table schema),
  `ARRAY`/`SPLIT` functions, `REGEXP_SUBSTR` capture groups. Each needs its own semantic check first.
- Descriptions keep ZillaCode's company/scenario names; attribution is in place, and the NOTICE is not a legal review.

## 2026-09-25 · Projects: end-to-end stories across the labs

The user asked for a Workbench module **Projects** that gives meaning to every lab: 2-3 end-to-end projects, each a
story whose steps are done in the existing modules, with checkboxes that follow the learner's progress. PRs #20
(runtime + retail project), #21 (the two other projects) and the Projects UI PR (this section) are on `main`.

- **Runtime**:
  - `runtime/datapass_runtime/run_journal.py`: each lab route records what it really ran in
    `.datapass/data/run_journal.json` (`record_run` in `main.py`, API process only; a journal error never fails a lab);
  - `projects.py`: the `project.json` schema (pydantic, like the packs) and the checks. State checks run in the
    kernel (op `project_state_checks`): tables with columns, types and rows; read-only SQL assertions; SQL pool
    designs (`sqlpool.json`); MLflow models (`databricks_state.json`). Run checks match the journal: exercise passed
    on Submit, Cloud Lab pipeline, SQL pool script (the tab now sends the script path as `source`), Databricks job
    (principal, attempts), BI star model checks, BI lineage (truth "static"), dbt emulation nodes, Airflow simulation
    (schedule, catchup, runs, retries), Pipeline Lab run, SparkLab (columns, simulated plan), Mosaic run, lakehouse
    demo, and a generic `run` check for future labs;
  - `POST /api/local/projects/check {project_id, steps}`: checks come from shipped content only; manual steps come
    back "manual", never verified.
- **Content** (English, like the rest of the Workbench), all doable with today's features:
  - `retail-fabric` (12 steps): CSV import and typed silver SQL in Mosaic, a SparkLab broadcast join, a second Copy
    activity added to the Fabric pipeline (Copy, notebook and stored procedure run locally), an SCD2 star with green
    model checks, dbt build, a daily Airflow schedule with catchup and retries, a Pipeline Lab quality gate, three
    exercises, a manual runbook;
  - `databricks-ml` (10 steps): lakehouse medallion demo, SparkLab exploration, a Databricks job as `sp-feature-eng`
    denied until least-privilege grants are added, MLflow training twice (champion moves to v2), retries, an optional
    trusted-Python Polars check, three exercises, a manual cost review;
  - `synapse-to-fabric` (12 steps): bronze load, SQL pool distributions, partitions and a procedure, the Synapse
    pipeline fixed to keep every segment, a margin column traced by the lineage, star checks, a Fabric Warehouse
    port, three exercises, a manual migration checklist.
- **Extension**: module `projects` (first tab and first Labs item, `datapass.openProjects`):
  - `src/platform/projects.ts` (pure): content normalization, `.datapass/progress.json` (manual ticks, `last`
    verification, `verified` = last one that passed), next suggested step, Markdown subset;
  - `src/projectState.ts`: content, progress file, project files copied without overwriting;
  - `workbenchPanel.ts`: scaffolds, **Open in <lab>** (file or exercise beside, lab tab via `focus`),
    **Verify**, manual ticks;
  - `ProjectsSurface.tsx`: list with a two-segment progress bar (verified / ticked by hand), project page with the
    story, next step, steps with checkbox, state badge ("verified", "ticked by hand", "to redo"), truth badges and
    last result. A verified step stays verified when a later project changes shared tables (the retail demo rewrites
    `silver.orders`); the regression is shown next to it.
- **Docs**: `docs/PROJECT_AUTHORING.md` (schema, checks, truth, walkthrough, how a future lab adds steps), CLAUDE.md,
  QUICKSTART, ARCHITECTURE.

Checked:
- `npm run compile`, `npm test` (new `projects_ui_smoke.mjs`), package boundary (reference answers stay out of the VSIX);
- `pip install ./runtime`, compileall, `runtime_smoke.py`, `exercise_packs_smoke.py` (271 / 271 / 396);
- `projects_smoke.py` (CI runtime job): every automatic check fails in a fresh workspace; the three reference
  walkthroughs run one after another in one workspace through the API; 12 untouched starters leave their step
  unverified; then all 50 automatic checks pass;
- `npm run test:host`: two new steps (starter files never overwrite, a manual tick stays manual; a verification
  through the runtime is kept in `progress.json`, a failing Submit does not verify);
- the packaged VSIX installed with `code --install-extension --force` in a fresh profile and walked in a real VS Code
  1.139 window by Playwright (`_electron.launch`, webview frames through `iframe.webview.ready` / `iframe#active-frame`):
  Projects list, **Create .datapass project**, **Setup runtime** (about 2 min) and **Start runtime**, the retail
  project page; step 1 through **Open in Mosaic** (project files created) and the real **Import CSV…** dialog,
  then **Verify** (verified); step 3 checked on the starter (to redo), then the SQL written and **Run active SQL**
  (verified); the runbook ticked by hand (never verified in `progress.json`); **Open in
  Practice** (exercise opened, list filtered), **Open in Cloud Lab** (Pipelines tab), **Open in BI Lab** (dbt
  tab); the page and the list at a narrow width. Screenshots reviewed.
- Bugs the walk found and fixed: a slow refresh (the Practice catalog) could land after a newer one and switch the
  Workbench back to Practice (refreshes now post only the newest state); a lab opened from a step kept the Projects
  page's scroll position (it now starts at the top). Walk tip: keep the test profile on a short path
  (`%TEMP%\dpw-walk`); from the long scratchpad path the webview's `dist/webview.js` failed to load
  (`net::ERR_FAILED`) and the Workbench stayed blank.

Open points for the user:
- The Projects module was first written in French (the request quoted French labels); the user then asked for
  English everywhere: the UI, the three projects, their starter files and the runtime's check messages are English.
- Next: steps for the future labs (dbt Core + dbt Charts, Terminal Lab, simulated Infra Lab) through `record_run`
  and the generic `run` check.

## 2026-09-25 · BI-2: dbt in the BI Lab (Datapass dbt emulation)

Branch `feature/bi-dbt`, stacked on `feature/bi-lab` ("2026-09-25 · BI Lab: data warehousing, SQL lineage and star models"). The user asked to continue with BI-2 (dbt in the BI
Lab). dbt runs without dbt Core, with an emulation that is checked against dbt Core.

- **Runtime** `runtime/dbtlab` (README there; new dependencies `jinja2`, `pyyaml`):
  - project Jinja is rendered in jinja2's `SandboxedEnvironment` with a dbt context (ref, source, config, var,
    this, is_incremental, target, macros, return); packages, env_var, run_query and adapter calls are refused;
    nothing is executed as Python;
  - dbt's parse (is_incremental() false), including its refusal of a ref only reached in incremental runs (the
    `-- depends_on:` hint fixes it, as in dbt);
  - dbt-duckdb materializations (view, table, incremental with delete+insert (default), append or merge, ephemeral
    CTEs), seeds with agate-like types, snapshots (timestamp, check, hard deletes, dbt_valid_to_current, dbt's
    dbt_scd_id), generic tests with dbt's SQL and names (classic and 1.10 `arguments:` forms, severity, where),
    singular tests, selection (+, tag:, path:, resource_type:, source:, exclude, eager tests) and dbt build's gating;
  - `lab.py` (route `POST /api/local/bi/dbt`, kernel op `bi_dbt`) returns nodes, results (compiled SQL, failing
    rows) and the column lineage of the compiled models (through `bilab.lineage`, which now unwraps `AS ( ... )`).
- **Checked against dbt Core 1.12.5 + dbt-duckdb 1.11.0**: `scripts/dbt_oracle_smoke.py` runs four projects step by
  step (materializations, snapshots, tests and build gating, and the BI sample with a correction and a full refresh)
  through real dbt Core and the emulation and compares every node status and every table (columns, types, rows).
  It passes; the check-strategy timestamps come from the clock and are skipped. It needs `DATAPASS_DBT_PYTHON` and is
  not in CI (CI does not install dbt Core).
- **Sample** `samples/bi-lab/dbt/` (copied to `bi/dbt/`): the BI warehouse the dbt way (sources with tests, staging
  views in silver, an ephemeral intermediate, marts in the warehouse layer with an incremental fact on a composite
  key, a check snapshot of product prices, tests, a singular test, generate_schema_name and date_key macros), plus a
  README on running it with dbt Core.
- **Practice pack `dbt-v1`** (12 exercises, 21 mutants, `scripts/authoring/gen_dbt.py`): languages `dbt-sql` and
  `dbt-yml`, runtime `datapass-dbt-emulation-v1`, truth `semantic-emulation`, graded in
  `datapass_runtime/dbt_project_grading.py` on an isolated catalog. Every reference fixture was also run through dbt
  Core by the generator and matched. The smoke gained `BUILD_ERRORS_ARE_ANSWERS`: in this pack a node that fails to
  build is a legitimate wrong answer (the dbt error is the lesson).
- **Extension**: BI Lab tab **dbt** (command, selection, --full-refresh, Run / Parse only; status counts; DAG from
  sources to marts colored by status, tests optional; results; node details with compiled SQL, failing rows,
  column lineage and Open file). `src/biState.ts` sends every project file of `bi/dbt` (not target/, logs/,
  profiles.yml, packages.yml).

Checked: `npm run compile`, `npm test` (bi_lab_smoke covers the dbt mapping), `pip install ./runtime`, compileall
with `runtime/dbtlab`, `runtime_smoke.py` (sample parse and build, conditional ref, sandbox, packages, schemas,
route), `exercise_packs_smoke.py` (259 references, 259 starters, 380 mutants), `npm run test:host` (24 steps), the
dbt oracle smoke, and the dbt tab in a browser harness with a real response. Not checked in a real F5 session.

Open points for the user:
- The older **dbt Lab** module (`dbt`, sample `dbt/retail-dbt`, real dbt Core in a terminal) now overlaps with the
  BI Lab dbt tab. Options: keep it as "run with dbt Core", or fold it into the BI Lab.
- Real dbt Core and the running runtime cannot write the same DuckDB file at once (DuckDB's single-writer lock): the
  dbt Lab's terminal run needs the runtime stopped. The sample README says so.
- Next: BI-3 (KPIs, a DAX-like measure layer translated to SQL, charts, the dbt Charts board preview), then the
  Cloud lab's dbt layer (Databricks dbt_task, Fabric dbt job activity), which can now run on this emulation.

## 2026-09-25 · BI Lab: data warehousing, SQL lineage and star models

Branch `feature/bi-lab`, stacked on `content/databricks-v1` ("2026-09-25 · Cloud Lab Databricks (jobs, compute, Unity Catalog, MLflow)"). A new Workbench module **BI Lab** (id `bi`), the
pipeline-free lab the user asked for, focused on data warehousing notions (the user asked explicitly for SQL
lineage, star-schema modeling and slowly changing dimensions types 1, 2 and 3). Nothing connects to Power BI.

- **Runtime** (`runtime/bilab`, README there; new dependency `sqlglot` in `runtime/pyproject.toml`):
  - `script.py`: warehouse scripts split into statements with line numbers (comments skipped on the original text),
    each run through the catalog's SQL contract on DuckDB; a script stops at its first error.
  - `lineage.py`: static column lineage with sqlglot (DuckDB dialect), qualified against the catalog's columns.
    CREATE TABLE/VIEW AS, INSERT ... SELECT (positional or BY NAME), UPDATE ... FROM and MERGE (via synthetic
    queries) write columns; CTEs, derived tables, scalar subqueries, UNION branches (by position) and windows are
    resolved by our own resolver over sqlglot scopes. Transform per column (copy, rename, expression, aggregate,
    window, constant, generated); `origins` follow tables the scripts build back to unbuilt tables; WHERE/JOIN/GROUP
    BY/HAVING/QUALIFY and MERGE conditions are row influence; `impact()` follows values and rows.
  - `model.py`: the star model file (`bi/model.json`, Datapass's own format with Power BI's relationship vocabulary:
    cardinality, cross-filter single/both, active) and its checks as real queries: keys, unknown member, grain, SCD2
    validity (range, one current, current flag, no overlap, no gap), relationship columns, 'one' side unique, NULL
    keys, orphans, fact-to-dimension, one active path, cross-filter (both only with a bridge), many-to-many.
  - `lab.py` + route `POST /api/local/bi/lab` (kernel op `bi_lab`, capability `bi_lab`, DuckDB only): run or only
    analyze the scripts, return statements, tables, lineage (with impact for every column), model and profiles.
- **Practice pack `dwh-v1`** (20 exercises, 47 mutants; `scripts/authoring/gen_dwh.py`): languages `warehouse`
  (solution.sql) and `bi-model` (solution.json), runtime `datapass-warehouse-v1`, truth `real`, graded in
  `datapass_runtime/warehouse_grading.py` on an isolated catalog per check. Scenarios seed tables, run the script
  1-3 times with per-run batches (incremental loads, rerun safety), and grade result, table, checks, relationships,
  lineage (origins) or impact. Lessons: snowflake flattening, surrogate keys + unknown member, date dimension with a
  July fiscal year, junk dimension, SCD 1, SCD 2 (NULL-safe change detection, rerun-safe), a type 1 attribute in a
  type 2 dimension, SCD 3, point-in-time join (exclusive valid_to), late arriving dimension (inferred members),
  allocating an order-level fee to the line grain, periodic snapshot (dense, semi-additive), accumulating snapshot
  (MERGE with COALESCE), factless fact (anti-join on coverage), drill across conformed dimensions (fan trap), weighted
  bridge, lineage of certified revenue (a COALESCE fallback to the header shows in lineage), lineage of personal
  data, star models with a role-playing date and with a bridge. Every expected row was reviewed by hand.
- **Extension**: module `bi` (`datapass.openBiLab`), `src/biState.ts` (bi/ files; open editors win),
  `src/platform/biRun.ts` (pure mapping, star layout, lineage graphs; `scripts/bi_lab_smoke.mjs`),
  `BiSurface.tsx` with tabs Warehouse (scripts, statements with Show-in-script, tables), Star model (star drawn fact
  in the middle; edges leave by the side facing their dimension; dashed inactive, purple both; checks and relationship
  profiles), Lineage (column table, multi-hop column graph, impact, row influence, table graph) and Concepts (SCD
  types, fact types, keys, dimension patterns, additivity, lineage; each item opens its exercise). Samples in
  `samples/bi-lab/` are copied to `bi/` by **Create lab files**. `SharedGraphCanvas` gained optional node positions
  and four-side handles (`allSides`, `sourceSide`/`targetSide`); other graphs are unchanged.

Checked:
- `npm run compile`, `npm test` (new `bi_lab_smoke.mjs`; package boundary includes `runtime/bilab`, the pack and
  the samples);
- `pip install ./runtime` (bilab and its README packaged), compileall with `runtime/bilab`;
- `runtime_smoke.py`: statement lines, contract refusal, the sample build through `lab_view` (16 sales rows, lineage
  transforms, origins, impact through the point-in-time join, all 77 model checks pass, a broken model fails the
  right checks), DML lineage, the API route and its validation;
- `exercise_packs_smoke.py`: 247 references pass, 247 starters and 359 mutants rejected;
- `npm run test:host` (23 steps): the sample warehouse built through the runtime, a broken model analyzed without
  running, and dwh-v1 references, starters, a lineage-only failure and invalid JSON graded; workspace catalog unchanged;
- the four tabs rendered in a browser harness with a real runtime response (star layout fixed after the first look).
  Not checked in a real F5 session.

Decided with the user in this session (2026-09-25), not built yet:
- **dbt Charts** exists in the dbt sample (`dbt_charts.yml`, `charts/revenue.yml`) but nothing renders it. dbt Charts
  is a real Apache-2.0 tool from dbt Labs (CLI `dct`, DuckDB built in, offline). Plan: same rule as dbt Core, real
  `dct validate`/render when installed, otherwise a Datapass preview labelled "not the dbt Charts renderer"; no
  vendor VS Code extension.
- **Next BI tranches**: BI-2 dbt in the BI lab (snapshots = real SCD2, tests incl. relationships, incremental models,
  lineage of dbt models with ref()/source() resolved, dbt Charts preview); BI-3 KPIs and a small DAX-like measure
  layer translated to SQL on the star (SUM, DIVIDE, CALCULATE, ALL, YTD / previous year, USERELATIONSHIP for the
  inactive ship date), with charts.
- **dbt layer in the Cloud lab** must follow real practice: Databricks `dbt_task` in a job (dbt Core on small job
  compute, SQL on a SQL warehouse, run_as needs CAN USE + Unity Catalog privileges, pinned dbt-databricks,
  parameters and task values in commands; 2-3 exercises tied to the ML flow, a failing dbt test blocks training);
  Fabric dbt job item + pipeline "dbt job" activity (preview; documented settings operation, select, exclude,
  fullRefresh, failFast, threads, selectorName; the activity's JSON `type` string is NOT documented, so verify it
  before writing any exercise; 3-4 exercises incl. the same load with and without dbt). ADF/Synapse have no dbt
  activity: dbt runs from CI/CD or Airflow there. Execution stays real dbt Core + dbt-duckdb when installed (say the
  adapter is dbt-duckdb), else the step fails explicitly.

## 2026-09-25 · Cloud Lab Databricks (jobs, compute, Unity Catalog, MLflow)

Branch `feature/databricks-lab`, stacked on `feature/sqlpool-lab` ("2026-09-25 · Cloud Lab SQL pool (Synapse dedicated SQL pool, Fabric Warehouse)"). A **Databricks** tab in Cloud Lab: a simulated
Azure Databricks workspace. Facts checked on Microsoft Learn (run_if options and outcomes, the leaf rule, If/else
comparisons, task values, dynamic value references, job-parameter precedence, Unity Catalog privileges, models in UC).

- **Runtime** (`runtime/databrickslab`, README there):
  - Jobs API JSON validated (task types, dependencies, cycles, condition outcomes, compute references, parameters) and
    simulated on a logical clock: `run_if` (all six), Excluded / Upstream failed, retries, `timeout_seconds`, If/else
    (`==`/`!=` as text, others numeric), for each with concurrency, job parameters pushed down as widgets (they win over
    task parameters), dynamic value references, task values, the leaf rule (Succeeded / Succeeded with failures / Failed).
  - Compute modelled: job clusters, all-purpose clusters (`compute.json`, idle until auto-termination), serverless, SQL
    warehouses; start times, DBU and lab cost units (order real, amounts illustrative).
  - Unity Catalog: `main` catalog, layers as schemas plus `ml`; owners, `grants.sql` (GRANT/REVOKE/ALTER OWNER),
    groups; every read/write of a `run_as` principal is checked (USE CATALOG default for all users, USE SCHEMA, SELECT,
    MODIFY+SELECT, CREATE TABLE, CREATE MODEL, EXECUTE, ownership).
  - MLflow: tracking (experiments, runs, params, metrics, logged models) and a UC registry (three-level names,
    signature required, versions, aliases), persisted in `databricks_state.json`.
- **SparkLab** (still no eval/exec): `sparklab/ml.py` (VectorAssembler, LinearRegression by least squares,
  LogisticRegression by Newton's method, Pipeline, evaluators, `randomSplit` by md5), `sparklab/mlflow_api.py`,
  `dbutils.jobs.taskValues`, `collect()`/`first()`/Rows, `with mlflow.start_run() as run:`, tuple unpacking and dicts
  in notebook mode. `CatalogNotebookRuntime.fetch` reads rows for them.
- **Fix**: `catalog.statements` kept a trailing `\r` from Windows line endings as an empty statement; now stripped.
- **Extension**: Cloud Lab tabs Pipelines, SQL pool, **Databricks**, Lakehouse. The Databricks tab has Jobs (canvas,
  run settings, result, compute and cost), Catalog, Experiments and models, Compute. Files under `factory/databricks/`
  (`jobs/*.json`, notebooks, `.sql`, `compute.json`, `unity_catalog.json`, `grants.sql`); samples copied by **Create lab
  files**. Mapping in `src/platform/databricksRun.ts`.
- **Practice pack `databricks-v1`** (branch `content/databricks-v1`, stacked on this one): 13 exercises, 28 mutants.
  New languages `databricks-job` (solution.json), `databricks-notebook` (solution.py), `databricks-grants`
  (solution.sql); runtime `datapass-databricks-sim-v1`, grading in `datapass_runtime/databricks_grading.py` on an
  isolated catalog per check, scenario model and outcomes in `databrickslab/exercise.py` (task runs, run, task values,
  compute, table, models, MLflow runs, Unity Catalog access probes). Deprecated references such as `{{start_date}}`
  now resolve, as Databricks still accepts them. Generated by `scripts/authoring/gen_databricks.py`; expected rows reviewed by hand.
- **Not done yet**: dbt tasks (the optional dbt layer), Lakeflow pipelines, Run Job tasks, repair runs;
  pandas/scikit-learn in notebooks.

Checked:
- `npm run compile`, `npm test` (new `databricks_lab_smoke.mjs`);
- `pip install ./runtime`, compileall (with `runtime/databrickslab`);
- `runtime_smoke.py`: run_if and leaf-rule tables, retries, timeouts, If/else comparisons, parameters and references,
  for each, cluster billing, invalid jobs, the three sample jobs on a catalog (task values, SQL output, UC denial,
  MLflow versions and aliases, ownership), notebook sandbox rejections, the API routes;
- `exercise_packs_smoke.py`: 227 references pass, 227 starters and 312 mutants rejected (with the pack);
- `npm run test:host` (22 steps): the sample jobs through the runtime, as their principals;
- the tab rendered in a browser harness with a real runtime response. Not checked in a real F5 session.

## 2026-09-25 · Cloud Lab SQL pool (Synapse dedicated SQL pool, Fabric Warehouse)

Branch `feature/sqlpool-lab`, stacked on `content/cloud-pipelines-v1` ("2026-09-25 · Cloud Lab pipeline exercises"). A **SQL pool** tab in Cloud Lab and the `sqlpool-v1` Practice pack.

- **Runtime** (`runtime/sqlpoollab`, README there):
  - T-SQL scripts are split (`;`, `GO`) and translated to DuckDB for a documented subset: brackets, `N''`, variables, `dbo` → the `warehouse` layer, `ISNULL`, `LEN`, `COUNT_BIG`, `IIF`, `EOMONTH`, the `GETDATE` family (fixed lab clock), `CAST`/`CONVERT` types, `DATEADD`/`DATEDIFF`/`DATEPART` (string dates included), `CHARINDEX`, `TOP` (subqueries included). `+` string concatenation is not translated (use `CONCAT`).
  - Statements: CREATE TABLE (options, IDENTITY, NOT ENFORCED keys), CTAS, INSERT/UPDATE/DELETE/MERGE, SELECT/EXPLAIN, views, DROP, `IF OBJECT_ID ... DROP TABLE`, TRUNCATE, RENAME OBJECT, partition SWITCH (TRUNCATE_TARGET) / SPLIT / MERGE, indexes, statistics, procedures (CREATE [OR ALTER], EXEC with named/positional arguments, nesting), DECLARE/SET/PRINT. A script stops at its first error.
  - Two flavors with their rules: Synapse (ROUND_ROBIN + CCI default, CTAS needs DISTRIBUTION, no SELECT INTO, no FK, SPLIT needs an empty CCI partition...) and Fabric Warehouse (no DISTRIBUTION/index/PARTITION, CLUSTER BY, refused types with their mapping, FK NOT ENFORCED, no RENAME OBJECT).
  - Physical model: 60 distributions (repeated keys ≥1% placed by a stable hash, NULLs on one distribution, singletons spread evenly), partitions and columnstore rowgroups at scale (1 M rows per distribution and partition). Planner: replicated joins and aligned HASH joins (same type) are local; else broadcast (≤1/100) or shuffle; GROUP BY shuffles unless on the distribution column; partition elimination on bare-column predicates.
  - Data statements go through the catalog's SQL validation; designs persist in `.datapass/data/sqlpool.json`. Route `POST /api/local/sqlpool/run`, kernel op `sqlpool_run`, capability `sqlpool_lab`.
- **Extension**: Cloud Lab tabs are now Pipelines, **SQL pool**, Lakehouse and notebooks. The tab runs scripts of `factory/sql/pool/` (samples copied by **Create lab files**, `-- flavor:` comment picks the product) or the active `.sql`, with a scale selector. It shows the statements (click a line to reveal it), each plan's data movement and partition scans, the translated SQL, the rows, and per table the design, a 60-bar distribution chart with skew, partitions and rowgroup health; plus a movement legend and a Synapse vs Fabric Warehouse table. Mapping in `src/platform/sqlpoolRun.ts`.
- **Pack `sqlpool-v1`**: 12 exercises, 25 mutants: replicated dimension, co-located facts (CTAS + RENAME, same type), skew-free key, staging heap, RANGE LEFT/RIGHT, partition elimination, partition size for columnstore, CTAS upsert, partition switch load, NOT ENFORCED key dedup, rerun-safe procedure, Fabric port (its starter is refused by design: `STARTERS_REFUSED_BY_DESIGN`). Generated by `scripts/authoring/gen_sqlpool.py` from the references; expected rows reviewed by hand.
- **Not done yet**:
  - Synapse pipelines' `SqlPoolStoredProcedure` activity still calls `factory/sql/procedures` (DuckDB SQL), not the pool's T-SQL procedures;
  - serverless SQL pool (OPENROWSET over files), workload management, materialized views, result-set caching;
  - the tab shows a table designed with the other flavor as it was created (one catalog for both flavors).

Checked:
- `npm run compile` and `npm test` (new `sqlpool_lab_smoke.mjs`);
- `pip install ./runtime` and compileall (now with `runtime/sqlpoollab`);
- `runtime_smoke.py`: CTAS placement, replicated/aligned/type-mismatched joins, partition elimination, skew, procedures, T-SQL idioms, SWITCH, platform refusals, catalog validation, the API route;
- `exercise_packs_smoke.py`: 214 references pass, 214 starters and 284 mutants rejected;
- `npm run test:host` (18 steps): the four sample scripts on the runtime, the pack's reference and starters, and the workspace catalog unchanged by grading;
- the tab rendered in a browser harness with a real runtime response. Not checked in a real F5 session.

## 2026-09-25 · Cloud Lab pipeline exercises

Branch `content/cloud-pipelines-v1`, stacked on `feature/factory-lab` ("2026-09-25 · Cloud Lab pipelines (Factory Lab)"). Guided Practice exercises on the Cloud Lab pipeline simulator.

- **Grading** (`datapass_runtime/factory_grading.py`, scenario model `factorylab/exercise.py`):
  - New Practice languages: `factory` (the learner writes the pipeline JSON, `solution.json`) and `factory-notebook` (the learner writes the notebook a given pipeline runs, `solution.py`).
  - Runtime `datapass-factory-sim-v1`, truth `simulated`.
  - A fixture scenario sets the product flavor, the run settings (parameters, trigger time, per-activity behavior) and the lab files.
  - With `data_plane: local`, the scenario also names tables seeded into an isolated DuckDB catalog in a temporary folder. The workspace catalog is never touched; the host E2E checks this.
  - `runs` repeats the pipeline, so rerun-safety can be graded.
  - Outcomes: activity runs, run status, variables, resolved inputs/outputs, or a table. An invalid pipeline fails the check with "Pipeline rejected: ...".
  - The registry validates scenarios per language, and the runtime must match the language.
- **Engine additions**:
  - scenario output sequences (`outputs`: one per run of an activity) for polling loops;
  - Data Factory's rule that a Set variable cannot reference the variable it sets. The smoke's Until test now counts through a second variable, as real pipelines must.
- **Pack `cloud-pipelines-v1`**: 16 exercises (4 easy, 8 medium, 4 hard), 39 mutants, 3 to 4 fixtures each.
  - Orchestration:
    - an email only on failure (the run then ends Succeeded: try/catch);
    - a cleanup that always runs (Completed + Skipped);
    - retries and a timeout;
    - ForEach batchCount from a parameter;
    - If on a Lookup (Boolean needed);
    - the notebook exit value in Fabric (`output.result.exitValue`, text vs number);
    - .NET date formats (`MM` vs `mm`);
    - an Until polling loop with an If inside;
    - the leaf rule, handling a failed copy while a Transform failure still fails the run;
    - porting an ADF pipeline to Fabric (TridentNotebook parameters, exit value, Teams).
  - Local data:
    - a watermark incremental load (two runs, strict `>`);
    - a rerun-safe upsert that keeps rows missing from the source;
    - a Synapse SQL pool procedure with typed parameters.
  - Notebooks in pipelines:
    - the Fabric parameters cell;
    - Databricks widgets and save modes (the second daily run fails with errorifexists).
  - `scripts/authoring/gen_cloud_pipelines.py` produced the pack: expected rows come from the references, and it checks that starters and mutants run and fail. I reviewed every expected row by hand. The pack is in `RUNNABLE_STARTER_PACKS`.
- **Extension**:
  - `factory` exercises open `solution.json` and `factory-notebook` exercises open `solution.py`.
  - The brief explains the simulated grading.
  - The Cloud Lab Pipelines tab has a **Pipeline exercises** button.
- **Not done yet**:
  - exercises with the optional dbt layer: the Fabric dbt activity JSON is still unverified, so nothing is invented;
  - a Synapse notebook exercise;
  - a Switch exercise.

Checked:
- `npm run compile` and `npm test`;
- `pip install ./runtime` and compileall;
- `runtime_smoke.py` (output sequences, the self-reference rule);
- `exercise_packs_smoke.py`: 202 references pass, 202 starters and 259 mutants rejected;
- `npm run test:host`: the watermark reference passes, its starter fails, invalid JSON is rejected, the notebook reference passes and its starter fails, and the workspace catalog is unchanged.

## 2026-09-25 · Cloud Lab pipelines (Factory Lab)

Branch `feature/factory-lab`, stacked on `feature/airflow-lab-surface`. "Fabric Lab" becomes **Cloud Lab** (module id `fabric` and command id unchanged). It is the first piece of the simulated cloud platform the user asked for. Nothing connects to Fabric, Azure or Databricks, and the real Fabric VS Code extension is not used.

- **Engine** `runtime/factorylab` (new package, shipped with the runtime; see its README):
  - `loader.py` reads real pipeline JSON (Fabric `pipeline-content.json`, ADF / Synapse `pipeline/<name>.json`) for three flavors and validates it with Data Factory's design-time rules. An activity used in the wrong product names the equivalent: TridentNotebook in ADF → DatabricksNotebook.
  - `expressions.py` is a bounded parser and evaluator for the expression language: `@`, `@{}`, `@@`, `?.`, pipeline() system variables as documented for each product, variables(), activity(), item(), and string, collection, logic, conversion, math and date functions.
  - `engine.py` simulates the orchestration: conditions and AND/OR, skip propagation, the leaf rule (try/catch succeeds, do-if-else fails), retries and timeouts, Inactive activities, ForEach (batchCount), If, Switch, Until, Filter, variables and return value, Execute/Invoke pipeline. It adds a readable note for each activity run.
  - `work.py` runs Copy (overwrite, append BY NAME, ADF upsert with MERGE, preCopyScript), Lookup, Script and stored procedures (`@params` checked like SQL Server, typed Int32/Decimal/Boolean values) on the local catalog. It runs notebooks too. A missing procedure or notebook fails the activity.
- **Runtime**:
  - `datapass_runtime/factory_workspace.py` adapts the catalog. It runs SparkLab notebooks in *pipeline notebook* mode (`sparklab/notebook_utils.py`, `SafeSparkParser.run_notebook`).
  - Kernel op `factory_simulate` and `POST /api/local/factory/simulate` take the flavor, the pipeline, the lab files and the scenario, with size limits. `data_plane` is `local` (really run) or `simulated` (dry run). The response adds `tables_changed`.
  - `catalog.validate_sql` now allows MERGE.
- **SparkLab pipeline notebook mode** (ordinary SparkLab cells are unchanged; the smoke checks that they still reject these):
  - Fabric `# PARAMETERS CELL` injection. Without the cell, values are injected at the top and later assignments overwrite them; the run reports it.
  - `dbutils.widgets` (`InputWidgetNotDefined`).
  - `df.write.mode(...).saveAsTable()` with Spark's default errorifexists.
  - `spark.sql` (queries become DataFrames, statements run), `spark.read.table`, `df.count()`, f-strings, text arithmetic.
  - `notebookutils` / `mssparkutils` / `dbutils` `.notebook.exit`, `display`, `print`.
  - 3-part names (`lakehouse.schema.table`, Unity Catalog) drop the first part.
  - Side effects run on the catalog as the statements are reached. Still no eval/exec.
- **Samples** `samples/factory-lab/` (copied to the learner's `factory/`) hold the same daily retail load in the three git layouts:
  - Fabric: Copy → Notebook → stored procedure → Lookup → If → Teams, plus an Outlook alert on notebook failure;
  - ADF: upsert Copy → Databricks notebook → procedure → Web, with datasets and linked services that hold no secrets and point at `.invalid` hosts;
  - Synapse: Script CTAS → SQL pool stored procedure → Lookup.
- **Extension**:
  - `src/factoryState.ts` reads `factory/` and sends the referenced files with each run; `src/platform/factoryRun.ts` holds the pure mapping (tested by `scripts/factory_lab_smoke.mjs`).
  - The **Pipelines** tab (`FactoryPipelines.tsx`) has:
    - a product switch and a pipeline picker;
    - a canvas with condition-colored edges, drill-down into containers and activity details (input, output, error, **Show in JSON**);
    - run settings: parameters, trigger, and per-activity failures, durations and outputs;
    - **Run on local lakehouse** and **Dry run**;
    - the run status explained by the leaf rule, activity runs, child runs, variables and tables written;
    - a Fabric vs ADF vs Synapse differences table.
  - The old content lives in the **Lakehouse and notebooks** tab. `SharedGraphCanvas` gained `onNodeClick` and edge `className`.
- **Checked against Microsoft Learn**: Fabric pipeline system variables (`DataFactory` = workspace name, `Pipeline` = pipeline name), and the notebook exit value path (`output.result.exitValue`). Everything else relies on product knowledge, not a live service: activity type names such as `TridentNotebook`, `InvokePipeline`, `Teams` and `Office365Outlook`, and the shape of the Teams and Outlook activities, which is abbreviated.
- **Next** (roadmap agreed with the user):
  - The Cloud lab holds pipelines, notebooks, Synapse-style SQL (procedures, CTAS, indexes, partitioning, distributions) and Databricks. Light optional layers (dbt, Airflow, modeling) appear only in some exercises.
  - A separate BI lab holds SQL, dbt, gold tables, KPI and a little DAX, with no pipelines.
  - Next tranche: guided pipeline exercises, including an ADF → Fabric port. Then SQL pool / warehouse, Databricks (clusters, jobs, Unity Catalog, ML), and the BI lab.
  - The overlap between the older Pipeline Lab DSL and the Factory Lab is still to decide with the user.

Checked:
- `npm run compile`;
- `npm test` (new `factory_lab_smoke.mjs`; `package_smoke.mjs` requires the new files);
- `pip install ./runtime` and compileall (now with `runtime/factorylab`);
- `runtime_smoke.py`: engine semantics, pipeline notebooks, the three samples through the API with the kernel worker, dry run, wrong-product validation and size limits;
- `exercise_packs_smoke.py`: 186 references pass, 186 starters and 220 mutants rejected, so SparkLab's existing packs are unchanged;
- `npm run test:host`: 20/20 steps, including the two new ones;
- the Pipelines tab in a browser harness, with the built webview and a real run result: canvas colors, activity details, drill-down into If, product switch, narrow width. It found one bug: a run that succeeded after retries kept the failed attempt's error. That is fixed and covered by the smoke.

Not re-checked in a real F5 session.

## 2026-09-25 · Airflow lab simulator and exercise pack

Branch `content/airflow-lab-v1`. Airflow practice without Airflow, in the local runtime (no FastAPI Cloud, no separate service; `datapass-airflow-runner` stays empty).

- **Simulator** `runtime/airflowlab` (new package, shipped in the VSIX with the runtime): `parser.py` reads a real-looking Airflow DAG file through a whitelisted AST walk and never executes it (classic operators, sensors, TaskFlow `@task`/`@dag`, `>>`/lists/`chain`, `default_args`, timetables); unsupported syntax is rejected with a line number, including Airflow 2 arguments removed in Airflow 3. `schedule.py` creates runs with Airflow 3 timetables (CronTriggerTimetable by default, CronDataIntervalTimetable on request, catchup default False). `simulate.py` simulates task instances (Airflow's TriggerRuleDep rules, retries, execution_timeout, sensor poke/timeout/soft_fail, branch and short-circuit skipping, leaf-based run state). `templates.py` renders `{{ ds }}`-style fields without Jinja or eval. See its README for exactly what is and is not modeled.
- **Grading**: new exercise language `airflow`, runtime `datapass-airflow-sim-v1`, truth `simulated` (`datapass_runtime/airflow_grading.py`). Fixtures carry a `scenario` (scheduler clock, task behavior, outcome table) instead of input rows; the registry validates it. See `docs/EXERCISE_AUTHORING.md`.
- **Pack** `airflow-lab-v1` (13 exercises: 6 easy / 5 medium / 2 hard): fan-in/fan-out, TaskFlow data dependencies, catchup, no accidental backfill, weekday cron, data-interval timetable, `ds_add` under the Airflow 3 `@daily` default, retries, all_done cleanup, one_failed watcher, branch join, soft-fail sensor, `default_args` override. Expected rows computed by simulating the references, reviewed by hand; 32 mutants.
- **Extension**: `airflow` solutions open as `.py`; the brief says the file is parsed, never executed.
- **Airflow Lab panel on the same simulator** (branch `feature/airflow-lab-surface`, stacked on this one): `POST /api/local/airflow/simulate` (`airflowlab/lab.py`) takes the DAG file's TEXT and a scenario and returns the parsed DAG, runs (latest 40 simulated), task instances, timed events and rendered templates; parse errors carry a line, and a simulation error (e.g. a branch without a known choice) still returns the DAG. The panel simulates the active DAG `.py` (or `airflow/dags/retail_daily.py`, the new Python starter): scenario form (scheduler clock, unpause time, manual run, per-task outcome, duration, sensor arrival, branch choice), an Airflow-style grid of task states per run, the graph with state colors, Start/Step/End replay over the events, the task table, the log and rendered templates, and **Go to line** for parser errors. In the Lab, a sensor without a scenario setting sees its file on the first poke (grading keeps "never"). The webview simulator, the JSON spec validator and `main.dag.json` starter were removed; an existing `main.dag.json` only triggers a notice. Scenarios gained `manual_runs` (logical date = trigger time; CronDataIntervalTimetable infers the last complete interval) and events carry `state`/`try_number`. `SharedGraphCanvas` now lays out graphs left to right by dependency depth (Pipeline and dbt too; dragged positions still win) and colors nodes by an optional `status`.
- **Semantics checked against Airflow's code paths from memory, not against a live Airflow**: CronTriggerTimetable vs CronDataIntervalTimetable run creation, `_skip_to_latest`, TriggerRuleDep, sensor timeout after a false poke, `try_number <= retries`. A real-Airflow oracle (like the Spark one in `fastapispark` PR #1) would be the way to verify them.

Checked: `npm run compile`; `npm test` (airflow brief, package boundary); `pip install ./runtime`; compileall; `runtime_smoke.py` (parser rejections, both timetables, catchup, a trigger-rule table, retries, sensor timeout, templates); `exercise_packs_smoke.py` → 186 references pass, 186 starters and 220 mutants rejected; `npm run test:host` (branch-join reference passes, starter fails, `import os` rejected). Not re-checked in a real F5 session.

## 2026-09-25 · Spark lab pack and simulated plan checks

Merged as PR #7 (`58baba9`). Branch `content/spark-lab-v1`. Targeted Spark practice on the existing bounded SparkLab (no new engine, nothing distributed).

- **Exchange model** (`runtime/sparklab/physical.py`, `plan-driven-v2`): shuffle exchanges now follow Spark's planning rules (satisfied clustering reuses an existing hash partitioning, broadcast joins keep the streamed side's partitioning, broadcasts above 8 GB are refused, EliminateSorts under joins and MIN/MAX/COUNT aggregates). Before, every wide operator counted a shuffle, so two windows on the same key or a join on an aggregated key were overcounted. `metrics.plan_facts` exposes exchanges with reasons; the SparkLab panel shows the count. Also fixed: a join whose right DataFrame contained a window was misread as a window (`.sql` of the DataFrame was scanned).
- **Plan checks**: an exercise may declare `spark_plan` (profile, AQE, authored `scale` per table, rules `max_exchanges`, `min_broadcast_joins`, `max_shuffle_joins`, `max_global_windows`, `max_output_partitions`). `exercises.grade` passes the scale to the simulation, grades the checks once on the first successful run and returns them as `kind: "plan"` checks (visible, on Run visible and Submit). The registry rejects plan checks on non-SparkLab exercises, unknown tables or profiles, and ids that clash with fixtures. See `docs/EXERCISE_AUTHORING.md`.
- **Pack** `spark-lab-v1` (12 exercises, 4 easy / 5 medium / 3 hard): 7 result lessons (left-join filter placement, semi join, `count(col)`, `eqNullSafe`, full outer reconcile, join fan-out, RANGE vs ROWS ties) and 5 plan lessons (`coalesce` vs `repartition`, one-pass aggregation, broadcast above the threshold, random repartition before a window, window instead of self-join). The starters are the buggy code; plan-lesson starters return the right rows and fail only the plan (`PLAN_ONLY_STARTERS` in the pack gate enforces this). Expected rows computed by running the references, reviewed by hand.
- **Extension**: Practice cards list the plan requirements; plan results are labeled "simulated plan"; the exercise brief shows the authored sizes and checks.

Checked: `npm run compile`; `npm test` (brief and SparkLab view assertions); `pip install ./runtime`; compileall; `runtime_smoke.py` (new exchange-model assertions); `exercise_packs_smoke.py` → 185 references pass, 185 starters and 204 mutants rejected; `npm run test:host` (Spark lab grading step: broadcast reference passes, starter fails only on the plan, Run visible grades plan checks). Not re-checked in a real F5 session.

Related repositories reviewed on 2026-09-25 (on disk under `D:\PROJ`): `fastapispark` is an earlier stand-alone fake-Spark FastAPI service (regex parser, one DuckDB query); SparkLab here supersedes it. Its open PR #1 adds an optional real-Spark oracle on GitHub Actions (learner code runs on public runners with a server token), not integrated. `datapass-airflow-runner` is empty. `fastapi-fabric` is a v0.1 Data Factory pipeline simulator (in-memory; only `Succeeded` dependency conditions are honored). Decision with the user: the VS Code Workbench is the product; no FastAPI Cloud or web backend. Promote useful ideas into this runtime (next candidates: an Airflow simulator in the Python runtime with graded exercises; a Data Factory pipeline mode in Fabric Lab).

## 2026-09-25 · Data-engineering patterns pack

Merged as PR #6 (`63e5f0b`). Branch `content/more-exercises`. New pack `content/exercise-packs/de-patterns-v1` (16 authored DuckDB SQL exercises, 5 easy / 8 medium / 3 hard). It fills the gap between `sql-lab-v1` (joins/grouping/windows) and real pipeline work: typing text columns after Mosaic **Import CSV**, latest-per-key CDC dedup with a tie-breaker, the `NOT IN` NULL trap, gaps and islands, 30-minute sessionization, `ASOF LEFT JOIN`, SCD2 validity ranges with `LEAD`, full-row upsert results, a UNION ALL data-quality rule report, a `generate_series` calendar spine, a user-level funnel, `MEDIAN`, monthly cohorts, `string_split`/`UNNEST` tag normalisation, strict `>` watermarks, and `COUNT(*) FILTER` vs the `COUNT(boolean)` trap.

Every exercise has a visible, a hidden and an edge fixture designed around its pitfall, a runnable starter that fails, and 1-3 mutants (34 in total). Expected rows were computed by running the reference over the grader's own typed fixture CTEs, then reviewed by hand. Gate: `exercise_packs_smoke.py` → 173 references pass, 173 starters and 188 mutants rejected; `de-patterns-v1` joined `RUNNABLE_STARTER_PACKS`. The host E2E grades `de-not-in-null-trap` from the extension catalog (the reference passes; `NOT IN` fails only on the guest-order fixture).

## 2026-09-25 · Mosaic CSV import

Merged as PR #4 (`aeb7aef`).

Branch `feature/mosaic-import-csv`. Gives learners a way to load their own data besides the retail demo, using the existing `import_csv` kernel op.

- **Runtime**: `POST /api/local/import-csv` `{asset, text}`. Pydantic allows only `bronze.<ident>` and text up to 1,000,000 chars, and forbids extra fields (no `path`). `local_data.parse_csv` still enforces 1 MB UTF-8 bytes, 5,000 rows, 1-40 unique simple headers, and equal field counts. An existing table → 400 "already exists"; imports never overwrite. Every column is `VARCHAR`. `/api/capabilities → mosaic.csv_import` states these rules.
- **Extension**: **Import CSV…** in Mosaic's *Local data runtime* block (enabled only while the runtime runs). The host opens a file picker, reads the file, decodes it strictly as UTF-8 (`src/platform/csvImport.ts`: size, encoding, empty-file checks), and suggests a free `bronze.<name>` from the file name, validated live against the catalog. It then sends the TEXT, not the path. The result is `RuntimeViewState.csvImport`, shown as a preview with the rows, "every column is text" and a CAST hint; a later SQL/Python run replaces it. FastAPI `detail` is surfaced as "CSV import refused: …".
- **Truth**: real local DuckDB import; no type inference is claimed.

Checked: `npm run compile`; `npm test` (new `csv_import_smoke.mjs`); `runtime_smoke.py` (new TestClient block: import, catalog, duplicate/non-bronze/injection-name/malformed/over-limit/extra-`path` refusals, CAST query); compileall; pack smoke; `npm run test:host` (new step, 17/17); browser harness render of the preview and the button → `importCsv` message. Not re-checked in a real F5 session (the native file picker and input box are only exercised through the host classes).

## 2026-09-25 · Polish tranche

Merged as PR #3 (`603babd`). Branch `polish/setup-progress-and-lockfile`. Closes the three "known, not fixed" items from the F5 pass below and the lockfile decision.

- **Setup runtime progress**: `RuntimeEnvironmentView.progress` carries step (1 venv, 2 pip install, 3 engine import check), the latest recognised pip line (`describeSetupOutputLine` in `src/platform/runtimeEnvironment.ts`, throttled to one webview update per 400 ms) and the start time. The Local runtime card shows it with an indeterminate bar and a ticking elapsed time (pip reports no overall percentage, so no fake percentage is shown); a VS Code notification mirrors it. The Output channel is no longer forced open; **Show setup log** opens it, also after a failed setup.
- **Minimap theme**: `--xy-minimap-*` variables are mapped to VS Code theme colors in `workbench.css`.
- **Pipeline header**: shows the compiler truth in words (`Source: compiled, never executed`), a per-activity count (`3 run locally · 1 declared only`), and marks the schedule as metadata only. The runtime contract (`truth: compiled_design_only`) is unchanged.
- **Lockfile**: `package-lock.json` is committed; CI uses `npm ci` with the npm cache.

Checked: `npm run compile`, `npm test` (new parser assertions in `runtime_environment_smoke.mjs`), the Python gates, and the built webview in a browser harness with a stubbed VS Code API (setup-progress card, pipeline header, minimap computed colors in a dark theme). Not re-checked in a real F5 session.

## 2026-09-25 · Manual F5 pass

A real VS Code 1.139 Extension Development Host (fresh profile, disposable workspace, managed runtime set up through the UI) was driven over the Chrome DevTools Protocol: real webview buttons, the real modal dialog, real mouse drags, screenshots. This replaced the "NOT exercised" item from the earlier tranche.

Exercised end to end in the real UI: Labs tree, Create .datapass project, **Setup runtime** (managed venv + pip install), Start/Stop runtime, Mosaic SQL + Python, trusted-Python enable via modal, "requested" state after a lost confirmation, disable, Mosaic drag → `.datapass/mosaic.json` → close/reopen restore, SparkLab (profile/AQE switch, unsupported syntax), Practice (filter, open solution + brief, Run visible, Submit, Python lab), Fabric Lab scaffold + medallion run, generated retail SQL in Mosaic, Pipeline graph + run, Airflow step/run/reset, dbt static lineage with a broken local dbt install.

Bugs found and fixed:

1. **Start runtime always failed on a fresh managed venv**: 6.5 s health timeout vs ~10 s cold start. Now 90 s with fail-fast on process exit; Polars/DuckDB imported lazily in `retail_demo.py` (health in ~1.6 s here).
2. **Run active SQL/Python failed in the default single tab group**: the Workbench hides the file it shares a group with. Files now open beside the Workbench and the last focused `.sql`/`.py` is remembered.
3. **Pipeline/Airflow/dbt graph blanked the whole Workbench** (React #185, max update depth): `SharedGraphCanvas` recreated its persisted view object every render → endless `setNodes`. Now keyed on graph content; unrelated host messages no longer reset dragged nodes.
4. **SQL submissions ending in a `--` comment failed to parse** (every SQL starter did): the grading wrapper put `) AS submitted` on the comment line. Fixed with `subquery_body`; the pack gate now requires runnable starters in the new packs (caught a `GROUP BY`-less starter).
5. **Guided Spark shown as gradable** → raw HTTP 400. Now labelled not locally gradable, buttons disabled.
6. **Start runtime without an open folder** started anyway, then HTTP 500s. Now refused with a clear message.
7. Badges wrapped out of their pills; Output panel popped open on every start; a broken dbt install dumped a 20-line traceback into the dbt card (now one line). QUICKSTART/README used stale button labels.

Known, not fixed at the time (all three addressed in "2026-09-25 · Polish tranche"): first **Setup runtime** took ~15 min on this Windows machine (pip unpacking under antivirus); only the output channel shows progress. React Flow minimap is light in dark theme. Pipeline header shows the compiler's `compiled_design_only` truth next to executable activities.

The driver lives outside the repo (Playwright over CDP); if you repeat it, launch Code with `--folder-uri`, `--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows`, and `window.dialogStyle: custom`, and use DOM clicks inside webviews.

## 2026-09-24 · Content tranche

| Commit | Change |
| --- | --- |
| `2eb2740` | Typed fixture literals; SQL named multi-table fixtures; semantic-variant id fix in Practice; pandas runtime dependency; richer exercise brief |
| `5af1be0` | `sql-lab-v1` pack (30 DuckDB SQL exercises) + `scripts/exercise_packs_smoke.py` mutant gate (CI runtime job) + host E2E grading step |

What changed and why:

- **Grader**: fixture literals are CAST to allowlisted `data_context` types; SQL exercises may declare several named fixture tables (one CTE each). Non-SQL languages reject named tables. See `docs/EXERCISE_AUTHORING.md`.
- **Bugs found by grading every installed exercise**: (1) the Practice catalog listed semantic-pack variants under the scenario id, which the runtime does not register, so all 10 `unified-retail-v1` variants failed to grade from the UI; (2) its Python variants import pandas, which the runtime never installed. Both fixed.
- **Content**: 30 exercises adapted from `legacy-donors/leetcodedataeng/sqlChallenges.js` (joins, GROUP BY/HAVING, CASE, GROUPING SETS/ROLLUP/CUBE, windows), with new visible/hidden/edge fixtures designed around each pitfall. Expected rows were computed from the reference solution and every row was reviewed by hand.
- **Quality gate**: the pack smoke grades all 47 installed exercises: reference passes, starter fails, and 51 runnable mutants (plausible wrong answers) fail.

Executed: `npm run compile`, `npm test`, runtime smoke, pack smoke, and `npm run test:host` (16 steps) locally. CI for `5af1be0` must be checked before continuing.

Not done / next content steps:

- Done in a follow-up: the remaining 30 donor SQL lab items were added (pack version 2, 60 exercises; 108 mutants in the gate). All 60 donor SQL lab challenges are now promoted.
- Done in a follow-up: `engine-lab-v1` (20 cross-engine scenarios, 68 SQL/pandas/Polars/SparkLab variants) and `python-lab-v1` (12 exercises) promoted from `engineLab.js` / `curriculum.js`; named fixture tables now bind in SQL, SparkLab and Python/Polars. The gate grades 157 exercises with 154 mutants. What was not promoted, and why, is listed in `docs/EXERCISE_AUTHORING.md`.
- Reference solutions ship inside the VSIX (`grading.server.json`); grading is a teaching aid, not an exam control.


Branch tip after this tranche: `48ee7b6` on `codex/bootstrap-datapass-workbench` (draft PR #1 stays draft).

| Commit | Change |
| --- | --- |
| `8e17eaf` | Explicit trusted-Python opt-in; direct SparkLab execution UX; graceful kernel shutdown; runtime reports trust |
| `31d0283` | Extension Development Host E2E suite (`npm run test:host`) + `extension-host` CI job |
| `d59716d` | Pipeline dbt activity kept explicitly unsupported, fails fast; per-activity truth labels in the graph |
| `dc191c5` | Mosaic layout persisted to versioned `.datapass/mosaic.json`; SparkLab result overflow fix |
| `48ee7b6` | Retail SQL starter made runnable through Mosaic (no blocked file functions) |

CI: `8e17eaf` run 36049484672 and `31d0283` run 36050050237 were green on all jobs (extension, runtime, extension-host with all 14 E2E steps executed, none skipped). Check the latest run for `48ee7b6` before continuing.

### What was actually executed vs statically inspected

Executed (automated, locally on Windows and in Linux CI):

- `npm run compile`, `npm test` (6 Node contract smokes incl. new `trust_smoke.mjs`, `mosaic_layout_smoke.mjs`);
- `python -m pip install ./runtime`, `compileall`, `scripts/runtime_smoke.py` (now also: trusted/untrusted Python, workspace-relative paths, SparkLab starter + unsafe-source rejection, dbt pipeline fail-fast);
- `npm run test:host`: a real VS Code Extension Development Host on a disposable workspace. Activation + all commands, Workbench webview opens, manifest, trust resolution, Mosaic layout file round trip, Airflow starter, dbt static lineage, then against a real runtime: untrusted start despite injected `DATAPASS_TRUSTED_PYTHON=1`, Mosaic SQL, Python refusal, SparkLab, Practice run/submit/wrong answer, Pipeline compile + run, retail demo + generated retail SQL, trusted restart + real Python/Polars run.

Executed visually (not in CI): the built `dist/webview.js` was rendered in a browser harness with a stubbed VS Code API and state captured from the real runtime. Mosaic (untrusted/trusted) and SparkLab (success/rejected) were inspected, and button → host messages were verified. This found and fixed a SparkLab layout overflow.

NOT exercised: a human F5 session clicking through the real webview inside VS Code (modal confirmation dialog, drag/resize writing `.datapass/mosaic.json`, reload restoring it). The E2E drives the same host classes but does not click webview buttons. Do this before taking PR #1 out of draft.

### Decisions made in this tranche

- **Trusted Python** = manifest `runtime.trustedLocalPython: true` AND per-machine modal confirmation (`workspaceState`) AND VS Code Workspace Trust. A cloned repo's manifest flag alone never enables Python. The extension builds the runtime env via `runtimeProcessEnv` (always strips inherited `DATAPASS_TRUSTED_PYTHON`), verifies `/api/capabilities → runtime.trusted_local_python` after start, and restarts a running runtime on change.
- **Pipeline dbt** stays declared-only (option 2 of the P2 item). Reason: donor `dbt_runner.py` depends on job/document infrastructure absent here, and dbt macros/hooks need the trust boundary extended first.
- **Mosaic layout** is project-portable only inside a Datapass project; opening Mosaic never creates `.datapass/`.
- **Mosaic SQL file access** stays blocked (`read_csv_auto` etc.); starters build on catalog tables instead.

### Recommended next steps

1. Manual F5 pass over the new UI (see "NOT exercised" above), then decide on un-drafting PR #1. *(Done 2026-09-25; PR #1 merged.)*
2. P2 content: promote exercises from `legacy-donors/leetcodedataeng`. The grader uses a single `input` fixture table per exercise (`content/exercise-packs/*/grading.server.json`); most donor SQL problems are multi-table, so either extend fixtures to named tables or re-author. Add each exercise to the runtime smoke with its reference solution.
3. ~~A Mosaic "Import CSV into catalog" action~~ Done ("2026-09-25 · Mosaic CSV import").
4. If wiring Pipeline dbt later: extend the trusted-local opt-in to dbt, validate the project path against the manifest `assets.dbt`, reuse `dbt_runner` artifact validation, never report success without a qualified manifest/run_results pair.
5. ~~`package-lock.json` is not committed~~ Done: the lockfile is committed and CI uses `npm ci` ("2026-09-25 · Polish tranche").

## 2026-09-24 · PR #1: the implementation branch merged into `main`

PR #1 merged the implementation branch into `main` with a merge commit (`f35dbe4`, all 223 commits preserved). CI on `main` after the merge was green on all three jobs (run 36068237602). `codex/bootstrap-datapass-workbench` is kept for history only.

Workflow from here: branch from `main` for each tranche, keep CI green, merge through a pull request. The dated sections below record how the project got here; branch names and tips in them are historical.

## 2026-09-24 · Original handoff reference sections

Sections 1–11 of the first handoff (`docs/CLAUDE_HANDOFF_2026-09-24.md`), as they stood on 2026-09-26 when the
file was split. Several are out of date (the module list, the Airflow Lab description, the required tests); the
current state is in docs/HANDOFF.md. Kept whole so no decision or fact is lost.

### 1. Start here

Repository: `julian-passebecq/datapass-mosaic-vscode`

Baseline branch: `main` (see "Current status" above). Start new work on a branch from `main`.

History: before PR #1, `main` was the one-line initial repository and all work lived on `codex/bootstrap-datapass-workbench`. The older baseline records below are kept for reference.

Known good implementation baseline before the first documentation pass:

```text
ae489cd161e4565808a056de17b42241c63ecc20
Smoke test versioned Practice grading
2026-09-24 13:54:10 UTC
```

GitHub Actions run for that baseline:

```text
run 36008901370
extension: success
runtime:   success
```

Later tranches added the work recorded in the dated sections above; all of it is now on `main`.

### 2. History: why the project looked stopped

The work did not disappear. It was left on `codex/bootstrap-datapass-workbench` while `main` remained essentially empty, until PR #1 merged it on 2026-09-24.

The branch also progressed materially beyond the older checkpoint `abfe28df`. In particular, the execution bridge was completed further than earlier notes implied:

- real native SQL execution from Mosaic;
- shared local runtime/catalog state;
- real bounded Pipeline Lab activity execution;
- managed runtime environment setup;
- native-file Practice grading with separate Run/Submit behavior;
- VSIX package-boundary checks;
- extracted dbt sample outside donor trees.

Do not repeat those migrations.

### 3. Product architecture

Datapass Workbench is one VS Code extension, not a collection of separate apps.

```text
VS Code
├─ native editor / files / terminal / Git / Jupyter
└─ Datapass Workbench
   ├─ Mosaic
   ├─ Practice
   ├─ Fabric Lab
   ├─ SparkLab / ZilaCode
   ├─ dbt Lab
   ├─ Airflow Lab
   └─ Pipeline Lab
          │
          ▼
      one FastAPI runtime
      ├─ DuckDB / optional DuckLake
      ├─ Polars
      ├─ bounded SparkLab
      ├─ shared catalog/kernel
      ├─ exercise grading
      └─ bounded pipeline execution
```

Keep separate:

- Datapass WorkNotebook: standalone public/reference/cheatsheet experience.
- Contoso Data Studio: separate C# product; datasets/cases may cross the boundary.
- historical donors: references only.

### 4. Current surface status

#### Mosaic

Implemented:

- draggable/resizable `react-grid-layout` surface;
- persistent webview layout state;
- native VS Code SQL/Python/Markdown scratch files;
- real active-file SQL execution through the FastAPI runtime;
- SQL result preview;
- shared local catalog display.

Resolved in the 2026-09-24 Claude tranche:

- **Run active Python** executes the active `.py` file only when trusted local Python is effective; otherwise it is disabled with the reason shown.
- The layout is persisted to `.datapass/mosaic.json` inside a Datapass project.

#### Practice

Implemented:

- versioned exercise catalog;
- searchable Practice UI;
- native VS Code solution files;
- real shared-runtime grading;
- separate visible checks vs submission;
- status/check feedback in the webview;
- smoke coverage for versioned grading.

This is no longer just a scaffold.

#### Fabric Lab

Implemented:

- Fabric-inspired local teaching flow;
- connected retail demo scaffolding;
- real local medallion demo with DuckDB/Polars;
- preview/KPI results;
- links into SparkLab and Pipeline Lab.

Truth boundary:

- this is not an implicit Microsoft Fabric client;
- orchestration/Fabric chrome are teaching semantics;
- real local engines must be labeled as such.

#### SparkLab / ZilaCode

Runtime capability exists and is bounded.

Direct workflow implemented (2026-09-24 Claude tranche): `notebooks/sparklab.py` scratch, virtual cluster profile + AQE selection, **Run active SparkLab file**, result rows + compiled SQL (real local), teaching logical plan, and a SIMULATED stage/shuffle/credits panel. Unsupported source is rejected with `SparkLabSyntaxError`. No new Spark engine was added.

#### dbt Lab

Rebuilt on 2026-09-25 as the real-life lab (see "2026-09-25 · dbt Lab rebuild: real dbt Core, dbt Charts, missions"): managed dbt Core + dbt-duckdb + dbt Charts installed on
request, real commands typed in a VS Code terminal, the catalog handoff, the artifacts view, dbt Charts boards and
the missions. No static lineage and no emulation here (the emulation is the BI Lab's dbt tab).

Pipeline Lab accepts a dbt activity in the design grammar, but native pipeline dbt execution is deliberately **not wired**. `native_pipeline.py` fails that task once (no retries), states nothing was run, and skips downstream tasks; the graph labels it *Declared only · not executed*.

#### Airflow Lab

Implemented as deterministic UI-side simulation:

- DAG definition;
- dependencies;
- retries;
- retry delay;
- trigger rules;
- task states;
- simulated logs;
- step/run-to-end/reset.

Do not replace this with a full Airflow install merely to teach scheduling semantics.

#### Pipeline Lab

Implemented:

- bounded Python-like AST compiler;
- literal-only task declarations;
- dependency graph;
- source diagnostics;
- shared React Flow visualization;
- real local execution for supported activity bodies;
- task run history/result states.

Critical distinction:

```text
pipeline SOURCE: compiled only, NEVER eval/exec
activity BODY: may execute through the shared local runtime
schedule: metadata / teaching semantics
```

Currently wired activity bodies:

- SQL
- quality
- Python
- Polars

dbt syntax exists but runtime execution is not wired.

### 5. Runtime and security model

Key files:

- `runtime/datapass_runtime/main.py`
- `runtime/datapass_runtime/execution.py`
- `runtime/datapass_runtime/kernels.py`
- `runtime/datapass_runtime/native_pipeline.py`
- `runtime/datapass_runtime/pipeline_compiler.py`

The runtime is a loopback FastAPI control plane.

The kernel worker provides lifecycle isolation and timeout/restart semantics. It is **not a hostile-code sandbox**.

Environment filtering removes obvious TOKEN/SECRET/PASSWORD/API_KEY variables before spawning a worker, but that does not make arbitrary Python safe.

#### Trusted Python issue to resolve deliberately

`execution.py` only enables Python when `trusted_python=True`.

The API derives that from:

```text
DATAPASS_TRUSTED_PYTHON=1
```

Normal managed-runtime startup does not silently opt the user into this, which is the correct safety posture.

Therefore:

- SQL works in the normal local runtime.
- bounded SparkLab semantics work through their safe parser.
- arbitrary Python/Polars execution must remain explicitly trusted.

Implemented (2026-09-24 Claude tranche): see section 0 and `docs/ARCHITECTURE.md` → "Trusted local Python". Key files: `src/platform/pythonTrust.ts`, `src/pythonTrustController.ts`, `src/runtimeManager.ts`.

Suggested contract direction:

```json
{
  "runtime": {
    "storage": "duckdb",
    "pythonCommand": "python",
    "trustedLocalPython": false
  }
}
```

Requirements:

- default false;
- clear warning that it executes local code;
- workspace-scoped/project-scoped choice;
- no misleading “sandbox” wording;
- update runtime state/capabilities visibly.

### 6. Important files

Extension host:

- `src/extension.ts`
- `src/workbenchPanel.ts`
- `src/runtimeManager.ts`
- `src/workbenchState.ts`

Webview:

- `src/webview/WorkbenchApp.tsx`
- `src/webview/MosaicSurface.tsx`
- `src/webview/PracticeSurface.tsx`
- `src/webview/FabricSurface.tsx`
- `src/webview/SparkLabSurface.tsx`
- `src/webview/PipelineSurface.tsx`
- `src/webview/AirflowSurface.tsx`
- `src/webview/DbtSurface.tsx`
- `src/webview/SharedGraphCanvas.tsx`

Contracts/project:

- `src/webview/contracts.ts`
- `src/project/projectManifestModel.ts`
- `src/project/projectManifest.ts`

Runtime/tests:

- `runtime/datapass_runtime/main.py`
- `runtime/datapass_runtime/execution.py`
- `runtime/datapass_runtime/kernels.py`
- `runtime/datapass_runtime/native_pipeline.py`
- `scripts/runtime_smoke.py`
- `scripts/runtime_endpoint_smoke.mjs`
- `scripts/scaffold_smoke.mjs`
- `scripts/package_smoke.mjs`
- `.github/workflows/ci.yml`

### 7. Donor policy

Already audited in `docs/HARVEST_AUDIT.md`.

Use:

- `workbench-core/`
- `migration-sources/`
- `legacy-donors/`

only to recover a proven capability or content item.

Do not:

- add another React app shell;
- add another Monaco/editor layer;
- add another notebook runtime;
- add a duplicate Spark implementation;
- copy a full Airflow deployment;
- duplicate dbt execution;
- turn Fabric Lab into an unreviewed cloud control plane.

The VSIX intentionally excludes donor/development trees.

### 8. Priority continuation plan

Proceed in this order unless a newly reproduced bug blocks the sequence.

#### P0 — protect `main`

1. Branch from `main` for each tranche; merge back through a pull request.
2. Keep CI green after every coherent tranche.
3. Do not force-push or rewrite `main` history.
4. For user-facing changes, repeat the manual F5 pass (see "2026-09-25 · Manual F5 pass") before merging.

Status after the 2026-09-24 Claude tranches: P1 trusted Python — done; P1 SparkLab — done; P1 E2E — done (`npm run test:host`); P2 pipeline dbt — decided: explicitly unsupported; P2 Mosaic durability — done; P2 content — donor Practice content promoted: `sql-lab-v1` (60), `engine-lab-v1` (68 variants), `python-lab-v1` (12); non-gradable donor tracks intentionally left to reference material. Manual F5 pass done on 2026-09-25 and PR #1 merged to `main`. Remaining: the known limitations listed in "2026-09-24 · Content tranche" ("Recommended next steps") and further content.

#### P1 — trusted Python/Polars UX (done)

Implement explicit workspace/project opt-in.

Acceptance criteria:

- default remains disabled;
- state is visible in Workbench;
- managed runtime receives the flag only after explicit opt-in;
- Python/Polars buttons clearly explain why disabled when untrusted;
- tests cover default-disabled and enabled configuration;
- no claim of sandboxing.

#### P1 — direct SparkLab execution experience

Use the existing bounded SparkLab parser/runtime.

Target:

- open/edit code in native VS Code;
- run supported SparkLab source;
- show result rows;
- show logical/teaching physical plan;
- visibly mark simulated stages/shuffle/cost;
- reject unsupported syntax clearly.

Do not add a second Spark engine.

#### P1 — end-to-end Extension Host smoke

Automated unit/smoke gates are green, but add/strengthen extension-host/E2E coverage for:

1. create `.datapass/project.json`;
2. setup/start runtime;
3. run Mosaic SQL;
4. create/open Practice exercise and submit;
5. compile/run Pipeline Lab;
6. run retail demo;
7. inspect Airflow simulator;
8. dbt static lineage and real dbt route when available.

#### P2 — pipeline dbt activity

Either:

- wire it to real dbt Core the way the dbt Lab runs it (managed tools, generated profile, catalog handoff), or
- keep it disabled and make the UI/compiler state explicit.

Do not fake successful dbt execution.

#### P2 — Mosaic durability and UX

The layout currently survives via webview state. Evaluate whether project-portable Mosaic layouts should be stored under `.datapass/`.

If added:

- version the schema;
- keep source files native;
- do not serialize runtime secrets;
- gracefully migrate old layouts.

#### P2 — broader teaching content

After the runtime/surface contracts stabilize, promote additional exercises/cases from existing donor content rather than expanding shells first.

### 9. Required tests

Extension:

```bash
npm install --no-audit --no-fund
npm run compile
npm test
```

Runtime:

```bash
python -m pip install ./runtime
python -m compileall -q runtime/datapass_runtime runtime/sparklab runtime/airflowlab
python scripts/runtime_smoke.py
python scripts/exercise_packs_smoke.py
```

Extension Development Host E2E (see `docs/LOCAL_TEST.md`):

```bash
npm run test:host   # with DATAPASS_E2E_PYTHON pointing to a Python that has ./runtime installed
```

Current CI runs extension, runtime and extension-host jobs.

Manual test:

1. open the repo in VS Code;
2. press F5;
3. in Extension Development Host open a disposable data-project folder;
4. open Datapass activity bar;
5. Setup runtime;
6. Create `.datapass` project;
7. Mosaic: open/run SQL and inspect preview/catalog;
8. Practice: open an exercise, edit native solution, Run visible, Submit;
9. Pipeline: create source, compile graph, run supported activities;
10. Fabric Lab: create/repair retail demo, execute medallion flow;
11. Airflow: step/run/reset;
12. dbt Lab: Install dbt tools, run dbt build from the lab (terminal), see the artifacts and the Catalog view, render a board, check a mission.

### 10. Definition of done for the next Claude tranche

Do not report the project as finished merely because it compiles.

A tranche is done when:

- implementation matches the truth labels;
- no duplicate runtime/editor is introduced;
- security boundary is preserved;
- TypeScript build passes;
- Node smoke tests pass;
- Python runtime smoke passes;
- user-facing flow is manually exercised where applicable;
- docs/contracts are updated in the same tranche.

### 11. What not to do

- Do not restart this project from scratch.
- Do not commit directly to `main` or rewrite its history; branch from it and merge through a pull request with green CI.
- Do not continue work on the historical `codex/bootstrap-datapass-workbench` branch.
- Do not silently enable trusted Python.
- Do not eval/exec pipeline source.
- Do not claim SparkLab is a real Spark cluster.
- Do not claim Airflow simulation is real Airflow.
- Do not claim Fabric Lab is connected to Microsoft Fabric unless a future explicit connector is added.
- Do not present the BI Lab's dbt emulation as dbt Core, or anything but a real `dct` output as dbt Charts.
- Do not import whole donor repos into the production VSIX.
- Do not create competing app shells.

Read `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/HARVEST_AUDIT.md`, and this file before changing architecture.
