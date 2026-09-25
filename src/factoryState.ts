import * as vscode from "vscode";
import {
  FACTORY_FLAVORS,
  FACTORY_FOLDER,
  FACTORY_LIMITS,
  PIPELINE_NAME,
  classifyFactoryPath,
  designView,
  parseJsonDocument,
  pipelineRelativePath
} from "./platform/factoryRun";
import { SQLPOOL_LIMITS, flavorHint } from "./platform/sqlpoolRun";
import { DATABRICKS_LIMITS, JOB_NAME, jobDesignView } from "./platform/databricksRun";
import type { FactoryFlavor, FactoryViewState } from "./webview/contracts";

const MAX_FILES = 400;
const MAX_DEPTH = 6;

/** Lab files sent with a simulation, keyed as the runtime resolves references. */
export interface FactoryFilesPayload {
  pipelines: Record<string, unknown>;
  datasets: Record<string, unknown>;
  procedures: Record<string, string>;
  notebooks: Record<string, string>;
}

interface FactoryFile {
  relative: string;
  uri: vscode.Uri;
}

export function factoryRoot(): vscode.Uri | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  return root ? vscode.Uri.joinPath(root, FACTORY_FOLDER) : undefined;
}

/** Every pipeline of the lab, parsed for the canvas (the runtime validates them when they run). */
export async function loadFactoryState(): Promise<FactoryViewState> {
  const root = factoryRoot();
  const state: FactoryViewState = {
    folder: FACTORY_FOLDER, exists: false, pipelines: [], poolScripts: [], warnings: [],
    databricks: { exists: false, jobs: [], notebooks: [], sqlFiles: [], warnings: [] }
  };
  if (!root || !(await exists(root))) return state;
  state.exists = true;
  const files = await listFiles(root, state.warnings);
  for (const file of files) {
    const role = classifyFactoryPath(file.relative);
    if (file.relative.startsWith("databricks/")) state.databricks.exists = true;
    if (role?.role === "dbxJob") {
      if (!JOB_NAME.test(role.name)) {
        state.databricks.warnings.push(`${file.relative}: job file names use letters, digits, space, _, . and - (at most 100)`);
      } else if (state.databricks.jobs.length < DATABRICKS_LIMITS.jobs) {
        state.databricks.jobs.push(jobDesignView(role.name, `${FACTORY_FOLDER}/${file.relative}`, await readText(file.uri)));
      }
      continue;
    }
    if (role?.role === "notebook" && role.key.startsWith("databricks:")) state.databricks.notebooks.push(role.key.slice(11));
    if (role?.role === "dbxSql") state.databricks.sqlFiles.push(role.key.slice(11));
    if (role?.role === "poolScript") {
      if (state.poolScripts.length < SQLPOOL_LIMITS.scripts) {
        const path = `${FACTORY_FOLDER}/${file.relative}`;
        state.poolScripts.push({ name: role.name, path, flavor: flavorHint(await readText(file.uri)) });
      }
      continue;
    }
    if (role?.role !== "pipeline") continue;
    if (!PIPELINE_NAME.test(role.name)) {
      state.warnings.push(`${file.relative}: pipeline names use letters, digits, spaces, _ and - (at most 140)`);
      continue;
    }
    const text = await readText(file.uri);
    state.pipelines.push(designView(role.flavor, role.name, `${FACTORY_FOLDER}/${file.relative}`, text));
  }
  state.pipelines.sort((a, b) =>
    FACTORY_FLAVORS.indexOf(a.flavor) - FACTORY_FLAVORS.indexOf(b.flavor) || a.name.localeCompare(b.name));
  return state;
}

/**
 * The files a pipeline of `flavor` can reference: its product's pipelines and datasets, every
 * stored procedure and every notebook. Oversized or invalid files are skipped with a warning.
 */
export async function collectFactoryFiles(flavor: FactoryFlavor): Promise<{ files: FactoryFilesPayload; warnings: string[] }> {
  const files: FactoryFilesPayload = { pipelines: {}, datasets: {}, procedures: {}, notebooks: {} };
  const warnings: string[] = [];
  const root = factoryRoot();
  if (!root || !(await exists(root))) return { files, warnings };
  for (const file of await listFiles(root, warnings)) {
    const role = classifyFactoryPath(file.relative);
    if (!role || role.role === "poolScript" || role.role.startsWith("dbx")) continue;
    const text = await readText(file.uri);
    const tooLong = text.length > FACTORY_LIMITS.textChars;
    if (role.role === "pipeline" || role.role === "dataset") {
      if (role.flavor !== flavor) continue;
      const parsed = parseJsonDocument(text);
      const bucket = role.role === "pipeline" ? files.pipelines : files.datasets;
      const limit = role.role === "pipeline" ? FACTORY_LIMITS.pipelines : FACTORY_LIMITS.datasets;
      if (parsed.error || !parsed.value || typeof parsed.value !== "object") {
        warnings.push(`${file.relative} skipped: ${parsed.error ?? "not a JSON object"}`);
      } else if (Object.keys(bucket).length < limit) {
        bucket[role.name] = parsed.value;
      }
    } else if (tooLong) {
      warnings.push(`${file.relative} skipped: longer than ${FACTORY_LIMITS.textChars} characters`);
    } else if (role.role === "procedure" && Object.keys(files.procedures).length < FACTORY_LIMITS.procedures) {
      files.procedures[role.name] = text;
    } else if (role.role === "notebook" && Object.keys(files.notebooks).length < FACTORY_LIMITS.notebooks) {
      files.notebooks[role.key] = text;
    }
  }
  return { files, warnings };
}

export function pipelineUri(flavor: FactoryFlavor, name: string): vscode.Uri | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  return root ? vscode.Uri.joinPath(root, ...pipelineRelativePath(flavor, name).split("/")) : undefined;
}

/** A workspace-relative path the webview asked to open, accepted only inside the factory folder. */
export function factoryFileUri(relative: string): vscode.Uri | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  const parts = relative.replaceAll("\\", "/").split("/").filter(Boolean);
  if (!root || parts[0] !== FACTORY_FOLDER || parts.some(part => part === "." || part === ".." || part.includes(":"))) {
    return undefined;
  }
  return vscode.Uri.joinPath(root, ...parts);
}

/** Lab files a Databricks job run needs: notebooks, SQL files, compute and Unity Catalog settings. */
export interface DatabricksFilesPayload {
  notebooks: Record<string, string>;
  sql: Record<string, string>;
  compute?: unknown;
  unity_catalog?: unknown;
  grants?: string;
}

export async function collectDatabricksFiles(): Promise<{ files: DatabricksFilesPayload; jobs: Record<string, unknown>; warnings: string[] }> {
  const files: DatabricksFilesPayload = { notebooks: {}, sql: {} };
  const jobs: Record<string, unknown> = {};
  const warnings: string[] = [];
  const root = factoryRoot();
  if (!root || !(await exists(root))) return { files, jobs, warnings };
  for (const file of await listFiles(root, warnings)) {
    if (!file.relative.startsWith("databricks/")) continue;
    const role = classifyFactoryPath(file.relative);
    if (!role) continue;
    const text = await readText(file.uri);
    if (text.length > DATABRICKS_LIMITS.textChars) {
      warnings.push(`${file.relative} skipped: longer than ${DATABRICKS_LIMITS.textChars} characters`);
      continue;
    }
    const json = (): unknown => {
      const parsed = parseJsonDocument(text);
      if (parsed.error) warnings.push(`${file.relative} skipped: ${parsed.error}`);
      return parsed.error ? undefined : parsed.value;
    };
    if (role.role === "notebook" && Object.keys(files.notebooks).length < DATABRICKS_LIMITS.notebooks) {
      files.notebooks[role.key] = text;
    } else if (role.role === "dbxSql" && Object.keys(files.sql).length < DATABRICKS_LIMITS.sqlFiles) {
      files.sql[role.key] = text;
    } else if (role.role === "dbxJob" && JOB_NAME.test(role.name)) {
      const value = json();
      if (value !== undefined) jobs[role.name] = value;
    } else if (role.role === "dbxCompute") {
      files.compute = json();
    } else if (role.role === "dbxUnity") {
      files.unity_catalog = json();
    } else if (role.role === "dbxGrants") {
      files.grants = text;
    }
  }
  return { files, jobs, warnings };
}

export function databricksJobPath(name: string): string {
  return `${FACTORY_FOLDER}/databricks/jobs/${name}.json`;
}

/** A SQL pool script's text (an open editor wins over the file on disk), or an error to show. */
export async function readPoolScript(relative: string): Promise<{ text?: string; error?: string }> {
  const uri = factoryFileUri(relative);
  const role = classifyFactoryPath(relative.replaceAll("\\", "/").split("/").slice(1).join("/"));
  if (!uri || role?.role !== "poolScript") return { error: `${relative} is not a script of ${FACTORY_FOLDER}/sql/pool/` };
  if (!(await exists(uri))) return { error: `SQL pool script not found: ${relative}` };
  const text = await readText(uri);
  if (text.length > SQLPOOL_LIMITS.scriptChars) {
    return { error: `${relative} is longer than ${SQLPOOL_LIMITS.scriptChars} characters` };
  }
  return { text };
}

export async function copyFactorySamples(extensionUri: vscode.Uri): Promise<vscode.Uri | undefined> {
  const root = factoryRoot();
  if (!root) return undefined;
  await copyWithoutOverwrite(vscode.Uri.joinPath(extensionUri, "samples", "factory-lab"), root);
  return root;
}

async function copyWithoutOverwrite(source: vscode.Uri, target: vscode.Uri): Promise<void> {
  await vscode.workspace.fs.createDirectory(target);
  for (const [name, type] of await vscode.workspace.fs.readDirectory(source)) {
    const from = vscode.Uri.joinPath(source, name);
    const to = vscode.Uri.joinPath(target, name);
    if ((type & vscode.FileType.Directory) !== 0) {
      await copyWithoutOverwrite(from, to);
    } else if ((type & vscode.FileType.File) !== 0 && !(await exists(to))) {
      await vscode.workspace.fs.writeFile(to, await vscode.workspace.fs.readFile(from));
    }
  }
}

async function listFiles(root: vscode.Uri, warnings: string[]): Promise<FactoryFile[]> {
  const found: FactoryFile[] = [];
  const walk = async (folder: vscode.Uri, prefix: string, depth: number): Promise<void> => {
    if (depth > MAX_DEPTH) return;
    const entries = await vscode.workspace.fs.readDirectory(folder);
    entries.sort(([a], [b]) => a.localeCompare(b));
    for (const [name, type] of entries) {
      if (found.length >= MAX_FILES) {
        if (!warnings.some(w => w.startsWith("More than"))) warnings.push(`More than ${MAX_FILES} files under ${FACTORY_FOLDER}/: the rest is ignored`);
        return;
      }
      const relative = prefix ? `${prefix}/${name}` : name;
      if ((type & vscode.FileType.Directory) !== 0) {
        await walk(vscode.Uri.joinPath(folder, name), relative, depth + 1);
      } else if ((type & vscode.FileType.File) !== 0) {
        found.push({ relative, uri: vscode.Uri.joinPath(folder, name) });
      }
    }
  };
  await walk(root, "", 0);
  return found;
}

/** Open (possibly unsaved) editors win over the file on disk, like the other labs. */
async function readText(uri: vscode.Uri): Promise<string> {
  const open = vscode.workspace.textDocuments.find(document => document.uri.toString() === uri.toString());
  if (open) return open.getText();
  return new TextDecoder().decode(await vscode.workspace.fs.readFile(uri));
}

async function exists(uri: vscode.Uri): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

