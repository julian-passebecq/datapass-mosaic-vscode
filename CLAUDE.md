# Datapass Workbench (datapass-mosaic-vscode)

A local VS Code practice space for data engineering: Mosaic, Practice exercises, Projects and the labs (Cloud, dbt, Terminal, Infra, API, BI, Lakehouse, Airflow, Pipeline), served by one local FastAPI runtime in `runtime/`. VS Code keeps editing, files, terminals, Git and Python/Jupyter. `docs/HANDOFF.md` is the current state; `docs/TRUTH-MODEL.md` says what each lab really runs and what it simulates, the security boundaries and the full gate list.

## Build and test
- `npm run compile` and `npm test`, then the runtime smokes in `docs/TRUTH-MODEL.md` (Required quality gates) for the labs you touched. `npm run test:host` and `npm run package && npm run test:ui` drive a real VS Code (`docs/LOCAL_TEST.md`).
- CI: GitHub workflow `ci.yml` only, and GitHub Actions do not run here; the GitLab project `juliandatapass-group/datapass-mosaic-vscode` has no CI file. Run the gates yourself and quote them.

## Guidelines
- Never blur real execution and simulation: every result says which it is, because learners trust what the lab tells them.
- Never eval or exec Pipeline Lab source, Airflow DAG files, Cloud Lab notebooks or Infra Lab files; the Terminal Lab checker only reads files and Git state.
- Trusted local Python stays an explicit user choice, and the worker process is not a security sandbox.
- Runtime requests stay on loopback and carry the per-launch token; it is never stored or logged.
- No cloud credentials, tokens or copied local environment state; keep the CSP-protected webviews.
- One implementation per capability (one runtime, one catalog, one SQL dialect translator). `workbench-core/`, `migration-sources/` and `legacy-donors/` are donor material, not a second runtime.
- Add a dated section at the top of `docs/HANDOFF_HISTORY.md` for each tranche.

How work flows: the fleet guideline every session loads (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`). CI recipe and runners: datapass-fleet-facade `AGENTS.md`.
