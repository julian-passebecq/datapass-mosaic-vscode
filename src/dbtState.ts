import * as vscode from "vscode";
import { toDbtCoreRunView } from "./platform/dbtArtifacts";
import { readProfileName, readProjectName } from "./platform/dbtTools";
import type { DbtProjectRef, DbtToolsView, DbtViewState } from "./webview/contracts";

const PROJECT_GLOB = "**/dbt_project.yml";
const PROJECT_EXCLUDE = "{**/node_modules/**,**/target/**,**/dbt_packages/**,**/dbt_internal_packages/**,**/.datapass/**,**/.git/**}";
const MAX_MANIFEST_BYTES = 40_000_000;

/** Every dbt project in the workspace (a folder with dbt_project.yml), sorted by path. */
export async function findDbtProjects(): Promise<Array<DbtProjectRef & { file: vscode.Uri; folder: vscode.Uri }>> {
  const files = await vscode.workspace.findFiles(PROJECT_GLOB, PROJECT_EXCLUDE, 60);
  const projects = [];
  for (const file of files) {
    const folder = vscode.Uri.joinPath(file, "..");
    let text = "";
    try {
      text = new TextDecoder().decode(await vscode.workspace.fs.readFile(file));
    } catch {
      // Listed without a name; dbt itself will say what is wrong with it.
    }
    projects.push({
      path: vscode.workspace.asRelativePath(folder, false).replaceAll("\\", "/"),
      name: readProjectName(text),
      profile: readProfileName(text),
      file,
      folder
    });
  }
  return projects.sort((a, b) => a.path.localeCompare(b.path));
}

export function projectFolder(relative: string): vscode.Uri | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  const parts = relative.split("/").filter(Boolean);
  if (!root || parts.some(part => part === ".." || part === "." || part.includes(":"))) return undefined;
  return parts.length ? vscode.Uri.joinPath(root, ...parts) : root;
}

/**
 * The dbt Lab view: the workspace's dbt projects, the managed tools, and what the last real dbt Core command left in
 * the selected project's target/ folder. Nothing here runs dbt: the learner does, in the terminal.
 */
export async function loadDbtState(options: {
  tools: DbtToolsView;
  selected?: string;
  shellIntegration?: boolean;
}): Promise<DbtViewState> {
  const projects = (await findDbtProjects()).map(({ path, name, profile }) => ({ path, name, profile }));
  const selected = projects.find(project => project.path === options.selected)?.path ?? projects[0]?.path;
  const state: DbtViewState = {
    projects,
    selected,
    tools: options.tools,
    profilesPath: ".datapass/dbt/profiles.yml",
    shellIntegration: options.shellIntegration
  };
  const folder = selected !== undefined ? projectFolder(selected) : undefined;
  if (!folder) return state;
  const target = vscode.Uri.joinPath(folder, "target");
  const manifest = await readJson(vscode.Uri.joinPath(target, "manifest.json"));
  if (manifest.missing) return state;
  if (manifest.error) return { ...state, artifactError: `target/manifest.json: ${manifest.error}` };
  const results = await readJson(vscode.Uri.joinPath(target, "run_results.json"));
  try {
    return { ...state, run: toDbtCoreRunView(manifest.value, results.value), artifactError: results.error && `target/run_results.json: ${results.error}` };
  } catch (error) {
    return { ...state, artifactError: error instanceof Error ? error.message : String(error) };
  }
}

async function readJson(uri: vscode.Uri): Promise<{ value?: unknown; missing?: boolean; error?: string }> {
  try {
    const stat = await vscode.workspace.fs.stat(uri);
    if (stat.size > MAX_MANIFEST_BYTES) return { error: `larger than ${MAX_MANIFEST_BYTES / 1_000_000} MB; not read.` };
  } catch {
    return { missing: true };
  }
  try {
    return { value: JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(uri))) };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}
