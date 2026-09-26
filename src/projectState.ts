import * as vscode from "vscode";
import { exists } from "./workspaceFiles";
import { MODULES } from "./modules";
import {
  PROGRESS_PATH,
  isProjectFilePath,
  normalizeProject,
  parseProgress,
  projectView,
  serializeProgress,
  type ProgressDocument,
  type ProjectContent,
  type ProjectsViewState
} from "./platform/projects";

const MODULE_IDS = MODULES.map(module => module.id);
const MODULE_LABELS = Object.fromEntries(MODULES.map(module => [module.id, module.label]));

/** Every project shipped in content/projects, in their order. */
export async function loadProjectContents(extensionUri: vscode.Uri): Promise<{ projects: ProjectContent[]; errors: string[] }> {
  const root = vscode.Uri.joinPath(extensionUri, "content", "projects");
  const projects: ProjectContent[] = [];
  const errors: string[] = [];
  let entries: [string, vscode.FileType][] = [];
  try {
    entries = await vscode.workspace.fs.readDirectory(root);
  } catch {
    return { projects, errors };
  }
  for (const [name, type] of entries) {
    if ((type & vscode.FileType.Directory) === 0) continue;
    const uri = vscode.Uri.joinPath(root, name, "project.json");
    if (!(await exists(uri))) continue;
    try {
      const { project, error } = normalizeProject(JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(uri))), MODULE_IDS);
      if (project && project.id === name) projects.push(project);
      else errors.push(`content/projects/${name}/project.json: ${error ?? "its id is not its folder name"}`);
    } catch (error) {
      errors.push(`content/projects/${name}/project.json: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  projects.sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
  return { projects, errors };
}

export function progressUri(): vscode.Uri | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  return root ? vscode.Uri.joinPath(root, ...PROGRESS_PATH.split("/")) : undefined;
}

export async function readProgress(): Promise<{ document: ProgressDocument; error?: string }> {
  const uri = progressUri();
  if (!uri || !(await exists(uri))) return parseProgress(undefined);
  return parseProgress(new TextDecoder().decode(await vscode.workspace.fs.readFile(uri)));
}

export async function writeProgress(document: ProgressDocument): Promise<void> {
  const uri = progressUri();
  if (!uri) throw new Error("Open a workspace folder to keep project progress.");
  await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(uri, ".."));
  await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(serializeProgress(document)));
}

let progressQueue: Promise<unknown> = Promise.resolve();

/**
 * Read-modify-write of .datapass/progress.json, one at a time: Projects and Practice both write it, and a grading
 * can finish while a project verification is saving. A file that does not parse is never overwritten.
 */
export function updateProgress(update: (document: ProgressDocument) => ProgressDocument): Promise<void> {
  const next = progressQueue.then(async () => {
    const progress = await readProgress();
    if (progress.error) throw new Error(progress.error);
    await writeProgress(update(progress.document));
  });
  progressQueue = next.catch(() => undefined);
  return next;
}

export async function loadProjectsState(extensionUri: vscode.Uri): Promise<ProjectsViewState> {
  const { projects, errors } = await loadProjectContents(extensionUri);
  const progress = await readProgress();
  return {
    projects: projects.map(project => projectView(project, progress.document.projects[project.id], MODULE_LABELS)),
    progressPath: PROGRESS_PATH,
    progressError: progress.error,
    loadErrors: errors,
    hasWorkspace: Boolean(vscode.workspace.workspaceFolders?.length)
  };
}

/**
 * Copy a project's starter files (content/projects/<id>/files mirrors workspace paths) into the workspace,
 * never overwriting a file the learner already has. Returns the workspace paths written.
 */
export async function copyProjectFiles(extensionUri: vscode.Uri, projectId: string): Promise<string[]> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) return [];
  const source = vscode.Uri.joinPath(extensionUri, "content", "projects", projectId, "files");
  if (!(await exists(source))) return [];
  const written: string[] = [];
  const walk = async (folder: vscode.Uri, prefix: string, depth: number): Promise<void> => {
    if (depth > 8) return;
    for (const [name, type] of await vscode.workspace.fs.readDirectory(folder)) {
      const relative = prefix ? `${prefix}/${name}` : name;
      if ((type & vscode.FileType.Directory) !== 0) {
        await walk(vscode.Uri.joinPath(folder, name), relative, depth + 1);
        continue;
      }
      if ((type & vscode.FileType.File) === 0 || !isProjectFilePath(relative)) continue;
      if (relative.startsWith("projects/") && !relative.startsWith(`projects/${projectId}/`)) continue;
      const target = vscode.Uri.joinPath(root, ...relative.split("/"));
      if (await exists(target)) continue;
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(target, ".."));
      await vscode.workspace.fs.writeFile(target, await vscode.workspace.fs.readFile(vscode.Uri.joinPath(folder, name)));
      written.push(relative);
    }
  };
  await walk(source, "", 0);
  return written;
}
