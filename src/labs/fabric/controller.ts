import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
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
import { contentHash, parsePipeline } from "../../platform/factoryDocument";
import {
  FACTORY_FLAVORS,
  FACTORY_FOLDER,
  PIPELINE_NAME,
  classifyFactoryPath,
  designView,
  pipelineRelativePath,
  requestFactoryReload
} from "../../platform/factoryRun";
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
    saveFactoryPipeline: message => this.host.guarded("Saving the pipeline", () => this.saveFactoryPipeline(message.path, message.text, message.baseHash)),
    createFactoryPipeline: message => this.host.guarded("Creating the pipeline", () => this.createFactoryPipeline(message.flavor)),
    importFactoryPipeline: message => this.host.guarded("Importing the pipeline", () => this.importFactoryPipeline(message.flavor)),
    exportFactoryPipeline: message => this.host.guarded("Exporting the pipeline", () => this.exportFactoryPipeline(message.path, message.text)),
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
    if (!(await saveDirtyUnder(factoryRoot()))) return;
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
   * Save the pipeline editor's text. The editor sends the hash of the file it started from; when the file changed
   * since (another editor, git, a restore), nothing is written until the learner chooses Reload or Overwrite.
   */
  private async saveFactoryPipeline(path: string, text: string, baseHash: string): Promise<void> {
    const target = this.pipelineTarget(path);
    if (!target) return;
    if (typeof text !== "string" || text.length > MAX_PIPELINE_CHARS) {
      void vscode.window.showWarningMessage(`The pipeline is longer than ${MAX_PIPELINE_CHARS} characters; it was not saved.`);
      return;
    }
    const parsed = parsePipeline(text);
    if (parsed.error) {
      void vscode.window.showWarningMessage(`The pipeline was not saved: ${parsed.error}`);
      return;
    }
    const open = vscode.workspace.textDocuments.find(document => document.uri.toString() === target.uri.toString());
    const current = open ? open.getText() : (await exists(target.uri)) ? await readUtf8(target.uri) : undefined;
    if (current === undefined || contentHash(current) !== baseHash) {
      const choice = await vscode.window.showWarningMessage(
        current === undefined
          ? `${path} no longer exists on disk.`
          : `${path} changed since the pipeline editor loaded it${open?.isDirty ? " (it has unsaved changes in a text editor)" : ""}.`,
        {
          modal: true,
          detail: "Reload from disk drops the edits made in the pipeline editor and shows the file as it is now. Overwrite replaces the file with the pipeline editor's version."
        },
        "Reload from disk",
        "Overwrite"
      );
      if (choice === "Reload from disk") {
        requestFactoryReload(path);
        await this.host.refresh();
        return;
      }
      if (choice !== "Overwrite") return;
    }
    if (open && !open.isClosed) {
      const edit = new vscode.WorkspaceEdit();
      edit.replace(open.uri, new vscode.Range(open.positionAt(0), open.positionAt(open.getText().length)), text);
      if (!(await vscode.workspace.applyEdit(edit)) || !(await open.save())) {
        throw new Error(`could not write ${path}`);
      }
    } else {
      await vscode.workspace.fs.writeFile(target.uri, new TextEncoder().encode(text));
    }
    await this.host.refresh();
  }

  /** A factory pipeline path from the webview, or undefined (with a warning) when it is anything else. */
  private pipelineTarget(path: string): { uri: vscode.Uri; flavor: FactoryFlavor; name: string } | undefined {
    const uri = typeof path === "string" ? factoryFileUri(path) : undefined;
    const role = uri ? classifyFactoryPath(path.replaceAll("\\", "/").slice(FACTORY_FOLDER.length + 1)) : undefined;
    if (!uri || role?.role !== "pipeline" || !PIPELINE_NAME.test(role.name)) {
      void vscode.window.showWarningMessage(`Not a Cloud Lab pipeline file: ${String(path)}`);
      return undefined;
    }
    return { uri, flavor: role.flavor, name: role.name };
  }

  /** An empty pipeline of the product, in its git layout; an existing file is never replaced. */
  private async createFactoryPipeline(flavor: FactoryFlavor): Promise<void> {
    if (!FACTORY_FLAVORS.includes(flavor) || !vscode.workspace.workspaceFolders?.length) return;
    const name = await askPipelineName("New pipeline name", "pl_new");
    if (!name) return;
    const properties = { description: "", activities: [], parameters: {}, variables: {}, annotations: [] };
    const document = flavor === "fabric" ? { properties } : { name, properties };
    const relative = pipelineRelativePath(flavor, name);
    if (!(await createExclusive(relative, `${JSON.stringify(document, null, 2)}\n`))) {
      void vscode.window.showWarningMessage(`${relative} already exists: choose another name.`);
      return;
    }
    await this.host.refresh();
  }

  /**
   * Copy a pipeline JSON file into factory/<flavor>/ as written (Data Factory / Synapse pipeline/*.json, or a Fabric
   * pipeline-content.json). The file is checked to be a pipeline; its activities are checked by the editor and the
   * run, like any other pipeline. An existing pipeline is never replaced.
   */
  private async importFactoryPipeline(flavor: FactoryFlavor): Promise<void> {
    if (!FACTORY_FLAVORS.includes(flavor) || !vscode.workspace.workspaceFolders?.length) return;
    const picked = await vscode.window.showOpenDialog({
      canSelectMany: false,
      canSelectFiles: true,
      openLabel: "Import pipeline",
      title: "Import a pipeline JSON file into the Cloud Lab",
      filters: { "Pipeline JSON": ["json"] }
    });
    const source = picked?.[0];
    if (!source) return;
    const bytes = await vscode.workspace.fs.readFile(source);
    if (bytes.byteLength > MAX_PIPELINE_CHARS) {
      void vscode.window.showWarningMessage(`The file is larger than ${MAX_PIPELINE_CHARS} bytes.`);
      return;
    }
    const text = new TextDecoder().decode(bytes);
    const check = designView(flavor, "import", "import.json", text);
    if (check.error) {
      void vscode.window.showWarningMessage(`Not imported: ${check.error}`);
      return;
    }
    const parsed = parsePipeline(text).value ?? {};
    const parts = source.path.split("/");
    const file = parts[parts.length - 1];
    const folder = parts[parts.length - 2] ?? "";
    const suggested = typeof parsed.name === "string" && PIPELINE_NAME.test(parsed.name)
      ? parsed.name
      : file === "pipeline-content.json" && folder.endsWith(".DataPipeline")
        ? folder.slice(0, -".DataPipeline".length)
        : file.replace(/\.json$/i, "");
    const name = await askPipelineName("Pipeline name in the Cloud Lab", suggested);
    if (!name) return;
    const relative = pipelineRelativePath(flavor, name);
    if (!(await createExclusive(relative, text))) {
      void vscode.window.showWarningMessage(`${relative} already exists: the import never replaces a pipeline. Choose another name.`);
      return;
    }
    void vscode.window.showInformationMessage(`Imported as ${relative}. Its activities are checked against what the simulator supports.`);
    await this.host.refresh();
  }

  /** Save the editor's version of a pipeline to a file the learner chooses (the save dialog asks before replacing). */
  private async exportFactoryPipeline(path: string, text: string): Promise<void> {
    const target = this.pipelineTarget(path);
    if (!target || typeof text !== "string" || parsePipeline(text).error) return;
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri;
    const chosen = await vscode.window.showSaveDialog({
      defaultUri: folder ? vscode.Uri.joinPath(folder, `${target.name}.json`) : undefined,
      filters: { "Pipeline JSON": ["json"] },
      saveLabel: "Export pipeline",
      title: `Export ${target.name}`
    });
    if (!chosen) return;
    await vscode.workspace.fs.writeFile(chosen, new TextEncoder().encode(text));
    void vscode.window.showInformationMessage(`Exported ${target.name} to ${vscode.workspace.asRelativePath(chosen)}.`);
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
      let read = path ? await readPoolScript(path) : { error: "No script selected." };
      if (read.error || read.text === undefined) {
        void vscode.window.showWarningMessage(read.error ?? "No script selected.");
        return;
      }
      const uri = factoryFileUri(path!)!;
      const open = vscode.workspace.textDocuments.find(document => document.uri.toString() === uri.toString());
      if (open?.isDirty) {
        if (!(await open.save())) {
          void vscode.window.showWarningMessage(`Save ${path} before running it. Nothing was run.`);
          return;
        }
        // Saving can change the text (formatters and save participants). Run the saved version.
        read = await readPoolScript(path!);
        if (read.error || read.text === undefined) {
          void vscode.window.showWarningMessage(read.error ?? "No script selected.");
          return;
        }
      }
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
    if (!(await saveDirtyUnder(factoryRoot()))) return;
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

/** Pipeline files the editor writes or imports stay well under what the runtime reads. */
const MAX_PIPELINE_CHARS = 1_000_000;

async function readUtf8(uri: vscode.Uri): Promise<string> {
  return new TextDecoder().decode(await vscode.workspace.fs.readFile(uri));
}

async function askPipelineName(title: string, value: string): Promise<string | undefined> {
  const name = await vscode.window.showInputBox({
    title,
    value,
    prompt: "Letters, digits, spaces, _ and - (at most 140 characters)",
    validateInput: input => PIPELINE_NAME.test(input) ? undefined : "Use letters, digits, spaces, _ and - (at most 140), starting with a letter or digit."
  });
  return name && PIPELINE_NAME.test(name) ? name : undefined;
}

/** Write a new workspace file, failing (false) when it already exists: the check and the write are one operation. */
async function createExclusive(relative: string, text: string): Promise<boolean> {
  const uri = factoryFileUri(relative);
  if (!uri) return false;
  if (uri.scheme === "file") {
    await mkdir(dirname(uri.fsPath), { recursive: true });
    try {
      await writeFile(uri.fsPath, text, { encoding: "utf8", flag: "wx" });
      return true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "EEXIST") return false;
      throw error;
    }
  }
  if (await exists(uri)) return false;
  await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(text));
  return true;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
