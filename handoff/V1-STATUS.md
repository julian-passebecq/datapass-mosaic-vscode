# mosaic (Datapass Workbench) — V1 status

Written 2026-09-26 by ARCHI mosaic 1 when mosaic was **paused** (Julian's decision: the budget goes to DataPass).
Keeper while paused: ASSISTANT ARCHI mosaic 1 (TAMPON 26). The plan and actuals are in handoff/PLAN.md; the current
product state is docs/HANDOFF.md; the per-tranche history is docs/HANDOFF_HISTORY.md.

## Where the V1 launch stands

- **The plan's V1 is done and released**: `main` is green on the 4 required CI jobs, and **v0.2.0** is published as a
  GitHub Release with its VSIX (https://github.com/julian-passebecq/datapass-mosaic-vscode/releases/tag/v0.2.0),
  also installed in Julian's VS Code.
- `main` after v0.2.0 also has **governance (#69)**, listed under `[Unreleased]` in CHANGELOG.md: the next tag
  (0.2.1 or 0.3.0) will carry it.
- Nothing is running: no open pull request, no coder busy, and no feature branch left besides `main` and the
  historical `codex/bootstrap-datapass-workbench` (kept on purpose, CLAUDE.md).
- Ready for a "V1 launch" in the sense of a usable local release. Not done: a Marketplace publication (never
  decided, roadmap "Décisions"), and a hand test by Julian of the new screens.

## Features developed (one line each)

Before this plan (PRs #1–#57, 24–26 Sept): Workbench with Mosaic (DuckDB SQL, profile, import, EXPLAIN, history,
SQL dialect picker), Practice arena (one card per problem, language switch, feedback diff, hints, spaced review,
interview mode), Projects (3 end-to-end stories verified on the workspace), Cloud Lab (Fabric/ADF/Synapse
pipelines, SQL pool, Databricks), BI Lab, SparkLab (+ Polars engine #54), Airflow Lab (+ depends_on_past #56),
Pipeline Lab, real dbt Lab with missions (+ snapshots and contracts #55), Terminal Lab (#35, #37), Infra Lab first
slice (#50, #52), SQL dialects (#38, #39, #41, #42), zilla-v1 (#27), Spark SQL track (#57), runtime token and CSP
hardening (#36), VSIX UI pass in CI (#40), per-lab split of the host code (#53).

This plan, V1 (all merged 26 Sept):
- **A · Today home and navigation by families** ("Learn" / "Real work"; labs register in `content/modules.json`) — #60.
- **B · Lakehouse storage lab**: Parquet partitions, pruning, compaction, DuckLake time travel / schema evolution /
  MERGE, Delta through DuckDB's `delta` extension (read, time travel, append; no create); 7 missions — #62.
- **C · API ingestion lab**: simulated REST API on its own loopback port with a fictitious key, learner's real Python
  (trusted only); pagination, incremental, 429, drift, retries; 5 missions — #63.
- **D · Infra Lab depth**: Terraform local modules and `fmt -check`, Kubernetes Ingress / HPA / namespaces, compose
  volumes and networks; infra-v1 from 4 to 8 missions — #61.
- **E · CI and debt**: uv cache, one build, cancel-in-progress, parallel pack grading (runtime job 452 s → 135 s);
  dead `packages/` and routes removed — #59.

V2, light packages (merged 26 Sept):
- **J · Versions**: 0.2.0, CHANGELOG.md, release workflow on `v*` tags, docs/RELEASE.md — #65.
- **I · VS Code native**: JSON schemas (project, star model, missions, packs; generated from pydantic, checked in CI),
  CodeLens Run visible / Submit / Check mission, runtime status bar, walkthrough, API Lab Pylance stub — #66.
- **H · Practice**: concept checks (`concepts-v1`, 24 cards, 5 reference sheets) and pytest-graded production Python
  (`python-prod-v1`, 8 exercises, trusted Python only) — #67.
- **G · Governance**: SQL pool RLS, column GRANT/DENY, dynamic data masking, EXECUTE AS; Unity Catalog row filters,
  column masks, tags; pack `governance-v1` (5 exercises) — #69.

Practice totals after #69: 638 reference solutions pass, 638 starters and 643 mutants rejected.

## What is missing (packages for later)

| Id | Package | Size | Effort | Note |
|---|---|---|---|---|
| F | **BI-3**: KPIs, DAX-like measure layer translated to SQL, dbt Charts boards (real in dbt Lab, labelled preview in BI Lab) | L | high | held for budget (Julian: "F later") |
| K | **Release 0.3.0** with governance + whatever ships next (tag push, release workflow) | S | low | automatic, no Julian action |
| L | **Follow-ups**: select the managed venv as interpreter for API Lab missions (Pylance flags `httpx`); docs/LOCAL_TEST.md line on smokes needing a venv; look at the walkthrough page; local flakes (test:host HTTP 500s, trusted-Python UI steps) that CI does not show | S–M | medium | |
| M | **CI**: split the dbt missions smoke into a 5th `missions` job (extension-host is now ~6–8 min) | S | medium | needs Julian to add it to required checks |
| N | **Iceberg** in the lakehouse lab (pyiceberg or DuckDB's iceberg extension), Delta table creation | M | medium | V2+, after the app is stable (Julian: minimal first) |
| O | Cloud Lab dbt layer (Databricks `dbt_task`, Fabric dbt job), PostgreSQL Practice content, Infra Lab gaps (registry modules, StatefulSets/PVCs, TLS, memory HPA), governance limits (write security, views, ABAC) | M each | medium | from docs/HANDOFF.md "Known gaps" |
| P | Streaming lab (V3-7), lab template (T-2) | L | — | parked |

## Blockers and Julian's pending items

- No blocker. mosaic is paused by decision, not stuck.
- Julian (C:\Users\julia\.claude\effort-board\todo.md): require the 4 CI jobs on `main` in branch protection
  (GitHub → Settings → Branches), optionally a 5th `missions` job; allow auto-merge on the repo (optional).
- Minor choices the coders made are in effort-board/questions.md (lines dated 2026-09-26 · mosaic).
