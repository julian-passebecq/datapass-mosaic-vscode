# OUTCOME · Mosaic VSIX V1 finish (2026-10-12 → 13)

## Delivered (local branch `codex/mosaic-vsix-v1-finish-20261011`)
- **Regression root cause.** PR #74's red `runtime` and `extension-host` jobs came from main itself.
  - sqlglot 30.20+ removed `qualify(infer_schema=…)`. The TypeError was swallowed in `sqldialects/core.py::_annotate`,
    so every column lost its type, and T-SQL AVG and division were refused or mistyped.
  - Fixed without changing semantics. Verified on sqlglot 30.19 and 30.22.
- **PR #72 recovered** (Learning workspace: 6 paths, 19 lessons). PR #74's only extra commit, a CI workflow file, was
  not taken.
- **Learning (P1, P2, S1):**
  - 13 paths and 59 lessons.
  - Lessons link concept checks, extra practice, missions, a cheatsheet and a flashcard deck.
  - Four separate progress levels: read (self-reported), concept check, ran locally (not graded), Practice passed.
  - Self-rated flashcard review on Leitner intervals: 11 decks, 420 cards.
  - 21 one-page cheatsheets.
  - Practice pack `learning-checks-v1` (72 concept checks), graded by the existing grader.
- **Build (P3):**
  - Blank workspace (`catalog.seed: "none"`).
  - New File and Import Dataset never overwrite.
  - Mosaic empty state.
  - The `datapass.mosaic-exchange` v1 contract with Mosaic Studio (schema, docs/MOSAIC_EXCHANGE.md, import never runs
    anything, WASM runs labelled as such).
- **Pipeline authoring (P4):**
  - Canvas editing of Fabric, ADF and Synapse pipelines, with a palette per product, conditions, container levels, a
    properties panel, validation and undo/redo.
  - Source-preserving saves with a conflict check; import and export.
  - Runs on the existing simulation.
- **Infra ladder (P5):** 5 intro missions (13 in total) in ladder order, plus `infra-concepts-v1` (17 observability,
  PromQL, Grafana and SLO concept checks). Simulation only.
- **Acceptance:** `scripts/ui-suite/v1_acceptance.mjs`, 10 steps on the installed VSIX, run by `npm run test:ui`.
- **Version and docs:**
  - Version 0.4.0, untagged; CHANGELOG.
  - New handoff docs: features.csv, ux.csv, ACCESS_MATRIX, EVIDENCE, START, READY.
  - docs/HANDOFF.md and HANDOFF_HISTORY updated.

## Product fixes found by qualification
- New Blank Workspace opened Mosaic only after its notification was dismissed. It now opens Mosaic first (with a test).
- `handoff/` planning docs were shipped inside the VSIX. They are now excluded, and package_smoke guards it.

## Interoperability boundary
Mosaic Studio (`datapass-mosaicstudio`) was not touched. The exchange is file-based and versioned. DuckDB-WASM and
native DuckDB never share a database; imported cells are never executed.

## After V1 (2026-10-13)
- #78: Mosaic Studio's real interchange, `.ipynb` with `metadata.datapass`, imported and exported (never executed),
  round trip checked against Studio 4623b04's own `notebook_io.py`.
- #79: BI Lab UI test race fixed (test only).
- Delivered: VSIX 0.4.0 from main 44e8007 into the private galaxy-release-vault (see READY.md).

## Remaining
See handoff/READY.md "Open". F08 (real local Docker data journey): EXCLUDED_V1 by owner decision (Julian, 14 Oct 2026). Infra Lab stays
simulated in V1. A real Docker mode, optional and enabled only when Docker is detected, is a later idea
(handoff/ROADMAP.md). The original ChatGPT acceptance text was not recovered (NOT_RECOVERED).
