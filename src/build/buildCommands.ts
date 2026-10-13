import * as vscode from "vscode";
import { decodeCsvBytes, suggestBronzeAsset, validateBronzeAsset } from "../platform/csvImport";
import { FILE_IMPORT_MAX_BYTES, importFormat } from "../platform/mosaicTools";
import { safeRelativeParts } from "../platform/workspacePaths";
import {
  DATAPASS_MANIFEST_PATH,
  createBlankProjectManifest,
  readProjectManifest
} from "../project/projectManifest";
import type { PythonTrustController } from "../pythonTrustController";
import type { RuntimeManager } from "../runtimeManager";
import { exists } from "../workspaceFiles";
import {
  BUILD_FILE_KINDS,
  BUILD_FOLDERS,
  DATASET_EXTENSIONS,
  datasetExtension,
  datasetNameError,
  fileKindSpec,
  fileNameForKind,
  nextFreeName,
  titleFromFileName,
  type BuildFileKind
} from "./buildModel";
import { createExclusive, fileNames, workspaceRoot } from "./buildFiles";
import { registerInteropCommands } from "./interopCommands";

/** Build: a blank workspace, the learner's own files and datasets, and the Mosaic exchange (interopCommands.ts). */
export function registerBuildCommands(
  context: vscode.ExtensionContext,
  runtime: RuntimeManager,
  pythonTrust: PythonTrustController
): vscode.Disposable[] {
  return [
    vscode.commands.registerCommand("datapass.build.newWorkspace", () => newWorkspace(runtime)),
    vscode.commands.registerCommand("datapass.build.newFile", (arg?: unknown) => newFile(pythonTrust, kindArgument(arg))),
    vscode.commands.registerCommand("datapass.build.importDataset", () => importDataset(runtime)),
    ...registerInteropCommands(context, runtime)
  ];
}

function kindArgument(arg: unknown): BuildFileKind | undefined {
  const kind = typeof arg === "string" ? arg : arg && typeof arg === "object" ? (arg as { kind?: unknown }).kind : undefined;
  return BUILD_FILE_KINDS.some(spec => spec.kind === kind) ? kind as BuildFileKind : undefined;
}

async function requireFolder(action: string): Promise<vscode.Uri | undefined> {
  const root = workspaceRoot();
  if (root) return root;
  const choice = await vscode.window.showWarningMessage(`Open a folder before you ${action}: Datapass keeps your files and catalog in it.`, "Open Folder");
  if (choice === "Open Folder") await vscode.commands.executeCommand("workbench.action.files.openFolder");
  return undefined;
}

/** A blank workspace: manifest (no demo tables, trusted Python off) and empty folders. Refuses an existing project. */
async function newWorkspace(runtime: RuntimeManager): Promise<void> {
  const root = await requireFolder("create a Build workspace");
  if (!root) return;
  const manifestUri = vscode.Uri.joinPath(root, ...DATAPASS_MANIFEST_PATH.split("/"));
  const refuse = async () => {
    const choice = await vscode.window.showWarningMessage(
      "This folder already has a Datapass project (.datapass/project.json). New workspace never replaces it.",
      "Open project.json"
    );
    if (choice === "Open project.json") await vscode.window.showTextDocument(manifestUri);
  };
  if (await exists(manifestUri)) return refuse();

  const folderName = root.path.split("/").filter(Boolean).pop() ?? "data-project";
  const manifest = createBlankProjectManifest(folderName);
  if (!(await createExclusive(manifestUri, JSON.stringify(manifest, null, 2) + "\n"))) return refuse();
  for (const folder of BUILD_FOLDERS) await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(root, folder));

  const seeded = await exists(vscode.Uri.joinPath(root, ".datapass", "data", "workspace.duckdb"));
  const running = ["running", "starting"].includes(runtime.snapshot().status);
  const notes = [
    "Blank Datapass workspace ready: notebooks/, datasets/ and notes/ are empty, the catalog starts without demo tables, trusted local Python is off."
  ];
  if (seeded) notes.push("The catalog already in .datapass/data keeps its tables: Build never deletes data.");
  if (running) notes.push("Restart the Datapass runtime to apply the blank catalog.");
  // Mosaic (and its empty-state panel) opens now: a notification's promise stays pending until it is dismissed.
  await vscode.commands.executeCommand("datapass.openMosaic");
  const choice = await vscode.window.showInformationMessage(notes.join(" "), "New file", "Import dataset");
  if (choice === "New file") await vscode.commands.executeCommand("datapass.build.newFile");
  if (choice === "Import dataset") await vscode.commands.executeCommand("datapass.build.importDataset");
}

async function pickKind(pythonTrust: PythonTrustController): Promise<BuildFileKind | undefined> {
  const trust = await pythonTrust.resolve();
  const picked = await vscode.window.showQuickPick(
    BUILD_FILE_KINDS.map(spec => ({
      label: spec.label,
      description: spec.description,
      detail: spec.needsTrustedPython
        ? `Trusted local Python: ${trust.effective ? "on" : "off"}. ${trust.effective ? "" : "The file is created; it runs only after you enable trusted Python yourself."}`.trim()
        : undefined,
      fileKind: spec.kind
    })),
    { title: "New file", placeHolder: "What kind of file?" }
  );
  return picked?.fileKind;
}

/** A new SQL, Python, Polars or Markdown file: a safe single name, the kind's extension, created only when absent. */
async function newFile(pythonTrust: PythonTrustController, requested?: BuildFileKind): Promise<void> {
  const root = await requireFolder("create a file");
  if (!root) return;
  const kind = requested ?? await pickKind(pythonTrust);
  if (!kind) return;
  const spec = fileKindSpec(kind);
  const manifest = await readProjectManifest();
  const folderParts = spec.folder === "notes" ? ["notes"] : safeRelativeParts(manifest.manifest?.assets?.notebooks, "notebooks");
  const folder = vscode.Uri.joinPath(root, ...folderParts);
  const taken = new Set((await fileNames(folder)).map(entry => entry.name.toLowerCase()));

  let suggestion = nextFreeName(spec.defaultName, taken);
  for (;;) {
    const name = await vscode.window.showInputBox({
      title: `New ${spec.label} file in ${folderParts.join("/")}/`,
      prompt: `A file name; ${spec.extension} is added when missing. Existing files are never replaced.`,
      value: suggestion,
      valueSelection: [0, suggestion.length - spec.extension.length],
      validateInput: value => {
        const result = fileNameForKind(value, kind);
        return "error" in result ? result.error : undefined;
      }
    });
    if (name === undefined) return;
    const result = fileNameForKind(name, kind);
    if ("error" in result) return;
    const uri = vscode.Uri.joinPath(folder, result.fileName);
    if (await createExclusive(uri, spec.header(titleFromFileName(result.fileName)))) {
      await vscode.window.showTextDocument(uri, { preview: false });
      if (spec.needsTrustedPython) {
        const trust = await pythonTrust.resolve();
        if (!trust.effective) {
          void vscode.window.showInformationMessage(
            `${folderParts.join("/")}/${result.fileName} created. ${trust.reason} Datapass never turns it on for you: use the trusted Python switch in Mosaic when you decide to.`
          );
        }
      }
      return;
    }
    const choice = await vscode.window.showWarningMessage(
      `${folderParts.join("/")}/${result.fileName} already exists. It was not changed.`,
      "Open existing",
      "Choose another name"
    );
    if (choice === "Open existing") {
      await vscode.window.showTextDocument(uri, { preview: false });
      return;
    }
    if (choice !== "Choose another name") return;
    taken.add(result.fileName.toLowerCase());
    suggestion = nextFreeName(result.fileName, taken);
  }
}

/** Copy a CSV, Parquet or JSON file into datasets/ (never replacing one), then optionally into a new bronze table. */
async function importDataset(runtime: RuntimeManager): Promise<void> {
  const root = await requireFolder("import a dataset");
  if (!root) return;
  const manifest = await readProjectManifest();
  const datasetsParts = safeRelativeParts(manifest.manifest?.assets?.datasets, "datasets");
  const datasets = vscode.Uri.joinPath(root, ...datasetsParts);
  const picked = await vscode.window.showOpenDialog({
    canSelectMany: false,
    canSelectFolders: false,
    openLabel: "Copy into datasets",
    title: `Import a dataset into ${datasetsParts.join("/")}/ (a copy; the original is not changed)`,
    filters: { "Datasets": DATASET_EXTENSIONS.map(extension => extension.slice(1)) }
  });
  const source = picked?.[0];
  if (!source) return;
  const sourceName = source.path.split("/").pop() ?? "dataset.csv";
  if (!datasetExtension(sourceName)) {
    void vscode.window.showErrorMessage(`Import a ${DATASET_EXTENSIONS.join(", ")} file.`);
    return;
  }
  const bytes = await vscode.workspace.fs.readFile(source);
  if (!bytes.byteLength || bytes.byteLength > FILE_IMPORT_MAX_BYTES) {
    void vscode.window.showErrorMessage(`Datasets are 1 byte to ${FILE_IMPORT_MAX_BYTES / 1_000_000} MB; ${sourceName} is ${bytes.byteLength.toLocaleString("en-US")} bytes.`);
    return;
  }

  const taken = (await fileNames(datasets)).map(entry => entry.name);
  let target = vscode.Uri.joinPath(datasets, sourceName);
  let name = sourceName;
  const inside = source.toString() === target.toString();
  if (!inside) {
    if (datasetNameError(sourceName, taken)) {
      const chosen = await vscode.window.showInputBox({
        title: `Import ${sourceName}`,
        prompt: `${datasetsParts.join("/")}/${sourceName} cannot be used (it exists or the name is not safe). Existing files are never replaced.`,
        value: nextFreeName(sourceName.replace(/[^A-Za-z0-9 ._-]+/g, "-").replace(/^[^A-Za-z0-9]+/, ""), taken),
        validateInput: value => datasetNameError(value, taken)
      });
      if (!chosen) return;
      name = chosen.trim();
      target = vscode.Uri.joinPath(datasets, name);
    }
    if (!(await createExclusive(target, bytes))) {
      void vscode.window.showWarningMessage(`${datasetsParts.join("/")}/${name} appeared meanwhile; it was not replaced.`);
      return;
    }
  }

  const relative = `${datasetsParts.join("/")}/${name}`;
  if (runtime.snapshot().status !== "running") {
    void vscode.window.showInformationMessage(
      `${inside ? "" : `Copied to ${relative}. `}Start the Datapass runtime, then use Mosaic > Import file… to load it into a new bronze table.`
    );
    return;
  }
  const choice = await vscode.window.showInformationMessage(
    `${inside ? relative : `Copied to ${relative}`}. Also load it into a new bronze table of the local catalog?`,
    "Import into bronze"
  );
  if (choice !== "Import into bronze") return;
  await importIntoBronze(runtime, name, bytes);
}

/** The existing Mosaic bronze import (new table only, never overwrites), fed with the copied file's content. */
async function importIntoBronze(runtime: RuntimeManager, fileName: string, bytes: Uint8Array): Promise<void> {
  const format = importFormat(fileName);
  if (!format) return;
  const existing = (runtime.snapshot().catalog ?? []).map(asset => asset.name);
  const asset = await vscode.window.showInputBox({
    title: `Import ${fileName} into bronze`,
    prompt: format === "csv"
      ? "New bronze table name. Imports never overwrite; every column is stored as text."
      : "New bronze table name. Imports never overwrite; column types come from the file.",
    value: suggestBronzeAsset(fileName, existing),
    valueSelection: [7, Number.MAX_SAFE_INTEGER],
    validateInput: value => validateBronzeAsset(value, existing)
  });
  if (!asset) return;
  try {
    const result = format === "csv"
      ? await runtime.labs.mosaic.importCsv(asset.trim(), decodeCsvBytes(bytes), fileName)
      : await runtime.labs.mosaic.importFile(asset.trim(), format, Buffer.from(bytes).toString("base64"), fileName);
    void vscode.window.showInformationMessage(`Imported ${result.rows_imported} rows into ${result.asset}.`);
  } catch (error) {
    void vscode.window.showErrorMessage(error instanceof Error ? error.message : String(error));
  }
}

