import { createHash } from "node:crypto";
import * as vscode from "vscode";
import {
  EXCHANGE_MAX_BYTES,
  INTEROP_RECORD_DIR,
  buildExport,
  cellKindOfFile,
  exchangeId,
  notebookFromRecord,
  parseExchangeText,
  planImport,
  validateExchange,
  type ExportNotebookInput,
  type InteropRecord
} from "../platform/mosaicExchange";
import { safeRelativeParts } from "../platform/workspacePaths";
import { readProjectManifest } from "../project/projectManifest";
import type { RuntimeManager } from "../runtimeManager";
import { exists } from "../workspaceFiles";
import { createExclusive, fileNames, workspaceRoot } from "./buildFiles";

/**
 * The Mosaic exchange (`datapass.mosaic-exchange` v1) with Mosaic Studio: import writes cells as native files and runs
 * nothing; export writes names and hashes, never data. DuckDB-WASM's database and this workspace's native DuckDB
 * catalog are never shared: nothing here opens, attaches or copies a database file.
 */
export function registerInteropCommands(context: vscode.ExtensionContext, runtime: RuntimeManager): vscode.Disposable[] {
  return [
    vscode.commands.registerCommand("datapass.interop.import", () => importExchange()),
    vscode.commands.registerCommand("datapass.interop.export", () => exportExchange(context, runtime))
  ];
}

const decoder = new TextDecoder();

async function importExchange(): Promise<void> {
  const root = workspaceRoot();
  if (!root) {
    void vscode.window.showWarningMessage("Open a folder before importing a Mosaic exchange: its cells become files in that folder.");
    return;
  }
  const picked = await vscode.window.showOpenDialog({
    canSelectMany: false,
    openLabel: "Import exchange",
    title: "Import a Mosaic exchange (datapass.mosaic-exchange v1). Cells become files; nothing is run.",
    filters: { "Mosaic exchange": ["json"] }
  });
  const source = picked?.[0];
  if (!source) return;
  const stat = await vscode.workspace.fs.stat(source);
  if (stat.size > EXCHANGE_MAX_BYTES) {
    void vscode.window.showErrorMessage(`An exchange file is at most ${EXCHANGE_MAX_BYTES / 1_000_000} MB.`);
    return;
  }
  const parsed = parseExchangeText(decoder.decode(await vscode.workspace.fs.readFile(source)));
  if (!parsed.ok) {
    const shown = parsed.errors.slice(0, 4).join(" ");
    void vscode.window.showErrorMessage(`Not imported: ${shown}${parsed.errors.length > 4 ? ` (+${parsed.errors.length - 4} more)` : ""}`);
    return;
  }
  const manifest = await readProjectManifest();
  const notebooks = safeRelativeParts(manifest.manifest?.assets?.notebooks, "notebooks").join("/");
  const plans = planImport(parsed.exchange, notebooks, new Date().toISOString());

  // Never overwrite: a notebook already imported (its folder or record exists) is refused before anything is written.
  const taken: string[] = [];
  for (const plan of plans) {
    if (await exists(uriOf(root, plan.folder)) || await exists(uriOf(root, plan.record.path))) taken.push(plan.id);
  }
  if (taken.length) {
    void vscode.window.showErrorMessage(
      `Not imported: ${taken.join(", ")} ${taken.length === 1 ? "is" : "are"} already in this workspace (${notebooks}/imported/ or ${INTEROP_RECORD_DIR}/). Nothing was replaced.`
    );
    return;
  }
  let cells = 0;
  for (const plan of plans) {
    for (const file of [...plan.files, { path: plan.readme.path, content: plan.readme.content }]) {
      if (!(await createExclusive(uriOf(root, file.path), file.content))) throw new Error(`${file.path} appeared meanwhile; it was not replaced.`);
    }
    cells += plan.files.length;
    await createExclusive(uriOf(root, plan.record.path), JSON.stringify(plan.record.content, null, 2) + "\n");
  }
  const wasm = parsed.exchange.provenance.runs.filter(run => run.engine === "duckdb-wasm").length;
  void vscode.window.showInformationMessage(
    `Imported ${plans.length} notebook${plans.length === 1 ? "" : "s"} (${cells} cells) as files under ${notebooks}/imported/. Nothing was run.` +
      (wasm ? ` ${wasm} recorded run${wasm === 1 ? "" : "s"}: ran in Mosaic Studio (DuckDB-WASM), not re-run here.` : "")
  );
  await vscode.window.showTextDocument(uriOf(root, plans[0].readme.path), { preview: false });
}

async function readRecords(root: vscode.Uri): Promise<InteropRecord[]> {
  const records: InteropRecord[] = [];
  for (const entry of await fileNames(uriOf(root, INTEROP_RECORD_DIR))) {
    if (!entry.isFile || !entry.name.endsWith(".json")) continue;
    try {
      const record = JSON.parse(decoder.decode(await vscode.workspace.fs.readFile(uriOf(root, `${INTEROP_RECORD_DIR}/${entry.name}`)))) as InteropRecord;
      if (record?.format === "datapass.mosaic-exchange-import" && Array.isArray(record.files)) records.push(record);
    } catch {
      // A broken record is skipped; the files it described are still plain files.
    }
  }
  return records;
}

/** An imported notebook with its current file contents; a deleted cell file drops the cell and the edges to it. */
async function readRecordNotebook(root: vscode.Uri, record: InteropRecord): Promise<ExportNotebookInput> {
  const sources = new Map<string, string>();
  for (const file of record.files) {
    const uri = uriOf(root, file.path);
    if (await exists(uri)) sources.set(file.path, decoder.decode(await vscode.workspace.fs.readFile(uri)));
  }
  return notebookFromRecord(record, sources);
}

/** A plain folder of .sql, .py and .md files, one cell each in name order, without dependencies. */
async function notebookFromFolder(root: vscode.Uri, folder: vscode.Uri): Promise<ExportNotebookInput | undefined> {
  const cells: ExportNotebookInput["cells"] = [];
  const used = new Set<string>();
  const entries = (await fileNames(folder)).filter(entry => entry.isFile).map(entry => entry.name).sort();
  for (const name of entries) {
    const source = decoder.decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(folder, name)));
    const kind = cellKindOfFile(name, source);
    if (!kind) continue;
    let id = exchangeId(name, `cell-${cells.length + 1}`);
    while (used.has(id)) id = `${id.slice(0, 60)}-${cells.length + 1}`;
    used.add(id);
    cells.push({ id, kind, source, dependsOn: [] });
  }
  if (!cells.length) return undefined;
  const name = folder.path.split("/").filter(Boolean).pop() ?? "notebook";
  return { id: exchangeId(name, "notebook"), title: name, cells };
}

async function exportExchange(context: vscode.ExtensionContext, runtime: RuntimeManager): Promise<void> {
  const root = workspaceRoot();
  if (!root) {
    void vscode.window.showWarningMessage("Open a folder before exporting a Mosaic exchange.");
    return;
  }
  const records = await readRecords(root);
  const FOLDER = "folder";
  const choices = await vscode.window.showQuickPick(
    [
      ...records.map(record => ({
        label: record.exchange.notebooks[0].title,
        description: `imported ${record.importedAt.slice(0, 10)} · ${record.folder}`,
        id: record.notebook,
        picked: true
      })),
      { label: "A folder of SQL, Python and Markdown files…", description: "one cell per file, in name order", id: FOLDER, picked: records.length === 0 }
    ],
    { canPickMany: true, title: "Export a Mosaic exchange: which notebooks?", placeHolder: "Cells are exported as text; tables only by name, never data." }
  );
  if (!choices?.length) return;

  const notebooks: ExportNotebookInput[] = [];
  for (const choice of choices) {
    if (choice.id !== FOLDER) {
      const record = records.find(candidate => candidate.notebook === choice.id);
      if (record) notebooks.push(await readRecordNotebook(root, record));
      continue;
    }
    const manifest = await readProjectManifest();
    const folder = await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      defaultUri: vscode.Uri.joinPath(root, ...safeRelativeParts(manifest.manifest?.assets?.notebooks, "notebooks")),
      openLabel: "Export this folder"
    });
    if (!folder?.[0]) return;
    if (!folder[0].path.startsWith(root.path)) {
      void vscode.window.showErrorMessage("Export a folder of this workspace.");
      return;
    }
    const notebook = await notebookFromFolder(root, folder[0]);
    if (!notebook) {
      void vscode.window.showErrorMessage("That folder has no .sql, .py or .md file to export.");
      return;
    }
    if (notebooks.some(known => known.id === notebook.id)) notebook.id = `${notebook.id.slice(0, 56)}-folder`;
    notebooks.push(notebook);
  }
  const nonEmpty = notebooks.filter(notebook => notebook.cells.length > 0);
  if (!nonEmpty.length) {
    void vscode.window.showErrorMessage("Nothing to export: the chosen notebooks have no cell files left.");
    return;
  }

  const manifest = await readProjectManifest();
  const datasetsParts = safeRelativeParts(manifest.manifest?.assets?.datasets, "datasets");
  const files: { id: string; name: string; sha256: string }[] = [];
  for (const entry of await fileNames(vscode.Uri.joinPath(root, ...datasetsParts))) {
    if (!entry.isFile || entry.name.startsWith(".")) continue;
    const bytes = await vscode.workspace.fs.readFile(vscode.Uri.joinPath(root, ...datasetsParts, entry.name));
    files.push({ id: exchangeId(`dataset-${entry.name}`, `dataset-${files.length + 1}`), name: `${datasetsParts.join("/")}/${entry.name}`,
      sha256: createHash("sha256").update(bytes).digest("hex") });
  }
  let duckdbVersion = "unknown";
  try {
    duckdbVersion = (await runtime.labs.mosaic.engineInfo())?.duckdbVersion ?? "unknown";
  } catch {
    // The runtime is optional for an export; the version stays "unknown".
  }
  const folderName = root.path.split("/").filter(Boolean).pop() ?? "workspace";
  const document = buildExport({
    producerVersion: String((context.extension.packageJSON as { version?: unknown }).version ?? "0.0.0"),
    exportedAt: new Date().toISOString(),
    duckdbVersion,
    source: `datapass-workbench:${folderName}`,
    notebooks: nonEmpty,
    files
  });
  const check = validateExchange(document);
  if (!check.ok) {
    void vscode.window.showErrorMessage(`Export refused: ${check.errors.slice(0, 3).join(" ")}`);
    return;
  }
  const target = await vscode.window.showSaveDialog({
    defaultUri: vscode.Uri.joinPath(root, `${nonEmpty.length === 1 ? nonEmpty[0].id : folderName}.mosaic-exchange.json`),
    filters: { "Mosaic exchange": ["json"] },
    saveLabel: "Export"
  });
  if (!target) return;
  await vscode.workspace.fs.writeFile(target, new TextEncoder().encode(JSON.stringify(document, null, 2) + "\n"));
  void vscode.window.showInformationMessage(
    `Exported ${nonEmpty.length} notebook${nonEmpty.length === 1 ? "" : "s"} (${nonEmpty.reduce((sum, notebook) => sum + notebook.cells.length, 0)} cells) and ${document.artifacts.length} artifact names. No data was written.`
  );
}

function uriOf(root: vscode.Uri, relative: string): vscode.Uri {
  return vscode.Uri.joinPath(root, ...relative.split("/"));
}
