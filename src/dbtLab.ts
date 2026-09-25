import { execFile, spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";
import {
  DBT_TOOL_PACKAGES,
  dbtTerminalEnv,
  dbtToolRequirements,
  isCatalogCommand,
  isSupportedDbtPython,
  parsePythonVersion,
  profilesYaml,
  pythonCandidates,
  readProfileName,
  toDctValidation,
  type DctValidationView
} from "./platform/dbtTools";
import { describeSetupOutputLine, managedVenvPython } from "./platform/runtimeEnvironment";
import type { RuntimeManager } from "./runtimeManager";
import type { DbtToolsView } from "./webview/contracts";

const VENV_FOLDER = "dbt-tools-venv";
const VERSIONS_FILE = "dbt-tools.json";

/**
 * The managed dbt tools environment (dbt Core, dbt-duckdb): a venv in the extension's global storage, separate
 * from the runtime's (dbt pins its own dependencies and needs Python 3.10–3.13). It is created only by an explicit
 * Install dbt tools; nothing is installed silently.
 */
export class DbtToolsManager implements vscode.Disposable {
  private readonly output = vscode.window.createOutputChannel("Datapass dbt tools");
  private readonly changed = new vscode.EventEmitter<DbtToolsView>();
  readonly onDidChange = this.changed.event;
  private view: DbtToolsView;

  constructor(private readonly storageUri: vscode.Uri) {
    this.view = this.detect();
  }

  get venvRoot(): string {
    return path.join(this.storageUri.fsPath, VENV_FOLDER);
  }

  get binDir(): string {
    return path.dirname(managedVenvPython(this.venvRoot));
  }

  snapshot(): DbtToolsView {
    return { ...this.view };
  }

  showLog(): void {
    this.output.show(true);
  }

  /** Create the venv (if needed) and install the pinned tools; `runtimePython` pins DuckDB to the runtime's version. */
  async install(runtimePython: string | undefined, extraRequirements: readonly string[] = []): Promise<void> {
    if (this.view.status === "installing") return;
    const python = managedVenvPython(this.venvRoot);
    const startedAt = Date.now();
    const progress = (step: number, label: string, activity?: string) => {
      this.view = { status: "installing", detail: "Installing dbt tools in a managed environment…",
        progress: { step, totalSteps: 3, label, activity, startedAt } };
      this.changed.fire(this.snapshot());
    };
    try {
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Datapass dbt tools" },
        async report => {
          const say = (step: number, label: string, activity?: string) => {
            progress(step, label, activity);
            report.report({ message: `Step ${step}/3: ${label}${activity ? ` · ${activity}` : ""}` });
          };
          say(1, "Finding Python 3.10–3.13");
          if (!existsSync(python)) {
            const base = await findDbtPython(vscode.workspace.getConfiguration("datapass").get<string>("dbtTools.python"));
            this.output.appendLine(`Creating the dbt tools environment with ${base.label} (${base.version}).`);
            await vscode.workspace.fs.createDirectory(this.storageUri);
            await this.run(base.command, [...base.args, "-m", "venv", this.venvRoot]);
          }
          const duckdb = runtimePython ? await probeDuckdbVersion(runtimePython) : undefined;
          const requirements = dbtToolRequirements(duckdb, extraRequirements);
          say(2, "Installing " + requirements.map(r => r.split(/[<>=]/)[0]).join(", "));
          let last = 0;
          await this.run(python, ["-m", "pip", "install", "--disable-pip-version-check", "--upgrade", ...requirements], line => {
            const activity = describeSetupOutputLine(line);
            if (activity && Date.now() - last > 400) {
              last = Date.now();
              say(2, "Installing packages", activity);
            }
          });
          say(3, "Verifying dbt --version");
          await this.run(path.join(this.binDir, process.platform === "win32" ? "dbt.exe" : "dbt"), ["--version"]);
          const versions = await packageVersions(python);
          await vscode.workspace.fs.writeFile(
            vscode.Uri.joinPath(this.storageUri, VERSIONS_FILE),
            new TextEncoder().encode(JSON.stringify({ versions, installedAt: new Date().toISOString() }, null, 2))
          );
        }
      );
      this.view = this.detect();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      this.output.appendLine(detail);
      this.view = { status: "error", detail };
      this.changed.fire(this.snapshot());
      throw error;
    }
    this.changed.fire(this.snapshot());
  }

  /** Re-read the environment after an install or when the Workbench refreshes. */
  refresh(): DbtToolsView {
    if (this.view.status !== "installing") this.view = this.detect();
    return this.snapshot();
  }

  private detect(): DbtToolsView {
    const python = managedVenvPython(this.venvRoot);
    if (!existsSync(python)) return { status: "missing", detail: "dbt Core is not installed for the dbt Lab yet." };
    try {
      const file = path.join(this.storageUri.fsPath, VERSIONS_FILE);
      const saved = JSON.parse(readFileSync(file, "utf8")) as { versions?: Record<string, string | null> };
      const versions = saved.versions ?? {};
      if (!versions["dbt-core"] || !versions["dbt-duckdb"]) {
        return { status: "missing", python, detail: "The dbt tools environment is incomplete. Install dbt tools again." };
      }
      return { status: "ready", python, binDir: this.binDir, versions, detail: "Managed dbt tools are installed." };
    } catch {
      return { status: "missing", python, detail: "The dbt tools environment was not verified. Install dbt tools again." };
    }
  }

  private run(command: string, args: readonly string[], onLine?: (line: string) => void): Promise<void> {
    return new Promise((resolve, reject) => {
      this.output.appendLine(`> ${command} ${args.join(" ")}`);
      const child = spawn(command, [...args], {
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        env: { ...process.env, PIP_NO_INPUT: "1", DBT_SEND_ANONYMOUS_USAGE_STATS: "false" }
      });
      let pending = "";
      const onChunk = (chunk: unknown) => {
        const text = String(chunk);
        this.output.append(text);
        const lines = (pending + text).split(/\r?\n/);
        pending = lines.pop() ?? "";
        for (const line of lines) onLine?.(line);
      };
      child.stdout?.on("data", onChunk);
      child.stderr?.on("data", onChunk);
      child.once("error", reject);
      child.once("exit", code => code === 0 ? resolve() : reject(new Error(
        `${path.basename(command)} ${args.slice(0, 3).join(" ")} failed with code ${code}. See the "Datapass dbt tools" output.`
      )));
    });
  }

  dispose(): void {
    this.changed.dispose();
    this.output.dispose();
  }
}

async function findDbtPython(configured: string | undefined): Promise<{ command: string; args: string[]; label: string; version: string }> {
  const tried: string[] = [];
  for (const candidate of pythonCandidates(process.platform, configured)) {
    const label = [candidate.command, ...candidate.args].join(" ");
    const output = await execOutput(candidate.command, [...candidate.args, "--version"]);
    const version = parsePythonVersion(output ?? "");
    tried.push(`${label}: ${version ? version.join(".") : "not found"}`);
    if (isSupportedDbtPython(version)) return { ...candidate, label, version: version!.join(".") };
  }
  throw new Error(
    `dbt Core needs Python 3.10 to 3.13, and none was found (${tried.join("; ")}). ` +
    "Install one (python.org), or set the setting datapass.dbtTools.python to its path, then retry."
  );
}

async function probeDuckdbVersion(python: string): Promise<string | undefined> {
  const output = await execOutput(python, ["-c", "import duckdb; print(duckdb.__version__)"]);
  return output?.trim() || undefined;
}

async function packageVersions(python: string): Promise<Record<string, string | null>> {
  const packages = JSON.stringify([...DBT_TOOL_PACKAGES, "dbt-charts"]);
  const code = `import importlib.metadata as m, json\nout = {}\nfor p in ${packages}:\n    try: out[p] = m.version(p)\n    except m.PackageNotFoundError: out[p] = None\nprint(json.dumps(out))`;
  const output = await execOutput(python, ["-c", code]);
  return output ? JSON.parse(output) as Record<string, string | null> : {};
}

function execOutput(command: string, args: string[]): Promise<string | undefined> {
  return new Promise(resolve => {
    execFile(command, args, { timeout: 20000, windowsHide: true }, (error, stdout, stderr) => {
      resolve(error ? undefined : String(stdout || stderr || ""));
    });
  });
}

/**
 * The real `dct validate --json <board>` in the project folder (no database, nothing executed): run without a shell
 * by the host, for the lab's board badges and for the missions' checker.
 */
export async function dctValidate(tools: Pick<DbtToolsManager, "binDir" | "venvRoot">, folder: vscode.Uri,
  profilesDir: vscode.Uri, board: string): Promise<DctValidationView> {
  const env = dbtTerminalEnv(process.env, tools.binDir, tools.venvRoot, profilesDir.fsPath, path.delimiter);
  const output = await new Promise<string>(resolve => {
    execFile(path.join(tools.binDir, process.platform === "win32" ? "dct.exe" : "dct"), ["--no-workspace-guard", "validate", "--json", board], {
      cwd: folder.fsPath, env: { ...process.env, ...env, PYTHONIOENCODING: "utf-8" }, timeout: 60_000, windowsHide: true, maxBuffer: 4_000_000
    }, (_error, stdout, stderr) => resolve(String(stdout || stderr || "")));
  });
  const checkedAt = new Date().toISOString();
  try {
    return toDctValidation(JSON.parse(output), board, checkedAt);
  } catch {
    const message = output.trim().split(/\r?\n/).slice(-3).join(" ") || "dct validate gave no JSON.";
    return { board, success: false, checkedAt, warnings: [], errors: [{ code: "", message }] };
  }
}

/** Write `.datapass/dbt/profiles.yml` with one DuckDB output per dbt project profile found in the workspace. */
export async function writeDbtProfiles(root: vscode.Uri, projectFiles: readonly vscode.Uri[]): Promise<vscode.Uri> {
  const profilesDir = vscode.Uri.joinPath(root, ".datapass", "dbt");
  const dataDir = vscode.Uri.joinPath(root, ".datapass", "data");
  await vscode.workspace.fs.createDirectory(profilesDir);
  await vscode.workspace.fs.createDirectory(dataDir);
  const names: string[] = [];
  for (const file of projectFiles) {
    try {
      const name = readProfileName(new TextDecoder().decode(await vscode.workspace.fs.readFile(file)));
      if (name) names.push(name);
    } catch {
      // A project that cannot be read gets no profile; dbt then says the profile is missing.
    }
  }
  const content = profilesYaml(names, vscode.Uri.joinPath(dataDir, "workspace.duckdb").fsPath);
  const target = vscode.Uri.joinPath(profilesDir, "profiles.yml");
  let current: string | undefined;
  try {
    current = new TextDecoder().decode(await vscode.workspace.fs.readFile(target));
  } catch {
    current = undefined;
  }
  if (current !== content) await vscode.workspace.fs.writeFile(target, new TextEncoder().encode(content));
  return profilesDir;
}

/**
 * The dbt Lab terminal: a real VS Code integrated terminal in the project folder, with the managed tools on PATH.
 * A dbt or dct command borrows the catalog file: Datapass asks the runtime to release it when the command starts
 * and reattaches it when the command ends (VS Code shell integration reports both). Commands the learner retypes
 * in that terminal get the same handoff.
 */
export class DbtTerminalSession implements vscode.Disposable {
  private terminal?: vscode.Terminal;
  private serveTerminal?: vscode.Terminal;
  private cwd?: string;
  /** Catalog commands in flight, with the terminal that runs them. */
  private readonly running = new Map<vscode.TerminalShellExecution, vscode.Terminal>();
  /** Every command in flight in an owned terminal: a new one waits for them (executeCommand would interrupt it). */
  private readonly busy = new Map<vscode.TerminalShellExecution, vscode.Terminal>();
  private readonly idle = new vscode.EventEmitter<void>();
  private readonly disposables: vscode.Disposable[] = [];
  private readonly ended = new vscode.EventEmitter<{ commandLine: string; exitCode: number | undefined }>();
  readonly onDidEndCommand = this.ended.event;
  /** The `dct serve` URL while its terminal is open. */
  serveUrl?: string;

  constructor(
    private readonly runtime: RuntimeManager,
    private readonly tools: Pick<DbtToolsManager, "binDir" | "venvRoot">
  ) {
    this.disposables.push(
      vscode.window.onDidStartTerminalShellExecution(event => {
        if (this.owns(event.terminal)) this.busy.set(event.execution, event.terminal);
        if (!this.owns(event.terminal) || !isCatalogCommand(event.execution.commandLine.value)) return;
        this.running.set(event.execution, event.terminal);
        void this.lend(event.execution.commandLine.value);
      }),
      vscode.window.onDidEndTerminalShellExecution(event => {
        if (this.busy.delete(event.execution)) this.idle.fire();
        if (!this.owns(event.terminal) || !this.running.delete(event.execution)) return;
        void this.giveBack().then(() => this.ended.fire({ commandLine: event.execution.commandLine.value, exitCode: event.exitCode }));
      }),
      vscode.window.onDidCloseTerminal(terminal => {
        if (!this.owns(terminal)) return;
        if (terminal === this.terminal) this.terminal = undefined;
        if (terminal === this.serveTerminal) {
          this.serveTerminal = undefined;
          this.serveUrl = undefined;
        }
        for (const [execution, owner] of this.running) if (owner === terminal) this.running.delete(execution);
        for (const [execution, owner] of this.busy) if (owner === terminal) this.busy.delete(execution);
        this.idle.fire();
        void this.giveBack().then(() => this.ended.fire({ commandLine: "", exitCode: undefined }));
      })
    );
  }

  /** Type and run `commandLine` in the project folder's dbt terminal (created if needed); without one, just show it. */
  async run(projectDir: vscode.Uri, profilesDir: vscode.Uri, commandLine: string | undefined): Promise<void> {
    const terminal = this.ensureTerminal(projectDir, profilesDir);
    terminal.show(!commandLine ? false : true);
    if (commandLine) await this.execute(terminal, commandLine);
  }

  /**
   * `dct serve` in a terminal of its own (a server keeps its terminal busy). It borrows the catalog while it runs;
   * closing the terminal (Stop) ends it and gives the catalog back.
   */
  async serve(projectDir: vscode.Uri, profilesDir: vscode.Uri, commandLine: string, url: string): Promise<void> {
    this.serveTerminal?.dispose();
    this.serveTerminal = this.createTerminal(`dct serve · ${path.basename(projectDir.fsPath)}`, projectDir, profilesDir);
    this.serveUrl = url;
    this.serveTerminal.show(true);
    await this.execute(this.serveTerminal, commandLine);
  }

  stopServe(): void {
    this.serveTerminal?.dispose();
  }

  get serving(): boolean {
    return Boolean(this.serveTerminal);
  }

  get hasShellIntegration(): boolean {
    return Boolean(this.terminal?.shellIntegration);
  }

  private owns(terminal: vscode.Terminal): boolean {
    return terminal === this.terminal || terminal === this.serveTerminal;
  }

  private async execute(terminal: vscode.Terminal, commandLine: string): Promise<void> {
    await this.whenIdle(terminal);
    // Release before typing: dbt and dct open the file within seconds of starting.
    if (isCatalogCommand(commandLine)) await this.lend(commandLine);
    const integration = terminal.shellIntegration ?? await waitForShellIntegration(terminal, 4000);
    if (integration) {
      integration.executeCommand(commandLine);
    } else {
      // No shell integration (e.g. cmd.exe): the end of the command is not reported, so Reattach is manual.
      terminal.sendText(commandLine, true);
    }
  }

  /** Wait (up to 10 minutes) until no command runs in `terminal`: typing now would interrupt the running one. */
  private whenIdle(terminal: vscode.Terminal): Promise<void> {
    const isBusy = () => [...this.busy.values()].includes(terminal);
    if (!isBusy()) return Promise.resolve();
    return new Promise(resolve => {
      const timer = setTimeout(done, 600_000);
      const listener = this.idle.event(() => { if (!isBusy()) done(); });
      function done() {
        clearTimeout(timer);
        listener.dispose();
        resolve();
      }
    });
  }

  private ensureTerminal(projectDir: vscode.Uri, profilesDir: vscode.Uri): vscode.Terminal {
    if (this.terminal && this.terminal.exitStatus === undefined && this.cwd === projectDir.fsPath) return this.terminal;
    this.terminal?.dispose();
    this.cwd = projectDir.fsPath;
    this.terminal = this.createTerminal(`dbt · ${path.basename(projectDir.fsPath)}`, projectDir, profilesDir);
    return this.terminal;
  }

  private createTerminal(name: string, projectDir: vscode.Uri, profilesDir: vscode.Uri): vscode.Terminal {
    return vscode.window.createTerminal({
      name,
      cwd: projectDir,
      iconPath: new vscode.ThemeIcon("database"),
      env: dbtTerminalEnv(process.env, this.tools.binDir, this.tools.venvRoot, profilesDir.fsPath, path.delimiter)
    });
  }

  private async lend(commandLine: string): Promise<void> {
    try {
      await this.runtime.releaseCatalog(commandLine);
    } catch (error) {
      void vscode.window.showWarningMessage(
        `The runtime could not release the catalog: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  private async giveBack(): Promise<void> {
    if (this.running.size > 0) return;
    // Windows can take a moment to release a file after the process that held it exits: retry briefly.
    for (let attempt = 0; attempt < 5; attempt++) {
      if (await this.runtime.reattachCatalog()) return;
      if (this.running.size > 0) return;
      await new Promise(resolve => setTimeout(resolve, 800 * (attempt + 1)));
    }
    if (!(await this.runtime.reattachCatalog())) {
      void vscode.window.showWarningMessage(
        this.runtime.snapshot().catalogLease?.reattachError ?? "The catalog is still held by another process."
      );
    }
  }

  dispose(): void {
    for (const disposable of this.disposables) disposable.dispose();
    this.ended.dispose();
    this.idle.dispose();
    this.terminal?.dispose();
    this.serveTerminal?.dispose();
  }
}

function waitForShellIntegration(terminal: vscode.Terminal, timeoutMs: number): Promise<vscode.TerminalShellIntegration | undefined> {
  return new Promise(resolve => {
    const timer = setTimeout(() => {
      listener.dispose();
      resolve(terminal.shellIntegration);
    }, timeoutMs);
    const listener = vscode.window.onDidChangeTerminalShellIntegration(event => {
      if (event.terminal !== terminal) return;
      clearTimeout(timer);
      listener.dispose();
      resolve(event.shellIntegration);
    });
  });
}
