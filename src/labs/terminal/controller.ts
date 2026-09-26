import * as vscode from "vscode";
import type { ModuleId } from "../../modules";
import type { MissionView } from "../../platform/missions";
import { preferredShell, type ShellId } from "../../platform/terminalShells";
import type { TerminalMessage, TerminalViewState } from "../../webview/contracts";
import { exists } from "../../workspaceFiles";
import type { WorkbenchStateExtras } from "../../workbenchState";
import type { LabController, MessageHandlers, WorkbenchHost } from "../host";
import type { MissionLabHooks } from "../missions/controller";

/** Terminal Lab: real bash, PowerShell and Git in a VS Code terminal the learner types in; Datapass types nothing. */
export class TerminalController implements LabController<TerminalMessage> {
  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<TerminalMessage> = {
    selectTerminalShell: async message => {
      await this.host.services.terminalLab.choose(message.shell);
      await this.host.refresh();
    },
    openLabTerminal: message => this.openLabTerminal(message.missionId),
    refreshTerminalLab: async () => {
      await this.host.services.terminalLab.detect(true);
      await this.host.refresh();
    }
  };

  /** Terminal missions: the folder's terminals close before it is rebuilt and reopen after. */
  readonly missionHooks: MissionLabHooks = {
    restartWarning: missionId =>
      `Start the mission over? missions/${missionId} is moved to .datapass/missions/attic/ (nothing is deleted) and rebuilt as the ticket found it. Its terminals are closed.`,
    beforeStart: missionId => this.host.services.terminalLab.release(this.host.services.missions.folderUri(missionId)),
    open: mission => this.openTerminalMission(mission)
  };

  async contribute(selected: ModuleId): Promise<Partial<WorkbenchStateExtras>> {
    return { terminal: selected === "terminal" ? await this.terminalState() : undefined };
  }

  /** Terminal Lab: the ticket beside the Workbench and a terminal in the mission folder, with the learner's shell. */
  private async openTerminalMission(mission: MissionView): Promise<void> {
    const ticket = this.host.services.missions.ticketUri(mission);
    if (await exists(ticket)) await this.host.openBeside(ticket);
    await this.openLabTerminal(mission.id);
  }

  /** A terminal in the mission folder (or the workspace folder), with the chosen shell. Nothing is typed in it. */
  private async openLabTerminal(missionId?: string): Promise<void> {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root) {
      void vscode.window.showWarningMessage("Open a workspace folder first.");
      return;
    }
    const lab = this.host.services.terminalLab;
    const shell: ShellId | undefined = preferredShell((await lab.detect()).shells, lab.chosen);
    if (!shell) {
      void vscode.window.showWarningMessage("No bash or PowerShell was found. Install Git for Windows (Git Bash) or PowerShell 7, then Refresh.");
      return;
    }
    const folder = missionId ? this.host.services.missions.folderUri(missionId) : root;
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

  private async terminalState(): Promise<TerminalViewState> {
    const { terminalLab: lab, missions } = this.host.services;
    const { shells, git } = await lab.detect();
    return {
      shells,
      shell: preferredShell(shells, lab.chosen),
      git,
      missions: { missions: await missions.list("terminal"), progress: (await missions.progress()).missions }
    };
  }
}
