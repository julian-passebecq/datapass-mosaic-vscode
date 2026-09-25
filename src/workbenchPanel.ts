import * as vscode from "vscode";
import { AIRFLOW_STARTER_FILE, airflowPaths } from "./airflowState";
import { biFileUri, biRoot, collectBiDbtFiles, collectBiScripts, copyBiSamples, readBiModel } from "./biState";
import { BI_LIMITS, BI_MODEL_FILE, DBT_COMMANDS, parseSelect } from "./platform/biRun";
import { loadExerciseCatalog } from "./exerciseCatalog";
import { prepareExerciseWorkspace } from "./exerciseWorkspace";
import { decodeCsvBytes, suggestBronzeAsset, validateBronzeAsset } from "./platform/csvImport";
import {
  collectDatabricksFiles,
  collectFactoryFiles,
  copyFactorySamples,
  databricksJobPath,
  factoryFileUri,
  factoryRoot,
  pipelineUri,
  readPoolScript
} from "./factoryState";
import { JOB_NAME } from "./platform/databricksRun";
import { FACTORY_FLAVORS, PIPELINE_NAME, pipelineRelativePath } from "./platform/factoryRun";
import { SQLPOOL_FLAVORS, SQLPOOL_LIMITS, isValidScale } from "./platform/sqlpoolRun";
import { probeDbtCli } from "./dbtState";
import { MODULES, type ModuleId } from "./modules";
import { writeMosaicLayout } from "./mosaicLayoutStore";
import { createDefaultProjectManifest, readProjectManifest, writeProjectManifest } from "./project/projectManifest";
import type { PythonTrustController } from "./pythonTrustController";
import type { RuntimeManager } from "./runtimeManager";
import { retailDemoReadme, retailOrdersCsv, retailPythonStarter, retailSqlStarter } from "./scaffold/retailDemo";
import { airflowStarter, pipelineStarter, scratchSpec } from "./scaffold/starters";
import { exerciseReadme } from "./scaffold/exerciseReadme";
import { collectWorkbenchState } from "./workbenchState";
import { copyProjectFiles, loadProjectContents, progressUri, readProgress, writeProgress } from "./projectState";
import {
  applyVerification,
  emptyProgress,
  isProjectFilePath,
  serializeProgress,
  setManual,
  type ProjectContent,
  type ProjectScaffold
} from "./platform/projects";
import { contentSecurityPolicy, makeNonce } from "./webview/security";
import type {
  AirflowScenarioInput,
  BiDbtCommand,
  BiRunMode,
  FactoryFlavor,
  FactoryScenarioInput,
  DatabricksScenarioInput,
  ProjectsHostState,
  ScratchKind,
  SqlPoolFlavor,
  WebviewToHostMessage,
  WorkbenchFocus
} from "./webview/contracts";

export class WorkbenchPanel {
  private static current?: WorkbenchPanel;

  static async show(
    context: vscode.ExtensionContext,
    runtimeManager: RuntimeManager,
    pythonTrust: PythonTrustController,
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
      pythonTrust,
      initialModule
    );
  }

  private selectedModule: ModuleId;
  private readonly disposables: vscode.Disposable[] = [];
  /** Last focused file per extension, so "Run active ..." works when the Workbench shares a tab group with it. */
  private readonly lastDocuments = new Map<string, vscode.Uri>();
  /** The DAG file Airflow Lab last simulated, to reveal a parser error line in it. */
  private lastAirflowFile?: vscode.Uri;
  /** The T-SQL script the SQL pool tab last ran, to reveal a statement's line in it. */
  private lastSqlPoolFile?: vscode.Uri;
  /** The active .sql file the BI Lab last ran (not under bi/), to reveal a statement's line in it. */
  private lastBiActiveFile?: vscode.Uri;
  /** The lab tab (or Practice filter) a project step asked to show. */
  private focus?: WorkbenchFocus;
  private focusSeq = 0;
  /** A project verification in flight, or the last one's error. */
  private projectsHost: ProjectsHostState = {};
  /** Only the newest refresh posts its state (see refresh). */
  private refreshSeq = 0;

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private readonly context: vscode.ExtensionContext,
    private readonly runtimeManager: RuntimeManager,
    private readonly pythonTrust: PythonTrustController,
    initialModule: ModuleId
  ) {
    this.selectedModule = initialModule;
    this.rememberEditor(vscode.window.activeTextEditor);
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
      vscode.window.onDidChangeActiveTextEditor(editor => this.rememberEditor(editor)),
      this.panel.webview.onDidReceiveMessage(message => {
        void this.handleMessage(message as WebviewToHostMessage);
      }),
      this.runtimeManager.onDidChange(() => {
        void this.refresh();
      }),
      vscode.workspace.onDidGrantWorkspaceTrust(() => {
        void this.refresh();
      }),
      vscode.workspace.onDidSaveTextDocument(document => {
        if (
          document.uri.path.endsWith("/.datapass/project.json") ||
          this.selectedModule === "pipeline" ||
          this.selectedModule === "airflow" ||
          this.selectedModule === "fabric" ||
          this.selectedModule === "bi" ||
          this.selectedModule === "dbt" ||
          this.selectedModule === "projects"
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
          this.focus = undefined;
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
      case "refreshCatalog":
        await this.runtimeManager.refreshCatalog();
        return;
      case "runActiveSql":
        await this.runActiveSql();
        return;
      case "runActivePython":
        await this.runActivePython();
        return;
      case "runActiveSparkLab":
        await this.runActiveSparkLab(message.profileId, message.aqe);
        return;
      case "setTrustedPython":
        await this.setTrustedPython(message.enabled);
        return;
      case "saveMosaicLayout":
        // Persist only inside a Datapass project; never create .datapass/ just by dragging.
        if ((await readProjectManifest()).exists) await writeMosaicLayout(message.layout);
        return;
      case "setupRuntime":
        await this.setupRuntime();
        return;
      case "importCsv":
        await this.importCsv();
        return;
      case "showRuntimeLog":
        this.runtimeManager.showLog();
        return;
      case "startRuntime":
        await this.startRuntime();
        return;
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
      case "gradeExercise":
        await this.gradeExercise(message.exerciseKey, message.mode);
        return;
      case "openPipelineSource":
        await this.openPipelineSource();
        return;
      case "refreshPipeline":
        await this.refresh();
        return;
      case "runPipeline":
        await this.runPipeline();
        return;
      case "openAirflowSource":
        await this.openAirflowSource();
        return;
      case "refreshAirflow":
        await this.refresh();
        return;
      case "simulateAirflow":
        await this.simulateAirflow(message.scenario);
        return;
      case "revealAirflowLine":
        await this.revealAirflowLine(message.line);
        return;
      case "createFactoryLab":
        await this.createFactoryLab();
        break;
      case "refreshFactory":
        await this.refresh();
        break;
      case "openFactoryFile":
        await this.openFactoryFile(message.path);
        break;
      case "revealFactoryActivity":
        await this.revealFactoryActivity(message.path, message.activity);
        break;
      case "simulateFactory":
        await this.simulateFactory(message.flavor, message.name, message.scenario);
        break;
      case "runSqlPool":
        await this.runSqlPool(message.flavor, message.scale, message.source, message.path);
        break;
      case "revealSqlPoolLine":
        await this.revealSqlPoolLine(message.line);
        break;
      case "simulateDatabricks":
        await this.simulateDatabricks(message.name, message.scenario);
        break;
      case "refreshDatabricksState":
        await this.refreshDatabricksState();
        break;
      case "createBiLab":
        await this.createBiLab();
        break;
      case "refreshBi":
        await this.refresh();
        break;
      case "openBiFile":
        await this.openBiFile(message.path);
        break;
      case "runBiLab":
        await this.runBiLab(message.mode);
        break;
      case "revealBiLine":
        await this.revealBiLine(message.path, message.line);
        break;
      case "runBiDbt":
        await this.runBiDbt(message.command, message.select, message.fullRefresh);
        break;
      case "openDbtProject":
        await this.openDbtProject();
        return;
      case "refreshDbt":
        await this.refresh();
        return;
      case "runDbtBuild":
        await this.runDbtBuild();
        return;
      case "prepareProject":
        await this.prepareProject(message.projectId);
        return;
      case "openProjectStep":
        await this.openProjectStep(message.projectId, message.stepId);
        return;
      case "verifyProjectSteps":
        await this.verifyProjectSteps(message.projectId, message.stepIds);
        return;
      case "setProjectStepManual":
        await this.setProjectStepManual(message.projectId, message.stepId, message.checked);
        return;
      case "openProgressFile":
        await this.openProgressFile();
        return;
    }
  }

  private async startRuntime(): Promise<void> {
    // The runtime's catalog lives in <workspace>/.datapass/data; without a folder every call would fail.
    if (!vscode.workspace.workspaceFolders?.length) {
      void vscode.window.showWarningMessage("Open a folder before starting the Datapass runtime; its local catalog lives in that folder.");
      return;
    }
    const manifest = await readProjectManifest();
    const pythonCommand = manifest.manifest?.runtime?.pythonCommand ?? "python";
    const storage = manifest.manifest?.runtime?.storage ?? "duckdb";
    const trust = await this.pythonTrust.resolve();
    await this.runtimeManager.start(pythonCommand, storage, trust.effective);
  }

  private async setTrustedPython(enabled: boolean): Promise<void> {
    const changed = enabled ? await this.pythonTrust.enable() : await this.pythonTrust.disable();
    const status = this.runtimeManager.snapshot().status;
    if (changed && (status === "running" || status === "starting")) {
      // Trust is fixed per runtime process, so apply it with a clean restart.
      await this.runtimeManager.stopAndWait();
      await this.startRuntime();
    }
    await this.refresh();
  }

  private rememberEditor(editor: vscode.TextEditor | undefined): void {
    if (editor?.document.uri.scheme !== "file") return;
    const match = /\.(sql|py)$/i.exec(editor.document.fileName);
    if (match) this.lastDocuments.set("." + match[1].toLowerCase(), editor.document.uri);
  }

  /** Open a file next to the Workbench so the webview and the file stay visible together. */
  private async openBeside(uri: vscode.Uri): Promise<void> {
    const document = await vscode.workspace.openTextDocument(uri);
    const column = this.panel.viewColumn === vscode.ViewColumn.Two ? vscode.ViewColumn.One : vscode.ViewColumn.Two;
    const editor = await vscode.window.showTextDocument(document, { preview: false, viewColumn: column });
    this.rememberEditor(editor);
  }

  private async setupRuntime(): Promise<void> {
    const manifest = await readProjectManifest();
    const pythonCommand = manifest.manifest?.runtime?.pythonCommand ?? "python";
    try {
      await this.runtimeManager.setup(pythonCommand);
      void vscode.window.showInformationMessage("Datapass managed runtime is ready.");
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Datapass runtime setup failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.refresh();
  }

  /** Mosaic: read a user-picked CSV on the host and send its TEXT to a new bronze table. */
  private async importCsv(): Promise<void> {
    if (this.runtimeManager.snapshot().status !== "running") {
      void vscode.window.showWarningMessage("Start the Datapass runtime before importing a CSV.");
      return;
    }
    const picked = await vscode.window.showOpenDialog({
      canSelectMany: false,
      canSelectFolders: false,
      defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri,
      filters: { "CSV files": ["csv"] },
      openLabel: "Import into catalog",
      title: "Import CSV into the local catalog (new bronze table)"
    });
    const uri = picked?.[0];
    if (!uri) return;

    const fileName = uri.path.split("/").pop() ?? "data.csv";
    let text: string;
    try {
      text = decodeCsvBytes(await vscode.workspace.fs.readFile(uri));
    } catch (error) {
      void vscode.window.showErrorMessage(error instanceof Error ? error.message : String(error));
      return;
    }

    const existing = (this.runtimeManager.snapshot().catalog ?? []).map(asset => asset.name);
    const asset = await vscode.window.showInputBox({
      title: `Import ${fileName}`,
      prompt: "New bronze table name. Imports never overwrite; every column is stored as text.",
      value: suggestBronzeAsset(fileName, existing),
      valueSelection: [7, Number.MAX_SAFE_INTEGER],
      validateInput: value => validateBronzeAsset(value, existing)
    });
    if (!asset) return;

    try {
      const result = await this.runtimeManager.importCsv(asset.trim(), text, fileName);
      void vscode.window.showInformationMessage(
        `Imported ${result.rows_imported} rows into ${result.asset}. Columns are text; CAST them in SQL when building silver tables.`
      );
    } catch (error) {
      void vscode.window.showErrorMessage(error instanceof Error ? error.message : String(error));
    }
    await this.refresh();
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
    await this.openBeside(uri);
    await this.refresh();
  }

  private async createRetailDemo(): Promise<void> {
    const root = await this.writeRetailDemoFiles();
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating the retail demo.");
      return;
    }

    await this.openPipelineSource();
    await this.openAirflowSource();
    await this.openDbtProject();

    const readme = vscode.Uri.joinPath(root, "README_DATAPASS_RETAIL.md");
    await this.openBeside(readme);
    void vscode.window.showInformationMessage(
      "Datapass retail demo created: dataset, notebook starters, pipeline, Airflow DAG and dbt sample."
    );
    await this.refresh();
  }

  /** The retail demo's dataset, notebooks and README (missing files only). Returns the workspace root. */
  private async writeRetailDemoFiles(): Promise<vscode.Uri | undefined> {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) return undefined;

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
        airflow: [...airflowRoot, "dags", AIRFLOW_STARTER_FILE].join("/"),
        dbtProject: [...dbtRoot, "retail-dbt"].join("/")
      })
    );
    return root;
  }

  private async runActiveSql(): Promise<void> {
    const document = await activeSavedDocument(".sql", "SQL", this.lastDocuments.get(".sql"));
    if (!document) return;

    try {
      await this.runtimeManager.runSql(document.getText());
    } catch (error) {
      void vscode.window.showErrorMessage(
        `SQL execution failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.refresh();
  }

  private async runActivePython(): Promise<void> {
    const trust = await this.pythonTrust.resolve();
    if (!trust.effective || !this.runtimeManager.snapshot().trustedPython) {
      void vscode.window.showWarningMessage(
        trust.effective
          ? "Restart the Datapass runtime to apply trusted local Python."
          : trust.reason
      );
      return;
    }
    const document = await activeSavedDocument(".py", "Python", this.lastDocuments.get(".py"));
    if (!document) return;

    try {
      await this.runtimeManager.runPython(document.getText());
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Python execution failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.refresh();
  }

  private async runActiveSparkLab(profileId: string, aqe: boolean): Promise<void> {
    const document = await activeSavedDocument(".py", "SparkLab (.py)", this.lastDocuments.get(".py"));
    if (!document) return;

    try {
      await this.runtimeManager.runSparkLab(
        document.getText(),
        vscode.workspace.asRelativePath(document.uri),
        profileId,
        aqe
      );
    } catch (error) {
      void vscode.window.showErrorMessage(
        `SparkLab execution failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
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
    await this.openBeside(manifest.uri);
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
    await this.openBeside(uri);
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
    await prepareExerciseWorkspace(this.context.extensionUri, root, exerciseRoot, directory, exercise, console.warn);

    await this.openBeside(starterUri);
  }

  private async gradeExercise(
    exerciseKey: string,
    mode: "run" | "submit"
  ): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before grading a Datapass exercise.");
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
    const starterUri = vscode.Uri.joinPath(
      directory,
      `solution.${extensionFor(exercise.language)}`
    );

    if (!(await exists(starterUri))) {
      await this.openExercise(exerciseKey);
      void vscode.window.showInformationMessage(
        "Exercise starter created. Edit the native solution file, then run the checks."
      );
      return;
    }

    const openDocument = vscode.workspace.textDocuments.find(
      document => document.uri.toString() === starterUri.toString()
    );
    const code = openDocument
      ? openDocument.getText()
      : new TextDecoder().decode(await vscode.workspace.fs.readFile(starterUri));

    if (!code.trim()) {
      void vscode.window.showWarningMessage("The exercise solution file is empty.");
      return;
    }

    try {
      await this.runtimeManager.gradeExercise(exercise.key, {
        exercise_id: exercise.id,
        exercise_version: exercise.version,
        language: exercise.language,
        code,
        mode,
        notebook_id: `exercise-${slug(exercise.id)}-${slug(exercise.version)}`,
        cell_id: "solution",
        source_revision: openDocument?.version ?? 0
      });
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Exercise grading failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.refresh();
  }

  private async runPipeline(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before running a pipeline.");
      return;
    }
    const manifest = await readProjectManifest();
    const pipelineRoot = safeRelativeParts(manifest.manifest?.assets?.pipelines, "pipelines");
    const uri = vscode.Uri.joinPath(root, ...pipelineRoot, "main.pipeline.py");
    if (!(await exists(uri))) {
      await this.openPipelineSource();
      return;
    }

    const source = new TextDecoder().decode(await vscode.workspace.fs.readFile(uri));
    try {
      await this.runtimeManager.runPipeline(source);
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Pipeline execution failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.refresh();
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

    await this.openBeside(uri);
    await this.refresh();
  }

  private async openAirflowSource(): Promise<void> {
    const { root, dagsParts } = await airflowPaths();
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating an Airflow Lab DAG.");
      return;
    }
    const directory = vscode.Uri.joinPath(root, ...dagsParts);
    const uri = vscode.Uri.joinPath(directory, AIRFLOW_STARTER_FILE);
    await vscode.workspace.fs.createDirectory(directory);
    await writeIfMissing(uri, airflowStarter());
    await this.openBeside(uri);
    await this.refresh();
  }

  /** Simulate the active Airflow DAG file (or the starter). The runtime parses it; nothing is executed. */
  private async simulateAirflow(scenario: AirflowScenarioInput): Promise<void> {
    const document = await this.activeAirflowDocument();
    if (!document) return;
    this.lastAirflowFile = document.uri;
    try {
      await this.runtimeManager.simulateAirflow(
        document.getText(),
        vscode.workspace.asRelativePath(document.uri),
        scenario
      );
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Airflow simulation failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.refresh();
  }

  private async activeAirflowDocument(): Promise<vscode.TextDocument | undefined> {
    const isDag = (document: vscode.TextDocument | undefined): document is vscode.TextDocument =>
      document?.uri.scheme === "file" && document.fileName.toLowerCase().endsWith(".py") &&
      /\bairflow\b/.test(document.getText());
    const remembered = this.lastDocuments.get(".py")?.toString();
    let document =
      (isDag(vscode.window.activeTextEditor?.document) ? vscode.window.activeTextEditor!.document : undefined) ??
      vscode.window.visibleTextEditors.map(editor => editor.document).find(isDag) ??
      vscode.workspace.textDocuments.find(candidate => !candidate.isClosed && isDag(candidate) && candidate.uri.toString() === remembered);
    if (!document) {
      const { root, dagsParts } = await airflowPaths();
      const starter = root ? vscode.Uri.joinPath(root, ...dagsParts, AIRFLOW_STARTER_FILE) : undefined;
      if (!starter || !(await exists(starter))) {
        void vscode.window.showWarningMessage("Open an Airflow DAG file (.py), or create the starter DAG first.");
        return undefined;
      }
      document = await vscode.workspace.openTextDocument(starter);
    }
    if (document.isDirty && !(await document.save())) {
      void vscode.window.showWarningMessage("Save the DAG file before simulating it.");
      return undefined;
    }
    return document;
  }

  private async revealAirflowLine(line: number): Promise<void> {
    if (!this.lastAirflowFile || !Number.isInteger(line) || line < 1) return;
    const document = await vscode.workspace.openTextDocument(this.lastAirflowFile);
    const column = this.panel.viewColumn === vscode.ViewColumn.Two ? vscode.ViewColumn.One : vscode.ViewColumn.Two;
    const editor = await vscode.window.showTextDocument(document, { preview: false, viewColumn: column });
    const position = new vscode.Position(Math.min(line, document.lineCount) - 1, 0);
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
  }

  /** Copy the Cloud Lab sample files (Fabric, ADF, Synapse, notebooks, procedures) into factory/, keeping existing files. */
  private async createFactoryLab(): Promise<void> {
    const root = await copyFactorySamples(this.context.extensionUri);
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating the Cloud Lab files.");
      return;
    }
    const starter = pipelineUri("fabric", "pl_retail_daily");
    if (starter && (await exists(starter))) await this.openBeside(starter);
    void vscode.window.showInformationMessage(
      "Cloud Lab files are in factory/: the same daily load for Fabric, Azure Data Factory and Synapse, notebooks, a stored procedure, T-SQL scripts for the SQL pool tab (factory/sql/pool) and Databricks jobs (factory/databricks). Existing files were kept."
    );
    await this.refresh();
  }

  private async openFactoryFile(relative: string): Promise<void> {
    const uri = factoryFileUri(relative);
    if (!uri || !(await exists(uri))) {
      void vscode.window.showWarningMessage(`Cloud Lab file not found: ${relative}`);
      return;
    }
    await this.openBeside(uri);
  }

  /** Open a pipeline file on the activity's "name" entry. */
  private async revealFactoryActivity(relative: string, activity: string): Promise<void> {
    const uri = factoryFileUri(relative);
    if (!uri || !(await exists(uri))) return;
    const document = await vscode.workspace.openTextDocument(uri);
    const offset = document.getText().search(new RegExp(`"name"\\s*:\\s*${escapeRegExp(JSON.stringify(activity))}`));
    const position = offset >= 0 ? document.positionAt(offset) : new vscode.Position(0, 0);
    const column = this.panel.viewColumn === vscode.ViewColumn.Two ? vscode.ViewColumn.One : vscode.ViewColumn.Two;
    const editor = await vscode.window.showTextDocument(document, { preview: false, viewColumn: column });
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
  }

  /** Run a pipeline of the Cloud Lab: the runtime simulates it and runs supported activities on the local catalog. */
  private async simulateFactory(flavor: FactoryFlavor, name: string, scenario: FactoryScenarioInput): Promise<void> {
    if (!FACTORY_FLAVORS.includes(flavor) || !PIPELINE_NAME.test(name)) return;
    const root = factoryRoot();
    if (root) {
      // A run uses the files as saved, like the other labs.
      for (const document of vscode.workspace.textDocuments) {
        if (document.isDirty && document.uri.toString().startsWith(root.toString() + "/")) await document.save();
      }
    }
    const { files, warnings } = await collectFactoryFiles(flavor);
    const path = pipelineRelativePath(flavor, name);
    const document = files.pipelines[name];
    if (!document) {
      void vscode.window.showWarningMessage(`Pipeline ${name} is missing or is not valid JSON (${path}).`);
      return;
    }
    try {
      await this.runtimeManager.simulateFactory({ flavor, name, path, document, files, scenario, warnings });
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Pipeline run failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.refresh();
  }

  /**
   * SQL pool tab: run a script of factory/sql/pool, the active .sql editor, or nothing (describe the
   * tables). The runtime translates the T-SQL; data statements run on the local catalog.
   */
  private async runSqlPool(
    flavor: SqlPoolFlavor,
    scale: number,
    source: "file" | "active" | "describe",
    path?: string
  ): Promise<void> {
    if (!SQLPOOL_FLAVORS.includes(flavor) || !isValidScale(scale)) return;
    let script = "";
    let label = "";
    if (source === "file") {
      const read = path ? await readPoolScript(path) : { error: "No script selected." };
      if (read.error || read.text === undefined) {
        void vscode.window.showWarningMessage(read.error ?? "No script selected.");
        return;
      }
      const uri = factoryFileUri(path!)!;
      const open = vscode.workspace.textDocuments.find(document => document.uri.toString() === uri.toString());
      if (open?.isDirty) await open.save();  // a run uses the file as saved, like the other labs
      script = read.text;
      label = path!;
      this.lastSqlPoolFile = uri;
    } else if (source === "active") {
      const document = await activeSavedDocument(".sql", "SQL", this.lastDocuments.get(".sql"));
      if (!document) return;
      script = document.getText();
      if (script.length > SQLPOOL_LIMITS.scriptChars) {
        void vscode.window.showWarningMessage(`The script is longer than ${SQLPOOL_LIMITS.scriptChars} characters.`);
        return;
      }
      label = vscode.workspace.asRelativePath(document.uri);
      this.lastSqlPoolFile = document.uri;
    }
    try {
      await this.runtimeManager.runSqlPool({ flavor, script, scale, source: label });
    } catch (error) {
      void vscode.window.showErrorMessage(
        `SQL pool run failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.refresh();
  }

  /** Run a Databricks job of the Cloud Lab: the runtime simulates it; notebook and SQL tasks run on the catalog. */
  private async simulateDatabricks(name: string, scenario: DatabricksScenarioInput): Promise<void> {
    if (!JOB_NAME.test(name)) return;
    const root = factoryRoot();
    if (root) {
      for (const document of vscode.workspace.textDocuments) {
        if (document.isDirty && document.uri.toString().startsWith(root.toString() + "/")) await document.save();
      }
    }
    const { files, jobs, warnings } = await collectDatabricksFiles();
    const path = databricksJobPath(name);
    const document = jobs[name];
    if (!document) {
      void vscode.window.showWarningMessage(`Job ${name} is missing or is not valid JSON (${path}).`);
      return;
    }
    try {
      await this.runtimeManager.simulateDatabricks({ name, path, document, files, scenario, warnings });
    } catch (error) {
      void vscode.window.showErrorMessage(`Databricks job run failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.refresh();
  }

  private async refreshDatabricksState(): Promise<void> {
    try {
      await this.runtimeManager.exploreDatabricks((await collectDatabricksFiles()).files);
    } catch (error) {
      void vscode.window.showErrorMessage(`Databricks state refresh failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.refresh();
  }

  /** Copy the BI Lab samples (warehouse scripts and the star model) into bi/, keeping existing files. */
  private async createBiLab(): Promise<void> {
    const root = await copyBiSamples(this.context.extensionUri);
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating the BI Lab files.");
      return;
    }
    const model = biFileUri(BI_MODEL_FILE);
    if (model && (await exists(model))) await this.openBeside(model);
    void vscode.window.showInformationMessage(
      "BI Lab files are in bi/: warehouse scripts that build a star schema from CRM, ERP and shop sources (bi/warehouse, run in name order) and its star model (bi/model.json). Existing files were kept."
    );
    await this.refresh();
  }

  private async openBiFile(relative: string): Promise<void> {
    const uri = biFileUri(relative);
    if (!uri || !(await exists(uri))) {
      void vscode.window.showWarningMessage(`BI Lab file not found: ${relative}`);
      return;
    }
    await this.openBeside(uri);
  }

  /**
   * BI Lab: build (run every script of bi/warehouse in name order), run the active .sql file, or only analyze
   * (lineage and model checks on the tables as they are). The scripts run on the local catalog.
   */
  private async runBiLab(mode: BiRunMode): Promise<void> {
    if (mode !== "build" && mode !== "analyze" && mode !== "active") return;
    const root = biRoot();
    if (root) {
      for (const document of vscode.workspace.textDocuments) {
        if (document.isDirty && document.uri.toString().startsWith(root.toString() + "/")) await document.save();
      }
    }
    let scripts: { path: string; text: string }[];
    let warnings: string[];
    let source: string;
    if (mode === "active") {
      const document = await activeSavedDocument(".sql", "SQL", this.lastDocuments.get(".sql"));
      if (!document) return;
      const text = document.getText();
      if (text.length > BI_LIMITS.scriptChars) {
        void vscode.window.showWarningMessage(`The script is longer than ${BI_LIMITS.scriptChars} characters.`);
        return;
      }
      source = vscode.workspace.asRelativePath(document.uri, false).replaceAll("\\", "/");
      if (!/^[A-Za-z0-9_./ -]{1,200}$/.test(source) || source.split("/").includes("..")) source = "active.sql";
      this.lastBiActiveFile = document.uri;
      scripts = [{ path: source, text }];
      warnings = [];
    } else {
      ({ scripts, warnings } = await collectBiScripts());
      if (!scripts.length) {
        void vscode.window.showWarningMessage("No warehouse scripts in bi/warehouse. Create the BI Lab files first.");
        return;
      }
      source = mode === "build" ? "bi/warehouse" : "analysis only";
    }
    const model = await readBiModel();
    try {
      await this.runtimeManager.runBiLab({ mode, source, scripts, model: model.model, modelError: model.error, warnings });
    } catch (error) {
      void vscode.window.showErrorMessage(`BI Lab run failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.refresh();
  }

  /** BI Lab dbt tab: run a dbt command on bi/dbt with the Datapass dbt emulation (never dbt Core, never a shell). */
  private async runBiDbt(command: BiDbtCommand, selectText: string, fullRefresh: boolean): Promise<void> {
    if (![...DBT_COMMANDS, "parse"].includes(command)) return;
    const parsed = parseSelect(typeof selectText === "string" ? selectText : "");
    if (parsed.error) {
      void vscode.window.showWarningMessage(parsed.error);
      return;
    }
    const root = biRoot();
    if (root) {
      for (const document of vscode.workspace.textDocuments) {
        if (document.isDirty && document.uri.toString().startsWith(root.toString() + "/")) await document.save();
      }
    }
    const { files, warnings } = await collectBiDbtFiles();
    if (!("dbt_project.yml" in files)) {
      void vscode.window.showWarningMessage("No dbt project in bi/dbt. Create the BI Lab files first.");
      return;
    }
    try {
      await this.runtimeManager.runBiDbt({ command, select: parsed.selectors, selectText, fullRefresh: fullRefresh === true, files, warnings });
    } catch (error) {
      void vscode.window.showErrorMessage(`dbt run failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.refresh();
  }

  private async revealBiLine(relative: string, line: number): Promise<void> {
    if (!Number.isInteger(line) || line < 1) return;
    const uri = biFileUri(relative) ?? (this.lastBiActiveFile && vscode.workspace.asRelativePath(this.lastBiActiveFile, false)
      .replaceAll("\\", "/") === relative ? this.lastBiActiveFile : undefined);
    if (!uri || !(await exists(uri))) return;
    const document = await vscode.workspace.openTextDocument(uri);
    const column = this.panel.viewColumn === vscode.ViewColumn.Two ? vscode.ViewColumn.One : vscode.ViewColumn.Two;
    const editor = await vscode.window.showTextDocument(document, { preview: false, viewColumn: column });
    const position = new vscode.Position(Math.min(line, document.lineCount) - 1, 0);
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
  }

  private async revealSqlPoolLine(line: number): Promise<void> {
    if (!this.lastSqlPoolFile || !Number.isInteger(line) || line < 1) return;
    const document = await vscode.workspace.openTextDocument(this.lastSqlPoolFile);
    const column = this.panel.viewColumn === vscode.ViewColumn.Two ? vscode.ViewColumn.One : vscode.ViewColumn.Two;
    const editor = await vscode.window.showTextDocument(document, { preview: false, viewColumn: column });
    const position = new vscode.Position(Math.min(line, document.lineCount) - 1, 0);
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
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
      "samples",
      "dbt",
      "retail-dbt"
    );
    await copyDirectoryWithoutOverwrite(donor, projectRoot);

    if (!(await exists(projectFile))) {
      void vscode.window.showErrorMessage("The bundled dbt retail sample is incomplete: dbt_project.yml was not found.");
      return;
    }

    await ensureDbtProfile(root);
    await this.openBeside(projectFile);
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

  // ---- Projects ----------------------------------------------------------------------------------------

  private async findProject(projectId: string): Promise<ProjectContent | undefined> {
    const project = (await loadProjectContents(this.context.extensionUri)).projects.find(p => p.id === projectId);
    if (!project) void vscode.window.showErrorMessage(`Projet introuvable : ${projectId}`);
    return project;
  }

  /** Create the lab files a step needs, never overwriting the learner's files. */
  private async runScaffolds(project: ProjectContent, names: readonly ProjectScaffold[]): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) return;
    for (const name of new Set(names)) {
      switch (name) {
        case "project":
          await copyProjectFiles(this.context.extensionUri, project.id);
          break;
        case "factory":
          await copyFactorySamples(this.context.extensionUri);
          break;
        case "bi":
          await copyBiSamples(this.context.extensionUri);
          break;
        case "retail_demo":
          await this.writeRetailDemoFiles();
          break;
        case "airflow": {
          const { dagsParts } = await airflowPaths();
          await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(root, ...dagsParts));
          await writeIfMissing(vscode.Uri.joinPath(root, ...dagsParts, AIRFLOW_STARTER_FILE), airflowStarter());
          break;
        }
        case "pipeline": {
          const manifest = await readProjectManifest();
          const directory = vscode.Uri.joinPath(root, ...safeRelativeParts(manifest.manifest?.assets?.pipelines, "pipelines"));
          await vscode.workspace.fs.createDirectory(directory);
          await writeIfMissing(vscode.Uri.joinPath(directory, "main.pipeline.py"), pipelineStarter());
          break;
        }
        case "sparklab": {
          const manifest = await readProjectManifest();
          const directory = vscode.Uri.joinPath(root, ...safeRelativeParts(manifest.manifest?.assets?.notebooks, "notebooks"));
          const spec = scratchSpec("sparklab");
          await vscode.workspace.fs.createDirectory(directory);
          await writeIfMissing(vscode.Uri.joinPath(directory, spec.fileName), spec.content);
          break;
        }
      }
    }
  }

  /** Every file the project's steps need: its starter files and the lab samples. */
  private async prepareProject(projectId: string): Promise<void> {
    if (!vscode.workspace.workspaceFolders?.length) {
      void vscode.window.showWarningMessage("Ouvrez un dossier de workspace avant de préparer un projet.");
      return;
    }
    const project = await this.findProject(projectId);
    if (!project) return;
    await this.runScaffolds(project, project.steps.flatMap(step => step.open.scaffold));
    void vscode.window.showInformationMessage(
      `Fichiers du projet « ${project.title} » prêts (projects/${project.id}/ et les échantillons des labos). Les fichiers existants ont été gardés.`
    );
    await this.refresh();
  }

  /** "Ouvrir dans <lab>": create the step's files, open its file or exercise beside, and show its lab and tab. */
  private async openProjectStep(projectId: string, stepId: string): Promise<void> {
    const project = await this.findProject(projectId);
    const step = project?.steps.find(s => s.id === stepId);
    if (!project || !step) return;
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Ouvrez un dossier de workspace avant d'ouvrir une étape de projet.");
      return;
    }
    await this.runScaffolds(project, step.open.scaffold);
    let query: string | undefined;
    if (step.open.exercise) {
      await this.openExercise(step.open.exercise);
      query = step.open.exercise.split("/")[1];
    } else if (step.open.file && isProjectFilePath(step.open.file)) {
      const uri = vscode.Uri.joinPath(root, ...step.open.file.split("/"));
      if (await exists(uri)) await this.openBeside(uri);
      else void vscode.window.showWarningMessage(`Fichier introuvable : ${step.open.file}`);
    }
    this.selectedModule = step.open.module;
    this.focus = { module: step.open.module, tab: step.open.tab, query, seq: ++this.focusSeq };
    await this.refresh();
  }

  /** "Vérifier": the runtime checks the steps on the workspace; the result is kept in .datapass/progress.json. */
  private async verifyProjectSteps(projectId: string, stepIds: string[]): Promise<void> {
    if (this.runtimeManager.snapshot().status !== "running") {
      void vscode.window.showWarningMessage("Démarrez le runtime Datapass pour vérifier les étapes : il lit le catalogue et le journal des exécutions.");
      return;
    }
    const project = await this.findProject(projectId);
    if (!project || !Array.isArray(stepIds)) return;
    const known = stepIds.filter(id => project.steps.some(step => step.id === id && step.checks.length));
    if (!known.length) return;
    this.projectsHost = { verifying: { projectId, stepIds: known } };
    await this.refresh();
    try {
      const progress = await readProgress();
      if (progress.error) throw new Error(`${progress.error} Corrigez ou supprimez le fichier, puis vérifiez à nouveau.`);
      const result = await this.runtimeManager.checkProject(projectId, known);
      await writeProgress(applyVerification(progress.document, project, result, new Date().toISOString()));
      this.projectsHost = {};
    } catch (error) {
      this.projectsHost = { error: `Vérification impossible : ${error instanceof Error ? error.message : String(error)}` };
    }
    await this.refresh();
  }

  /** The learner ticks a step by hand: kept as a declaration, never as a verification. */
  private async setProjectStepManual(projectId: string, stepId: string, checked: boolean): Promise<void> {
    if (!vscode.workspace.workspaceFolders?.length) {
      void vscode.window.showWarningMessage("Ouvrez un dossier de workspace pour garder la progression.");
      return;
    }
    const project = await this.findProject(projectId);
    if (!project || !project.steps.some(step => step.id === stepId)) return;
    const progress = await readProgress();
    if (progress.error) {
      void vscode.window.showErrorMessage(`${progress.error} Corrigez ou supprimez le fichier.`);
      return;
    }
    await writeProgress(setManual(progress.document, project, stepId, checked === true, new Date().toISOString()));
    await this.refresh();
  }

  private async openProgressFile(): Promise<void> {
    const uri = progressUri();
    if (!uri) return;
    if (!(await exists(uri))) {
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(uri, ".."));
      await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(serializeProgress(emptyProgress())));
    }
    await this.openBeside(uri);
  }

  private async refresh(): Promise<void> {
    // A slow refresh (the Practice catalog) must not land after a newer one and switch the module back.
    const seq = ++this.refreshSeq;
    const state = await collectWorkbenchState(
      this.selectedModule,
      this.runtimeManager,
      this.context.extensionUri,
      this.pythonTrust,
      { focus: this.focus, projects: this.projectsHost }
    );
    if (seq !== this.refreshSeq) return;
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

function extensionFor(language: string): string {
  switch (language.toLowerCase()) {
    case "sql":
    case "dbt":
    case "sqlpool":
    case "databricks-grants":
    case "warehouse":
    case "dbt-sql":
    case "snowflake":
      return "sql";
    case "python":
    case "pandas":
    case "polars":
    case "sparklab":
    case "pyspark":
    case "airflow":
    case "factory-notebook":
    case "databricks-notebook":
      return "py";
    case "factory":
    case "databricks-job":
    case "bi-model":
      return "json";
    case "powershell":
      return "ps1";
    case "yaml":
    case "yml":
    case "dbt-yml":
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

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function quoteShellArg(value: string): string {
  return `"${value.replaceAll('"', '\\"')}"`;
}

async function activeSavedDocument(
  extension: string,
  label: string,
  remembered?: vscode.Uri
): Promise<vscode.TextDocument | undefined> {
  const matches = (candidate: vscode.TextDocument | undefined) =>
    candidate?.uri.scheme === "file" && candidate.fileName.toLowerCase().endsWith(extension);
  // Clicking the Workbench hides a file that shares its tab group, so fall back
  // from the active editor to a visible one, then to the last focused file.
  const document =
    (matches(vscode.window.activeTextEditor?.document) ? vscode.window.activeTextEditor!.document : undefined) ??
    vscode.window.visibleTextEditors.map(editor => editor.document).find(matches) ??
    vscode.workspace.textDocuments.find(candidate =>
      !candidate.isClosed && matches(candidate) && candidate.uri.toString() === remembered?.toString()
    );
  if (!document) {
    void vscode.window.showWarningMessage(`Open a ${label} file in VS Code before running it.`);
    return undefined;
  }
  if (document.isDirty && !(await document.save())) {
    void vscode.window.showWarningMessage(`Save the ${label} file before running it.`);
    return undefined;
  }
  return document;
}

async function exists(uri: vscode.Uri): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}
