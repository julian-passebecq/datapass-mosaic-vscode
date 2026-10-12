# READY · Datapass Workbench 0.4.0 (Mosaic VSIX V1)

**Status: locally qualified, remote publication STAGED.** The four required CI jobs (`extension`, `runtime`,
`extension-host`, `vscode-ui`) have not run on this branch yet, because pushing needs Julian's grant. Release readiness
is claimed only after they are green.

## Package
- VSIX: `D:\PROJ\datapass-mosaic-vscode-release\0.4.0\datapass-mosaic-vscode-0.4.0.vsix`
  - sha256 `e88477d791b8d44c531028a9d7b8b54b4b6a15320282e619cb0675f8ddac974a`
  - 618 entries; `handoff/`, solutions, mutants and `quality.json` are excluded.
- Source: branch `codex/mosaic-vsix-v1-finish-20261011`, commit `c35d632d8b8e49915700371f1e38cbd78c9ae15a`, base main `544c420`.
  - Later commits change `handoff/` only, which is not packaged.
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

## Open before calling it released
1. **Julian:** grant remote publication (target repo, branch and file scope as in the brief). Then the branch is pushed
   and the four CI jobs must go green on the exact commit.
2. **Not run locally** (CI covers them): `dbt_oracle_smoke.py` and `missions_smoke.py` (they need the dbt tools).
   No dbt code changed.
3. **Known flake:** `vscode_ui_pass` timed out once after the concept-check sheet step (1 of 2 runs at c35d632). The
   rerun was green.
4. **Content caveats:**
   - The platform facts in learning-checks-v1 and infra-concepts-v1 were written from documented behaviour and not
     re-checked against live vendor docs (E-FACTS-P2).
   - The Git and shell, and Polars, lesson examples were not run on every version (E-CONTENT-RUN-P1).
5. **Not automated:** the pipeline save-conflict modal, the import/export file dialogs and pointer drag on the canvas.
6. **Not done here:** no tag, no Marketplace publication, no merge to main.
