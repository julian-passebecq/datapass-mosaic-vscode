import * as vscode from "vscode";
import { copyWithoutOverwrite, exists, readText } from "./factoryState";
import { BI_FOLDER, BI_LIMITS, BI_MODEL_FILE, BI_SCRIPTS_FOLDER, isBiPath, orderScripts } from "./platform/biRun";
import type { BiViewState } from "./webview/contracts";

export function biRoot(): vscode.Uri | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  return root ? vscode.Uri.joinPath(root, BI_FOLDER) : undefined;
}

/** A workspace-relative path the webview asked to open, accepted only inside bi/. */
export function biFileUri(relative: string): vscode.Uri | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root || !isBiPath(relative)) return undefined;
  return vscode.Uri.joinPath(root, ...relative.replaceAll("\\", "/").split("/").filter(Boolean));
}

async function scriptFiles(): Promise<{ name: string; path: string; uri: vscode.Uri }[]> {
  const folder = biFileUri(BI_SCRIPTS_FOLDER);
  if (!folder || !(await exists(folder))) return [];
  const entries = await vscode.workspace.fs.readDirectory(folder);
  const files = entries
    .filter(([name, type]) => (type & vscode.FileType.File) !== 0 && name.toLowerCase().endsWith(".sql"))
    .map(([name]) => ({ name, path: `${BI_SCRIPTS_FOLDER}/${name}`, uri: vscode.Uri.joinPath(folder, name) }));
  return orderScripts(files);
}

export async function loadBiState(): Promise<BiViewState> {
  const root = biRoot();
  const state: BiViewState = {
    folder: BI_FOLDER, exists: false, scripts: [], modelPath: BI_MODEL_FILE, modelExists: false, warnings: []
  };
  if (!root || !(await exists(root))) return state;
  const files = await scriptFiles();
  const warnings: string[] = [];
  if (files.length > BI_LIMITS.scripts) warnings.push(`Only the first ${BI_LIMITS.scripts} scripts of ${BI_SCRIPTS_FOLDER}/ run.`);
  const model = await readBiModel();
  return {
    ...state,
    exists: true,
    scripts: files.slice(0, BI_LIMITS.scripts).map(({ name, path }) => ({ name, path })),
    modelExists: model.exists,
    modelError: model.error,
    warnings
  };
}

/** Every warehouse script, in name order; open editors win over the files on disk. */
export async function collectBiScripts(): Promise<{ scripts: { path: string; text: string }[]; warnings: string[] }> {
  const scripts: { path: string; text: string }[] = [];
  const warnings: string[] = [];
  for (const file of (await scriptFiles()).slice(0, BI_LIMITS.scripts)) {
    const text = await readText(file.uri);
    if (text.length > BI_LIMITS.scriptChars) {
      warnings.push(`${file.path} skipped: longer than ${BI_LIMITS.scriptChars} characters`);
      continue;
    }
    scripts.push({ path: file.path, text });
  }
  return { scripts, warnings };
}

/** The star model file, parsed. The runtime validates its content; here only JSON errors are reported. */
export async function readBiModel(): Promise<{ exists: boolean; model?: unknown; error?: string }> {
  const uri = biFileUri(BI_MODEL_FILE);
  if (!uri || !(await exists(uri))) return { exists: false };
  const text = await readText(uri);
  if (text.length > BI_LIMITS.modelChars) return { exists: true, error: `${BI_MODEL_FILE} is larger than 100 KB.` };
  try {
    return { exists: true, model: JSON.parse(text) as unknown };
  } catch (error) {
    return { exists: true, error: `${BI_MODEL_FILE} is not valid JSON: ${error instanceof Error ? error.message : String(error)}` };
  }
}

export async function copyBiSamples(extensionUri: vscode.Uri): Promise<vscode.Uri | undefined> {
  const root = biRoot();
  if (!root) return undefined;
  await copyWithoutOverwrite(vscode.Uri.joinPath(extensionUri, "samples", "bi-lab"), root);
  return root;
}
