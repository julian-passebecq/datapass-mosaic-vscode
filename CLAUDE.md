# CLAUDE.md — Datapass Workbench

This repository is the authoritative implementation target for the Datapass Workbench VS Code extension.

## Product boundary

Do not turn this repository into another standalone IDE or browser notebook.

VS Code owns:

- source editing and tabs;
- Explorer/files;
- terminals;
- Git;
- Microsoft Python/Jupyter integration.

Datapass owns:

- Mosaic workspace composition;
- Practice/exercise UX and grading;
- Fabric-inspired local learning UX;
- bounded SparkLab/ZilaCode semantics;
- dbt learning/lineage integration;
- Airflow scheduling simulation;
- Pipeline Lab design/execution UX;
- the single local FastAPI control plane.

The standalone Datapass WorkNotebook and Contoso Data Studio are separate products. Historical code under `workbench-core/`, `migration-sources/`, and `legacy-donors/` is donor/reference material, not a second runtime.

## Non-negotiable truth model

Never blur real execution and simulation.

- Mosaic SQL: real local DuckDB execution.
- Mosaic Python/Polars: real local execution only when explicitly trusted local Python is enabled.
- Practice: native VS Code solution files with real local grading through the shared runtime.
- Fabric Lab: Fabric-inspired UX; local DuckDB/DuckLake and selected real-local operations; no implicit Microsoft Fabric connection.
- SparkLab/ZilaCode: bounded PySpark-style semantics; distributed Spark behavior and telemetry are simulated/teaching data.
- dbt Lab: prefer real dbt Core + dbt-duckdb; static lineage is a fallback, not execution.
- Airflow Lab: deterministic scheduling simulator; it is not an Airflow scheduler/executor.
- Pipeline Lab: the Python-like pipeline source is parsed by a bounded AST compiler and is NEVER eval/exec'd. Supported activity bodies may execute locally. Scheduling remains metadata/simulation.

## Security boundaries

- Never eval/exec Pipeline Lab source.
- Never silently enable arbitrary Python execution.
- The local Python worker is process-isolated for lifecycle reasons; it is NOT a security sandbox.
- Trusted Python/Polars must remain an explicit user choice.
- Do not add cloud credentials, tokens, secrets, or copied local environment state.
- Preserve CSP/nonce-protected webviews.
- Keep runtime requests loopback/local by default.

## Architecture constraints

Prefer one implementation of each capability:

- one FastAPI local runtime;
- one shared local data catalog;
- one bounded SparkLab runtime;
- one shared React Flow graph foundation;
- one project manifest at `.datapass/project.json`;
- native VS Code files instead of embedded Monaco/editor clones.

Do not copy whole historical applications into the extension. Promote only proven contracts, content, runtime mechanics, or UI components.

## Required quality gates

Before declaring a change complete:

```bash
npm install --no-audit --no-fund
npm run compile
npm test
python -m pip install ./runtime
python -m compileall -q runtime/datapass_runtime runtime/sparklab
python scripts/runtime_smoke.py
npm run test:host   # with DATAPASS_E2E_PYTHON set; see docs/LOCAL_TEST.md
```

Also manually inspect the Extension Development Host for user-facing changes when possible.

## Current continuation point

Read `docs/CLAUDE_HANDOFF_2026-09-24.md` before making substantial changes. It records the current branch, implemented execution bridge, known gaps, and prioritized continuation plan.
