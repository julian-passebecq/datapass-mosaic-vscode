import * as vscode from "vscode";
import type { ModuleId } from "../../modules";
import { missionFolder, type MissionView } from "../../platform/missions";
import type { ApiLabMessage, ApiLabViewState } from "../../webview/contracts";
import { exists } from "../../workspaceFiles";
import type { WorkbenchStateExtras } from "../../workbenchState";
import { saveDirtyUnder, type LabController, type MessageHandlers, type WorkbenchHost } from "../host";
import type { MissionLabHooks } from "../missions/controller";

const ACTIVE = "datapass.apilab.activeMission";
const MISSION_ID = /^[a-z0-9][a-z0-9-]{0,47}$/;

/**
 * API Lab: the learner's ingest.py (real Python, trusted Python only) against a simulated REST API that the runtime
 * serves on its own loopback port with a fictitious per-mission key. Missions use the shared missions panel.
 */
export class ApiLabController implements LabController<ApiLabMessage> {
  constructor(private readonly host: WorkbenchHost) {}

  readonly handlers: MessageHandlers<ApiLabMessage> = {
    runApiIngestion: message => this.host.guarded("API Lab", () => this.run(message.missionId)),
    selectApiMission: async message => {
      if (MISSION_ID.test(message.missionId)) await this.setActive(message.missionId);
      await this.host.refresh();
    },
    copyApiKey: message => this.host.guarded("API Lab", async () => {
      const api = await this.host.runtime.labs.apilab.state(message.missionId);
      if (!api.key) throw new Error("Start the mission first: its API key is made when the mission starts.");
      await vscode.env.clipboard.writeText(api.key);
      void vscode.window.showInformationMessage("The mission's API key is in the clipboard (a fictitious key for the simulated API).");
    }),
    refreshApiLab: () => this.host.refresh()
  };

  /** API Lab missions: Start over restarts the simulated API; the learner's ingest.py is kept. */
  readonly missionHooks: MissionLabHooks = {
    restartWarning: missionId =>
      `Start the mission over? The simulated API restarts at day 1 with a new key, its request log and runs are cleared, and the mission's bronze tables are dropped. Your missions/${missionId}/ingest.py is kept.`,
    beforeStart: async missionId => {
      await this.setActive(missionId);
    },
    open: mission => this.openMission(mission)
  };

  async contribute(selected: ModuleId): Promise<Partial<WorkbenchStateExtras>> {
    return { apilab: selected === "apilab" ? await this.viewState() : undefined };
  }

  private async setActive(missionId: string): Promise<void> {
    await this.host.context.workspaceState.update(ACTIVE, missionId);
  }

  private async run(missionId: string): Promise<void> {
    if (!MISSION_ID.test(missionId)) return;
    await this.setActive(missionId);
    const root = vscode.workspace.workspaceFolders?.[0]?.uri;
    await saveDirtyUnder(root ? vscode.Uri.joinPath(root, ...missionFolder(missionId).split("/")) : undefined);
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: `Running missions/${missionId}/ingest.py…` },
      () => this.host.runtime.labs.apilab.run(missionId));
    if (result.status !== "ok") {
      const last = (result.error ?? "").trim().split(/\r?\n/).pop() ?? "error";
      void vscode.window.showWarningMessage(`ingest.py failed (run ${result.run}): ${last}`);
    }
  }

  /** The ticket beside the Workbench, and the file the learner edits. */
  private async openMission(mission: MissionView): Promise<void> {
    await this.setActive(mission.id);
    const ticket = this.host.services.missions.ticketUri(mission);
    if (await exists(ticket)) await this.host.openBeside(ticket);
    const ingest = vscode.Uri.joinPath(this.host.services.missions.folderUri(mission.id), "ingest.py");
    if (await exists(ingest)) await this.host.openBeside(ingest);
  }

  private async viewState(): Promise<ApiLabViewState> {
    const service = this.host.services.missions;
    const missions = await service.list("apilab");
    const progress = (await service.progress()).missions;
    const stored = this.host.context.workspaceState.get<string>(ACTIVE);
    const started = missions.filter(mission => progress[mission.id]?.started).map(mission => mission.id);
    const active = stored && started.includes(stored) ? stored : started[0];
    const view: ApiLabViewState = { missions: { missions, progress }, active };
    if (active && this.host.runtime.snapshot().status === "running") {
      try {
        view.api = await this.host.runtime.labs.apilab.state(active);
      } catch (error) {
        view.apiError = error instanceof Error ? error.message : String(error);
      }
    }
    return view;
  }
}
