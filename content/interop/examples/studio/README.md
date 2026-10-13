# Mosaic Studio notebooks (.ipynb fixtures)

These notebooks were written by Mosaic Studio's own `export_notebook` (`py/service/notebook_io.py`, nbformat 4.5 with
DataPass fields in `metadata.datapass`), not by this extension. They are what Studio produces today, and the
Workbench's `.ipynb` importer (`src/platform/studioNotebook.ts`) reads them; `scripts/suite/studio_notebook.test.mjs`
round-trips them.

- `studio-wind-reference.ipynb`: Studio's `py/notebooks/wind_reference.ipynb`, imported then exported by Studio.
- `studio-e2e01-export.ipynb`: Studio's `qa/E2E-01-b3f194d/e2e01-export.ipynb`, imported then exported by Studio
  (outputs not exported: source only, no data).
- `studio-all-kinds.ipynb`: a synthetic payload written in `scripts/interop/studio_roundtrip.py` (`ALL_KINDS`) with
  every Studio cell kind (note, jupyter, sql with a chart, runtime-model, inert raw cell) and dependencies, exported
  by Studio's `export_notebook`.

All content is synthetic. Nothing in these files has been run by the Workbench.

Regenerate (a local Mosaic Studio checkout at the commit below, Python 3.10+, Node with this repo's `npm install`):

```sh
DATAPASS_MOSAICSTUDIO=<path to a Mosaic Studio checkout> python scripts/interop/studio_roundtrip.py --write-fixtures
```

Studio commit: 4623b04949906070a0b898b23a64ffd5f1eede8a
