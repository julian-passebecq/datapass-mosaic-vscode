import * as vscode from "vscode";
import { AIRFLOW_STARTER_FILE } from "../../airflowState";
import {
  collectDatabricksFiles,
  collectFactoryFiles,
  copyFactorySamples,
  databricksJobPath,
  factoryFileUri,
  factoryRoot,
  pipelineUri,
  readPoolScript
} from "../../factoryState";
import { JOB_NAME } from "../../platform/databricksRun";
import { FACTORY_FLAVORS, PIPELINE_NAME, pipelineRelativePath } from "../../platform/factoryRun";
import { SQLPOOL_FLAVORS, SQLPOOL_LIMITS, isValidScale } from "../../platform/sqlpoolRun";
import { safeRelativeParts } from "../../platform/workspacePaths";
import { createDefaultProjectManifest, readProjectManifest, writeProjectManifest } from "../../project/projectManifest";
import { retailDemoReadme, retailOrdersCsv, retailPythonStarter, retailSqlStarter } from "../../scaffold/retailDemo";
import type {
  DatabricksScenarioInput,
  FabricMessage,
  FactoryFlavor,
  FactoryScenarioInput,
  SqlPoolFlavor
} from "../../webview/contracts";
import { exists, writeIfMissing } from "../../workspaceFiles";
import { activeSavedDocument, atLine, saveDirtyUnder, type LabController, type MessageHandlers, type WorkbenchHost } from "../host";

/** The starters the retail demo opens in the other labs. */
export interface RetailDemoLabs {
  openPipelineSource(): Promise<void>;
  openAirflowSource(): Promise<void>;
  createDbtSample(): Promise<void>;
}

/** Cloud Lab (module id `fabric`): the retail demo, and the Pipelines, SQL pool and Databricks tabs over factory/. */
export class FabricController implements LabController<FabricMessage> {
  readonly refreshOnSave = "fabric" as const;
  /** The T-SQL script the SQL pool tab last ran, to reveal a statement's line in it. */
  private lastSqlPoolFile?: vscode.Uri;

  constructor(private readonly host: WorkbenchHost, private readonly labs: RetailDemoLabs) {}

  readonly handlers: MessageHandlers<FabricMessage> = {
    createRetailDemo: () => this.createRetailDemo(),
    runRetailDemo: () => this.runRetailDemo(),
    createFactoryLab: () => this.createFactoryLab(),
    refreshFactory: () => this.host.refresh(),
    openFactoryFile: message => this.openFactoryFile(message.path),
    revealFactoryActivity: message => this.revealFactoryActivity(message.path, message.activity),
    simulateFactory: message => this.simulateFactory(message.flavor, message.name, message.scenario),
    runSqlPool: message => this.runSqlPool(message.flavor, message.scale, message.source, message.path),
    revealSqlPoolLine: message => this.revealSqlPoolLine(message.line),
    simulateDatabricks: message => this.simulateDatabricks(message.name, message.scenario),
    refreshDatabricksState: () => this.refreshDatabricksState()
  };

  private async createRetailDemo(): Promise<void> {
    const root = await this.writeRetailDemoFiles();
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating the retail demo.");
      return;
    }

    await this.labs.openPipelineSource();
    await this.labs.openAirflowSource();
    await this.labs.createDbtSample();

    const readme = vscode.Uri.joinPath(root, "README_DATAPASS_RETAIL.md");
    await this.host.openBeside(readme);
    void vscode.window.showInformationMessage(
      "Datapass retail demo created: dataset, notebook starters, pipeline, Airflow DAG and dbt sample."
    );
    await this.host.refresh();
  }

  /** The retail demo's dataset, notebooks and README (missing files only). Returns the workspace root. */
  async writeRetailDemoFiles(): Promise<vscode.Uri | undefined> {
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
      await this.host.runtime.labs.fabric.runRetailDemo(datasetPath);
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Retail demo failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.host.refresh();
  }

  /** Copy the Cloud Lab sample files (Fabric, ADF, Synapse, notebooks, procedures) into factory/, keeping existing files. */
  private async createFactoryLab(): Promise<void> {
    const root = await copyFactorySamples(this.host.context.extensionUri);
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating the Cloud Lab files.");
      return;
    }
    const starter = pipelineUri("fabric", "pl_retail_daily");
    if (starter && (await exists(starter))) await this.host.openBeside(starter);
    void vscode.window.showInformationMessage(
      "Cloud Lab files are in factory/: the same daily load for Fabric, Azure Data Factory and Synapse, notebooks, a stored procedure, T-SQL scripts for the SQL pool tab (factory/sql/pool) and Databricks jobs (factory/databricks). Existing files were kept."
    );
    await this.host.refresh();
  }

  private async openFactoryFile(relative: string): Promise<void> {
    const uri = factoryFileUri(relative);
    if (!uri || !(await exists(uri))) {
      void vscode.window.showWarningMessage(`Cloud Lab file not found: ${relative}`);
      return;
    }
    await this.host.openBeside(uri);
  }

  /** Open a pipeline file on the activity's "name" entry. */
  private async revealFactoryActivity(relative: string, activity: string): Promise<void> {
    const uri = factoryFileUri(relative);
    if (!uri || !(await exists(uri))) return;
    await this.host.revealBeside(uri, document => {
      const offset = document.getText().search(new RegExp(`"name"\\s*:\\s*${escapeRegExp(JSON.stringify(activity))}`));
      return offset >= 0 ? document.positionAt(offset) : new vscode.Position(0, 0);
    });
  }

  /** Run a pipeline of the Cloud Lab: the runtime simulates it and runs supported activities on the local catalog. */
  private async simulateFactory(flavor: FactoryFlavor, name: string, scenario: FactoryScenarioInput): Promise<void> {
    if (!FACTORY_FLAVORS.includes(flavor) || !PIPELINE_NAME.test(name)) return;
    // A run uses the files as saved, like the other labs.
    await saveDirtyUnder(factoryRoot());
    const { files, warnings } = await collectFactoryFiles(flavor);
    const path = pipelineRelativePath(flavor, name);
    const document = files.pipelines[name];
    if (!document) {
      void vscode.window.showWarningMessage(`Pipeline ${name} is missing or is not valid JSON (${path}).`);
      return;
    }
    try {
      await this.host.runtime.labs.fabric.simulateFactory({ flavor, name, path, document, files, scenario, warnings });
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Pipeline run failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.host.refresh();
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
      const document = await activeSavedDocument(".sql", "SQL", this.host.lastDocument(".sql"));
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
      await this.host.runtime.labs.fabric.runSqlPool({ flavor, script, scale, source: label });
    } catch (error) {
      void vscode.window.showErrorMessage(
        `SQL pool run failed: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    await this.host.refresh();
  }

  private async revealSqlPoolLine(line: number): Promise<void> {
    if (!this.lastSqlPoolFile || !Number.isInteger(line) || line < 1) return;
    await this.host.revealBeside(this.lastSqlPoolFile, atLine(line));
  }

  /** Run a Databricks job of the Cloud Lab: the runtime simulates it; notebook and SQL tasks run on the catalog. */
  private async simulateDatabricks(name: string, scenario: DatabricksScenarioInput): Promise<void> {
    if (!JOB_NAME.test(name)) return;
    await saveDirtyUnder(factoryRoot());
    const { files, jobs, warnings } = await collectDatabricksFiles();
    const path = databricksJobPath(name);
    const document = jobs[name];
    if (!document) {
      void vscode.window.showWarningMessage(`Job ${name} is missing or is not valid JSON (${path}).`);
      return;
    }
    try {
      await this.host.runtime.labs.fabric.simulateDatabricks({ name, path, document, files, scenario, warnings });
    } catch (error) {
      void vscode.window.showErrorMessage(`Databricks job run failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.host.refresh();
  }

  private async refreshDatabricksState(): Promise<void> {
    try {
      await this.host.runtime.labs.fabric.exploreDatabricks((await collectDatabricksFiles()).files);
    } catch (error) {
      void vscode.window.showErrorMessage(`Databricks state refresh failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.host.refresh();
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
