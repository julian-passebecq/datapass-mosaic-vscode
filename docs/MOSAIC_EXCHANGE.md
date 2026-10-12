# Mosaic exchange (`datapass.mosaic-exchange`, version 1)

The file format that moves notebook work between **Mosaic Studio** (the browser app, DuckDB-WASM) and the
**Datapass Workbench** (this extension, native DuckDB). It carries cells as text, the names and hashes of what they
produced, and the history of past runs. It never carries data and it is never executed on import.

- Schema: `schemas/mosaic-exchange.schema.json` (written by hand).
- Validator, import plan and export: `src/platform/mosaicExchange.ts` (pure; the schema and the validator are kept in
  step, and the validator also checks what a schema cannot: unique ids, references and cycles).
- Commands: **Datapass: Import Mosaic Exchange** (`datapass.interop.import`) and **Datapass: Export Mosaic Exchange**
  (`datapass.interop.export`), in `src/build/interopCommands.ts`.
- Examples: `content/interop/examples/` (one exported by Mosaic Studio on DuckDB-WASM, one by the Workbench).
- Tests: `scripts/suite/mosaic_exchange.test.mjs` (round trip of every example, refusals, no overwrite),
  `scripts/json_schemas_smoke.mjs`, and a step of `src/test/hostSuite.ts`.

Mosaic Studio lives in its own repository (`datapass-mosaicstudio`); this document is the contract both sides follow.

## Document

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

## Import (Workbench)

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

## Export (Workbench)

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
mutable database. The exchange carries text, names and hashes; neither side opens, attaches or copies the other's
database file. To get the same tables on the other side, run the cells there.
