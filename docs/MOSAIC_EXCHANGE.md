# Mosaic Studio interop: `.ipynb` notebooks and the Mosaic exchange

Two formats move notebook work between **Mosaic Studio** (the browser app, DuckDB-WASM, repository
`datapass-mosaicstudio`) and the **Datapass Workbench** (this extension, native DuckDB). Neither carries data and
neither is executed on import.

| Format | Produced by Mosaic Studio today | Read and written by the Workbench |
| --- | --- | --- |
| Jupyter `.ipynb` (nbformat 4) with DataPass fields in `metadata.datapass` | **yes**: Studio's merged interchange (`py/service/notebook_io.py`, `export_notebook` / `import_notebook`) | yes, since this change (`src/platform/studioNotebook.ts`) |
| `datapass.mosaic-exchange` v1 (this document's contract) | **no**: Studio does not produce or read it yet | yes (`src/platform/mosaicExchange.ts`) |

The exchange stays for provenance-rich exchange (several notebooks, artifact names and hashes, past runs and their
engine). Studio's open PR #45 (`datapass.workbench.notebook`, unmerged) is a third format, not targeted here.

- Commands: **Datapass: Import Mosaic Exchange** (`datapass.interop.import`) accepts a `.ipynb` or an exchange
  `.json`; **Datapass: Export Mosaic Exchange** (`datapass.interop.export`) asks for the format first, labelled by the
  setting `datapass.interop.formatLabels` ("Mosaic Studio notebook (.ipynb)", "Datapass exchange (.json)"). Both in
  `src/build/interopCommands.ts`.
- Tests: `scripts/suite/studio_notebook.test.mjs` and `scripts/suite/mosaic_exchange.test.mjs` (round trips,
  refusals, no overwrite), `scripts/json_schemas_smoke.mjs`, a step of `src/test/hostSuite.ts`, step 8 of
  `scripts/ui-suite/v1_acceptance.mjs`, and locally `scripts/interop/studio_roundtrip.py` against Studio's own Python.

## Mosaic Studio notebooks (`.ipynb`)

Studio writes nbformat 4.5 notebooks: `metadata.datapass = {format: "datapass.notebook", version: 1, exportedAt}`,
and on each cell `metadata.datapass = {cellId, title, dependsOn, kind?, chart?, outputTable?, model?, inputs?,
resultSha256?}`. The Workbench maps cells exactly as Studio does:

| Notebook cell | Studio kind | Workbench file |
| --- | --- | --- |
| markdown without attachments, at most 8,000 characters | note | `NN-<id>.md` |
| code with `metadata.datapass.kind = "sql"` or a first line `%%sql` | sql | `NN-<id>.sql` (the SQL, without the `%%sql` line) |
| code, kernel language Python | jupyter | `NN-<id>.py` |
| code with `metadata.datapass.kind = "runtime-model"` | python (allowlisted model) | `NN-<id>.model.json`: `{model, inputs, outputTable?}`, not Python code |
| raw, other kernel languages, attachments, oversize source | inert | `NN-<id>.inert.json`: the original cell (outputs removed), never run, exported back unchanged |

Import: the file is at most 4 MB and 50 cells (Studio's limits), nbformat 4, cells `code`, `markdown` or `raw`. Cell
ids are `metadata.datapass.cellId`, else the nbformat id, made Studio-safe exactly as Studio makes them (`c-<id>` when
it starts with a digit, `<kind>-<n>` when there is none); an unsafe or duplicate id is refused. `dependsOn` must name
runnable cells (sql, jupyter, python) of the same notebook, never itself, without a cycle: anything else refuses the
whole import (Studio itself drops such edges with a loss report; the Workbench does not guess). The folder is
`<notebooks>/imported/<file name>/`; `.datapass/interop/<id>.json` (`format: "datapass.studio-ipynb-import"`) keeps
the notebook metadata, every cell's metadata (unknown keys and unknown `metadata.datapass` fields included), its
nbformat id and dependencies, and which file holds it. Outputs are **not imported** (source only); execution counts
and result hashes are listed in the README as **"ran in Mosaic Studio, not re-run here"**, never as a local result.
Every file is created exclusively, as for the exchange below.

Export: one notebook per `.ipynb`, from an imported Studio notebook (its record), an imported exchange notebook, or a
plain folder of `.sql`, `.py` and `.md` files (ids from the file names, a lowercase letter first). The result is
nbformat 4.5 that Studio's `import_notebook` accepts unchanged: SQL as `%%sql` + `metadata.datapass.kind = "sql"`,
Python as `kind = "python"`, models as `kind = "runtime-model"`, inert cells verbatim, the recorded notebook and cell
metadata written back, no outputs, `execution_count` null, no data. The notebook is validated (ids, at most 12
dependencies per cell, acyclic, no dangling edge, sizes) before it is saved.

Fixtures: `content/interop/examples/studio/*.ipynb` were written by Studio's own `export_notebook` at the Studio
commit recorded in their README. `DATAPASS_MOSAICSTUDIO=<Studio checkout> python scripts/interop/studio_roundtrip.py`
runs Studio's real `notebook_io.py` (copied to a temporary folder, `python -I`, a venv under %TEMP% with Studio's
pinned nbformat) against this extension's reader and writer both ways; it skips when the variable is unset (CI).

## Mosaic exchange (`datapass.mosaic-exchange`, version 1)

The contract for provenance-rich exchange: cells as text, the names and hashes of what they produced, and the
history of past runs. Mosaic Studio does not produce or read it yet; its producer would follow this section.

- Schema: `schemas/mosaic-exchange.schema.json` (written by hand).
- Validator, import plan and export: `src/platform/mosaicExchange.ts` (pure; the schema and the validator are kept in
  step, and the validator also checks what a schema cannot: unique ids, references and cycles).
- Examples: `content/interop/examples/*.json`, written by hand to this contract: `mosaic-studio-sensors.json` shows
  what a Studio (DuckDB-WASM) producer would write, `datapass-workbench-orders.json` a Workbench export. Studio did
  not produce them.

### Document

| Field | Type | Rule |
| --- | --- | --- |
| `format` | `"datapass.mosaic-exchange"` | required |
| `version` | `1` | required; a reader of version 1 refuses any other version |
| `producer` | `{app, version}` | required; `app` is `mosaic-studio` or `datapass-workbench` |
| `exportedAt` | ISO 8601 date-time with a zone | required |
| `runtime` | `{engine, version}` | `engine` is `duckdb-native` or `duckdb-wasm`; `version` is the DuckDB version or `unknown` |
| `notebooks` | 1 to 50 `{id, title, cells}` | ids unique |
| `notebooks[].cells` | 1 to 500 `{id, kind, source, dependsOn}` | `kind`: `sql`, `python`, `polars`, `markdown`; `source` at most 200,000 characters; ids unique in the notebook |
| `cells[].dependsOn` | cell ids | cells of the **same** notebook; no self-reference, no unknown id, no cycle |
| `artifacts` | `{id, kind, name, sha256?, producedBy?}` | `kind`: `table` (`layer.table`) or `file` (workspace-relative path); `sha256`: 64 lowercase hex; `producedBy {notebook, cell}` must name a cell, and is absent for an input file such as a dataset; an artifact with `data`, `rows`, `content` or `bytes` is refused |
| `provenance` | `{source, commit?, runs}` | `runs[]`: `{cell, notebook?, engine, at, status}`; `status` is `success`, `error` or `cancelled`; `notebook` is required when two notebooks use the same cell id |
| `extensions` | object | opaque: kept as is on import and written back on export, never interpreted |

Ids match `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`, so they are safe as file and folder names. A file is at most 5 MB.
Unknown fields are allowed at every level, kept by an import and written back by an export: a newer producer can add
a field without breaking a version 1 reader. A change that a version 1 reader would misread needs version 2.

`sha256` is the producer's hash: the bytes of a file; for a table, the producer's own content hash. A reader compares
hashes from the same producer only; it never recomputes a table's hash from another engine.

### Import (Workbench)

1. The file is size-checked, parsed and validated; any error refuses the whole import and nothing is written.
2. Each notebook becomes a folder `<notebooks>/imported/<notebook id>/` (`<notebooks>` is the manifest's
   `assets.notebooks`, default `notebooks`). Each cell becomes one native file, in order:
   `01-<cell id>.sql`, `.py` (python and polars) or `.md`. The file holds the cell source exactly.
3. A `README.md` in that folder lists the cells, their dependencies and the producer's runs. A run made by
   Mosaic Studio is labelled **"ran in Mosaic Studio (DuckDB-WASM), not re-run here"**; a native run
   "ran on native DuckDB where it was exported, not re-run here".
4. `.datapass/interop/<notebook id>.json` records the exchange header and this notebook as received (unknown fields
   included, cell sources left out since the files hold them), its artifacts and runs, and which file holds which cell.
5. Every file is created exclusively. If a notebook's folder or record already exists the import is refused before
   anything is written; a file that appears meanwhile is never replaced.

The import **runs nothing**. A SQL cell runs only when the learner runs the file with Mosaic's Run active SQL (real
local DuckDB). A Python or Polars file runs only after the learner enables trusted local Python for the workspace;
an import never changes that setting. Tables named in `artifacts` do not exist in the Workbench catalog until the
learner runs the cells or imports the datasets.

### Export (Workbench)

The learner picks imported notebooks (their records) and/or a plain folder of `.sql`, `.py` and `.md` files.

- An imported notebook keeps its ids, titles, order, dependencies, unknown fields, artifacts, runs and extensions;
  the cell sources are the files' current text. A deleted cell file drops the cell, the dependencies on it, its runs
  and the artifacts it produced.
- A plain folder becomes one notebook: one cell per file in name order, the id from the file name, no dependencies;
  a `.py` file that imports Polars is a `polars` cell.
- `runtime` is `{engine: "duckdb-native", version: <the runtime's DuckDB, or "unknown" when it is stopped>}`,
  `producer` is `datapass-workbench` and the extension version, `provenance.source` is
  `datapass-workbench:<folder name>`. Runs recorded by the producer keep their own engine.
- `artifacts` add the files of the manifest's `datasets` folder: their path and sha256, never their bytes. No table
  data, no catalog file, no query result is written.
- The document is validated before it is saved.

## One engine per database

DuckDB-WASM (Mosaic Studio, in the browser) and native DuckDB (the Workbench runtime, `.datapass/data`) never share a
mutable database. Both formats carry text, names and hashes; neither side opens, attaches or copies the other's
database file. To get the same tables on the other side, run the cells there.
