import * as http from "node:http";
import * as vscode from "vscode";
import { dctValidate, writeDbtProfiles } from "../../dbtLab";
import { findDbtProjects, projectFolder } from "../../dbtState";
import type { ModuleId } from "../../modules";
import {
  buildDbtCommand,
  buildDctCommand,
  isBoardPath,
  renderPath,
  type DbtCommand,
  type DctFormat,
  type DctValidationView
} from "../../platform/dbtTools";
import { missionFolder } from "../../platform/missions";
import { findFreePort } from "../../platform/runtimeEndpoint";
import { safeRelativeParts } from "../../platform/workspacePaths";
import { readProjectManifest } from "../../project/projectManifest";
import type { DbtMessage } from "../../webview/contracts";
import { copyWithoutOverwrite, exists } from "../../workspaceFiles";
import type { WorkbenchStateExtras } from "../../workbenchState";
import type { LabController, MessageHandlers, WorkbenchHost } from "../host";
import type { MissionLabHooks } from "../missions/controller";

const DBT_SELECTED_KEY = "datapass.dbt.selectedProject";

/**
 * dbt Lab: real dbt Core and dbt Charts typed in a VS Code terminal (managed tools installed only on request), the
 * catalog handoff, the artifacts view and the dbt missions.
 */
export class DbtController implements LabController<DbtMessage> {
  readonly refreshOnSave = "dbt" as const;
  /** `dct validate --json` results per `<project>::<board>`, shown next to each board. */
  private readonly dctValidations = new Map<string, DctValidationView>();
  private readonly disposables: vscode.Disposable[] = [];

  constructor(private readonly host: WorkbenchHost) {
    const { tools, terminal } = host.services;
    const refreshIfShown = () => {
      if (this.host.selectedModule === "dbt") void this.host.refresh();
    };
    // A real dbt run rewrites target/run_results.json and target/manifest.json.
    const dbtArtifactWatcher = vscode.workspace.createFileSystemWatcher("**/target/{manifest,run_results}.json");
    this.disposables.push(
      dbtArtifactWatcher,
      dbtArtifactWatcher.onDidCreate(refreshIfShown),
      dbtArtifactWatcher.onDidChange(() => {
        refreshIfShown();
        // Without shell integration the terminal never reports the end of a command: new artifacts are the signal.
        if (this.host.runtime.snapshot().catalogLease && !terminal.hasShellIntegration) {
          setTimeout(() => void this.host.runtime.reattachCatalog(), 2000);
        }
      }),
      tools.onDidChange(refreshIfShown),
      terminal.onDidEndCommand(refreshIfShown)
    );
  }

  readonly handlers: MessageHandlers<DbtMessage> = {
    createDbtSample: () => this.createDbtSample(),
    selectDbtProject: async message => {
      await this.host.context.workspaceState.update(DBT_SELECTED_KEY, message.path);
      await this.host.refresh();
    },
    refreshDbt: async () => {
      this.host.services.tools.refresh();
      await this.host.refresh();
    },
    installDbtTools: () => this.installDbtTools(),
    showDbtToolsLog: () => this.host.services.tools.showLog(),
    runDbtCommand: message => this.runDbtCommand(message.command, message.select, message.exclude, message.fullRefresh),
    openDbtTerminal: () => this.runDbtCommand(undefined, "", "", false),
    openDbtFile: message => this.openDbtFile(message.path),
    runDct: message => this.runDct(message.action, message.board, message.format),
    serveDct: () => this.serveDct(),
    stopDctServe: async () => {
      this.host.services.terminal.stopServe();
      await this.host.refresh();
    },
    openDctHtml: message => this.openDctHtml(message.board)
  };

  /** dbt missions: the mission folder is a dbt project; the checker reads the catalog it built. */
  readonly missionHooks: MissionLabHooks = {
    restartWarning: () =>
      "Start the mission over? Its data in the catalog is reloaded from the first batch and the tables dbt built for it are dropped. Your files in the mission folder stay as they are.",
    open: mission => this.openMission(mission.id)
  };

  async contribute(selected: ModuleId): Promise<Partial<WorkbenchStateExtras>> {
    const { tools, terminal, missions } = this.host.services;
    return {
      dbtLab: {
        tools: tools.snapshot(),
        selected: this.host.context.workspaceState.get<string>(DBT_SELECTED_KEY),
        shellIntegration: terminal.hasShellIntegration,
        validations: this.dctValidations,
        serveUrl: terminal.serveUrl,
        missions: selected === "dbt"
          ? { missions: await missions.list("dbt"), progress: (await missions.progress()).missions }
          : undefined
      }
    };
  }

  dispose(): void {
    while (this.disposables.length) this.disposables.pop()?.dispose();
  }

  /** Copy the bundled retail dbt sample to <assets.dbt>/retail-dbt (never overwriting) and select it. */
  async createDbtSample(): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder before creating a dbt project.");
      return;
    }
    const manifest = await readProjectManifest();
    const dbtRoot = safeRelativeParts(manifest.manifest?.assets?.dbt, "dbt");
    const projectRoot = vscode.Uri.joinPath(root, ...dbtRoot, "retail-dbt");
    await copyWithoutOverwrite(vscode.Uri.joinPath(this.host.context.extensionUri, "samples", "dbt", "retail-dbt"), projectRoot);
    const projectFile = vscode.Uri.joinPath(projectRoot, "dbt_project.yml");
    if (!(await exists(projectFile))) {
      void vscode.window.showErrorMessage("The bundled dbt retail sample is incomplete: dbt_project.yml was not found.");
      return;
    }
    await this.host.context.workspaceState.update(DBT_SELECTED_KEY, [...dbtRoot, "retail-dbt"].join("/"));
    await writeDbtProfiles(root, (await findDbtProjects()).map(project => project.file));
    await this.host.openBeside(projectFile);
    await this.host.refresh();
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
    const runtimeEnv = this.host.runtime.snapshot().environment;
    try {
      await this.host.services.tools.install(runtimeEnv?.status === "ready" ? runtimeEnv.python : undefined);
      void vscode.window.showInformationMessage("dbt tools installed. Pick a command in the dbt Lab: it runs in a terminal in the project folder.");
    } catch (error) {
      void vscode.window.showErrorMessage(`dbt tools install failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.host.refresh();
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
    if (this.host.services.tools.refresh().status !== "ready") {
      void vscode.window.showWarningMessage("Install the dbt tools first (dbt Lab > Install dbt tools).");
      return;
    }
    const projects = await findDbtProjects();
    const selected = this.host.context.workspaceState.get<string>(DBT_SELECTED_KEY);
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
    await this.host.services.terminal.run(folder, profilesDir, commandLine);
    await this.host.refresh();
  }

  /** Select the mission's project in the dbt Lab and open its TICKET.md. */
  private async openMission(missionId: string): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) return;
    const folder = missionFolder(missionId);
    await this.host.context.workspaceState.update(DBT_SELECTED_KEY, folder);
    const ticket = vscode.Uri.joinPath(root, ...folder.split("/"), "TICKET.md");
    if (await exists(ticket)) await this.host.openBeside(ticket);
  }

  /** The selected dbt project and its folder, or undefined (with a message) when there is none. */
  private async selectedDbtProject(): Promise<{ path: string; folder: vscode.Uri; files: vscode.Uri[] } | undefined> {
    const projects = await findDbtProjects();
    const selected = this.host.context.workspaceState.get<string>(DBT_SELECTED_KEY);
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
    const tools = this.host.services.tools.refresh();
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
    await this.host.services.terminal.run(project.folder, profilesDir, commandLine);
    if (action === "validate") {
      this.dctValidations.set(`${project.path}::${board}`, await dctValidate(this.host.services.tools, project.folder, profilesDir, board));
    }
    await this.host.refresh();
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
    await this.host.services.terminal.serve(project.folder, profilesDir, buildDctCommand({ action: "serve", port }), url);
    await this.host.refresh();
    if (await waitForHttp(url, 90_000)) {
      await vscode.commands.executeCommand("simpleBrowser.show", url);
    } else {
      void vscode.window.showWarningMessage(`dct serve did not answer on ${url} yet: see its terminal.`);
    }
    await this.host.refresh();
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
    const selected = this.host.context.workspaceState.get<string>(DBT_SELECTED_KEY);
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
    await this.host.openBeside(uri);
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
