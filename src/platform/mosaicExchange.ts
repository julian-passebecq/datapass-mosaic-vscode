/**
 * The Mosaic exchange contract `datapass.mosaic-exchange` version 1, shared with Mosaic Studio (the browser app that
 * runs DuckDB-WASM). Pure: validation, the files an import writes, and the document an export produces. Nothing here
 * reads, runs or attaches a database: cells are TEXT, artifacts are names and hashes, never data. See
 * docs/MOSAIC_EXCHANGE.md and schemas/mosaic-exchange.schema.json (kept in step with `validateExchange`).
 */

export const EXCHANGE_FORMAT = "datapass.mosaic-exchange";
export const EXCHANGE_VERSION = 1;
/** An exchange file larger than this is refused before parsing. */
export const EXCHANGE_MAX_BYTES = 5_000_000;
export const EXCHANGE_MAX_NOTEBOOKS = 50;
export const EXCHANGE_MAX_CELLS = 500;
export const EXCHANGE_MAX_SOURCE = 200_000;
/** Where an import writes, relative to the notebooks folder; and where it records what it imported. */
export const IMPORTED_FOLDER = "imported";
export const INTEROP_RECORD_DIR = ".datapass/interop";
/** The label of a run that happened in Mosaic Studio's browser engine. */
export const WASM_RUN_LABEL = "ran in Mosaic Studio (DuckDB-WASM), not re-run here";
export const NATIVE_RUN_LABEL = "ran on native DuckDB where it was exported, not re-run here";

export type ExchangeEngine = "duckdb-native" | "duckdb-wasm";
export type ExchangeCellKind = "sql" | "python" | "polars" | "markdown";
export type ExchangeRunStatus = "success" | "error" | "cancelled";

export interface ExchangeCell {
  id: string;
  kind: ExchangeCellKind;
  source: string;
  dependsOn: string[];
  [unknown: string]: unknown;
}

export interface ExchangeNotebook {
  id: string;
  title: string;
  cells: ExchangeCell[];
  [unknown: string]: unknown;
}

export interface ExchangeArtifact {
  id: string;
  kind: "table" | "file";
  name: string;
  sha256?: string;
  /** The cell that produced it; absent for an input file (a dataset). */
  producedBy?: { notebook: string; cell: string };
  [unknown: string]: unknown;
}

export interface ExchangeRun {
  /** A cell id; `notebook` is required when two notebooks use the same cell id. */
  cell: string;
  notebook?: string;
  engine: ExchangeEngine;
  at: string;
  status: ExchangeRunStatus;
  [unknown: string]: unknown;
}

export interface MosaicExchange {
  format: typeof EXCHANGE_FORMAT;
  version: typeof EXCHANGE_VERSION;
  producer: { app: string; version: string; [unknown: string]: unknown };
  exportedAt: string;
  runtime: { engine: ExchangeEngine; version: string; [unknown: string]: unknown };
  notebooks: ExchangeNotebook[];
  artifacts: ExchangeArtifact[];
  provenance: { source: string; commit?: string; runs: ExchangeRun[]; [unknown: string]: unknown };
  /** Opaque: kept as is on import and written back on export, never interpreted. */
  extensions: Record<string, unknown>;
  [unknown: string]: unknown;
}

const ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const SHA256 = /^[a-f0-9]{64}$/;
const ENGINES: readonly string[] = ["duckdb-native", "duckdb-wasm"];
const KINDS: readonly string[] = ["sql", "python", "polars", "markdown"];
const STATUSES: readonly string[] = ["success", "error", "cancelled"];
const KNOWN_TOP = new Set(["format", "version", "producer", "exportedAt", "runtime", "notebooks", "artifacts", "provenance", "extensions"]);

export type ExchangeResult = { ok: true; exchange: MosaicExchange } | { ok: false; errors: string[] };

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isText(value: unknown, max = 400): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= max;
}

function isDateTime(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.test(value)
    && !Number.isNaN(Date.parse(value));
}

/** Parse the bytes of an exchange file: size first, then JSON, then the contract. */
export function parseExchangeText(text: string): ExchangeResult {
  if (text.length > EXCHANGE_MAX_BYTES) return { ok: false, errors: [`An exchange file is at most ${EXCHANGE_MAX_BYTES / 1_000_000} MB.`] };
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (error) {
    return { ok: false, errors: [`Invalid JSON: ${error instanceof Error ? error.message : String(error)}`] };
  }
  return validateExchange(raw);
}

/** Every rule of version 1. Unknown fields are allowed (and kept); a broken reference or a cycle is not. */
export function validateExchange(raw: unknown): ExchangeResult {
  const errors: string[] = [];
  if (!isObject(raw)) return { ok: false, errors: ["An exchange document must be an object."] };
  if (raw.format !== EXCHANGE_FORMAT) errors.push(`format must be "${EXCHANGE_FORMAT}".`);
  if (raw.version !== EXCHANGE_VERSION) errors.push(`version must be ${EXCHANGE_VERSION}; this Workbench reads version 1 only.`);
  if (!isObject(raw.producer) || !isText(raw.producer.app, 100) || !isText(raw.producer.version, 100)) {
    errors.push("producer needs app and version (non-empty text).");
  }
  if (!isDateTime(raw.exportedAt)) errors.push("exportedAt must be an ISO 8601 date-time with a time zone.");
  if (!isObject(raw.runtime) || !ENGINES.includes(raw.runtime.engine as string) || !isText(raw.runtime.version, 100)) {
    errors.push('runtime needs engine ("duckdb-native" or "duckdb-wasm") and version.');
  }
  if (raw.extensions !== undefined && !isObject(raw.extensions)) errors.push("extensions must be an object.");

  const cells = new Map<string, Map<string, unknown>>(); // notebook id -> cell ids
  if (!Array.isArray(raw.notebooks) || raw.notebooks.length === 0 || raw.notebooks.length > EXCHANGE_MAX_NOTEBOOKS) {
    errors.push(`notebooks must hold 1 to ${EXCHANGE_MAX_NOTEBOOKS} notebooks.`);
  } else {
    raw.notebooks.forEach((notebook, index) => validateNotebook(notebook, index, cells, errors));
  }

  if (!Array.isArray(raw.artifacts)) {
    errors.push("artifacts must be a list (it may be empty).");
  } else {
    const ids = new Set<string>();
    raw.artifacts.forEach((artifact, index) => {
      const where = `artifacts[${index}]`;
      if (!isObject(artifact)) {
        errors.push(`${where} must be an object.`);
        return;
      }
      if (typeof artifact.id !== "string" || !ID.test(artifact.id)) errors.push(`${where}.id must match ${ID.source}.`);
      else if (ids.has(artifact.id)) errors.push(`${where}.id "${artifact.id}" is used twice.`);
      else ids.add(artifact.id);
      if (artifact.kind !== "table" && artifact.kind !== "file") errors.push(`${where}.kind must be "table" or "file".`);
      if (!isText(artifact.name, 300)) errors.push(`${where}.name is required.`);
      if (artifact.sha256 !== undefined && (typeof artifact.sha256 !== "string" || !SHA256.test(artifact.sha256))) {
        errors.push(`${where}.sha256 must be 64 lowercase hex characters.`);
      }
      if (artifact.producedBy !== undefined) {
        const by = artifact.producedBy;
        if (!isObject(by) || typeof by.notebook !== "string" || typeof by.cell !== "string") {
          errors.push(`${where}.producedBy needs notebook and cell.`);
        } else if (!cells.get(by.notebook)?.has(by.cell)) {
          errors.push(`${where}.producedBy names ${by.notebook}/${by.cell}, which is not in notebooks.`);
        }
      }
      for (const key of ["data", "rows", "content", "bytes"]) {
        if (key in artifact) errors.push(`${where}.${key}: artifacts carry names and hashes only, never data.`);
      }
    });
  }

  if (!isObject(raw.provenance) || !isText(raw.provenance.source, 400)) {
    errors.push("provenance needs source.");
  } else {
    const provenance = raw.provenance;
    if (provenance.commit !== undefined && !isText(provenance.commit, 100)) errors.push("provenance.commit must be text.");
    if (!Array.isArray(provenance.runs)) {
      errors.push("provenance.runs must be a list (it may be empty).");
    } else {
      provenance.runs.forEach((run, index) => validateRun(run, index, cells, errors));
    }
  }

  if (errors.length) return { ok: false, errors };
  const exchange = raw as unknown as MosaicExchange;
  return { ok: true, exchange: { ...exchange, extensions: (raw.extensions as Record<string, unknown> | undefined) ?? {} } };
}

function validateNotebook(notebook: unknown, index: number, cells: Map<string, Map<string, unknown>>, errors: string[]): void {
  const where = `notebooks[${index}]`;
  if (!isObject(notebook)) {
    errors.push(`${where} must be an object.`);
    return;
  }
  if (typeof notebook.id !== "string" || !ID.test(notebook.id)) {
    errors.push(`${where}.id must match ${ID.source}.`);
    return;
  }
  if (cells.has(notebook.id)) {
    errors.push(`${where}.id "${notebook.id}" is used twice.`);
    return;
  }
  if (!isText(notebook.title, 200)) errors.push(`${where}.title is required.`);
  const own = new Map<string, unknown>();
  cells.set(notebook.id, own);
  if (!Array.isArray(notebook.cells) || notebook.cells.length === 0 || notebook.cells.length > EXCHANGE_MAX_CELLS) {
    errors.push(`${where}.cells must hold 1 to ${EXCHANGE_MAX_CELLS} cells.`);
    return;
  }
  const edges = new Map<string, string[]>();
  notebook.cells.forEach((cell, cellIndex) => {
    const at = `${where}.cells[${cellIndex}]`;
    if (!isObject(cell)) {
      errors.push(`${at} must be an object.`);
      return;
    }
    if (typeof cell.id !== "string" || !ID.test(cell.id)) {
      errors.push(`${at}.id must match ${ID.source}.`);
      return;
    }
    if (own.has(cell.id)) {
      errors.push(`${at}.id "${cell.id}" is used twice in ${notebook.id}.`);
      return;
    }
    own.set(cell.id, cell);
    if (!KINDS.includes(cell.kind as string)) errors.push(`${at}.kind must be sql, python, polars or markdown.`);
    if (typeof cell.source !== "string" || cell.source.length > EXCHANGE_MAX_SOURCE) {
      errors.push(`${at}.source must be text of at most ${EXCHANGE_MAX_SOURCE.toLocaleString("en-US")} characters.`);
    }
    if (!Array.isArray(cell.dependsOn) || cell.dependsOn.some(dep => typeof dep !== "string")) {
      errors.push(`${at}.dependsOn must be a list of cell ids.`);
      return;
    }
    edges.set(cell.id, cell.dependsOn as string[]);
  });
  for (const [cell, deps] of edges) {
    for (const dep of deps) {
      if (dep === cell) errors.push(`${notebook.id}/${cell} depends on itself.`);
      else if (!own.has(dep)) errors.push(`${notebook.id}/${cell} depends on "${dep}", which is not a cell of ${notebook.id}.`);
    }
  }
  const cycle = findCycle(edges);
  if (cycle) errors.push(`${notebook.id} has a dependency cycle: ${cycle.join(" -> ")}.`);
}

function validateRun(run: unknown, index: number, cells: Map<string, Map<string, unknown>>, errors: string[]): void {
  const where = `provenance.runs[${index}]`;
  if (!isObject(run)) {
    errors.push(`${where} must be an object.`);
    return;
  }
  if (!ENGINES.includes(run.engine as string)) errors.push(`${where}.engine must be "duckdb-native" or "duckdb-wasm".`);
  if (!isDateTime(run.at)) errors.push(`${where}.at must be an ISO 8601 date-time.`);
  if (!STATUSES.includes(run.status as string)) errors.push(`${where}.status must be success, error or cancelled.`);
  if (typeof run.cell !== "string") {
    errors.push(`${where}.cell is required.`);
    return;
  }
  if (run.notebook !== undefined) {
    if (typeof run.notebook !== "string" || !cells.get(run.notebook)?.has(run.cell)) {
      errors.push(`${where} names ${String(run.notebook)}/${run.cell}, which is not in notebooks.`);
    }
    return;
  }
  const owners = [...cells].filter(([, own]) => own.has(run.cell as string)).length;
  if (owners === 0) errors.push(`${where}.cell "${run.cell}" is not in notebooks.`);
  if (owners > 1) errors.push(`${where}.cell "${run.cell}" is in several notebooks: add notebook.`);
}

/** A dependency cycle as a path (first node repeated at the end), or undefined. Edges point to dependencies. */
export function findCycle(edges: ReadonlyMap<string, readonly string[]>): string[] | undefined {
  const state = new Map<string, 1 | 2>(); // 1 visiting, 2 done
  const stack: string[] = [];
  const visit = (node: string): string[] | undefined => {
    if (state.get(node) === 2) return undefined;
    if (state.get(node) === 1) return [...stack.slice(stack.indexOf(node)), node];
    state.set(node, 1);
    stack.push(node);
    for (const next of edges.get(node) ?? []) {
      if (!edges.has(next)) continue;
      const found = visit(next);
      if (found) return found;
    }
    stack.pop();
    state.set(node, 2);
    return undefined;
  };
  for (const node of edges.keys()) {
    const found = visit(node);
    if (found) return found;
  }
  return undefined;
}

/** The run label shown next to a cell: an imported run is history, never re-run here. */
export function runLabel(engine: ExchangeEngine): string {
  return engine === "duckdb-wasm" ? WASM_RUN_LABEL : NATIVE_RUN_LABEL;
}

export function cellExtension(kind: ExchangeCellKind): string {
  return kind === "sql" ? ".sql" : kind === "markdown" ? ".md" : ".py";
}

/** One imported notebook: the native files it becomes and the record kept in .datapass/interop/<id>.json. */
export interface ImportedNotebookPlan {
  id: string;
  /** Workspace-relative folder: <notebooks>/imported/<id>. */
  folder: string;
  files: { cell: string; kind: ExchangeCellKind; path: string; content: string }[];
  /** README.md of the folder: where the cells came from, their order, dependencies and past runs. */
  readme: { path: string; content: string };
  record: { path: string; content: InteropRecord };
}

/**
 * What .datapass/interop/<id>.json holds: the exchange header and this notebook as received (unknown fields
 * included), and which file holds which cell. Export reads it back, so a round trip keeps ids, order, dependencies,
 * runs and extensions.
 */
export interface InteropRecord {
  format: "datapass.mosaic-exchange-import";
  version: 1;
  importedAt: string;
  notebook: string;
  folder: string;
  files: { cell: string; kind: ExchangeCellKind; path: string }[];
  /** The exchange document with only this notebook, its artifacts and its runs; cell sources removed (they live in the files). */
  exchange: RecordedExchange;
}

/** A cell without its source (the source is the file). */
export interface ExchangeCellHeader {
  id: string;
  kind: ExchangeCellKind;
  dependsOn: string[];
  [unknown: string]: unknown;
}

export interface ExchangeNotebookHeader {
  id: string;
  title: string;
  cells: ExchangeCellHeader[];
  [unknown: string]: unknown;
}

export interface RecordedExchange {
  format: typeof EXCHANGE_FORMAT;
  version: typeof EXCHANGE_VERSION;
  producer: MosaicExchange["producer"];
  exportedAt: string;
  runtime: MosaicExchange["runtime"];
  notebooks: [ExchangeNotebookHeader];
  artifacts: ExchangeArtifact[];
  provenance: MosaicExchange["provenance"];
  extensions: Record<string, unknown>;
  [unknown: string]: unknown;
}

/** The files an import writes. It runs nothing; the caller creates each file exclusively (never overwrites). */
export function planImport(exchange: MosaicExchange, notebooksFolder: string, importedAt: string): ImportedNotebookPlan[] {
  const base = notebooksFolder.replace(/\\/g, "/").replace(/\/+$/, "") || "notebooks";
  return exchange.notebooks.map(notebook => {
    const folder = `${base}/${IMPORTED_FOLDER}/${notebook.id}`;
    const width = String(notebook.cells.length).length < 2 ? 2 : String(notebook.cells.length).length;
    const files = notebook.cells.map((cell, index) => ({
      cell: cell.id,
      kind: cell.kind,
      path: `${folder}/${String(index + 1).padStart(width, "0")}-${cell.id}${cellExtension(cell.kind)}`,
      content: cell.source
    }));
    const runs = runsOf(exchange, notebook.id);
    const { cells, ...notebookRest } = notebook;
    const header: ExchangeNotebookHeader = {
      ...notebookRest,
      cells: cells.map(({ source: _source, ...cell }) => cell)
    };
    const record: InteropRecord = {
      format: "datapass.mosaic-exchange-import",
      version: 1,
      importedAt,
      notebook: notebook.id,
      folder,
      files: files.map(({ cell, kind, path }) => ({ cell, kind, path })),
      exchange: {
        ...exchange,
        notebooks: [header],
        artifacts: exchange.artifacts.filter(artifact => !artifact.producedBy || artifact.producedBy.notebook === notebook.id),
        provenance: { ...exchange.provenance, runs }
      }
    };
    return {
      id: notebook.id,
      folder,
      files,
      readme: { path: `${folder}/README.md`, content: importReadme(exchange, notebook, files, runs) },
      record: { path: `${INTEROP_RECORD_DIR}/${notebook.id}.json`, content: record }
    };
  });
}

function runsOf(exchange: MosaicExchange, notebookId: string): ExchangeRun[] {
  const own = new Set(exchange.notebooks.find(notebook => notebook.id === notebookId)?.cells.map(cell => cell.id) ?? []);
  return exchange.provenance.runs
    .filter(run => run.notebook === notebookId || (run.notebook === undefined && own.has(run.cell)));
}

function importReadme(exchange: MosaicExchange, notebook: ExchangeNotebook,
  files: ImportedNotebookPlan["files"], runs: ExchangeRun[]): string {
  const lines = [
    `# ${notebook.title}`,
    "",
    `Imported from ${exchange.producer.app} ${exchange.producer.version} (exported ${exchange.exportedAt}, ` +
      `${exchange.runtime.engine} ${exchange.runtime.version}). Source: ${exchange.provenance.source}` +
      `${exchange.provenance.commit ? ` at ${exchange.provenance.commit}` : ""}.`,
    "",
    "Nothing was executed on import. Each cell is a native file; run a SQL file with Mosaic's Run active SQL",
    "(real local DuckDB). Python and Polars files run only after you enable trusted local Python yourself.",
    "",
    "| # | Cell | Kind | Depends on | File |",
    "| --- | --- | --- | --- | --- |",
    ...files.map((file, index) => {
      const deps = notebook.cells[index].dependsOn;
      return `| ${index + 1} | ${file.cell} | ${file.kind} | ${deps.length ? deps.join(", ") : "-"} | ${file.path.split("/").pop()} |`;
    })
  ];
  if (runs.length) {
    lines.push("", "## Runs recorded by the producer", "");
    for (const run of runs) lines.push(`- ${run.cell}: ${run.status} at ${run.at}, ${runLabel(run.engine)}.`);
  }
  lines.push("", "DuckDB-WASM and this workspace's native DuckDB never share a database file: tables named in the",
    "exchange are names and hashes only. Recreate them here by running the cells or importing the datasets.", "");
  return lines.join("\n");
}

/** One notebook to export: from an import record (round trip) or from a plain folder of native files. */
export interface ExportNotebookInput {
  id: string;
  title: string;
  cells: { id: string; kind: ExchangeCellKind; source: string; dependsOn: string[] }[];
  /** The import record when the notebook came from an exchange: its unknown fields, artifacts and runs come back. */
  record?: InteropRecord;
}

export interface ExportInput {
  producerVersion: string;
  exportedAt: string;
  /** The native DuckDB version of the runtime, or "unknown" when the runtime is not running. */
  duckdbVersion: string;
  source: string;
  notebooks: ExportNotebookInput[];
  /** Files of the workspace (datasets): names and hashes only. */
  files: { id: string; name: string; sha256: string }[];
}

/** A version 1 document from this Workbench: engine duckdb-native, names and hashes only, no data. */
export function buildExport(input: ExportInput): MosaicExchange {
  const notebooks: ExchangeNotebook[] = [];
  let artifacts: ExchangeArtifact[] = [];
  const runs: { run: ExchangeRun; notebook: string }[] = [];
  let extensions: Record<string, unknown> = {};
  let unknown: Record<string, unknown> = {};
  let producerFields: Record<string, unknown> = {};
  let runtimeFields: Record<string, unknown> = {};
  let provenanceFields: Record<string, unknown> = {};
  for (const notebook of input.notebooks) {
    const header = notebook.record?.exchange.notebooks[0];
    const headerCells = new Map((header?.cells ?? []).map(cell => [cell.id, cell]));
    const { cells: _cells, id: _id, title: _title, ...headerRest } = header ?? { cells: [], id: "", title: "" };
    notebooks.push({
      ...headerRest,
      id: notebook.id,
      title: notebook.title,
      cells: notebook.cells.map(cell => ({ ...(headerCells.get(cell.id) ?? {}), ...cell, dependsOn: [...cell.dependsOn] }))
    });
    if (notebook.record) {
      artifacts.push(...notebook.record.exchange.artifacts.filter(artifact => !artifacts.some(known => known.id === artifact.id)));
      const own = new Set(notebook.cells.map(cell => cell.id));
      runs.push(...notebook.record.exchange.provenance.runs
        .filter(run => own.has(run.cell))
        .map(run => ({ run, notebook: notebook.id })));
      extensions = { ...extensions, ...notebook.record.exchange.extensions };
      producerFields = { ...producerFields, ...notebook.record.exchange.producer };
      runtimeFields = { ...runtimeFields, ...notebook.record.exchange.runtime };
      const { source: _source, commit: _commit, runs: _runs, ...extraProvenance } = notebook.record.exchange.provenance;
      provenanceFields = { ...provenanceFields, ...extraProvenance };
      const recorded = notebook.record.exchange as unknown as Record<string, unknown>;
      for (const key of Object.keys(recorded)) if (!KNOWN_TOP.has(key)) unknown = { ...unknown, [key]: recorded[key] };
    }
  }
  // A run names its notebook when its cell id is used by several exported notebooks.
  const owners = (cell: string) => notebooks.filter(notebook => notebook.cells.some(candidate => candidate.id === cell)).length;
  const exportedRuns = runs.map(({ run, notebook }) =>
    run.notebook === undefined && owners(run.cell) > 1 ? { ...run, notebook } : run);
  // Drop deleted producers before merging current datasets, so a dangling historical artifact cannot hide a file.
  artifacts = artifacts.filter(artifact => !artifact.producedBy || notebooks.some(notebook =>
    notebook.id === artifact.producedBy?.notebook && notebook.cells.some(cell => cell.id === artifact.producedBy?.cell)));
  for (const file of [...input.files].sort((a, b) => a.name.localeCompare(b.name))) {
    // Refresh a plain file's hash by path, not by an id derived from its stem. A produced artifact with changed
    // bytes stays historical: the current file gets its own id and never inherits an unverified producer claim.
    // Refresh every current record before considering a historical hash match. Otherwise a file reverting to
    // earlier bytes can match history first and leave a later current-file record stale.
    let refreshed = false;
    for (let index = 0; index < artifacts.length; index++) {
      const artifact = artifacts[index];
      if (artifact.kind === "file" && artifact.name === file.name && !artifact.producedBy) {
        artifacts[index] = { ...artifact, sha256: file.sha256 };
        refreshed = true;
      }
    }
    if (refreshed || artifacts.some(artifact => artifact.kind === "file" && artifact.name === file.name &&
      artifact.sha256 === file.sha256)) continue;
    let id = file.id;
    let counter = 2;
    while (artifacts.some(artifact => artifact.id === id)) {
      const suffix = `-${counter++}`;
      id = `${file.id.slice(0, 64 - suffix.length)}${suffix}`;
    }
    artifacts.push({ id, kind: "file", name: file.name, sha256: file.sha256 });
  }
  return {
    ...unknown,
    format: EXCHANGE_FORMAT,
    version: EXCHANGE_VERSION,
    producer: { ...producerFields, app: "datapass-workbench", version: input.producerVersion },
    exportedAt: input.exportedAt,
    runtime: { ...runtimeFields, engine: "duckdb-native", version: input.duckdbVersion },
    notebooks,
    artifacts,
    provenance: { ...provenanceFields, source: input.source, runs: exportedRuns },
    extensions
  };
}

/**
 * An imported notebook for export, with its files' current text (`sources`: path -> text; a missing path is a deleted
 * cell, dropped together with the dependencies on it).
 */
export function notebookFromRecord(record: InteropRecord, sources: ReadonlyMap<string, string>): ExportNotebookInput {
  const header = record.exchange.notebooks[0];
  const deps = new Map(header.cells.map(cell => [cell.id, cell.dependsOn]));
  const cells = record.files
    .filter(file => sources.has(file.path))
    .map(file => ({ id: file.cell, kind: file.kind, source: sources.get(file.path) ?? "", dependsOn: [...(deps.get(file.cell) ?? [])] }));
  const present = new Set(cells.map(cell => cell.id));
  for (const cell of cells) cell.dependsOn = cell.dependsOn.filter(dep => present.has(dep));
  return { id: record.notebook, title: header.title, cells, record };
}

/** Exchange-safe id from a file or folder name. */
export function exchangeId(name: string, fallback = "item"): string {
  const id = name.replace(/\.[^.]*$/, "").replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^[-_]+|-+$/g, "").slice(0, 64);
  return id && ID.test(id) ? id : fallback;
}

/** The kind of a native file exported as a cell; undefined for files that are not cells. */
export function cellKindOfFile(fileName: string, source: string): ExchangeCellKind | undefined {
  const lower = fileName.toLowerCase();
  if (lower.endsWith(".sql")) return "sql";
  if (lower.endsWith(".md")) return "markdown";
  if (lower.endsWith(".py")) return /^\s*(import polars|from polars\b)/m.test(source) ? "polars" : "python";
  return undefined;
}

/** Unknown top-level fields of a document, kept by an import. */
export function unknownTopLevel(exchange: MosaicExchange): string[] {
  return Object.keys(exchange).filter(key => !KNOWN_TOP.has(key));
}
