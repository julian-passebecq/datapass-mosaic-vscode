# RESUME · Mosaic VSIX V1 finish (branch `codex/mosaic-vsix-v1-finish-20261011`)

Started 2026-10-12 from verified `main` 544c420 (= the SHA in the brief; no drift). Lead: Claude (Opus 5.5), local
worktree `.claude/worktrees/nifty-chatterjee-624074`. Remote publication: **STAGED** (needs Julian's narrow grant).

## Goal and done condition
Finish and qualify Datapass Mosaic VSIX V1 on top of 0.3.0: Learning (PR #72 recovered and expanded), blank Build
workspace, pipeline authoring, Infra progression, Mosaic Studio exchange contract, product docs, installed-VSIX
acceptance. Done = every package below merged into this branch, the CLAUDE.md gate list green locally, the
acceptance journey green on the packaged VSIX, READY/OUTCOME written; then green CI once publication is granted.

## Done
- Preflight: no twin session; Codex worktree `ceff` (release/mosaic-v03) clean; old worktrees from 25 Sept clean.
- PR #74 CI failure (`AVG needs a value whose type is known`) reproduced on **main** with sqlglot 30.22: sqlglot
  30.20+ removed `qualify(infer_schema=...)`; the TypeError was swallowed in `sqldialects/core.py::_annotate`, so
  columns lost their types. Fixed (`ad8d7b7`); runtime smoke passes on sqlglot 30.19 and 30.22.
- PR #72 (3 commits) cherry-picked cleanly; PR #74's only extra commit (`learning-v1.yml` workflow) not taken.
- Wave 0: Learning catalog split into `content/learning/catalog.json` (path order) + `content/learning/paths/<id>.json`
  (`assembleCatalog` in `media/learning/model.mjs`); `npm test` also runs `node --test scripts/suite/`; `test:ui`
  also runs `scripts/ui_suite.mjs` (every `scripts/ui-suite/*.mjs`).

## Packages (full plan: handoff/V1-FINISH-PLAN.md)
P1 Learning engine + core content · P2 curriculum content + `learning-checks-v1` quiz pack · P3 blank Build +
exchange contract · P4 pipeline authoring · P5 Infra progression · P6 docs + acceptance journey (lead).

## How to verify
`npm run compile && npm test`, the CLAUDE.md gate list, `npm run package && npm run test:ui`.
