# Evidence

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
| E-CI-EXTENSION | CI job `extension` | pending | pending | pending |
| E-CI-RUNTIME | CI job `runtime` | pending | pending | pending |
| E-CI-HOST | CI job `extension-host` (`npm run test:host`) | pending | pending | pending |
| E-CI-UI | CI job `vscode-ui` (`npm run package && npm run test:ui`) | pending | pending | pending |
| E-SMOKE-PACKS | `python scripts/exercise_packs_smoke.py` (new counts with learning-checks-v1 and infra-concepts-v1) | pending | pending | pending |
| E-CONTENT-RUN-P1 | Git and shell content against real git and bash; Polars on versions other than 2.0.0 | pending | pending | pending |
| E-FACTS-P2 | P2 and P5 platform facts checked against live vendor docs; reword the pack provenance line | pending | pending | pending |
| E-HOST-BUILD | `npm run test:host` Build and import commands | pending | pending | pending |
| E-UI-LEARNING | `npm run test:ui` Learning tree levels, cheatsheet preview, narrow layout of new cards | pending | pending | pending |
| E-UI-BUILD | `npm run test:ui` Mosaic empty-state panel and Build dialogs | pending | pending | pending |
| E-UI-PIPELINE | VS Code: save conflict, dirty text editor, import, export, new pipeline, pointer drag | pending | pending | pending |
| E-UI-INFRA | VS Code: Infra Lab mission list with intro levels | pending | pending | pending |
| E-EXCHANGE-STUDIO | Mosaic Studio producer follows docs/MOSAIC_EXCHANGE.md | pending | pending | pending |
