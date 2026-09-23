import * as vscode from "vscode";
import { loadExerciseCatalog } from "./exerciseCatalog";
import { MODULES, type ModuleId } from "./modules";
import { createDefaultProjectManifest, readProjectManifest, writeProjectManifest } from "./project/projectManifest";
import type { RuntimeManager } from "./runtimeManager";
import { collectWorkbenchState } from "./workbenchState";
import { contentSecurityPolicy, makeNonce } from "./webview/security";
import type { ExerciseSummary, ScratchKind, WebviewToHostMessage } from "./webview/contracts";

export class WorkbenchPanel {
  private static current?: WorkbenchPanel;

  static async show(
    context: vscode.ExtensionContext,
    runtimeManager: RuntimeManager,
    initialModule: ModuleId
  ): Promise<void> {
    if (WorkbenchPanel.current) {
      WorkbenchPanel.current.selectedModule = initialModule;
      WorkbenchPanel.current.panel.reveal(vscode.ViewColumn.One, true);
      await WorkbenchPanel.current.refresh();
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      "datapass.workbench",
      "Datapass Workbench",
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "dist")]
      }
    );

    WorkbenchPanel.current = new WorkbenchPanel(
      panel,
      context,
      runtimeManager,
      initialModule
    );
  }

  private selectedModule: ModuleId;
  private readonly disposables: vscode.Disposable[] = [];

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private readonly context: vscode.ExtensionContext,
    private readonly runtimeManager: RuntimeManager,
    initialModule: ModuleId
  ) {
    this.selectedModule = initialModule;
    this.panel.webview.html = this.html(this.panel.webview);

    this.disposables.push(
      this.panel.onDidDispose(() => this.dispose()),
      this.panel.webview.onDidReceiveMessage(message => {
        void this.handleMessage(message as WebviewToHostMessage);
      }),
      this.runtimeManager.onDidChange(() => {
        void this.refresh();
      })
    );
  }

  private async handleMessage(message: WebviewToHostMessage): Promise<void> {
    switch (message.type) {
      case "ready":
        await this.refresh();
        return;
      case "selectModule":
        if (MODULES.some(module => module.id === message.moduleId)) {
          this.selectedModule = message.moduleId;
          await this.refresh();
        }
        return;
      case "createManifest":
        await this.createManifest();
        return;
      case "openManifest":
        await this.openManifest();
        return;
      case "startRuntime": {
        const manifest = await readProjectManifest();
        const pythonCommand = manifest.manifest?.runtime?.pythonCommand ?? "python";
        await this.runtimeManager.start(pythonCommand);
        return;
      }
      case "stopRuntime":
        this.runtimeManager.stop();
        return;
      case "openTerminal":
        await vscode.commands.executeCommand("workbench.action.terminal.new");
        return;
      case "openScratch":
        await this.openScratch(message.kind);
        return;
      case "openExercise":
        await this.openExercise(message.exerciseKey);
        return;
    }
  }

  private async createManifest(): Promise<void> {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating a Datapass project.");
      return;
    }

    const current = await readProjectManifest();
    if (current.exists) {
      await this.openManifest();
      return;
    }

    const uri = await writeProjectManifest(createDefaultProjectManifest(folder.name));
    await openTextDocument(uri);
    await this.refresh();
  }

  private async openManifest(): Promise<void> {
    const manifest = await readProjectManifest();
    if (!manifest.uri || !manifest.exists) {
      void vscode.window.showInformationMessage("No .datapass/project.json exists yet.");
      return;
    }
    await openTextDocument(manifest.uri);
  }

  private async openScratch(kind: ScratchKind): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating Mosaic scratch files.");
      return;
    }

    const manifest = await readProjectManifest();
    const notebooks = safeRelativeParts(manifest.manifest?.assets?.notebooks, "notebooks");
    const spec = scratchSpec(kind);
    const directoryParts = kind === "notes" ? ["notes"] : notebooks;
    const directory = vscode.Uri.joinPath(root, ...directoryParts);
    const uri = vscode.Uri.joinPath(directory, spec.fileName);

    await vscode.workspace.fs.createDirectory(directory);
    if (!(await exists(uri))) {
      await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(spec.content));
    }
    await openTextDocument(uri);
  }

  private async openExercise(exerciseKey: string): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before opening a Datapass exercise.");
      return;
    }

    const catalog = await loadExerciseCatalog(this.context.extensionUri);
    const exercise = catalog.find(item => item.key === exerciseKey);
    if (!exercise) {
      void vscode.window.showErrorMessage(`Exercise not found: ${exerciseKey}`);
      return;
    }

    const manifest = await readProjectManifest();
    const exerciseRoot = safeRelativeParts(manifest.manifest?.assets?.exercises, "exercises");
    const directory = vscode.Uri.joinPath(
      root,
      ...exerciseRoot,
      slug(exercise.id),
      slug(exercise.language)
    );
    const starterUri = vscode.Uri.joinPath(directory, `solution.${extensionFor(exercise.language)}`);
    const readmeUri = vscode.Uri.joinPath(directory, "README.md");

    await vscode.workspace.fs.createDirectory(directory);
    if (!(await exists(starterUri))) {
      await vscode.workspace.fs.writeFile(
        starterUri,
        new TextEncoder().encode(ensureTrailingNewline(exercise.starterSource))
      );
    }
    if (!(await exists(readmeUri))) {
      await vscode.workspace.fs.writeFile(
        readmeUri,
        new TextEncoder().encode(exerciseReadme(exercise))
      );
    }

    await openTextDocument(starterUri);
  }

  private async refresh(): Promise<void> {
    const state = await collectWorkbenchState(
      this.selectedModule,
      this.runtimeManager,
      this.context.extensionUri
    );
    await this.panel.webview.postMessage({ type: "state", state });
  }

  private html(webview: vscode.Webview): string {
    const nonce = makeNonce();
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, "dist", "webview.js")
    );
    const styleUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, "dist", "webview.css")
    );

    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="${contentSecurityPolicy(webview, nonce)}">
  <link rel="stylesheet" href="${styleUri}">
  <title>Datapass Workbench</title>
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }

  private dispose(): void {
    if (WorkbenchPanel.current === this) {
      WorkbenchPanel.current = undefined;
    }
    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
  }
}

function scratchSpec(kind: ScratchKind): { fileName: string; content: string } {
  switch (kind) {
    case "sql":
      return {
        fileName: "mosaic.sql",
        content: "-- Datapass Mosaic SQL scratch\n-- Run locally with DuckDB / DuckLake.\n\nselect 1 as datapass_ready;\n"
      };
    case "python":
      return {
        fileName: "mosaic.py",
        content: "import polars as pl\n\ndf = pl.DataFrame({\"value\": [1, 2, 3]})\nprint(df)\n"
      };
    case "notes":
      return {
        fileName: "mosaic.md",
        content: "# Mosaic notes\n\nUse this file for dataset grain, assumptions, checks and observations.\n"
      };
  }
}

function exerciseReadme(exercise: ExerciseSummary): string {
  const topics = exercise.topics.length ? exercise.topics.join(", ") : "—";
  return [
    `# ${exercise.title}`,
    "",
    `- Pack: ${exercise.packTitle}`,
    `- Language: ${exercise.language}`,
    `- Difficulty: ${exercise.difficulty}`,
    `- Truth: ${exercise.truth ?? "not specified"}`,
    `- Topics: ${topics}`,
    "",
    "## Task",
    "",
    exercise.prompt,
    "",
    "## Workspace rule",
    "",
    "Edit the solution file next to this brief. Datapass will not overwrite an existing learner solution.",
    ""
  ].join("\n");
}

function extensionFor(language: string): string {
  switch (language.toLowerCase()) {
    case "sql":
    case "dbt":
      return "sql";
    case "python":
    case "pandas":
    case "polars":
    case "sparklab":
    case "pyspark":
      return "py";
    case "powershell":
      return "ps1";
    case "yaml":
    case "yml":
      return "yml";
    default:
      return "txt";
  }
}

function slug(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "exercise";
}

function ensureTrailingNewline(value: string): string {
  return value.endsWith("\n") ? value : value + "\n";
}

function safeRelativeParts(value: string | undefined, fallback: string): string[] {
  const normalized = (value ?? fallback).replaceAll("\\", "/");
  const parts = normalized.split("/").filter(Boolean);
  if (
    parts.length === 0 ||
    parts.some(part => part === "." || part === ".." || part.includes(":"))
  ) {
    return [fallback];
  }
  return parts;
}

async function exists(uri: vscode.Uri): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

async function openTextDocument(uri: vscode.Uri): Promise<void> {
  const document = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(document, { preview: false });
}
