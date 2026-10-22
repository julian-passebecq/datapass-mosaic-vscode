/**
 * Mosaic Studio's notebook interchange: Jupyter `.ipynb` (nbformat 4) with DataPass fields in `metadata.datapass`, as
 * written and read by Studio's `py/service/notebook_io.py` (export_notebook / import_notebook). Pure: validation, the
 * files an import writes and the notebook an export produces. Nothing here runs a cell, opens a database or keeps an
 * output: cells are TEXT. See docs/MOSAIC_EXCHANGE.md.
 *
 * Cell kinds follow Studio's mapping:
 *   markdown (no attachments)                          <-> note     -> .md
 *   code with metadata.datapass.kind "sql" or "%%sql"  <-> sql      -> .sql (the SQL, without the magic line)
 *   code, kernel language python                       <-> jupyter  -> .py
 *   code with metadata.datapass.kind "runtime-model"   <-> python   -> .model.json (an allowlisted model name and its
 *                                                                      inputs, not Python code)
 *   anything else (raw, other languages, attachments,  <-> inert    -> .inert.json (the original cell, outputs removed,
 *     oversize source)                                                 exported back unchanged, never run)
 */
import { IMPORTED_FOLDER, INTEROP_RECORD_DIR, exchangeId, findCycle } from "./mosaicExchange";

/** Studio's own bounds (notebook_io.py), so whatever is imported here can go back to Studio unchanged. */
export const STUDIO_MAX_BYTES = 4 * 1024 * 1024;
export const STUDIO_MAX_CELLS = 50;
export const STUDIO_MAX_CODE = 20_000;
export const STUDIO_MAX_NOTE = 8_000;
export const STUDIO_MAX_TITLE = 120;
export const STUDIO_MAX_INERT_JSON = 64 * 1024;
export const STUDIO_MAX_DEPS = 12;
export const STUDIO_RECORD_FORMAT = "datapass.studio-ipynb-import";
/** The label of anything Studio ran: history, never a local result. */
export const STUDIO_RUN_LABEL = "ran in Mosaic Studio, not re-run here";

export type StudioCellKind = "note" | "sql" | "jupyter" | "python" | "inert";

const WB_ID = /^[a-z][a-zA-Z0-9_-]{0,79}$/;
const NB_ID = /^[a-zA-Z0-9_-]{1,64}$/;
const TABLE = /^[a-z][a-z0-9_]{0,62}$/;
const RESERVED = new Set(["constructor", "prototype", "__proto__"]);
const RUNNABLE: readonly StudioCellKind[] = ["sql", "jupyter", "python"];

export function isStudioCellId(value: unknown): value is string {
  return typeof value === "string" && WB_ID.test(value) && !RESERVED.has(value);
}

export function studioExtension(kind: StudioCellKind): string {
  return kind === "sql" ? ".sql" : kind === "note" ? ".md" : kind === "jupyter" ? ".py" : kind === "python" ? ".model.json" : ".inert.json";
}

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function sourceOf(cell: Json): string {
  const src = cell.source;
  return Array.isArray(src) ? src.map(String).join("") : typeof src === "string" ? src : "";
}

/** Studio's _title: the first non-empty line without heading marks, or the fallback. */
export function studioTitle(text: string, fallback: string): string {
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim().replace(/^#+/, "").trim().replace(/^-+/, "").trim();
    if (line && !line.startsWith("%%")) return line.slice(0, STUDIO_MAX_TITLE);
  }
  return fallback;
}

/** One cell as this Workbench keeps it: a native file plus what the file cannot hold. */
export interface StudioCell {
  id: string;
  kind: StudioCellKind;
  title: string;
  /** The file's text. */
  content: string;
  dependsOn: string[];
  /** The original cell type and metadata (unknown keys and metadata.datapass included). */
  cellType: "code" | "markdown" | "raw";
  metadata: Json;
  /** The cell's original nbformat id, when it had one. */
  nbId?: string;
  /** Producer facts kept as history: execution count, outputs not imported, why a cell is inert. */
  executionCount?: number;
  outputsDropped?: number;
  reason?: string;
}

export interface StudioNotebook {
  id: string;
  title: string;
  nbformat: string;
  language: string;
  /** The notebook metadata as received (kernelspec, language_info, datapass and any other key). */
  metadata: Json;
  cells: StudioCell[];
}

export type StudioParseResult = { ok: true; notebook: StudioNotebook } | { ok: false; errors: string[] };

/** Read a Studio-style .ipynb: size, JSON, nbformat 4, Studio's cell mapping, safe ids, dependencies. Runs nothing. */
export function parseStudioNotebook(text: string, fileName: string): StudioParseResult {
  if (new TextEncoder().encode(text).length > STUDIO_MAX_BYTES) return { ok: false, errors: [`A notebook is at most ${STUDIO_MAX_BYTES / 1024 / 1024} MB.`] };
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (error) {
    return { ok: false, errors: [`Invalid JSON: ${error instanceof Error ? error.message : String(error)}`] };
  }
  const errors: string[] = [];
  if (!isObject(raw)) return { ok: false, errors: ["A notebook must be a JSON object."] };
  if (raw.nbformat !== 4) errors.push("Only Jupyter nbformat 4 notebooks are read (nbformat must be 4).");
  if (!Number.isInteger(raw.nbformat_minor) || (raw.nbformat_minor as number) < 0) errors.push("nbformat_minor must be a non-negative integer.");
  if (!isObject(raw.metadata)) errors.push("metadata must be an object.");
  if (!Array.isArray(raw.cells) || raw.cells.length === 0) errors.push("cells must hold at least one cell.");
  else if (raw.cells.length > STUDIO_MAX_CELLS) errors.push(`The notebook has ${raw.cells.length} cells; at most ${STUDIO_MAX_CELLS} are read (Mosaic Studio's limit).`);
  if (errors.length) return { ok: false, errors };
  const meta = raw.metadata as Json;
  const kernel = isObject(meta.kernelspec) ? meta.kernelspec : {};
  const info = isObject(meta.language_info) ? meta.language_info : {};
  const language = String(kernel.language || info.name || "python").toLowerCase().slice(0, 40);

  const cells: StudioCell[] = [];
  const used = new Set<string>();
  const declared = new Map<string, unknown>();
  const newId = (preferred: unknown, kind: StudioCellKind, index: number): string => {
    const candidates: string[] = [];
    if (isStudioCellId(preferred)) candidates.push(preferred);
    else if (typeof preferred === "string" && NB_ID.test(preferred)) candidates.push(`c-${preferred}`.slice(0, 80));
    candidates.push(`${kind}-${index + 1}`);
    for (const candidate of candidates) {
      if (isStudioCellId(candidate) && !used.has(candidate)) {
        used.add(candidate);
        return candidate;
      }
    }
    let n = 2;
    while (used.has(`${kind}-${index + 1}-${n}`)) n += 1;
    used.add(`${kind}-${index + 1}-${n}`);
    return `${kind}-${index + 1}-${n}`;
  };

  (raw.cells as unknown[]).forEach((value, index) => {
    const at = `cells[${index}]`;
    if (!isObject(value)) {
      errors.push(`${at} must be an object.`);
      return;
    }
    const cell = value;
    const cellType = cell.cell_type;
    if (cellType !== "code" && cellType !== "markdown" && cellType !== "raw") {
      errors.push(`${at}.cell_type must be code, markdown or raw.`);
      return;
    }
    if (typeof cell.source !== "string" && !(Array.isArray(cell.source) && cell.source.every(line => typeof line === "string"))) {
      errors.push(`${at}.source must be text or a list of text lines.`);
      return;
    }
    if (cell.metadata !== undefined && !isObject(cell.metadata)) {
      errors.push(`${at}.metadata must be an object.`);
      return;
    }
    if (cell.id !== undefined && (typeof cell.id !== "string" || !NB_ID.test(cell.id))) {
      errors.push(`${at}.id must match ${NB_ID.source}.`);
      return;
    }
    const metadata = (cell.metadata as Json | undefined) ?? {};
    const dp = isObject(metadata.datapass) ? metadata.datapass : {};
    if (dp.cellId !== undefined && !isStudioCellId(dp.cellId)) {
      errors.push(`${at}.metadata.datapass.cellId must match ${WB_ID.source}.`);
      return;
    }
    const preferred = dp.cellId ?? cell.id;
    if (isStudioCellId(preferred) && declared.has(preferred)) {
      errors.push(`${at}: cell id "${preferred}" is used twice.`);
      return;
    }
    if (isStudioCellId(preferred)) declared.set(preferred, cell);
    const source = sourceOf(cell);
    const outputs = Array.isArray(cell.outputs) ? cell.outputs.length : 0;
    const base = {
      cellType,
      metadata,
      ...(typeof cell.id === "string" ? { nbId: cell.id } : {}),
      ...(Number.isInteger(cell.execution_count) ? { executionCount: cell.execution_count as number } : {}),
      ...(outputs ? { outputsDropped: outputs } : {})
    } as const;
    const inert = (reason: string): void => {
      const original: Json = { ...cell };
      if ("outputs" in original) original.outputs = [];
      if ("execution_count" in original) original.execution_count = null;
      const content = JSON.stringify(original, null, 1) + "\n";
      if (content.length > STUDIO_MAX_INERT_JSON) {
        errors.push(`${at} (${reason}) is above ${STUDIO_MAX_INERT_JSON / 1024} KB and cannot be kept inert.`);
        return;
      }
      cells.push({ ...base, id: newId(preferred, "inert", index), kind: "inert", title: studioTitle(source, `${cellType} cell`), content, dependsOn: [], reason });
    };
    const deps = Array.isArray(dp.dependsOn) ? dp.dependsOn : dp.dependsOn === undefined ? [] : undefined;
    if (cellType === "markdown") {
      if (cell.attachments && isObject(cell.attachments) && Object.keys(cell.attachments).length) return inert("markdown with attachments");
      if (source.length > STUDIO_MAX_NOTE) return inert("markdown above 8,000 characters");
      cells.push({ ...base, id: newId(preferred, "note", index), kind: "note", title: studioTitle(source, "Note"), content: source, dependsOn: [] });
      return;
    }
    if (cellType === "raw") return inert("raw cell");
    const first = source.trim() ? source.trimStart().split("\n", 1)[0].trim() : "";
    let entry: StudioCell | undefined;
    if (dp.kind === "runtime-model" && isStudioCellId(dp.model) && isObject(dp.inputs)) {
      const model: Json = { model: dp.model, inputs: dp.inputs };
      if (typeof dp.outputTable === "string" && TABLE.test(dp.outputTable)) model.outputTable = dp.outputTable;
      entry = { ...base, id: newId(preferred, "python", index), kind: "python", title: titleOf(dp, "Python model run"),
        content: JSON.stringify(model, null, 2) + "\n", dependsOn: [] };
    } else if (dp.kind === "sql" || first === "%%sql") {
      const trimmed = source.trimStart();
      const sql = first === "%%sql" ? (trimmed.includes("\n") ? trimmed.slice(trimmed.indexOf("\n") + 1) : "") : source;
      if (sql.length > STUDIO_MAX_CODE) return inert("SQL above 20,000 characters");
      entry = { ...base, id: newId(preferred, "sql", index), kind: "sql", title: titleOf(dp, studioTitle(sql, "SQL query")), content: sql, dependsOn: [] };
    } else if (language !== "python") {
      return inert(`code in kernel language '${language}' is not run by the workbench`);
    } else if (source.length > STUDIO_MAX_CODE) {
      return inert("Python source above 20,000 characters");
    } else {
      entry = { ...base, id: newId(preferred, "jupyter", index), kind: "jupyter", title: titleOf(dp, studioTitle(source, "Python cell")), content: source, dependsOn: [] };
    }
    if (!deps || !deps.every(dep => typeof dep === "string")) {
      errors.push(`${at}.metadata.datapass.dependsOn must be a list of cell ids.`);
      return;
    }
    if (deps.length > STUDIO_MAX_DEPS) errors.push(`${entry.id} has ${deps.length} dependencies; at most ${STUDIO_MAX_DEPS}.`);
    entry.dependsOn = [...new Set(deps as string[])];
    cells.push(entry);
  });
  if (errors.length) return { ok: false, errors };
  errors.push(...dependencyErrors(cells));
  if (errors.length) return { ok: false, errors };

  const stem = fileName.replace(/\\/g, "/").split("/").pop() ?? "notebook";
  const id = exchangeId(stem, "notebook");
  const firstNote = cells.find(cell => cell.kind === "note" && cell.content.trim());
  return {
    ok: true,
    notebook: {
      id,
      title: firstNote ? firstNote.title : stem.replace(/\.ipynb$/i, ""),
      nbformat: `4.${raw.nbformat_minor as number}`,
      language,
      metadata: meta,
      cells
    }
  };
}

function titleOf(dp: Json, fallback: string): string {
  return (typeof dp.title === "string" && dp.title.trim() ? dp.title : fallback).slice(0, STUDIO_MAX_TITLE);
}

/** Dependencies name runnable cells of the same notebook, never themselves, and form no cycle. */
function dependencyErrors(cells: readonly Pick<StudioCell, "id" | "kind" | "dependsOn">[]): string[] {
  const errors: string[] = [];
  const kinds = new Map(cells.map(cell => [cell.id, cell.kind]));
  for (const cell of cells) {
    for (const dep of cell.dependsOn) {
      if (dep === cell.id) errors.push(`${cell.id} depends on itself.`);
      else if (!kinds.has(dep)) errors.push(`${cell.id} depends on "${dep}", which is not a cell of this notebook.`);
      else if (!RUNNABLE.includes(kinds.get(dep) as StudioCellKind)) errors.push(`${cell.id} depends on "${dep}", which is a ${kinds.get(dep)} cell (not runnable).`);
    }
  }
  if (errors.length) return errors;
  const cycle = findCycle(new Map(cells.map(cell => [cell.id, cell.dependsOn])));
  return cycle ? [`The dependencies form a cycle: ${cycle.join(" -> ")}.`] : [];
}

/** What .datapass/interop/<id>.json holds for an imported Studio notebook; export reads it back. */
export interface StudioRecord {
  format: typeof STUDIO_RECORD_FORMAT;
  version: 1;
  importedAt: string;
  notebook: string;
  title: string;
  folder: string;
  sourceName: string;
  nbformat: string;
  language: string;
  metadata: Json;
  files: { cell: string; kind: StudioCellKind; path: string }[];
  /** Every cell without its text (the text is the file). */
  cells: (Omit<StudioCell, "content"> & { path: string })[];
}

export interface StudioImportPlan {
  id: string;
  folder: string;
  files: { cell: string; kind: StudioCellKind; path: string; content: string }[];
  readme: { path: string; content: string };
  record: { path: string; content: StudioRecord };
}

/** The files an import writes. It runs nothing; the caller creates each file exclusively (never overwrites). */
export function planStudioImport(notebook: StudioNotebook, notebooksFolder: string, importedAt: string, sourceName: string): StudioImportPlan {
  const base = notebooksFolder.replace(/\\/g, "/").replace(/\/+$/, "") || "notebooks";
  const folder = `${base}/${IMPORTED_FOLDER}/${notebook.id}`;
  const width = Math.max(2, String(notebook.cells.length).length);
  const files = notebook.cells.map((cell, index) => ({
    cell: cell.id,
    kind: cell.kind,
    path: `${folder}/${String(index + 1).padStart(width, "0")}-${cell.id}${studioExtension(cell.kind)}`,
    content: cell.content
  }));
  const record: StudioRecord = {
    format: STUDIO_RECORD_FORMAT,
    version: 1,
    importedAt,
    notebook: notebook.id,
    title: notebook.title,
    folder,
    sourceName,
    nbformat: notebook.nbformat,
    language: notebook.language,
    metadata: notebook.metadata,
    files: files.map(({ cell, kind, path }) => ({ cell, kind, path })),
    cells: notebook.cells.map(({ content: _content, ...cell }, index) => ({ ...cell, path: files[index].path }))
  };
  return {
    id: notebook.id,
    folder,
    files,
    readme: { path: `${folder}/README.md`, content: studioReadme(notebook, files, sourceName) },
    record: { path: `${INTEROP_RECORD_DIR}/${notebook.id}.json`, content: record }
  };
}

function studioReadme(notebook: StudioNotebook, files: StudioImportPlan["files"], sourceName: string): string {
  const exportedAt = isObject(notebook.metadata.datapass) ? notebook.metadata.datapass.exportedAt : undefined;
  const lines = [
    `# ${notebook.title}`,
    "",
    `Imported from the Jupyter notebook ${sourceName} (nbformat ${notebook.nbformat}, Mosaic Studio's interchange` +
      `${typeof exportedAt === "string" ? `, exported ${exportedAt}` : ""}).`,
    "",
    "Nothing was executed on import. Each cell is a native file: run a SQL file with Mosaic's Run active SQL (real",
    "local DuckDB); a Python file runs only after you enable trusted local Python yourself. A .model.json file names an",
    "allowlisted Mosaic Studio model and its inputs: it is not Python code and is not run here. A .inert.json file is",
    "the original cell kept verbatim (outputs removed): it is never run and is exported back unchanged.",
    "",
    "| # | Cell | Kind | Depends on | File |",
    "| --- | --- | --- | --- | --- |",
    ...notebook.cells.map((cell, index) =>
      `| ${index + 1} | ${cell.id} | ${cell.kind} | ${cell.dependsOn.length ? cell.dependsOn.join(", ") : "-"} | ${files[index].path.split("/").pop()} |`)
  ];
  const history = notebook.cells.flatMap(cell => {
    const dp = isObject(cell.metadata.datapass) ? cell.metadata.datapass : {};
    const facts: string[] = [];
    if (cell.executionCount !== undefined) facts.push(`execution count ${cell.executionCount}`);
    if (typeof dp.resultSha256 === "string") facts.push(`result hash ${dp.resultSha256.slice(0, 12)}…`);
    if (cell.outputsDropped) facts.push(`${cell.outputsDropped} output${cell.outputsDropped === 1 ? "" : "s"} not imported (source only)`);
    if (cell.reason) facts.push(`inert: ${cell.reason}`);
    return facts.length ? [`- ${cell.id}: ${facts.join("; ")}.`] : [];
  });
  if (history.length) lines.push("", `## Recorded by the producer (${STUDIO_RUN_LABEL})`, "", ...history);
  lines.push("", "Mosaic Studio's DuckDB-WASM database and this workspace's native DuckDB never share a database file: a",
    "table a cell publishes (outputTable) is a name only. Recreate it here by running the cells yourself.", "");
  return lines.join("\n");
}

/** One cell to export: its kind, file text and dependencies, plus the recorded metadata when it was imported. */
export interface StudioExportCell {
  id: string;
  kind: StudioCellKind;
  title: string;
  content: string;
  dependsOn: string[];
  metadata?: Json;
  nbId?: string;
}

export type StudioExportResult = { ok: true; notebook: Json; text: string } | { ok: false; errors: string[] };

/**
 * A standard nbformat 4.5 notebook that Studio's import_notebook accepts unchanged: source only (no outputs,
 * execution counts null), DataPass fields in metadata.datapass, recorded unknown metadata written back.
 */
export function buildStudioNotebook(cells: readonly StudioExportCell[], exportedAt: string, metadata: Json = {}): StudioExportResult {
  const errors: string[] = [];
  if (cells.length === 0) errors.push("Nothing to export: no cell.");
  if (cells.length > STUDIO_MAX_CELLS) errors.push(`At most ${STUDIO_MAX_CELLS} cells go to Mosaic Studio (${cells.length} chosen).`);
  const seen = new Set<string>();
  for (const cell of cells) {
    if (!isStudioCellId(cell.id)) errors.push(`Cell id "${cell.id}" must match ${WB_ID.source}.`);
    else if (seen.has(cell.id)) errors.push(`Cell id "${cell.id}" is used twice.`);
    seen.add(cell.id);
    if (cell.dependsOn.length > STUDIO_MAX_DEPS) errors.push(`${cell.id} has more than ${STUDIO_MAX_DEPS} dependencies.`);
    if ((cell.kind === "sql" || cell.kind === "jupyter") && cell.content.length > STUDIO_MAX_CODE) errors.push(`${cell.id} is above ${STUDIO_MAX_CODE.toLocaleString("en-US")} characters.`);
    if (cell.kind === "note" && cell.content.length > STUDIO_MAX_NOTE) errors.push(`${cell.id} is above ${STUDIO_MAX_NOTE.toLocaleString("en-US")} characters.`);
  }
  if (!errors.length) errors.push(...dependencyErrors(cells));
  if (errors.length) return { ok: false, errors };

  const nbIds = new Set<string>();
  const out: Json[] = [];
  cells.forEach((cell, index) => {
    const recorded = cell.metadata ?? {};
    const dpIn = isObject(recorded.datapass) ? recorded.datapass : {};
    const title = (cell.title.trim() ? cell.title : studioTitle(cell.content, `${cell.kind} cell`)).slice(0, STUDIO_MAX_TITLE);
    const { kind: _kind, model: _model, inputs: _inputs, outputTable: recordedTable, chart: _chart, ...dpRest } = dpIn;
    const dp: Json = { ...dpRest, cellId: cell.id, title, dependsOn: [...cell.dependsOn] };
    if (dpIn.chart !== undefined && cell.kind === "sql") dp.chart = dpIn.chart;
    if (recordedTable !== undefined && cell.kind === "jupyter") dp.outputTable = recordedTable;
    const pickNbId = (): string => {
      const wanted = [cell.nbId, cell.id].find(value => typeof value === "string" && NB_ID.test(value) && !nbIds.has(value));
      let id = wanted ?? `cell-${index + 1}`;
      let suffix = 2;
      while (nbIds.has(id)) id = `cell-${index + 1}-${suffix++}`;
      nbIds.add(id);
      return id;
    };
    const meta = { ...recorded, datapass: dp };
    if (cell.kind === "inert") {
      let original: unknown;
      try {
        original = JSON.parse(cell.content);
      } catch {
        errors.push(`${cell.id}: the inert cell file is not JSON.`);
        return;
      }
      if (!isObject(original) || !["code", "markdown", "raw"].includes(original.cell_type as string)) {
        errors.push(`${cell.id}: the inert cell file is not a notebook cell.`);
        return;
      }
      const verbatim: Json = { ...original };
      if (typeof verbatim.id !== "string" || !NB_ID.test(verbatim.id) || nbIds.has(verbatim.id)) verbatim.id = pickNbId();
      else nbIds.add(verbatim.id);
      if (verbatim.cell_type === "code") {
        verbatim.outputs = [];
        verbatim.execution_count = null;
      }
      if (!isObject(verbatim.metadata)) verbatim.metadata = {};
      out.push(verbatim);
      return;
    }
    if (cell.kind === "note") {
      out.push({ cell_type: "markdown", id: pickNbId(), metadata: meta, source: lines(cell.content) });
      return;
    }
    let source = cell.content;
    if (cell.kind === "sql") {
      dp.kind = "sql";
      source = `%%sql\n${cell.content}`;
    } else if (cell.kind === "jupyter") {
      dp.kind = "python";
    } else {
      let model: unknown;
      try {
        model = JSON.parse(cell.content);
      } catch {
        errors.push(`${cell.id}: the model file is not JSON.`);
        return;
      }
      if (!isObject(model) || !isStudioCellId(model.model) || !isObject(model.inputs)) {
        errors.push(`${cell.id}: the model file needs model (an id) and inputs (an object).`);
        return;
      }
      if (model.outputTable !== undefined && (typeof model.outputTable !== "string" || !TABLE.test(model.outputTable))) {
        errors.push(`${cell.id}: outputTable must match ${TABLE.source}.`);
        return;
      }
      Object.assign(dp, { kind: "runtime-model", model: model.model, inputs: model.inputs });
      if (model.outputTable !== undefined) dp.outputTable = model.outputTable;
      source = "# DataPass allowlisted runtime model (datapass.runtime/1), not Python code.\n" +
        `# model: ${model.model}\n# inputs: ${pythonJson(model.inputs)}\n`;
    }
    out.push({ cell_type: "code", execution_count: null, id: pickNbId(), metadata: meta, outputs: [], source: lines(source) });
  });
  if (errors.length) return { ok: false, errors };
  const kernelspec = isObject(metadata.kernelspec) ? metadata.kernelspec : { display_name: "Python 3", language: "python", name: "python3" };
  const languageInfo = isObject(metadata.language_info) ? metadata.language_info : { name: "python" };
  const notebook: Json = {
    cells: out,
    metadata: {
      ...metadata,
      datapass: { exportedAt, format: "datapass.notebook", version: 1 },
      kernelspec,
      language_info: languageInfo
    },
    nbformat: 4,
    nbformat_minor: 5
  };
  return { ok: true, notebook, text: sortedJson(notebook) + "\n" };
}

/** Python's json.dumps(value, sort_keys=True) for plain JSON values, so model cells read like Studio's. */
function pythonJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(pythonJson).join(", ")}]`;
  if (isObject(value)) return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}: ${pythonJson(value[key])}`).join(", ")}}`;
  return JSON.stringify(value) ?? "null";
}

/** nbformat's multi-line source: lines with their line endings. */
function lines(text: string): string[] {
  return text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
}

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortValue);
  if (isObject(value)) return Object.fromEntries(Object.keys(value).sort().map(key => [key, sortValue(value[key])]));
  return value;
}

function sortedJson(value: unknown): string {
  return JSON.stringify(sortValue(value), null, 1);
}

/** An imported Studio notebook for export, with its files' current text; a deleted file drops its cell and the edges to it. */
export function studioCellsFromRecord(record: StudioRecord, sources: ReadonlyMap<string, string>): StudioExportCell[] {
  const cells = record.cells
    .filter(cell => sources.has(cell.path))
    .map(cell => ({ id: cell.id, kind: cell.kind, title: cell.title, content: sources.get(cell.path) ?? "", dependsOn: [...cell.dependsOn],
      metadata: cell.metadata, ...(cell.nbId ? { nbId: cell.nbId } : {}) }));
  const present = new Set(cells.map(cell => cell.id));
  for (const cell of cells) cell.dependsOn = cell.dependsOn.filter(dep => present.has(dep));
  return cells;
}

/** The Studio kind of a native file of a plain folder; undefined for files that are not cells. */
export function studioKindOfFile(fileName: string): StudioCellKind | undefined {
  const lower = fileName.toLowerCase();
  if (lower.endsWith(".model.json")) return "python";
  if (lower.endsWith(".inert.json")) return "inert";
  if (lower.endsWith(".sql")) return "sql";
  if (lower.endsWith(".md")) return "note";
  if (lower.endsWith(".py")) return "jupyter";
  return undefined;
}

/**
 * Cells from plain files or exchange cells: ids made Studio-safe (a lowercase letter first; dependencies follow the
 * renamed ids), titles from the text. Exchange kinds map as sql -> sql, python/polars -> jupyter, markdown -> note.
 */
export function studioCellsFromPlain(items: readonly { name: string; kind: StudioCellKind; content: string; dependsOn?: readonly string[] }[]): StudioExportCell[] {
  const used = new Set<string>();
  const renamed = new Map<string, string>();
  const cells = items.map((item, index) => {
    const stem = item.name.replace(/\.(model|inert)\.json$/i, "").replace(/\.[^.]*$/, "").replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^[-_]+|[-_]+$/g, "");
    let id = isStudioCellId(stem.slice(0, 64)) ? stem.slice(0, 64) : `${item.kind}-${stem || index + 1}`.slice(0, 64).replace(/[-_]+$/, "");
    if (!isStudioCellId(id)) id = `${item.kind}-${index + 1}`;
    while (used.has(id)) id = `${id.slice(0, 58)}-${index + 1}`;
    used.add(id);
    renamed.set(item.name, id);
    const fallback = item.kind === "sql" ? "SQL query" : item.kind === "note" ? "Note" : item.kind === "jupyter" ? "Python cell" : `${item.kind} cell`;
    return { id, kind: item.kind, title: studioTitle(item.kind === "inert" || item.kind === "python" ? "" : item.content, fallback), content: item.content,
      dependsOn: [...(item.dependsOn ?? [])] };
  });
  for (const cell of cells) cell.dependsOn = cell.dependsOn.map(dep => renamed.get(dep) ?? dep).filter(dep => used.has(dep));
  return cells;
}

/** Exchange cell kinds as Studio kinds. */
export function studioKindOfExchange(kind: "sql" | "python" | "polars" | "markdown"): StudioCellKind {
  return kind === "sql" ? "sql" : kind === "markdown" ? "note" : "jupyter";
}
