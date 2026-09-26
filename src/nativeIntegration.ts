import * as vscode from "vscode";
import { loadExerciseCatalog } from "./exerciseCatalog";
import { MODULES, type WorkbenchView } from "./modules";
import { toProgressFile } from "./platform/missions";
import { exerciseSlug, missionOf, runtimeStatusView, solutionTarget, type RuntimeAction } from "./platform/native";
import { safeRelativeParts } from "./platform/workspacePaths";
import { readProjectManifest } from "./project/projectManifest";
import type { RuntimeManager } from "./runtimeManager";
import type { MissionsService } from "./missions";
import type { WebviewToHostMessage } from "./webview/contracts";

/** Open the Workbench on a view and, optionally, hand it a webview message as if its surface had sent it. */
export type OpenWorkbench = (view: WorkbenchView, message?: WebviewToHostMessage) => Promise<void>;

const RUNTIME_ACTION = "datapass.runtime.action";

/**
 * What VS Code itself shows for Datapass: the runtime in the status bar, and CodeLens above Practice solution files
 * (Run visible tests, Submit) and the files of a started mission (Check mission; Run ingest.py in the API Lab).
 * Every action goes through the Workbench's own message handlers, so it behaves exactly like its button.
 */
export function registerNativeIntegration(runtime: RuntimeManager, missions: MissionsService, extensionUri: vscode.Uri,
  open: OpenWorkbench): vscode.Disposable[] {
  const status = vscode.window.createStatusBarItem("datapass.runtime", vscode.StatusBarAlignment.Left, 50);
  status.name = "Datapass runtime";
  let action: RuntimeAction = "setup";
  const update = () => {
    const view = runtimeStatusView(runtime.snapshot());
    action = view.action;
    status.text = view.text;
    status.tooltip = view.tooltip;
    status.command = RUNTIME_ACTION;
    status.backgroundColor = view.warning ? new vscode.ThemeColor("statusBarItem.warningBackground") : undefined;
    status.show();
  };
  update();

  const lenses = new DatapassCodeLens(missions);
  return [
    status,
    runtime.onDidChange(update),
    vscode.commands.registerCommand(RUNTIME_ACTION, async () => {
      if (action === "log") runtime.showLog();
      else if (action === "open") await open("home");
      else await open("home", { type: action === "start" ? "startRuntime" : "setupRuntime" });
    }),
    vscode.commands.registerCommand("datapass.runtime.setup", () => open("home", { type: "setupRuntime" })),
    vscode.commands.registerCommand("datapass.runtime.start", () => open("home", { type: "startRuntime" })),
    vscode.commands.registerCommand("datapass.practice.runVisible", (uri?: vscode.Uri) => grade(extensionUri, open, "run", uri)),
    vscode.commands.registerCommand("datapass.practice.submit", (uri?: vscode.Uri) => grade(extensionUri, open, "submit", uri)),
    vscode.commands.registerCommand("datapass.missions.check", async (uri?: vscode.Uri) => {
      const id = missionOf(relativeParts(uri ?? vscode.window.activeTextEditor?.document.uri) ?? []);
      if (!id) {
        void vscode.window.showWarningMessage("Open a file of a mission folder (missions/<id>/) to check that mission.");
        return;
      }
      const lab = (await missions.mission(id).catch(() => undefined))?.lab;
      await open(moduleView(lab), { type: "checkMission", missionId: id });
    }),
    vscode.commands.registerCommand("datapass.apilab.run", async (missionId: string) => {
      await open("apilab", { type: "runApiIngestion", missionId });
    }),
    vscode.languages.registerCodeLensProvider({ scheme: "file" }, lenses),
    missionsProgressWatcher(() => lenses.changed())
  ];
}

class DatapassCodeLens implements vscode.CodeLensProvider {
  private readonly emitter = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this.emitter.event;

  constructor(private readonly missions: MissionsService) {}

  changed(): void {
    this.emitter.fire();
  }

  async provideCodeLenses(document: vscode.TextDocument): Promise<vscode.CodeLens[]> {
    const parts = relativeParts(document.uri);
    if (!parts) return [];
    const top = new vscode.Range(0, 0, 0, 0);
    const missionId = missionOf(parts);
    if (missionId) {
      const progress = toProgressFile(await readJson(workspaceUri(".datapass", "missions", "progress.json")));
      if (!progress.missions[missionId]?.started) return [];
      const lenses = [new vscode.CodeLens(top, { title: "$(checklist) Check mission", command: "datapass.missions.check", arguments: [document.uri] })];
      const lab = (await this.missions.mission(missionId).catch(() => undefined))?.lab;
      if (lab === "apilab" && parts.length === 3 && parts[2] === "ingest.py") {
        lenses.unshift(new vscode.CodeLens(top, { title: "$(play) Run ingest.py", command: "datapass.apilab.run", arguments: [missionId] }));
      }
      return lenses;
    }
    const manifest = await readProjectManifest();
    if (!solutionTarget(parts, safeRelativeParts(manifest.manifest?.assets?.exercises, "exercises"))) return [];
    return [
      new vscode.CodeLens(top, { title: "$(play) Run visible tests", command: "datapass.practice.runVisible", arguments: [document.uri] }),
      new vscode.CodeLens(top, { title: "$(pass) Submit", command: "datapass.practice.submit", arguments: [document.uri] })
    ];
  }
}

async function grade(extensionUri: vscode.Uri, open: OpenWorkbench, mode: "run" | "submit", uri?: vscode.Uri): Promise<void> {
  const target = uri ?? vscode.window.activeTextEditor?.document.uri;
  const parts = relativeParts(target);
  const manifest = await readProjectManifest();
  const solution = parts && solutionTarget(parts, safeRelativeParts(manifest.manifest?.assets?.exercises, "exercises"));
  if (!solution) {
    void vscode.window.showWarningMessage("Open a Practice solution file (exercises/<exercise>/<language>/solution.*) first.");
    return;
  }
  const exercise = (await loadExerciseCatalog(extensionUri))
    .find(item => exerciseSlug(item.id) === solution.exercise && exerciseSlug(item.language) === solution.language);
  if (!exercise) {
    void vscode.window.showWarningMessage(`No installed exercise matches ${parts.join("/")}.`);
    return;
  }
  // Grading reads the file from disk: save the edits first, as Run visible and Submit in Practice expect.
  const document = vscode.workspace.textDocuments.find(item => item.uri.toString() === target?.toString());
  if (document?.isDirty) await document.save();
  await open("practice", { type: "gradeExercise", exerciseKey: exercise.key, mode });
}

function moduleView(lab: string | undefined): WorkbenchView {
  return MODULES.find(module => module.id === lab)?.id ?? "home";
}

function missionsProgressWatcher(changed: () => void): vscode.Disposable {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) return new vscode.Disposable(() => undefined);
  const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(folder, ".datapass/missions/progress.json"));
  watcher.onDidChange(changed);
  watcher.onDidCreate(changed);
  watcher.onDidDelete(changed);
  return watcher;
}

/** The file's path inside the first workspace folder, split on "/", or undefined when it is outside. */
function relativeParts(uri: vscode.Uri | undefined): string[] | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!uri || !root || uri.scheme !== "file") return undefined;
  const base = root.path.endsWith("/") ? root.path : `${root.path}/`;
  const path = uri.path;
  const inside = process.platform === "win32" ? path.toLowerCase().startsWith(base.toLowerCase()) : path.startsWith(base);
  return inside ? path.slice(base.length).split("/").filter(Boolean) : undefined;
}

function workspaceUri(...parts: string[]): vscode.Uri | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  return root ? vscode.Uri.joinPath(root, ...parts) : undefined;
}

async function readJson(uri: vscode.Uri | undefined): Promise<unknown> {
  if (!uri) return undefined;
  try {
    return JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(uri)));
  } catch {
    return undefined;
  }
}
