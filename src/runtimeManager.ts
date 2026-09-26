import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import type { RuntimeEnvironmentView, RuntimeViewState } from "./webview/contracts";
import { createLabClients, type LabClients } from "./labs/clients";
import type { RuntimeConnection } from "./labs/runtimeConnection";
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
import {
  checkManagedRuntime,
  extensionVersion,
  readRuntimeMarker,
  removeRuntimeMarker,
  runtimeFingerprint,
  writeRuntimeMarker
} from "./platform/runtimeFingerprint";
import { runtimeProcessEnv } from "./platform/pythonTrust";
import { newRuntimeToken, requestGetJson, requestJson, runtimeErrorDetail } from "./platform/runtimeClient";

const HOST = "127.0.0.1";
/** Catalog listing, including the first one that creates the workspace catalog. */
const CATALOG_TIMEOUT_MS = 30_000;
// A cold start in a fresh managed venv (FastAPI, DuckDB, Polars, pandas; first
// bytecode compilation; antivirus scanning on Windows) can exceed ten seconds.
const STARTUP_TIMEOUT_MS = 90_000;

export class RuntimeManager implements vscode.Disposable {
  private child?: ChildProcess;
  /** This launch's runtime token: in memory only, never persisted or logged. */
  private token?: string;
  private state: RuntimeViewState = { status: "stopped" };
  private readonly output = vscode.window.createOutputChannel("Datapass Runtime");
  private readonly changed = new vscode.EventEmitter<RuntimeViewState>();
  private environment: RuntimeEnvironmentView;

  readonly onDidChange = this.changed.event;

  /** The runtime clients of the labs (`labs.mosaic.runSql(...)`), one per lab, on this manager's connection. */
  readonly labs: LabClients = createLabClients(this.connection());

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly storageUri: vscode.Uri
  ) {
    this.environment = this.inspectEnvironment();
  }

  /**
   * The managed venv as it is on disk: missing, ready, or stale when its recorded runtime fingerprint differs from
   * this extension's `runtime/` sources (a newer VSIX over an older Setup). A stale runtime is never started as is.
   */
  private inspectEnvironment(): RuntimeEnvironmentView {
    const venvRoot = this.managedVenvRoot();
    const python = managedVenvPython(venvRoot);
    let fingerprint: string;
    try {
      fingerprint = runtimeFingerprint(this.runtimeRoot());
    } catch (error) {
      return { status: "error", python, detail: `Could not read the bundled runtime: ${error instanceof Error ? error.message : String(error)}` };
    }
    const check = checkManagedRuntime({
      pythonExists: existsSync(python),
      marker: readRuntimeMarker(venvRoot),
      fingerprint,
      extensionVersion: extensionVersion(this.extensionUri.fsPath)
    });
    switch (check.status) {
      case "missing":
        return { status: "missing", detail: "Managed Datapass runtime is not installed yet." };
      case "ready":
        return { status: "ready", python, detail: "Managed Datapass runtime is installed and matches this extension." };
      case "stale":
        return { status: "stale", python, detail: check.reason };
    }
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

    const runtimeRoot = this.runtimeRoot();
    const venvRoot = this.managedVenvRoot();
    const managedPython = managedVenvPython(venvRoot);
    // Fingerprint the sources before installing: pip builds in the source folder (build/, *.egg-info), which the
    // fingerprint ignores anyway, and the marker must describe exactly what this install took.
    const fingerprint = runtimeFingerprint(runtimeRoot);
    const updating = existsSync(managedPython);
    const title = updating ? "Datapass runtime update" : "Datapass runtime setup";

    const startedAt = Date.now();
    const totalSteps = 3;
    let reportNotification: (message: string) => void = () => undefined;
    let lastActivityFire = 0;
    const setProgress = (step: number, label: string, activity?: string): void => {
      this.environment = {
        status: "setting-up",
        python: managedPython,
        detail: updating
          ? "Reinstalling this extension's Datapass runtime into the existing environment…"
          : "Creating and installing the isolated Datapass runtime…",
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
        { location: vscode.ProgressLocation.Notification, title },
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

          removeRuntimeMarker(venvRoot);
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
          writeRuntimeMarker(venvRoot, {
            schema: 1,
            fingerprint,
            extensionVersion: extensionVersion(this.extensionUri.fsPath),
            installedAt: new Date().toISOString()
          });
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

    const runtimeRoot = this.runtimeRoot();
    const managedPython = this.managedPythonPath();
    if (existsSync(managedPython)) {
      // Re-check on every start: the extension may have been updated since the last check.
      this.environment = this.inspectEnvironment();
      if (this.environment.status === "stale") {
        this.output.appendLine(`${this.environment.detail} Updating it before the start.`);
        try {
          await this.setup(pythonCommand);
        } catch {
          return; // setup() reported the failure; never fall back to the stale install.
        }
      }
      if (this.environment.status !== "ready") {
        this.setState({ status: "error", detail: this.environment.detail ?? "The managed Datapass runtime is not ready." });
        return;
      }
    }
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
      `${url}/api/local/catalog/release`, { holder: holder.slice(0, 200) }, 30000
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
      await this.postJson<unknown>(`${url}/api/local/catalog/reattach`, {}, 30000);
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

  private runtimeRoot(): string {
    return path.join(this.extensionUri.fsPath, "runtime");
  }

  private managedVenvRoot(): string {
    return path.join(this.storageUri.fsPath, "runtime-venv");
  }

  private managedPythonPath(): string {
    return managedVenvPython(this.managedVenvRoot());
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

  private postJson<T>(url: string, body: unknown, timeoutMs?: number): Promise<T> {
    return requestJson<T>(url, "POST", body, timeoutMs, this.token);
  }

  private getJson<T>(url: string, timeoutMs?: number): Promise<T> {
    return requestGetJson<T>(url, timeoutMs, this.token);
  }

  /** What the lab clients use: the running URL, token-carrying requests and the shared state. */
  private connection(): RuntimeConnection {
    return {
      runningUrl: () => (this.state.status === "running" ? this.state.url : undefined),
      requireRunning: action => this.requireRunning(action),
      requireAttached: action => this.requireAttached(action),
      postJson: (url, body, timeoutMs) => this.postJson(url, body, timeoutMs),
      getJson: (url, timeoutMs) => this.getJson(url, timeoutMs),
      state: () => this.state,
      update: patch => this.setState({ ...this.state, ...patch }),
      refreshCatalog: () => this.refreshCatalog()
    };
  }

  private setState(next: RuntimeViewState): void {
    this.state = next;
    this.changed.fire(this.snapshot());
  }
}
