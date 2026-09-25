import * as vscode from "vscode";
import {
  PYLANCE_STUBS_FOLDER,
  exerciseBuiltinsStub,
  exerciseFileExcludes,
  exerciseLabelPatterns,
  isPythonExerciseLanguage,
  mergeExtraPaths,
  mergeMissing
} from "./platform/exerciseWorkspace";
import type { ExerciseSummary } from "./webview/contracts";

/**
 * Called each time an exercise is opened. Writes the workspace settings and helper files that make the
 * exercise read well in VS Code; a failure here never stops the exercise from opening.
 */
export async function prepareExerciseWorkspace(
  extensionUri: vscode.Uri,
  root: vscode.Uri,
  exerciseRoot: string[],
  directory: vscode.Uri,
  exercise: ExerciseSummary,
  log: (message: string) => void
): Promise<void> {
  await attempt(log, "tab labels", () => ensureEntries(root, "workbench.editor", "customLabels.patterns", exerciseLabelPatterns(exerciseRoot)));
  if (!isPythonExerciseLanguage(exercise.language)) return;
  await attempt(log, "files.exclude", () => ensureEntries(root, "files", "exclude", exerciseFileExcludes(exerciseRoot)));

  const builtins = exerciseBuiltinsStub(
    exercise.language,
    exercise.dataContext.map(table => table.name),
    exercise.runtime
  );
  if (builtins) {
    await attempt(log, "__builtins__.pyi", () => writeIfChanged(vscode.Uri.joinPath(directory, "__builtins__.pyi"), builtins));
  }
  await attempt(log, "Pylance stubs", () => syncPylanceStubs(extensionUri, root));
  await attempt(log, "python.analysis.extraPaths", () => ensureExtraPaths(root));
}

/** Adds object-setting entries to the workspace value (VS Code merges it with the user's). */
async function ensureEntries<T>(root: vscode.Uri, section: string, key: string, wanted: Record<string, T>): Promise<void> {
  const config = vscode.workspace.getConfiguration(section, root);
  const merged = mergeMissing(config.inspect<Record<string, T>>(key)?.workspaceValue, wanted);
  if (merged) await config.update(key, merged, vscode.ConfigurationTarget.Workspace);
}

async function ensureExtraPaths(root: vscode.Uri): Promise<void> {
  const config = vscode.workspace.getConfiguration("python.analysis", root);
  // Registered by Pylance: without it there is nothing to configure (and no false warnings either).
  if (config.inspect("extraPaths")?.defaultValue === undefined) return;
  // A workspace array replaces the user's: start from the effective value so user paths are kept.
  const merged = mergeExtraPaths(config.get<string[]>("extraPaths"));
  if (merged) await config.update("extraPaths", merged, vscode.ConfigurationTarget.Workspace);
}

/** Mirrors the extension's content/pylance-stubs into the workspace, rewriting only what changed. */
async function syncPylanceStubs(extensionUri: vscode.Uri, root: vscode.Uri): Promise<void> {
  const source = vscode.Uri.joinPath(extensionUri, "content", "pylance-stubs");
  const target = vscode.Uri.joinPath(root, ...PYLANCE_STUBS_FOLDER.split("/"));
  const wanted = await listFiles(source);
  for (const relative of wanted) {
    const bytes = await vscode.workspace.fs.readFile(vscode.Uri.joinPath(source, ...relative.split("/")));
    await writeIfChanged(vscode.Uri.joinPath(target, ...relative.split("/")), new TextDecoder().decode(bytes));
  }
  const keep = new Set(wanted);
  for (const relative of await listFiles(target)) {
    if (!keep.has(relative)) await vscode.workspace.fs.delete(vscode.Uri.joinPath(target, ...relative.split("/")));
  }
}

async function listFiles(folder: vscode.Uri, prefix = ""): Promise<string[]> {
  let entries: [string, vscode.FileType][];
  try {
    entries = await vscode.workspace.fs.readDirectory(folder);
  } catch {
    return [];
  }
  const files: string[] = [];
  for (const [name, type] of entries) {
    const relative = prefix ? `${prefix}/${name}` : name;
    if (type & vscode.FileType.Directory) files.push(...await listFiles(vscode.Uri.joinPath(folder, name), relative));
    else if (type & vscode.FileType.File) files.push(relative);
  }
  return files;
}

async function writeIfChanged(uri: vscode.Uri, text: string): Promise<void> {
  try {
    if (new TextDecoder().decode(await vscode.workspace.fs.readFile(uri)) === text) return;
  } catch {
    // Missing: written below.
  }
  await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(uri, ".."));
  await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(text));
}

async function attempt(log: (message: string) => void, what: string, action: () => Promise<void>): Promise<void> {
  try {
    await action();
  } catch (error) {
    log(`Exercise workspace: could not update ${what}: ${error instanceof Error ? error.message : String(error)}`);
  }
}
