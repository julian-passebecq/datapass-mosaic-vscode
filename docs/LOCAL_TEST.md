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

- module tabs for Mosaic, Practice, Cloud Lab, SparkLab, dbt Lab, Terminal Lab, Infra Lab, Airflow Lab and Pipeline Lab;
- workspace manifest status;
- local runtime status;
- a draggable/resizable Mosaic surface.

## First smoke path

The first **Setup runtime** creates a managed venv and installs FastAPI, DuckDB, Polars and pandas. When `uv` is found (PATH, `~/.local/bin`, `~/.cargo/bin`) it creates the venv (`uv venv --seed`, from the same base Python) and installs the runtime (`uv pip install`); if uv fails, Setup falls back to `python -m venv` and pip. Measured on the maintainer's Windows machine (Python 3.14, antivirus on): 16 s for `python -m venv` and 130 s for pip (91 s with a warm pip cache), against 2 s for `uv venv` and 12 s for uv (7 s with a warm uv cache). With pip and real-time antivirus scanning, a first setup can still take well over ten minutes on a slow disk. The Local runtime card and a VS Code notification show the current step, the latest pip activity and the elapsed time; **Show setup log** opens the full **Datapass Runtime** output channel. Later starts take seconds.

Scratch files, exercise solutions and other files opened from the Workbench open in the column beside it, so the webview and the file stay visible together; **Run active …** also works when both share one tab group.

1. Click **Create .datapass project**.
2. Start the local runtime.
3. In Mosaic, open the SQL scratch file and **Run active SQL**.
4. Open the Python/Polars scratch file; **Run active Python** stays disabled and explains why.
5. **Enable trusted local Python…**, read the warning, confirm; the runtime restarts and the side panel shows *Trusted Python: enabled (not sandboxed)*. Run the Python scratch, then **Disable** again.
6. SparkLab: **Open SparkLab scratch**, **Run active SparkLab file**; check result, compiled SQL, plan and the SIMULATED stage table.
7. Drag/resize the Mosaic blocks; `.datapass/mosaic.json` updates.
8. Close the Workbench tab and reopen Mosaic (or reload the window); the layout is restored from `.datapass/mosaic.json`.

The generated starter files are normal workspace files:

```text
.datapass/project.json
.datapass/mosaic.json      (after the first drag/resize)
notebooks/mosaic.sql
notebooks/mosaic.py
notebooks/sparklab.py
notes/mosaic.md
```

No cloud account is required.

## Automated gates

GitHub Actions runs four independent checks:

- extension: TypeScript typecheck + esbuild bundle + Node contract smokes (`npm test`, which includes
  `scripts/terminal_lab_smoke.mjs`: the Terminal Lab's shell-detection rules — Git Bash next to `git.exe` or in the
  usual Git for Windows folders, never `System32\bash.exe`, `datapass.terminalLab.bashPath` overriding, pwsh then
  Windows PowerShell 5.1 — bundled and run under Node without `vscode`; and `scripts/infra_lab_smoke.mjs`: the Infra
  Lab's simulated-terminal line editor (echo, Backspace, Enter, Ctrl+C, history, cursor keys ignored) and the
  `infra-v1` pack's mission.json contract, bundled and run under Node without `vscode` or the Python runtime);
- runtime: install local Python package + compile + runtime smoke (`scripts/runtime_smoke.py`);
- extension-host: a real VS Code Extension Development Host E2E (`npm run test:host` under `xvfb-run`);
- vscode-ui: the packaged VSIX in a real VS Code window driven by Playwright (`npm run test:ui` under `xvfb-run`), with the screenshots uploaded as the `vscode-ui-pass` artifact.

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
3. trusted-Python resolution (manifest flag alone is not enough; confirmation required; disable resets); Mosaic layout round trip through `.datapass/mosaic.json`, rejected input and corrupt-file fallback;
4. Airflow starter DAG file under `airflow/dags`; the dbt Lab finds the workspace's dbt projects and writes `.datapass/dbt/profiles.yml` (no run claimed before `target/` exists);
5. runtime start **with `DATAPASS_TRUSTED_PYTHON=1` injected into the host** — it must still report trusted Python off;
6. Mosaic SQL scratch on real DuckDB; Python refused while untrusted;
7. SparkLab scratch result + simulated stages; unsafe SparkLab source rejected; Airflow Lab simulates the starter DAG (states, retries, all_done cleanup) and rejects a bad import with its line;
8. Practice `demo-sum` visible run and submission pass; a wrong answer fails;
9. Pipeline starter compiles to a graph and its activities run;
10. retail medallion demo;
11. trusted restart and a real Python/Polars run;
12. Terminal Lab: the mission folder is built and a real terminal opens in it (bash and, if installed, PowerShell);
    the reference commands are typed there, as a learner would, and the hidden checker judges what they left behind;
    **Start over** releases the folder (closing the lab's terminals and the Git extension's repository on it) and
    moves it to the attic instead of deleting it.
13. Infra Lab: the mission folder and its simulated world (`.infralab/world.json`) are built; a mission's reference
    lines are typed in the simulated terminal (a `Pseudoterminal` that starts no process, each line sent to the
    runtime's simulators) and reach the journal; the hidden checker judges the simulated world it produced.

The runtime steps also cover the catalog handoff (release, a second process writing the file, a refused reattach while it is held, then a reattach that sees its table) and the Catalog tree. With `DATAPASS_DBT_PYTHON` set to a Python that has dbt-core and dbt-duckdb, one more step types `dbt build` for the BI project in a real terminal and checks that the catalog was lent and reattached through shell integration and that the artifacts read back as a clean dbt Core run (CI installs them in a venv for this).

With both variables, a mission step starts *Last night's build failed on a unique test* through the missions service, reproduces the failing `dbt build` in a real terminal, applies the fix, rebuilds and gets a passing verdict from the hidden checker. Without `DATAPASS_DBT_PYTHON` it only checks the project copy, `TICKET.md`, the progress file and a first "not yet" verdict.

`scripts/missions_smoke.py` plays every mission of `content/missions` through the runtime API with real dbt Core and dct (`DATAPASS_DBT_PYTHON` must point to a Python that has dbt-core, dbt-duckdb and dbt-charts): each reference solution passes, each untouched project and each mutant fails. Without the variable it only validates the pack.

`scripts/terminal_missions_smoke.py` plays every Terminal Lab mission of `content/missions/terminal-v1` through the runtime API: it builds each mission's fixture (files and Git history) and runs the reference solution with a real shell, as a learner would type the commands, then asks the checker. It needs git and bash (Git Bash on Windows; `DATAPASS_BASH` overrides); PowerShell steps (`solution/solve.ps1`) are skipped with a note when no PowerShell is installed, unless `DATAPASS_REQUIRE_POWERSHELL=1` (set in CI, where pwsh is on the runner). Mission ids passed as arguments play only those missions. Reference solutions pass; the untouched fixture and every mutant (`mutants/<name>/solve.sh` or `solve.ps1`) fail.

```bash
python scripts/terminal_missions_smoke.py
DATAPASS_REQUIRE_POWERSHELL=1 python scripts/terminal_missions_smoke.py   # CI
python scripts/terminal_missions_smoke.py merge-conflict reflog-rescue    # only these missions
```

`scripts/infra_missions_smoke.py` plays every Infra Lab mission of `content/missions/infra-v1` through the runtime
API: it builds each mission's fixture (files, simulated world, fixture commands), types the reference lines in the
simulated shell (`/api/local/infra/command`), as a learner would, then asks the checker. No external tool is needed:
`terraform`, `docker`, `kubectl` and `az` are all simulated. Reference solutions pass; the untouched fixture, the
starter project played with the reference commands, and every mutant fail; two builds of a fixture give the same
simulated world (deterministic ids, clock and metrics). Mission ids passed as arguments play only those missions.

```bash
python scripts/infra_missions_smoke.py
python scripts/infra_missions_smoke.py lake-landing-zone   # only this mission
```

Without `DATAPASS_E2E_PYTHON` steps 5–11 are reported as skipped. The suite does not click webview buttons: it drives the same host classes the panel uses. Manual F5 inspection of the webview UI is still required for user-facing changes.

The extension must stay green before deeper Mosaic/Pipeline/Fabric surfaces are promoted from migration sources.

### Packaged VSIX UI pass

```bash
npm run package
npm run test:ui
```

`scripts/vscode_ui_pass.mjs` installs the newest `*.vsix` into a fresh VS Code profile (a VS Code test build downloaded into `.vscode-test/`), opens a disposable workspace and clicks through the Workbench with Playwright (`_electron.launch`), as a learner would:

1. **Create .datapass project**, **Setup runtime** (the managed venv), **Start runtime**.
2. Raw requests to the live runtime port: 401 without the launch token, 400 with a foreign Host; the token never appears in the runtime log.
3. Mosaic: the SQL scratch file, **Run active SQL**, the DuckDB result row in the webview.
4. Practice: **Open solution** on the first exercise, then **Submit**; the runtime grades the starter.
5. Infra Lab: **Start mission** on *Page the on-call when the self-hosted integration runtime goes down*, its
   reference commands typed one by one in the simulated terminal (Playwright types into the xterm textarea, no real
   `terraform`/`docker`/`kubectl`/`az` runs), then **Check my work** passes and the simulated world shows.
6. Layout at a 520 px Workbench: every module tab and every lab sub-tab. No element may stick out on the right unless a container scrolls or clips it (the PR #17 overflow). The probe first proves it catches a planted 2000 px block.
7. **Stop runtime**; the port is closed afterwards. Uncaught webview errors fail the pass.
8. Upgrade: the managed venv is made to look like an older VSIX set it up (another fingerprint in its `datapass-runtime.json` marker, a changed installed `datapass_runtime/__init__.py`). After **Developer: Reload Window** the Workbench must show the environment as "needs update" with **Update runtime** and no **Start runtime**; **Update runtime** must restore the marker and the installed module; the runtime then starts.

Results and one screenshot per step land in `test-results/vscode-ui/` (`results.json`, `layout-<tab>.png`, …). The profile and workspace live under `C:\dpw-ui` on Windows (the managed venv sits in the profile and DuckDB's DLL path must stay under MAX_PATH) and under the temp folder elsewhere; the root is wiped first.

| Variable | Use |
|---|---|
| `DATAPASS_UI_VSIX` | VSIX to install (default: the newest `*.vsix` in the repository root) |
| `DATAPASS_UI_ROOT` | profile and workspace root (keep it short on Windows) |
| `DATAPASS_UI_OUT` | results and screenshots folder |
| `DATAPASS_UI_PYTHON` | base Python for **Setup runtime**, written to the manifest's `runtime.pythonCommand` |
| `VSCODE_TEST_VERSION` / `DATAPASS_UI_CODE` | VS Code build to download (default stable) / an installed Code executable instead |
| `DATAPASS_UI_KEEP=1` | keep the profile, so a rerun skips **Setup runtime**; when the new VSIX's runtime differs from the one the kept venv holds, the pass clicks **Update runtime** instead |

The VSIX declares an extension pack, so the install also fetches the Python and Jupyter extensions from the Marketplace. On Linux, give the virtual display a real screen: `xvfb-run -a --server-args="-screen 0 1600x1000x24" npm run test:ui`.
