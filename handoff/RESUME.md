# RESUME · Mosaic VSIX V1 finish (branch `codex/mosaic-vsix-v1-finish-20261011`)

Started 2026-10-12 from verified `main` 544c420 (= the SHA in the brief; no drift). Lead: Claude (Opus 5.5), local
worktree `.claude/worktrees/nifty-chatterjee-624074`. Remote publication: granted by Julian on 2026-10-13; merged (#75, #76).

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

## State (2026-10-13, closed)
Merged: PR #75 (`e4519fc`, V1 0.4.0) and #76 (`4b2b91f`, acceptance races). Main CI green on 4b2b91f. VSIX built from
main: `D:\PROJ\datapass-mosaic-vscode-release\0.4.0\` (sha256 501db2fd…8783, source-manifest.json, SHA256SUMS). Details: handoff/READY.md,
OUTCOME.md, EVIDENCE.md.

## Left (optional)
- Tag `v0.4.0` to publish a GitHub Release (docs/RELEASE.md); not done in this lane.
- Content checks E-FACTS-P2, E-CONTENT-RUN-P1, E-EXCHANGE-STUDIO (handoff/EVIDENCE.md).

## How to verify
`npm run compile && npm test`, the CLAUDE.md gate list, `npm run package && npm run test:ui` (set DATAPASS_UI_PYTHON).
