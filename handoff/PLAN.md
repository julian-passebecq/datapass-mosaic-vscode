# PLAN — mosaic (Datapass Workbench, `D:\PROJ\datapass-mosaic-vscode`)

Kept by `ARCHI mosaic N` (docs/roles/archi.md in claude-control). Lean on purpose: one screen per version. Estimates
are orders of magnitude; fill **Actual** when a package merges (GALAXY Contrôle compares them every week).

Updated: 2026-09-26 15:30 by ARCHI mosaic 1 · Sources: the roadmap artifact
(https://claude.ai/artifact/RhQMPGxeuNo9GTFzH5B8aJ), docs/HANDOFF.md, merged PRs #27–#57. The old
`docs/CLAUDE_HANDOFF_2026-09-24.md` no longer exists (split into HANDOFF.md / HANDOFF_HISTORY.md by T-5).

Already done (do not redo): V1-1…V1-7, V2-1 (arena, review, interview), V2-2 (dialects), V2-3 (zilla-v1), V3-1
(Terminal Lab), V3-2 first slice (Infra Lab), T-3 (VSIX UI pass), T-5 (short handoff), D-1, D-2, D-5, D-6 (per-lab
split), D-9, D-11, Polars engine in SparkLab (#54), dbt snapshot/contract missions (#55), Airflow depends_on_past
(#56), Spark SQL track (#57).

## Versions

| Version | Goal (one line) | Useful? | Status |
|---|---|---|---|
| V1 | Two new "real work" labs (lakehouse storage, API ingestion), a home page that scales past 11 modules, Infra Lab depth, a faster CI | yes: lakehouse partitioning is Julian's declared weak point, API ingestion is half the job and nothing covers it, 11 tabs no longer fit | done (PRs #59–#63) |
| V2 | BI-3 (KPIs, DAX-like measures to SQL, dbt Charts boards), governance (RLS/CLS, masks, PII), concept quizzes + reference sheets (V2-4), pytest-graded production Python (V2-5), VS Code native bits (T-4, D-10 JSON schemas), Cloud Lab dbt layer, PostgreSQL Practice content, versioning + changelog (T-6) | yes, after V1 | later |
| V2+ | Iceberg in the lakehouse lab (pyiceberg or DuckDB's iceberg extension), richer Delta if B only got reads | yes, once the app is stable (Julian: minimal version first) | later |
| V3 | Streaming lab (V3-7), a formal lab template (T-2) | no for now: streaming is off-profile (Azure batch); D-6 already gave most of T-2's gain | parked |

## Packages (V1)

Packages that run at the same time own disjoint files. Shared, append-only files every package may touch with a
small hunk (resolve by keeping both sides on rebase): `docs/HANDOFF.md`, `docs/HANDOFF_HISTORY.md` (new dated
section at the top), `src/test/hostSuite.ts`, `runtime/datapass_runtime/main.py` (route registration only),
`src/labs/controllers.ts`, `src/labs/clients.ts`, `src/webview/contracts/index.ts`, `package.json` (commands),
`scripts/vscode_ui_pass.mjs`, `CLAUDE.md` (one truth-model bullet per new lab).

| Id | Package | Size | Estimate (h · M tokens) | Model · effort | Owned files | Acceptance tests | Coder | Status | Actual (h · M tokens) |
|---|---|---|---|---|---|---|---|---|---|
| A | **T-1 Home and navigation by families**: a "Today" home (progress from `.datapass/progress.json`, next suggested step, runtime state), labs grouped in two families ("Learn", "Real work") instead of one flat tab bar; every module still reachable by its `datapass.open…` command | M | 2–4 h · 40–90 | Opus 5.5 · medium | `src/webview/WorkbenchApp.tsx` (nav shell), new `src/webview/HomeSurface.tsx`, `src/labs/workbench/`, `src/webview/contracts/workbench.ts`, `src/modules.ts`, `content/modules.json`, `src/webview/workbench.css` | `npm run compile`, `npm test`; `npm run package && npm run test:ui` passes with every module reached through the new nav at 520 px, no overflow | TAMPON 2 | merged #60 | 1.5 h · 0.25 |
| B | **V3-3 Lakehouse storage lab**: Parquet + Hive partitions, small-files problem and compaction, DuckLake (snapshots, time travel, schema evolution, MERGE-style upserts); the same task in Polars, DuckDB SQL and SparkLab; Delta too if DuckDB gives it cheaply (its `delta` extension or DuckLake, no delta-rs; 15-min check by the coder, read-only Delta if writes are missing); Iceberg later, once the app is stable (Julian, 2026-09-26: minimal version first, no new dependency); missions or a Practice pack checked on the files and the catalog | M–L | 3–5 h · 80–160 | Opus 5.5 · medium | new `runtime/lakehouselab/`, `src/labs/lakehouse/`, `src/webview/contracts/lakehouse.ts`, `src/webview/LakehouseSurface.tsx`, its content pack, its smoke script | all CLAUDE.md gates + a new `scripts/lakehouse_smoke.py` (references pass, starters and mutants fail); truth labels real/emulated shown | TAMPON 3 | merged #62 | 3.5 h · 0.4 |
| C | **V3-4 API ingestion lab**: a simulated REST API served on 127.0.0.1 on its own port with a fictitious per-mission key (Julian, 2026-09-26), never the runtime token; pagination, incremental load, rate limit, schema drift, transient errors; ingested into bronze by the learner's real Python (requests/httpx, trusted Python only); checks on the catalog and the API's request log | L | 4–7 h · 100–200 | Opus 5.5 · high | new `runtime/apilab/`, `src/labs/apilab/`, `src/webview/contracts/apilab.ts`, `src/webview/ApiLabSurface.tsx`, its missions or pack, its smoke script | all gates + `scripts/api_lab_smoke.py` (references pass, naive solutions that ignore pagination / rate limit / drift fail); token rule of CLAUDE.md intact | TAMPON 4 | merged #63 | 2.3 h · 0.4 |
| D | **Infra Lab depth**: one or two more missions per simulator; Terraform modules (local `module` blocks) and `fmt`; Kubernetes Ingress, HPA, namespaces; compose volumes and networks | M–L | 4–6 h · 80–160 | Opus 5.5 · medium | `runtime/infralab/`, `runtime/missionlab/infra.py`, `content/missions/infra-v1/`, `scripts/infra_missions_smoke.py`, `scripts/infra_lab_smoke.mjs`, `src/labs/infra/`, `src/webview/InfraSurface.tsx` | `python scripts/infra_missions_smoke.py` (every reference passes, untouched fixtures, starters and mutants fail), `npm test`, runtime smoke | TAMPON 5 | merged #61 | 3.5 h · ~25 (coder estimate, context peak 0.5) |
| E | **Debt: D-3, D-4, D-7**: delete `packages/` and the caller-less `/api/local/capabilities` and `/api/local/restart` if still unused; one dbt project reader (drop the regex reader in `src/dbtState.ts` if the real dbt Lab no longer needs it, else document why); CI: pip/uv cache, single build in the extension job, `concurrency` cancel-in-progress, parallel pack grading in `exercise_packs_smoke.py` with identical counts | M | 2–3 h · 40–80 | Opus 5.5 · medium | `.github/workflows/ci.yml`, `scripts/exercise_packs_smoke.py`, `packages/`, `src/dbtState.ts`, `runtime/datapass_runtime/main.py` (the two routes only) | the 4 CI jobs green; packs smoke reports the same counts (584 / 584 / 549 + spark-sql-v1's); runtime job at least 30 % faster than the last 5 runs on main (quote the numbers in the PR) | TAMPON 6 | merged #59 | 0.8 h · 0.09 |

Size guide: **S** < 1 h, one area · **M** 1–3 h, a few files · **L** > 3 h or hard (effort high, or split it).

## Packages (V2)

Julian, 2026-09-26: light packages first (H, I, J: all merged, version 0.2.0 ready to tag); F and G after, paused on 2026-09-26 while Julian tests 0.2.0 (resume with his feedback).

Follow-ups noted by coders: select the managed venv as the Python interpreter for API Lab missions (Pylance flags `httpx` otherwise); a docs/LOCAL_TEST.md line on API Lab smokes needing a venv (a user-site runtime fails locally); the walkthrough page not yet looked at by hand; a separate `missions` CI job (branch protection is Julian's).

| Id | Package | Size | Estimate (h · M tokens) | Model · effort | Owned files | Coder | Status |
|---|---|---|---|---|---|---|---|
| F | **BI-3**: KPIs, a DAX-like measure layer translated to SQL (static, labelled), dbt Charts boards real in the dbt Lab and a labelled preview in the BI Lab | L | 4–6 h · 0.3–0.6 | Opus 5.5 · high | `runtime/bilab/`, `src/labs/bi/`, `src/webview/BiSurface.tsx`, `content/exercise-packs/dwh-v1/` | — | later |
| G | **Governance** (V3-6): row/column security (Fabric, Synapse), Databricks row filters and column masks under Unity Catalog, PII tagging, dbt model contracts; missions checked on the catalog | M–L | 3–5 h · 0.3–0.5 | Opus 5.5 · medium | `runtime/sqlpoollab/` security part, `runtime/databrickslab/` UC part, new missions | — | later |
| H | **Concept quizzes + reference sheets** (V2-4) and **pytest-graded production Python** (V2-5) in Practice | M | 2–4 h · 0.2–0.4 | Opus 5.5 · medium | `runtime/datapass_runtime/exercises.py` grading kinds, new packs, `src/labs/practice/` | TAMPON 7 | merged #67 · 1.75 h · ~25 M (coder estimate) |
| I | **VS Code native** (T-4 + D-10): JSON schemas for `.datapass/project.json` and `bi/model.json`, CodeLens Run visible / Submit on solution files, runtime state in the status bar, a Walkthrough; Pylance `__builtins__.pyi` for API Lab `ingest.py` | M | 2–3 h · 0.2–0.3 | Opus 5.5 · medium | `package.json` contributes, new `schemas/`, `src/platform/` codelens/status | TAMPON 2 | merged #66 · 1.5 h · 0.2 M |
| J | **Versions and changelog** (T-6): version bump, CHANGELOG, a release workflow attaching the VSIX (publishing a release waits for Julian) | S | < 1 h · 0.05 | Opus 5.5 · medium | `CHANGELOG.md`, `.github/workflows/release.yml`, `package.json` version | TAMPON 6 | merged #65 · 0.6 h · 0.04 M |

F, G, H, I, J own disjoint files and can run in parallel. V2+ (Iceberg) and V3 stay parked.

## Merge order

E and D merge as soon as they are green (they own disjoint files). A merges next; then it tells B and C "T-1 merged:
rebase and register your module in the new navigation". C and B merge in the order they finish, each rebased on main
first. Every coder rebases on main right before merging and reruns the gates its rebase touched.

## Escalations and decisions

| Date | Package | What happened | Re-run at / consult | Result |
|---|---|---|---|---|
| 2026-09-26 | E | finished in 0.8 h (estimate 2–3 h); runtime CI job 452 s → 135 s | — | merged #59 |
| 2026-09-26 | B | Delta check: DuckDB delta extension reads, time-travels and appends but cannot create, so the mission ships its `_delta_log` | — | merged #62 |
| 2026-09-26 | B | Julian chose Parquet + DuckLake only: package shrinks from L/high to M–L/medium | medium | |

xhigh consult briefs: `handoff/briefs/<date>-<topic>.md` (question, options, files to read, then "## Decision").

## Open questions for Julian

None open. Answered 2026-09-26: B uses Parquet + DuckLake, plus Delta through DuckDB if cheap (no deltalake / pyiceberg); C serves the simulated API
on its own loopback port with a fictitious key.
