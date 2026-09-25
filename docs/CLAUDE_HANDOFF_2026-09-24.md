# Claude handoff — Datapass Workbench VS Code

Date: 2026-09-24 (updated 2026-09-25)

## Current status — `main` is the baseline

PR #1 merged the implementation branch into `main` with a merge commit (`f35dbe4`, all 223 commits preserved). CI on `main` after the merge was green on all three jobs (run 36068237602). `codex/bootstrap-datapass-workbench` is kept for history only.

Workflow from here: branch from `main` for each tranche, keep CI green, merge through a pull request. The dated sections below record how the project got here; branch names and tips in them are historical.

## 0. Airflow lab simulator and exercise pack — Claude, 2026-09-25 (newest)

Branch `content/airflow-lab-v1`. Airflow practice without Airflow, in the local runtime (no FastAPI Cloud, no separate service; `datapass-airflow-runner` stays empty).

- **Simulator** `runtime/airflowlab` (new package, shipped in the VSIX with the runtime): `parser.py` reads a real-looking Airflow DAG file through a whitelisted AST walk and never executes it (classic operators, sensors, TaskFlow `@task`/`@dag`, `>>`/lists/`chain`, `default_args`, timetables); unsupported syntax is rejected with a line number, including Airflow 2 arguments removed in Airflow 3. `schedule.py` creates runs with Airflow 3 timetables (CronTriggerTimetable by default, CronDataIntervalTimetable on request, catchup default False). `simulate.py` simulates task instances (Airflow's TriggerRuleDep rules, retries, execution_timeout, sensor poke/timeout/soft_fail, branch and short-circuit skipping, leaf-based run state). `templates.py` renders `{{ ds }}`-style fields without Jinja or eval. See its README for exactly what is and is not modeled.
- **Grading**: new exercise language `airflow`, runtime `datapass-airflow-sim-v1`, truth `simulated` (`datapass_runtime/airflow_grading.py`). Fixtures carry a `scenario` (scheduler clock, task behavior, outcome table) instead of input rows; the registry validates it. See `docs/EXERCISE_AUTHORING.md`.
- **Pack** `airflow-lab-v1` (13 exercises: 6 easy / 5 medium / 2 hard): fan-in/fan-out, TaskFlow data dependencies, catchup, no accidental backfill, weekday cron, data-interval timetable, `ds_add` under the Airflow 3 `@daily` default, retries, all_done cleanup, one_failed watcher, branch join, soft-fail sensor, `default_args` override. Expected rows computed by simulating the references, reviewed by hand; 32 mutants.
- **Extension**: `airflow` solutions open as `.py`; the brief says the file is parsed, never executed. The Airflow Lab surface is unchanged: it still simulates `airflow/main.dag.json` in the webview. Next step: point it at DAG `.py` files and this runtime simulator, and retire the webview simulator, so there is one Airflow implementation.
- **Semantics checked against Airflow's code paths from memory, not against a live Airflow**: CronTriggerTimetable vs CronDataIntervalTimetable run creation, `_skip_to_latest`, TriggerRuleDep, sensor timeout after a false poke, `try_number <= retries`. A real-Airflow oracle (like the Spark one in `fastapispark` PR #1) would be the way to verify them.

Checked: `npm run compile`; `npm test` (airflow brief, package boundary); `pip install ./runtime`; compileall; `runtime_smoke.py` (parser rejections, both timetables, catchup, a trigger-rule table, retries, sensor timeout, templates); `exercise_packs_smoke.py` → 186 references pass, 186 starters and 220 mutants rejected; `npm run test:host` (branch-join reference passes, starter fails, `import os` rejected). Not re-checked in a real F5 session.

## 0a. Data-engineering patterns pack — Claude, 2026-09-25

Merged as PR #6 (`63e5f0b`). Branch `content/more-exercises`. New pack `content/exercise-packs/de-patterns-v1` (16 authored DuckDB SQL exercises, 5 easy / 8 medium / 3 hard). It fills the gap between `sql-lab-v1` (joins/grouping/windows) and real pipeline work: typing text columns after Mosaic **Import CSV**, latest-per-key CDC dedup with a tie-breaker, the `NOT IN` NULL trap, gaps and islands, 30-minute sessionization, `ASOF LEFT JOIN`, SCD2 validity ranges with `LEAD`, full-row upsert results, a UNION ALL data-quality rule report, a `generate_series` calendar spine, a user-level funnel, `MEDIAN`, monthly cohorts, `string_split`/`UNNEST` tag normalisation, strict `>` watermarks, and `COUNT(*) FILTER` vs the `COUNT(boolean)` trap.

Every exercise has a visible, a hidden and an edge fixture designed around its pitfall, a runnable starter that fails, and 1-3 mutants (34 in total). Expected rows were computed by running the reference over the grader's own typed fixture CTEs, then reviewed by hand. Gate: `exercise_packs_smoke.py` → 173 references pass, 173 starters and 188 mutants rejected; `de-patterns-v1` joined `RUNNABLE_STARTER_PACKS`. The host E2E grades `de-not-in-null-trap` from the extension catalog (the reference passes; `NOT IN` fails only on the guest-order fixture).

## 0b. Mosaic CSV import — Claude, 2026-09-25

Merged as PR #4 (`aeb7aef`).

Branch `feature/mosaic-import-csv`. Gives learners a way to load their own data besides the retail demo, using the existing `import_csv` kernel op.

- **Runtime**: `POST /api/local/import-csv` `{asset, text}`. Pydantic allows only `bronze.<ident>` and text up to 1,000,000 chars, and forbids extra fields (no `path`). `local_data.parse_csv` still enforces 1 MB UTF-8 bytes, 5,000 rows, 1-40 unique simple headers, and equal field counts. An existing table → 400 "already exists"; imports never overwrite. Every column is `VARCHAR`. `/api/capabilities → mosaic.csv_import` states these rules.
- **Extension**: **Import CSV…** in Mosaic's *Local data runtime* block (enabled only while the runtime runs). The host opens a file picker, reads the file, decodes it strictly as UTF-8 (`src/platform/csvImport.ts`: size, encoding, empty-file checks), and suggests a free `bronze.<name>` from the file name, validated live against the catalog. It then sends the TEXT, not the path. The result is `RuntimeViewState.csvImport`, shown as a preview with the rows, "every column is text" and a CAST hint; a later SQL/Python run replaces it. FastAPI `detail` is surfaced as "CSV import refused: …".
- **Truth**: real local DuckDB import; no type inference is claimed.

Checked: `npm run compile`; `npm test` (new `csv_import_smoke.mjs`); `runtime_smoke.py` (new TestClient block: import, catalog, duplicate/non-bronze/injection-name/malformed/over-limit/extra-`path` refusals, CAST query); compileall; pack smoke; `npm run test:host` (new step, 17/17); browser harness render of the preview and the button → `importCsv` message. Not re-checked in a real F5 session (the native file picker and input box are only exercised through the host classes).

## 0c. Polish tranche — Claude, 2026-09-25

Merged as PR #3 (`603babd`). Branch `polish/setup-progress-and-lockfile`. Closes the three "known, not fixed" items from the F5 pass below and the lockfile decision.

- **Setup runtime progress**: `RuntimeEnvironmentView.progress` carries step (1 venv, 2 pip install, 3 engine import check), the latest recognised pip line (`describeSetupOutputLine` in `src/platform/runtimeEnvironment.ts`, throttled to one webview update per 400 ms) and the start time. The Local runtime card shows it with an indeterminate bar and a ticking elapsed time (pip reports no overall percentage, so no fake percentage is shown); a VS Code notification mirrors it. The Output channel is no longer forced open; **Show setup log** opens it, also after a failed setup.
- **Minimap theme**: `--xy-minimap-*` variables are mapped to VS Code theme colors in `workbench.css`.
- **Pipeline header**: shows the compiler truth in words (`Source: compiled, never executed`), a per-activity count (`3 run locally · 1 declared only`), and marks the schedule as metadata only. The runtime contract (`truth: compiled_design_only`) is unchanged.
- **Lockfile**: `package-lock.json` is committed; CI uses `npm ci` with the npm cache.

Checked: `npm run compile`, `npm test` (new parser assertions in `runtime_environment_smoke.mjs`), the Python gates, and the built webview in a browser harness with a stubbed VS Code API (setup-progress card, pipeline header, minimap computed colors in a dark theme). Not re-checked in a real F5 session.

## 0d. Manual F5 pass — Claude, 2026-09-25

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

Known, not fixed at the time (all three addressed in §0c): first **Setup runtime** took ~15 min on this Windows machine (pip unpacking under antivirus); only the output channel shows progress. React Flow minimap is light in dark theme. Pipeline header shows the compiler's `compiled_design_only` truth next to executable activities.

The driver lives outside the repo (Playwright over CDP); if you repeat it, launch Code with `--folder-uri`, `--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows`, and `window.dialogStyle: custom`, and use DOM clicks inside webviews.

## 0e. Content tranche — Claude, 2026-09-24

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
3. ~~A Mosaic "Import CSV into catalog" action~~ Done (§0b).
4. If wiring Pipeline dbt later: extend the trusted-local opt-in to dbt, validate the project path against the manifest `assets.dbt`, reuse `dbt_runner` artifact validation, never report success without a qualified manifest/run_results pair.
5. ~~`package-lock.json` is not committed~~ Done: the lockfile is committed and CI uses `npm ci` (§0c).

## 1. Start here

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

Later tranches added the work recorded in §0; all of it is now on `main`.

## 2. History: why the project looked stopped

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

## 3. Product architecture

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

## 4. Current surface status

### Mosaic

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

### Practice

Implemented:

- versioned exercise catalog;
- searchable Practice UI;
- native VS Code solution files;
- real shared-runtime grading;
- separate visible checks vs submission;
- status/check feedback in the webview;
- smoke coverage for versioned grading.

This is no longer just a scaffold.

### Fabric Lab

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

### SparkLab / ZilaCode

Runtime capability exists and is bounded.

Direct workflow implemented (2026-09-24 Claude tranche): `notebooks/sparklab.py` scratch, virtual cluster profile + AQE selection, **Run active SparkLab file**, result rows + compiled SQL (real local), teaching logical plan, and a SIMULATED stage/shuffle/credits panel. Unsupported source is rejected with `SparkLabSyntaxError`. No new Spark engine was added.

### dbt Lab

Implemented:

- extracted local sample under `samples/dbt/retail-dbt`;
- dbt CLI + dbt-duckdb probing;
- static project lineage fallback;
- real `dbt build` path when tooling is installed;
- prefer real `target/manifest.json` after execution.

Pipeline Lab accepts a dbt activity in the design grammar, but native pipeline dbt execution is deliberately **not wired**. `native_pipeline.py` fails that task once (no retries), states nothing was run, and skips downstream tasks; the graph labels it *Declared only · not executed*.

### Airflow Lab

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

### Pipeline Lab

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

## 5. Runtime and security model

Key files:

- `runtime/datapass_runtime/main.py`
- `runtime/datapass_runtime/execution.py`
- `runtime/datapass_runtime/kernels.py`
- `runtime/datapass_runtime/native_pipeline.py`
- `runtime/datapass_runtime/pipeline_compiler.py`

The runtime is a loopback FastAPI control plane.

The kernel worker provides lifecycle isolation and timeout/restart semantics. It is **not a hostile-code sandbox**.

Environment filtering removes obvious TOKEN/SECRET/PASSWORD/API_KEY variables before spawning a worker, but that does not make arbitrary Python safe.

### Trusted Python issue to resolve deliberately

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

## 6. Important files

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

## 7. Donor policy

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

## 8. Priority continuation plan

Proceed in this order unless a newly reproduced bug blocks the sequence.

### P0 — protect `main`

1. Branch from `main` for each tranche; merge back through a pull request.
2. Keep CI green after every coherent tranche.
3. Do not force-push or rewrite `main` history.
4. For user-facing changes, repeat the manual F5 pass (see §0d) before merging.

Status after the 2026-09-24 Claude tranches: P1 trusted Python — done; P1 SparkLab — done; P1 E2E — done (`npm run test:host`); P2 pipeline dbt — decided: explicitly unsupported; P2 Mosaic durability — done; P2 content — donor Practice content promoted: `sql-lab-v1` (60), `engine-lab-v1` (68 variants), `python-lab-v1` (12); non-gradable donor tracks intentionally left to reference material. Manual F5 pass done on 2026-09-25 and PR #1 merged to `main`. Remaining: the known limitations listed in §0 and further content.

### P1 — trusted Python/Polars UX (done)

Implement explicit workspace/project opt-in.

Acceptance criteria:

- default remains disabled;
- state is visible in Workbench;
- managed runtime receives the flag only after explicit opt-in;
- Python/Polars buttons clearly explain why disabled when untrusted;
- tests cover default-disabled and enabled configuration;
- no claim of sandboxing.

### P1 — direct SparkLab execution experience

Use the existing bounded SparkLab parser/runtime.

Target:

- open/edit code in native VS Code;
- run supported SparkLab source;
- show result rows;
- show logical/teaching physical plan;
- visibly mark simulated stages/shuffle/cost;
- reject unsupported syntax clearly.

Do not add a second Spark engine.

### P1 — end-to-end Extension Host smoke

Automated unit/smoke gates are green, but add/strengthen extension-host/E2E coverage for:

1. create `.datapass/project.json`;
2. setup/start runtime;
3. run Mosaic SQL;
4. create/open Practice exercise and submit;
5. compile/run Pipeline Lab;
6. run retail demo;
7. inspect Airflow simulator;
8. dbt static lineage and real dbt route when available.

### P2 — pipeline dbt activity

Either:

- wire it to the existing real dbt Core adapter with strict project/resource validation, or
- keep it disabled and make the UI/compiler state explicit.

Do not fake successful dbt execution.

### P2 — Mosaic durability and UX

The layout currently survives via webview state. Evaluate whether project-portable Mosaic layouts should be stored under `.datapass/`.

If added:

- version the schema;
- keep source files native;
- do not serialize runtime secrets;
- gracefully migrate old layouts.

### P2 — broader teaching content

After the runtime/surface contracts stabilize, promote additional exercises/cases from existing donor content rather than expanding shells first.

## 9. Required tests

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
12. dbt: verify static lineage; if dbt Core + dbt-duckdb exist, run build and verify manifest-backed lineage.

## 10. Definition of done for the next Claude tranche

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

## 11. What not to do

- Do not restart this project from scratch.
- Do not commit directly to `main` or rewrite its history; branch from it and merge through a pull request with green CI.
- Do not continue work on the historical `codex/bootstrap-datapass-workbench` branch.
- Do not silently enable trusted Python.
- Do not eval/exec pipeline source.
- Do not claim SparkLab is a real Spark cluster.
- Do not claim Airflow simulation is real Airflow.
- Do not claim Fabric Lab is connected to Microsoft Fabric unless a future explicit connector is added.
- Do not make static dbt lineage look like a successful dbt run.
- Do not import whole donor repos into the production VSIX.
- Do not create competing app shells.

Read `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/HARVEST_AUDIT.md`, and this file before changing architecture.
