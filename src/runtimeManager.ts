import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import type {
  AirflowScenarioInput,
  BiDbtCommand,
  BiRunMode,
  CsvImportView,
  FactoryFlavor,
  FactoryScenarioInput,
  LocalCellRunView,
  QueryPlanView,
  RuntimeEnvironmentView,
  DatabricksScenarioInput,
  RuntimeViewState,
  SqlPoolFlavor,
  TableProfileView
} from "./webview/contracts";
import { findFreePort, waitForDatapassHealth } from "./platform/runtimeEndpoint";
import {
  describeSetupOutputLine,
  managedVenvPython,
  runtimeInstallArgs,
  runtimeVerifyArgs,
  pythonExecutableArgs,
  uvCandidates,
  uvInstallArgs,
  uvVenvArgs
} from "./platform/runtimeEnvironment";
import { runtimeProcessEnv } from "./platform/pythonTrust";
import { newRuntimeToken, requestGetJson, requestJson } from "./platform/runtimeClient";
import { toSparkLabRunView } from "./platform/sparkLabRun";
import { toAirflowLabView, toRuntimeScenario } from "./platform/airflowRun";
import { toFactoryLabView, toRuntimeScenario as toFactoryScenario } from "./platform/factoryRun";
import type { FactoryFilesPayload } from "./factoryState";
import { toSqlPoolView } from "./platform/sqlpoolRun";
import { toDatabricksLabView, toDatabricksScenario, toDatabricksStateView } from "./platform/databricksRun";
import type { DatabricksFilesPayload } from "./factoryState";
import { toBiDbtView, toBiLabView } from "./platform/biRun";

const HOST = "127.0.0.1";
/** Catalog listing, including the first one that creates the workspace catalog. */
const CATALOG_TIMEOUT_MS = 30_000;
// A cold start in a fresh managed venv (FastAPI, DuckDB, Polars, pandas; first
// bytecode compilation; antivirus scanning on Windows) can exceed ten seconds.
const STARTUP_TIMEOUT_MS = 90_000;

export interface PipelineCompileResponse {
  valid: boolean;
  source_hash: string;
  truth: string;
  diagnostics: Array<{ line: number; column: number; message: string }>;
  ir: null | {
    id: string;
    schedule: string | null;
    tasks: Array<{
      id: string;
      kind: string;
      retries: number;
      retry_delay: number;
    }>;
    edges: Array<{ source: string; target: string }>;
  };
}

export class RuntimeManager implements vscode.Disposable {
  private child?: ChildProcess;
  /** This launch's runtime token: in memory only, never persisted or logged. */
  private token?: string;
  private state: RuntimeViewState = { status: "stopped" };
  private readonly output = vscode.window.createOutputChannel("Datapass Runtime");
  private readonly changed = new vscode.EventEmitter<RuntimeViewState>();
  private environment: RuntimeEnvironmentView;

  readonly onDidChange = this.changed.event;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly storageUri: vscode.Uri
  ) {
    const python = this.managedPythonPath();
    this.environment = existsSync(python)
      ? { status: "ready", python, detail: "Managed Datapass runtime is installed." }
      : { status: "missing", detail: "Managed Datapass runtime is not installed yet." };
  }

  snapshot(): RuntimeViewState {
    return { ...this.state, environment: { ...this.environment } };
  }

  showLog(): void {
    this.output.show(true);
  }

  async setup(pythonCommand = "python"): Promise<string> {
    if (this.state.status === "running" || this.state.status === "starting") {
      throw new Error("Stop the Datapass runtime before updating its environment.");
    }

    const runtimeRoot = path.join(this.extensionUri.fsPath, "runtime");
    const venvRoot = path.join(this.storageUri.fsPath, "runtime-venv");
    const managedPython = managedVenvPython(venvRoot);

    const startedAt = Date.now();
    const totalSteps = 3;
    let reportNotification: (message: string) => void = () => undefined;
    let lastActivityFire = 0;
    const setProgress = (step: number, label: string, activity?: string): void => {
      this.environment = {
        status: "setting-up",
        python: managedPython,
        detail: "Creating and installing the isolated Datapass runtime…",
        progress: { step, totalSteps, label, activity, startedAt }
      };
      this.changed.fire(this.snapshot());
      reportNotification(`Step ${step}/${totalSteps}: ${label}${activity ? ` · ${activity}` : ""}`);
    };
    // pip can print hundreds of lines per second; keep webview updates cheap.
    const onActivity = (step: number, label: string) => (activity: string): void => {
      const now = Date.now();
      if (now - lastActivityFire < 400) return;
      lastActivityFire = now;
      setProgress(step, label, activity);
    };

    setProgress(1, "Creating Python environment");

    try {
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Datapass runtime setup" },
        async progress => {
          reportNotification = message => progress.report({ message });
          await vscode.workspace.fs.createDirectory(this.storageUri);
          // uv creates the venv and installs the same packages much faster; pip stays the fallback when uv is
          // absent or fails. Measured on Windows: about 14 s instead of 146 s for a first setup.
          const uv = await this.findUv();
          if (!existsSync(managedPython)) {
            this.output.appendLine("Creating isolated Datapass Python environment.");
            setProgress(1, "Creating Python environment");
            let created = false;
            if (uv) {
              try {
                const basePython = await this.pythonExecutable(pythonCommand);
                await this.runSetupCommand(uv, uvVenvArgs(basePython, venvRoot), this.storageUri.fsPath);
                created = existsSync(managedPython);
              } catch (error) {
                this.output.appendLine(`uv could not create the environment (${error instanceof Error ? error.message : String(error)}). Using python -m venv.`);
              }
            }
            if (!created) {
              await this.runSetupCommand(
                pythonCommand,
                ["-m", "venv", venvRoot],
                this.storageUri.fsPath
              );
            }
          }

          let installed = false;
          if (uv) {
            const uvLabel = "Installing runtime dependencies with uv";
            this.output.appendLine(`Installing Datapass runtime and local engine dependencies with uv (${uv}).`);
            setProgress(2, uvLabel);
            try {
              await this.runSetupCommand(uv, uvInstallArgs(managedPython, runtimeRoot), runtimeRoot, onActivity(2, uvLabel));
              installed = true;
            } catch (error) {
              this.output.appendLine(`uv could not install the runtime (${error instanceof Error ? error.message : String(error)}). Falling back to pip.`);
            }
          }
          if (!installed) {
            const installLabel = "Installing runtime dependencies with pip";
            this.output.appendLine(uv
              ? "Installing Datapass runtime and local engine dependencies with pip."
              : "Installing Datapass runtime and local engine dependencies with pip (uv not found; installing uv makes this step much faster).");
            setProgress(2, installLabel);
            await this.runSetupCommand(
              managedPython,
              runtimeInstallArgs(runtimeRoot),
              runtimeRoot,
              onActivity(2, installLabel)
            );
          }

          setProgress(3, "Verifying engines (DuckDB, Polars, pandas)");
          await this.runSetupCommand(
            managedPython,
            runtimeVerifyArgs(),
            runtimeRoot
          );
        }
      );

      this.environment = {
        status: "ready",
        python: managedPython,
        detail: "Managed Datapass runtime is ready."
      };
      this.state = {
        ...this.state,
        status: "stopped",
        detail: "Runtime environment ready. Start the local runtime when needed."
      };
      this.changed.fire(this.snapshot());
      return managedPython;
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      this.environment = {
        status: "error",
        python: managedPython,
        detail
      };
      this.state = { ...this.state, status: "error", detail };
      this.changed.fire(this.snapshot());
      throw error;
    }
  }

  /**
   * Start the loopback runtime. `trustedPython` must come from the explicit
   * workspace opt-in (see platform/pythonTrust); it is never inherited.
   */
  async start(
    pythonCommand = "python",
    storage: "duckdb" | "ducklake" = "duckdb",
    trustedPython = false
  ): Promise<void> {
    if (this.state.status === "running" || this.state.status === "starting") return;

    const runtimeRoot = path.join(this.extensionUri.fsPath, "runtime");
    const managedPython = this.managedPythonPath();
    const resolvedPython = existsSync(managedPython) ? managedPython : pythonCommand;
    const port = await findFreePort(HOST);
    const url = `http://${HOST}:${port}`;
    const token = newRuntimeToken();
    this.token = token;
    this.setState({ status: "starting", url, detail: "Starting local FastAPI runtime… The first start can take up to a minute." });
    this.output.appendLine(`Starting Datapass runtime with ${resolvedPython}`);
    this.output.appendLine(trustedPython
      ? "Trusted local Python: ENABLED by explicit workspace opt-in. Python/Polars run as real local code; the worker is not a sandbox."
      : "Trusted local Python: disabled. SQL and bounded SparkLab only.");

    const child = spawn(
      resolvedPython,
      [
        "-m",
        "uvicorn",
        "datapass_runtime.main:app",
        "--app-dir",
        runtimeRoot,
        "--host",
        HOST,
        "--port",
        String(port)
      ],
      {
        cwd: runtimeRoot,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        env: runtimeProcessEnv(process.env, {
          contentRoot: path.join(this.extensionUri.fsPath, "content"),
          storage,
          trustedPython,
          workspaceRoot: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
          runtimeToken: token,
          runtimePort: port
        })
      }
    );

    this.child = child;
    let exitReason: string | undefined;
    child.once("exit", (code, signal) => {
      exitReason = `Runtime process exited during startup${code !== null ? ` with code ${code}` : ""}${signal ? ` (${signal})` : ""}. See the Datapass Runtime output.`;
    });
    child.stdout?.on("data", chunk => this.output.append(String(chunk)));
    child.stderr?.on("data", chunk => this.output.append(String(chunk)));

    child.once("error", error => {
      if (this.child !== child) return;
      this.child = undefined;
      this.setState({ status: "error", url, detail: error.message });
    });

    child.once("exit", (code, signal) => {
      if (this.child !== child) return;
      this.child = undefined;
      if (this.state.status !== "error") {
        this.setState({
          status: "stopped",
          detail: `Runtime exited${code !== null ? ` with code ${code}` : ""}${signal ? ` (${signal})` : ""}.`
        });
      }
    });

    try {
      await waitForDatapassHealth(`${url}/api/health`, STARTUP_TIMEOUT_MS, () => exitReason, token);
      if (this.child === child) {
        const capabilities = await this.getJson<{ runtime?: { trusted_local_python?: unknown } }>(
          `${url}/api/capabilities`
        );
        const reported = capabilities.runtime?.trusted_local_python === true;
        if (reported !== trustedPython) {
          throw new Error(
            `Runtime reported trusted Python ${reported ? "enabled" : "disabled"}, but ${trustedPython ? "enabled" : "disabled"} was requested. The runtime was stopped.`
          );
        }
        this.setState({ status: "running", url, detail: "Local runtime healthy.", trustedPython: reported });
        await this.refreshCatalog();
      }
    } catch (error) {
      child.kill();
      this.child = undefined;
      this.output.show(true);
      this.setState({
        status: "error",
        url,
        detail: error instanceof Error ? error.message : String(error)
      });
    }
  }

  async gradeExercise(
    exerciseKey: string,
    request: {
      exercise_id: string;
      exercise_version: string;
      language: string;
      code: string;
      mode: "run" | "submit";
      notebook_id: string;
      cell_id: string;
      source_revision: number;
    }
  ): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before grading an exercise.");
    const result = await this.postJson<Omit<NonNullable<RuntimeViewState["practiceResult"]>, "exerciseKey" | "mode">>(
      `${url}/api/local/exercise`,
      "POST",
      request,
      30000
    );
    this.setState({
      ...this.state,
      detail: request.mode === "submit"
        ? `Exercise submission: ${result.status}.`
        : `Visible exercise checks: ${result.status}.`,
      practiceResult: {
        ...result,
        exerciseKey,
        mode: request.mode
      }
    });
  }

  async runRetailDemo(datasetPath: string): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running the retail demo.");
    this.setState({ ...this.state, detail: "Running retail medallion demo…" });
    try {
      const retailDemo = await this.postJson<NonNullable<RuntimeViewState["retailDemo"]>>(
        `${url}/api/demo/retail/run`,
        "POST",
        { dataset_path: datasetPath },
        10000
      );
      this.setState({
        ...this.state,
        detail: "Retail demo completed with real local Polars + DuckDB execution.",
        retailDemo
      });
      await this.refreshCatalog();
    } catch (error) {
      this.setState({
        ...this.state,
        detail: error instanceof Error ? error.message : String(error)
      });
      throw error;
    }
  }

  /** Send CSV TEXT (never a path) to create a new bronze table; the runtime refuses overwrites. */
  async importCsv(asset: string, text: string, fileName: string): Promise<CsvImportView> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before importing a CSV.");
    let response: Omit<CsvImportView, "fileName">;
    try {
      response = await this.postJson<Omit<CsvImportView, "fileName">>(
        `${url}/api/local/import-csv`,
        "POST",
        { asset, text },
        30000
      );
    } catch (error) {
      throw new Error(`CSV import refused: ${runtimeErrorDetail(error)}`);
    }
    const csvImport: CsvImportView = {
      asset: response.asset,
      fileName,
      rows_imported: response.rows_imported,
      sha256: response.sha256,
      schema: response.schema,
      truth: response.truth,
      result: response.result
    };
    this.setState({
      ...this.state,
      detail: `Imported ${csvImport.rows_imported} rows from ${fileName} into ${csvImport.asset} (all columns are text).`,
      lastRun: undefined,
      csvImport
    });
    await this.refreshCatalog();
    return csvImport;
  }

  async runSql(code: string): Promise<LocalCellRunView> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running SQL.");
    const lastRun = await this.postJson<NonNullable<RuntimeViewState["lastRun"]>>(
      `${url}/api/local/execute`,
      "POST",
      {
        language: "sql",
        code,
        notebook_id: "vscode-sql",
        cell_id: "active-sql"
      },
      10000
    );
    this.setState({
      ...this.state,
      detail: lastRun.status === "success"
        ? `SQL completed in ${lastRun.elapsed_ms.toFixed(1)} ms.`
        : `SQL failed: ${lastRun.error?.message ?? "Unknown error"}`,
      lastRun,
      csvImport: undefined
    });
    await this.refreshCatalog();
    return lastRun;
  }

  /** Parquet or JSON CONTENT (base64) into a new bronze table; the runtime keeps the file's types. */
  async importFile(asset: string, format: "parquet" | "json", data: string, fileName: string): Promise<CsvImportView> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before importing a file.");
    let response: Omit<CsvImportView, "fileName">;
    try {
      response = await this.postJson<Omit<CsvImportView, "fileName">>(
        `${url}/api/local/import-file`, "POST", { asset, format, data }, 120000);
    } catch (error) {
      throw new Error(`${format === "parquet" ? "Parquet" : "JSON"} import refused: ${runtimeErrorDetail(error)}`);
    }
    const fileImport: CsvImportView = { ...response, fileName, format };
    this.setState({
      ...this.state,
      detail: `Imported ${fileImport.rows_imported} rows from ${fileName} into ${fileImport.asset} (typed columns).`,
      lastRun: undefined,
      csvImport: fileImport
    });
    await this.refreshCatalog();
    return fileImport;
  }

  /** DuckDB SUMMARIZE of a catalog table. */
  async profileTable(asset: string): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before profiling a table.");
    let tableProfile: TableProfileView;
    try {
      tableProfile = await this.postJson<TableProfileView>(`${url}/api/local/profile`, "POST", { asset }, 60000);
    } catch (error) {
      throw new Error(`Profile refused: ${runtimeErrorDetail(error)}`);
    }
    this.setState({ ...this.state, detail: `Profiled ${asset} in ${tableProfile.elapsed_ms.toFixed(1)} ms.`, tableProfile });
  }

  /** DuckDB EXPLAIN ANALYZE of one read-only query: it runs once to time each operator. */
  async explainQuery(query: string, source?: string): Promise<QueryPlanView> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before explaining a query.");
    let plan: QueryPlanView;
    try {
      plan = { ...await this.postJson<QueryPlanView>(`${url}/api/local/explain`, "POST", { query }, 60000), source };
    } catch (error) {
      throw new Error(`EXPLAIN ANALYZE refused: ${runtimeErrorDetail(error)}`);
    }
    this.setState({ ...this.state, detail: `Query plan measured in ${plan.elapsed_ms.toFixed(1)} ms.`, queryPlan: plan });
    return plan;
  }

  async runPython(code: string): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running Python.");
    if (!this.state.trustedPython) {
      throw new Error("Trusted local Python is disabled for this runtime. Enable it for the workspace, then restart the runtime.");
    }
    const lastRun = await this.postJson<NonNullable<RuntimeViewState["lastRun"]>>(
      `${url}/api/local/execute`,
      "POST",
      {
        language: "python",
        code,
        notebook_id: "vscode-python",
        cell_id: "active-python"
      },
      25000
    );
    this.setState({
      ...this.state,
      detail: lastRun.status === "success"
        ? `Python completed in ${lastRun.elapsed_ms.toFixed(1)} ms (trusted local execution).`
        : `Python failed: ${lastRun.error?.message ?? "Unknown error"}`,
      lastRun,
      csvImport: undefined
    });
    await this.refreshCatalog();
  }

  /** Bounded SparkLab: whitelisted AST to local SQL. Never executed as Python. */
  async runSparkLab(code: string, fileName: string, profileId: string, aqe: boolean): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running SparkLab.");
    const raw = await this.postJson<unknown>(
      `${url}/api/local/execute`,
      "POST",
      {
        language: "sparklab",
        code,
        notebook_id: "vscode-sparklab",
        cell_id: "active-sparklab",
        profile: profileId,
        aqe
      },
      25000
    );
    const sparkRun = toSparkLabRunView(raw, { fileName, profileId, aqe });
    this.setState({
      ...this.state,
      detail: sparkRun.status === "success"
        ? `SparkLab result computed locally in ${sparkRun.elapsed_ms.toFixed(1)} ms; distributed metrics are simulated.`
        : `SparkLab rejected or failed: ${sparkRun.error?.message ?? "Unknown error"}`,
      sparkRun
    });
    await this.refreshCatalog();
  }

  async refreshCatalog(): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url || this.state.catalogLease) return;
    try {
      // The first call after a start spawns the kernel and creates and seeds the DuckDB catalog: about 4 s on a
      // Windows machine with antivirus, more than requestGetJson's 3 s default.
      const catalog = await this.getJson<NonNullable<RuntimeViewState["catalog"]>>(
        `${url}/api/local/catalog`,
        CATALOG_TIMEOUT_MS
      );
      this.setState({ ...this.state, catalog });
    } catch (error) {
      this.setState({
        ...this.state,
        detail: `Catalog refresh failed: ${error instanceof Error ? error.message : String(error)}`
      });
    }
  }

  /**
   * dbt Lab handoff: the runtime closes the workspace catalog so a real dbt Core or dct command can open the DuckDB
   * file (one writer per file). Every catalog request is refused until {@link reattachCatalog}. Without a running
   * runtime there is nothing to release.
   */
  async releaseCatalog(holder: string): Promise<boolean> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) return false;
    if (this.state.catalogLease) return true;
    const lease = await this.postJson<{ holder?: string; since?: string }>(
      `${url}/api/local/catalog/release`, "POST", { holder: holder.slice(0, 200) }, 30000
    );
    this.output.appendLine(`Catalog lent to: ${holder}`);
    this.setState({
      ...this.state,
      detail: `Catalog lent to ${holder}. It is reattached when the command ends.`,
      catalogLease: { holder: lease.holder ?? holder, since: lease.since ?? new Date().toISOString() }
    });
    return true;
  }

  /** Take the catalog back after a dbt Core or dct command. Returns false (and says why) if the file is still held. */
  async reattachCatalog(): Promise<boolean> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url || !this.state.catalogLease) return true;
    try {
      await this.postJson<unknown>(`${url}/api/local/catalog/reattach`, "POST", {}, 30000);
    } catch (error) {
      const reason = runtimeErrorDetail(error);
      this.setState({ ...this.state, detail: reason, catalogLease: { ...this.state.catalogLease, reattachError: reason } });
      return false;
    }
    this.output.appendLine("Catalog reattached.");
    this.setState({ ...this.state, detail: "Catalog reattached: the runtime sees what dbt built.", catalogLease: undefined });
    await this.refreshCatalog();
    return true;
  }

  /** Missions: load one fixture batch of a shipped mission (the first one starts the mission over). */
  async missionSetup(missionId: string, batchId: string): Promise<void> {
    const url = this.requireAttached("load a mission's data");
    try {
      await this.postJson<unknown>(`${url}/api/local/missions/setup`, "POST", { mission_id: missionId, batch_id: batchId }, 60000);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
    await this.refreshCatalog();
  }

  /**
   * Terminal Lab missions: the runtime (re)builds `missions/<id>/` from the shipped pack (files and Git history). The
   * catalog is not involved, so a lent catalog does not block it.
   */
  async terminalMissionSetup(missionId: string): Promise<{ folder: string; previous?: string | null }> {
    const url = this.requireRunning("start a mission");
    try {
      return await this.postJson<{ folder: string; previous?: string | null }>(`${url}/api/local/missions/setup`, "POST", { mission_id: missionId }, 60000);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
  }

  /**
   * Missions: the hidden checker. `dct` carries the real `dct validate --json` results for the mission's boards. A
   * Terminal Lab mission reads files and Git only (`catalog: false`), so a lent catalog does not block it.
   */
  async missionCheck(missionId: string, dct: Record<string, unknown>, catalog = true): Promise<unknown> {
    const url = catalog ? this.requireAttached("check a mission") : this.requireRunning("check a mission");
    try {
      return await this.postJson<unknown>(`${url}/api/local/missions/check`, "POST", { mission_id: missionId, dct }, 60000);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
  }

  private requireRunning(action: string): string {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error(`Start the Datapass runtime to ${action}.`);
    return url;
  }

  private requireAttached(action: string): string {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error(`Start the Datapass runtime to ${action}.`);
    if (this.state.catalogLease) {
      throw new Error(`The catalog is lent to ${this.state.catalogLease.holder}: wait for it to end (or Reattach catalog), then retry.`);
    }
    return url;
  }

  /** Catalog tree view: every schema's tables and views with columns, types and row counts. */
  async fetchCatalogSchema(): Promise<unknown> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime to browse the catalog.");
    if (this.state.catalogLease) throw new Error(`The catalog is lent to ${this.state.catalogLease.holder}.`);
    return this.getJson<unknown>(`${url}/api/local/catalog/schema`, 20000);
  }

  /** Airflow Lab: the DAG file's TEXT is parsed and simulated by the runtime, never executed. */
  async simulateAirflow(source: string, fileName: string, scenario: AirflowScenarioInput): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before simulating an Airflow DAG.");
    const raw = await this.postJson<unknown>(
      `${url}/api/local/airflow/simulate`,
      "POST",
      { source, scenario: toRuntimeScenario(scenario) },
      20000
    );
    const airflowRun = toAirflowLabView(raw, fileName, scenario);
    this.setState({
      ...this.state,
      detail: airflowRun.status === "simulated"
        ? `Airflow DAG ${airflowRun.dag?.dagId ?? ""} simulated: ${airflowRun.totalRuns} run(s); nothing was executed.`
        : `Airflow DAG not simulated: ${airflowRun.error?.message ?? "unknown error"}`,
      airflowRun
    });
  }

  /**
   * Factory Lab: the runtime validates and simulates the pipeline JSON. With the local data plane,
   * Copy, Lookup, Script, stored procedures and SparkLab notebooks act on the local catalog.
   */
  async simulateFactory(request: {
    flavor: FactoryFlavor;
    name: string;
    path: string;
    document: unknown;
    files: FactoryFilesPayload;
    scenario: FactoryScenarioInput;
    warnings: string[];
  }): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running a pipeline.");
    const context = { flavor: request.flavor, pipelineName: request.name, path: request.path, scenario: request.scenario };
    const { scenario, errors } = toFactoryScenario(request.scenario);
    if (errors.length) {
      const factoryRun = toFactoryLabView(
        { status: "error", issues: errors.map(message => ({ path: "scenario", message, severity: "error" })) },
        { ...context, warnings: request.warnings }
      );
      this.setState({ ...this.state, detail: `Pipeline ${request.name} not run: fix the scenario.`, factoryRun });
      return;
    }
    const raw = await this.postJson<unknown>(
      `${url}/api/local/factory/simulate`,
      "POST",
      {
        flavor: request.flavor,
        name: request.name,
        document: request.document,
        files: request.files,
        scenario,
        data_plane: request.scenario.dataPlane
      },
      60000
    );
    const factoryRun = toFactoryLabView(raw, { ...context, warnings: request.warnings });
    this.setState({
      ...this.state,
      detail: factoryRun.run
        ? `Pipeline ${request.name} ${factoryRun.run.status.toLowerCase()} (${factoryRun.flavorLabel}, ${factoryRun.dataPlane === "local" ? "local activities ran on the catalog" : "dry run"}).`
        : `Pipeline ${request.name} not run: ${factoryRun.issues[0]?.message ?? factoryRun.status}`,
      factoryRun
    });
    if (factoryRun.tablesChanged.length) await this.refreshCatalog();
  }

  /**
   * SQL pool Lab: the runtime translates the T-SQL script for a documented subset and runs the data
   * statements on the local catalog; distributions, partitions and plans are modelled. An empty
   * script only describes the pool's tables.
   */
  async runSqlPool(request: { flavor: SqlPoolFlavor; script: string; scale: number; source: string; warnings?: string[] }): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running a SQL pool script.");
    const raw = await this.postJson<unknown>(
      `${url}/api/local/sqlpool/run`,
      "POST",
      { flavor: request.flavor, script: request.script, scale: request.scale, source: sqlPoolSourceLabel(request.source) },
      60000
    );
    const sqlpoolRun = toSqlPoolView(raw, request);
    const failed = sqlpoolRun.statements.find(statement => statement.status === "error");
    this.setState({
      ...this.state,
      detail: !request.script.trim()
        ? `SQL pool tables described (${sqlpoolRun.flavorLabel}).`
        : failed
          ? `SQL pool script stopped at statement ${failed.index} (line ${failed.line}): ${failed.message}`
          : `SQL pool script ran: ${sqlpoolRun.statements.length} statement(s) on the simulated ${sqlpoolRun.flavorLabel}.`,
      sqlpoolRun
    });
    if (request.script.trim()) await this.refreshCatalog();
  }

  /**
   * BI Lab: the warehouse scripts run on the local catalog (real DuckDB), then the runtime reports the tables,
   * the SQL lineage of the scripts (static analysis) and the star model checks (real queries).
   */
  async runBiLab(request: {
    mode: BiRunMode;
    source: string;
    scripts: { path: string; text: string }[];
    model: unknown;
    modelError?: string;
    warnings: string[];
  }): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running the BI Lab.");
    const raw = await this.postJson<unknown>(
      `${url}/api/local/bi/lab`,
      "POST",
      { scripts: request.scripts, model: request.model ?? null, run: request.mode !== "analyze" },
      120000
    );
    const biRun = toBiLabView(raw, request);
    const failed = biRun.statements.find(statement => statement.status === "error");
    this.setState({
      ...this.state,
      detail: failed
        ? `BI Lab stopped at ${failed.path}, line ${failed.line}: ${failed.message}`
        : biRun.ran
          ? `BI Lab: ${biRun.statements.length} statement(s) ran on the local catalog (${request.source}).`
          : `BI Lab: lineage and model checks refreshed (${request.source}).`,
      biRun
    });
    if (biRun.ran) await this.refreshCatalog();
  }

  /**
   * BI Lab dbt tab: the Datapass dbt emulation runs the command on the local catalog (Jinja in a sandbox, SQL on
   * DuckDB) and reports the nodes, the results and the column lineage of the models. It is not dbt Core.
   */
  async runBiDbt(request: { command: BiDbtCommand; select: string[]; selectText: string; fullRefresh: boolean;
    files: Record<string, string>; warnings: string[] }): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running dbt.");
    const raw = await this.postJson<unknown>(
      `${url}/api/local/bi/dbt`,
      "POST",
      { files: request.files, command: request.command, select: request.select, full_refresh: request.fullRefresh },
      120000
    );
    const biDbtRun = toBiDbtView(raw, { command: request.command, select: request.selectText, warnings: request.warnings });
    const counts = biDbtRun.counts ?? {};
    this.setState({
      ...this.state,
      detail: biDbtRun.status === "invalid"
        ? `dbt ${request.command} not run: ${biDbtRun.error ?? "invalid project"}`
        : biDbtRun.status === "parsed"
          ? `dbt project parsed: ${biDbtRun.nodes.length} nodes.`
          : `dbt ${request.command} (Datapass emulation): ${Object.entries(counts).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(", ") || "nothing selected"}.`,
      biDbtRun
    });
    if (biDbtRun.results.length) await this.refreshCatalog();
  }

  /**
   * Databricks Lab: the runtime validates and simulates the job; notebook and SQL tasks run on the local
   * catalog under Unity Catalog rules (or not at all in a dry run).
   */
  async simulateDatabricks(request: {
    name: string;
    path: string;
    document: unknown;
    files: DatabricksFilesPayload;
    scenario: DatabricksScenarioInput;
    warnings: string[];
  }): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running a Databricks job.");
    const context = { jobName: request.name, path: request.path, scenario: request.scenario, warnings: request.warnings };
    const { scenario, errors } = toDatabricksScenario(request.scenario);
    if (errors.length) {
      const databricksRun = toDatabricksLabView({ status: "error", issues: errors.map(message => ({ path: "scenario", message })) }, context);
      this.setState({ ...this.state, detail: `Job ${request.name} not run: fix the run settings.`, databricksRun });
      return;
    }
    const raw = await this.postJson<unknown>(
      `${url}/api/local/databricks/run`,
      "POST",
      { name: request.name, document: request.document, files: request.files, scenario, data_plane: request.scenario.dataPlane },
      60000
    );
    const databricksRun = toDatabricksLabView(raw, context);
    const record = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
    this.setState({
      ...this.state,
      detail: databricksRun.run
        ? `Job ${request.name}: ${databricksRun.run.statusLabel} (${databricksRun.dataPlane === "local" ? "tasks ran on the local catalog" : "dry run"}).`
        : `Job ${request.name} not run: ${databricksRun.issues[0]?.message ?? databricksRun.status}`,
      databricksRun,
      databricksState: record.unity ? toDatabricksStateView(raw) : this.state.databricksState
    });
    if (databricksRun.tablesChanged.length) await this.refreshCatalog();
  }

  /** Databricks Lab: Unity Catalog, MLflow and compute as they are, without running a job. */
  async exploreDatabricks(files: DatabricksFilesPayload): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) return;
    const raw = await this.postJson<unknown>(`${url}/api/local/databricks/state`, "POST", { files }, 20000);
    this.setState({ ...this.state, databricksState: toDatabricksStateView(raw) });
  }

  async runPipeline(source: string): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running a pipeline.");
    const pipelineRun = await this.postJson<NonNullable<RuntimeViewState["pipelineRun"]>>(
      `${url}/api/pipeline/run`,
      "POST",
      { source },
      30000
    );
    this.setState({
      ...this.state,
      detail: pipelineRun.status === "success"
        ? `Pipeline ${pipelineRun.pipeline_id} completed.`
        : `Pipeline ${pipelineRun.pipeline_id} finished with failures.`,
      pipelineRun
    });
    await this.refreshCatalog();
  }

  async compilePipeline(source: string): Promise<PipelineCompileResponse> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before compiling a pipeline.");
    return this.postJson<PipelineCompileResponse>(
      `${url}/api/pipeline/compile`,
      "POST",
      { source }
    );
  }

  /**
   * Projects: the runtime verifies steps of a shipped project on the workspace catalog and its run journal.
   * The caller keeps the result in .datapass/progress.json; manual steps are never verified.
   */
  async checkProject(projectId: string, steps: string[]): Promise<unknown> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before verifying project steps.");
    try {
      return await this.postJson<unknown>(`${url}/api/local/projects/check`, "POST", { project_id: projectId, steps }, 60000);
    } catch (error) {
      throw new Error(runtimeErrorDetail(error));
    }
  }

  /** Stop and wait for the process to exit so a restart never races the old worker. */
  async stopAndWait(timeoutMs = 5000): Promise<void> {
    const child = this.child;
    if (!child || child.exitCode !== null || child.signalCode !== null) {
      this.stop();
      return;
    }
    const exited = new Promise<void>(resolve => child.once("exit", () => resolve()));
    this.stop();
    await Promise.race([exited, new Promise<void>(resolve => setTimeout(resolve, timeoutMs))]);
  }

  stop(): void {
    if (!this.child) {
      this.setState({ status: "stopped" });
      return;
    }
    const child = this.child;
    this.child = undefined;
    this.token = undefined;
    child.kill();
    this.setState({ status: "stopped", detail: "Local runtime stopped." });
  }

  dispose(): void {
    this.stop();
    this.changed.dispose();
    this.output.dispose();
  }

  private managedPythonPath(): string {
    return managedVenvPython(path.join(this.storageUri.fsPath, "runtime-venv"));
  }

  /** The absolute path of the interpreter `pythonCommand` runs, so uv builds the venv from that same Python. */
  private pythonExecutable(pythonCommand: string): Promise<string> {
    return new Promise((resolve, reject) => {
      const child = spawn(pythonCommand, pythonExecutableArgs(), { windowsHide: true, stdio: ["ignore", "pipe", "ignore"] });
      let out = "";
      child.stdout?.on("data", chunk => { out += String(chunk); });
      child.once("error", reject);
      child.once("exit", code => {
        const executable = out.trim();
        if (code === 0 && executable) resolve(executable);
        else reject(new Error(`${pythonCommand} did not report its executable.`));
      });
    });
  }

  /** The first uv that answers `uv --version`: on PATH, then in its installers' folders. */
  private async findUv(): Promise<string | undefined> {
    for (const candidate of uvCandidates(homedir())) {
      if (candidate !== "uv" && !existsSync(candidate)) continue;
      const found = await new Promise<boolean>(resolve => {
        const child = spawn(candidate, ["--version"], { windowsHide: true, stdio: "ignore" });
        const timer = setTimeout(() => {
          child.kill();
          resolve(false);
        }, 5000);
        child.once("error", () => {
          clearTimeout(timer);
          resolve(false);
        });
        child.once("exit", code => {
          clearTimeout(timer);
          resolve(code === 0);
        });
      });
      if (found) return candidate;
    }
    return undefined;
  }

  private runSetupCommand(
    command: string,
    args: readonly string[],
    cwd: string,
    onActivity?: (activity: string) => void
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      this.output.appendLine(`> ${command} ${args.join(" ")}`);
      const child = spawn(command, [...args], {
        cwd,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        env: process.env
      });

      let pending = "";
      const onChunk = (chunk: unknown): void => {
        const text = String(chunk);
        this.output.append(text);
        if (!onActivity) return;
        const lines = (pending + text).split(/\r?\n/);
        pending = lines.pop() ?? "";
        for (const line of lines) {
          const activity = describeSetupOutputLine(line);
          if (activity) onActivity(activity);
        }
      };
      child.stdout?.on("data", onChunk);
      child.stderr?.on("data", onChunk);
      child.once("error", reject);
      child.once("exit", (code, signal) => {
        if (code === 0) {
          resolve();
          return;
        }
        reject(new Error(
          `Runtime setup command failed${code !== null ? ` with code ${code}` : ""}${signal ? ` (${signal})` : ""}.`
        ));
      });
    });
  }

  private postJson<T>(url: string, method: "POST", body: unknown, timeoutMs?: number): Promise<T> {
    return requestJson<T>(url, method, body, timeoutMs, this.token);
  }

  private getJson<T>(url: string, timeoutMs?: number): Promise<T> {
    return requestGetJson<T>(url, timeoutMs, this.token);
  }

  private setState(next: RuntimeViewState): void {
    this.state = next;
    this.changed.fire(this.snapshot());
  }
}



/** The script's workspace path as the run journal's label; anything the runtime would refuse is dropped. */
function sqlPoolSourceLabel(source: string): string {
  return /^[A-Za-z0-9_./ -]{0,200}$/.test(source) ? source : "";
}

/** Pull FastAPI's `detail` out of a "Runtime request failed with HTTP 4xx: {...}" error. */
function runtimeErrorDetail(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const body = /^Runtime request failed with HTTP \d+: (.*)$/s.exec(message)?.[1];
  if (!body) return message;
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map(item => (item && typeof item === "object" && "msg" in item ? String(item.msg) : String(item)))
        .join("; ");
    }
  } catch {
    // Not JSON (e.g. truncated); fall through to the raw message.
  }
  return message;
}
