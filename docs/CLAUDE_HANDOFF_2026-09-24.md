# Claude handoff — Datapass Workbench VS Code

Date: 2026-09-24 (updated 2026-09-25)

## Current status — `main` is the baseline

PR #1 merged the implementation branch into `main` with a merge commit (`f35dbe4`, all 223 commits preserved). CI on `main` after the merge was green on all three jobs (run 36068237602). `codex/bootstrap-datapass-workbench` is kept for history only.

Workflow from here: branch from `main` for each tranche, keep CI green, merge through a pull request. The dated sections below record how the project got here; branch names and tips in them are historical.

**2026-09-25: stack merged, installed VSIX checked in VS Code.**

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

## 0. Packaged VSIX UI pass in the repository (roadmap T-3) — Claude, 2026-09-25 (newest)

The Playwright pass that earlier sessions ran from a scratch file is now `scripts/vscode_ui_pass.mjs` (`npm run test:ui`, after `npm run package`) and the CI job `vscode-ui` (Linux, `xvfb-run` with a 1600×1000 screen, screenshots uploaded as `vscode-ui-pass`). See docs/LOCAL_TEST.md, "Packaged VSIX UI pass".

- **Covers.** Fresh-profile VSIX install; Create .datapass project; Setup/Start runtime; raw 401/400 against the live port and no token in the log; Mosaic Run active SQL result; Practice Open solution + Submit graded; every module tab and lab sub-tab at a 520 px Workbench with an overflow probe; Stop runtime and a closed port; no uncaught webview errors.
- **Overflow probe.** Flags any element whose right edge passes the webview unless an ancestor scrolls or clips it; it must first catch a planted 2000 px block, so it cannot pass blind. First run: all 16 tab/sub-tab layouts clean at 521 px.
- **Gotchas.** Typing into Monaco through Electron did not reach the editor; the script writes the scratch file on disk and waits for the editor to show it. The first Practice Submit on an exercise without a starter only creates the file, so the pass clicks Open solution first. `locator.evaluate(fn, arg)` passes the element first. The exercise editor tab is titled `<exercise> · <language>`, not `solution.*`.

## 0. Runtime loopback authentication (audit D-2, D-9) — Claude, 2026-09-25

Audit finding: the runtime declared no middleware, so any local process or a DNS-rebinding web page could call it, including `POST /api/local/execute` with trusted Python on.

- **Token.** `RuntimeManager.start` generates a token per launch (`newRuntimeToken`, `src/platform/runtimeClient.ts`, 32 random bytes), keeps it in memory, and passes it with the port as `DATAPASS_RUNTIME_TOKEN` / `DATAPASS_RUNTIME_PORT` (`runtimeProcessEnv` drops inherited values). All HTTP helpers moved to `runtimeClient.ts` and send `X-Datapass-Token`; the class routes every call through `postJson` / `getJson`.
- **Runtime.** `runtime/datapass_runtime/auth.py` (pure ASGI middleware): Host must be `127.0.0.1:<port>` or `localhost:<port>` (400), token must match (401, `hmac.compare_digest`), no token or port configured → 503 on everything. Decision: `/api/health` is not exempt (the extension always has the token; the refusal leaks nothing).
- **Callers.** TestClient smokes use `scripts/runtime_test_auth.py` (`client_kwargs()`); the host E2E injects a hostile inherited `DATAPASS_RUNTIME_TOKEN`. The kernel worker drops `*TOKEN*` variables; dbt/dct terminals take the extension host's environment, so neither sees the token.
- **D-9.** `makeNonce` uses `crypto.randomBytes` (unbiased); the webview CSP `img-src` is `webview.cspSource data:` (no `https:`). The only webview image is the dct PNG render, inlined as a data URL.
- **Tests.** `scripts/runtime_auth_smoke.mjs` (client header on every helper, env, nonce, CSP); `runtime_smoke.py` (401 without/with a wrong token, 400 for a rebound or other-port Host, `localhost:<port>` accepted).

## 0. dbt Lab rebuild: real dbt Core, dbt Charts, missions — Claude, 2026-09-25

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

## Vague 1: Practice and Mosaic quick wins — Claude, 2026-09-25

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

## 0a. ZillaCode pack (`zilla-v1`) and the Snowflake SQL dialect — Claude, 2026-09-25

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

## 0b. Projects: end-to-end stories across the labs — Claude, 2026-09-25

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

## 0c. BI-2: dbt in the BI Lab (Datapass dbt emulation) — Claude, 2026-09-25

Branch `feature/bi-dbt`, stacked on `feature/bi-lab` (§0c). The user asked to continue with BI-2 (dbt in the BI
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

## 0d. BI Lab: data warehousing, SQL lineage and star models — Claude, 2026-09-25

Branch `feature/bi-lab`, stacked on `content/databricks-v1` (§0d). A new Workbench module **BI Lab** (id `bi`), the
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

## 0e. Cloud Lab Databricks (jobs, compute, Unity Catalog, MLflow) — Claude, 2026-09-25

Branch `feature/databricks-lab`, stacked on `feature/sqlpool-lab` (§0e). A **Databricks** tab in Cloud Lab: a simulated
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

## 0f. Cloud Lab SQL pool (Synapse dedicated SQL pool, Fabric Warehouse) — Claude, 2026-09-25

Branch `feature/sqlpool-lab`, stacked on `content/cloud-pipelines-v1` (§0f). A **SQL pool** tab in Cloud Lab and the `sqlpool-v1` Practice pack.

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

## 0g. Cloud Lab pipeline exercises — Claude, 2026-09-25

Branch `content/cloud-pipelines-v1`, stacked on `feature/factory-lab` (§0g). Guided Practice exercises on the Cloud Lab pipeline simulator.

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

## 0h. Cloud Lab pipelines (Factory Lab) — Claude, 2026-09-25

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

## 0i. Airflow lab simulator and exercise pack — Claude, 2026-09-25

Branch `content/airflow-lab-v1`. Airflow practice without Airflow, in the local runtime (no FastAPI Cloud, no separate service; `datapass-airflow-runner` stays empty).

- **Simulator** `runtime/airflowlab` (new package, shipped in the VSIX with the runtime): `parser.py` reads a real-looking Airflow DAG file through a whitelisted AST walk and never executes it (classic operators, sensors, TaskFlow `@task`/`@dag`, `>>`/lists/`chain`, `default_args`, timetables); unsupported syntax is rejected with a line number, including Airflow 2 arguments removed in Airflow 3. `schedule.py` creates runs with Airflow 3 timetables (CronTriggerTimetable by default, CronDataIntervalTimetable on request, catchup default False). `simulate.py` simulates task instances (Airflow's TriggerRuleDep rules, retries, execution_timeout, sensor poke/timeout/soft_fail, branch and short-circuit skipping, leaf-based run state). `templates.py` renders `{{ ds }}`-style fields without Jinja or eval. See its README for exactly what is and is not modeled.
- **Grading**: new exercise language `airflow`, runtime `datapass-airflow-sim-v1`, truth `simulated` (`datapass_runtime/airflow_grading.py`). Fixtures carry a `scenario` (scheduler clock, task behavior, outcome table) instead of input rows; the registry validates it. See `docs/EXERCISE_AUTHORING.md`.
- **Pack** `airflow-lab-v1` (13 exercises: 6 easy / 5 medium / 2 hard): fan-in/fan-out, TaskFlow data dependencies, catchup, no accidental backfill, weekday cron, data-interval timetable, `ds_add` under the Airflow 3 `@daily` default, retries, all_done cleanup, one_failed watcher, branch join, soft-fail sensor, `default_args` override. Expected rows computed by simulating the references, reviewed by hand; 32 mutants.
- **Extension**: `airflow` solutions open as `.py`; the brief says the file is parsed, never executed.
- **Airflow Lab panel on the same simulator** (branch `feature/airflow-lab-surface`, stacked on this one): `POST /api/local/airflow/simulate` (`airflowlab/lab.py`) takes the DAG file's TEXT and a scenario and returns the parsed DAG, runs (latest 40 simulated), task instances, timed events and rendered templates; parse errors carry a line, and a simulation error (e.g. a branch without a known choice) still returns the DAG. The panel simulates the active DAG `.py` (or `airflow/dags/retail_daily.py`, the new Python starter): scenario form (scheduler clock, unpause time, manual run, per-task outcome, duration, sensor arrival, branch choice), an Airflow-style grid of task states per run, the graph with state colors, Start/Step/End replay over the events, the task table, the log and rendered templates, and **Go to line** for parser errors. In the Lab, a sensor without a scenario setting sees its file on the first poke (grading keeps "never"). The webview simulator, the JSON spec validator and `main.dag.json` starter were removed; an existing `main.dag.json` only triggers a notice. Scenarios gained `manual_runs` (logical date = trigger time; CronDataIntervalTimetable infers the last complete interval) and events carry `state`/`try_number`. `SharedGraphCanvas` now lays out graphs left to right by dependency depth (Pipeline and dbt too; dragged positions still win) and colors nodes by an optional `status`.
- **Semantics checked against Airflow's code paths from memory, not against a live Airflow**: CronTriggerTimetable vs CronDataIntervalTimetable run creation, `_skip_to_latest`, TriggerRuleDep, sensor timeout after a false poke, `try_number <= retries`. A real-Airflow oracle (like the Spark one in `fastapispark` PR #1) would be the way to verify them.

Checked: `npm run compile`; `npm test` (airflow brief, package boundary); `pip install ./runtime`; compileall; `runtime_smoke.py` (parser rejections, both timetables, catchup, a trigger-rule table, retries, sensor timeout, templates); `exercise_packs_smoke.py` → 186 references pass, 186 starters and 220 mutants rejected; `npm run test:host` (branch-join reference passes, starter fails, `import os` rejected). Not re-checked in a real F5 session.

## 0j. Spark lab pack and simulated plan checks — Claude, 2026-09-25

Merged as PR #7 (`58baba9`). Branch `content/spark-lab-v1`. Targeted Spark practice on the existing bounded SparkLab (no new engine, nothing distributed).

- **Exchange model** (`runtime/sparklab/physical.py`, `plan-driven-v2`): shuffle exchanges now follow Spark's planning rules (satisfied clustering reuses an existing hash partitioning, broadcast joins keep the streamed side's partitioning, broadcasts above 8 GB are refused, EliminateSorts under joins and MIN/MAX/COUNT aggregates). Before, every wide operator counted a shuffle, so two windows on the same key or a join on an aggregated key were overcounted. `metrics.plan_facts` exposes exchanges with reasons; the SparkLab panel shows the count. Also fixed: a join whose right DataFrame contained a window was misread as a window (`.sql` of the DataFrame was scanned).
- **Plan checks**: an exercise may declare `spark_plan` (profile, AQE, authored `scale` per table, rules `max_exchanges`, `min_broadcast_joins`, `max_shuffle_joins`, `max_global_windows`, `max_output_partitions`). `exercises.grade` passes the scale to the simulation, grades the checks once on the first successful run and returns them as `kind: "plan"` checks (visible, on Run visible and Submit). The registry rejects plan checks on non-SparkLab exercises, unknown tables or profiles, and ids that clash with fixtures. See `docs/EXERCISE_AUTHORING.md`.
- **Pack** `spark-lab-v1` (12 exercises, 4 easy / 5 medium / 3 hard): 7 result lessons (left-join filter placement, semi join, `count(col)`, `eqNullSafe`, full outer reconcile, join fan-out, RANGE vs ROWS ties) and 5 plan lessons (`coalesce` vs `repartition`, one-pass aggregation, broadcast above the threshold, random repartition before a window, window instead of self-join). The starters are the buggy code; plan-lesson starters return the right rows and fail only the plan (`PLAN_ONLY_STARTERS` in the pack gate enforces this). Expected rows computed by running the references, reviewed by hand.
- **Extension**: Practice cards list the plan requirements; plan results are labeled "simulated plan"; the exercise brief shows the authored sizes and checks.

Checked: `npm run compile`; `npm test` (brief and SparkLab view assertions); `pip install ./runtime`; compileall; `runtime_smoke.py` (new exchange-model assertions); `exercise_packs_smoke.py` → 185 references pass, 185 starters and 204 mutants rejected; `npm run test:host` (Spark lab grading step: broadcast reference passes, starter fails only on the plan, Run visible grades plan checks). Not re-checked in a real F5 session.

Related repositories reviewed on 2026-09-25 (on disk under `D:\PROJ`): `fastapispark` is an earlier stand-alone fake-Spark FastAPI service (regex parser, one DuckDB query); SparkLab here supersedes it. Its open PR #1 adds an optional real-Spark oracle on GitHub Actions (learner code runs on public runners with a server token), not integrated. `datapass-airflow-runner` is empty. `fastapi-fabric` is a v0.1 Data Factory pipeline simulator (in-memory; only `Succeeded` dependency conditions are honored). Decision with the user: the VS Code Workbench is the product; no FastAPI Cloud or web backend. Promote useful ideas into this runtime (next candidates: an Airflow simulator in the Python runtime with graded exercises; a Data Factory pipeline mode in Fabric Lab).

## 0k. Data-engineering patterns pack — Claude, 2026-09-25

Merged as PR #6 (`63e5f0b`). Branch `content/more-exercises`. New pack `content/exercise-packs/de-patterns-v1` (16 authored DuckDB SQL exercises, 5 easy / 8 medium / 3 hard). It fills the gap between `sql-lab-v1` (joins/grouping/windows) and real pipeline work: typing text columns after Mosaic **Import CSV**, latest-per-key CDC dedup with a tie-breaker, the `NOT IN` NULL trap, gaps and islands, 30-minute sessionization, `ASOF LEFT JOIN`, SCD2 validity ranges with `LEAD`, full-row upsert results, a UNION ALL data-quality rule report, a `generate_series` calendar spine, a user-level funnel, `MEDIAN`, monthly cohorts, `string_split`/`UNNEST` tag normalisation, strict `>` watermarks, and `COUNT(*) FILTER` vs the `COUNT(boolean)` trap.

Every exercise has a visible, a hidden and an edge fixture designed around its pitfall, a runnable starter that fails, and 1-3 mutants (34 in total). Expected rows were computed by running the reference over the grader's own typed fixture CTEs, then reviewed by hand. Gate: `exercise_packs_smoke.py` → 173 references pass, 173 starters and 188 mutants rejected; `de-patterns-v1` joined `RUNNABLE_STARTER_PACKS`. The host E2E grades `de-not-in-null-trap` from the extension catalog (the reference passes; `NOT IN` fails only on the guest-order fixture).

## 0l. Mosaic CSV import — Claude, 2026-09-25

Merged as PR #4 (`aeb7aef`).

Branch `feature/mosaic-import-csv`. Gives learners a way to load their own data besides the retail demo, using the existing `import_csv` kernel op.

- **Runtime**: `POST /api/local/import-csv` `{asset, text}`. Pydantic allows only `bronze.<ident>` and text up to 1,000,000 chars, and forbids extra fields (no `path`). `local_data.parse_csv` still enforces 1 MB UTF-8 bytes, 5,000 rows, 1-40 unique simple headers, and equal field counts. An existing table → 400 "already exists"; imports never overwrite. Every column is `VARCHAR`. `/api/capabilities → mosaic.csv_import` states these rules.
- **Extension**: **Import CSV…** in Mosaic's *Local data runtime* block (enabled only while the runtime runs). The host opens a file picker, reads the file, decodes it strictly as UTF-8 (`src/platform/csvImport.ts`: size, encoding, empty-file checks), and suggests a free `bronze.<name>` from the file name, validated live against the catalog. It then sends the TEXT, not the path. The result is `RuntimeViewState.csvImport`, shown as a preview with the rows, "every column is text" and a CAST hint; a later SQL/Python run replaces it. FastAPI `detail` is surfaced as "CSV import refused: …".
- **Truth**: real local DuckDB import; no type inference is claimed.

Checked: `npm run compile`; `npm test` (new `csv_import_smoke.mjs`); `runtime_smoke.py` (new TestClient block: import, catalog, duplicate/non-bronze/injection-name/malformed/over-limit/extra-`path` refusals, CAST query); compileall; pack smoke; `npm run test:host` (new step, 17/17); browser harness render of the preview and the button → `importCsv` message. Not re-checked in a real F5 session (the native file picker and input box are only exercised through the host classes).

## 0m. Polish tranche — Claude, 2026-09-25

Merged as PR #3 (`603babd`). Branch `polish/setup-progress-and-lockfile`. Closes the three "known, not fixed" items from the F5 pass below and the lockfile decision.

- **Setup runtime progress**: `RuntimeEnvironmentView.progress` carries step (1 venv, 2 pip install, 3 engine import check), the latest recognised pip line (`describeSetupOutputLine` in `src/platform/runtimeEnvironment.ts`, throttled to one webview update per 400 ms) and the start time. The Local runtime card shows it with an indeterminate bar and a ticking elapsed time (pip reports no overall percentage, so no fake percentage is shown); a VS Code notification mirrors it. The Output channel is no longer forced open; **Show setup log** opens it, also after a failed setup.
- **Minimap theme**: `--xy-minimap-*` variables are mapped to VS Code theme colors in `workbench.css`.
- **Pipeline header**: shows the compiler truth in words (`Source: compiled, never executed`), a per-activity count (`3 run locally · 1 declared only`), and marks the schedule as metadata only. The runtime contract (`truth: compiled_design_only`) is unchanged.
- **Lockfile**: `package-lock.json` is committed; CI uses `npm ci` with the npm cache.

Checked: `npm run compile`, `npm test` (new parser assertions in `runtime_environment_smoke.mjs`), the Python gates, and the built webview in a browser harness with a stubbed VS Code API (setup-progress card, pipeline header, minimap computed colors in a dark theme). Not re-checked in a real F5 session.

## 0n. Manual F5 pass — Claude, 2026-09-25

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

Known, not fixed at the time (all three addressed in §0l): first **Setup runtime** took ~15 min on this Windows machine (pip unpacking under antivirus); only the output channel shows progress. React Flow minimap is light in dark theme. Pipeline header shows the compiler's `compiled_design_only` truth next to executable activities.

The driver lives outside the repo (Playwright over CDP); if you repeat it, launch Code with `--folder-uri`, `--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows`, and `window.dialogStyle: custom`, and use DOM clicks inside webviews.

## 0o. Content tranche — Claude, 2026-09-24

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
3. ~~A Mosaic "Import CSV into catalog" action~~ Done (§0k).
4. If wiring Pipeline dbt later: extend the trusted-local opt-in to dbt, validate the project path against the manifest `assets.dbt`, reuse `dbt_runner` artifact validation, never report success without a qualified manifest/run_results pair.
5. ~~`package-lock.json` is not committed~~ Done: the lockfile is committed and CI uses `npm ci` (§0l).

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

Later tranches added the work recorded in §0b; all of it is now on `main`.

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

Rebuilt on 2026-09-25 as the real-life lab (see §0): managed dbt Core + dbt-duckdb + dbt Charts installed on
request, real commands typed in a VS Code terminal, the catalog handoff, the artifacts view, dbt Charts boards and
the missions. No static lineage and no emulation here (the emulation is the BI Lab's dbt tab).

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
4. For user-facing changes, repeat the manual F5 pass (see §0m) before merging.

Status after the 2026-09-24 Claude tranches: P1 trusted Python — done; P1 SparkLab — done; P1 E2E — done (`npm run test:host`); P2 pipeline dbt — decided: explicitly unsupported; P2 Mosaic durability — done; P2 content — donor Practice content promoted: `sql-lab-v1` (60), `engine-lab-v1` (68 variants), `python-lab-v1` (12); non-gradable donor tracks intentionally left to reference material. Manual F5 pass done on 2026-09-25 and PR #1 merged to `main`. Remaining: the known limitations listed in §0b and further content.

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

- wire it to real dbt Core the way the dbt Lab runs it (managed tools, generated profile, catalog handoff), or
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
12. dbt Lab: Install dbt tools, run dbt build from the lab (terminal), see the artifacts and the Catalog view, render a board, check a mission.

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
- Do not present the BI Lab's dbt emulation as dbt Core, or anything but a real `dct` output as dbt Charts.
- Do not import whole donor repos into the production VSIX.
- Do not create competing app shells.

Read `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/HARVEST_AUDIT.md`, and this file before changing architecture.
