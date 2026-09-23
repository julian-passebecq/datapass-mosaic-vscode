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
3. In Mosaic, open the SQL scratch file.
4. Open the Python/Polars scratch file.
5. Drag/resize the Mosaic blocks.
6. Switch to Fabric Lab and back to Mosaic; the webview layout should remain available.

The generated starter files are normal workspace files:

```text
.datapass/project.json
notebooks/mosaic.sql
notebooks/mosaic.py
notes/mosaic.md
```

No cloud account is required.

## Automated gates

GitHub Actions runs two independent checks:

- extension: TypeScript typecheck + esbuild bundle;
- runtime: install local Python package + compile/import smoke.

The extension must stay green before deeper Mosaic/Pipeline/Fabric surfaces are promoted from migration sources.
