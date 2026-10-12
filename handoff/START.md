# START — Mosaic VSIX V1 finish lane

Branch `codex/mosaic-vsix-v1-finish-20261011`, base `main` at 0.3.0. It carries the sqlglot typing fix, PR #72
(Learning) and packages P1 to P5, all merged locally. Nothing is pushed and there is no PR yet.

## Build and install the VSIX

```bash
npm ci
npm run compile
npm test
npm run package
code --install-extension <file>.vsix --force
```

`npm run package` builds the VSIX. Python smokes need `python -m pip install ./runtime` first
(see CLAUDE.md "Required quality gates" and docs/LOCAL_TEST.md for `test:host` and `test:ui`).

## Where things are

- Plan and package scope: `handoff/V1-FINISH-PLAN.md`; progress: `handoff/RESUME.md`.
- Features and truth labels: `handoff/features.csv`. Entry points: `handoff/ux.csv`.
- What each capability needs: `handoff/ACCESS_MATRIX.md`. Test results: `handoff/EVIDENCE.md` (rows marked pending are still to run).
- Current state: `docs/HANDOFF.md`; per-tranche Checked / Not checked: `docs/HANDOFF_HISTORY.md`.
- Learning: `docs/MOSAIC_LEARNING.md`, `content/learning/`. Exchange: `docs/MOSAIC_EXCHANGE.md`.
- Rules (truth model, security): `CLAUDE.md`.
