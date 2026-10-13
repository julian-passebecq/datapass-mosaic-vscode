# READY · Datapass Workbench 0.4.0 (Mosaic VSIX V1)

**Status: merged to main and green.** PR #75 squash-merged as `e4519fc` (all four required CI jobs green on the PR);
main CI on the follow-up #76 (`4b2b91f`) is green on `extension`, `runtime`, `extension-host` and `vscode-ui`. Not tagged.

## Package
- VSIX: `D:\PROJ\datapass-mosaic-vscode-release\0.4.0\datapass-mosaic-vscode-0.4.0.vsix`
  - sha256 `501db2fda8a3b5355921873a7133872020be188481209bea21531499f6958783`
  - 618 entries; `handoff/`, solutions, mutants and `quality.json` are excluded.
- Source: main at `e4519fc08fede946a1d58c9bf0c9bd3e2cb89d38` (squash of PR #75). Later main commits change `scripts/` and
  `handoff/` only, which are not packaged, so this VSIX is also main's.
- Manifest: `source-manifest.json` (each entry with its sha256), `SHA256SUMS`, and the three UI reports, in the same folder.

## Install locally
```
code --install-extension D:\PROJ\datapass-mosaic-vscode-release\0.4.0\datapass-mosaic-vscode-0.4.0.vsix --force
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
| 8 | Mosaic Studio exchange: import writes native files, runs nothing; export validates against the schema | pass | v1_acceptance 8 |
| 9 | Restart VS Code: Learning position, 4 levels, flashcards, files, datasets, query history, pipeline edit persist | pass | v1_acceptance 9 |
| 10 | No webview console errors | pass | v1_acceptance 10 |
| — | Existing modules, runtime auth (401/400), Practice/Review/Interview, Infra, Lakehouse, API Lab, trusted pytest, navigation through all 13 modules, runtime update | pass 68/68 | vscode_ui_pass |
| — | Learning smoke: Try, Exercise, real grading, SparkLab labels, narrow layout, restart | pass | learning_vscode_smoke |

Local gates: compile, `npm test`, compileall, the runtime / packs / projects / terminal / infra / lakehouse / API
smokes, `gen_json_schemas --check` and `test:host` all pass (handoff/EVIDENCE.md).

## Open
1. **Not run locally** (CI runs them): `dbt_oracle_smoke.py` and `missions_smoke.py` (they need the dbt tools).
2. **Flakes seen locally on Windows and fixed in the harness:**
   - files read before their content was written (#75, #76);
   - a command-palette row that sometimes does not appear (one retry in `vscode_ui_pass.mjs`).
3. **Content caveats:**
   - The platform facts in learning-checks-v1 and infra-concepts-v1 were written from documented behaviour and not
     re-checked against live vendor docs (E-FACTS-P2).
   - The Git and shell, and Polars, lesson examples were not run on every version (E-CONTENT-RUN-P1).
4. **Not automated:** the pipeline save-conflict modal, the import/export file dialogs and pointer drag on the canvas.
5. **Not done:** no tag, no GitHub Release, no Marketplace publication. Pushing a `v0.4.0` tag would trigger the release
   workflow (docs/RELEASE.md).
