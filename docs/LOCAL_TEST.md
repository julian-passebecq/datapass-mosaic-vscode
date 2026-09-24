# Local test

## One-time setup

```powershell
npm install
python -m pip install -e runtime
```

The Python package is the local Datapass runtime. It installs FastAPI, Uvicorn,
DuckDB, Polars and the runtime package from this repository.

## Run the extension

1. Open this repository in VS Code.
2. Press **F5** and choose **Run Datapass Workbench**.
3. In the Extension Development Host, open a normal data-project folder.
4. Click the **Datapass** Activity Bar icon.
5. Open **Mosaic**.

The Workbench panel should show:

- module tabs for Mosaic, Practice, Fabric Lab, SparkLab, dbt Lab, Airflow Lab and Pipeline Lab;
- workspace manifest status;
- local runtime status;
- a draggable/resizable Mosaic surface.

## First smoke path

1. Click **Create .datapass project**.
2. Start the local runtime.
3. In Mosaic, open the SQL scratch file and **Run active SQL**.
4. Open the Python/Polars scratch file; **Run active Python** stays disabled and explains why.
5. **Enable trusted local Python…**, read the warning, confirm; the runtime restarts and the side panel shows *Trusted Python: enabled (not sandboxed)*. Run the Python scratch, then **Disable** again.
6. SparkLab: **Open SparkLab scratch**, **Run active SparkLab file**; check result, compiled SQL, plan and the SIMULATED stage table.
7. Drag/resize the Mosaic blocks.
8. Switch to Fabric Lab and back to Mosaic; the webview layout should remain available.

The generated starter files are normal workspace files:

```text
.datapass/project.json
notebooks/mosaic.sql
notebooks/mosaic.py
notebooks/sparklab.py
notes/mosaic.md
```

No cloud account is required.

## Automated gates

GitHub Actions runs three independent checks:

- extension: TypeScript typecheck + esbuild bundle + Node contract smokes (`npm test`);
- runtime: install local Python package + compile + runtime smoke (`scripts/runtime_smoke.py`);
- extension-host: a real VS Code Extension Development Host E2E (`npm run test:host` under `xvfb-run`).

### Extension Development Host E2E

```bash
python -m pip install ./runtime
npm run test:host            # set DATAPASS_E2E_PYTHON first to include runtime steps
```

PowerShell:

```powershell
$env:DATAPASS_E2E_PYTHON = (Get-Command python).Source
npm run test:host
```

`scripts/extension_host_e2e.mjs` downloads a VS Code test build into `.vscode-test/`, opens a disposable workspace and runs `src/test/hostSuite.ts` inside the extension host. It covers, in the order of the manual smoke path:

1. activation and every Workbench command; the Mosaic command opens the Workbench webview;
2. `.datapass/project.json` creation with `trustedLocalPython: false`;
3. trusted-Python resolution (manifest flag alone is not enough; confirmation required; disable resets);
4. Airflow starter DAG validation; dbt sample static lineage (labeled static, not a run);
5. runtime start **with `DATAPASS_TRUSTED_PYTHON=1` injected into the host** — it must still report trusted Python off;
6. Mosaic SQL scratch on real DuckDB; Python refused while untrusted;
7. SparkLab scratch result + simulated stages; unsafe SparkLab source rejected;
8. Practice `demo-sum` visible run and submission pass; a wrong answer fails;
9. Pipeline starter compiles to a graph and its activities run;
10. retail medallion demo;
11. trusted restart and a real Python/Polars run.

Without `DATAPASS_E2E_PYTHON` steps 5–11 are reported as skipped. The suite does not click webview buttons: it drives the same host classes the panel uses. Manual F5 inspection of the webview UI is still required for user-facing changes.

The extension must stay green before deeper Mosaic/Pipeline/Fabric surfaces are promoted from migration sources.
