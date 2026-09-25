import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import * as http from "node:http";
import * as path from "node:path";
import * as vscode from "vscode";
import type { AirflowScenarioInput, CsvImportView, RuntimeEnvironmentView, RuntimeViewState } from "./webview/contracts";
import { findFreePort, waitForDatapassHealth } from "./platform/runtimeEndpoint";
import {
  describeSetupOutputLine,
  managedVenvPython,
  runtimeInstallArgs,
  runtimeVerifyArgs
} from "./platform/runtimeEnvironment";
import { runtimeProcessEnv } from "./platform/pythonTrust";
import { toSparkLabRunView } from "./platform/sparkLabRun";
import { toAirflowLabView, toRuntimeScenario } from "./platform/airflowRun";

const HOST = "127.0.0.1";
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
          if (!existsSync(managedPython)) {
            this.output.appendLine("Creating isolated Datapass Python environment.");
            setProgress(1, "Creating Python environment");
            await this.runSetupCommand(
              pythonCommand,
              ["-m", "venv", venvRoot],
              this.storageUri.fsPath
            );
          }

          const installLabel = "Installing runtime dependencies";
          this.output.appendLine("Installing Datapass runtime and local engine dependencies.");
          setProgress(2, installLabel);
          await this.runSetupCommand(
            managedPython,
            runtimeInstallArgs(runtimeRoot),
            runtimeRoot,
            onActivity(2, installLabel)
          );

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
          workspaceRoot: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
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
      await waitForDatapassHealth(`${url}/api/health`, STARTUP_TIMEOUT_MS, () => exitReason);
      if (this.child === child) {
        const capabilities = await requestGetJson<{ runtime?: { trusted_local_python?: unknown } }>(
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
    const result = await requestJson<Omit<NonNullable<RuntimeViewState["practiceResult"]>, "exerciseKey" | "mode">>(
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
      const retailDemo = await requestJson<NonNullable<RuntimeViewState["retailDemo"]>>(
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
      response = await requestJson<Omit<CsvImportView, "fileName">>(
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

  async runSql(code: string): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running SQL.");
    const lastRun = await requestJson<NonNullable<RuntimeViewState["lastRun"]>>(
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
  }

  async runPython(code: string): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running Python.");
    if (!this.state.trustedPython) {
      throw new Error("Trusted local Python is disabled for this runtime. Enable it for the workspace, then restart the runtime.");
    }
    const lastRun = await requestJson<NonNullable<RuntimeViewState["lastRun"]>>(
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
    const raw = await requestJson<unknown>(
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
    if (!url) return;
    try {
      const catalog = await requestGetJson<NonNullable<RuntimeViewState["catalog"]>>(
        `${url}/api/local/catalog`
      );
      this.setState({ ...this.state, catalog });
    } catch (error) {
      this.setState({
        ...this.state,
        detail: `Catalog refresh failed: ${error instanceof Error ? error.message : String(error)}`
      });
    }
  }

  /** Airflow Lab: the DAG file's TEXT is parsed and simulated by the runtime, never executed. */
  async simulateAirflow(source: string, fileName: string, scenario: AirflowScenarioInput): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before simulating an Airflow DAG.");
    const raw = await requestJson<unknown>(
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

  async runPipeline(source: string): Promise<void> {
    const url = this.state.status === "running" ? this.state.url : undefined;
    if (!url) throw new Error("Start the Datapass runtime before running a pipeline.");
    const pipelineRun = await requestJson<NonNullable<RuntimeViewState["pipelineRun"]>>(
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
    return requestJson<PipelineCompileResponse>(
      `${url}/api/pipeline/compile`,
      "POST",
      { source }
    );
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

  private setState(next: RuntimeViewState): void {
    this.state = next;
    this.changed.fire(this.snapshot());
  }
}



function requestJson<T>(
  url: string,
  method: "POST",
  body: unknown,
  timeoutMs = 2500
): Promise<T> {
  return new Promise((resolve, reject) => {
    const payload = Buffer.from(JSON.stringify(body), "utf8");
    const request = http.request(
      url,
      {
        method,
        headers: {
          "content-type": "application/json",
          "content-length": String(payload.length)
        }
      },
      response => {
        const chunks: Buffer[] = [];
        response.on("data", chunk => chunks.push(Buffer.from(chunk)));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          if ((response.statusCode ?? 500) < 200 || (response.statusCode ?? 500) >= 300) {
            reject(new Error(`Runtime request failed with HTTP ${response.statusCode}: ${text.slice(0, 500)}`));
            return;
          }
          try {
            resolve(JSON.parse(text) as T);
          } catch (error) {
            reject(error);
          }
        });
      }
    );
    request.setTimeout(timeoutMs, () => request.destroy(new Error("Runtime request timed out.")));
    request.on("error", reject);
    request.end(payload);
  });
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

function requestGetJson<T>(url: string, timeoutMs = 3000): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = http.get(url, response => {
      const chunks: Buffer[] = [];
      response.on("data", chunk => chunks.push(Buffer.from(chunk)));
      response.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        if ((response.statusCode ?? 500) < 200 || (response.statusCode ?? 500) >= 300) {
          reject(new Error(`Runtime request failed with HTTP ${response.statusCode}: ${text.slice(0, 500)}`));
          return;
        }
        try {
          resolve(JSON.parse(text) as T);
        } catch (error) {
          reject(error);
        }
      });
    });
    request.setTimeout(timeoutMs, () => request.destroy(new Error("Runtime request timed out.")));
    request.on("error", reject);
  });
}
