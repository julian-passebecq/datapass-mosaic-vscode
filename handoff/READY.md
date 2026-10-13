# READY · Datapass Workbench 0.4.0 (Mosaic VSIX V1)

**Status: merged to main, green, delivered privately.** Current build: main `44e8007` (after #78 Studio .ipynb interop and
#79 BI Lab test race); CI `extension`, `runtime`, `extension-host`, `vscode-ui` green on the PR and on main. Not tagged.

## Package
- VSIX: `D:\PROJ\datapass-mosaic-vscode-release\0.4.0-44e8007\datapass-mosaic-vscode-0.4.0.vsix`
  - sha256 `a060fb712adb8abf9bb5d9043bf5a83cfac397995e78ed21e0b47b06e43466b9`, 622 entries; `handoff/`, solutions,
    mutants and `quality.json` are excluded; privacy scan 0 hits.
- Source: main `44e80072ef6d6890f6a43229f7aa216a1ac99c35`.
- Same folder: `source-manifest.json` (sha256 per entry), `USER-GUIDE.md`, `TESTS.md`, `SHA256SUMS`.
- Private copy (Julian's grant, Galaxy Finition 2026-10-13): GitLab `juliandatapass-group/galaxy-release-vault`, generic
  package `datapass-mosaic-vscode/0.4.0-44e8007` (5 files). Authenticated re-download matches every sha256; anonymous
  access answers 401.
- Superseded local build: `0.4.0\` from `e4519fc` (sha256 `501db2fd…`), kept, not the current one.

## Install locally
```
code --install-extension D:\PROJ\datapass-mosaic-vscode-release\0.4.0-44e8007\datapass-mosaic-vscode-0.4.0.vsix --force
```
Cursor: `cursor --install-extension <same path> --force`. Then run **Datapass Build: New Blank Workspace** in an empty
folder, or **Datapass: Open Learning**. Python 3.11+ is needed for Setup runtime.

## Feature / UX acceptance (Windows 11, installed VSIX, VS Code stable)
| # | Journey step | Result | Evidence |
|---|---|---|---|
| 1 | New Blank Workspace: `catalog.seed: none`, trusted Python off, no samples, Mosaic opens | pass | v1_acceptance 1 |
| 2 | New File SQL/Python; same name never overwrites | pass | v1_acceptance 2 |
| 3 | Import Dataset into `datasets/`; a second import is renamed `-2`, never overwritten | pass | v1_acceptance 3 |
| 4 | Setup/Start runtime; no `source.*` tables; real DuckDB SQL; Python refused until trusted Python is explicitly enabled, then runs | pass | v1_acceptance 4 |
| 5 | Learning: read / concept check (not verified) / ran locally, not graded / Practice passed; flashcard rated | pass | v1_acceptance 5 |
| 6 | Cloud Lab pipeline: palette add, connect, undo/redo, save keeps unknown properties, simulated dry run | pass | v1_acceptance 6 |
| 7 | Infra intro mission tf-first-apply in the simulated terminal; Check passes | pass | v1_acceptance 7 |
| 8 | Mosaic Studio exchange: import writes native files, runs nothing; export validates against the schema; a Studio `.ipynb` (`metadata.datapass`) imports too (#78) | pass | v1_acceptance 8 |
| 9 | Restart VS Code: Learning position, 4 levels, flashcards, files, datasets, query history, pipeline edit persist | pass | v1_acceptance 9 |
| 10 | No webview console errors | pass | v1_acceptance 10 |
| — | Existing modules, runtime auth (401/400), Practice/Review/Interview, Infra, Lakehouse, API Lab, trusted pytest, navigation through all 13 modules, runtime update | pass in CI on 44e8007; locally 64-67/68 per run at 100 % CPU (one different timeout each run) | vscode_ui_pass |
| — | Learning smoke: Try, Exercise, real grading, SparkLab labels, narrow layout, restart | pass | learning_vscode_smoke |

Local gates: compile, `npm test`, compileall, the runtime / packs / projects / terminal / infra / lakehouse / API
smokes, `gen_json_schemas --check` and `test:host` all pass (handoff/EVIDENCE.md).

## Open
1. **Not run locally** (CI runs them): `dbt_oracle_smoke.py` and `missions_smoke.py` (they need the dbt tools).
2. **Flakes seen locally on Windows and fixed in the harness:**
   - files read before their content was written (#75, #76);
   - a command-palette row that sometimes does not appear (one retry in `vscode_ui_pass.mjs`);
   - the BI Lab build clicked before the Cloud Lab copy finished (#79).
3. **Content caveats:**
   - The platform facts in learning-checks-v1 and infra-concepts-v1 were written from documented behaviour and not
     re-checked against live vendor docs (E-FACTS-P2).
   - The Git and shell, and Polars, lesson examples were not run on every version (E-CONTENT-RUN-P1).
4. **Not automated:** the pipeline save-conflict modal, the import/export file dialogs and pointer drag on the canvas.
5. **Not done:** no tag, no GitHub Release, no Marketplace publication. Pushing a `v0.4.0` tag would trigger the release
   workflow (docs/RELEASE.md).
