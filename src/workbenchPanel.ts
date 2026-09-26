import * as vscode from "vscode";
import { AIRFLOW_STARTER_FILE, airflowPaths } from "./airflowState";
import { biFileUri, biRoot, collectBiDbtFiles, collectBiScripts, copyBiSamples, readBiModel } from "./biState";
import { BI_LIMITS, BI_MODEL_FILE, DBT_COMMANDS, parseSelect } from "./platform/biRun";
import { loadExerciseCatalog } from "./exerciseCatalog";
import { prepareExerciseWorkspace } from "./exerciseWorkspace";
import { decodeCsvBytes, suggestBronzeAsset, validateBronzeAsset } from "./platform/csvImport";
import {
  FILE_IMPORT_MAX_BYTES,
  IMPORT_FILTERS,
  addQueryHistory,
  importFormat,
  restoreQueryHistory,
  type QueryHistoryEntry
} from "./platform/mosaicTools";

/** Mosaic query history, per workspace; not a project file (it may contain ad-hoc SQL). */
const QUERY_HISTORY_KEY = "datapass.mosaic.queryHistory";
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
import { findDbtProjects, projectFolder } from "./dbtState";
import { dctValidate, writeDbtProfiles, type DbtTerminalSession, type DbtToolsManager } from "./dbtLab";
import type { MissionsService } from "./missions";
import { missionFolder, type MissionView } from "./platform/missions";
import { preferredShell, type ShellId } from "./platform/terminalShells";
import type { TerminalLabSession } from "./terminalLab";
import type { InfraLabSession } from "./infraLab";
import {
  buildDbtCommand,
  buildDctCommand,
  isBoardPath,
  renderPath,
  type DbtCommand,
  type DctFormat,
  type DctValidationView
} from "./platform/dbtTools";
import { findFreePort } from "./platform/runtimeEndpoint";
import * as http from "node:http";
import * as path from "node:path";
import { MODULES, type ModuleId } from "./modules";
import { writeMosaicLayout } from "./mosaicLayoutStore";
import { openQueryPlan, openTranslatedSql } from "./queryPlanDocuments";
import { runDialect, TranslatedDialectId } from "./platform/sqlDialect";
import { createDefaultProjectManifest, readProjectManifest, writeProjectManifest } from "./project/projectManifest";
import type { PythonTrustController } from "./pythonTrustController";
import type { RuntimeManager } from "./runtimeManager";
import { retailDemoReadme, retailOrdersCsv, retailPythonStarter, retailSqlStarter } from "./scaffold/retailDemo";
import { airflowStarter, pipelineStarter, scratchSpec } from "./scaffold/starters";
import { exerciseReadme } from "./scaffold/exerciseReadme";
import { collectWorkbenchState } from "./workbenchState";
import { copyProjectFiles, loadProjectContents, progressUri, readProgress, updateProgress, writeProgress } from "./projectState";
import { recordGrade, recordInterview, recordOpened, recordSolutionViewed, revealHint } from "./platform/practiceProgress";
import { SOLUTION_AFTER_FAILURES, solutionUnlocked } from "./platform/practiceFeedback";
import { loadReferenceSolution, referenceUri } from "./referenceSolutions";
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
  TerminalViewState,
  InfraViewState,
  InfraWorldView,
  WebviewToHostMessage,
  WorkbenchFocus
} from "./webview/contracts";

/**
 * The labs' host services: the dbt Lab's managed dbt tools and the terminal that runs real dbt Core commands, the
 * missions (shared by the dbt Lab, the Terminal Lab and the Infra Lab), the Terminal Lab's shells and terminals, and
 * the Infra Lab's simulated terminals.
 */
export interface DbtLabServices {
  tools: DbtToolsManager;
  terminal: DbtTerminalSession;
  missions: MissionsService;
  terminalLab: TerminalLabSession;
  infraLab: InfraLabSession;
}

const DBT_SELECTED_KEY = "datapass.dbt.selectedProject";

export class WorkbenchPanel {
  private static current?: WorkbenchPanel;

  static async show(
    context: vscode.ExtensionContext,
    runtimeManager: RuntimeManager,
    pythonTrust: PythonTrustController,
    initialModule: ModuleId,
    dbtLab: DbtLabServices
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
      initialModule,
      dbtLab
    );
  }

  private selectedModule: ModuleId;
  private readonly disposables: vscode.Disposable[] = [];
  /** Last focused file per extension, so "Run active ..." works when the Workbench shares a tab group with it. */
  private readonly lastDocuments = new Map<string, vscode.Uri>();
  /** The SQL file of the last Run active SQL: names its translated SQL tab. */
  private lastSqlFile: string | undefined;
  /** The DAG file Airflow Lab last simulated, to reveal a parser error line in it. */
  private lastAirflowFile?: vscode.Uri;
  /** The T-SQL script the SQL pool tab last ran, to reveal a statement's line in it. */
  private lastSqlPoolFile?: vscode.Uri;
  /** `dct validate --json` results per `<project>::<board>`, shown next to each board. */
  private readonly dctValidations = new Map<string, DctValidationView>();
  /** Reference solutions revealed in this panel, by exercise key (the text is read from the pack on demand). */
  private readonly revealedSolutions = new Map<string, string>();
  /** A broken progress.json is reported once per panel, not on every grading. */
  private practiceProgressWarned = false;
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
    initialModule: ModuleId,
    private readonly dbtLab: DbtLabServices
  ) {
    this.selectedModule = initialModule;
    this.rememberEditor(vscode.window.activeTextEditor);
    this.panel.webview.html = this.html(this.panel.webview);
    // A real dbt run rewrites target/run_results.json and target/manifest.json.
    const dbtArtifactWatcher = vscode.workspace.createFileSystemWatcher("**/target/{manifest,run_results}.json");

    this.disposables.push(
      dbtArtifactWatcher,
      dbtArtifactWatcher.onDidCreate(() => {
        if (this.selectedModule === "dbt") void this.refresh();
      }),
      dbtArtifactWatcher.onDidChange(() => {
        if (this.selectedModule === "dbt") void this.refresh();
        // Without shell integration the terminal never reports the end of a command: new artifacts are the signal.
        if (this.runtimeManager.snapshot().catalogLease && !this.dbtLab.terminal.hasShellIntegration) {
          setTimeout(() => void this.runtimeManager.reattachCatalog(), 2000);
        }
      }),
      this.dbtLab.tools.onDidChange(() => {
        if (this.selectedModule === "dbt") void this.refresh();
      }),
      this.dbtLab.terminal.onDidEndCommand(() => {
        if (this.selectedModule === "dbt") void this.refresh();
      }),
      this.dbtLab.infraLab.onDidRunCommand(() => {
        if (this.selectedModule === "infra") void this.refresh();
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
      case "importFile":
        await this.importFile();
        return;
      case "profileTable":
        await this.guarded("Profile", () => this.runtimeManager.profileTable(message.asset));
        return;
      case "explainActiveSql":
        await this.explainActiveSql();
        return;
      case "openQueryPlan": {
        const plan = this.runtimeManager.snapshot().queryPlan;
        if (plan) await openQueryPlan(plan);
        return;
      }
      case "openTranslatedSql": {
        const translation = this.runtimeManager.snapshot().lastRun?.dialect;
        if (translation) await openTranslatedSql(translation, this.lastSqlFile);
        return;
      }
      case "rerunQuery":
        await this.rerunQuery(message.id);
        return;
      case "openQueryFile":
        await this.openQueryFile(message.id);
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
      case "revealHint":
        await this.revealHint(message.exerciseKey);
        return;
      case "showSolution":
        await this.showSolution(message.exerciseKey);
        return;
      case "compareSolution":
        await this.compareSolution(message.exerciseKey);
        return;
      case "saveInterview":
        await this.saveInterview(message.interview);
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
      case "createDbtSample":
        await this.createDbtSample();
        return;
      case "selectDbtProject":
        await this.context.workspaceState.update(DBT_SELECTED_KEY, message.path);
        await this.refresh();
        return;
      case "refreshDbt":
        this.dbtLab.tools.refresh();
        await this.refresh();
        return;
      case "installDbtTools":
        await this.installDbtTools();
        return;
      case "showDbtToolsLog":
        this.dbtLab.tools.showLog();
        return;
      case "runDbtCommand":
        await this.runDbtCommand(message.command, message.select, message.exclude, message.fullRefresh);
        return;
      case "openDbtTerminal":
        await this.runDbtCommand(undefined, "", "", false);
        return;
      case "openDbtFile":
        await this.openDbtFile(message.path);
        return;
      case "runDct":
        await this.runDct(message.action, message.board, message.format);
        return;
      case "serveDct":
        await this.serveDct();
        return;
      case "stopDctServe":
        this.dbtLab.terminal.stopServe();
        await this.refresh();
        return;
      case "openDctHtml":
        await this.openDctHtml(message.board);
        return;
      case "selectTerminalShell":
        await this.dbtLab.terminalLab.choose(message.shell);
        await this.refresh();
        return;
      case "openLabTerminal":
        await this.openLabTerminal(message.missionId);
        return;
      case "refreshTerminalLab":
        await this.dbtLab.terminalLab.detect(true);
        await this.refresh();
        return;
      case "openInfraTerminal":
        await this.openInfraTerminal(message.missionId);
        return;
      case "selectInfraFolder":
        if (/^missions\/[a-z0-9][a-z0-9-]{0,47}$/.test(message.folder)) await this.dbtLab.infraLab.select(message.folder);
        await this.refresh();
        return;
      case "refreshInfraLab":
        await this.refresh();
        return;
      case "startMission":
      case "restartMission":
      case "openMission":
      case "loadMissionBatch":
      case "revealMissionHint":
      case "checkMission":
        await this.missionAction(message.type, message.missionId);
        return;
      case "reattachCatalog":
        if (!(await this.runtimeManager.reattachCatalog())) {
          void vscode.window.showWarningMessage(this.runtimeManager.snapshot().catalogLease?.reattachError ?? "The catalog is still held.");
        }
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
  /** CSV, Parquet or JSON into a new bronze table. The file's CONTENT is sent, never its path. */
  private async importFile(): Promise<void> {
    if (this.runtimeManager.snapshot().status !== "running") {
      void vscode.window.showWarningMessage("Start the Datapass runtime before importing a file.");
      return;
    }
    const picked = await vscode.window.showOpenDialog({
      canSelectMany: false,
      canSelectFolders: false,
      defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri,
      filters: IMPORT_FILTERS,
      openLabel: "Import into catalog",
      title: "Import a CSV, Parquet or JSON file into the local catalog (new bronze table)"
    });
    const uri = picked?.[0];
    if (!uri) return;
    const fileName = uri.path.split("/").pop() ?? "data";
    const format = importFormat(fileName);
    if (!format) {
      void vscode.window.showErrorMessage("Import a .csv, .parquet, .json, .jsonl or .ndjson file.");
      return;
    }
    if (format !== "csv") {
      await this.importTypedFile(uri, fileName, format);
      return;
    }

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

  private async importTypedFile(uri: vscode.Uri, fileName: string, format: "parquet" | "json"): Promise<void> {
    const bytes = await vscode.workspace.fs.readFile(uri);
    if (!bytes.byteLength || bytes.byteLength > FILE_IMPORT_MAX_BYTES) {
      void vscode.window.showErrorMessage(`Import files must be 1 byte to ${FILE_IMPORT_MAX_BYTES / 1_000_000} MB; ${fileName} is ${bytes.byteLength.toLocaleString()} bytes.`);
      return;
    }
    const existing = (this.runtimeManager.snapshot().catalog ?? []).map(asset => asset.name);
    const asset = await vscode.window.showInputBox({
      title: `Import ${fileName}`,
      prompt: `New bronze table name. Imports never overwrite; column types come from the ${format === "parquet" ? "Parquet file" : "JSON (DuckDB read_json_auto)"}.`,
      value: suggestBronzeAsset(fileName, existing),
      valueSelection: [7, Number.MAX_SAFE_INTEGER],
      validateInput: value => validateBronzeAsset(value, existing)
    });
    if (!asset) return;
    try {
      const result = await this.runtimeManager.importFile(asset.trim(), format, Buffer.from(bytes).toString("base64"), fileName);
      void vscode.window.showInformationMessage(`Imported ${result.rows_imported} rows into ${result.asset} with typed columns.`);
    } catch (error) {
      void vscode.window.showErrorMessage(error instanceof Error ? error.message : String(error));
    }
    await this.refresh();
  }

  /** EXPLAIN ANALYZE of the active SQL file, or of its selection when there is one. */
  private async explainActiveSql(): Promise<void> {
    const document = await activeSavedDocument(".sql", "SQL", this.lastDocuments.get(".sql"));
    if (!document) return;
    const editor = vscode.window.visibleTextEditors.find(candidate => candidate.document === document);
    const selected = editor && !editor.selection.isEmpty ? document.getText(editor.selection) : undefined;
    const sql = selected?.trim() ? selected : document.getText();
    const file = vscode.workspace.asRelativePath(document.uri, false);
    // The dialect is the file's (its first line), also when only a selection is explained.
    const { dialect, error } = runDialect(document.getText());
    if (error) {
      void vscode.window.showErrorMessage(error);
      return;
    }
    await this.recordQuery("explain", sql, file, async () => {
      const plan = await this.runtimeManager.explainQuery(sql, selected ? `${file} (selection)` : file, dialect);
      return { status: "success", elapsedMs: plan.elapsed_ms };
    }, dialect);
    await this.refresh();
  }

  private async rerunQuery(id: string): Promise<void> {
    const entry = this.queryHistory().find(item => item.id === id);
    if (!entry) return;
    await this.recordQuery(entry.kind, entry.sql, entry.file, async () => {
      if (entry.kind === "explain") {
        const plan = await this.runtimeManager.explainQuery(entry.sql, entry.file, entry.dialect);
        return { status: "success", elapsedMs: plan.elapsed_ms };
      }
      const run = await this.runtimeManager.runSql(entry.sql, entry.dialect);
      return { status: run.status, elapsedMs: run.elapsed_ms, rows: run.result?.rows.length, error: run.error?.message };
    }, entry.dialect);
    await this.refresh();
  }

  private async openQueryFile(id: string): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    const entry = this.queryHistory().find(item => item.id === id);
    if (!root || !entry?.file) return;
    const uri = vscode.Uri.joinPath(root, ...entry.file.split("/"));
    if (await exists(uri)) await this.openBeside(uri);
    else void vscode.window.showWarningMessage(`${entry.file} no longer exists.`);
  }

  private queryHistory(): QueryHistoryEntry[] {
    return restoreQueryHistory(this.context.workspaceState.get(QUERY_HISTORY_KEY));
  }

  /** Runs one Mosaic query action and keeps it in the workspace's query history, failures included. */
  private async recordQuery(
    kind: QueryHistoryEntry["kind"],
    sql: string,
    file: string | undefined,
    action: () => Promise<{ status: "success" | "error"; elapsedMs: number; rows?: number; error?: string }>,
    dialect?: TranslatedDialectId
  ): Promise<void> {
    let outcome: { status: "success" | "error"; elapsedMs: number; rows?: number; error?: string };
    try {
      outcome = await action();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      outcome = { status: "error", elapsedMs: 0, error: message };
      void vscode.window.showErrorMessage(message);
    }
    const entry: QueryHistoryEntry = {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      at: new Date().toISOString(),
      kind,
      file,
      sql,
      ...(dialect ? { dialect } : {}),
      ...outcome
    };
    await this.context.workspaceState.update(QUERY_HISTORY_KEY, addQueryHistory(this.queryHistory(), entry));
  }

  private async guarded(what: string, action: () => Promise<void>): Promise<void> {
    try {
      await action();
    } catch (error) {
      void vscode.window.showErrorMessage(`${what}: ${error instanceof Error ? error.message : String(error)}`);
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
    await this.createDbtSample();

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
    // `-- dialect: <name>` on the first line: the runtime translates the file to DuckDB (the SQL: status bar item).
    const { dialect, error } = runDialect(document.getText());
    if (error) {
      void vscode.window.showErrorMessage(error);
      return;
    }
    this.lastSqlFile = vscode.workspace.asRelativePath(document.uri, false);

    await this.recordQuery("run", document.getText(), vscode.workspace.asRelativePath(document.uri, false), async () => {
      try {
        const run = await this.runtimeManager.runSql(document.getText(), dialect);
        return { status: run.status, elapsedMs: run.elapsed_ms, rows: run.result?.rows.length, error: run.error?.message };
      } catch (error) {
        throw new Error(`SQL execution failed: ${error instanceof Error ? error.message : String(error)}`);
      }
    }, dialect);
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
    await this.savePracticeProgress(document => ({
      ...document,
      practice: recordOpened(document.practice, exercise.key, new Date().toISOString())
    }));

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
      const result = this.runtimeManager.snapshot().practiceResult;
      if (result?.exerciseKey === exercise.key) {
        await this.savePracticeProgress(document => ({
          ...document,
          practice: recordGrade(document.practice, exercise.key, exercise.version, mode, result.status, new Date().toISOString())
        }));
      }
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Exercise grading failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.refresh();
  }

  /** One more hint for an exercise; the count is kept in .datapass/progress.json. */
  private async revealHint(exerciseKey: string): Promise<void> {
    const exercise = (await loadExerciseCatalog(this.context.extensionUri)).find(item => item.key === exerciseKey);
    if (!exercise?.hints.length) return;
    await this.savePracticeProgress(document => ({
      ...document,
      practice: revealHint(document.practice, exercise.key, exercise.hints.length)
    }));
    await this.refresh();
  }

  /**
   * The pack's reference solution and explanation, once the exercise is solved or after a few failed gradings.
   * Reference solutions ship in the VSIX: this is a teaching choice, not an exam control.
   */
  private async showSolution(exerciseKey: string): Promise<string | undefined> {
    const exercise = (await loadExerciseCatalog(this.context.extensionUri)).find(item => item.key === exerciseKey);
    if (!exercise) return undefined;
    const record = (await readProgress()).document.practice?.exercises[exercise.key];
    if (!solutionUnlocked(record)) {
      void vscode.window.showInformationMessage(
        `The reference solution opens once you solve the exercise, or after ${SOLUTION_AFTER_FAILURES} gradings that do not pass.`
      );
      return undefined;
    }
    const code = await loadReferenceSolution(this.context.extensionUri, exercise);
    if (code === undefined) {
      void vscode.window.showWarningMessage("This exercise has no reference solution to show.");
      return undefined;
    }
    this.revealedSolutions.set(exercise.key, code);
    await this.savePracticeProgress(document => ({
      ...document,
      practice: recordSolutionViewed(document.practice, exercise.key, new Date().toISOString())
    }));
    await this.refresh();
    return code;
  }

  /** VS Code's diff editor: the reference (read-only) on the left, the learner's solution file on the right. */
  private async compareSolution(exerciseKey: string): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    const exercise = (await loadExerciseCatalog(this.context.extensionUri)).find(item => item.key === exerciseKey);
    if (!root || !exercise) return;
    const code = this.revealedSolutions.get(exerciseKey) ?? await this.showSolution(exerciseKey);
    if (code === undefined) return;
    const manifest = await readProjectManifest();
    const exerciseRoot = safeRelativeParts(manifest.manifest?.assets?.exercises, "exercises");
    const extension = extensionFor(exercise.language);
    const mine = vscode.Uri.joinPath(root, ...exerciseRoot, slug(exercise.id), slug(exercise.language), `solution.${extension}`);
    if (!(await exists(mine))) {
      void vscode.window.showWarningMessage("Open the exercise first: there is no solution file to compare yet.");
      return;
    }
    await vscode.commands.executeCommand("vscode.diff", referenceUri(exercise, extension), mine, `${exercise.id}: reference ↔ your solution`, {
      viewColumn: vscode.ViewColumn.Beside
    });
  }

  /** A finished interview's summary, validated before it joins .datapass/progress.json. */
  private async saveInterview(interview: unknown): Promise<void> {
    await this.savePracticeProgress(document => ({ ...document, practice: recordInterview(document.practice, interview) }));
    await this.refresh();
  }

  /** Practice progress lives in .datapass/progress.json next to the Projects progress. Saving it never blocks Practice. */
  private async savePracticeProgress(update: Parameters<typeof updateProgress>[0]): Promise<void> {
    if (!vscode.workspace.workspaceFolders?.length) return;
    try {
      await updateProgress(update);
    } catch (error) {
      if (this.practiceProgressWarned) return;
      this.practiceProgressWarned = true;
      void vscode.window.showWarningMessage(
        `Practice progress was not saved: ${error instanceof Error ? error.message : String(error)} Fix or delete .datapass/progress.json.`
      );
    }
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

  /** Copy the bundled retail dbt sample to <assets.dbt>/retail-dbt (never overwriting) and select it. */
  private async createDbtSample(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating a dbt project.");
      return;
    }
    const manifest = await readProjectManifest();
    const dbtRoot = safeRelativeParts(manifest.manifest?.assets?.dbt, "dbt");
    const projectRoot = vscode.Uri.joinPath(root, ...dbtRoot, "retail-dbt");
    await copyDirectoryWithoutOverwrite(vscode.Uri.joinPath(this.context.extensionUri, "samples", "dbt", "retail-dbt"), projectRoot);
    const projectFile = vscode.Uri.joinPath(projectRoot, "dbt_project.yml");
    if (!(await exists(projectFile))) {
      void vscode.window.showErrorMessage("The bundled dbt retail sample is incomplete: dbt_project.yml was not found.");
      return;
    }
    await this.context.workspaceState.update(DBT_SELECTED_KEY, [...dbtRoot, "retail-dbt"].join("/"));
    await writeDbtProfiles(root, (await findDbtProjects()).map(project => project.file));
    await this.openBeside(projectFile);
    await this.refresh();
  }

  /** Explicit action only: create the managed dbt tools environment and install dbt Core, dbt-duckdb and dbt Charts in it. */
  private async installDbtTools(): Promise<void> {
    const choice = await vscode.window.showInformationMessage(
      "Install dbt Core, dbt-duckdb and dbt Charts for the dbt Lab? Datapass creates (or updates) a separate Python environment in its " +
      "extension storage (about 250 MB, a few minutes). Nothing else on your machine changes.",
      { modal: true },
      "Install dbt tools"
    );
    if (choice !== "Install dbt tools") return;
    const runtimeEnv = this.runtimeManager.snapshot().environment;
    try {
      await this.dbtLab.tools.install(runtimeEnv?.status === "ready" ? runtimeEnv.python : undefined);
      void vscode.window.showInformationMessage("dbt tools installed. Pick a command in the dbt Lab: it runs in a terminal in the project folder.");
    } catch (error) {
      void vscode.window.showErrorMessage(`dbt tools install failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.refresh();
  }

  /**
   * Type a real dbt Core command in the dbt Lab terminal (project folder, managed tools on PATH, generated profiles).
   * Without a command, only open the terminal for the learner to type in.
   */
  private async runDbtCommand(command: DbtCommand | undefined, select: string, exclude: string, fullRefresh: boolean): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before running dbt.");
      return;
    }
    if (this.dbtLab.tools.refresh().status !== "ready") {
      void vscode.window.showWarningMessage("Install the dbt tools first (dbt Lab > Install dbt tools).");
      return;
    }
    const projects = await findDbtProjects();
    const selected = this.context.workspaceState.get<string>(DBT_SELECTED_KEY);
    const project = projects.find(item => item.path === selected) ?? projects[0];
    const folder = project ? projectFolder(project.path) : undefined;
    if (!project || !folder) {
      void vscode.window.showWarningMessage("No dbt project in this workspace. Create the retail sample or start a mission first.");
      return;
    }
    let commandLine: string | undefined;
    try {
      commandLine = command ? buildDbtCommand({ command, select, exclude, fullRefresh }) : undefined;
    } catch (error) {
      void vscode.window.showWarningMessage(error instanceof Error ? error.message : String(error));
      return;
    }
    const profilesDir = await writeDbtProfiles(root, projects.map(item => item.file));
    await this.dbtLab.terminal.run(folder, profilesDir, commandLine);
    await this.refresh();
  }

  /** Missions: start, start over, open, load the next batch, reveal a hint, or run the hidden checker. */
  private async missionAction(action: string, missionId: string): Promise<void> {
    const missions = this.dbtLab.missions;
    try {
      const mission = await missions.mission(missionId);
      const terminal = mission.lab === "terminal";
      const infra = mission.lab === "infra";
      if (action === "restartMission") {
        const choice = await vscode.window.showWarningMessage(
          infra
            ? `Start the mission over? missions/${missionId} is moved to .datapass/missions/attic/ (nothing is deleted) and rebuilt as the ticket found it, with a fresh simulated world. Its simulated terminal is closed.`
            : terminal
            ? `Start the mission over? missions/${missionId} is moved to .datapass/missions/attic/ (nothing is deleted) and rebuilt as the ticket found it. Its terminals are closed.`
            : "Start the mission over? Its data in the catalog is reloaded from the first batch and the tables dbt built for it are dropped. Your files in the mission folder stay as they are.",
          { modal: true }, "Start over");
        if (choice !== "Start over") return;
      }
      if (action === "startMission" || action === "restartMission") {
        const restore = terminal ? await this.dbtLab.terminalLab.release(missions.folderUri(missionId)) : undefined;
        if (infra && this.dbtLab.infraLab.closeIn(missionFolder(missionId))) await new Promise(resolve => setTimeout(resolve, 300));
        try {
          await missions.start(missionId);
        } finally {
          await restore?.();
        }
        await (infra ? this.openInfraMission(mission) : terminal ? this.openTerminalMission(mission) : this.openMission(missionId));
      } else if (action === "openMission") {
        await (infra ? this.openInfraMission(mission) : terminal ? this.openTerminalMission(mission) : this.openMission(missionId));
      } else if (action === "loadMissionBatch") {
        const label = await missions.loadNextBatch(missionId);
        if (label) void vscode.window.showInformationMessage(`Loaded: ${label}. Run dbt again, as the nightly job would.`);
      } else if (action === "revealMissionHint") {
        await missions.revealHint(missionId);
      } else if (action === "checkMission") {
        await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Checking the mission…" },
          () => missions.check(missionId));
      }
    } catch (error) {
      void vscode.window.showErrorMessage(`Mission: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.refresh();
  }

  /** Infra Lab: the ticket beside the Workbench and the simulated terminal of the mission folder. */
  private async openInfraMission(mission: MissionView): Promise<void> {
    const ticket = this.dbtLab.missions.ticketUri(mission);
    if (await exists(ticket)) await this.openBeside(ticket);
    await this.openInfraTerminal(mission.id);
  }

  /**
   * The Infra Lab's simulated terminal in a mission folder (the selected one without an id). It is a Pseudoterminal:
   * no process starts; each line goes to the runtime's simulated shell.
   */
  private async openInfraTerminal(missionId?: string): Promise<void> {
    const folder = missionId ? missionFolder(missionId) : this.dbtLab.infraLab.folder;
    if (!folder) {
      void vscode.window.showWarningMessage("Start an Infra Lab mission first: its simulated terminal opens in the mission folder.");
      return;
    }
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root || !(await exists(vscode.Uri.joinPath(root, ...folder.split("/"))))) {
      void vscode.window.showWarningMessage(`${folder} does not exist yet: start the mission first.`);
      return;
    }
    await this.dbtLab.infraLab.open(folder, folder.split("/").pop() ?? folder);
    await this.refresh();
  }

  /** Terminal Lab: the ticket beside the Workbench and a terminal in the mission folder, with the learner's shell. */
  private async openTerminalMission(mission: MissionView): Promise<void> {
    const ticket = this.dbtLab.missions.ticketUri(mission);
    if (await exists(ticket)) await this.openBeside(ticket);
    await this.openLabTerminal(mission.id);
  }

  /** A terminal in the mission folder (or the workspace folder), with the chosen shell. Nothing is typed in it. */
  private async openLabTerminal(missionId?: string): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder first.");
      return;
    }
    const lab = this.dbtLab.terminalLab;
    const shell: ShellId | undefined = preferredShell((await lab.detect()).shells, lab.chosen);
    if (!shell) {
      void vscode.window.showWarningMessage("No bash or PowerShell was found. Install Git for Windows (Git Bash) or PowerShell 7, then Refresh.");
      return;
    }
    const folder = missionId ? this.dbtLab.missions.folderUri(missionId) : root;
    if (missionId && !(await exists(folder))) {
      void vscode.window.showWarningMessage(`missions/${missionId} does not exist yet: start the mission first.`);
      return;
    }
    try {
      await lab.open(folder, shell, missionId ?? "Terminal Lab");
    } catch (error) {
      void vscode.window.showErrorMessage(error instanceof Error ? error.message : String(error));
    }
  }

  /** Select the mission's project in the dbt Lab and open its TICKET.md. */
  private async openMission(missionId: string): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) return;
    const folder = missionFolder(missionId);
    await this.context.workspaceState.update(DBT_SELECTED_KEY, folder);
    const ticket = vscode.Uri.joinPath(root, ...folder.split("/"), "TICKET.md");
    if (await exists(ticket)) await this.openBeside(ticket);
  }

  /** The selected dbt project and its folder, or undefined (with a message) when there is none. */
  private async selectedDbtProject(): Promise<{ path: string; folder: vscode.Uri; files: vscode.Uri[] } | undefined> {
    const projects = await findDbtProjects();
    const selected = this.context.workspaceState.get<string>(DBT_SELECTED_KEY);
    const project = projects.find(item => item.path === selected) ?? projects[0];
    const folder = project ? projectFolder(project.path) : undefined;
    if (!project || !folder) {
      void vscode.window.showWarningMessage("No dbt project in this workspace. Create the retail sample or start a mission first.");
      return undefined;
    }
    return { path: project.path, folder, files: projects.map(item => item.file) };
  }

  /** dbt Charts needs the managed tools with dbt-charts in them. */
  private dctReady(): boolean {
    const tools = this.dbtLab.tools.refresh();
    if (tools.status !== "ready") {
      void vscode.window.showWarningMessage("Install the dbt tools first (dbt Lab > Install dbt tools).");
      return false;
    }
    if (!tools.versions?.["dbt-charts"]) {
      void vscode.window.showWarningMessage("dbt Charts is not in the dbt tools yet: use Update dbt tools in the dbt Lab.");
      return false;
    }
    return true;
  }

  /**
   * dbt Charts: type `dct validate` or `dct render` in the dbt terminal. Validate also runs `dct validate --json`
   * (no database, nothing executed) to show the result next to the board; render borrows the catalog like dbt.
   */
  private async runDct(action: "validate" | "render", board: string, format: DctFormat | undefined): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root || !this.dctReady() || !isBoardPath(board)) return;
    const project = await this.selectedDbtProject();
    if (!project) return;
    const profilesDir = await writeDbtProfiles(root, project.files);
    const commandLine = action === "validate"
      ? buildDctCommand({ action, board })
      : buildDctCommand({ action, board, format: format ?? "png" });
    // dct writes --output files but does not create their folder (dct 0.8).
    if (action === "render") await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(project.folder, "renders"));
    await this.dbtLab.terminal.run(project.folder, profilesDir, commandLine);
    if (action === "validate") {
      this.dctValidations.set(`${project.path}::${board}`, await dctValidate(this.dbtLab.tools, project.folder, profilesDir, board));
    }
    await this.refresh();
  }

  /** `dct serve` on a free loopback port in its own terminal, then the board list in VS Code's Simple Browser. */
  private async serveDct(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root || !this.dctReady()) return;
    const project = await this.selectedDbtProject();
    if (!project) return;
    const profilesDir = await writeDbtProfiles(root, project.files);
    const port = await findFreePort("127.0.0.1");
    const url = `http://127.0.0.1:${port}/`;
    await this.dbtLab.terminal.serve(project.folder, profilesDir, buildDctCommand({ action: "serve", port }), url);
    await this.refresh();
    if (await waitForHttp(url, 90_000)) {
      await vscode.commands.executeCommand("simpleBrowser.show", url);
    } else {
      void vscode.window.showWarningMessage(`dct serve did not answer on ${url} yet: see its terminal.`);
    }
    await this.refresh();
  }

  /** A rendered HTML board carries scripts, so it opens in the system browser, never inside the Workbench webview. */
  private async openDctHtml(board: string): Promise<void> {
    if (!isBoardPath(board)) return;
    const project = await this.selectedDbtProject();
    if (!project) return;
    const uri = vscode.Uri.joinPath(project.folder, ...renderPath(board, "html").split("/"));
    if (!(await exists(uri))) {
      void vscode.window.showWarningMessage(`${renderPath(board, "html")} does not exist yet: render the board as HTML first.`);
      return;
    }
    await vscode.env.openExternal(uri);
  }

  /** Open a file of the selected dbt project (a model, or its compiled SQL under target/). */
  private async openDbtFile(relative: string): Promise<void> {
    const selected = this.context.workspaceState.get<string>(DBT_SELECTED_KEY);
    const projects = await findDbtProjects();
    const project = projects.find(item => item.path === selected) ?? projects[0];
    const folder = project ? projectFolder(project.path) : undefined;
    const parts = relative.replaceAll("\\", "/").split("/").filter(Boolean);
    if (!folder || !parts.length || parts.some(part => part === ".." || part.includes(":"))) return;
    const uri = vscode.Uri.joinPath(folder, ...parts);
    if (!(await exists(uri))) {
      void vscode.window.showWarningMessage(`${relative} does not exist (compiled files appear after dbt compiles the node).`);
      return;
    }
    await this.openBeside(uri);
  }

  // ---- Projects ----------------------------------------------------------------------------------------

  private async findProject(projectId: string): Promise<ProjectContent | undefined> {
    const project = (await loadProjectContents(this.context.extensionUri)).projects.find(p => p.id === projectId);
    if (!project) void vscode.window.showErrorMessage(`Project not found: ${projectId}`);
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
      void vscode.window.showWarningMessage("Open a workspace folder before preparing a project.");
      return;
    }
    const project = await this.findProject(projectId);
    if (!project) return;
    await this.runScaffolds(project, project.steps.flatMap(step => step.open.scaffold));
    void vscode.window.showInformationMessage(
      `Files for "${project.title}" are ready (projects/${project.id}/ and the lab samples). Existing files were kept.`
    );
    await this.refresh();
  }

  /** "Open in <lab>": create the step's files, open its file or exercise beside, and show its lab and tab. */
  private async openProjectStep(projectId: string, stepId: string): Promise<void> {
    const project = await this.findProject(projectId);
    const step = project?.steps.find(s => s.id === stepId);
    if (!project || !step) return;
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before opening a project step.");
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
    this.focus = { module: step.open.module, tab: step.open.tab, query, exerciseKey: step.open.exercise, seq: ++this.focusSeq };
    await this.refresh();
  }

  /** "Verify": the runtime checks the steps on the workspace; the result is kept in .datapass/progress.json. */
  private async verifyProjectSteps(projectId: string, stepIds: string[]): Promise<void> {
    if (this.runtimeManager.snapshot().status !== "running") {
      void vscode.window.showWarningMessage("Start the Datapass runtime to verify steps: it reads the catalog and the journal of what the labs ran.");
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
      if (progress.error) throw new Error(`${progress.error} Fix or delete the file, then verify again.`);
      const result = await this.runtimeManager.checkProject(projectId, known);
      await writeProgress(applyVerification(progress.document, project, result, new Date().toISOString()));
      this.projectsHost = {};
    } catch (error) {
      this.projectsHost = { error: `Verification failed: ${error instanceof Error ? error.message : String(error)}` };
    }
    await this.refresh();
  }

  /** The learner ticks a step by hand: kept as a declaration, never as a verification. */
  private async setProjectStepManual(projectId: string, stepId: string, checked: boolean): Promise<void> {
    if (!vscode.workspace.workspaceFolders?.length) {
      void vscode.window.showWarningMessage("Open a workspace folder to keep project progress.");
      return;
    }
    const project = await this.findProject(projectId);
    if (!project || !project.steps.some(step => step.id === stepId)) return;
    const progress = await readProgress();
    if (progress.error) {
      void vscode.window.showErrorMessage(`${progress.error} Fix or delete the file.`);
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
      {
        focus: this.focus,
        projects: this.projectsHost,
        dbtLab: {
          tools: this.dbtLab.tools.snapshot(),
          selected: this.context.workspaceState.get<string>(DBT_SELECTED_KEY),
          shellIntegration: this.dbtLab.terminal.hasShellIntegration,
          validations: this.dctValidations,
          serveUrl: this.dbtLab.terminal.serveUrl,
          missions: this.selectedModule === "dbt"
            ? { missions: await this.dbtLab.missions.list("dbt"), progress: (await this.dbtLab.missions.progress()).missions }
            : undefined
        },
        practiceSolutions: Object.fromEntries(this.revealedSolutions),
        queryHistory: this.selectedModule === "mosaic" ? this.queryHistory() : undefined,
        terminal: this.selectedModule === "terminal" ? await this.terminalState() : undefined,
        infra: this.selectedModule === "infra" ? await this.infraState() : undefined
      }
    );
    if (seq !== this.refreshSeq) return;
    await this.panel.webview.postMessage({ type: "state", state });
  }

  private async terminalState(): Promise<TerminalViewState> {
    const lab = this.dbtLab.terminalLab;
    const { shells, git } = await lab.detect();
    return {
      shells,
      shell: preferredShell(shells, lab.chosen),
      git,
      missions: { missions: await this.dbtLab.missions.list("terminal"), progress: (await this.dbtLab.missions.progress()).missions }
    };
  }

  private async infraState(): Promise<InfraViewState> {
    const missions = await this.dbtLab.missions.list("infra");
    const progress = (await this.dbtLab.missions.progress()).missions;
    const folders = missions.filter(mission => progress[mission.id]?.started).map(mission => missionFolder(mission.id));
    const lab = this.dbtLab.infraLab;
    const folder = lab.folder && folders.includes(lab.folder) ? lab.folder : folders[0];
    const view: InfraViewState = { folder, folders, missions: { missions, progress } };
    if (folder && this.runtimeManager.snapshot().status === "running") {
      try {
        view.world = await this.runtimeManager.infraState(folder) as InfraWorldView;
      } catch (error) {
        view.worldError = error instanceof Error ? error.message : String(error);
      }
    }
    return view;
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
    case "tsql":
    case "bigquery":
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

/** Poll a loopback URL until it answers (any HTTP status) or the time runs out. */
async function waitForHttp(url: string, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const answered = await new Promise<boolean>(resolve => {
      const request = http.get(url, response => {
        response.resume();
        resolve(true);
      });
      request.setTimeout(2000, () => request.destroy());
      request.on("error", () => resolve(false));
    });
    if (answered) return true;
    await new Promise(resolve => setTimeout(resolve, 700));
  }
  return false;
}
