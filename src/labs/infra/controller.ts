import * as vscode from "vscode";
import type { ModuleId } from "../../modules";
import { missionFolder, type MissionView } from "../../platform/missions";
import type { InfraMessage, InfraViewState, InfraWorldView } from "../../webview/contracts";
import { exists } from "../../workspaceFiles";
import type { WorkbenchStateExtras } from "../../workbenchState";
import type { LabController, MessageHandlers, WorkbenchHost } from "../host";
import type { MissionLabHooks } from "../missions/controller";

/** Infra Lab: one simulated terminal (a Pseudoterminal, no process) per mission folder, and its simulated world. */
export class InfraController implements LabController<InfraMessage> {
  private readonly subscription: vscode.Disposable;

  constructor(private readonly host: WorkbenchHost) {
    this.subscription = host.services.infraLab.onDidRunCommand(() => {
      if (this.host.selectedModule === "infra") void this.host.refresh();
    });
  }

  readonly handlers: MessageHandlers<InfraMessage> = {
    openInfraTerminal: message => this.openInfraTerminal(message.missionId),
    selectInfraFolder: async message => {
      if (/^missions\/[a-z0-9][a-z0-9-]{0,47}$/.test(message.folder)) await this.host.services.infraLab.select(message.folder);
      await this.host.refresh();
    },
    refreshInfraLab: () => this.host.refresh()
  };

  /** Infra missions: the folder's simulated terminal closes before it is rebuilt with a fresh simulated world. */
  readonly missionHooks: MissionLabHooks = {
    restartWarning: missionId =>
      `Start the mission over? missions/${missionId} is moved to .datapass/missions/attic/ (nothing is deleted) and rebuilt as the ticket found it, with a fresh simulated world. Its simulated terminal is closed.`,
    beforeStart: async missionId => {
      if (this.host.services.infraLab.closeIn(missionFolder(missionId))) await new Promise(resolve => setTimeout(resolve, 300));
    },
    open: mission => this.openInfraMission(mission)
  };

  async contribute(selected: ModuleId): Promise<Partial<WorkbenchStateExtras>> {
    return { infra: selected === "infra" ? await this.infraState() : undefined };
  }

  dispose(): void {
    this.subscription.dispose();
  }

  /** Infra Lab: the ticket beside the Workbench and the simulated terminal of the mission folder. */
  private async openInfraMission(mission: MissionView): Promise<void> {
    const ticket = this.host.services.missions.ticketUri(mission);
    if (await exists(ticket)) await this.host.openBeside(ticket);
    await this.openInfraTerminal(mission.id);
  }

  /**
   * The Infra Lab's simulated terminal in a mission folder (the selected one without an id). It is a Pseudoterminal:
   * no process starts; each line goes to the runtime's simulated shell.
   */
  private async openInfraTerminal(missionId?: string): Promise<void> {
    const folder = missionId ? missionFolder(missionId) : this.host.services.infraLab.folder;
    if (!folder) {
      void vscode.window.showWarningMessage("Start an Infra Lab mission first: its simulated terminal opens in the mission folder.");
      return;
    }
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!root || !(await exists(vscode.Uri.joinPath(root, ...folder.split("/"))))) {
      void vscode.window.showWarningMessage(`${folder} does not exist yet: start the mission first.`);
      return;
    }
    await this.host.services.infraLab.open(folder, folder.split("/").pop() ?? folder);
    await this.host.refresh();
  }

  private async infraState(): Promise<InfraViewState> {
    const { missions: service, infraLab: lab } = this.host.services;
    const missions = await service.list("infra");
    const progress = (await service.progress()).missions;
    const folders = missions.filter(mission => progress[mission.id]?.started).map(mission => missionFolder(mission.id));
    const folder = lab.folder && folders.includes(lab.folder) ? lab.folder : folders[0];
    const view: InfraViewState = { folder, folders, missions: { missions, progress } };
    if (folder && this.host.runtime.snapshot().status === "running") {
      try {
        view.world = await this.host.runtime.labs.infra.infraState(folder) as InfraWorldView;
      } catch (error) {
        view.worldError = error instanceof Error ? error.message : String(error);
      }
    }
    return view;
  }
}
