# Evidence

## Current 0.4.1 candidate — 2026-10-22

See [the resumed candidate report](GA-FOLLOWUP-2026-10-22.md) for current fixes and qualification, and
[the earlier report](GA-PASS-2026-10-22.md) for preserved c3d73af evidence. **RELEASE_PASS=false**. The rows below are historical 0.4.0 evidence;
they must not be used to qualify 0.4.1.

## Historical evidence

Lead fills the "pending" rows. Commit column: the commit the run was made at.

| evidence_id | command or CI job | artifact path | commit | result |
|---|---|---|---|---|
| E-RUNTIME-SQLGLOT | `python scripts/runtime_smoke.py` on sqlglot 30.19 and 30.22 | smoke output | ad8d7b7 | passed |
| E-NPM-TEST | `npm run compile` + `npm test` | test output | 57ab2d8 | passed |
| E-PKG-VERIFY-P1 | P1 built and independently verified (packaged VSIX journey incl. flashcards passes) | pkg-notes (session scratchpad) | 43a6ceb | passed with gaps (see HANDOFF_HISTORY) |
| E-PKG-VERIFY-P2 | P2 built and independently verified (validateCatalog, exercise_packs_smoke, 5 SQL examples on DuckDB) | pkg-notes | e820e0e | passed; vendor facts not re-checked |
| E-PKG-VERIFY-P3 | P3 built and independently verified (node test, runtime smoke, host E2E) | pkg-notes | 32ac85d | passed; webview not clicked |
| E-PKG-VERIFY-P4 | P4 built and independently verified (round trip, webview harness) | pkg-notes | fcd403b | passed; host flows not checked |
| E-PKG-VERIFY-P5 | P5 built and independently verified (13 missions played via runtime API) | pkg-notes | 3b703f0 | passed; not opened in VS Code |
| E-CI-EXTENSION | CI job `extension` | GitHub Actions | af229b9 (PR #75), 4b2b91f (main) | passed |
| E-CI-RUNTIME | CI job `runtime` (local equivalent: compileall + runtime, packs, projects, terminal, infra, lakehouse, api smokes + schemas --check, sqlglot 30.22) | local logs | 57ab2d8 | local: all passed; CI passed on af229b9 (PR #75) and 4b2b91f (main) |
| E-CI-HOST | CI job `extension-host`: `npm run test:host` locally (dbt missions smoke not run locally: needs dbt tools) | local log | 4d1a182 | local: "Extension host E2E passed" incl. catalog.seed none step; CI passed on af229b9 (one infrastructure flake rerun) and 4b2b91f (main) |
| E-CI-UI | `npm run package && npm run test:ui` on Windows 11 (vscode_ui_pass 68/68, learning smoke, ui-suite v1_acceptance 10/10) | D:\PROJ\datapass-mosaic-vscode-release\0.4.0\*.json | c35d632 and main VSIX e4519fc (with the #77 palette retry) | passed (96 PASS, 0 FAIL); earlier local runs flaked on a command-palette wait, fixed by one retry |
| E-SMOKE-PACKS | `python scripts/exercise_packs_smoke.py` | local log | 57ab2d8 and 798d70a | 727 reference solutions passed, 727 starters and 818 mutants rejected |
| E-CONTENT-RUN-P1 | Git and shell content against real git and bash; Polars on versions other than 2.0.0 | pending | pending | pending |
| E-FACTS-P2 | P2 and P5 platform facts checked against live vendor docs; reword the pack provenance line | pending | pending | pending |
| E-HOST-BUILD | Build commands in the installed VSIX (v1_acceptance steps 1-3) | v1-acceptance-report.json | c35d632 | passed |
| E-UI-LEARNING | Learning levels, flashcards, restart (v1_acceptance 5 and 9, learning smoke) | v1-acceptance-report.json, learning-ui-report.json | c35d632 | passed; cheatsheet preview and narrow layout of new cards not separately asserted |
| E-UI-BUILD | Mosaic empty state + Build dialogs (v1_acceptance 1-4) | v1-acceptance-report.json | c35d632 | passed |
| E-UI-PIPELINE | Pipeline edit: palette add, connect, undo/redo, save with unknown properties kept, dry run (v1_acceptance 6, 9) | v1-acceptance-report.json | c35d632 | passed; save-conflict modal, import/export dialogs and pointer drag not automated |
| E-UI-INFRA | Infra intro mission tf-first-apply in the simulated terminal (v1_acceptance 7) | v1-acceptance-report.json | c35d632 | passed |
| E-EXCHANGE-STUDIO | Mosaic Studio producer follows docs/MOSAIC_EXCHANGE.md | Studio origin/main | Studio 4623b04 | not produced: Studio's merged interchange is .ipynb + metadata.datapass (see E-STUDIO-IPYNB); the exchange stays pending on Studio's side |
| E-STUDIO-IPYNB | `DATAPASS_MOSAICSTUDIO=<temp worktree of Studio origin/main> python scripts/interop/studio_roundtrip.py`: our .ipynb exports into Studio's own `import_notebook`, Studio's `export_notebook` of its samples and of every cell kind into our importer | content/interop/examples/studio/ (fixtures + README) | branch feat/studio-ipynb-interop; Studio 4623b04949906070a0b898b23a64ffd5f1eede8a | passed (OK, 0 failures; 3 fixtures, sample folder, both directions) |
| E-UI-INTEROP | Exchange import (files, nothing run) + export validates (v1_acceptance 8) | v1-acceptance-report.json | c35d632 | passed |
| E-VSIX | VSIX 0.4.0 built from main e4519fc, 618 entries, handoff/ excluded | source-manifest.json, SHA256SUMS | e4519fc | sha256 501db2fda8a3b5355921873a7133872020be188481209bea21531499f6958783 (rebuilt from main; c35d632 build was e88477d7…) |
| E-CI-UI-MAIN | CI job `vscode-ui` on main | GitHub Actions | e4519fc failed (acceptance file race, fixed by #76); 4b2b91f passed | passed |
