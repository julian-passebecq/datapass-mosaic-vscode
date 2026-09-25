import * as vscode from "vscode";
import { toDbtCoreRunView } from "./platform/dbtArtifacts";
import { readProfileName, readProjectName, renderPath, toDctRender, type DctValidationView } from "./platform/dbtTools";
import type { DbtBoardView, DbtChartsView, DbtProjectRef, DbtToolsView, DbtViewState } from "./webview/contracts";

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
  validations?: ReadonlyMap<string, DctValidationView>;
  serveUrl?: string;
  missions?: DbtViewState["missions"];
}): Promise<DbtViewState> {
  const projects = (await findDbtProjects()).map(({ path, name, profile }) => ({ path, name, profile }));
  const selected = projects.find(project => project.path === options.selected)?.path ?? projects[0]?.path;
  const state: DbtViewState = {
    projects,
    selected,
    tools: options.tools,
    profilesPath: ".datapass/dbt/profiles.yml",
    shellIntegration: options.shellIntegration,
    missions: options.missions
  };
  const folder = selected !== undefined ? projectFolder(selected) : undefined;
  if (!folder) return state;
  state.charts = await loadCharts(folder, selected!, options.validations, options.serveUrl);
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

const MAX_BOARDS = 40;
const MAX_PNG_BYTES = 4_000_000;

/** Boards under charts/ (as dct finds them) and their latest renders in renders/. */
async function loadCharts(
  folder: vscode.Uri,
  project: string,
  validations: ReadonlyMap<string, DctValidationView> | undefined,
  serveUrl: string | undefined
): Promise<DbtChartsView> {
  const configured = await exists(vscode.Uri.joinPath(folder, "dbt_charts.yml"));
  const paths: string[] = [];
  const walk = async (relative: string, depth: number): Promise<void> => {
    let entries: [string, vscode.FileType][];
    try {
      entries = await vscode.workspace.fs.readDirectory(vscode.Uri.joinPath(folder, ...relative.split("/")));
    } catch {
      return;
    }
    for (const [name, type] of entries.sort(([a], [b]) => a.localeCompare(b))) {
      const child = `${relative}/${name}`;
      if (type & vscode.FileType.Directory) {
        if (depth < 3) await walk(child, depth + 1);
      } else if (/\.ya?ml$/i.test(name) && paths.length < MAX_BOARDS) {
        paths.push(child);
      }
    }
  };
  await walk("charts", 0);
  const boards: DbtBoardView[] = [];
  for (const path of paths) {
    const board: DbtBoardView = { path, validation: validations?.get(`${project}::${path}`) };
    const png = vscode.Uri.joinPath(folder, ...renderPath(path, "png").split("/"));
    try {
      const stat = await vscode.workspace.fs.stat(png);
      if (stat.size <= MAX_PNG_BYTES) {
        board.png = `data:image/png;base64,${Buffer.from(await vscode.workspace.fs.readFile(png)).toString("base64")}`;
        board.pngAt = new Date(stat.mtime).toISOString();
      }
    } catch {
      // Not rendered yet.
    }
    if (await exists(vscode.Uri.joinPath(folder, ...renderPath(path, "html").split("/")))) board.html = renderPath(path, "html");
    const json = await readJson(vscode.Uri.joinPath(folder, ...renderPath(path, "json").split("/")));
    if (json.value !== undefined) {
      try {
        board.render = toDctRender(json.value);
      } catch (error) {
        board.renderError = error instanceof Error ? error.message : String(error);
      }
    } else if (json.error) {
      board.renderError = json.error;
    }
    boards.push(board);
  }
  return { configured, boards, serveUrl };
}

async function exists(uri: vscode.Uri): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
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
