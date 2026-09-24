import * as vscode from "vscode";
import { loadExerciseCatalog } from "./exerciseCatalog";
import { probeDbtCli } from "./dbtState";
import { MODULES, type ModuleId } from "./modules";
import { createDefaultProjectManifest, readProjectManifest, writeProjectManifest } from "./project/projectManifest";
import type { RuntimeManager } from "./runtimeManager";
import { retailDemoReadme, retailOrdersCsv, retailPythonStarter, retailSqlStarter } from "./scaffold/retailDemo";
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
    const dbtArtifactWatcher = vscode.workspace.createFileSystemWatcher("**/target/manifest.json");

    this.disposables.push(
      dbtArtifactWatcher,
      dbtArtifactWatcher.onDidCreate(() => {
        if (this.selectedModule === "dbt") void this.refresh();
      }),
      dbtArtifactWatcher.onDidChange(() => {
        if (this.selectedModule === "dbt") void this.refresh();
      }),
      this.panel.onDidDispose(() => this.dispose()),
      this.panel.webview.onDidReceiveMessage(message => {
        void this.handleMessage(message as WebviewToHostMessage);
      }),
      this.runtimeManager.onDidChange(() => {
        void this.refresh();
      }),
      vscode.workspace.onDidSaveTextDocument(() => {
        if (
          this.selectedModule === "pipeline" ||
          this.selectedModule === "airflow" ||
          this.selectedModule === "dbt"
        ) {
          void this.refresh();
        }
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
      case "createRetailDemo":
        await this.createRetailDemo();
        return;
      case "runRetailDemo":
        await this.runRetailDemo();
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
      case "openPipelineSource":
        await this.openPipelineSource();
        return;
      case "refreshPipeline":
        await this.refresh();
        return;
      case "openAirflowSource":
        await this.openAirflowSource();
        return;
      case "refreshAirflow":
        await this.refresh();
        return;
      case "openDbtProject":
        await this.openDbtProject();
        return;
      case "refreshDbt":
        await this.refresh();
        return;
      case "runDbtBuild":
        await this.runDbtBuild();
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

  private async createRetailDemo(): Promise<void> {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating the retail demo.");
      return;
    }

    const root = folder.uri;
    const current = await readProjectManifest();
    if (!current.exists) {
      await writeProjectManifest(createDefaultProjectManifest(folder.name));
    }

    const manifest = await readProjectManifest();
    const datasetRoot = safeRelativeParts(manifest.manifest?.assets?.datasets, "datasets");
    const notebookRoot = safeRelativeParts(manifest.manifest?.assets?.notebooks, "notebooks");
    const pipelineRoot = safeRelativeParts(manifest.manifest?.assets?.pipelines, "pipelines");
    const airflowRoot = safeRelativeParts(manifest.manifest?.assets?.airflow, "airflow");
    const dbtRoot = safeRelativeParts(manifest.manifest?.assets?.dbt, "dbt");

    const datasetDir = vscode.Uri.joinPath(root, ...datasetRoot);
    const notebookDir = vscode.Uri.joinPath(root, ...notebookRoot);
    const datasetPath = [...datasetRoot, "retail_orders.csv"].join("/");
    const sqlNotebookPath = [...notebookRoot, "retail_medallion.sql"].join("/");
    const pythonNotebookPath = [...notebookRoot, "retail_quality.py"].join("/");
    await vscode.workspace.fs.createDirectory(datasetDir);
    await vscode.workspace.fs.createDirectory(notebookDir);

    await writeIfMissing(
      vscode.Uri.joinPath(datasetDir, "retail_orders.csv"),
      retailOrdersCsv()
    );
    await writeIfMissing(
      vscode.Uri.joinPath(notebookDir, "retail_medallion.sql"),
      retailSqlStarter(datasetPath)
    );
    await writeIfMissing(
      vscode.Uri.joinPath(notebookDir, "retail_quality.py"),
      retailPythonStarter(datasetPath)
    );
    await writeIfMissing(
      vscode.Uri.joinPath(root, "README_DATAPASS_RETAIL.md"),
      retailDemoReadme({
        dataset: datasetPath,
        sqlNotebook: sqlNotebookPath,
        pythonNotebook: pythonNotebookPath,
        pipeline: [...pipelineRoot, "main.pipeline.py"].join("/"),
        airflow: [...airflowRoot, "main.dag.json"].join("/"),
        dbtProject: [...dbtRoot, "retail-dbt"].join("/")
      })
    );

    await this.openPipelineSource();
    await this.openAirflowSource();
    await this.openDbtProject();

    const readme = vscode.Uri.joinPath(root, "README_DATAPASS_RETAIL.md");
    await openTextDocument(readme);
    void vscode.window.showInformationMessage(
      "Datapass retail demo created: dataset, notebook starters, pipeline, Airflow DAG and dbt sample."
    );
    await this.refresh();
  }

  private async runRetailDemo(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before running the retail demo.");
      return;
    }

    const manifest = await readProjectManifest();
    const datasetRoot = safeRelativeParts(manifest.manifest?.assets?.datasets, "datasets");
    const datasetPath = [...datasetRoot, "retail_orders.csv"].join("/");
    const datasetUri = vscode.Uri.joinPath(root, ...datasetRoot, "retail_orders.csv");
    if (!(await exists(datasetUri))) {
      void vscode.window.showWarningMessage(
        "Retail demo dataset is missing. Create the retail end-to-end demo first."
      );
      return;
    }

    try {
      await this.runtimeManager.runRetailDemo(datasetPath);
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Retail demo failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
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

  private async openPipelineSource(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating a Datapass pipeline.");
      return;
    }

    const manifest = await readProjectManifest();
    const pipelineRoot = safeRelativeParts(manifest.manifest?.assets?.pipelines, "pipelines");
    const directory = vscode.Uri.joinPath(root, ...pipelineRoot);
    const uri = vscode.Uri.joinPath(directory, "main.pipeline.py");

    await vscode.workspace.fs.createDirectory(directory);
    if (!(await exists(uri))) {
      await vscode.workspace.fs.writeFile(
        uri,
        new TextEncoder().encode(pipelineStarter())
      );
    }

    await openTextDocument(uri);
    await this.refresh();
  }

  private async openAirflowSource(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating an Airflow Lab DAG.");
      return;
    }

    const manifest = await readProjectManifest();
    const airflowRoot = safeRelativeParts(manifest.manifest?.assets?.airflow, "airflow");
    const directory = vscode.Uri.joinPath(root, ...airflowRoot);
    const uri = vscode.Uri.joinPath(directory, "main.dag.json");

    await vscode.workspace.fs.createDirectory(directory);
    if (!(await exists(uri))) {
      await vscode.workspace.fs.writeFile(
        uri,
        new TextEncoder().encode(airflowStarter())
      );
    }

    await openTextDocument(uri);
    await this.refresh();
  }

  private async openDbtProject(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating a dbt Lab project.");
      return;
    }

    const manifest = await readProjectManifest();
    const dbtRoot = safeRelativeParts(manifest.manifest?.assets?.dbt, "dbt");
    const projectRoot = vscode.Uri.joinPath(root, ...dbtRoot, "retail-dbt");
    const projectFile = vscode.Uri.joinPath(projectRoot, "dbt_project.yml");

    const donor = vscode.Uri.joinPath(
      this.context.extensionUri,
      "workbench-core",
      "examples",
      "analytics-m2",
      "retail-dbt"
    );
    await copyDirectoryWithoutOverwrite(donor, projectRoot);

    if (!(await exists(projectFile))) {
      void vscode.window.showErrorMessage("The bundled dbt retail sample is incomplete: dbt_project.yml was not found.");
      return;
    }

    await ensureDbtProfile(root);
    await openTextDocument(projectFile);
    await this.refresh();
  }

  private async runDbtBuild(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before running dbt.");
      return;
    }

    const probe = await probeDbtCli();
    if (!probe.available || !probe.adapterAvailable) {
      void vscode.window.showWarningMessage(
        probe.available
          ? "dbt Core is installed, but dbt-duckdb was not detected. Install dbt-duckdb before running this project."
          : "dbt CLI was not detected. Install dbt-core and dbt-duckdb first."
      );
      return;
    }

    const manifest = await readProjectManifest();
    const dbtRoot = safeRelativeParts(manifest.manifest?.assets?.dbt, "dbt");
    const projectRoot = vscode.Uri.joinPath(root, ...dbtRoot, "retail-dbt");
    const projectFile = vscode.Uri.joinPath(projectRoot, "dbt_project.yml");
    if (!(await exists(projectFile))) {
      await this.openDbtProject();
      return;
    }

    const profilesDir = await ensureDbtProfile(root);
    const terminal = vscode.window.createTerminal({
      name: "Datapass dbt",
      cwd: projectRoot
    });
    terminal.show();
    terminal.sendText(`dbt build --profiles-dir ${quoteShellArg(profilesDir.fsPath)}`, true);
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

function pipelineStarter(): string {
  return [
    'pipeline("retail_quality", schedule="@daily")',
    'extract = sql("extract", "CREATE OR REPLACE TABLE bronze_sample AS SELECT 1 AS id")',
    'check = quality("check", "SELECT * FROM bronze_sample WHERE id IS NULL", retries=1, retry_delay=1)',
    'publish = sql("publish", "SELECT COUNT(*) AS rows FROM bronze_sample")',
    "extract >> check >> publish",
    ""
  ].join("\n");
}

function airflowStarter(): string {
  return JSON.stringify({
    schemaVersion: 1,
    dagId: "retail_daily",
    schedule: "@daily",
    tasks: [
      {
        id: "wait_for_orders",
        label: "Wait for orders",
        type: "sensor",
        dependsOn: [],
        retries: 0,
        retryDelaySeconds: 0,
        durationSeconds: 2,
        triggerRule: "all_success",
        failureMode: "none"
      },
      {
        id: "extract",
        label: "Extract orders",
        type: "task",
        dependsOn: ["wait_for_orders"],
        retries: 1,
        retryDelaySeconds: 5,
        durationSeconds: 4,
        triggerRule: "all_success",
        failureMode: "none"
      },
      {
        id: "check_quality",
        label: "Check data quality",
        type: "quality",
        dependsOn: ["extract"],
        retries: 1,
        retryDelaySeconds: 3,
        durationSeconds: 2,
        triggerRule: "all_success",
        failureMode: "transient"
      },
      {
        id: "publish",
        label: "Publish gold",
        type: "task",
        dependsOn: ["check_quality"],
        retries: 0,
        retryDelaySeconds: 0,
        durationSeconds: 3,
        triggerRule: "all_success",
        failureMode: "none"
      }
    ]
  }, null, 2) + "\n";
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

async function ensureDbtProfile(root: vscode.Uri): Promise<vscode.Uri> {
  const profilesDir = vscode.Uri.joinPath(root, ".datapass", "dbt");
  const dataDir = vscode.Uri.joinPath(root, ".datapass", "data");
  const profile = vscode.Uri.joinPath(profilesDir, "profiles.yml");
  const database = vscode.Uri.joinPath(dataDir, "workspace.duckdb");

  await vscode.workspace.fs.createDirectory(profilesDir);
  await vscode.workspace.fs.createDirectory(dataDir);

  if (!(await exists(profile))) {
    const databasePath = database.fsPath.replaceAll("\\", "/").replaceAll("'", "''");
    const content = [
      "datapass_retail:",
      "  target: dev",
      "  outputs:",
      "    dev:",
      "      type: duckdb",
      `      path: '${databasePath}'`,
      "      threads: 4",
      ""
    ].join("\n");
    await vscode.workspace.fs.writeFile(profile, new TextEncoder().encode(content));
  }

  return profilesDir;
}

async function writeIfMissing(uri: vscode.Uri, content: string): Promise<void> {
  if (!(await exists(uri))) {
    await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(content));
  }
}

async function copyDirectoryWithoutOverwrite(source: vscode.Uri, target: vscode.Uri): Promise<void> {
  await vscode.workspace.fs.createDirectory(target);
  const entries = await vscode.workspace.fs.readDirectory(source);
  for (const [name, type] of entries) {
    const from = vscode.Uri.joinPath(source, name);
    const to = vscode.Uri.joinPath(target, name);
    if ((type & vscode.FileType.Directory) !== 0) {
      await copyDirectoryWithoutOverwrite(from, to);
    } else if ((type & vscode.FileType.File) !== 0 && !(await exists(to))) {
      const bytes = await vscode.workspace.fs.readFile(from);
      await vscode.workspace.fs.writeFile(to, bytes);
    }
  }
}

function quoteShellArg(value: string): string {
  return `"${value.replaceAll('"', '\\"')}"`;
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
